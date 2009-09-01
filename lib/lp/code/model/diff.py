# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation classes for IDiff, etc."""

__metaclass__ = type
__all__ = ['Diff', 'PreviewDiff', 'StaticDiff']

from cStringIO import StringIO

from bzrlib.branch import Branch
from bzrlib.diff import show_diff_trees
from bzrlib.patches import parse_patches
from bzrlib.merge import Merger, Merge3Merger
from lazr.delegates import delegates
import simplejson
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

    _diffstat = StringCol(dbName='diffstat')

    def _get_diffstat(self):
        if self._diffstat is None:
            return None
        return dict((key, tuple(value))
                    for key, value
                    in simplejson.loads(self._diffstat).items())

    def _set_diffstat(self, diffstat):
        # diffstats should be mappings of path to line counts.
        assert isinstance(diffstat, dict)
        self._diffstat = simplejson.dumps(diffstat)

    diffstat = property(_get_diffstat, _set_diffstat)

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
        :return: A `Diff` for a merge preview.
        """
        source_branch.lock_read()
        try:
            target_branch.lock_read()
            try:
                merge_target = target_branch.basis_tree()
                # Can't use bzrlib.merge.Merger because it fetches.
                graph = target_branch.repository.get_graph(
                    source_branch.repository)
                base_revision = graph.find_unique_lca(
                    source_revision, merge_target.get_revision_id())
                repo = source_branch.repository
                merge_source, merge_base = repo.revision_trees(
                    [source_revision, base_revision])
                merger = Merge3Merger(
                    merge_target, merge_target, merge_base, merge_source,
                    do_merge=False)
                transform =merger.make_preview_transform()
                try:
                    to_tree = transform.get_preview_tree()
                    return Diff.fromTrees(merge_target, to_tree)
                finally:
                    transform.finalize()
            finally:
                target_branch.unlock()
        finally:
            source_branch.unlock()

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
    def fromFile(cls, diff_content, size, filename=None):
        """Create a Diff from a textual diff.

        :diff_content: The diff text
        :size: The number of bytes in the diff text.
        :filename: The filename to store the content with.  Randomly generated
            if not supplied.
        """
        if size == 0:
            diff_text = None
            diff_lines_count = 0
            diff_content_bytes = ''
        else:
            if filename is None:
                filename = generate_uuid() + '.txt'
            diff_text = getUtility(ILibraryFileAliasSet).create(
                filename, size, diff_content, 'text/x-diff')
            diff_content.seek(0)
            diff_content_bytes = diff_content.read(size)
            diff_lines_count = len(diff_content_bytes.strip().split('\n'))
        diffstat = cls.generateDiffstat(diff_content_bytes)
        return cls(diff_text=diff_text, diff_lines_count=diff_lines_count,
                   diffstat=diffstat)

    @staticmethod
    def generateDiffstat(diff_bytes):
        """Generate statistics about the provided diff.

        :param diff_bytes: A unified diff, as bytes.
        :return: A map of {filename: (added_line_count, removed_line_count)}
        """
        file_stats = {}
        for patch in parse_patches(diff_bytes.splitlines(True)):
            path = patch.newname.split('\t')[0]
            file_stats[path] = tuple(patch.stats_values()[:2])
        return file_stats


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
    def fromBranchMergeProposal(cls, bmp):
        """Create a `PreviewDiff` from a `BranchMergeProposal`.

        Includes a diff from the source to the target.
        :param bmp: The `BranchMergeProposal` to generate a `PreviewDiff` for.
        :return: A `PreviewDiff`.
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

    @classmethod
    def create(cls, diff_content, source_revision_id, target_revision_id,
               dependent_revision_id, conflicts):
        """Create a PreviewDiff with specified values.

        :param diff_content: The text of the dift, as bytes.
        :param source_revision_id: The revision_id of the source branch.
        :param target_revision_id: The revision_id of the target branch.
        :param dependent_revision_id: The revision_id of the dependent branch.
        :param conflicts: The conflicts, as text.
        :return: A `PreviewDiff` with specified values.
        """
        preview = cls()
        preview.source_revision_id = source_revision_id
        preview.target_revision_id = target_revision_id
        preview.dependent_revision_id = dependent_revision_id
        preview.conflicts = conflicts

        filename = generate_uuid() + '.txt'
        size = len(diff_content)
        preview.diff = Diff.fromFile(StringIO(diff_content), size, filename)
        return preview

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
