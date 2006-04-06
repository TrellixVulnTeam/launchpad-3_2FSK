#!/usr/bin/env python
# Copyright 2006 Canonical Ltd.  All rights reserved.
# Author: David Allouche <david@allouche.net>

"""Test cases for baz2bzr, bzr import and publishing."""

__metaclass__ = type

import sys
import os
import pty
import resource
import shutil
from StringIO import StringIO
from subprocess import Popen, call, STDOUT, PIPE
import unittest

import pybaz
import bzrlib.branch

import transaction
from zope.component import getUtility
from canonical.database.sqlbase import flush_database_caches
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IProductSet)

from importd import baz2bzr
from importd.tests import TestUtil
from importd.tests.helpers import (
    SandboxHelper, ZopelessUtilitiesHelper)


class ProductSeriesHelper:
    """Helper for tests that use the testing ProductSeries."""

    def setUp(self):
        self.utilities_helper = ZopelessUtilitiesHelper()
        self.utilities_helper.setUp()
        self.version = pybaz.Version('importd@example.com/test--branch--0')
        self.series = None

    def tearDown(self):
        self.utilities_helper.tearDown()

    def setUpTestSeries(self):
        """Create a sample ProductSeries with targetarch* details."""
        assert self.series is None
        product = getUtility(IProductSet)['gnome-terminal']
        series = product.newSeries('importd-test', displayname='', summary='')
        self.series = series
        parser = pybaz.NameParser(self.version.fullname)
        series.targetarcharchive = self.version.archive.name
        series.targetarchcategory = self.version.category.nonarch
        series.targetarchbranch = parser.get_branch()
        series.targetarchversion = parser.get_version()
        transaction.commit()

    def setUpNonarchSeries(self):
        """Create a sample ProductSeries without targetarch* details."""
        assert self.series is None
        product = getUtility(IProductSet)['gnome-terminal']
        series = product.newSeries('importd-test', displayname='', summary='')
        self.series = series
        series.targetarcharchive = None
        series.targetarchcategory = None
        series.targetarchbranch = None
        series.targetarchversion = None
        transaction.commit()        

    def getTestSeries(self):
        """Retrieve the sample ProductSeries created by setUpTestSeries.

        That is useful to test that changes to the ProductSeries reached the
        database.
        """
        product = getUtility(IProductSet)['gnome-terminal']
        series = product.getSeries('importd-test')
        return series


class Baz2bzrTestCase(unittest.TestCase):
    """Base class for baz2bzr test cases."""

    def setUp(self):
        self.sandbox_helper = SandboxHelper()
        self.sandbox_helper.setUp()
        self.series_helper = ProductSeriesHelper()
        self.series_helper.setUp()
        self.series_helper.setUpTestSeries()
        self.version = self.series_helper.version
        self.series_id = self.series_helper.series.id
        self.sandbox_helper.mkdir('archives')
        self.bzrworking = self.sandbox_helper.path('bzrworking')

    def tearDown(self):
        self.sandbox_helper.tearDown()
        self.series_helper.tearDown()

    def extractCannedArchive(self, number):
        """Extract the canned archive with the given sequence number.

        Remove any previously extracted canned archive.
        """
        basedir = os.path.dirname(__file__)
        # Use the saved cwd to turn __file__ into an absolute path
        basedir = os.path.join(self.sandbox_helper.here, basedir)
        tarball = os.path.join(basedir, 'importd@example.com-%d.tgz' % number)
        target_dir = self.sandbox_helper.path('archives')
        archive_path = os.path.join(target_dir, 'importd@example.com')
        if os.path.isdir(archive_path):
            shutil.rmtree(archive_path)
        retcode = call(['tar', 'xzf', tarball], cwd=target_dir)
        assert retcode == 0, 'failed to extract canned archive %d' % number

    def registerCannedArchive(self):
        """Register a canned archive created by extractCannedArchive."""
        path = os.path.join(self.sandbox_helper.path('archives'),
                            'importd@example.com')
        location = pybaz.ArchiveLocation(path)
        location.register()

    def bzrBranch(self, path):
        """Return the bzrlib Branch object for the produced branch."""
        return bzrlib.branch.Branch.open(path)

    def assertRevisionMatchesExpected(self, branch, index):
        """Match revision attributes against expected data."""
        history = branch.revision_history()
        revision = branch.repository.get_revision(history[index])
        revision_attrs = (
            revision.revision_id,
            revision.timestamp,
            revision.timezone,
            revision.committer,
            revision.message,
            revision.properties)
        # Revisions we expect baz-import to generate. Note that we are using
        # the baz-import version which has been modified to parse the cscvs
        # metadata and add launchpad.net advertising. Since we are always
        # importing from the same baz archive (generated by cscvs), we must
        # always get the same revision properties.
        expected_revs = [
            ('Arch-1:importd@example.com%test--branch--0--base-0',
             1140542478.0, None, 'david', 'Initial revision\n',
             {'converted-by': 'launchpad.net', 'cscvs-id': 'MAIN.1'}),
            ('Arch-1:importd@example.com%test--branch--0--patch-1',
             1140542480.0, None, 'david', 'change 1\n',
             {'converted-by': 'launchpad.net', 'cscvs-id': 'MAIN.2'}),
            ('Arch-1:importd@example.com%test--branch--0--patch-2',
             1140542509.0, None, 'david', 'change 2\n',
             {'converted-by': 'launchpad.net', 'cscvs-id': 'MAIN.3'})]
        self.assertEqual(revision_attrs, expected_revs[index])

    def assertHistoryMatchesExpectedTwo(self, branch):
        """Check that history is two items long and match expected data."""
        # This method unrolls the loop to provide helpful backtraces.
        history = branch.revision_history()
        self.assertEqual(len(history), 2)
        self.assertRevisionMatchesExpected(branch, 0)
        self.assertRevisionMatchesExpected(branch, 1)

    def assertHistoryMatchesExpectedThree(self, branch):
        """Check that history is three items long and match expected data."""
        # This method unrolls the loop to provide helpful backtraces.
        history = branch.revision_history()
        self.assertEqual(len(history), 3)
        self.assertRevisionMatchesExpected(branch, 0)
        self.assertRevisionMatchesExpected(branch, 1)
        self.assertRevisionMatchesExpected(branch, 2)

    def baz2bzrPath(self):
        """Filename of the baz2bzr script, used for spawning the script."""
        # Use the saved cwd to turn __file__ into an absolute path
        return os.path.join(self.sandbox_helper.here, baz2bzr.__file__)

    def baz2bzrEnv(self):
        """Build the baz2bzr environment dictionnary."""
        # XXX: It would be nice if we could use launchpad.config there, but
        # importd and baz2bzr are not good Launchpad citizens and do not use
        # the config system. Therefore the relevant section is not there to be
        # found, and I do not think there would be much sense in adding a
        # config entry just for the benefit of this test suite.
        # -- David Allouche 2005-04-05
        environ = dict(os.environ)
        environ['LP_DBNAME'] = 'launchpad_ftest'
        environ['LP_DBUSER'] = 'importd'
        return environ

    def baz2bzrCommand(self, args, silence_deprecations=False):
        """Command line for baz2bzr.

        Setting silence_deprecations to True will disable all deprecation
        warnings. Use that when testing the output of baz2bzr. Do not use that
        when just testing the behaviour, so running the test suite will still
        cause the warnings to be displayed.
        """
        if silence_deprecations:
            warning_options = ['-W', 'ignore::DeprecationWarning::']
        else:
            warning_options = []
        return ([sys.executable] + warning_options
                + [self.baz2bzrPath()] + args)

    def callBaz2bzr(self, args):
        """Execute baz2bzr with the provided argument list.

        Does not redirect stdio so baz2bzr can be traced with pdb.

        :raise AssertionError: if the exit code is non-zero.
        """
        retcode = call(
            self.baz2bzrCommand(args, silence_deprecations=False),
            env=self.baz2bzrEnv())
        assert retcode == 0, 'baz2bzr failed (status %d)' % retcode

    def pipeBaz2bzr(self, args, status=0):
        """Execute baz2bzr on pipes with the provided argument list.

        :return: stderr and stdout combined in a single string.
        :raise AssertionError: if the exit code is non-zero.
        """
        process = Popen(
            self.baz2bzrCommand(args, silence_deprecations=True),
            stdin=PIPE, stdout=PIPE, stderr=STDOUT, env=self.baz2bzrEnv())
        output, error = process.communicate()
        unused = error
        returncode = process.returncode
        self.assertEqual(returncode, status,
            'baz2bzr failed (status %d)\n%s' % (returncode,  output))
        return output

    def ptyBaz2bzr(self, args):
        """Execute baz2bzr in a pty with the provided argument list.

        :return: output read from the pty
        :raise AssertionError: if the exit code is non-zero
        """
        # pty forking magic was lifted from pexpect.py and simplified to remove
        # compatibility code.
        pid, child_fd = pty.fork()
        if pid == 0: # Child
            child_fd = sys.stdout.fileno()
            max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            for i in range (3, max_fd):
                try:
                    os.close (i)
                except OSError:
                    pass
            new_env = self.baz2bzrEnv()
            os.environ.clear()
            os.environ.update(new_env)
            try:
                os.execvp(
                    sys.executable,
                    self.baz2bzrCommand(args, silence_deprecations=True))
            finally:
                # If execvp fails, we do not want an exception to bubble up
                # into the callers
                os._exit(2)

        # Read all output. That will deadlock if the the child process tries to
        # read input. We cannot close input without closing output as well. If
        # deadlocking turns out to be a problem, we can raise non-blocking read
        # code from pexpect.py and kill the suprocess after a reasonable time
        # (5 minutes?).
        child_file = os.fdopen(child_fd)
        output = child_file.read()
        child_file.close()
        pid, sts = os.waitpid(pid, 0)

        # Exit status handling was lifted from subprocess.py
        if os.WIFSIGNALED(sts):
            returncode = -os.WTERMSIG(sts)
        elif os.WIFEXITED(sts):
            returncode = os.WEXITSTATUS(sts)
        else:
            # Should never happen
            raise RuntimeError("Unknown child exit status!")

        self.assertEqual(returncode, 0,
            'baz2bzr failed (status %d)\n%s' % (returncode,  output))
        return output
        

class TestBaz2bzrImportFeature(Baz2bzrTestCase):

    def test_conversion(self):
        # test the initial import
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        self.callBaz2bzr(['-q', str(self.series_id), '/dev/null'])
        branch = self.bzrBranch(self.bzrworking)
        self.assertHistoryMatchesExpectedTwo(branch)
        # test updating the bzr branch
        self.extractCannedArchive(2)
        self.callBaz2bzr(['-q', str(self.series_id), '/dev/null'])
        self.assertHistoryMatchesExpectedThree(branch)

    def test_pipe_output(self):
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        output = self.pipeBaz2bzr([str(self.series_id), '/dev/null'])
        self.assertEqual(output, '\n'.join(self.expected_lines))

    def test_pty_output(self):
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        output = self.ptyBaz2bzr([str(self.series_id), '/dev/null'])
        self.assertEqual(output, '\r\n'.join(self.expected_lines))

    # expected_lines should be a reasonable amount of progress output. Enough
    # for the process no to spin for 20 minutes without producing output (and
    # be killed by buildbot). Not too much to avoid hitting the string
    # concatenation bug in buildbot. One line per revision is good.
    expected_lines = [
        '0/2 revisions',
        '1/2 revisions',
        '2/2 revisions',
        'Cleaning up',
        'Import complete.',
        ''] # empty item denotes final newline

    def test_blacklist(self):
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        blacklist_path = self.sandbox_helper.path('blacklist')
        blacklist_file = open(blacklist_path, 'w')
        print >> blacklist_file, self.version.fullname
        blacklist_file.close()
        output = self.pipeBaz2bzr(
            [str(self.series_id), blacklist_path])
        expected = "blacklisted: %s\nNot exporting to bzr\n" % (
            self.version.fullname)
        self.assertEqual(output, expected)
        self.failIf(os.path.exists(self.bzrworking))


class TestBaz2bzrPublishFeature(Baz2bzrTestCase):

    def setUp(self):
        Baz2bzrTestCase.setUp(self)
        self.mirror_prefix = self.sandbox_helper.path('bzr_mirrors') + '/'
        os.mkdir(self.mirror_prefix)

    def getTestSeries(self):
        return self.series_helper.getTestSeries()
    
    def test_publish(self):
        # test the initial publishing
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        self.callBaz2bzr([
            '-q', str(self.series_id), '/dev/null', self.mirror_prefix])
        flush_database_caches()
        self.assertNotEqual(self.getTestSeries().branch, None)
        branch_id = self.getTestSeries().branch.id
        mirror_path = os.path.join(
            self.mirror_prefix, '%08x' % branch_id)
        self.failUnless(os.path.isdir(mirror_path))
        branch = self.bzrBranch(mirror_path)
        self.assertHistoryMatchesExpectedTwo(branch)
        # test updating the bzr branch
        self.extractCannedArchive(2)
        self.callBaz2bzr([
            '-q', str(self.series_id), '/dev/null', self.mirror_prefix])
        self.assertHistoryMatchesExpectedThree(branch)

    def test_pipe_output(self):
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        output = self.pipeBaz2bzr([
            str(self.series_id), '/dev/null', self.mirror_prefix])
        self.assertEqual(output, '\n'.join(self.expected_lines))

    def test_pty_output(self):
        self.extractCannedArchive(1)
        self.registerCannedArchive()
        output = self.ptyBaz2bzr([
            str(self.series_id), '/dev/null', self.mirror_prefix])
        self.assertEqual(output, '\r\n'.join(self.expected_lines))

    expected_lines = TestBaz2bzrImportFeature.expected_lines[:-1] + [
        'get destination history',
        '0/1 merge weaves',
        '0/2 inventory fetch',
        '1/2 inventory fetch',
        '2/2 inventory fetch',
        'preparing to copy',
        '1/2 copy',
        '2/2 copy',
        ''] # empty item denotes final newline


class TestBlacklistParser(unittest.TestCase):

    def assertBlacklistParses(self, blacklist, expected):
        stringio = StringIO(blacklist)
        result = baz2bzr.parse_blacklist(stringio)
        self.assertEqual(list(result), expected)

    def test_one(self):
        self.assertBlacklistParses('foo\n', ['foo'])
        self.assertBlacklistParses('foo', ['foo'])
        self.assertBlacklistParses('\nfoo', ['foo'])
        self.assertBlacklistParses(' foo \n', ['foo'])

    def test_empty(self):
        self.assertBlacklistParses('', [])
        self.assertBlacklistParses('\n', [])
        self.assertBlacklistParses(' \n', [])

    def test_two(self):
        self.assertBlacklistParses('foo\nbar\n', ['foo', 'bar'])
        self.assertBlacklistParses('foo\nbar', ['foo', 'bar'])
        self.assertBlacklistParses('foo\n\nbar\n', ['foo', 'bar'])


class TestArchFromSeries(unittest.TestCase):

    def setUp(self):
        self.series_helper = ProductSeriesHelper()
        self.series_helper.setUp()

    def tearDown(self):
        self.series_helper.tearDown()

    def testWithArch(self):
        self.series_helper.setUpTestSeries()
        self.series = self.series_helper.series
        self.version = self.series_helper.version
        expected = self.version.fullname
        result = baz2bzr.arch_from_series(self.series)        
        self.assertEqual(result, expected)

    def testWithoutArch(self):
        self.series_helper.setUpNonarchSeries()
        self.series = self.series_helper.series
        expected = 'unnamed@bazaar.ubuntu.com/series--%d' % self.series.id
        result = baz2bzr.arch_from_series(self.series)
        self.assertEqual(result, expected)


class TestBranch(unittest.TestCase):

    def setUp(self):
        self.series_helper = ProductSeriesHelper()
        self.series_helper.setUp()
        self.series_helper.setUpTestSeries()
        self.series = self.series_helper.series

    def tearDown(self):
        self.series_helper.tearDown()
        self.series = None

    def getTestSeries(self):
        return self.series_helper.getTestSeries()

    def testBranchFromSeries(self):
        self.assertEqual(self.getTestSeries().branch, None)
        branch = baz2bzr.branch_from_series(self.series)
        self.assertEqual(self.getTestSeries().branch, branch)
        branch2 = baz2bzr.branch_from_series(self.series)
        self.assertEqual(branch2, branch)
        self.assertEqual(branch2, self.getTestSeries().branch)

    def testCreateBranchForSeries(self):
        branch = baz2bzr.create_branch_for_series(self.series)
        self.assertEqual(branch.title, None)
        self.assertEqual(branch.summary, None)
        vcs_imports = getUtility(ILaunchpadCelebrities).vcs_imports
        self.assertEqual(branch.owner, vcs_imports)
        self.assertEqual(branch.product, self.series.product)
        self.assertEqual(branch.name, self.series.name)
        self.assertEqual(branch.url, None)


TestUtil.register(__name__)
