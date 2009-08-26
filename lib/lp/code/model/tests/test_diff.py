# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Diff, etc."""

__metaclass__ = type


from cStringIO import StringIO
from unittest import TestLoader

from bzrlib.branch import Branch
import transaction

from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.code.model.diff import Diff, PreviewDiff, StaticDiff
from lp.code.model.directbranchcommit import DirectBranchCommit
from lp.code.interfaces.diff import (
    IDiff, IPreviewDiff, IStaticDiff, IStaticDiffSource)
from lp.testing import login, login_person, TestCaseWithFactory


class DiffTestCase(TestCaseWithFactory):

    @staticmethod
    def commitFile(branch, path, contents):
        """Create a commit that updates a file to specified contents.

        This will create or modify the file, as needed.
        """
        committer = DirectBranchCommit(branch, mirrored=True)
        committer.writeFile(path, contents)
        try:
            return committer.commit('committing')
        finally:
            committer.unlock()

    def createExampleMerge(self):
        """Create a merge proposal with conflicts and updates."""
        self.useBzrBranches()
        bmp = self.factory.makeBranchMergeProposal()
        bzr_target = self.createBzrBranch(bmp.target_branch)
        self.commitFile(bmp.target_branch, 'foo', 'a\n')
        self.createBzrBranch(bmp.source_branch, bzr_target)
        source_rev_id = self.commitFile(bmp.source_branch, 'foo', 'd\na\nb\n')
        target_rev_id = self.commitFile(bmp.target_branch, 'foo', 'c\na\n')
        return bmp, source_rev_id, target_rev_id

    def checkExampleMerge(self, diff_text):
        """Ensure the diff text matches the values for ExampleMerge."""
        # The source branch added a line "b".
        self.assertIn('+b\n', diff_text)
        # The line "a" was present before any changes were made, so it's not
        # considered added.
        self.assertNotIn('+a\n', diff_text)
        # There's a conflict because the source branch added a line "d", but
        # the target branch added the line "c" in the same place.
        self.assertIn(
            '+<<<<<<< TREE\n c\n+=======\n+d\n+>>>>>>> MERGE-SOURCE\n',
            diff_text)


class TestDiff(DiffTestCase):

    layer = LaunchpadFunctionalLayer

    def test_providesInterface(self):
        verifyObject(IDiff, Diff())

    def _create_diff(self, content):
        # Create a Diff object with the content specified.
        sio = StringIO()
        sio.write(content)
        size = sio.tell()
        sio.seek(0)
        diff = Diff.fromFile(sio, size)
        # Commit to make the alias available for reading.
        transaction.commit()
        return diff

    def test_text_reads_librarian_content(self):
        # IDiff.text will read at most config.diff.max_read_size bytes from
        # the librarian.
        content = "1234567890" * 10
        diff = self._create_diff(content)
        self.assertEqual(content, diff.text)

    def test_oversized_normal(self):
        # A diff smaller than config.diff.max_read_size is not oversized.
        content = "1234567890" * 10
        diff = self._create_diff(content)
        self.assertFalse(diff.oversized)

    def test_text_read_limited_by_config(self):
        # IDiff.text will read at most config.diff.max_read_size bytes from
        # the librarian.
        self.pushConfig("diff", max_read_size=25)
        content = "1234567890" * 10
        diff = self._create_diff(content)
        self.assertEqual(content[:25], diff.text)

    def test_oversized_for_big_diff(self):
        # A diff larger than config.diff.max_read_size is oversized.
        self.pushConfig("diff", max_read_size=25)
        content = "1234567890" * 10
        diff = self._create_diff(content)
        self.assertTrue(diff.oversized)

    def test_mergePreviewFromBranches(self):
        # mergePreviewFromBranches generates the correct diff.
        bmp, source_rev_id, target_rev_id = self.createExampleMerge()
        source_branch = Branch.open(bmp.source_branch.warehouse_url)
        target_branch = Branch.open(bmp.target_branch.warehouse_url)
        diff = Diff.mergePreviewFromBranches(
            source_branch, source_rev_id, target_branch)
        transaction.commit()
        self.checkExampleMerge(diff.text)


class TestStaticDiff(TestCaseWithFactory):
    """Test that StaticDiff objects work."""

    layer = LaunchpadZopelessLayer

    def test_providesInterface(self):
        verifyObject(IStaticDiff, StaticDiff())

    def test_providesSourceInterface(self):
        verifyObject(IStaticDiffSource, StaticDiff)

    def test_acquire_existing(self):
        """Ensure that acquire returns the existing StaticDiff."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.commit('First commit', rev_id='rev1')
        diff1 = StaticDiff.acquire('null:', 'rev1', tree.branch.repository)
        diff2 = StaticDiff.acquire('null:', 'rev1', tree.branch.repository)
        self.assertIs(diff1, diff2)

    def test_acquire_existing_different_repo(self):
        """The existing object is used even if the repository is different."""
        self.useBzrBranches()
        branch1, tree1 = self.create_branch_and_tree('tree1')
        tree1.commit('First commit', rev_id='rev1')
        branch2, tree2 = self.create_branch_and_tree('tree2')
        tree2.pull(tree1.branch)
        diff1 = StaticDiff.acquire('null:', 'rev1', tree1.branch.repository)
        diff2 = StaticDiff.acquire('null:', 'rev1', tree2.branch.repository)
        self.assertTrue(diff1 is diff2)

    def test_acquire_nonexisting(self):
        """A new object is created if there is no existant matching object."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.commit('First commit', rev_id='rev1')
        tree.commit('Next commit', rev_id='rev2')
        diff1 = StaticDiff.acquire('null:', 'rev1', tree.branch.repository)
        diff2 = StaticDiff.acquire('rev1', 'rev2', tree.branch.repository)
        self.assertIsNot(diff1, diff2)

    def test_acquireFromText(self):
        """acquireFromText works as expected.

        It creates a new object if there is none, but uses the existing one
        if possible.
        """
        diff_a = 'a'
        diff_b = 'b'
        static_diff = StaticDiff.acquireFromText('rev1', 'rev2', diff_a)
        self.assertEqual('rev1', static_diff.from_revision_id)
        self.assertEqual('rev2', static_diff.to_revision_id)
        static_diff2 = StaticDiff.acquireFromText('rev1', 'rev2', diff_b)
        self.assertIs(static_diff, static_diff2)

    def test_acquireFromTextEmpty(self):
        static_diff = StaticDiff.acquireFromText('rev1', 'rev2', '')
        self.assertEqual('', static_diff.diff.text)

    def test_acquireFromTextNonEmpty(self):
        static_diff = StaticDiff.acquireFromText('rev1', 'rev2', 'abc')
        transaction.commit()
        self.assertEqual('abc', static_diff.diff.text)


class TestPreviewDiff(DiffTestCase):
    """Test that PreviewDiff objects work."""

    layer = LaunchpadFunctionalLayer

    def _createProposalWithPreviewDiff(self, dependent_branch=None,
                                       content='content'):
        # Create and return a preview diff.
        mp = self.factory.makeBranchMergeProposal(
            dependent_branch=dependent_branch)
        login_person(mp.registrant)
        if dependent_branch is None:
            dependent_revision_id = None
        else:
            dependent_revision_id = u'rev-c'
        mp.updatePreviewDiff(
            content, u'stat', u'rev-a', u'rev-b',
            dependent_revision_id=dependent_revision_id)
        # Make sure the librarian file is written.
        transaction.commit()
        return mp

    def test_providesInterface(self):
        # In order to test the interface provision, we need to make sure that
        # the associated diff object that is delegated to is also created.
        mp = self._createProposalWithPreviewDiff()
        verifyObject(IPreviewDiff, mp.preview_diff)

    def test_canonicalUrl(self):
        # The canonical_url of the merge diff is '+preview' after the
        # canonical_url of the merge proposal itself.
        mp = self._createProposalWithPreviewDiff()
        self.assertEqual(
            canonical_url(mp) + '/+preview-diff',
            canonical_url(mp.preview_diff))

    def test_empty_diff(self):
        # Once the source is merged into the target, the diff between the
        # branches will be empty.
        mp = self._createProposalWithPreviewDiff(content=None)
        preview = mp.preview_diff
        self.assertIs(None, preview.diff_text)
        self.assertEqual(0, preview.diff_lines_count)
        self.assertEqual(mp, preview.branch_merge_proposal)

    def test_stale_allInSync(self):
        # If the revision ids of the preview diff match the source and target
        # branches, then not stale.
        mp = self._createProposalWithPreviewDiff()
        # Log in an admin to avoid the launchpad.Edit needs for last_scanned.
        login('admin@canonical.com')
        mp.source_branch.last_scanned_id = 'rev-a'
        mp.target_branch.last_scanned_id = 'rev-b'
        self.assertEqual(False, mp.preview_diff.stale)

    def test_stale_sourceNewer(self):
        # If the source branch has a different rev id, the diff is stale.
        mp = self._createProposalWithPreviewDiff()
        # Log in an admin to avoid the launchpad.Edit needs for last_scanned.
        login('admin@canonical.com')
        mp.source_branch.last_scanned_id = 'rev-c'
        mp.target_branch.last_scanned_id = 'rev-b'
        self.assertEqual(True, mp.preview_diff.stale)

    def test_stale_targetNewer(self):
        # If the source branch has a different rev id, the diff is stale.
        mp = self._createProposalWithPreviewDiff()
        # Log in an admin to avoid the launchpad.Edit needs for last_scanned.
        login('admin@canonical.com')
        mp.source_branch.last_scanned_id = 'rev-a'
        mp.target_branch.last_scanned_id = 'rev-d'
        self.assertEqual(True, mp.preview_diff.stale)

    def test_stale_dependentBranch(self):
        # If the merge proposal has a dependent branch, then the tip revision
        # id of the dependent branch is also checked.
        dep_branch = self.factory.makeProductBranch()
        mp = self._createProposalWithPreviewDiff(dep_branch)
        # Log in an admin to avoid the launchpad.Edit needs for last_scanned.
        login('admin@canonical.com')
        mp.source_branch.last_scanned_id = 'rev-a'
        mp.target_branch.last_scanned_id = 'rev-b'
        dep_branch.last_scanned_id = 'rev-c'
        self.assertEqual(False, mp.preview_diff.stale)
        dep_branch.last_scanned_id = 'rev-d'
        self.assertEqual(True, mp.preview_diff.stale)

    def test_fromBMP(self):
        # Correctly generates a PreviewDiff from a BranchMergeProposal.
        bmp, source_rev_id, target_rev_id = self.createExampleMerge()
        preview = PreviewDiff.fromBMP(bmp)
        self.assertEqual(source_rev_id, preview.source_revision_id)
        self.assertEqual(target_rev_id, preview.target_revision_id)
        transaction.commit()
        self.checkExampleMerge(preview.text)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
