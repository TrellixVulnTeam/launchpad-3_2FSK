# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Commit files straight to bzr branch."""

__metaclass__ = type
__all__ = [
    'ConcurrentUpdateError',
    'DirectBranchCommit',
    ]


import os.path

from bzrlib.branch import Branch
from bzrlib.generate_ids import gen_file_id
from bzrlib.revision import NULL_REVISION
from bzrlib.transform import TransformPreview

from canonical.launchpad.interfaces import IMasterObject
from lp.codehosting.vfs import make_branch_mirrorer


class ConcurrentUpdateError(Exception):
    """Bailout exception for concurrent updates.

    This is raised when committing to a branch would risk overwriting
    concurrent changes made by another party.
    """


class DirectBranchCommit:
    """Commit a set of files straight into a branch.

    Use this to write a set of files into a branch efficiently, without
    caring what was in there before.  The files may be new to the branch
    or they may exist there already; in the latter case they will be
    overwritten.

    The branch is write-locked for the entire lifetime of this object.
    Be sure to call unlock() when done.  This will be done for you as
    part of a successful commit, but unlocking more than once will do no
    harm.

    The trick for this was invented by Aaron Bentley.  It saves having
    to do a full checkout of the branch.
    """
    is_open = False
    is_locked = False
    commit_builder = None

    def __init__(self, db_branch, committer=None, to_mirror=False):
        """Create context for direct commit to branch.

        Before constructing a `DirectBranchCommit`, set up a server that
        allows write access to lp-hosted:/// URLs:

        bzrserver = get_multi_server(write_hosted=True)
        bzrserver.setUp()
        try:
            branchcommit = DirectBranchCommit(branch)
            # ...
        finally:
            bzrserver.tearDown()

        Or in tests, just call `useBzrBranches` before creating a
        `DirectBranchCommit`.

        :param db_branch: a Launchpad `Branch` object.
        :param committer: the `Person` writing to the branch.
        :param to_mirror: If True, write to the mirrored copy of the branch
            instead of the hosted copy.  (Mainly useful for tests)
        """
        self.db_branch = db_branch
        self.to_mirror = to_mirror

        if committer is None:
            committer = db_branch.owner
        self.committer = committer

        # Directories we create on the branch, and their ids.
        self.path_ids = {}

        if to_mirror:
            self.bzrbranch = Branch.open(self.db_branch.warehouse_url)
        else:
            # Have the opening done through a branch mirrorer.  It will
            # pick the right policy.  In case we're writing to a hosted
            # branch stacked on a mirrored branch, the mirrorer knows
            # how to do the right thing.
            mirrorer = make_branch_mirrorer(self.db_branch.branch_type)
            self.bzrbranch = mirrorer.open(self.db_branch.getPullURL())

        self.bzrbranch.lock_write()
        self.is_locked = True

        try:
            self.revision_tree = self.bzrbranch.basis_tree()
            self.transform_preview = TransformPreview(self.revision_tree)
            assert self.transform_preview.find_conflicts() == [], (
                "TransformPreview is not in a consistent state.")

            self.is_open = True
        except:
            self.unlock()
            raise

        self.files = set()

    def _getDir(self, path):
        """Get trans_id for directory "path."  Create if necessary."""
        path_id = self.path_ids.get(path)
        if path_id:
            # This is a path we've just created in the branch.
            return path_id

        if self.revision_tree.path2id(path):
            # This is a path that was already in the branch.
            return self.transform_preview.trans_id_tree_path(path)

        # Look up (or create) parent directory.
        parent_dir, dirname = os.path.split(path)
        if dirname:
            parent_id = self._getDir(parent_dir)
        else:
            parent_id = None

        # Create new directory.
        dirfile_id = gen_file_id(path)
        path_id = self.transform_preview.new_directory(
            dirname, parent_id, dirfile_id)
        self.path_ids[path] = path_id
        return path_id

    def writeFile(self, path, contents):
        """Write file to branch; may be an update or a new file.

        If you write a file multiple times, the first one is used and
        the rest ignored.
        """
        assert self.is_open, "Writing file to closed DirectBranchCommit."

        if path in self.files:
            # We already have this file.  Ignore second write.
            return

        file_id = self.revision_tree.path2id(path)
        if file_id is None:
            parent_path, name = os.path.split(path)
            parent_id = self._getDir(parent_path)
            file_id = gen_file_id(name)
            self.transform_preview.new_file(
                name, parent_id, [contents], file_id)
        else:
            trans_id = self.transform_preview.trans_id_tree_path(path)
            # Delete old contents.  It doesn't actually matter whether
            # we do this before creating the new contents.
            self.transform_preview.delete_contents(trans_id)
            self.transform_preview.create_file([contents], trans_id)

        self.files.add(path)

    def _checkForRace(self):
        """Check if bzrbranch has any changes waiting to be scanned.

        If it does, raise `ConcurrentUpdateError`.
        """
        # A different last_scanned_id does not indicate a race for mirrored
        # branches -- last_scanned_id is a proxy for the mirrored branch.
        if self.to_mirror:
            return
        assert self.is_locked, "Getting revision on un-locked branch."
        last_revision = None
        last_revision = self.bzrbranch.last_revision()
        if last_revision != self.db_branch.last_scanned_id:
            raise ConcurrentUpdateError(
                "Branch has been changed.  Not committing.")

    def commit(self, commit_message):
        """Commit to branch."""
        assert self.is_open, "Committing closed DirectBranchCommit."
        assert self.is_locked, "Not locked at commit time."

        builder = None
        try:
            self._checkForRace()

            preview_tree = self.transform_preview.get_preview_tree()

            rev_id = self.revision_tree.get_revision_id()
            if rev_id == NULL_REVISION:
                parents = []
            else:
                parents = [rev_id]

            builder = self.bzrbranch.get_commit_builder(parents)

            list(builder.record_iter_changes(
                preview_tree, rev_id, self.transform_preview.iter_changes()))

            builder.finish_inventory()

            new_rev_id = builder.commit(commit_message)
            builder = None

            revno, old_rev_id = self.bzrbranch.last_revision_info()
            self.bzrbranch.set_last_revision_info(revno + 1, new_rev_id)

            IMasterObject(self.db_branch).requestMirror()

        finally:
            if builder:
                builder.abort()
            self.unlock()
            self.is_open = False
        return new_rev_id

    def unlock(self):
        """Release commit lock, if held."""
        if self.is_locked:
            self.transform_preview.finalize()
            self.bzrbranch.unlock()
            self.is_locked = False
