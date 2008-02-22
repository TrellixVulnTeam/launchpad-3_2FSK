# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0101

"""Acceptance tests for Supermirror SFTP server's bzr support."""

__metaclass__ = type

from StringIO import StringIO
import os
import sys
import thread
import unittest
import xmlrpclib

import bzrlib.branch
from bzrlib.builtins import cmd_branch, cmd_push
from bzrlib.errors import (
    BzrCommandError, LockFailed, NotBranchError, TransportNotPossible)
from bzrlib.repofmt.weaverepo import RepositoryFormat7
from bzrlib.repository import format_registry

from bzrlib.urlutils import local_path_from_url
from bzrlib.tests import default_transport, TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

from paramiko import SSHClient, SSHException, MissingHostKeyPolicy

from canonical.authserver.client.twistedclient import get_blocking_proxy
from canonical.codehosting.tests.helpers import (
    adapt_suite, deferToThread, ServerTestCase)
from canonical.codehosting.tests.servers import (
    make_bzr_ssh_server, make_sftp_server)
from canonical.codehosting import branch_id_to_path
from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.launchpad import database
from canonical.launchpad.ftests.harness import LaunchpadZopelessTestSetup
from canonical.launchpad.interfaces import BranchLifecycleStatus, BranchType
from canonical.launchpad.webapp.errorlog import globalErrorUtility
from canonical.testing import TwistedLayer


class SSHTestCase(ServerTestCase):

    layer = TwistedLayer
    server = None

    def installServer(self, server):
        super(SSHTestCase, self).installServer(server)
        self.default_user = server.authserver.testUser
        self.default_team = server.authserver.testTeam

    def setUp(self):
        super(SSHTestCase, self).setUp()
        self._main_thread_id = thread.get_ident()

        # Create a local branch with one revision
        tree = self.make_branch_and_tree('.')
        self.local_branch = tree.branch
        self.local_branch_path = local_path_from_url(self.local_branch.base)
        self.build_tree(['foo'])
        tree.add('foo')
        tree.commit('Added foo', rev_id='rev1')

    def tearDown(self):
        TestCaseWithTransport.tearDown(self)
        return ServerTestCase.tearDown(self)

    def assertBranchesMatch(self, local_url, remote_url):
        """Assert that two branches have the same last revision."""
        local_revision = self.getLastRevision(local_url)
        remote_revision = self.getLastRevision(remote_url)
        self.assertEqual(local_revision, remote_revision)

    def assertNotInMainThread(self, function_name):
        self.assertNotEqual(
            thread.get_ident(), self._main_thread_id,
            "%s cannot be run in the main thread.")

    def runInChdir(self, directory, func, *args, **kwargs):
        old_dir = os.getcwdu()
        os.chdir(directory)
        try:
            return func(*args, **kwargs)
        finally:
            os.chdir(old_dir)

    def branch(self, remote_url, local_directory):
        """Branch from the given URL to a local directory.

        This method is used to test the end-to-end behaviour of pushing Bazaar
        branches to the SSH server.

        Do NOT run this method in the main thread! It does a blocking read
        from the SSH server, which is running in the Twisted reactor in the
        main thread.
        """
        self.assertNotInMainThread('branch')
        output = StringIO()
        push_command = cmd_branch()
        push_command.outf = output
        self.server.runAndWaitForDisconnect(
            push_command.run, remote_url, local_directory)
        return output.getvalue()

    def push(self, local_directory, remote_url):
        """Push the local branch to the given URL.

        This method is used to test the end-to-end behaviour of pushing Bazaar
        branches to the SFTP server.

        Do NOT run this method in the main thread! It does a blocking read
        from the SFTP server, which is running in the Twisted reactor in the
        main thread.
        """
        self.assertNotInMainThread('push')
        output = StringIO()
        push_command = cmd_push()
        push_command.outf = output
        self.runInChdir(
            local_directory,
            self.server.runAndWaitForDisconnect, push_command.run, remote_url)
        return output.getvalue()

    def getLastRevision(self, remote_url):
        """Get the last revision at the given URL.

        Do NOT run this method in the main thread! It does a blocking read
        from the SFTP server, which is running in the Twisted reactor in the
        main thread.
        """
        self.assertNotInMainThread('getLastRevision')
        return self.server.runAndWaitForDisconnect(
            lambda: bzrlib.branch.Branch.open(remote_url).last_revision())

    def getTransportURL(self, relpath=None, username=None):
        """Return the base URL for the tests."""
        if relpath is None:
            relpath = ''
        return self.server.get_url(username) + relpath

    def getDatabaseBranch(self, personName, productName, branchName):
        """Look up and return the specified branch from the database."""
        owner = database.Person.byName(personName)
        if productName is None:
            product = None
        else:
            product = database.Product.selectOneBy(name=productName)
        return database.Branch.selectOneBy(
            owner=owner, product=product, name=branchName)

    def createBazaarBranch(self, user, product, branch, creator=None,
                           branch_root=None):
        """Create a new branch in the database and push our test branch there.

        Used to create branches that the test user is not able to create, and
        might not even be able to view.
        """
        authserver = get_blocking_proxy(self.server.authserver.get_url())
        if creator is None:
            creator_id = authserver.getUser(user)['id']
        else:
            creator_id = authserver.getUser(creator)['id']
        if branch_root is None:
            branch_root = self.server._mirror_root
        branch_id = authserver.createBranch(creator_id, user, product, branch)
        branch_url = 'file://' + os.path.abspath(
            os.path.join(branch_root, branch_id_to_path(branch_id)))
        self.runInChdir(
            self.local_branch_path,
            self.run_bzr, ['push', '--create-prefix', branch_url],
            retcode=None)
        return branch_url


class SmokeTest(SSHTestCase):
    """Smoke test for repository support."""

    def getDefaultServer(self):
        return make_bzr_ssh_server()

    def setUp(self):
        super(SmokeTest, self).setUp()
        self.first_tree = 'first'
        self.second_tree = 'second'

    def make_branch_specifying_repo_format(self, relpath, repo_format):
        bd = self.make_bzrdir(relpath, format=self.bzrdir_format)
        repo_format.initialize(bd)
        return bd.create_branch()

    def make_branch_and_tree(self, relpath):
        b = self.make_branch_specifying_repo_format(
            relpath, self.repository_format)
        return b.bzrdir.create_workingtree()

    @deferToThread
    def test_smoke(self):
        # Make a new branch
        tree = self.make_branch_and_tree(self.first_tree)

        # Push up a new branch.
        remote_url = self.getTransportURL('~testuser/+junk/new-branch')
        self.push(self.first_tree, remote_url)
        self.assertBranchesMatch(self.first_tree, remote_url)

        # Commit to it.
        tree.commit('new revision', allow_pointless=True)

        # Push it up again.
        self.push(self.first_tree, remote_url)
        self.assertBranchesMatch(self.first_tree, remote_url)

        # Pull it back down.
        self.branch(remote_url, self.second_tree)
        self.assertBranchesMatch(self.first_tree, self.second_tree)


class AcceptanceTests(SSHTestCase):
    """Acceptance tests for the Launchpad codehosting service.

    Originally converted from the English at
    https://launchpad.canonical.com/SupermirrorTaskList
    """

    def assertNotBranch(self, url):
        """Assert that there's no branch at 'url'."""
        self.assertRaises(
            NotBranchError,
            self.server.runAndWaitForDisconnect,
            bzrlib.branch.Branch.open, url)

    def addRevisionToBranch(self, branch):
        """Add a new revision in the database to the given database branch."""
        # We don't care who the author is. Just find someone.
        author = database.RevisionAuthor.selectFirst(orderBy='id')
        revision = database.Revision(
            revision_id='rev1', log_body='', revision_date=UTC_NOW,
            revision_author=author, owner=branch.owner)
        database.BranchRevision(branch=branch, sequence=1, revision=revision)
        return revision

    def captureStderr(self, function, *args, **kwargs):
        real_stderr, sys.stderr = sys.stderr, StringIO()
        try:
            ret = function(*args, **kwargs)
        finally:
            captured_stderr, sys.stderr = sys.stderr, real_stderr
        return ret, captured_stderr.getvalue()

    def getDefaultServer(self):
        return make_sftp_server()

    def makeDatabaseBranch(self, owner_name, product_name, branch_name,
                           branch_type=BranchType.HOSTED, private=False):
        """Create a new branch in the database."""
        owner = database.Person.selectOneBy(name=owner_name)
        if product_name == '+junk':
            product = None
        else:
            product = database.Product.selectOneBy(name=product_name)
        if branch_type == BranchType.MIRRORED:
            url = 'http://example.com'
        else:
            url = None
        return database.Branch(
            registrant=owner,
            name=branch_name, owner=owner, author=owner, product=product,
            url=url, title=None, lifecycle_status=BranchLifecycleStatus.NEW,
            summary=None, home_page=None, whiteboard=None, private=private,
            date_created=UTC_NOW, branch_type=branch_type)

    @deferToThread
    def test_push_to_new_branch(self):
        """
        The bzr client should be able to read and write to the codehosting
        server just like another other server.  This means that actions
        like:
            * `bzr push bzr+ssh://testinstance/somepath`
            * `bzr log sftp://testinstance/somepath`
        (and/or their bzrlib equivalents) and so on should work, so long as
        the user has permission to read or write to those URLs.
        """
        remote_url = self.getTransportURL('~testuser/+junk/test-branch')
        self.push(self.local_branch_path, remote_url)
        self.assertBranchesMatch(self.local_branch_path, remote_url)

    @deferToThread
    def test_push_to_existing_branch(self):
        """Pushing to an existing branch must work."""
        # Initial push.
        remote_url = self.getTransportURL('~testuser/+junk/test-branch')
        self.push(self.local_branch_path, remote_url)
        remote_revision = self.getLastRevision(remote_url)
        self.assertEqual(remote_revision, 'rev1')
        # Add a single revision to the local branch.
        tree = WorkingTree.open(self.local_branch.base)
        tree.commit('Empty commit', rev_id='rev2')
        # Push the new revision.
        self.push(self.local_branch_path, remote_url)
        self.assertBranchesMatch(self.local_branch_path, remote_url)

    @deferToThread
    def test_rename_branch(self):
        """
        Branches should be able to be renamed in the Launchpad webapp, and
        those renames should be immediately reflected in subsequent SFTP
        connections.

        Also, the renames may happen in the database for other reasons, e.g.
        if the DBA running a one-off script.
        """

        # Push the local branch to the server
        remote_url = self.getTransportURL('~testuser/+junk/test-branch')
        self.push(self.local_branch_path, remote_url)

        # Rename branch in the database
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch('testuser', None, 'test-branch')
        branch.name = 'renamed-branch'
        LaunchpadZopelessTestSetup().txn.commit()

        # Check that it's not at the old location.
        self.assertNotBranch(
            self.getTransportURL('~testuser/+junk/test-branch'))

        # Check that it *is* at the new location.
        self.assertBranchesMatch(
            self.local_branch_path,
            self.getTransportURL('~testuser/+junk/renamed-branch'))


    @deferToThread
    def test_rename_product(self):
        # Push the local branch to the server
        remote_url = self.getTransportURL('~testuser/+junk/test-branch')
        self.push(self.local_branch_path, remote_url)

        # Assign to a different product in the database. This is effectively a
        # rename as far as bzr is concerned: the URL changes.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch('testuser', None, 'test-branch')
        branch.product = database.Product.byName('firefox')
        LaunchpadZopelessTestSetup().txn.commit()

        self.assertNotBranch(
            self.getTransportURL('~testuser/+junk/test-branch'))

        self.assertBranchesMatch(
            self.local_branch_path,
            self.getTransportURL('~testuser/firefox/test-branch'))

    @deferToThread
    def test_rename_user(self):
        # Rename person in the database. Again, the URL changes (and so does
        # the username we have to connect as!).
        remote_url = self.getTransportURL('~testuser/+junk/test-branch')
        self.push(self.local_branch_path, remote_url)

        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch('testuser', None, 'test-branch')
        branch.owner.name = 'renamed-user'
        LaunchpadZopelessTestSetup().txn.commit()

        # Check that it's not at the old location.
        self.assertNotBranch(
            self.getTransportURL(
                '~testuser/+junk/test-branch', 'renamed-user'))

        # Check that it *is* at the new location.
        self.assertBranchesMatch(
            self.local_branch_path,
            self.getTransportURL(
                '~renamed-user/+junk/test-branch', 'renamed-user'))

    @deferToThread
    def test_push_team_branch(self):
        remote_url = self.getTransportURL('~testteam/firefox/a-new-branch')
        self.push(self.local_branch_path, remote_url)
        self.assertBranchesMatch(self.local_branch_path, remote_url)

    @deferToThread
    def test_push_new_branch_creates_branch_in_database(self):
        remote_url = self.getTransportURL(
            '~testuser/+junk/totally-new-branch')
        self.push(self.local_branch_path, remote_url)

        # Retrieve the branch from the database.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch(
            'testuser', None, 'totally-new-branch')
        LaunchpadZopelessTestSetup().txn.abort()

        self.assertEqual(
            '~testuser/+junk/totally-new-branch', branch.unique_name)

    @deferToThread
    def test_push_triggers_mirror_request(self):
        # Pushing new data to a branch should trigger a mirror request.
        remote_url = self.getTransportURL(
            '~testuser/+junk/totally-new-branch')
        self.push(self.local_branch_path, remote_url)

        # Retrieve the branch from the database.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch(
            'testuser', None, 'totally-new-branch')
        # Confirm that the branch hasn't had a mirror requested yet. Not core
        # to the test, but helpful for checking internal state.
        self.assertNotEqual(None, branch.next_mirror_time)
        branch.next_mirror_time = None
        LaunchpadZopelessTestSetup().txn.commit()

        # Add a single revision to the local branch.
        tree = WorkingTree.open(self.local_branch.base)
        tree.commit('Empty commit', rev_id='rev2')

        # Push the new revision.
        self.push(self.local_branch_path, remote_url)

        # Retrieve the branch from the database.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch(
            'testuser', None, 'totally-new-branch')
        self.assertNotEqual(None, branch.next_mirror_time)
        LaunchpadZopelessTestSetup().txn.abort()

    @deferToThread
    def test_cant_access_private_branch(self):
        # Trying to get information about a private branch should fail as if
        # the branch doesn't exist.

        # 'salgado' is a member of landscape-developers.
        salgado = database.Person.selectOneBy(name='salgado')
        landscape_dev = database.Person.selectOneBy(
            name='landscape-developers')
        self.assertTrue(
            salgado.inTeam(landscape_dev),
            "salgado should be a member of landscape-developers, but isn't.")

        # Make a private branch.
        branch_url = self.createBazaarBranch(
            'landscape-developers', 'landscape', 'some-branch',
            creator='salgado')
        # Sanity checking that the branch is actually there. We don't care
        # about the result, only that the call succeeds.
        self.getLastRevision(branch_url)

        # Check that testuser can't access the branch.
        remote_url = self.getTransportURL(
            '~landscape-developers/landscape/some-branch')
        self.assertRaises(NotBranchError, self.getLastRevision, remote_url)

    @deferToThread
    def test_can_push_to_existing_hosted_branch(self):
        # If a hosted branch exists in the database, but not on the
        # filesystem, and is writable by the user, then the user is able to
        # push to it.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.makeDatabaseBranch('testuser', 'firefox', 'some-branch')
        remote_url = self.getTransportURL(branch.unique_name)
        LaunchpadZopelessTestSetup().txn.commit()
        self.push(self.local_branch_path, remote_url)
        self.assertBranchesMatch(self.local_branch_path, remote_url)

    @deferToThread
    def test_cant_push_to_existing_mirrored_branch(self):
        # Users cannot push to mirrored branches.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.makeDatabaseBranch(
            'testuser', 'firefox', 'some-branch', BranchType.MIRRORED)
        remote_url = self.getTransportURL(branch.unique_name)
        LaunchpadZopelessTestSetup().txn.commit()
        # The Bazaar client forwards the error from the SFTP server. We don't
        # care about that error for this test, so just swallow it. The error
        # we care about is the one that cmd_push raises.
        self.captureStderr(
            self.assertRaises,
            (BzrCommandError, TransportNotPossible),
            self.push, self.local_branch_path, remote_url)

    @deferToThread
    def test_cant_push_to_existing_unowned_hosted_branch(self):
        # Users can only push to hosted branches that they own.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.makeDatabaseBranch('sabdfl', 'firefox', 'some-branch')
        remote_url = self.getTransportURL(branch.unique_name)
        LaunchpadZopelessTestSetup().txn.commit()
        self.assertRaises(
            (BzrCommandError, TransportNotPossible),
            self.push, self.local_branch_path, remote_url)

    @deferToThread
    def test_cant_push_to_existing_hosted_branch_with_revisions(self):
        # XXX: JonathanLange 2007-08-07, We shoudn't be able to push to
        # branches that have revisions in the database but not actual files:
        # it's a pathological case.
        #
        # However, at the moment we don't provide any checking for this. We
        # should in the future. Until then, this test is disabled.
        return
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.makeDatabaseBranch('testuser', 'firefox', 'some-branch')
        self.addRevisionToBranch(branch)
        remote_url = self.getTransportURL(branch.unique_name)
        LaunchpadZopelessTestSetup().txn.commit()
        self.assertRaises(
            (BzrCommandError, TransportNotPossible),
            self.push, self.local_branch_path, remote_url)

    @deferToThread
    def test_can_push_loom_branch(self):
        # We can push and pull a loom branch.
        tree = self.makeLoomBranchAndTree('loom')
        remote_url = self.getTransportURL('~testuser/+junk/loom')
        self.push('loom', remote_url)
        self.assertBranchesMatch('loom', remote_url)


class SmartserverTests(SSHTestCase):
    """Acceptance tests for the codehosting smartserver."""

    def getDefaultServer(self):
        return make_bzr_ssh_server()

    def makeMirroredBranch(self, person_name, product_name, branch_name):
        ro_branch_url = self.createBazaarBranch(
            person_name, product_name, branch_name)

        # Mark as mirrored.
        LaunchpadZopelessTestSetup().txn.begin()
        branch = self.getDatabaseBranch(
            person_name, product_name, branch_name)
        branch.branch_type = BranchType.MIRRORED
        branch.url = "http://example.com/smartservertest/branch"
        LaunchpadZopelessTestSetup().txn.commit()
        return ro_branch_url

    @deferToThread
    def test_can_read_readonly_branch(self):
        # We can get information from a read-only branch.
        ro_branch_url = self.createBazaarBranch(
            'sabdfl', '+junk', 'ro-branch')
        revision = bzrlib.branch.Branch.open(ro_branch_url).last_revision()
        remote_revision = self.getLastRevision(
            self.getTransportURL('~sabdfl/+junk/ro-branch'))
        self.assertEqual(revision, remote_revision)

    @deferToThread
    def test_cant_write_to_readonly_branch(self):
        # We can't write to a read-only branch.
        ro_branch_url = self.createBazaarBranch(
            'sabdfl', '+junk', 'ro-branch')
        revision = bzrlib.branch.Branch.open(ro_branch_url).last_revision()

        # Create a new revision on the local branch.
        tree = WorkingTree.open(self.local_branch.base)
        tree.commit('Empty commit', rev_id='rev2')

        # Push the local branch to the remote url
        remote_url = self.getTransportURL('~sabdfl/+junk/ro-branch')
        self.assertRaises(
            LockFailed, self.push, self.local_branch_path, remote_url)

    @deferToThread
    def test_can_read_mirrored_branch(self):
        # Users should be able to read mirrored branches that they own.
        # Added to catch bug 126245.
        ro_branch_url = self.makeMirroredBranch(
            'testuser', 'firefox', 'mirror')
        revision = bzrlib.branch.Branch.open(ro_branch_url).last_revision()
        remote_revision = self.getLastRevision(
            self.getTransportURL('~testuser/firefox/mirror'))
        self.assertEqual(revision, remote_revision)

    @deferToThread
    def test_can_read_unowned_mirrored_branch(self):
        # Users should be able to read mirrored branches even if they don't
        # own those branches.
        ro_branch_url = self.makeMirroredBranch('sabdfl', 'firefox', 'mirror')
        revision = bzrlib.branch.Branch.open(ro_branch_url).last_revision()
        remote_revision = self.getLastRevision(
            self.getTransportURL('~sabdfl/firefox/mirror'))
        self.assertEqual(revision, remote_revision)

    @deferToThread
    def test_authserver_error_propagation(self):
        # Errors raised by createBranch on the authserver should be displayed
        # sensibly by the client.  We test this by pushing to a product that
        # does not exist (the other error message possibilities are covered by
        # unit tests).
        remote_url = self.getTransportURL('~sabdfl/no-such-product/branch')
        error = self.assertTransportRaises(
            TransportNotPossible,
            self.push, self.local_branch_path, remote_url)
        self.assertIn("Project 'no-such-product' does not exist.", str(error))


class OOPSReportingSmartserverTests(SSHTestCase):
    """Acceptance tests for the ssh server that involve OOPS reporting."""

    def setUp(self):
        SSHTestCase.setUp(self)
        self._oops_prefix = config.launchpad.errorreports.oops_prefix
        self._errordir = config.launchpad.errorreports.errordir
        self._copy_to_zlog = config.launchpad.errorreports.copy_to_zlog
        errorreports = config.codehosting
        config.launchpad.errorreports.oops_prefix = errorreports.oops_prefix
        config.launchpad.errorreports.errordir = errorreports.errordir
        config.launchpad.errorreports.copy_to_zlog = errorreports.copy_to_zlog

    def tearDown(self):
        SSHTestCase.tearDown(self)
        config.launchpad.errorreports.oops_prefix = self._oops_prefix
        config.launchpad.errorreports.errordir = self._errordir
        config.launchpad.errorreports.copy_to_zlog = self._copy_to_zlog

    def test_oops_reported_on_unhandled_exception(self):
        # We have to examine the oops reports in the main thread because
        # canonical.config.config is a thread-locals object, but we have to do
        # ssh client things in another thread, as the server runs in the
        # twisted reactor in the main thread.

        # Note the last oops reported before we start.
        existing_report = globalErrorUtility.getLastOopsReport()

        real_stderr = sys.stderr
        sys.stderr = StringIO()

        @deferToThread
        def cause_exception_in_ssh_server():
            """Trigger an unhandled exception in the code hosting ssh server.

            What we do is attempt to execute some command other than 'bzr
            serve', which works but is thoroughly arbitrary.
            """
            ssh_client = SSHClient()
            # Connect to unrecognized hosts freely:
            ssh_client.set_missing_host_key_policy(MissingHostKeyPolicy())
            ssh_client.connect(
                'localhost', 22222, 'sabdfl',
                key_filename=os.path.join(os.environ['HOME'], '.ssh/id_dsa'))
            try:
                ssh_client.exec_command('sleep')
            except SSHException:
                pass
            ssh_client.close()

        defer_cause_exception = cause_exception_in_ssh_server()

        def check_new_oops_has_been_reported(ignored):
            """Check that there has been a new OOPS report logged."""
            new_report = globalErrorUtility.getLastOopsReport()
            self.assertNotEqual(new_report, None)
            if existing_report is not None:
                self.assertNotEqual(new_report.id, existing_report.id)
            self.assertIn('Not allowed to execute', new_report.value)

        def restore_stderr(ignored):
            sys.stderr = real_stderr

        return defer_cause_exception.addCallback(
            check_new_oops_has_been_reported).addBoth(restore_stderr)

def make_server_tests(base_suite, servers):
    from canonical.codehosting.tests.helpers import (
        CodeHostingTestProviderAdapter)
    adapter = CodeHostingTestProviderAdapter(servers)
    return adapt_suite(adapter, base_suite)


def make_smoke_tests(base_suite):
    from bzrlib.tests.repository_implementations import (
        RepositoryTestProviderAdapter)
    # We specifically exclude RepositoryFormat7, which is not supported.
    # See bug 173807 for details.
    all_formats = [
        format_registry.get(key) for key in format_registry.keys()
        if not isinstance(format_registry.get(key), RepositoryFormat7)]
    adapter = RepositoryTestProviderAdapter(
        default_transport, None,
        [(format, format._matchingbzrdir) for format in all_formats])
    return adapt_suite(adapter, base_suite)


def test_suite():
    base_suite = unittest.makeSuite(AcceptanceTests)
    suite = unittest.TestSuite()
    suite.addTest(make_server_tests(
            base_suite, [make_sftp_server, make_bzr_ssh_server]))
    suite.addTest(make_server_tests(
            unittest.makeSuite(SmartserverTests), [make_bzr_ssh_server]))
    suite.addTest(make_server_tests(
            unittest.makeSuite(OOPSReportingSmartserverTests),
            [make_bzr_ssh_server]))
    suite.addTest(make_smoke_tests(unittest.makeSuite(SmokeTest)))
    return suite
