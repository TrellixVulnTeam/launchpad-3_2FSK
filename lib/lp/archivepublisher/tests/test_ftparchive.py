# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for ftparchive.py"""

__metaclass__ = type

import os
import shutil
import difflib
from tempfile import mkdtemp
import unittest

from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.testing import LaunchpadZopelessLayer
from lp.archivepublisher.config import Config
from lp.archivepublisher.diskpool import DiskPool
from lp.archivepublisher.ftparchive import FTPArchiveHandler, f_touch
from lp.archivepublisher.publishing import Publisher
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.pocket import PackagePublishingPocket


def sanitize_feisty_apt_ftparchive_output(text):
    # See XXX BarryWarsaw 2007-05-18 bug=116048:
    #
    # This function filters feisty's apt-ftparchive output to look more like
    # dapper's output.  Specifically, it removes any lines that start with
    # SHA1: or SHA256: since dapper's version doesn't have these lines.  Start
    # by splitting the original text by lines, keeping the original line
    # endings.
    lines = text.splitlines(True)
    return ''.join(line for line in lines
                   if not (line.startswith('SHA256:') or
                           line.startswith('SHA1:')))


class SamplePublisher:
    """Publisher emulation test class."""
    def __init__(self, archive):
        self.archive = archive


class FakeSelectResult:
    """Receive a list and emulate a SelectResult object."""

    def __init__(self, result):
        self._result = result

    def __iter__(self):
        return iter(self._result)

    def count(self):
        return len(self._result)

    def __getslice__(self, i, j):
        return self._result[i:j]


class TestFTPArchive(unittest.TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.layer.switchDbUser(config.archivepublisher.dbuser)

        self._distribution = getUtility(IDistributionSet)['ubuntutest']
        self._archive = self._distribution.main_archive
        self._config = Config(self._distribution)
        self._config.setupArchiveDirs()
        self._sampledir = os.path.join(
            config.root, "lib", "lp", "archivepublisher", "tests",
            "apt-data")
        self._distsdir = self._config.distsroot
        self._confdir = self._config.miscroot
        self._pooldir = self._config.poolroot
        self._overdir = self._config.overrideroot
        self._listdir = self._config.overrideroot
        self._tempdir = self._config.temproot
        self._logger = QuietFakeLogger()
        self._dp = DiskPool(self._pooldir, self._tempdir, self._logger)
        self._publisher = SamplePublisher(self._archive)

    def tearDown(self):
        shutil.rmtree(self._config.distroroot)

    def _verifyFile(self, filename, directory, output_filter=None):
        """Compare byte-to-byte the given file and the respective sample.

        It's a poor way of testing files generated by apt-ftparchive.
        """
        result_path = os.path.join(directory, filename)
        result_text = open(result_path).read()
        if output_filter is not None:
            result_text = output_filter(result_text)
        sample_path = os.path.join(self._sampledir, filename)
        sample_text = open(sample_path).read()
        # When the comparison between the sample text and the generated text
        # differ, just printing the strings will be less than optimal.  Use
        # difflib to get a line-by-line comparison that makes it much more
        # immediately obvious what the differences are.
        diff_lines = difflib.ndiff(
            sample_text.splitlines(), result_text.splitlines())
        self.assertEqual(result_text, sample_text, '\n'.join(diff_lines))

    def _addRepositoryFile(self, component, sourcename, leafname):
        """Create a repository file."""
        fullpath = self._dp.pathFor(component, sourcename, leafname)
        dirname = os.path.dirname(fullpath)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        leaf = os.path.join(self._sampledir, leafname)
        leafcontent = file(leaf).read()
        file(fullpath, "w").write(leafcontent)

    def _setUpFTPArchiveHandler(self):
        fa = FTPArchiveHandler(
            self._logger, self._config, self._dp, self._distribution,
            self._publisher)
        return fa

    def test_getSourcesForOverrides(self):
        # getSourcesForOverrides returns a list of tuples containing:
        # (sourcename, suite, component, section)

        # Reconfigure FTPArchiveHandler to retrieve sampledata overrides.
        fa = self._setUpFTPArchiveHandler()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        fa.publisher.archive = hoary.main_archive

        published_sources = fa.getSourcesForOverrides(
            hoary, PackagePublishingPocket.RELEASE)

        # For the above query, we are depending on the sample data to
        # contain seven rows of SourcePackagePublishghistory data.
        expectedSources = [
            ('linux-source-2.6.15', 'hoary', 'main', 'base'),
            ('libstdc++', 'hoary', 'main', 'base'),
            ('cnews', 'hoary', 'universe', 'base'),
            ('alsa-utils', 'hoary', 'main', 'base'),
            ('pmount', 'hoary', 'main', 'editors'),
            ('netapplet', 'hoary', 'main', 'web'),
            ('evolution', 'hoary', 'main', 'editors'),
            ]
        self.assertEqual(expectedSources, list(published_sources))

    def test_getBinariesForOverrides(self):
        # getBinariesForOverrides returns a list of tuples containing:
        # (sourcename, suite, component, section, priority)

        # Reconfigure FTPArchiveHandler to retrieve sampledata overrides.
        fa = self._setUpFTPArchiveHandler()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        fa.publisher.archive = hoary.main_archive

        published_binaries = fa.getBinariesForOverrides(
            hoary, PackagePublishingPocket.RELEASE)
        expectedBinaries = [
            ('pmount', 'hoary', 'main', 'base', 'extra'),
            ('pmount', 'hoary', 'universe', 'editors', 'important')
            ]
        self.assertEqual(expectedBinaries, list(published_binaries))

    def test_getBinariesForOverrides_with_no_architectures(self):
        # getBinariesForOverrides() copes with uninitiazed distroseries
        # (no architectures), returning an empty ResultSet.
        fa = self._setUpFTPArchiveHandler()

        breezy_autotest = self._distribution.getSeries('breezy-autotest')
        self.assertEquals([], list(breezy_autotest.architectures))

        published_binaries = fa.getBinariesForOverrides(
            breezy_autotest, PackagePublishingPocket.RELEASE)
        self.assertEqual([], list(published_binaries))

    def test_publishOverrides(self):
        # publishOverrides write the expected files on disk.
        fa = self._setUpFTPArchiveHandler()

        source_overrides = FakeSelectResult(
            [('foo', 'hoary-test', 'main', 'misc')])
        binary_overrides = FakeSelectResult(
            [('foo', 'hoary-test', 'main', 'misc', 'extra')])
        fa.publishOverrides(source_overrides, binary_overrides)

        # Check that the overrides lists generated by LP exist and have the
        # expected contents.
        self._verifyFile("override.hoary-test.main", self._overdir)
        self._verifyFile("override.hoary-test.main.src", self._overdir)
        self._verifyFile("override.hoary-test.extra.main", self._overdir)

    def test_getSourceFiles(self):
        # getSourceFiles returns a list of tuples containing:
        # (sourcename, suite, filename, component)

        # Reconfigure FTPArchiveHandler to retrieve sampledata records.
        fa = self._setUpFTPArchiveHandler()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        fa.distro = ubuntu
        fa.publisher.archive = hoary.main_archive

        sources_files = fa.getSourceFiles(
            hoary, PackagePublishingPocket.RELEASE)
        expected_files = [
            ('alsa-utils', 'hoary', 'alsa-utils_1.0.9a-4ubuntu1.dsc', 'main'),
            ('evolution', 'hoary', 'evolution-1.0.tar.gz', 'main'),
            ('netapplet', 'hoary', 'netapplet_1.0.0.orig.tar.gz', 'main'),
            ]
        self.assertEqual(expected_files, list(sources_files))

    def test_getBinaryFiles(self):
        # getBinaryFiles returns a list of tuples containing:
        # (sourcename, suite, filename, component, architecture)

        # Reconfigure FTPArchiveHandler to retrieve sampledata records.
        fa = self._setUpFTPArchiveHandler()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        fa.distro = ubuntu
        fa.publisher.archive = hoary.main_archive

        binary_files = fa.getBinaryFiles(
            hoary, PackagePublishingPocket.RELEASE)
        expected_files = [
            ('pmount', 'hoary', 'pmount_1.9-1_all.deb', 'main', 'binary-hppa')
            ]
        self.assertEqual(expected_files, list(binary_files))

    def test_publishFileLists(self):
        # publishFileLists writes the expected files on disk.
        fa = self._setUpFTPArchiveHandler()

        source_files = FakeSelectResult(
            [('foo', 'hoary-test',  'foo.dsc', 'main')])
        binary_files = FakeSelectResult(
            [('foo', 'hoary-test', 'foo.deb', 'main', 'binary-i386')])
        fa.publishFileLists(source_files, binary_files)

        # Check that the file lists generated by LP exist and have the
        # expected contents.
        self._verifyFile("hoary-test_main_source", self._listdir)
        self._verifyFile("hoary-test_main_binary-i386", self._listdir)

    def test_generateConfig(self):
        # Generate apt-ftparchive configuration file and run it.

        # Setup FTPArchiveHandler with a real Publisher for Ubuntutest.
        publisher = Publisher(
            self._logger, self._config, self._dp, self._archive)
        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                               self._distribution, publisher)
        fa.createEmptyPocketRequests(fullpublish=True)

        # Calculate overrides.
        source_overrides = FakeSelectResult(
            [('foo', 'hoary-test', 'main', 'misc'),])
        binary_overrides = FakeSelectResult(
            [('foo', 'hoary-test', 'main', 'misc', 'extra')])
        fa.publishOverrides(source_overrides, binary_overrides)

        # Calculate filelists.
        source_files = FakeSelectResult(
            [('foo', 'hoary-test',  'foo.dsc', 'main')])
        binary_files = FakeSelectResult(
            [('foo', 'hoary-test', 'foo.deb', 'main', 'binary-i386')])
        fa.publishFileLists(source_files, binary_files)

        # Add mentioned files in the repository pool/.
        self._addRepositoryFile('main', 'foo', 'foo.dsc')
        self._addRepositoryFile('main', 'foo', 'foo.deb')

        # XXX cprov 2007-03-21: Relying on byte-to-byte configuration file
        # comparing is weak. We should improve this methodology to avoid
        # wasting time on test failures due to irrelevant format changes.
        apt_conf = fa.generateConfig(fullpublish=True)
        self._verifyFile("apt.conf", self._confdir)

        # XXX cprov 2007-03-21: This is an extra problem. Running a-f on
        # developer machines is wasteful. We need to find a away to split
        # those kind of tests and avoid to run it when performing 'make
        # check'. Although they should remain active in PQM to avoid possible
        # regressions.
        assert fa.runApt(apt_conf) == 0
        # XXX barry 2007-05-18 bug=116048:
        # This is a hack to make this test pass on dapper and feisty.
        # Feisty's apt-ftparchive outputs SHA256 and MD5 hash
        # lines which don't appear in dapper's version.  We can't change the
        # sample data to include these lines because that would break pqm,
        # which runs dapper.  But without those lines, a straight byte
        # comparison will fail on developers' feisty boxes.  The hack then is
        # to filter these lines out of the output from apt-ftparchive.
        # Feisty's apt-ftparchive also includes an extra blank line. :(
        self._verifyFile("Packages",
            os.path.join(self._distsdir, "hoary-test", "main", "binary-i386"),
                         sanitize_feisty_apt_ftparchive_output)
        self._verifyFile("Sources",
            os.path.join(self._distsdir, "hoary-test", "main", "source"))

        # XXX cprov 2007-03-21: see above, byte-to-byte configuration
        # comparing is weak.
        # Test that a publisher run now will generate an empty apt
        # config and nothing else.
        apt_conf = fa.generateConfig()
        assert len(file(apt_conf).readlines()) == 23

        # XXX cprov 2007-03-21: see above, do not run a-f on dev machines.
        assert fa.runApt(apt_conf) == 0

    def test_generateConfig_empty_and_careful(self):
        # Generate apt-ftparchive config for an specific empty suite.
        #
        # By passing 'careful_apt' option associated with 'allowed_suite'
        # we can publish only a specific group of the suites even if they
        # are still empty. It makes APT clients happier during development
        # cycle.
        #
        # This test should check:
        #
        #  * if apt.conf was generated correctly.
        #  * a-f runs based on this config without any errors
        #  * a-f *only* creates the wanted archive indexes.
        allowed_suites = set()
        allowed_suites.add(('hoary-test', PackagePublishingPocket.UPDATES))

        publisher = Publisher(
            self._logger, self._config, self._dp,
            allowed_suites=allowed_suites, archive=self._archive)

        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                               self._distribution, publisher)

        fa.createEmptyPocketRequests(fullpublish=True)

        # XXX cprov 2007-03-21: see above, byte-to-byte configuration
        # comparing is weak.
        apt_conf = fa.generateConfig(fullpublish=True)
        self.assertTrue(os.path.exists(apt_conf))
        apt_conf_content = file(apt_conf).read()
        sample_content = file(
            os.path.join(
            self._sampledir, 'apt_conf_single_empty_suite_test')).read()
        self.assertEqual(apt_conf_content, sample_content)

        # XXX cprov 2007-03-21: see above, do not run a-f on dev machines.
        self.assertEqual(fa.runApt(apt_conf), 0)
        self.assertTrue(os.path.exists(
            os.path.join(self._distsdir, "hoary-test-updates", "main",
                         "binary-i386", "Packages")))
        self.assertTrue(os.path.exists(
            os.path.join(self._distsdir, "hoary-test-updates", "main",
                         "source", "Sources")))

        self.assertFalse(os.path.exists(
            os.path.join(self._distsdir, "hoary-test", "main",
                         "binary-i386", "Packages")))
        self.assertFalse(os.path.exists(
            os.path.join(self._distsdir, "hoary-test", "main",
                         "source", "Sources")))


class TestFTouch(unittest.TestCase):
    """Tests for f_touch function."""

    def setUp(self):
        self.test_folder = mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_folder)

    def test_f_touch_new_file(self):
        # Test f_touch correctly creates a new file.
        f_touch(self.test_folder, "file_to_touch")
        self.assertTrue(os.path.exists("%s/file_to_touch" % self.test_folder))

    def test_f_touch_existing_file(self):
        # Test f_touch truncates existing files.
        f = open("%s/file_to_truncate" % self.test_folder, "w")
        test_contents = "I'm some test contents"
        f.write(test_contents)
        f.close()

        f_touch(self.test_folder, "file_to_leave_alone")

        f = open("%s/file_to_leave_alone" % self.test_folder, "r")
        contents = f.read()
        f.close()

        self.assertEqual("", contents)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

