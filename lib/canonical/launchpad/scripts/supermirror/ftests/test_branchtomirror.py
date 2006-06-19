# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Functional tests for branchtomirror.py."""

__metaclass__ = type

import httplib
import os
import shutil
import socket
import tempfile
import unittest
import urllib2

import bzrlib.branch
import bzrlib.errors
from bzrlib.tests import TestCaseInTempDir
from bzrlib.tests.repository_implementations.test_repository import (
            TestCaseWithRepository)
from bzrlib.transport import get_transport
from bzrlib.weave import Weave
from bzrlib.errors import (
    BzrError, UnsupportedFormatError, UnknownFormatError, ParamikoNotPresent,
    NotBranchError)

import transaction
from canonical.launchpad import database
from canonical.launchpad.scripts.supermirror.ftests import createbranch
from canonical.launchpad.scripts.supermirror.branchtomirror import (
    BranchToMirror)
from canonical.authserver.client.branchstatus import BranchStatusClient
from canonical.authserver.ftests.harness import AuthserverTacTestSetup
from canonical.launchpad.ftests.harness import (
    LaunchpadFunctionalTestSetup, LaunchpadFunctionalTestCase)
from canonical.testing.layers import Functional


class TestBranchToMirror(LaunchpadFunctionalTestCase):

    layer = Functional

    testdir = None

    def setUp(self):
        self.testdir = tempfile.mkdtemp()
        LaunchpadFunctionalTestCase.setUp(self)
        # Change the HOME environment variable in order to ignore existing
        # user config files.
        os.environ.update({'HOME': self.testdir})
        self.authserver = AuthserverTacTestSetup()
        self.authserver.setUp()

    def tearDown(self):
        shutil.rmtree(self.testdir)
        self.authserver.tearDown()
        LaunchpadFunctionalTestCase.tearDown(self)

    def _getBranchDir(self, branchname):
        return os.path.join(self.testdir, branchname)

    def testMirror(self):
        # Create a branch
        srcbranchdir = self._getBranchDir("branchtomirror-testmirror-src")
        destbranchdir = self._getBranchDir("branchtomirror-testmirror-dest")

        client = BranchStatusClient()
        to_mirror = BranchToMirror(srcbranchdir, destbranchdir, client, 1)

        tree = createbranch(srcbranchdir)
        to_mirror.mirror()
        mirrored_branch = bzrlib.branch.Branch.open(to_mirror.dest)
        self.assertEqual(tree.last_revision(),
                         mirrored_branch.last_revision())


class TestBranchToMirrorFormats(TestCaseWithRepository):

    layer = Functional

    def setUp(self):
        super(TestBranchToMirrorFormats, self).setUp()
        LaunchpadFunctionalTestSetup().setUp()
        self.authserver = AuthserverTacTestSetup()
        self.authserver.setUp()

    def tearDown(self):
        self.authserver.tearDown()
        super(TestBranchToMirrorFormats, self).tearDown()
        LaunchpadFunctionalTestSetup().tearDown()
        test_root = TestCaseInTempDir.TEST_ROOT
        if test_root is not None and os.path.exists(test_root):
            shutil.rmtree(test_root)
        # Set the TEST_ROOT back to None, to tell TestCaseInTempDir we need it
        # to create a new root when the next test is run.
        # The TestCaseInTempDir is part of bzr's test infrastructure and the
        # bzr test runner normally does this cleanup, but here we have to do
        # that ourselves.
        TestCaseInTempDir.TEST_ROOT = None

    def testMirrorKnitAsKnit(self):
        # Create a source branch in knit format, and check that the mirror is in
        # knit format.
        self.bzrdir_format = bzrlib.bzrdir.BzrDirMetaFormat1()
        self.repository_format = bzrlib.repository.RepositoryFormatKnit1()
        self._testMirrorFormat()

    def testMirrorMetaweaveAsMetaweave(self):
        # Create a source branch in metaweave format, and check that the mirror
        # is in metaweave format.
        self.bzrdir_format = bzrlib.bzrdir.BzrDirMetaFormat1()
        self.repository_format = bzrlib.repository.RepositoryFormat7()
        self._testMirrorFormat()

    def testMirrorWeaveAsWeave(self):
        # Create a source branch in weave format, and check that the mirror is
        # in weave format.
        self.bzrdir_format = bzrlib.bzrdir.BzrDirFormat6()
        self.repository_format = bzrlib.repository.RepositoryFormat6()
        self._testMirrorFormat()

    def testSourceFormatChange(self):
        # Create and mirror a branch in weave format.
        self.bzrdir_format = bzrlib.bzrdir.BzrDirMetaFormat1()
        self.repository_format = bzrlib.repository.RepositoryFormat7()
        self._createSourceBranch()
        self._mirror()
        
        # Change the branch to knit format.
        shutil.rmtree('src-branch')
        self.repository_format = bzrlib.repository.RepositoryFormatKnit1()
        self._createSourceBranch()

        # Mirror again.  The mirrored branch should now be in knit format.
        mirrored_branch = self._mirror()
        self.assertEqual(
            self.repository_format.get_format_description(),
            mirrored_branch.repository._format.get_format_description())

    def _createSourceBranch(self):
        os.mkdir('src-branch')
        tree = self.make_branch_and_tree('src-branch')
        self.local_branch = tree.branch
        self.build_tree(['foo'], transport=get_transport('./src-branch'))
        tree.add('foo')
        tree.commit('Added foo', rev_id='rev1')
        return tree

    def _mirror(self):
        # Mirror src-branch to dest-branch
        client = BranchStatusClient()
        to_mirror = BranchToMirror('src-branch', 'dest-branch', client, 1)
        to_mirror.mirror()
        mirrored_branch = bzrlib.branch.Branch.open(to_mirror.dest)
        return mirrored_branch

    def _testMirrorFormat(self):
        tree = self._createSourceBranch()
        
        mirrored_branch = self._mirror()
        self.assertEqual(tree.last_revision(),
                         mirrored_branch.last_revision())

        # Assert that the mirrored branch is in source's format
        # XXX AndrewBennetts 2006-05-18: comparing format objects is ugly.
        # See bug 45277.
        self.assertEqual(
            self.repository_format.get_format_description(),
            mirrored_branch.repository._format.get_format_description())
        self.assertEqual(
            self.bzrdir_format.get_format_description(),
            mirrored_branch.bzrdir._format.get_format_description())


class TestBranchToMirror_SourceProblems(TestCaseInTempDir):

    layer = Functional

    def setUp(self):
        LaunchpadFunctionalTestSetup().setUp()
        TestCaseInTempDir.setUp(self)
        self.authserver = AuthserverTacTestSetup()
        self.authserver.setUp()

    def tearDown(self):
        self.authserver.tearDown()
        TestCaseInTempDir.tearDown(self)
        LaunchpadFunctionalTestSetup().tearDown()
        test_root = TestCaseInTempDir.TEST_ROOT
        if test_root is not None and os.path.exists(test_root):
            shutil.rmtree(test_root)
        # Set the TEST_ROOT back to None, to tell TestCaseInTempDir we need it
        # to create a new root when the next test is run.
        # The TestCaseInTempDir is part of bzr's test infrastructure and the
        # bzr test runner normally does this cleanup, but here we have to do
        # that ourselves.
        TestCaseInTempDir.TEST_ROOT = None

    def testUnopenableSourceDoesNotCreateMirror(self):
        non_existant_branch = "nonsensedir"
        dest_dir = "dest-dir"
        client = BranchStatusClient()
        mybranch = BranchToMirror(
            non_existant_branch, dest_dir, client, 1)
        mybranch.mirror()
        self.failIf(os.path.exists(dest_dir), 'dest-dir should not exist')

    def testMissingSourceWhines(self):
        non_existant_branch = "nonsensedir"
        client = BranchStatusClient()
        # ensure that we have no errors muddying up the test
        client.mirrorComplete(1)
        mybranch = BranchToMirror(
            non_existant_branch, "anothernonsensedir", client, 1)
        mybranch.mirror()
        transaction.abort()
        branch = database.Branch.get(1)
        self.assertEqual(1, branch.mirror_failures)

    def testMissingFileRevisionData(self):
        self.build_tree(['missingrevision/',
                         'missingrevision/afile'])
        tree = bzrlib.bzrdir.BzrDir.create_standalone_workingtree(
            'missingrevision')
        tree.add(['afile'], ['myid'])
        tree.commit('start')
        # now we have a good branch with a file called afile and id myid
        # we need to figure out the actual path for the weave.. or 
        # deliberately corrupt it. like this.
        tree.branch.repository.weave_store.put_weave(
            "myid", Weave(weave_name="myid"),
            tree.branch.repository.get_transaction())
        # now try mirroring this branch.
        client = BranchStatusClient()
        # clear the error status
        client.mirrorComplete(1)
        mybranch = BranchToMirror(
            'missingrevision', "missingrevisiontarget", client, 1)
        mybranch.mirror()
        transaction.abort()
        branch = database.Branch.get(1)
        self.assertEqual(1, branch.mirror_failures)


class TestErrorHandling(unittest.TestCase):

    def setUp(self):
        self.errors = []
        client = BranchStatusClient()
        self.branch = BranchToMirror('foo', 'bar', client, 1)
        # Stub out everything that we don't need to test
        client.startMirroring = lambda branch_id: None
        self.branch._mirrorFailed = lambda err, m=None: self.errors.append(err)
        self.branch._openSourceBranch = lambda: None
        self.branch._mirrorToDestBranch = lambda: None

    def _runMirrorAndCheckError(self, expected_error):
        self.branch.mirror()
        self.assertEqual(len(self.errors), 1)
        error = str(self.errors[0])
        if not error.startswith(expected_error):
            self.fail('Expected "%s" but got "%s"' % (expected_error, error))

    def testHTTPError(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise urllib2.HTTPError(
                'http://something', httplib.UNAUTHORIZED, 
                'Authorization Required', 'some headers',
                open(tempfile.mkstemp()[1]))
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'Private branch; required authentication'
        self._runMirrorAndCheckError(expected_msg)

    def testSocketErrorHandling(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise socket.error('foo')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'A socket error occurred:'
        self._runMirrorAndCheckError(expected_msg)

    def testUnsupportedFormatErrorHandling(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise UnsupportedFormatError('Bazaar-NG branch, format 0.0.4')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'The supermirror does not support branches'
        self._runMirrorAndCheckError(expected_msg)

    def testUnknownFormatError(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise UnknownFormatError('Some junk')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'Unknown branch format:'
        self._runMirrorAndCheckError(expected_msg)

        self.errors = []
        def stubOpenSourceBranch():
            raise UnknownFormatError(
                'Loads of junk\n with two or more\n newlines.')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'Not a branch'
        self._runMirrorAndCheckError(expected_msg)

    def testParamikoNotPresent(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise ParamikoNotPresent('No module named paramiko')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'The supermirror does not support mirroring branches'
        self._runMirrorAndCheckError(expected_msg)

    def testNotBranchError(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise NotBranchError('/foo/baz/')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'Not a branch:'
        self._runMirrorAndCheckError(expected_msg)

    def testBzrErrorHandling(self):
        self.errors = []
        def stubOpenSourceBranch():
            raise BzrError('A generic bzr error')
        self.branch._openSourceBranch = stubOpenSourceBranch
        expected_msg = 'A generic bzr error'
        self._runMirrorAndCheckError(expected_msg)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
