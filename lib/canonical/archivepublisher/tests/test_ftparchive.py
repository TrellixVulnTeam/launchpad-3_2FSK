# Copyright 2004 Canonical Ltd.  All rights reserved.
#

"""Tests for ftparchive.py"""

__metaclass__ = type

import os
import shutil
import unittest

from zope.component import getUtility

from canonical.config import config
from canonical.archivepublisher.config import Config
from canonical.archivepublisher.diskpool import (
    DiskPool, Poolifier)
from canonical.archivepublisher.tests.util import (
    FakeSourcePublishing, FakeSourceFilePublishing,
    FakeBinaryPublishing, FakeBinaryFilePublishing, FakeLogger)
from canonical.launchpad.ftests.harness import (
    LaunchpadZopelessTestCase, LaunchpadZopelessTestSetup)
from canonical.launchpad.interfaces import (
    ILibraryFileAliasSet, IDistributionSet)
from canonical.librarian.client import LibrarianClient


class TestFTPArchive(LaunchpadZopelessTestCase):
    dbuser = 'lucille'

    def setUp(self):
        LaunchpadZopelessTestCase.setUp(self)
        self.library = LibrarianClient()
        self._distribution = getUtility(IDistributionSet)['ubuntutest']
        self._config = Config(self._distribution)
        self._config.setupArchiveDirs()

        self._sampledir = os.path.join(config.root, "lib", "canonical",
                                       "archivepublisher", "tests", "apt-data")
        self._distsdir = self._config.distsroot
        self._confdir = self._config.miscroot
        self._pooldir = self._config.poolroot
        self._overdir = self._config.overrideroot
        self._listdir = self._config.overrideroot
        self._logger = FakeLogger()
        self._dp = DiskPool(Poolifier(), self._pooldir, self._logger)

    def tearDown(self):
        LaunchpadZopelessTestCase.tearDown(self)
        shutil.rmtree(self._config.distroroot)

    def _verifyFile(self, filename, directory):
        fullpath = "%s/%s" % (directory, filename)
        assert os.stat(fullpath)
        text = file(fullpath).read()
        assert text
        assert text == file("%s/%s" % (self._sampledir, filename)).read()

    def _addMockFile(self, component, sourcename, leafname):
        """Add a mock file in Librarian.

        Returns a ILibraryFileAlias corresponding to the file uploaded.
        """
        fullpath = self._dp.pathFor(component, sourcename, leafname)
        dirname = os.path.dirname(fullpath)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        leaf = os.path.join(self._sampledir, leafname)
        leafcontent = file(leaf).read()
        file(fullpath, "w").write(leafcontent)

        alias_id = self.library.addFile(
            leafname, len(leafcontent), file(leaf), 'application/text')
        LaunchpadZopelessTestSetup.txn.commit()
        return getUtility(ILibraryFileAliasSet)[alias_id]

    def _getFakePubSource(self, sourcename, component, leafname, section, dr):
        """Return a mock source publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeSourcePublishing(sourcename, component, alias, section, dr)

    def _getFakePubBinary(self, binaryname, sourcename, component, leafname,
                         section, dr, priority, archtag):
        """Return a mock binary publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeBinaryPublishing(binaryname, sourcename, component, alias,
                                    section, dr, priority, archtag)

    def _getFakePubSourceFile(self, sourcename, component, leafname,
                              section, dr):
        """Return a mock source publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeSourceFilePublishing(sourcename, component, leafname,
                                        alias, section, dr)

    def _getFakePubBinaryFile(self, binaryname, sourcename, component,
                              leafname, section, dr, priority, archtag,):
        """Return a mock binary publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        # Yes, it's the sourcename. There's nothing much related to
        # binary packages in BinaryPackageFilePublishing apart from the
        # binarypackagepublishing link it has.
        return FakeBinaryFilePublishing(sourcename, component, leafname,
                                        alias, section, dr, priority, archtag)

    def testInstantiate(self):
        """canonical.archivepublisher.FTPArchive should be instantiatable"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        FTPArchiveHandler(self._logger, self._config, self._dp,
                   self._distribution, set())

    def testPublishOverrides(self):
        """canonical.archivepublisher.Publisher.publishOverrides should work"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                        self._distribution, set())
        src = [self._getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinary(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", 10, "i386")]
        fa.publishOverrides(src, bin)
        # Check that the files exist
        self._verifyFile("override.hoary-test.main", self._overdir)
        self._verifyFile("override.hoary-test.main.src", self._overdir)
        self._verifyFile("override.hoary-test.extra.main", self._overdir)

    def testPublishFileLists(self):
        """canonical.archivepublisher.Publisher.publishFileLists should work"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                        self._distribution, set())
        src = [self._getFakePubSourceFile(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinaryFile(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", 10, "i386")]
        fa.publishFileLists(src, bin)
        self._verifyFile("hoary-test_main_source", self._listdir)
        self._verifyFile("hoary-test_main_binary-i386", self._listdir)

    def testGenerateConfig(self):
        """Generate apt-ftparchive config"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        from canonical.archivepublisher.publishing import Publisher
        publisher = Publisher(self._logger, self._config, self._dp,
                              self._distribution)
        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                               self._distribution, publisher)
        src = [self._getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinary(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", 10, "i386")]
        fa.createEmptyPocketRequests()
        fa.publishOverrides(src, bin)
        src = [self._getFakePubSourceFile(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinaryFile(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", 10, "i386")]
        fa.publishFileLists(src, bin)
        apt_conf = fa.generateConfig(fullpublish=True)
        self._verifyFile("apt.conf", self._confdir)
        assert fa.runApt(apt_conf) == 0

        self._verifyFile("Packages",
            os.path.join(self._distsdir, "hoary-test", "main", "binary-i386"))
        self._verifyFile("Sources",
            os.path.join(self._distsdir, "hoary-test", "main", "source"))

        # Test that a publisher run now will generate an empty apt
        # config and nothing else.
        apt_conf = fa.generateConfig()
        assert len(file(apt_conf).readlines()) == 23
        assert fa.runApt(apt_conf) == 0

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

