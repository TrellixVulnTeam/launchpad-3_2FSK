import logging
import os
import shutil
import tempfile
import unittest

import bzrlib

from canonical.config import config
from canonical.launchpad.interfaces import BranchType
from canonical.launchpad.scripts.supermirror.branchtomirror import (
    BranchToMirror)
from canonical.launchpad.scripts.supermirror.branchtargeter import branchtarget
from canonical.launchpad.scripts.supermirror.ftests import createbranch
from canonical.launchpad.scripts.supermirror import jobmanager
from canonical.authserver.client.branchstatus import BranchStatusClient
from canonical.authserver.tests.harness import AuthserverTacTestSetup
from canonical.testing import LaunchpadFunctionalLayer, reset_logging


class TestJobManager(unittest.TestCase):

    def setUp(self):
        self.masterlock = 'master.lock'
        # We set the log level to CRITICAL so that the log messages
        # are suppressed.
        logging.basicConfig(level=logging.CRITICAL)

    def tearDown(self):
        reset_logging()

    def makeFakeClient(self, hosted, mirrored, imported):
        return FakeBranchStatusClient(
            {'HOSTED': hosted, 'MIRRORED': mirrored, 'IMPORTED': imported})

    def testEmptyAddBranches(self):
        fakeclient = self.makeFakeClient([], [], [])
        manager = jobmanager.JobManager(BranchType.HOSTED)
        manager.addBranches(fakeclient)
        self.assertEqual([], manager.branches_to_mirror)

    def testSingleAddBranches(self):
        # Get a list of branches and ensure that it can add a branch object.
        expected_branch = BranchToMirror(
            'managersingle', config.supermirror.branchesdest + '/00/00/00/00',
            None, None, None)
        fakeclient = self.makeFakeClient(
            [(0, 'managersingle', u'name//trunk')], [], [])
        manager = jobmanager.JobManager(BranchType.HOSTED)
        manager.addBranches(fakeclient)
        self.assertEqual([expected_branch], manager.branches_to_mirror)

    def testAddJobManager(self):
        manager = jobmanager.JobManager(BranchType.HOSTED)
        manager.add(BranchToMirror(None, None, None, None, None))
        manager.add(BranchToMirror(None, None, None, None, None))
        self.assertEqual(len(manager.branches_to_mirror), 2)

    def testManagerCreatesLocks(self):
        try:
            manager = jobmanager.JobManager(BranchType.HOSTED)
            manager.lockfilename = self.masterlock
            manager.lock()
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def testManagerEnforcesLocks(self):
        try:
            manager = jobmanager.JobManager(BranchType.HOSTED)
            manager.lockfilename = self.masterlock
            manager.lock()
            anothermanager = jobmanager.JobManager(BranchType.HOSTED)
            anothermanager.lockfilename = self.masterlock
            self.assertRaises(jobmanager.LockError, anothermanager.lock)
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def _removeLockFile(self):
        if os.path.exists(self.masterlock):
            os.unlink(self.masterlock)

    def testImportAddBranches(self):
        client = self.makeFakeClient(
            [], [],
            [(14, 'http://escudero.ubuntu.com:680/0000000e',
              'vcs-imports//main')])
        import_manager = jobmanager.JobManager(BranchType.IMPORTED)
        import_manager.addBranches(client)
        expected_branch = BranchToMirror(
            'http://escudero.ubuntu.com:680/0000000e',
            config.supermirror.branchesdest + '/00/00/00/0e',
            None, None, None)
        self.assertEqual(import_manager.branches_to_mirror, [expected_branch])

    def testUploadAddBranches(self):
        client = self.makeFakeClient(
            [(25, '/tmp/sftp-test/branches/00/00/00/19', u'name12//pushed')],
            [], [])
        upload_manager = jobmanager.JobManager(BranchType.HOSTED)
        upload_manager.addBranches(client)
        expected_branch = BranchToMirror(
            '/tmp/sftp-test/branches/00/00/00/19',
            config.supermirror.branchesdest + '/00/00/00/19',
            None, None, None)
        self.assertEqual(upload_manager.branches_to_mirror, [expected_branch])

    def testMirrorAddBranches(self):
        client = self.makeFakeClient(
            [],
            [(15, 'http://example.com/gnome-terminal/main', u'name12//main')],
            [])
        mirror_manager = jobmanager.JobManager(BranchType.MIRRORED)
        mirror_manager.addBranches(client)
        expected_branch = BranchToMirror(
            'http://example.com/gnome-terminal/main',
            config.supermirror.branchesdest + '/00/00/00/0f',
            None, None, None)
        self.assertEqual(mirror_manager.branches_to_mirror, [expected_branch])


class TestJobManagerInLaunchpad(unittest.TestCase):
    layer = LaunchpadFunctionalLayer

    testdir = None

    def setUp(self):
        self.testdir = tempfile.mkdtemp()
        # Change the HOME environment variable in order to ignore existing
        # user config files.
        os.environ.update({'HOME': self.testdir})
        self.authserver = AuthserverTacTestSetup()
        self.authserver.setUp()

    def tearDown(self):
        shutil.rmtree(self.testdir)
        self.authserver.tearDown()

    def _getBranchDir(self, branchname):
        return os.path.join(self.testdir, branchname)

    def assertMirrored(self, branch_to_mirror):
        """Assert that branch_to_mirror's source and destinations have the same
        revisions.
        
        :param branch_to_mirror: a BranchToMirror instance.
        """
        source_branch = bzrlib.branch.Branch.open(branch_to_mirror.source)
        dest_branch = bzrlib.branch.Branch.open(branch_to_mirror.dest)
        self.assertEqual(source_branch.last_revision(),
                         dest_branch.last_revision())

    def testJobRunner(self):
        manager = jobmanager.JobManager(BranchType.HOSTED)
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

        manager.run(logging.getLogger())

        self.assertEqual(len(manager.branches_to_mirror), 0)
        self.assertMirrored(brancha)
        self.assertMirrored(branchb)
        self.assertMirrored(branchc)
        self.assertMirrored(branchd)
        self.assertMirrored(branche)

    def _makeBranch(self, relativedir, target, branch_status_client,
                    unique_name=None):
        """Given a relative directory, make a strawman branch and return it.

        @param relativedir - The directory to make the branch
        @output BranchToMirror - A branch object representing the strawman
                                    branch
        """
        branchdir = os.path.join(self.testdir, relativedir)
        createbranch(branchdir)
        if target == None:
            targetdir = None
        else:
            targetdir = os.path.join(self.testdir, branchtarget(target))
        return BranchToMirror(
                branchdir, targetdir, branch_status_client, target,
                unique_name)


class FakeBranchStatusClient:
    """A dummy branch status client implementation for testing getBranches()"""

    def __init__(self, branch_queues):
        self.branch_queues = branch_queues

    def getBranchPullQueue(self, branch_type):
        return self.branch_queues[branch_type]


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

