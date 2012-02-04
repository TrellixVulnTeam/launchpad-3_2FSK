__metaclass__ = type

import logging

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, format_registry
from bzrlib.plugins.loom.branch import loomify
from bzrlib.repofmt.groupcompress_repo import (
    RepositoryFormat2a, RepositoryFormat2aSubtree)
from bzrlib.revision import NULL_REVISION
from bzrlib.transport import get_transport

from lp.code.bzr import (
    BranchFormat,
    branch_changed,
    get_branch_formats,
    RepositoryFormat,
    )
from lp.codehosting.bzrutils import read_locked
from lp.codehosting.upgrade import (
    Upgrader,
    )
from lp.testing import (
    temp_dir,
    TestCaseWithFactory,
    )
from lp.testing.layers import ZopelessDatabaseLayer


class TestUpgrader(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def prepare(self, format='pack-0.92', loomify_branch=False):
        self.useBzrBranches(direct_database=True)
        branch, tree = self.create_branch_and_tree(format=format)
        tree.commit(
            'foo', rev_id='prepare-commit', committer='jrandom@example.com')
        if loomify_branch:
            loomify(tree.branch)
            bzr_branch = tree.bzrdir.open_branch()
        else:
            bzr_branch = tree.branch
        return self.getUpgrader(bzr_branch, branch)

    def getUpgrader(self, bzr_branch, branch):
        target_dir = self.useContext(temp_dir())
        return Upgrader(
            branch, target_dir, logging.getLogger(), bzr_branch)

    def addTreeReference(self, tree):
        sub_branch = BzrDir.create_branch_convenience(
            tree.bzrdir.root_transport.clone('sub').base)
        tree.add_reference(sub_branch.bzrdir.open_workingtree())
        tree.commit('added tree reference', committer='jrandom@example.com')

    def check_branch(self, upgraded, branch_format=BranchFormat.BZR_BRANCH_7,
                     repository_format=RepositoryFormat.BZR_CHK_2A):
        """Check that a branch matches expected post-upgrade formats."""
        control, branch, repository = get_branch_formats(upgraded)
        self.assertEqual(repository, repository_format)
        self.assertEqual(branch, branch_format)

    def test_simple_upgrade(self):
        """Upgrade a pack-0.92 branch."""
        upgrader = self.prepare()
        upgrader.start_upgrade()
        upgrader.finish_upgrade()
        self.check_branch(
            upgrader.branch.getBzrBranch())

    def test_subtree_upgrade(self):
        """Upgrade a pack-0.92-subtree branch."""
        upgrader = self.prepare('pack-0.92-subtree')
        upgrader.start_upgrade()
        upgrader.finish_upgrade()
        self.check_branch(upgrader.branch.getBzrBranch())

    def test_upgrade_loom(self):
        """Upgrade a loomified pack-0.92 branch."""
        upgrader = self.prepare(loomify_branch=True)
        upgrader.start_upgrade()
        upgrader.finish_upgrade()
        upgraded = upgrader.branch.getBzrBranch()
        self.check_branch(upgraded, BranchFormat.BZR_LOOM_2)

    def test_upgrade_subtree_loom(self):
        """Upgrade a loomified pack-0.92-subtree branch."""
        upgrader = self.prepare('pack-0.92-subtree', loomify_branch=True)
        upgrader.start_upgrade()
        upgrader.finish_upgrade()
        upgraded = upgrader.branch.getBzrBranch()
        self.check_branch(upgraded, BranchFormat.BZR_LOOM_2)

    def test_default_repo_format(self):
        """By default, the 2a repo format is selected."""
        upgrader = self.prepare()
        target_format = upgrader.get_target_format()
        self.assertIs(
            target_format._repository_format.__class__, RepositoryFormat2a)

    def test_subtree_format_repo_format(self):
        """Even subtree formats use 2a if they don't have tree references."""
        self.useBzrBranches(direct_database=True)
        format = format_registry.make_bzrdir('pack-0.92-subtree')
        branch, tree = self.create_branch_and_tree(format=format)
        upgrader = self.getUpgrader(tree.branch, branch)
        with read_locked(upgrader.bzr_branch):
            target_format = upgrader.get_target_format()
        self.assertIs(
            target_format._repository_format.__class__, RepositoryFormat2a)

    def test_tree_reference_repo_format(self):
        """Repos with tree references get 2aSubtree."""
        self.useBzrBranches(direct_database=True)
        format = format_registry.make_bzrdir('pack-0.92-subtree')
        branch, tree = self.create_branch_and_tree(format=format)
        upgrader = self.getUpgrader(tree.branch, branch)
        self.addTreeReference(tree)
        with read_locked(upgrader.bzr_branch):
            target_format = upgrader.get_target_format()
        self.assertIs(
            target_format._repository_format.__class__,
            RepositoryFormat2aSubtree)

    def test_add_upgraded_branch_preserves_tip(self):
        """Fetch-based upgrade preserves branch tip."""
        upgrader = self.prepare('pack-0.92-subtree')
        with read_locked(upgrader.bzr_branch):
            upgrader.start_upgrade()
            upgraded = upgrader.add_upgraded_branch().open_branch()
        self.assertEqual('prepare-commit', upgraded.last_revision())

    def test_create_upgraded_repository_preserves_dead_heads(self):
        """Fetch-based upgrade preserves heads in the repository."""
        upgrader = self.prepare('pack-0.92-subtree')
        upgrader.bzr_branch.set_last_revision_info(0, NULL_REVISION)
        with read_locked(upgrader.bzr_branch):
            upgrader.create_upgraded_repository()
        upgraded = upgrader.get_bzrdir().open_repository()
        self.assertEqual(
            'foo', upgraded.get_revision('prepare-commit').message)

    def test_create_upgraded_repository_uses_target_subdir(self):
        upgrader = self.prepare()
        with read_locked(upgrader.bzr_branch):
            upgrader.create_upgraded_repository()
        upgrader.get_bzrdir().open_repository()

    def test_add_upgraded_branch_preserves_tags(self):
        """Fetch-based upgrade preserves heads in the repository."""
        upgrader = self.prepare('pack-0.92-subtree')
        upgrader.bzr_branch.tags.set_tag('steve', 'rev-id')
        with read_locked(upgrader.bzr_branch):
            upgrader.start_upgrade()
            upgraded = upgrader.add_upgraded_branch().open_branch()
        self.assertEqual('rev-id', upgraded.tags.lookup_tag('steve'))

    def test_has_tree_references(self):
        """Detects whether repo contains actual tree references."""
        self.useBzrBranches(direct_database=True)
        format = format_registry.make_bzrdir('pack-0.92-subtree')
        branch, tree = self.create_branch_and_tree(format=format)
        upgrader = self.getUpgrader(tree.branch, branch)
        with read_locked(tree.branch.repository):
            self.assertFalse(upgrader.has_tree_references())
        self.addTreeReference(tree)
        with read_locked(tree.branch.repository):
            self.assertTrue(upgrader.has_tree_references())

    def test_use_subtree_format_for_tree_references(self):
        """Subtree references cause RepositoryFormat2aSubtree to be used."""
        self.useBzrBranches(direct_database=True)
        format = format_registry.make_bzrdir('pack-0.92-subtree')
        branch, tree = self.create_branch_and_tree(format=format)
        sub_branch = BzrDir.create_branch_convenience(
            tree.bzrdir.root_transport.clone('sub').base, format=format)
        tree.add_reference(sub_branch.bzrdir.open_workingtree())
        tree.commit('added tree reference', committer='jrandom@example.org')
        upgrader = self.getUpgrader(tree.branch, branch)
        with read_locked(tree.branch):
            upgrader.create_upgraded_repository()
        upgraded = upgrader.get_bzrdir().open_repository()
        self.assertIs(RepositoryFormat2aSubtree, upgraded._format.__class__)

    def test_swap_in(self):
        upgrader = self.prepare()
        upgrader.start_upgrade()
        upgrader.add_upgraded_branch()
        upgrader.swap_in()
        self.check_branch(upgrader.branch.getBzrBranch())

    def test_swap_in_retains_original(self):
        upgrader = self.prepare()
        upgrader.start_upgrade()
        upgrader.add_upgraded_branch()
        upgrader.swap_in()
        t = get_transport(upgrader.branch.getInternalBzrUrl())
        t = t.clone('backup.bzr')
        branch = Branch.open_from_transport(t)
        self.check_branch(branch, BranchFormat.BZR_BRANCH_6,
                          RepositoryFormat.BZR_KNITPACK_1)

    def test_start_all_upgrades(self):
        upgrader = self.prepare()
        branch_changed(upgrader.branch, upgrader.bzr_branch)
        Upgrader.start_all_upgrades(
            upgrader.target_dir, upgrader.logger)
        upgraded = upgrader.get_bzrdir().open_repository()
        self.assertIs(RepositoryFormat2a, upgraded._format.__class__)
        self.assertEqual(
            'foo', upgraded.get_revision('prepare-commit').message)

    def test_finish_upgrade_fetches(self):
        upgrader = self.prepare()
        upgrader.start_upgrade()
        tree = upgrader.bzr_branch.create_checkout('tree', lightweight=True)
        bar_id = tree.commit('bar', committer='jrandom@example.org')
        upgrader.finish_upgrade()
        upgraded = upgrader.branch.getBzrBranch()
        self.assertEqual(
            'bar', upgraded.repository.get_revision(bar_id).message)

    def test_finish_upgrade_updates_formats(self):
        upgrader = self.prepare()
        upgrader.start_upgrade()
        upgrader.finish_upgrade()
        self.assertEqual(
            upgrader.branch.branch_format, BranchFormat.BZR_BRANCH_7)
        self.assertEqual(
            upgrader.branch.repository_format, RepositoryFormat.BZR_CHK_2A)

    def test_finish_all_upgrades(self):
        upgrader = self.prepare()
        branch_changed(upgrader.branch, upgrader.bzr_branch)
        upgrader.start_upgrade()
        Upgrader.finish_all_upgrades(
            upgrader.target_dir, upgrader.logger)
        upgraded = upgrader.branch.getBzrBranch()
        self.assertIs(RepositoryFormat2a,
            upgraded.repository._format.__class__)
        self.assertEqual(
            'foo', upgraded.repository.get_revision('prepare-commit').message)
