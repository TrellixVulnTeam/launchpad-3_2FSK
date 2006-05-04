import os
import shutil
import tempfile
import unittest
from StringIO import StringIO

import bzrlib

from canonical.config import config
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestCase
from canonical.launchpad.scripts.supermirror.branchtomirror import (
    BranchToMirror)
from canonical.launchpad.scripts.supermirror.branchtargeter import branchtarget
from canonical.launchpad.scripts.supermirror.ftests import createbranch
from canonical.launchpad.scripts.supermirror import jobmanager
from canonical.authserver.client.branchstatus import BranchStatusClient
from canonical.authserver.ftests.harness import AuthserverTacTestSetup
from canonical.functional import FunctionalLayer


class TestJobManager(unittest.TestCase):

    def setUp(self):
        self.masterlock = 'master.lock'

    def testExistance(self):
        from canonical.launchpad.scripts.supermirror.jobmanager import (
            JobManager)
        assert JobManager

    def testEmptyBranchStreamToBranchList(self):
        falsestdin = StringIO("")
        manager = jobmanager.JobManager()
        self.assertEqual([], manager.branchStreamToBranchList(falsestdin, None))

    def testSingleBranchStreamToBranchList(self):
        """Get a list of branches and ensure that it can add a branch object."""
        expected_branch = BranchToMirror(
            'managersingle', config.supermirror.branchesdest + '/00/00/00/00',
            None, None)
        falsestdin = StringIO("0 managersingle\n")
        manager = jobmanager.JobManager()
        branches = manager.branchStreamToBranchList(falsestdin, None)
        self.assertEqual([expected_branch], branches)

    def testAddJobManager(self):
        manager = jobmanager.JobManager()
        manager.add(BranchToMirror('foo', 'bar', None, None))
        manager.add(BranchToMirror('baz', 'bar', None, None))
        self.assertEqual(len(manager.branches_to_mirror), 2)

    def testManagerCreatesLocks(self):
        try:
            manager = jobmanager.JobManager()
            self._removeLockFile()
            manager.lock(lockfilename=self.masterlock)
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def testManagerEnforcesLocks(self):
        try:
            manager = jobmanager.JobManager()
            self._removeLockFile()
            manager.lock(lockfilename=self.masterlock)
            anothermanager = jobmanager.JobManager()
            self.assertRaises(jobmanager.LockError, anothermanager.lock)
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def _removeLockFile(self):
        if os.path.exists(self.masterlock):
            os.unlink(self.masterlock)


class TestJobManagerInLaunchpad(LaunchpadFunctionalTestCase):
    layer = FunctionalLayer

    testdir = None

    def setUp(self):
        LaunchpadFunctionalTestCase.setUp(self)
        self.testdir = tempfile.mkdtemp()
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

    def assertMirrored(self, branch):
        source_tree = bzrlib.workingtree.WorkingTree.open(branch.source)
        dest_tree = bzrlib.workingtree.WorkingTree.open(branch.dest)
        self.assertEqual(source_tree.last_revision(), dest_tree.last_revision())

    def testJobRunner(self):
        manager = jobmanager.JobManager()
        self.assertEqual(len(manager.branches_to_mirror), 0)

        client = BranchStatusClient()
        brancha = self._makeBranch("brancha", 1, client)
        manager.add(brancha)

        branchb = self._makeBranch("branchb", 2, client)
        manager.add(branchb)

        branchc = self._makeBranch("branchc", 3, client)
        manager.add(branchc)

        branchd = self._makeBranch("branchd", 4, client)
        manager.add(branchd)

        branche = self._makeBranch("branche", 5, client)
        manager.add(branche)

        self.assertEqual(len(manager.branches_to_mirror), 5)

        manager.run()

        self.assertEqual(len(manager.branches_to_mirror), 0)
        self.assertMirrored(brancha)
        self.assertMirrored(branchb)
        self.assertMirrored(branchc)
        self.assertMirrored(branchd)
        self.assertMirrored(branche)

    def _makeBranch(self, relativedir, target, branch_status_client):
        """Given a relative directory, make a strawman branch and return it.

        @param relativedir - The directory to make the branch
        @output BranchToMirror - A branch object representing the strawman branch
        """
        branchdir = os.path.join(self.testdir, relativedir)
        createbranch(branchdir)
        if target == None:
            targetdir = None
        else:
            targetdir = os.path.join(self.testdir, branchtarget(target))
        return BranchToMirror(
                branchdir, targetdir, branch_status_client, target
                )


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

