# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Branches."""

__metaclass__ = type

from datetime import datetime, timedelta
from unittest import TestLoader

from pytz import UTC

from storm.locals import Store
from sqlobject import SQLObjectNotFound

import transaction

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.launchpad import _
from canonical.launchpad.ftests import (
    ANONYMOUS, login, login_person, logout, syncUpdate)
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.interfaces import IOpenLaunchBag
from canonical.testing import DatabaseFunctionalLayer, LaunchpadZopelessLayer

from lp.blueprints.interfaces.specification import (
    ISpecificationSet, SpecificationDefinitionStatus)
from lp.blueprints.model.specificationbranch import (
    SpecificationBranch)
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.model.bugbranch import BugBranch
from lp.code.bzr import BranchFormat, RepositoryFormat
from lp.code.enums import (
    BranchLifecycleStatus, BranchSubscriptionNotificationLevel, BranchType,
    BranchVisibilityRule, CodeReviewNotificationLevel)
from lp.code.interfaces.branch import (
    BranchCannotBePrivate, BranchCannotBePublic,
    BranchCreatorNotMemberOfOwnerTeam, BranchCreatorNotOwner,
    BranchTargetError, CannotDeleteBranch, DEFAULT_BRANCH_STATUS_IN_LISTING)
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.branchnamespace import IBranchNamespaceSet
from lp.code.interfaces.branchmergeproposal import (
    BRANCH_MERGE_PROPOSAL_FINAL_STATES as FINAL_STATES,
    InvalidBranchMergeProposal)
from lp.code.interfaces.linkedbranch import ICanHasLinkedBranch
from lp.code.interfaces.seriessourcepackagebranch import (
    IFindOfficialBranchLinks)
from lp.code.model.branch import (
    ClearDependentBranch, ClearOfficialPackageBranch, ClearSeriesBranch,
    DeleteCodeImport, DeletionCallable, DeletionOperation,
    update_trigger_modified_fields)
from lp.code.model.branchjob import (
    BranchDiffJob, BranchJob, BranchJobType, ReclaimBranchSpaceJob)
from lp.code.model.branchmergeproposal import (
    BranchMergeProposal)
from lp.code.model.codeimport import CodeImport, CodeImportSet
from lp.code.model.codereviewcomment import CodeReviewComment
from lp.registry.interfaces.person import IPersonSet
from lp.registry.model.product import ProductSet
from lp.registry.model.sourcepackage import SourcePackage
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.testing import (
    run_with_login, TestCase, TestCaseWithFactory, time_counter)
from lp.testing.factory import LaunchpadObjectFactory


class TestCodeImport(TestCase):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('test@canonical.com')
        self.factory = LaunchpadObjectFactory()

    def test_branchCodeImport(self):
        """Ensure the codeImport property works correctly."""
        code_import = self.factory.makeCodeImport()
        branch = code_import.branch
        self.assertEqual(code_import, branch.code_import)
        CodeImportSet().delete(code_import)
        self.assertEqual(None, branch.code_import)


class TestBranchGetRevision(TestCaseWithFactory):
    """Make sure that `Branch.getBranchRevision` works as expected."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.branch = self.factory.makeAnyBranch()

    def _makeRevision(self, revno):
        # Make a revision and add it to the branch.
        rev = self.factory.makeRevision()
        self.branch.createBranchRevision(revno, rev)
        return rev

    def testGetBySequenceNumber(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(sequence=1)
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testGetByRevision(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(revision=rev1)
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testGetByRevisionId(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(
            revision_id=rev1.revision_id)
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testNonExistant(self):
        self._makeRevision(1)
        self.assertTrue(self.branch.getBranchRevision(sequence=2) is None)
        rev2 = self.factory.makeRevision()
        self.assertTrue(self.branch.getBranchRevision(revision=rev2) is None)
        self.assertTrue(
            self.branch.getBranchRevision(revision_id='not found') is None)

    def testInvalidParams(self):
        self.assertRaises(AssertionError, self.branch.getBranchRevision)
        rev1 = self._makeRevision(1)
        self.assertRaises(AssertionError, self.branch.getBranchRevision,
                          sequence=1, revision=rev1,
                          revision_id=rev1.revision_id)
        self.assertRaises(AssertionError, self.branch.getBranchRevision,
                          sequence=1, revision=rev1)
        self.assertRaises(AssertionError, self.branch.getBranchRevision,
                          revision=rev1, revision_id=rev1.revision_id)
        self.assertRaises(AssertionError, self.branch.getBranchRevision,
                          sequence=1, revision_id=rev1.revision_id)


class TestGetMainlineBranchRevisions(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_getMainlineBranchRevisions(self):
        """Only gets the mainline revisions, ignoring the others."""
        branch = self.factory.makeBranch()
        self.factory.makeBranchRevision(branch, 'rev1', 1)
        self.factory.makeBranchRevision(branch, 'rev2', 2)
        self.factory.makeBranchRevision(branch, 'rev2b', None)
        result_set = branch.getMainlineBranchRevisions(
            ['rev1', 'rev2', 'rev3'])
        revid_set = set(
            branch_revision.revision.revision_id for
            branch_revision in result_set)
        self.assertEqual(set(['rev1', 'rev2']), revid_set)

    def test_getMainlineBranchRevisionsWrongBranch(self):
        """Only gets the revisions for this branch, ignoring the others."""
        branch = self.factory.makeBranch()
        other_branch = self.factory.makeBranch()
        self.factory.makeBranchRevision(branch, 'rev1', 1)
        self.factory.makeBranchRevision(other_branch, 'rev1b', 2)
        result_set = branch.getMainlineBranchRevisions(
            ['rev1', 'rev1b'])
        revid_set = set(
            branch_revision.revision.revision_id for
            branch_revision in result_set)
        self.assertEqual(set(['rev1']), revid_set)


class TestBranch(TestCaseWithFactory):
    """Test basic properties about Launchpad database branches."""

    layer = DatabaseFunctionalLayer

    def test_pullURLHosted(self):
        # Hosted branches are pulled from internal Launchpad URLs.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)
        self.assertEqual(
            'lp-hosted:///%s' % branch.unique_name, branch.getPullURL())

    def test_pullURLMirrored(self):
        # Mirrored branches are pulled from their actual URLs -- that's the
        # point.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        self.assertEqual(branch.url, branch.getPullURL())

    def test_pullURLImported(self):
        # Imported branches are pulled from the import servers at locations
        # corresponding to the hex id of the branch being mirrored.
        import_server = config.launchpad.bzr_imports_root_url
        branch = self.factory.makeAnyBranch(branch_type=BranchType.IMPORTED)
        self.assertEqual(
            '%s/%08x' % (import_server, branch.id), branch.getPullURL())

    def test_pullURLRemote(self):
        # We cannot mirror remote branches. getPullURL raises an
        # AssertionError.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.REMOTE)
        self.assertRaises(AssertionError, branch.getPullURL)

    def test_owner_name(self):
        # The owner_name attribute is set to be the name of the branch owner
        # through a db trigger.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            branch.owner.name, removeSecurityProxy(branch).owner_name)

    def test_owner_name_updated(self):
        # When the owner of a branch is changed, the denormalised owner_name
        # attribute is updated too.
        branch = self.factory.makeAnyBranch()
        new_owner = self.factory.makePerson()
        removeSecurityProxy(branch).owner = new_owner
        # Call the function that is normally called through the event system
        # to auto reload the fields updated by the db triggers.
        update_trigger_modified_fields(branch)
        self.assertEqual(
            new_owner.name, removeSecurityProxy(branch).owner_name)

    def test_target_suffix_product(self):
        # The target_suffix for a product branch is the name of the product.
        branch = self.factory.makeProductBranch()
        self.assertEqual(
            branch.product.name, removeSecurityProxy(branch).target_suffix)

    def test_target_suffix_junk(self):
        # The target_suffix for a junk branch is None.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, removeSecurityProxy(branch).target_suffix)

    def test_target_suffix_package(self):
        # A package branch has the target_suffix set to the name of the source
        # package.
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            branch.sourcepackagename.name,
            removeSecurityProxy(branch).target_suffix)

    def test_unique_name_product(self):
        branch = self.factory.makeProductBranch()
        self.assertEqual(
            '~%s/%s/%s' % (
                branch.owner.name, branch.product.name, branch.name),
            branch.unique_name)

    def test_unique_name_junk(self):
        branch = self.factory.makePersonalBranch()
        self.assertEqual(
            '~%s/+junk/%s' % (branch.owner.name, branch.name),
            branch.unique_name)

    def test_unique_name_source_package(self):
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            '~%s/%s/%s/%s/%s' % (
                branch.owner.name, branch.distribution.name,
                branch.distroseries.name, branch.sourcepackagename.name,
                branch.name),
            branch.unique_name)

    def test_target_name_junk(self):
        branch = self.factory.makePersonalBranch()
        self.assertEqual('+junk', branch.target.name)

    def test_target_name_product(self):
        branch = self.factory.makeProductBranch()
        self.assertEqual(branch.product.name, branch.target.name)

    def test_target_name_package(self):
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            '%s/%s/%s' % (
                branch.distribution.name, branch.distroseries.name,
                branch.sourcepackagename.name),
            branch.target.name)

    def makeLaunchBag(self):
        return getUtility(IOpenLaunchBag)

    def test_addToLaunchBag_product(self):
        # Branches are not added directly to the launchbag. Instead,
        # information about their target is added.
        branch = self.factory.makeProductBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertEqual(branch.product, launchbag.product)

    def test_addToLaunchBag_personal(self):
        # Junk branches may also be added to the launchbag.
        branch = self.factory.makePersonalBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertIs(None, launchbag.product)

    def test_addToLaunchBag_package(self):
        # Package branches can be added to the launchbag.
        branch = self.factory.makePackageBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertEqual(branch.distroseries, launchbag.distroseries)
        self.assertEqual(branch.distribution, launchbag.distribution)
        self.assertEqual(branch.sourcepackage, launchbag.sourcepackage)
        self.assertIs(None, branch.product)

    def test_distribution_personal(self):
        # The distribution property of a branch is None for personal branches.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, branch.distribution)

    def test_distribution_product(self):
        # The distribution property of a branch is None for product branches.
        branch = self.factory.makeProductBranch()
        self.assertIs(None, branch.distribution)

    def test_distribution_package(self):
        # The distribution property of a branch is the distribution of the
        # distroseries for package branches.
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            branch.distroseries.distribution, branch.distribution)

    def test_sourcepackage_personal(self):
        # The sourcepackage property of a branch is None for personal
        # branches.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, branch.sourcepackage)

    def test_sourcepackage_product(self):
        # The sourcepackage property of a branch is None for product branches.
        branch = self.factory.makeProductBranch()
        self.assertIs(None, branch.sourcepackage)

    def test_sourcepackage_package(self):
        # The sourcepackage property of a branch is the ISourcePackage built
        # from the distroseries and sourcepackagename of the branch.
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            SourcePackage(branch.sourcepackagename, branch.distroseries),
            branch.sourcepackage)

    def test_needsUpgrading_branch_format_unrecognized(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If the format is
        # unrecognized, we don't try to upgrade it.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.UNRECOGNIZED)
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_branch_format_upgrade_not_needed(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If a branch is up to date, it
        # doesn't need to be upgraded.
        #
        # XXX: JonathanLange 2009-06-06: This test needs to be changed every
        # time Bazaar adds a new branch format. Surely we can think of a
        # better way of testing this?
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8)
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_branch_format_upgrade_needed(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If a branch doesn't support
        # stacking, it needs to be upgraded.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_6)
        self.assertTrue(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_unrecognized(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  In the repo format is
        # unrecognized, we don't try to upgrade it.
        branch = self.factory.makePersonalBranch(
            repository_format=RepositoryFormat.UNRECOGNIZED)
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_upgrade_not_needed(self):
        # A branch has a needs_upgrading method that returns whether or not a
        # branch needs to be upgraded or not.  If the repo format is up to
        # date, there's no need to upgrade it.
        branch = self.factory.makePersonalBranch(
            repository_format=RepositoryFormat.BZR_KNITPACK_6)
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_upgrade_needed(self):
        # A branch has a needs_upgrading method that returns whether or not a
        # branch needs to be upgraded or not.  If the format doesn't support
        # stacking, it needs to be upgraded.
        branch = self.factory.makePersonalBranch(
            repository_format=RepositoryFormat.BZR_REPOSITORY_4)
        self.assertTrue(branch.needs_upgrading)


class TestBzrIdentity(TestCaseWithFactory):
    """Test IBranch.bzr_identity."""

    layer = DatabaseFunctionalLayer

    def assertBzrIdentity(self, branch, identity_path):
        """Assert that the bzr identity of 'branch' is 'identity_path'.

        Actually, it'll be lp://dev/<identity_path>.
        """
        self.assertEqual(
            'lp://dev/%s' % identity_path, branch.bzr_identity,
            "bzr identity")

    def test_default_identity(self):
        # By default, the bzr identity is an lp URL with the branch's unique
        # name.
        branch = self.factory.makeAnyBranch()
        self.assertBzrIdentity(branch, branch.unique_name)

    def test_linked_to_product(self):
        # If a branch is the development focus branch for a product, then it's
        # bzr identity is lp:product.
        branch = self.factory.makeProductBranch()
        product = removeSecurityProxy(branch.product)
        linked_branch = ICanHasLinkedBranch(product)
        linked_branch.setBranch(branch)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_linked_to_product_series(self):
        # If a branch is the development focus branch for a product series,
        # then it's bzr identity is lp:product/series.
        branch = self.factory.makeProductBranch()
        product = branch.product
        series = self.factory.makeProductSeries(product=product)
        linked_branch = ICanHasLinkedBranch(series)
        linked_branch.setBranch(branch)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_private_linked_to_product(self):
        # If a branch is private, then the bzr identity is the unique name,
        # even if it's linked to a product. Of course, you have to be able to
        # see the branch at all.
        branch = self.factory.makeProductBranch(private=True)
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        product = removeSecurityProxy(branch.product)
        ICanHasLinkedBranch(product).setBranch(branch)
        self.assertBzrIdentity(branch, branch.unique_name)

    def test_linked_to_series_and_dev_focus(self):
        # If a branch is the development focus branch for a product and the
        # branch for a series, the bzr identity will be the storter of the two
        # URLs.
        branch = self.factory.makeProductBranch()
        series = self.factory.makeProductSeries(product=branch.product)
        product_link = ICanHasLinkedBranch(
            removeSecurityProxy(branch.product))
        series_link = ICanHasLinkedBranch(series)
        product_link.setBranch(branch)
        series_link.setBranch(branch)
        self.assertBzrIdentity(branch, product_link.bzr_path)

    def test_junk_branch_always_unique_name(self):
        # For junk branches, the bzr identity is always based on the unique
        # name of the branch, even if it's linked to a product, product series
        # or whatever.
        branch = self.factory.makePersonalBranch()
        product = removeSecurityProxy(self.factory.makeProduct())
        ICanHasLinkedBranch(product).setBranch(branch)
        self.assertBzrIdentity(branch, branch.unique_name)

    def test_linked_to_package(self):
        # If a branch is linked to a pocket of a package, then the
        # bzr identity is the path to that package.
        branch = self.factory.makePackageBranch()
        # Have to pick something that's not RELEASE in order to guarantee that
        # it's not the dev focus source package.
        pocket = PackagePublishingPocket.BACKPORTS
        linked_branch = ICanHasLinkedBranch(
            branch.sourcepackage.getSuiteSourcePackage(pocket))
        registrant = getUtility(
            ILaunchpadCelebrities).ubuntu_branches.teamowner
        login_person(registrant)
        linked_branch.setBranch(branch, registrant)
        logout()
        login(ANONYMOUS)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_linked_to_dev_package(self):
        # If a branch is linked to the development focus version of a package
        # then the bzr identity is distro/package.
        sourcepackage = self.factory.makeSourcePackage()
        distro_package = sourcepackage.distribution_sourcepackage
        branch = self.factory.makePackageBranch(
            sourcepackage=distro_package.development_version)
        linked_branch = ICanHasLinkedBranch(distro_package)
        registrant = getUtility(
            ILaunchpadCelebrities).ubuntu_branches.teamowner
        run_with_login(
            registrant,
            linked_branch.setBranch, branch, registrant)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)


class TestBranchDeletion(TestCaseWithFactory):
    """Test the different cases that makes a branch deletable or not."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, 'test@canonical.com')
        self.product = ProductSet().getByName('firefox')
        self.user = getUtility(IPersonSet).getByEmail('test@canonical.com')
        self.branch = self.factory.makeProductBranch(
            name='to-delete', owner=self.user, product=self.product)
        # The owner of the branch is subscribed to the branch when it is
        # created.  The tests here assume no initial connections, so
        # unsubscribe the branch owner here.
        self.branch.unsubscribe(self.branch.owner)

    def test_deletable(self):
        """A newly created branch can be deleted without any problems."""
        self.assertEqual(self.branch.canBeDeleted(), True,
                         "A newly created branch should be able to be "
                         "deleted.")
        branch_id = self.branch.id
        branch_set = getUtility(IBranchLookup)
        self.branch.destroySelf()
        self.assert_(branch_set.get(branch_id) is None,
                     "The branch has not been deleted.")

    def test_stackedBranchDisablesDeletion(self):
        # A branch that is stacked upon cannot be deleted.
        self.factory.makeAnyBranch(stacked_on=self.branch)
        self.assertFalse(self.branch.canBeDeleted())

    def test_subscriptionDoesntDisableDeletion(self):
        """A branch that has a subscription can be deleted."""
        self.branch.subscribe(
            self.user, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.NOEMAIL)
        self.assertEqual(True, self.branch.canBeDeleted())

    def test_codeImportDisablesDeletion(self):
        """A branch that has an attached code import can't be deleted."""
        code_import = LaunchpadObjectFactory().makeCodeImport()
        branch = code_import.branch
        self.assertEqual(branch.canBeDeleted(), False,
                         "A branch that has a import is not deletable.")
        self.assertRaises(CannotDeleteBranch, branch.destroySelf)

    def test_bugBranchLinkDisablesDeletion(self):
        """A branch linked to a bug cannot be deleted."""
        params = CreateBugParams(
            owner=self.user, title='Firefox bug', comment='blah')
        params.setBugTarget(product=self.product)
        bug = getUtility(IBugSet).createBug(params)
        bug.linkBranch(self.branch, self.user)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch linked to a bug is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_specBranchLinkDisablesDeletion(self):
        """A branch linked to a spec cannot be deleted."""
        spec = getUtility(ISpecificationSet).new(
            name='some-spec', title='Some spec', product=self.product,
            owner=self.user, summary='', specurl=None,
            definition_status=SpecificationDefinitionStatus.NEW)
        spec.linkBranch(self.branch, self.user)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch linked to a spec is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_associatedProductSeriesBranchDisablesDeletion(self):
        """A branch linked as a branch to a product series cannot be
        deleted.
        """
        self.product.development_focus.branch = self.branch
        syncUpdate(self.product.development_focus)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch that is a user branch for a product series"
                         " is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_productSeriesTranslationsBranchDisablesDeletion(self):
        self.product.development_focus.translations_branch = self.branch
        syncUpdate(self.product.development_focus)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch that is a translations branch for a "
                         "product series is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_revisionsDeletable(self):
        """A branch that has some revisions can be deleted."""
        revision = self.factory.makeRevision()
        self.branch.createBranchRevision(0, revision)
        # Need to commit the addition to make sure that the branch revisions
        # are recorded as there and that the appropriate deferred foreign keys
        # are set up.
        transaction.commit()
        self.assertEqual(self.branch.canBeDeleted(), True,
                         "A branch that has a revision is deletable.")
        unique_name = self.branch.unique_name
        self.branch.destroySelf()
        # Commit again to trigger the deferred indices.
        transaction.commit()
        branch_lookup = getUtility(IBranchLookup)
        self.assertEqual(branch_lookup.getByUniqueName(unique_name), None,
                         "Branch was not deleted.")

    def test_landingTargetDisablesDeletion(self):
        """A branch with a landing target cannot be deleted."""
        target_branch = self.factory.makeProductBranch(
            name='landing-target', owner=self.user, product=self.product)
        self.branch.addLandingTarget(self.user, target_branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a landing target is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_landingCandidateDisablesDeletion(self):
        """A branch with a landing candidate cannot be deleted."""
        source_branch = self.factory.makeProductBranch(
            name='landing-candidate', owner=self.user, product=self.product)
        source_branch.addLandingTarget(self.user, self.branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a landing candidate is not"
                         " deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_prerequisiteBranchDisablesDeletion(self):
        """A branch that is a prerequisite branch cannot be deleted."""
        source_branch = self.factory.makeProductBranch(
            name='landing-candidate', owner=self.user, product=self.product)
        target_branch = self.factory.makeProductBranch(
            name='landing-target', owner=self.user, product=self.product)
        source_branch.addLandingTarget(self.user, target_branch, self.branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a prerequisite target is not "
                         "deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_relatedBranchJobsDeleted(self):
        # A branch with an associated branch job will delete those jobs.
        branch = self.factory.makeAnyBranch()
        BranchDiffJob.create(branch, 'from-spec', 'to-spec')
        branch.destroySelf()
        # Need to commit the transaction to fire off the constraint checks.
        transaction.commit()

    def test_createsJobToReclaimSpace(self):
        # When a branch is deleted from the database, a job to remove the
        # branch from disk as well.
        branch = self.factory.makeAnyBranch()
        branch_id = branch.id
        store = Store.of(branch)
        branch.destroySelf()
        jobs = store.find(
            BranchJob,
            BranchJob.job_type == BranchJobType.RECLAIM_BRANCH_SPACE)
        self.assertEqual(
            [branch_id],
            [ReclaimBranchSpaceJob(job).branch_id for job in jobs])


class TestBranchDeletionConsequences(TestCase):
    """Test determination and application of branch deletion consequences."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('test@canonical.com')
        self.factory = LaunchpadObjectFactory()
        # Has to be a product branch because of merge proposals.
        self.branch = self.factory.makeProductBranch()
        # The owner of the branch is subscribed to the branch when it is
        # created.  The tests here assume no initial connections, so
        # unsubscribe the branch owner here.
        self.branch.unsubscribe(self.branch.owner)

    def test_plainBranch(self):
        """Ensure that a fresh branch has no deletion requirements."""
        self.assertEqual({}, self.branch.deletionRequirements())

    def makeMergeProposals(self):
        """Produce a merge proposal for testing purposes."""
        target_branch = self.factory.makeProductBranch(
            product=self.branch.product)
        prerequisite_branch = self.factory.makeProductBranch(
            product=self.branch.product)
        # Remove the implicit subscriptions.
        target_branch.unsubscribe(target_branch.owner)
        prerequisite_branch.unsubscribe(prerequisite_branch.owner)
        merge_proposal1 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, prerequisite_branch)
        # Disable this merge proposal, to allow creating a new identical one
        lp_admins = getUtility(ILaunchpadCelebrities).admin
        merge_proposal1.rejectBranch(lp_admins, 'null:')
        syncUpdate(merge_proposal1)
        merge_proposal2 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, prerequisite_branch)
        return merge_proposal1, merge_proposal2

    def test_branchWithMergeProposal(self):
        """Ensure that deletion requirements with a merge proposal are right.

        Each branch related to the merge proposal is tested to ensure it
        produces a unique, correct result.
        """
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        self.assertEqual({
            merge_proposal1:
            ('delete', _('This branch is the source branch of this merge'
             ' proposal.')),
            merge_proposal2:
            ('delete', _('This branch is the source branch of this merge'
             ' proposal.'))},
                         self.branch.deletionRequirements())
        self.assertEqual({
            merge_proposal1:
            ('delete', _('This branch is the target branch of this merge'
             ' proposal.')),
            merge_proposal2:
            ('delete', _('This branch is the target branch of this merge'
             ' proposal.'))},
            merge_proposal1.target_branch.deletionRequirements())
        self.assertEqual({
            merge_proposal1:
            ('alter', _('This branch is the prerequisite branch of this merge'
             ' proposal.')),
            merge_proposal2:
            ('alter', _('This branch is the prerequisite branch of this merge'
             ' proposal.'))},
            merge_proposal1.prerequisite_branch.deletionRequirements())

    def test_deleteMergeProposalSource(self):
        """Merge proposal source branches can be deleted with break_links."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1_id = merge_proposal1.id
        BranchMergeProposal.get(merge_proposal1_id)
        self.branch.destroySelf(break_references=True)
        self.assertRaises(SQLObjectNotFound,
            BranchMergeProposal.get, merge_proposal1_id)

    def test_deleteMergeProposalTarget(self):
        """Merge proposal target branches can be deleted with break_links."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1_id = merge_proposal1.id
        BranchMergeProposal.get(merge_proposal1_id)
        merge_proposal1.target_branch.destroySelf(break_references=True)
        self.assertRaises(SQLObjectNotFound,
            BranchMergeProposal.get, merge_proposal1_id)

    def test_deleteMergeProposalDependent(self):
        """break_links enables deleting merge proposal dependant branches."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1.prerequisite_branch.destroySelf(break_references=True)
        self.assertEqual(None, merge_proposal1.prerequisite_branch)

    def test_deleteSourceCodeReviewComment(self):
        """Deletion of branches that have CodeReviewComments works."""
        comment = self.factory.makeCodeReviewComment()
        comment_id = comment.id
        branch = comment.branch_merge_proposal.source_branch
        branch.destroySelf(break_references=True)
        self.assertRaises(
            SQLObjectNotFound, CodeReviewComment.get, comment_id)

    def test_deleteTargetCodeReviewComment(self):
        """Deletion of branches that have CodeReviewComments works."""
        comment = self.factory.makeCodeReviewComment()
        comment_id = comment.id
        branch = comment.branch_merge_proposal.target_branch
        branch.destroySelf(break_references=True)
        self.assertRaises(
            SQLObjectNotFound, CodeReviewComment.get, comment_id)

    def test_branchWithBugRequirements(self):
        """Deletion requirements for a branch with a bug are right."""
        bug = self.factory.makeBug()
        bug.linkBranch(self.branch, self.branch.owner)
        self.assertEqual({bug.linked_branches[0]:
            ('delete', _('This bug is linked to this branch.'))},
            self.branch.deletionRequirements())

    def test_branchWithBugDeletion(self):
        """break_links allows deleting a branch with a bug."""
        bug1 = self.factory.makeBug()
        bug1.linkBranch(self.branch, self.branch.owner)
        bug_branch1 = bug1.linked_branches[0]
        bug_branch1_id = bug_branch1.id
        self.branch.destroySelf(break_references=True)
        self.assertRaises(SQLObjectNotFound, BugBranch.get, bug_branch1_id)

    def test_branchWithSpecRequirements(self):
        """Deletion requirements for a branch with a spec are right."""
        spec = self.factory.makeSpecification()
        spec.linkBranch(self.branch, self.branch.owner)
        self.assertEqual({self.branch.spec_links[0]:
            ('delete', _(
                'This blueprint is linked to this branch.'))},
             self.branch.deletionRequirements())

    def test_branchWithSpecDeletion(self):
        """break_links allows deleting a branch with a spec."""
        spec1 = self.factory.makeSpecification()
        spec1.linkBranch(self.branch, self.branch.owner)
        spec1_branch_id = self.branch.spec_links[0].id
        spec2 = self.factory.makeSpecification()
        spec2.linkBranch(self.branch, self.branch.owner)
        spec2_branch_id = self.branch.spec_links[1].id
        self.branch.destroySelf(break_references=True)
        self.assertRaises(SQLObjectNotFound, SpecificationBranch.get,
                          spec1_branch_id)
        self.assertRaises(SQLObjectNotFound, SpecificationBranch.get,
                          spec2_branch_id)

    def test_branchWithSeriesRequirements(self):
        """Deletion requirements for a series' branch are right."""
        series = self.factory.makeSeries(branch=self.branch)
        self.assertEqual(
            {series: ('alter',
            _('This series is linked to this branch.'))},
            self.branch.deletionRequirements())

    def test_branchWithSeriesDeletion(self):
        """break_links allows deleting a series' branch."""
        series1 = self.factory.makeSeries(branch=self.branch)
        series2 = self.factory.makeSeries(branch=self.branch)
        self.branch.destroySelf(break_references=True)
        self.assertEqual(None, series1.branch)
        self.assertEqual(None, series2.branch)

    def test_official_package_requirements(self):
        # If a branch is officially linked to a source package, then the
        # deletion requirements indicate the fact.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        ubuntu_branches = getUtility(ILaunchpadCelebrities).ubuntu_branches
        run_with_login(
            ubuntu_branches.teamowner,
            package.development_version.setBranch,
            pocket, branch, ubuntu_branches.teamowner)
        series_set = getUtility(IFindOfficialBranchLinks)
        [link] = list(series_set.findForBranch(branch))
        self.assertEqual(
            {link: ('alter',
                    _('Branch is officially linked to a source package.'))},
            branch.deletionRequirements())

    def test_official_package_branch_deleted(self):
        # A branch that's an official package branch can be deleted if you are
        # allowed to modify package branch links, and you pass in
        # break_references.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        ubuntu_branches = getUtility(ILaunchpadCelebrities).ubuntu_branches
        run_with_login(
            ubuntu_branches.teamowner,
            package.development_version.setBranch,
            pocket, branch, ubuntu_branches.teamowner)
        self.assertEqual(False, branch.canBeDeleted())
        branch.destroySelf(break_references=True)
        self.assertIs(None, package.getBranch(pocket))

    def test_branchWithCodeImportRequirements(self):
        """Deletion requirements for a code import branch are right"""
        code_import = self.factory.makeCodeImport()
        # Remove the implicit branch subscription first.
        code_import.branch.unsubscribe(code_import.branch.owner)
        self.assertEqual({code_import:
            ('delete', _('This is the import data for this branch.'))},
             code_import.branch.deletionRequirements())

    def test_branchWithCodeImportDeletion(self):
        """break_links allows deleting a code import branch."""
        code_import = self.factory.makeCodeImport()
        code_import_id = code_import.id
        self.factory.makeCodeImportJob(code_import)
        code_import.branch.destroySelf(break_references=True)
        self.assertRaises(
            SQLObjectNotFound, CodeImport.get, code_import_id)

    def test_sourceBranchWithCodeReviewVoteReference(self):
        """Break_references handles CodeReviewVoteReference source branch."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        merge_proposal.nominateReviewer(self.factory.makePerson(),
                                        self.factory.makePerson())
        merge_proposal.source_branch.destroySelf(break_references=True)

    def test_targetBranchWithCodeReviewVoteReference(self):
        """Break_references handles CodeReviewVoteReference target branch."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        merge_proposal.nominateReviewer(self.factory.makePerson(),
                                        self.factory.makePerson())
        merge_proposal.target_branch.destroySelf(break_references=True)

    def test_ClearDependentBranch(self):
        """ClearDependent.__call__ must clear the prerequisite branch."""
        merge_proposal = removeSecurityProxy(self.makeMergeProposals()[0])
        ClearDependentBranch(merge_proposal)()
        self.assertEqual(None, merge_proposal.prerequisite_branch)

    def test_ClearOfficialPackageBranch(self):
        # ClearOfficialPackageBranch.__call__ clears the official package
        # branch.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        ubuntu_branches = getUtility(ILaunchpadCelebrities).ubuntu_branches
        run_with_login(
            ubuntu_branches.teamowner,
            package.development_version.setBranch,
            pocket, branch, ubuntu_branches.teamowner)
        series_set = getUtility(IFindOfficialBranchLinks)
        [link] = list(series_set.findForBranch(branch))
        ClearOfficialPackageBranch(link)()
        self.assertIs(None, package.getBranch(pocket))

    def test_ClearSeriesBranch(self):
        """ClearSeriesBranch.__call__ must clear the user branch."""
        series = removeSecurityProxy(self.factory.makeSeries(
            branch=self.branch))
        ClearSeriesBranch(series, self.branch)()
        self.assertEqual(None, series.branch)

    def test_DeletionOperation(self):
        """DeletionOperation.__call__ is not implemented."""
        self.assertRaises(NotImplementedError, DeletionOperation('a', 'b'))

    def test_DeletionCallable(self):
        """DeletionCallable must invoke the callable."""
        spec = self.factory.makeSpecification()
        spec_link = spec.linkBranch(self.branch, self.branch.owner)
        spec_link_id = spec_link.id
        DeletionCallable(spec, 'blah', spec_link.destroySelf)()
        self.assertRaises(SQLObjectNotFound, SpecificationBranch.get,
                          spec_link_id)

    def test_DeleteCodeImport(self):
        """DeleteCodeImport.__call__ must delete the CodeImport."""
        code_import = self.factory.makeCodeImport()
        code_import_id = code_import.id
        self.factory.makeCodeImportJob(code_import)
        DeleteCodeImport(code_import)()
        self.assertRaises(
            SQLObjectNotFound, CodeImport.get, code_import_id)


class StackedBranches(TestCaseWithFactory):
    """Tests for showing branches stacked on another."""

    layer = DatabaseFunctionalLayer

    def testNoBranchesStacked(self):
        # getStackedBranches returns an empty collection if there are no
        # branches stacked on it.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(set(), set(branch.getStackedBranches()))

    def testSingleBranchStacked(self):
        # some_branch.getStackedBranches returns a collection of branches
        # stacked on some_branch.
        branch = self.factory.makeAnyBranch()
        stacked_branch = self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual(
            set([stacked_branch]), set(branch.getStackedBranches()))

    def testMultipleBranchesStacked(self):
        # some_branch.getStackedBranches returns a collection of branches
        # stacked on some_branch.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_b = self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual(
            set([stacked_a, stacked_b]), set(branch.getStackedBranches()))

    def testStackedBranchesIncompleteMirrorsNoBranches(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors does not include
        # stacked branches that haven't been mirrored at all.
        branch = self.factory.makeAnyBranch()
        self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual(
            set(), set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesIncompleteMirrors(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors returns branches
        # stacked on some_branch that had their mirrors started but not
        # finished.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_a.startMirroring()
        self.assertEqual(
            set([stacked_a]),
            set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesIncompleteMirrorsNotStacked(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors does not include
        # branches with incomplete mirrors that are not stacked on
        # some_branch.
        branch = self.factory.makeAnyBranch()
        not_stacked = self.factory.makeAnyBranch()
        not_stacked.startMirroring()
        self.assertEqual(
            set(), set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesCompleteMirrors(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors does not include
        # branches that have been successfully mirrored.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_a.startMirroring()
        stacked_a.mirrorComplete(self.factory.getUniqueString())
        self.assertEqual(
            set(), set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesFailedMirrors(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors includes
        # branches that failed to mirror. This is not directly desired, but is
        # a consequence of wanting to include branches that have started,
        # failed, then started again.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_a.startMirroring()
        stacked_a.mirrorFailed(self.factory.getUniqueString())
        self.assertEqual(
            set([stacked_a]),
            set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesFailedThenStartedMirrors(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors includes
        # branches that had a failed mirror but have since been started.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_a.startMirroring()
        stacked_a.mirrorFailed(self.factory.getUniqueString())
        stacked_a.startMirroring()
        self.assertEqual(
            set([stacked_a]),
            set(branch.getStackedBranchesWithIncompleteMirrors()))

    def testStackedBranchesMirrorRequested(self):
        # some_branch.getStackedBranchesWithIncompleteMirrors does not include
        # branches that have only had a mirror requested.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_a.requestMirror()
        self.assertEqual(
            set(), set(branch.getStackedBranchesWithIncompleteMirrors()))


class BranchAddLandingTarget(TestCaseWithFactory):
    """Exercise all the code paths for adding a landing target."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, 'admin@canonical.com')
        self.product = self.factory.makeProduct()

        self.user = self.factory.makePerson()
        self.source = self.factory.makeProductBranch(
            name='source-branch', owner=self.user, product=self.product)
        self.target = self.factory.makeProductBranch(
            name='target-branch', owner=self.user, product=self.product)
        self.prerequisite = self.factory.makeProductBranch(
            name='prerequisite-branch', owner=self.user, product=self.product)

    def tearDown(self):
        logout()

    def test_junkSource(self):
        """Junk branches cannot be used as a source for merge proposals."""
        self.source.setTarget(user=self.source.owner)
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

    def test_targetProduct(self):
        """The product of the target branch must match the product of the
        source branch.
        """
        self.target.setTarget(user=self.target.owner)
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

        project = self.factory.makeProduct()
        self.target.setTarget(user=self.target.owner, project=project)
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

    def test_targetMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.source)

    def test_prerequisiteBranchSameProduct(self):
        """The prerequisite branch, if any, must be for the same product.
        """
        self.prerequisite.setTarget(user=self.prerequisite.owner)
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.prerequisite)

        project = self.factory.makeProduct()
        self.prerequisite.setTarget(
            user=self.prerequisite.owner, project=project)
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.prerequisite)

    def test_prerequisiteMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.source)

    def test_prerequisiteMustNotBeTheTarget(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.target)

    def test_existingMergeProposal(self):
        """If there is an existing merge proposal for the source and target
        branch pair, then another landing target specifying the same pair
        raises.
        """
        self.source.addLandingTarget(
            self.user, self.target, self.prerequisite)

        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.prerequisite)

    def test_existingRejectedMergeProposal(self):
        """If there is an existing rejected merge proposal for the source and
        target branch pair, then another landing target specifying the same
        pair is fine.
        """
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.prerequisite)
        proposal.rejectBranch(self.user, 'some_revision')
        syncUpdate(proposal)
        self.source.addLandingTarget(
            self.user, self.target, self.prerequisite)

    def test_attributeAssignment(self):
        """Smoke test to make sure the assignments are there."""
        whiteboard = u"Some whiteboard"
        commit_message = u'Some commit message'
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.prerequisite, whiteboard,
            commit_message=commit_message)
        self.assertEqual(proposal.registrant, self.user)
        self.assertEqual(proposal.source_branch, self.source)
        self.assertEqual(proposal.target_branch, self.target)
        self.assertEqual(proposal.prerequisite_branch, self.prerequisite)
        self.assertEqual(proposal.whiteboard, whiteboard)
        self.assertEqual(proposal.commit_message, commit_message)


class BranchDateLastModified(TestCaseWithFactory):
    """Exercies the situations where date_last_modifed is udpated."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, 'test@canonical.com')

    def test_initialValue(self):
        """Initially the date_last_modifed is the date_created."""
        branch = self.factory.makeAnyBranch()
        self.assertEqual(branch.date_last_modified, branch.date_created)

    def test_bugBranchLinkUpdates(self):
        """Linking a branch to a bug updates the last modified time."""
        date_created = datetime(2000, 1, 1, 12, tzinfo=UTC)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        self.assertEqual(branch.date_last_modified, date_created)

        params = CreateBugParams(
            owner=branch.owner, title='A bug', comment='blah')
        params.setBugTarget(product=branch.product)
        bug = getUtility(IBugSet).createBug(params)

        bug.linkBranch(branch, branch.owner)
        self.assertTrue(branch.date_last_modified > date_created,
                        "Date last modified was not updated.")

    def test_updateScannedDetails_with_null_revision(self):
        # If updateScannedDetails is called with a null revision, it
        # effectively means that there is an empty branch, so we can't use the
        # revision date, so we set the last modified time to UTC_NOW.
        date_created = datetime(2000, 1, 1, 12, tzinfo=UTC)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        branch.updateScannedDetails(None, 0)
        self.assertSqlAttributeEqualsDate(
            branch, 'date_last_modified', UTC_NOW)

    def test_updateScannedDetails_with_revision(self):
        # If updateScannedDetails is called with a revision with which has a
        # revision date set in the past (the usual case), the last modified
        # time of the branch is set to be the date from the Bazaar revision
        # (Revision.revision_date).
        date_created = datetime(2000, 1, 1, 12, tzinfo=UTC)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        revision_date = datetime(2005, 2, 2, 12, tzinfo=UTC)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.updateScannedDetails(revision, 1)
        self.assertEqual(revision_date, branch.date_last_modified)

    def test_updateScannedDetails_with_future_revision(self):
        # If updateScannedDetails is called with a revision with which has a
        # revision date set in the future, UTC_NOW is used as the last modifed
        # time.  date_created = datetime(2000, 1, 1, 12, tzinfo=UTC)
        date_created = datetime(2000, 1, 1, 12, tzinfo=UTC)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        revision_date = datetime.now(UTC) + timedelta(days=1000)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.updateScannedDetails(revision, 1)
        self.assertSqlAttributeEqualsDate(
            branch, 'date_last_modified', UTC_NOW)


class TestBranchLifecycleStatus(TestCaseWithFactory):
    """Exercises changes in lifecycle status."""
    layer = DatabaseFunctionalLayer

    def checkStatusAfterUpdate(self, initial_state, expected_state):
        # Make sure that the lifecycle status of the branch with the initial
        # lifecycle state to be the expected_state after a revision has been
        # scanned.
        branch = self.factory.makeAnyBranch(lifecycle_status=initial_state)
        revision = self.factory.makeRevision()
        branch.updateScannedDetails(revision, 1)
        self.assertEqual(expected_state, branch.lifecycle_status)

    def test_updateScannedDetails_active_branch(self):
        # If a new revision is scanned, and the branch is in an active state,
        # then the lifecycle status isn't changed.
        for state in DEFAULT_BRANCH_STATUS_IN_LISTING:
            self.checkStatusAfterUpdate(state, state)

    def test_updateScannedDetails_inactive_branch(self):
        # If a branch is inactive (merged or abandonded) and a new revision is
        # scanned, the branch is moved to the development state.
        for state in (BranchLifecycleStatus.MERGED,
                      BranchLifecycleStatus.ABANDONED):
            self.checkStatusAfterUpdate(
                state, BranchLifecycleStatus.DEVELOPMENT)


class TestCreateBranchRevisionFromIDs(TestCaseWithFactory):
    """Tests for `Branch.createBranchRevisionFromIDs`."""

    layer = DatabaseFunctionalLayer

    def test_simple(self):
        # createBranchRevisionFromIDs when passed a single revid, sequence
        # pair, creates the appropriate BranchRevision object.
        branch = self.factory.makeAnyBranch()
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)])
        branch_revision = branch.getBranchRevision(revision=rev)
        self.assertEqual(revision_number, branch_revision.sequence)

    def test_multiple(self):
        # createBranchRevisionFromIDs when passed multiple revid, sequence
        # pairs, creates the appropriate BranchRevision objects.
        branch = self.factory.makeAnyBranch()
        revision_to_number = {}
        revision_id_sequence_pairs = []
        for i in range(10):
            rev = self.factory.makeRevision()
            revision_number = self.factory.getUniqueInteger()
            revision_to_number[rev] = revision_number
            revision_id_sequence_pairs.append(
                (rev.revision_id, revision_number))
        branch.createBranchRevisionFromIDs(revision_id_sequence_pairs)
        for rev in revision_to_number:
            branch_revision = branch.getBranchRevision(revision=rev)
            self.assertEqual(
                revision_to_number[rev], branch_revision.sequence)

    def test_empty(self):
        # createBranchRevisionFromIDs does not fail when passed no pairs.
        branch = self.factory.makeAnyBranch()
        branch.createBranchRevisionFromIDs([])

    def test_call_twice_in_one_transaction(self):
        # createBranchRevisionFromIDs creates temporary tables, but cleans
        # after itself so that it can safely be called twice in one
        # transaction.
        branch = self.factory.makeAnyBranch()
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)])
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        # This is just "assertNotRaises"
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)])


class TestCodebrowseURL(TestCaseWithFactory):
    """Tests for `Branch.codebrowse_url`."""

    layer = DatabaseFunctionalLayer

    def test_simple(self):
        # The basic codebrowse URL for a public branch is a 'http' url.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            'http://bazaar.launchpad.dev/' + branch.unique_name,
            branch.codebrowse_url())

    def test_private(self):
        # The codebrowse URL for a private branch is a 'https' url.
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(private=True, owner=owner)
        login_person(owner)
        self.assertEqual(
            'https://bazaar.launchpad.dev/' + branch.unique_name,
            branch.codebrowse_url())

    def test_extra_args(self):
        # Any arguments to codebrowse_url are appended to the URL.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            'http://bazaar.launchpad.dev/' + branch.unique_name + '/a/b',
            branch.codebrowse_url('a', 'b'))

    def test_source_code_url(self):
        # The source code URL points to the codebrowse URL where you can
        # actually browse the source code.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            branch.browse_source_url, branch.codebrowse_url('files'))


class TestBranchNamespace(TestCaseWithFactory):
    """Tests for `IBranch.namespace`."""

    layer = DatabaseFunctionalLayer

    def assertNamespaceEqual(self, namespace_one, namespace_two):
        """Assert that `namespace_one` equals `namespace_two`."""
        namespace_one = removeSecurityProxy(namespace_one)
        namespace_two = removeSecurityProxy(namespace_two)
        self.assertEqual(namespace_one.__class__, namespace_two.__class__)
        self.assertEqual(namespace_one.owner, namespace_two.owner)
        self.assertEqual(
            getattr(namespace_one, 'sourcepackage', None),
            getattr(namespace_two, 'sourcepackage', None))
        self.assertEqual(
            getattr(namespace_one, 'product', None),
            getattr(namespace_two, 'product', None))

    def test_namespace_personal(self):
        # The namespace attribute of a personal branch points to the namespace
        # that corresponds to ~owner/+junk.
        branch = self.factory.makePersonalBranch()
        namespace = getUtility(IBranchNamespaceSet).get(person=branch.owner)
        self.assertNamespaceEqual(namespace, branch.namespace)

    def test_namespace_package(self):
        # The namespace attribute of a package branch points to the namespace
        # that corresponds to
        # ~owner/distribution/distroseries/sourcepackagename.
        branch = self.factory.makePackageBranch()
        namespace = getUtility(IBranchNamespaceSet).get(
            person=branch.owner, distroseries=branch.distroseries,
            sourcepackagename=branch.sourcepackagename)
        self.assertNamespaceEqual(namespace, branch.namespace)

    def test_namespace_product(self):
        # The namespace attribute of a product branch points to the namespace
        # that corresponds to ~owner/product.
        branch = self.factory.makeProductBranch()
        namespace = getUtility(IBranchNamespaceSet).get(
            person=branch.owner, product=branch.product)
        self.assertNamespaceEqual(namespace, branch.namespace)


class TestPendingWrites(TestCaseWithFactory):
    """Are there changes to this branch not reflected in the database?"""

    layer = DatabaseFunctionalLayer

    def test_new_branch_no_writes(self):
        # New branches have no pending writes.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(False, branch.pending_writes)

    def test_requestMirror_for_hosted(self):
        # If a hosted branch has a requested mirror, then someone has just
        # pushed something up. Therefore, pending writes.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)
        branch.requestMirror()
        self.assertEqual(True, branch.pending_writes)

    def test_requestMirror_for_imported(self):
        # If an imported branch has a requested mirror, then we've just
        # imported new changes. Therefore, pending writes.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.IMPORTED)
        branch.requestMirror()
        self.assertEqual(True, branch.pending_writes)

    def test_requestMirror_for_mirrored(self):
        # Mirrored branches *always* have a requested mirror. The fact that a
        # mirror is requested has no bearing on whether there are pending
        # writes. Thus, pending_writes is False.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.requestMirror()
        self.assertEqual(False, branch.pending_writes)

    def test_pulled_but_not_scanned(self):
        # If a branch has been pulled (mirrored) but not scanned, then we have
        # yet to load the revisions into the database. This means there are
        # pending writes.
        branch = self.factory.makeAnyBranch()
        branch.startMirroring()
        rev_id = self.factory.getUniqueString('rev-id')
        branch.mirrorComplete(rev_id)
        self.assertEqual(True, branch.pending_writes)

    def test_pulled_and_scanned(self):
        # If a branch has been pulled and scanned, then there are no pending
        # writes.
        branch = self.factory.makeAnyBranch()
        branch.startMirroring()
        rev_id = self.factory.getUniqueString('rev-id')
        branch.mirrorComplete(rev_id)
        # Cheat! The actual API for marking a branch as scanned is
        # updateScannedDetails. That requires a revision in the database
        # though.
        removeSecurityProxy(branch).last_scanned_id = rev_id
        self.assertEqual(False, branch.pending_writes)

    def test_first_mirror_started(self):
        # If we have started mirroring the branch for the first time, then
        # there are probably pending writes.
        branch = self.factory.makeAnyBranch()
        branch.startMirroring()
        self.assertEqual(True, branch.pending_writes)

    def test_following_mirror_started(self):
        # If we have started mirroring the branch, then there are probably
        # pending writes.
        branch = self.factory.makeAnyBranch()
        branch.startMirroring()
        rev_id = self.factory.getUniqueString('rev-id')
        branch.mirrorComplete(rev_id)
        # Cheat! The actual API for marking a branch as scanned is
        # updateScannedDetails. That requires a revision in the database
        # though.
        removeSecurityProxy(branch).last_scanned_id = rev_id
        # Cheat again! We can only tell if mirroring has started if the last
        # mirrored attempt is different from the last mirrored time. To ensure
        # this, we start the second mirror in a new transaction.
        transaction.commit()
        branch.startMirroring()
        self.assertEqual(True, branch.pending_writes)


class TestBranchSetPrivate(TestCaseWithFactory):
    """Test IBranch.setPrivate."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin user as we aren't checking edit permissions here.
        TestCaseWithFactory.setUp(self, 'admin@canonical.com')

    def test_public_to_public(self):
        # Setting a public branch to be public is a no-op.
        branch = self.factory.makeProductBranch()
        self.assertFalse(branch.private)
        branch.setPrivate(False)
        self.assertFalse(branch.private)

    def test_public_to_private_allowed(self):
        # If there is a privacy policy allowing the branch owner to have
        # private branches, then setting the branch private is allowed.
        branch = self.factory.makeProductBranch()
        branch.product.setBranchVisibilityTeamPolicy(
            branch.owner, BranchVisibilityRule.PRIVATE)
        branch.setPrivate(True)
        self.assertTrue(branch.private)

    def test_public_to_private_not_allowed(self):
        # If there are no privacy policies allowing private branches, then
        # BranchCannotBePrivate is rasied.
        branch = self.factory.makeProductBranch()
        self.assertRaises(
            BranchCannotBePrivate,
            branch.setPrivate,
            True)

    def test_private_to_private(self):
        # Setting a private branch to be private is a no-op.
        branch = self.factory.makeProductBranch(private=True)
        self.assertTrue(branch.private)
        branch.setPrivate(True)
        self.assertTrue(branch.private)

    def test_private_to_public_allowed(self):
        # If the namespace policy allows public branches, then changing from
        # private to public is allowed.
        branch = self.factory.makeProductBranch(private=True)
        branch.setPrivate(False)
        self.assertFalse(branch.private)

    def test_private_to_public_not_allowed(self):
        # If the namespace policy does not allow public branches, attempting
        # to change the branch to be public raises BranchCannotBePublic.
        branch = self.factory.makeProductBranch(private=True)
        branch.product.setBranchVisibilityTeamPolicy(
            None, BranchVisibilityRule.FORBIDDEN)
        branch.product.setBranchVisibilityTeamPolicy(
            branch.owner, BranchVisibilityRule.PRIVATE_ONLY)
        self.assertRaises(
            BranchCannotBePublic,
            branch.setPrivate,
            False)


class TestBranchCommitsForDays(TestCaseWithFactory):
    """Tests for `Branch.commitsForDays`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        # Use a 30 day epoch for the tests.
        self.epoch = datetime.now(tz=UTC) - timedelta(days=30)

    def date_generator(self, epoch_offset, delta=None):
        if delta is None:
            delta = timedelta(days=1)
        return time_counter(self.epoch + timedelta(days=epoch_offset), delta)

    def test_empty_branch(self):
        # A branch with no commits returns an empty list.
        branch = self.factory.makeAnyBranch()
        self.assertEqual([], branch.commitsForDays(self.epoch))

    def test_commits_before_epoch_not_returned(self):
        # Commits that occur before the epoch are not returned.
        branch = self.factory.makeAnyBranch()
        self.factory.makeRevisionsForBranch(
            branch, date_generator=self.date_generator(-10))
        self.assertEqual([], branch.commitsForDays(self.epoch))

    def test_commits_after_epoch_are_returned(self):
        # Commits that occur after the epoch are returned.
        branch = self.factory.makeAnyBranch()
        self.factory.makeRevisionsForBranch(
            branch, count=5, date_generator=self.date_generator(1))
        # There is one commit for each day starting from epoch + 1.
        start = self.epoch + timedelta(days=1)
        # Clear off the fractional parts of the day.
        start = datetime(start.year, start.month, start.day)
        commits = []
        for count in range(5):
            commits.append((start + timedelta(days=count), 1))
        self.assertEqual(commits, branch.commitsForDays(self.epoch))

    def test_commits_are_grouped(self):
        # The commits are grouped to give counts of commits for the days.
        branch = self.factory.makeAnyBranch()
        start = self.epoch + timedelta(days=1)
        # Add 8 commits starting from 5pm (+ whatever minutes).
        # 5, 7, 9, 11pm, then 1, 3, 5, 7am for the following day.
        start = start.replace(hour=17)
        date_generator = time_counter(start, timedelta(hours=2))
        self.factory.makeRevisionsForBranch(
            branch, count=8, date_generator=date_generator)
        # The resulting queries return time zone unaware times.
        first_day = datetime(start.year, start.month, start.day)
        commits = [(first_day, 4), (first_day + timedelta(days=1), 4)]
        self.assertEqual(commits, branch.commitsForDays(self.epoch))

    def test_non_mainline_commits_count(self):
        # Non-mainline commits are counted too.
        branch = self.factory.makeAnyBranch()
        start = self.epoch + timedelta(days=1)
        revision = self.factory.makeRevision(revision_date=start)
        branch.createBranchRevision(None, revision)
        day = datetime(start.year, start.month, start.day)
        commits = [(day, 1)]
        self.assertEqual(commits, branch.commitsForDays(self.epoch))


class TestBranchBugLinks(TestCaseWithFactory):
    """Tests for bug linkages in `Branch`"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()

    def test_bug_link(self):
        # Branches can be linked to bugs through the Branch interface.
        branch = self.factory.makeAnyBranch()
        bug = self.factory.makeBug()
        branch.linkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 1)

        linked_bug = branch.linked_bugs[0]

        self.assertEqual(linked_bug.id, bug.id)

    def test_bug_unlink(self):
        # Branches can be unlinked from the bug as well.
        branch = self.factory.makeAnyBranch()
        bug = self.factory.makeBug()
        branch.linkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 1)

        branch.unlinkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 0)


class TestBranchSpecLinks(TestCaseWithFactory):
    """Tests for bug linkages in `Branch`"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()

    def test_spec_link(self):
        # Branches can be linked to specs through the Branch interface.
        branch = self.factory.makeAnyBranch()
        spec = self.factory.makeSpecification()
        branch.linkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 1)

        spec_branch = branch.spec_links[0]

        self.assertEqual(spec_branch.specification.id, spec.id)
        self.assertEqual(spec_branch.branch.id, branch.id)

    def test_spec_unlink(self):
        # Branches can be unlinked from the spec as well.
        branch = self.factory.makeAnyBranch()
        spec = self.factory.makeSpecification()
        branch.linkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 1)

        branch.unlinkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 0)


class TestBranchIsPersonTrustedReviewer(TestCaseWithFactory):
    """Test the `IBranch.isPersonTrustedReviewer` method."""

    layer = DatabaseFunctionalLayer

    def assertTrustedReviewer(self, branch, person):
        """Assert that `person` is a trusted reviewer for the `branch`."""
        self.assertTrue(branch.isPersonTrustedReviewer(person))

    def assertNotTrustedReviewer(self, branch, person):
        """Assert that `person` is not a trusted reviewer for the `branch`."""
        self.assertFalse(branch.isPersonTrustedReviewer(person))

    def test_none_is_not_trusted(self):
        # If None is passed in as the person, the method returns false.
        branch = self.factory.makeAnyBranch()
        self.assertNotTrustedReviewer(branch, None)

    def test_branch_owner_is_trusted(self):
        # The branch owner is a trusted reviewer.
        branch = self.factory.makeAnyBranch()
        self.assertTrustedReviewer(branch, branch.owner)

    def test_non_branch_owner_is_not_trusted(self):
        # Someone other than the branch owner is not a trusted reviewer.
        branch = self.factory.makeAnyBranch()
        reviewer = self.factory.makePerson()
        self.assertNotTrustedReviewer(branch, reviewer)

    def test_lp_admins_always_trusted(self):
        # Launchpad admins are special, and as such, are trusted.
        branch = self.factory.makeAnyBranch()
        admins = getUtility(ILaunchpadCelebrities).admin
        # Grab a random admin, the teamowner is good enough here.
        self.assertTrustedReviewer(branch, admins.teamowner)

    def test_member_of_team_owned_branch(self):
        # If the branch is owned by a team, any team member is a trusted
        # reviewer.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(owner=team)
        self.assertTrustedReviewer(branch, team.teamowner)

    def test_review_team_member_is_trusted(self):
        # If the reviewer is a member of the review team, but not the owner
        # they are still trusted.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        self.assertTrustedReviewer(branch, team.teamowner)

    def test_branch_owner_not_review_team_member_is_trusted(self):
        # If the owner of the branch is not in the review team, they are still
        # trusted.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        self.assertFalse(branch.owner.inTeam(team))
        self.assertTrustedReviewer(branch, branch.owner)

    def test_community_reviewer(self):
        # If the reviewer is not a member of the owner, or the review team,
        # they are not trusted reviewers.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        reviewer = self.factory.makePerson()
        self.assertNotTrustedReviewer(branch, reviewer)


class TestBranchSetOwner(TestCaseWithFactory):
    """Tests for IBranch.setOwner."""

    layer = DatabaseFunctionalLayer

    def test_owner_sets_team(self):
        # The owner of the branch can set the owner of the branch to be a team
        # they are a member of.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam(owner=branch.owner)
        login_person(branch.owner)
        branch.setOwner(team, branch.owner)
        self.assertEqual(team, branch.owner)

    def test_owner_cannot_set_nonmember_team(self):
        # The owner of the branch cannot set the owner to be a team they are
        # not a member of.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam()
        login_person(branch.owner)
        self.assertRaises(
            BranchCreatorNotMemberOfOwnerTeam,
            branch.setOwner,
            team, branch.owner)

    def test_owner_cannot_set_other_user(self):
        # The owner of the branch cannot set the new owner to be another
        # person.
        branch = self.factory.makeAnyBranch()
        person = self.factory.makePerson()
        login_person(branch.owner)
        self.assertRaises(
            BranchCreatorNotOwner,
            branch.setOwner,
            person, branch.owner)

    def test_admin_can_set_any_team_or_person(self):
        # A Launchpad admin can set the branch to be owned by any team or
        # person.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam()
        # To get a random administrator, choose the admin team owner.
        admin = getUtility(ILaunchpadCelebrities).admin.teamowner
        login_person(admin)
        branch.setOwner(team, admin)
        self.assertEqual(team, branch.owner)
        person = self.factory.makePerson()
        branch.setOwner(person, admin)
        self.assertEqual(person, branch.owner)

    def test_bazaar_experts_can_set_any_team_or_person(self):
        # A bazaar expert can set the branch to be owned by any team or
        # person.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam()
        # To get a random administrator, choose the admin team owner.
        experts = getUtility(ILaunchpadCelebrities).bazaar_experts.teamowner
        login_person(experts)
        branch.setOwner(team, experts)
        self.assertEqual(team, branch.owner)
        person = self.factory.makePerson()
        branch.setOwner(person, experts)
        self.assertEqual(person, branch.owner)


class TestBranchSetTarget(TestCaseWithFactory):
    """Tests for IBranch.setTarget."""

    layer = DatabaseFunctionalLayer

    def test_not_both_project_and_source_package(self):
        # Only one of project or source_package can be passed in, not both.
        branch = self.factory.makePersonalBranch()
        project = self.factory.makeProduct()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        self.assertRaises(
            BranchTargetError,
            branch.setTarget,
            user=branch.owner, project=project, source_package=source_package)

    def test_junk_branch_to_project_branch(self):
        # A junk branch can be moved to a project.
        branch = self.factory.makePersonalBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_junk_branch_to_package_branch(self):
        # A junk branch can be moved to a source package.
        branch = self.factory.makePersonalBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_project_branch_to_other_project_branch(self):
        # Move a branch from one project to another.
        branch = self.factory.makeProductBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_project_branch_to_package_branch(self):
        # Move a branch from a project to a package.
        branch = self.factory.makeProductBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_project_branch_to_junk_branch(self):
        # Move a branch from a project to junk.
        branch = self.factory.makeProductBranch()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner)
        self.assertEqual(branch.owner, branch.target.context)

    def test_package_branch_to_other_package_branch(self):
        # Move a branch from one package to another.
        branch = self.factory.makePackageBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_package_branch_to_project_branch(self):
        # Move a branch from a package to a project.
        branch = self.factory.makePackageBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_package_branch_to_junk_branch(self):
        # Move a branch from a package to junk.
        branch = self.factory.makePackageBranch()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner)
        self.assertEqual(branch.owner, branch.target.context)


class TestScheduleDiffUpdates(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_scheduleDiffUpdates(self):
        """Create jobs for all merge proposals."""
        bmp1 = self.factory.makeBranchMergeProposal()
        bmp2 = self.factory.makeBranchMergeProposal(
            source_branch=bmp1.source_branch)
        jobs = bmp1.source_branch.scheduleDiffUpdates()
        self.assertEqual(2, len(jobs))
        bmps_to_update = set(
            removeSecurityProxy(job).branch_merge_proposal for job in jobs)
        self.assertEqual(set([bmp1, bmp2]), bmps_to_update)

    def test_scheduleDiffUpdates_ignores_final(self):
        """Diffs for proposals in final states aren't updated."""
        source_branch = self.factory.makeBranch()
        for state in FINAL_STATES:
            self.factory.makeBranchMergeProposal(
                source_branch=source_branch, set_state=state)
        # Creating a superseded proposal has the side effect of creating a
        # second proposal.  Delete the second proposal.
        for bmp in source_branch.landing_targets:
            if bmp.queue_status not in FINAL_STATES:
                removeSecurityProxy(bmp).deleteProposal()
        jobs = source_branch.scheduleDiffUpdates()
        self.assertEqual(0, len(jobs))


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
