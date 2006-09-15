# Copyright 2006 Canonical Ltd.  All rights reserved.
"""Test native publication workflow for Soyuz. """

from unittest import TestLoader
import os
import shutil
from StringIO import StringIO

from zope.component import getUtility

from canonical.database.constants import UTC_NOW

from canonical.archivepublisher.config import Config
from canonical.archivepublisher.diskpool import (
    DiskPool, Poolifier)
from canonical.archivepublisher.tests.util import FakeLogger

from canonical.launchpad.ftests.harness import (
    LaunchpadZopelessTestCase, LaunchpadZopelessTestSetup)
from canonical.launchpad.database.publishing import (
    SourcePackagePublishingHistory, SecureSourcePackagePublishingHistory)
from canonical.launchpad.interfaces import (
    ILibraryFileAliasSet, IDistributionSet, IPersonSet, ISectionSet,
    IComponentSet, ISourcePackageNameSet, IGPGKeySet)

from canonical.librarian.client import LibrarianClient

from canonical.lp.dbschema import (
    PackagePublishingStatus, PackagePublishingPocket, SourcePackageUrgency)


class TestNativePublishing(LaunchpadZopelessTestCase):

    dbuser = 'lucille'

    def setUp(self):
        """Setup creates a pool dir and setup librarian.

        Also instantiate DiskPool component.
        """
        LaunchpadZopelessTestCase.setUp(self)
        self.library = LibrarianClient()

        self.ubuntutest = getUtility(IDistributionSet)['ubuntutest']
        self.breezy_autotest = self.ubuntutest['breezy-autotest']
        self.config = Config(self.ubuntutest)
        self.config.setupArchiveDirs()

        self.pool_dir = self.config.poolroot
        self.logger = FakeLogger()
        self.disk_pool = DiskPool(Poolifier(), self.pool_dir, self.logger)

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
        component = getUtility(IComponentSet)[component]
        # any person, key, section
        person = getUtility(IPersonSet).getByName('sabdfl')
        signingkey = getUtility(IGPGKeySet).get(1)
        section = getUtility(ISectionSet)['base']

        spr = self.breezy_autotest.createUploadedSourcePackageRelease(
            sourcepackagename=spn,
            maintainer=person,
            creator=person,
            component=component,
            section=section,
            urgency=SourcePackageUrgency.LOW,
            dateuploaded=UTC_NOW,
            version='666',
            builddepends='',
            builddependsindep='',
            architecturehintlist='',
            changelog='',
            dsc='',
            dscsigningkey=signingkey,
            manifest=None
            )

        spr.addFile(alias)

        sspph = SecureSourcePackagePublishingHistory(
            distrorelease=self.breezy_autotest,
            sourcepackagerelease=spr,
            component=spr.component,
            section=spr.section,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            pocket=PackagePublishingPocket.RELEASE,
            embargo=False
            )

        # SPPH and SSPPH IDs are the same, since they are SPPH is a SQLVIEW
        # of SSPPH and other useful attributes.
        return SourcePackagePublishingHistory.get(sspph.id)

    def tearDown(self):
        """Tear down blows the pool dir away and stops librarian."""
        shutil.rmtree(self.config.distroroot)
        LaunchpadZopelessTestCase.tearDown(self)

    def testPublish(self):
        """Test publishOne in normal conditions (new file)."""
        pub_source = self.getPubSource(
            "foo", "main", "foo.dsc", filecontent='Hello world')
        pub_source.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()

        self.assertEqual(pub_source.status, PackagePublishingStatus.PUBLISHED)
        foo_name = "%s/main/f/foo/foo.dsc" % self.pool_dir
        self.assertEqual(open(foo_name).read().strip(), 'Hello world')


    def testPublishingOverwriteFileInPool(self):
        """Test if publishOne refuses to overwrite a file in pool.

        Check if it also keeps the original file content.
        It's done by publishing 'foo' by-hand and ensuring it
        has a special content, then publish 'foo' again, via publisher,
        and finally check one of the 'foo' files content.
        """
        foo_path = os.path.join(self.pool_dir, 'main', 'f', 'foo')
        os.makedirs(foo_path)
        foo_dsc_path = os.path.join(foo_path, 'foo.dsc')
        foo_dsc = open(foo_dsc_path, 'w')
        foo_dsc.write('Hello world')
        foo_dsc.close()

        self.disk_pool.scan()
        pub_source = self.getPubSource(
            "foo", "main", "foo.dsc", filecontent="Something")
        pub_source.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        self.assertEqual(
            pub_source.status,PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_dsc_path).read().strip(), 'Hello world')

    def testPublishingDiferentContents(self):
        """Test if publishOne refuses to overwrite its own publication."""
        pub_source = self.getPubSource(
            "foo", "main", "foo.dsc", filecontent='foo is happy')
        pub_source.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()

        foo_name = "%s/main/f/foo/foo.dsc" % self.pool_dir
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

        # try to publish 'foo' again with a different content, it
        # raises internally and keeps the files with the original
        # content.
        pub_source2 = self.getPubSource("foo", "main", "foo.dsc",
                                        'foo is depressing')
        pub_source2.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

    def testPublishingAlreadyInPool(self):
        """Test if publishOne works if file is already in Pool.

        It should identify that the file has the same content and
        mark it as PUBLISHED.
        """
        pub_source = self.getPubSource(
            "bar", "main", "bar.dsc", filecontent='bar is good')
        pub_source.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        bar_name = "%s/main/b/bar/bar.dsc" % self.pool_dir
        self.assertEqual(open(bar_name).read().strip(), 'bar is good')
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)

        pub_source2 = self.getPubSource(
            "bar", "main", "bar.dsc", filecontent='bar is good')
        pub_source2.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PUBLISHED)

    def testPublishingSymlink(self):
        """Test if publishOne moving publication between components.

        After check if the pool file contents as the same, it should
        create a symlink in the new pointing to the original file.
        """
        content = 'am I a file or a symbolic link ?'
        # publish sim.dsc in main and re-publish in universe
        pub_source = self.getPubSource(
            "sim", "main", "sim.dsc", filecontent=content)
        pub_source2 = self.getPubSource(
            "sim", "universe", "sim.dsc", filecontent=content)
        pub_source.publish(self.disk_pool, self.logger)
        pub_source2.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PUBLISHED)

        # check the resulted symbolic link
        sim_universe = "%s/universe/s/sim/sim.dsc" % self.pool_dir
        self.assertEqual(
            os.readlink(sim_universe), '../../../main/s/sim/sim.dsc')

        # if the contests don't match it raises.
        pub_source3 = self.getPubSource(
            "sim", "restricted", "sim.dsc", filecontent='It is all my fault')
        pub_source3.publish(self.disk_pool, self.logger)
        LaunchpadZopelessTestSetup.txn.commit()
        self.assertEqual(
            pub_source3.status, PackagePublishingStatus.PENDING)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
