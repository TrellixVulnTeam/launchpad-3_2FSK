#!/usr/bin/env python

# Copyright 2004 Canonical Ltd.  All rights reserved.
#

import unittest
import sys
import os
import shutil
from StringIO import StringIO

from zope.component import getUtility

from canonical.database.constants import UTC_NOW

from canonical.archivepublisher.config import Config
from canonical.archivepublisher.pool import (
    DiskPool, Poolifier)
from canonical.archivepublisher.tests.util import (
    FakeSourcePublishing, FakeBinaryPublishing, FakeLogger)

from canonical.functional import ZopelessLayer

from canonical.launchpad.ftests.harness import (
    LaunchpadZopelessTestCase, LaunchpadZopelessTestSetup)
from canonical.launchpad.database.publishing import (
    SourcePackagePublishing, SecureSourcePackagePublishingHistory,
    BinaryPackagePublishing, SecureBinaryPackagePublishingHistory)
from canonical.launchpad.interfaces import (
    ILibraryFileAliasSet, IDistributionSet, IPersonSet, ISectionSet,
    IComponentSet, ISourcePackageNameSet)

from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.librarian.client import LibrarianClient

from canonical.lp.dbschema import (
    PackagePublishingStatus, PackagePublishingPocket, SourcePackageUrgency)


class TestPublisher(LaunchpadZopelessTestCase):
    layer = ZopelessLayer
    dbuser = 'lucille'

    # Setup creates a pool dir...
    def setUp(self):
        LaunchpadZopelessTestCase.setUp(self)
        self.library = LibrarianClient()
        self._distribution = getUtility(IDistributionSet)['ubuntutest']
        self._distrorelease = self._distribution['breezy-autotest']
        self._config = Config(self._distribution)
        self._config.setupArchiveDirs()

        self._pooldir = self._config.poolroot
        self._overdir = self._config.overrideroot
        self._listdir = self._config.overrideroot
        self._logger = FakeLogger()
        self._dp = DiskPool(Poolifier(), self._pooldir, self._logger)

        self.librarian = LibrarianTestSetup()
        self.librarian.setUp()

    def addMockFile(self, filename, content):
        """Add a mock file in Librarian.

        Returns a ILibraryFileAlias corresponding to the file uploaded.
        """
        alias_id = self.library.addFile(
            filename, len(content), StringIO(content), 'application/text')
        LaunchpadZopelessTestSetup.txn.commit()
        return getUtility(ILibraryFileAliasSet)[alias_id]

    def getPubSource(self, sourcename, component, filename,
                     filecontent="I do not care about sources."):
        """Return a mock source publishing record."""

        alias = self.addMockFile(filename, filecontent)

        spn = getUtility(ISourcePackageNameSet).getOrCreateByName(sourcename)
        section = getUtility(ISectionSet)['base']
        component = getUtility(IComponentSet)['main']
        person = getUtility(IPersonSet).get(1)

        spr = self._distrorelease.createUploadedSourcePackageRelease(
            sourcepackagename=spn.id,
            maintainer=person.id,
            creator=person.id,
            component=component.id,
            section=section.id,
            urgency=SourcePackageUrgency.LOW,
            dateuploaded=UTC_NOW,
            version='666',
            builddepends='',
            builddependsindep='',
            architecturehintlist='',
            changelog='',
            dsc='',
            dscsigningkey=1,
            manifest=None
            )

        spr.addFile(alias)

        sspph = SecureSourcePackagePublishingHistory(
            distrorelease=self._distrorelease.id,
            sourcepackagerelease=spr.id,
            component=spr.component.id,
            section=spr.section.id,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            pocket=PackagePublishingPocket.RELEASE,
            embargo=False
            )

        return SourcePackagePublishing.get(sspph.id)

    def getFakePubSource(self, sourcename, component, leafname,
                         section='', dr='',
                         filecontent="I do not care about sources."):
        """Return a mock source publishing record."""
        alias = self.addMockFile(leafname, filecontent)
        return FakeSourcePublishing(sourcename, component, leafname, alias,
                                    section, dr)

    def getFakePubBinary(self, binaryname, component, filename,
                         section='', dr='', priority=0, archtag='',
                         filecontent="I do not care about binaries."):
        """Return a mock binary publishing record."""
        alias = self.addMockFile(filename, filecontent)
        return FakeBinaryPublishing(binaryname, component, filename, alias,
                                    section, dr, priority, archtag)

    # Tear down blows the pool dir away...
    def tearDown(self):
        self.librarian.tearDown()
        LaunchpadZopelessTestCase.tearDown(self)
        shutil.rmtree(self._config.distroroot)

    def testInstantiate(self):
        """canonical.archivepublisher.Publisher should be instantiatable"""
        from canonical.archivepublisher import Publisher
        Publisher(self._logger, self._config, self._dp, self._distribution)

    def testPathFor(self):
        """canonical.archivepublisher.Publisher._pathfor should work"""
        from canonical.archivepublisher import Publisher
        p = Publisher(self._logger, self._config, self._dp, self._distribution)
        cases = (
            ("main", "foo", None, "%s/main/f/foo" % self._config.poolroot),
            ("main", "foo", "foo.deb", "%s/main/f/foo/foo.deb"
             % self._config.poolroot)
            )
        for case in cases:
            self.assertEqual( case[3], p._pathfor(case[0], case[1], case[2]) )

    def testPublish(self):
        """Test publishOne in normal conditions (new file)."""
        from canonical.archivepublisher import Publisher
        pub_source = self.getPubSource( "foo", "main", "foo.dsc",
                                        filecontent='Hello world')
        pub_source.publish(self._dp, self._logger)
        self.assertEqual(pub_source.status, PackagePublishingStatus.PUBLISHED)
        foo_name = "%s/main/f/foo/foo.dsc" % self._pooldir
        self.assertEqual(open(foo_name).read().strip(), 'Hello world')


    def testPublishingOverwriteFileInPool(self):
        """Test if publishOne refuses to overwrite a file in pool.

        Check if it also keeps the original file content.
        """
        from canonical.archivepublisher import Publisher

        # publish 'foo' by-hand and ensure it has a special content
        foo_name = "%s/main/f/foo/foo.dsc" % self._pooldir
        os.mkdir(os.path.join(self._pooldir, 'main'))
        os.mkdir(os.path.join(self._pooldir, 'main', 'f'))
        os.mkdir(os.path.join(self._pooldir, 'main', 'f', 'foo'))
        open(foo_name, 'w').write('Hello world')

        # try to publish 'foo' again, via publisher, and check the content
        self._dp.scan()
        pub_source = self.getPubSource("foo", "main", "foo.dsc",
                                       filecontent="Something")
        pub_source.publish(self._dp, self._logger)
        self.assertEqual(pub_source.status,
                         PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_name).read().strip(), 'Hello world')

    def testPublishingDiferentContents(self):
        """Test if publishOne refuses to overwrite its own publication."""
        from canonical.archivepublisher import Publisher

        pub_source = self.getPubSource("foo", "main", "foo.dsc",
                                           filecontent='foo is happy')
        pub_source.publish(self._dp, self._logger)

        foo_name = "%s/main/f/foo/foo.dsc" % self._pooldir
        self.assertEqual(pub_source.status,
                         PackagePublishingStatus.PUBLISHED)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

        # try to publish 'foo' again with a different content, it
        # raises and keep the files with the original content.
        pub_source2 = self.getPubSource("foo", "main", "foo.dsc",
                                            'foo is depressing')
        pub_source2.publish(self._dp, self._logger)
        self.assertEqual(pub_source2.status,
                         PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

    def testPublishingAlreadyInPool(self):
        """Test if publishOne works if file is already in Pool.

        It should identify that the file has the same content and
        mark it as PUBLISHED.
        """
        from canonical.archivepublisher import Publisher

        pub_source = self.getPubSource("bar", "main", "bar.dsc",
                                           filecontent='bar is good')
        pub_source.publish(self._dp, self._logger)
        bar_name = "%s/main/b/bar/bar.dsc" % self._pooldir
        self.assertEqual(open(bar_name).read().strip(), 'bar is good')
        self.assertEqual(pub_source.status,
                         PackagePublishingStatus.PUBLISHED)

        pub_source2 = self.getPubSource("bar", "main", "bar.dsc",
                                            filecontent='bar is good')
        pub_source2.publish(self._dp, self._logger)
        self.assertEqual(pub_source2.status,
                         PackagePublishingStatus.PUBLISHED)

    def testPublishingSymlink(self):
        """Test if publishOne moving publication between components.

        After check if the pool file contents as the same, it should
        create a symlink in the new pointing to the original file.
        """
        from canonical.archivepublisher import Publisher

        content = 'am I a file or a symbolic link ?'
        # publish sim.dsc in main and re-publish in universe
        pub_source = self.getPubSource( "sim", "main", "sim.dsc",
                                            filecontent=content)
        pub_source2 = self.getPubSource( "sim", "universe", "sim.dsc",
                                            filecontent=content)
        pub_source.publish(self._dp, self._logger)
        pub_source2.publish(self._dp, self._logger)
        self.assertEqual(pub_source.status,
                         PackagePublishingStatus.PUBLISHED)
        self.assertEqual(pub_source2.status,
                         PackagePublishingStatus.PUBLISHED)

        # check the resulted symbolic link
        sim_universe = "%s/universe/s/sim/sim.dsc" % self._pooldir
        self.assertEqual(os.readlink(sim_universe),
                         '../../../main/s/sim/sim.dsc')

        # if the contests don't match it raises.
        pub_source3 = self.getPubSource("sim", "restricted", "sim.dsc",
                                            filecontent='It is all my fault')
        pub_source3.publish(self._dp, self._logger)
        self.assertEqual(pub_source3.sourcepackagepublishing.status,
                         PackagePublishingStatus.PENDING)

    def testPublishOverrides(self):
        """canonical.archivepublisher.Publisher.publishOverrides should work"""
        from canonical.archivepublisher import Publisher
        p = Publisher(self._logger, self._config, self._dp, self._distribution)
        src = [self.getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "warty")]
        bin = [self.getFakePubBinary(
            "foo", "main", "foo.deb", "misc", "warty", 10, "i386")]
        p.publishOverrides(src, bin)
        # Check that the files exist
        os.stat("%s/override.warty.main" % self._overdir)
        os.stat("%s/override.warty.main.src" % self._overdir)

    def testPublishFileLists(self):
        """canonical.archivepublisher.Publisher.publishFileLists should work"""
        from canonical.archivepublisher import Publisher
        p = Publisher(self._logger, self._config, self._dp, self._distribution)
        src = [self.getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "warty")]
        bin = [self.getFakePubBinary(
            "foo", "main", "foo.deb", "misc", "warty", 10, "i386")]
        p.publishFileLists(src, bin)
        os.stat("%s/warty_main_source" % self._listdir)
        os.stat("%s/warty_main_binary-i386" % self._listdir)

    def testGenerateConfig(self):
        """Generate apt-ftparchive config"""
        from canonical.archivepublisher import Publisher
        p = Publisher(self._logger, self._config, self._dp, self._distribution)
        p.generateAptFTPConfig()
        # XXX: dsilvers 2004-11-15
        # For now, all we can sensibly do is assert that the config was created
        # In future we may parse it and check values make sense.

def test_suite():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTest(loader.loadTestsFromTestCase(TestPublisher))
    return suite

def main():
    suite = test_suite()
    runner = unittest.TextTestRunner(verbosity=2)
    if not runner.run(suite).wasSuccessful():
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())

