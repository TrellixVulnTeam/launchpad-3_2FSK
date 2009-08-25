# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation classes for IDiff, etc."""

__metaclass__ = type
__all__ = ['Diff', 'PreviewDiff', 'StaticDiff']

from cStringIO import StringIO

from bzrlib.branch import Branch
from bzrlib.diff import show_diff_trees
from bzrlib.merge import Merger, Merge3Merger
from lazr.delegates import delegates
from sqlobject import ForeignKey, IntCol, StringCol
from storm.locals import Int, Reference, Storm, Unicode
from zope.component import getUtility
from zope.interface import classProvides, implements

from canonical.config import config
from canonical.database.sqlbase import SQLBase
from canonical.uuid import generate_uuid

from lp.code.interfaces.diff import (
    IDiff, IPreviewDiff, IStaticDiff, IStaticDiffSource)
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet


class Diff(SQLBase):
    """See `IDiff`."""

    implements(IDiff)

    diff_text = ForeignKey(foreignKey='LibraryFileAlias')

    diff_lines_count = IntCol()

    diffstat = StringCol()

    added_lines_count = IntCol()

    removed_lines_count = IntCol()

    @property
    def text(self):
        if self.diff_text is None:
            return ''
        else:
            self.diff_text.open()
            try:
                return self.diff_text.read(config.diff.max_read_size)
            finally:
                self.diff_text.close()

    @property
    def oversized(self):
        # If the size of the content of the librarian file is over the
        # config.diff.max_read_size, then we have an oversized diff.
        if self.diff_text is None:
            return False
        diff_size = self.diff_text.content.filesize
        return diff_size > config.diff.max_read_size

    @classmethod
    def mergePreviewFromBranches(cls, source_branch, source_revision,
                                 target_branch):
        """Generate a merge preview diff from the supplied branches.

        :param source_branch: The branch that will be merged.
        :param source_revision: The revision_id of the revision that will be
            merged.
        :param target_branch: The branch that the source will merge into.
        :return: A Diff for a merge preview.
        """
        source_branch.lock_read()
        target_branch.lock_write()
        try:
            merge_target = target_branch.basis_tree()
            merger = Merger.from_revision_ids(
                None, merge_target, source_revision,
                other_branch=source_branch, tree_branch=target_branch)
            merger.merge_type = Merge3Merger
            transform = merger.make_merger().make_preview_transform()
            try:
                to_tree = transform.get_preview_tree()
                return Diff.fromTrees(merge_target, to_tree)
            finally:
                transform.finalize()
        finally:
            source_branch.unlock()
            target_branch.unlock()

    @classmethod
    def fromTrees(klass, from_tree, to_tree, filename=None):
        """Create a Diff from two Bazaar trees.

        :from_tree: The old tree in the diff.
        :to_tree: The new tree in the diff.
        """
        diff_content = StringIO()
        show_diff_trees(from_tree, to_tree, diff_content, old_label='',
                        new_label='')
        size = diff_content.tell()
        diff_content.seek(0)
        return klass.fromFile(diff_content, size, filename)

    @classmethod
    def fromFile(klass, diff_content, size, filename=None):
        """Create a Diff from a textual diff.

        :diff_content: The diff text
        :size: The number of bytes in the diff text.
        """
        if size == 0:
            diff_text = None
        else:
            if filename is None:
                filename = generate_uuid() + '.txt'
            diff_text = getUtility(ILibraryFileAliasSet).create(
                filename, size, diff_content, 'text/x-diff')
        return klass(diff_text=diff_text)

    def _update(self, diff_content, diffstat, filename):
        """Update the diff content and diffstat."""
        # XXX: Tim Penhey, 2009-02-12, bug 328271
        # If the branch is private we should probably use the restricted
        # librarian.
        if diff_content is None or len(diff_content) == 0:
            self.diff_text = None
            self.diff_lines_count = 0
        else:
            self.diff_text = getUtility(ILibraryFileAliasSet).create(
                filename, len(diff_content), StringIO(diff_content),
                'text/x-diff')
            self.diff_lines_count = len(diff_content.strip().split('\n'))
        self.diffstat = diffstat


class StaticDiff(SQLBase):
    """A diff from one revision to another."""

    implements(IStaticDiff)

    classProvides(IStaticDiffSource)

    from_revision_id = StringCol()

    to_revision_id = StringCol()

    diff = ForeignKey(foreignKey='Diff', notNull=True)

    @classmethod
    def acquire(klass, from_revision_id, to_revision_id, repository,
                filename=None):
        """See `IStaticDiffSource`."""
        existing_diff = klass.selectOneBy(
            from_revision_id=from_revision_id, to_revision_id=to_revision_id)
        if existing_diff is not None:
            return existing_diff
        from_tree = repository.revision_tree(from_revision_id)
        to_tree = repository.revision_tree(to_revision_id)
        diff = Diff.fromTrees(from_tree, to_tree, filename)
        return klass(
            from_revision_id=from_revision_id, to_revision_id=to_revision_id,
            diff=diff)

    @classmethod
    def acquireFromText(klass, from_revision_id, to_revision_id, text,
                        filename=None):
        """See `IStaticDiffSource`."""
        existing_diff = klass.selectOneBy(
            from_revision_id=from_revision_id, to_revision_id=to_revision_id)
        if existing_diff is not None:
            return existing_diff
        diff = Diff.fromFile(StringIO(text), len(text), filename)
        return klass(
            from_revision_id=from_revision_id, to_revision_id=to_revision_id,
            diff=diff)

    def destroySelf(self):
        diff = self.diff
        SQLBase.destroySelf(self)
        diff.destroySelf()


class PreviewDiff(Storm):
    """See `IPreviewDiff`."""
    implements(IPreviewDiff)
    delegates(IDiff, context='diff')
    __storm_table__ = 'PreviewDiff'


    id = Int(primary=True)

    diff_id = Int(name='diff')
    diff = Reference(diff_id, 'Diff.id')

    source_revision_id = Unicode(allow_none=False)

    target_revision_id = Unicode(allow_none=False)

    dependent_revision_id = Unicode()

    conflicts = Unicode()

    branch_merge_proposal = Reference(
        "PreviewDiff.id", "BranchMergeProposal.preview_diff_id",
        on_remote=True)

    @classmethod
    def fromBMP(cls, bmp):
        """Create a PreviewDiff from a BranchMergeProposal.

        Includes a diff from the source to the target.
        :param bmp: The BranchMergeProposal to generate a PreviewDiff for.
        :return: A PreviewDiff.
        """
        source_branch = Branch.open(bmp.source_branch.warehouse_url)
        source_revision = source_branch.last_revision()
        target_branch = Branch.open(bmp.target_branch.warehouse_url)
        target_revision = target_branch.last_revision()
        preview = cls()
        preview.source_revision_id = source_revision.decode('utf-8')
        preview.target_revision_id = target_revision.decode('utf-8')
        preview.diff = Diff.mergePreviewFromBranches(
            source_branch, source_revision, target_branch)
        return preview

    def update(self, diff_content, diffstat,
               source_revision_id, target_revision_id,
               dependent_revision_id, conflicts):
        self.source_revision_id = source_revision_id
        self.target_revision_id = target_revision_id
        self.dependent_revision_id = dependent_revision_id
        self.conflicts = conflicts

        filename = generate_uuid() + '.txt'
        self.diff._update(diff_content, diffstat, filename)

    @property
    def stale(self):
        """See `IPreviewDiff`."""
        # A preview diff is stale if the revision ids used to make the diff
        # are different from the tips of the source or target branches.
        bmp = self.branch_merge_proposal
        is_stale = False
        if (self.source_revision_id != bmp.source_branch.last_scanned_id or
            self.target_revision_id != bmp.target_branch.last_scanned_id):
            # This is the simple frequent case.
            return True

        # More complex involves the dependent branch too.
        if (bmp.dependent_branch is not None and
            (self.dependent_revision_id !=
             bmp.dependent_branch.last_scanned_id)):
            return True
        else:
            return False
