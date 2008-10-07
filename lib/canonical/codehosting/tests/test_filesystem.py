# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Tests for the virtual filesystem presented by Launchpad codehosting."""

__metaclass__ = type

import unittest
import stat

from bzrlib import errors
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.urlutils import escape

from canonical.codehosting import branch_id_to_path
from canonical.codehosting.tests.servers import make_launchpad_server


class TestBranchIDToPath(unittest.TestCase):
    """Tests for branch_id_to_path."""

    def test_branch_id_to_path(self):
        # branch_id_to_path converts an integer branch ID into a path of four
        # segments, with each segment being a hexadecimal number.
        self.assertEqual('00/00/00/00', branch_id_to_path(0))
        self.assertEqual('00/00/00/01', branch_id_to_path(1))
        arbitrary_large_id = 6731
        assert "%x" % arbitrary_large_id == '1a4b', (
            "The arbitrary large id is not what we expect (1a4b): %s"
            % (arbitrary_large_id))
        self.assertEqual('00/00/1a/4b', branch_id_to_path(6731))


class TestFilesystem(TestCaseWithTransport):
    # XXX: JonathanLange 2008-10-07 bug=267013: Many of these tests duplicate
    # tests in test_branchfs and test_transport. We should review the tests
    # and remove the ones that aren't needed.

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.server = make_launchpad_server()
        self.server.setUp()
        self.addCleanup(self.server.tearDown)

    def getTransport(self, relpath=None):
        return self.server.getTransport(relpath)

    def test_remove_branch_directory(self):
        # Make some directories under ~testuser/+junk (i.e. create some empty
        # branches)
        transport = self.getTransport('~testuser/+junk')
        transport.mkdir('foo')
        transport.mkdir('bar')
        self.failUnless(stat.S_ISDIR(transport.stat('foo').st_mode))
        self.failUnless(stat.S_ISDIR(transport.stat('bar').st_mode))

        # Try to remove a branch directory, which is not allowed.
        self.assertRaises(
            errors.PermissionDenied, transport.rmdir, 'foo')

        # The 'foo' directory is still listed.
        self.assertTrue(transport.has('bar'))
        self.assertTrue(transport.has('foo'))

    def test_make_invalid_user_directory(self):
        # The top-level directory must always be of the form '~user'. However,
        # sometimes a transport will ask to look at files that aren't of that
        # form. In that case, the transport is denied permission.
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied, transport.mkdir, 'apple')

    def test_make_valid_user_directory(self):
        # Making a top-level directory is not supported by the Launchpad
        # transport.
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied, transport.mkdir, '~apple')

    def test_make_existing_user_directory(self):
        # Making a user directory raises an error. We don't really care what
        # the error is, but it should be one of FileExists,
        # TransportNotPossible or NoSuchFile
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied, transport.mkdir, '~testuser')

    def test_mkdir_not_team_member_error(self):
        # You can't make a branch under the directory of a team that you don't
        # belong to.
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied,
            transport.mkdir, '~not-my-team/firefox/new-branch')

    def test_make_team_branch_directory(self):
        # You can make a branch directory under a team directory that you are
        # a member of (so long as it's a real product).
        transport = self.getTransport()
        transport.mkdir('~testteam/firefox/shiny-new-thing')
        self.assertTrue(
            transport.has('~testteam/firefox/shiny-new-thing'))

    def test_make_team_junk_branch_directory(self):
        # Teams do not have +junk products
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied,
            transport.mkdir, '~testteam/+junk/new-branch')

    def test_make_product_directory_for_nonexistent_product(self):
        # Making a branch directory for a non-existent product is not allowed.
        # Products must first be registered in Launchpad.
        transport = self.getTransport()
        self.assertRaises(
            errors.PermissionDenied,
            transport.mkdir, '~testuser/no-such-product/new-branch')

    def test_make_branch_directory(self):
        # We allow users to create new branches by pushing them beneath an
        # existing product directory.
        transport = self.getTransport()
        transport.mkdir('~testuser/firefox/banana')
        self.assertTrue(transport.has('~testuser/firefox/banana'))

    def test_make_junk_branch(self):
        # Users can make branches beneath their '+junk' folder.
        transport = self.getTransport()
        transport.mkdir('~testuser/+junk/banana')
        # See comment in test_make_branch_directory.
        self.assertTrue(transport.has('~testuser/+junk/banana'))

    def test_get_stacking_policy(self):
        # A stacking policy control file is served underneath product
        # directories for products that have a default stacked-on branch.
        transport = self.getTransport()
        control_file = transport.get_bytes(
            '~testuser/evolution/.bzr/control.conf')
        self.assertEqual(
            'default_stack_on = /~vcs-imports/evolution/main',
            control_file.strip())

    def test_can_open_product_control_dir(self):
        # The stacking policy lives in a bzrdir in the product directory.
        # Bazaar needs to be able to open this bzrdir.
        transport = self.getTransport().clone('~testuser/evolution')
        found_bzrdir = BzrDir.open_from_transport(transport)
        # We really just want to test that the above line doesn't raise an
        # exception. However, we'll also check that we get the bzrdir that we
        # expected.
        expected_url = transport.clone('.bzr').base
        self.assertEqual(expected_url, found_bzrdir.transport.base)

    def test_directory_inside_branch(self):
        # We allow users to create new branches by pushing them beneath an
        # existing product directory.
        transport = self.getTransport()
        transport.mkdir('~testuser/firefox/banana')
        transport.mkdir('~testuser/firefox/banana/.bzr')
        self.assertTrue(transport.has('~testuser/firefox/banana'))
        self.assertTrue(transport.has('~testuser/firefox/banana/.bzr'))

    def test_bzr_backup_directory_inside_branch(self):
        # Bazaar sometimes needs to create .bzr.backup directories directly
        # underneath the branch directory. Thus, we allow the creation of
        # .bzr.backup directories. The .bzr.backup directory is a deprecated
        # name. Now Bazaar uses 'backup.bzr'.
        transport = self.getTransport()
        transport.mkdir('~testuser/firefox/banana')
        transport.mkdir('~testuser/firefox/banana/.bzr.backup')
        self.assertTrue(transport.has('~testuser/firefox/banana'))
        self.assertTrue(
            transport.has('~testuser/firefox/banana/.bzr.backup'))

    def test_backup_bzr_directory_inside_branch(self):
        # Bazaar sometimes needs to create backup.bzr directories directly
        # underneath the branch directory. This is alternative name for the
        # backup.bzr directory.
        transport = self.getTransport()
        transport.mkdir('~testuser/firefox/banana')
        transport.mkdir('~testuser/firefox/banana/backup.bzr')
        self.assertTrue(transport.has('~testuser/firefox/banana'))
        self.assertTrue(
            transport.has('~testuser/firefox/banana/backup.bzr'))

    def test_non_bzr_directory_inside_branch(self):
        # Users can only create Bazaar control directories (e.g. '.bzr')
        # inside a branch. Other directories are strictly forbidden.
        transport = self.getTransport()
        transport.mkdir('~testuser/+junk/banana')
        self.assertRaises(
            errors.PermissionDenied,
            transport.mkdir, '~testuser/+junk/banana/republic')

    def test_non_bzr_file_inside_branch(self):
        # Users can only create Bazaar control directories (e.g. '.bzr')
        # inside a branch. Files are not allowed.
        transport = self.getTransport()
        transport.mkdir('~testuser/+junk/banana')
        self.assertRaises(
            errors.PermissionDenied,
            transport.put_bytes, '~testuser/+junk/banana/README', 'Hello!')

    def test_rename_to_non_bzr_directory_fails(self):
        # Users cannot create an allowed directory (e.g. '.bzr' or
        # '.bzr.backup') and then rename it to something that's not allowed
        # (e.g. 'republic').
        transport = self.getTransport()
        transport.mkdir('~testuser/firefox/banana')
        transport.mkdir('~testuser/firefox/banana/.bzr')
        self.assertRaises(
            errors.PermissionDenied,
            transport.rename, '~testuser/firefox/banana/.bzr',
            '~testuser/firefox/banana/republic')

    def test_make_directory_without_prefix(self):
        # Because the user and product directories don't exist on the
        # filesystem, we can create a branch directory for a product even if
        # there are no existing branches for that product.
        transport = self.getTransport()
        transport.mkdir('~testuser/thunderbird/banana')
        self.assertTrue(transport.has('~testuser/thunderbird/banana'))

    def _getBzrDirTransport(self):
        """Make a .bzr directory in a branch and return a transport for it.

        We use this to test filesystem behaviour beneath the .bzr directory of
        a branch, which generally has fewer constraints and exercises
        different code paths.
        """
        transport = self.getTransport('~testuser/+junk')
        transport.mkdir('branch')
        transport.mkdir('branch/.bzr')
        return transport.clone('branch/.bzr')

    def test_rename_directory_to_existing_directory_fails(self):
        # 'rename dir1 dir2' should fail if 'dir2' exists. Unfortunately, it
        # will only fail if they both contain files/directories.
        transport = self._getBzrDirTransport()
        transport.mkdir('dir1')
        transport.mkdir('dir1/foo')
        transport.mkdir('dir2')
        transport.mkdir('dir2/bar')
        self.assertRaises(errors.FileExists, transport.rename, 'dir1', 'dir2')

    def test_rename_directory_succeeds(self):
        # 'rename dir1 dir2' succeeds if 'dir2' doesn't exist.
        transport = self._getBzrDirTransport()
        transport.mkdir('dir1')
        transport.mkdir('dir1/foo')
        transport.rename('dir1', 'dir2')
        self.assertEqual(['dir2'], transport.list_dir('.'))

    def test_make_directory_twice(self):
        # The transport raises a `FileExists` error if we try to make a
        # directory that already exists.
        transport = self._getBzrDirTransport()
        transport.mkdir('dir1')
        self.assertRaises(errors.FileExists, transport.mkdir, 'dir1')

    def test_url_escaping(self):
        # Transports accept and return escaped URL segments. The literal path
        # we use should be preserved, even if it can be unescaped itself.
        transport = self._getBzrDirTransport()

        # The bug we are checking only occurs if
        # unescape(path).encode('utf-8') != path.
        path = '%41%42%43'
        escaped_path = escape(path)
        content = 'content'
        transport.put_bytes(escaped_path, content)

        # We can use the escaped path to reach the file.
        self.assertEqual(content, transport.get_bytes(escaped_path))

        # We can also use the value that list_dir returns, which may be
        # different from our original escaped path. Note that in this case,
        # returned_path is equivalent but not equal to escaped_path.
        [returned_path] = list(transport.list_dir('.'))
        self.assertEqual(content, transport.get_bytes(returned_path))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
