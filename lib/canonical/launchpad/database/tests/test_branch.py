# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Tests for Branches."""

__metaclass__ = type

from datetime import datetime, timedelta
from unittest import TestCase, TestLoader

from pytz import UTC

from sqlobject import SQLObjectNotFound

import transaction

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.launchpad import _
from canonical.launchpad.database.branch import (
    BranchSet, ClearDependentBranch, ClearSeriesBranch, DeleteCodeImport,
    DeletionCallable, DeletionOperation)
from canonical.launchpad.database.branchjob import BranchDiffJob
from canonical.launchpad.database.branchmergeproposal import (
    BranchMergeProposal)
from canonical.launchpad.database.bugbranch import BugBranch
from canonical.launchpad.database.codeimport import CodeImport, CodeImportSet
from canonical.launchpad.database.codereviewcomment import CodeReviewComment
from canonical.launchpad.database.product import ProductSet
from canonical.launchpad.database.specificationbranch import (
    SpecificationBranch)
from canonical.launchpad.database.sourcepackage import SourcePackage
from canonical.launchpad.ftests import (
    ANONYMOUS, login, login_person, logout, syncUpdate)
from canonical.launchpad.interfaces import (
    BranchListingSort, BranchSubscriptionNotificationLevel, BranchType,
    CannotDeleteBranch, CodeReviewNotificationLevel, CreateBugParams,
    IBranchSet, IBugSet, ILaunchpadCelebrities, IPersonSet, IProductSet,
    ISpecificationSet, InvalidBranchMergeProposal, PersonCreationRationale,
    SpecificationDefinitionStatus)
from canonical.launchpad.interfaces.branch import (
    BranchLifecycleStatus, DEFAULT_BRANCH_STATUS_IN_LISTING, NoSuchBranch)
from canonical.launchpad.interfaces.branchnamespace import (
    get_branch_namespace, InvalidNamespace)
from canonical.launchpad.interfaces.codehosting import LAUNCHPAD_SERVICES
from canonical.launchpad.interfaces.person import NoSuchPerson
from canonical.launchpad.interfaces.product import NoSuchProduct
from canonical.launchpad.testing import (
    LaunchpadObjectFactory, TestCaseWithFactory)
from canonical.launchpad.webapp.interfaces import IOpenLaunchBag
from canonical.launchpad.xmlrpc.faults import (
    InvalidBranchIdentifier, InvalidProductIdentifier, NoBranchForSeries,
    NoSuchSeries)

from canonical.testing import DatabaseFunctionalLayer, LaunchpadZopelessLayer


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
        br = self.branch.createBranchRevision(revno, rev)
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
        rev1 = self._makeRevision(1)
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

    def test_container_name_junk(self):
        branch = self.factory.makePersonalBranch()
        self.assertEqual('+junk', branch.container.name)

    def test_container_name_product(self):
        branch = self.factory.makeProductBranch()
        self.assertEqual(branch.product.name, branch.container.name)

    def test_container_name_package(self):
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            '%s/%s/%s' % (
                branch.distribution.name, branch.distroseries.name,
                branch.sourcepackagename.name),
            branch.container.name)

    def makeLaunchBag(self):
        return getUtility(IOpenLaunchBag)

    def test_addToLaunchBag_product(self):
        # Branches are not added directly to the launchbag. Instead,
        # information about their container is added.
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


class TestGetByUniqueName(TestCaseWithFactory):
    """Tests for `IBranchSet.getByUniqueName`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.branch_set = getUtility(IBranchSet)

    def test_not_found(self):
        unused_name = self.factory.getUniqueString()
        found = self.branch_set.getByUniqueName(unused_name)
        self.assertIs(None, found)

    def test_junk(self):
        branch = self.factory.makePersonalBranch()
        found_branch = self.branch_set.getByUniqueName(branch.unique_name)
        self.assertEqual(branch, found_branch)

    def test_product(self):
        branch = self.factory.makeProductBranch()
        found_branch = self.branch_set.getByUniqueName(branch.unique_name)
        self.assertEqual(branch, found_branch)

    def test_source_package(self):
        branch = self.factory.makePackageBranch()
        found_branch = self.branch_set.getByUniqueName(branch.unique_name)
        self.assertEqual(branch, found_branch)


class TestGetByPath(TestCaseWithFactory):
    """Test `IBranchSet._getByPath`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self._unsafe_branch_set = removeSecurityProxy(getUtility(IBranchSet))

    def getByPath(self, path):
        return self._unsafe_branch_set._getByPath(path)

    def makeRelativePath(self):
        arbitrary_num_segments = 7
        return '/'.join([
            self.factory.getUniqueString()
            for i in range(arbitrary_num_segments)])

    def test_finds_exact_personal_branch(self):
        branch = self.factory.makePersonalBranch()
        found_branch, suffix = self.getByPath(branch.unique_name)
        self.assertEqual(branch, found_branch)
        self.assertEqual('', suffix)

    def test_finds_suffixed_personal_branch(self):
        branch = self.factory.makePersonalBranch()
        suffix = self.makeRelativePath()
        found_branch, found_suffix = self.getByPath(
            branch.unique_name + '/' + suffix)
        self.assertEqual(branch, found_branch)
        self.assertEqual(suffix, found_suffix)

    def test_missing_personal_branch(self):
        owner = self.factory.makePerson()
        namespace = get_branch_namespace(owner)
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        self.assertRaises(NoSuchBranch, self.getByPath, branch_name)

    def test_missing_suffixed_personal_branch(self):
        owner = self.factory.makePerson()
        namespace = get_branch_namespace(owner)
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        suffix = self.makeRelativePath()
        self.assertRaises(
            NoSuchBranch, self.getByPath, branch_name + '/' + suffix)

    def test_finds_exact_product_branch(self):
        branch = self.factory.makeProductBranch()
        found_branch, suffix = self.getByPath(branch.unique_name)
        self.assertEqual(branch, found_branch)
        self.assertEqual('', suffix)

    def test_finds_suffixed_product_branch(self):
        branch = self.factory.makeProductBranch()
        suffix = self.makeRelativePath()
        found_branch, found_suffix = self.getByPath(
            branch.unique_name + '/' + suffix)
        self.assertEqual(branch, found_branch)
        self.assertEqual(suffix, found_suffix)

    def test_missing_product_branch(self):
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = get_branch_namespace(owner, product=product)
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        self.assertRaises(NoSuchBranch, self.getByPath, branch_name)

    def test_missing_suffixed_product_branch(self):
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = get_branch_namespace(owner, product=product)
        suffix = self.makeRelativePath()
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        self.assertRaises(
            NoSuchBranch, self.getByPath, branch_name + '/' + suffix)

    def test_finds_exact_package_branch(self):
        branch = self.factory.makePackageBranch()
        found_branch, suffix = self.getByPath(branch.unique_name)
        self.assertEqual(branch, found_branch)
        self.assertEqual('', suffix)

    def test_missing_package_branch(self):
        owner = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = get_branch_namespace(
            owner, distroseries=distroseries,
            sourcepackagename=sourcepackagename)
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        self.assertRaises(NoSuchBranch, self.getByPath, branch_name)

    def test_missing_suffixed_package_branch(self):
        owner = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = get_branch_namespace(
            owner, distroseries=distroseries,
            sourcepackagename=sourcepackagename)
        suffix = self.makeRelativePath()
        branch_name = namespace.getBranchName(self.factory.getUniqueString())
        self.assertRaises(
            NoSuchBranch, self.getByPath, branch_name + '/' + suffix)

    def test_no_preceding_tilde(self):
        self.assertRaises(
            InvalidNamespace, self.getByPath, self.makeRelativePath())

    def test_too_short(self):
        person = self.factory.makePerson()
        self.assertRaises(
            InvalidNamespace, self.getByPath, '~%s' % person.name)

    def test_no_such_product(self):
        person = self.factory.makePerson()
        branch_name = '~%s/%s/%s' % (
            person.name, self.factory.getUniqueString(), 'branch-name')
        self.assertRaises(NoSuchProduct, self.getByPath, branch_name)


class TestBranchDeletion(TestCaseWithFactory):
    """Test the different cases that makes a branch deletable or not."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, 'test@canonical.com')
        self.product = ProductSet().getByName('firefox')
        self.user = getUtility(IPersonSet).getByEmail('test@canonical.com')
        self.branch_set = BranchSet()
        self.branch = BranchSet().new(
            BranchType.HOSTED, 'to-delete', self.user, self.user,
            self.product, None, 'A branch to delete')
        # The owner of the branch is subscribed to the branch when it is
        # created.  The tests here assume no initial connections, so
        # unsubscribe the branch owner here.
        self.branch.unsubscribe(self.branch.owner)

    def tearDown(self):
        logout()

    def test_deletable(self):
        """A newly created branch can be deleted without any problems."""
        self.assertEqual(self.branch.canBeDeleted(), True,
                         "A newly created branch should be able to be "
                         "deleted.")
        branch_id = self.branch.id
        branch_set = BranchSet()
        self.branch.destroySelf()
        self.assert_(branch_set.get(branch_id) is None,
                     "The branch has not been deleted.")

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
        bug.addBranch(self.branch, self.user)
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

    def test_associatedProductSeriesUserBranchDisablesDeletion(self):
        """A branch linked as a user_branch to a product series cannot be
        deleted.
        """
        self.product.development_focus.user_branch = self.branch
        syncUpdate(self.product.development_focus)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch that is a user branch for a product series"
                         " is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_associatedProductSeriesImportBranchDisablesDeletion(self):
        """A branch linked as an import_branch to a product series cannot
        be deleted.
        """
        self.product.development_focus.import_branch = self.branch
        syncUpdate(self.product.development_focus)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch that is an import branch for a product "
                         "series is not deletable.")
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
        self.assertEqual(BranchSet().getByUniqueName(unique_name), None,
                         "Branch was not deleted.")

    def test_landingTargetDisablesDeletion(self):
        """A branch with a landing target cannot be deleted."""
        target_branch = BranchSet().new(
            BranchType.HOSTED, 'landing-target', self.user, self.user,
            self.product, None)
        self.branch.addLandingTarget(self.user, target_branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a landing target is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_landingCandidateDisablesDeletion(self):
        """A branch with a landing candidate cannot be deleted."""
        source_branch = BranchSet().new(
            BranchType.HOSTED, 'landing-candidate', self.user, self.user,
            self.product, None)
        source_branch.addLandingTarget(self.user, self.branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a landing candidate is not"
                         " deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_dependentBranchDisablesDeletion(self):
        """A branch that is a dependent branch cannot be deleted."""
        source_branch = BranchSet().new(
            BranchType.HOSTED, 'landing-candidate', self.user, self.user,
            self.product, None)
        target_branch = BranchSet().new(
            BranchType.HOSTED, 'landing-target', self.user, self.user,
            self.product, None)
        source_branch.addLandingTarget(self.user, target_branch, self.branch)
        self.assertEqual(self.branch.canBeDeleted(), False,
                         "A branch with a dependent target is not deletable.")
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_relatedBranchJobsDeleted(self):
        # A branch with an associated branch job will delete those jobs.
        branch = self.factory.makeAnyBranch()
        BranchDiffJob.create(branch, 'from-spec', 'to-spec')
        branch.destroySelf()
        # Need to commit the transaction to fire off the constraint checks.
        transaction.commit()


class TestBranchDeletionConsequences(TestCase):
    """Test determination and application of branch deletion consequences."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('test@canonical.com')
        self.factory = LaunchpadObjectFactory()
        # Has to be a product branch because of merge proposals.
        self.branch = self.factory.makeProductBranch()
        self.branch_set = getUtility(IBranchSet)
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
        dependent_branch = self.factory.makeProductBranch(
            product=self.branch.product)
        # Remove the implicit subscriptions.
        target_branch.unsubscribe(target_branch.owner)
        dependent_branch.unsubscribe(dependent_branch.owner)
        merge_proposal1 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, dependent_branch)
        # Disable this merge proposal, to allow creating a new identical one
        lp_admins = getUtility(ILaunchpadCelebrities).admin
        merge_proposal1.rejectBranch(lp_admins, 'null:')
        syncUpdate(merge_proposal1)
        merge_proposal2 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, dependent_branch)
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
             ' proposal.'))
             },
                         self.branch.deletionRequirements())
        self.assertEqual({
            merge_proposal1:
            ('delete', _('This branch is the target branch of this merge'
             ' proposal.')),
            merge_proposal2:
            ('delete', _('This branch is the target branch of this merge'
             ' proposal.'))
            },
            merge_proposal1.target_branch.deletionRequirements())
        self.assertEqual({
            merge_proposal1:
            ('alter', _('This branch is the dependent branch of this merge'
             ' proposal.')),
            merge_proposal2:
            ('alter', _('This branch is the dependent branch of this merge'
             ' proposal.'))
            },
            merge_proposal1.dependent_branch.deletionRequirements())

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
        merge_proposal1_id = merge_proposal1.id
        merge_proposal1.dependent_branch.destroySelf(break_references=True)
        self.assertEqual(None, merge_proposal1.dependent_branch)

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
        bug.addBranch(self.branch, self.branch.owner)
        self.assertEqual({bug.bug_branches[0]:
            ('delete', _('This bug is linked to this branch.'))},
            self.branch.deletionRequirements())

    def test_branchWithBugDeletion(self):
        """break_links allows deleting a branch with a bug."""
        bug1 = self.factory.makeBug()
        bug2 = self.factory.makeBug()
        bug1.addBranch(self.branch, self.branch.owner)
        bug_branch1 = bug1.bug_branches[0]
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

    def test_branchWithSeriesUserRequirements(self):
        """Deletion requirements for a series' user_branch are right."""
        series = self.factory.makeSeries(self.branch)
        self.assertEqual(
            {series: ('alter',
            _('This series is linked to this branch.'))},
            self.branch.deletionRequirements())

    def test_branchWithSeriesImportRequirements(self):
        """Deletion requirements for a series' import_branch are right."""
        series = self.factory.makeSeries(import_branch=self.branch)
        self.assertEqual(
            {series: ('alter',
            _('This series is linked to this branch.'))},
            self.branch.deletionRequirements())

    def test_branchWithSeriesUserDeletion(self):
        """break_links allows deleting a series' user_branch."""
        series1 = self.factory.makeSeries(self.branch)
        series2 = self.factory.makeSeries(self.branch)
        self.branch.destroySelf(break_references=True)
        self.assertEqual(None, series1.user_branch)
        self.assertEqual(None, series2.user_branch)

    def test_branchWithSeriesImportDeletion(self):
        """break_links allows deleting a series' import_branch."""
        series = self.factory.makeSeries(import_branch=self.branch)
        self.branch.destroySelf(break_references=True)
        self.assertEqual(None, series.user_branch)

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
        """ClearDependent.__call__ must clear the dependent branch."""
        merge_proposal = removeSecurityProxy(self.makeMergeProposals()[0])
        ClearDependentBranch(merge_proposal)()
        self.assertEqual(None, merge_proposal.dependent_branch)

    def test_ClearSeriesUserBranch(self):
        """ClearSeriesBranch.__call__ must clear the user branch."""
        series = removeSecurityProxy(self.factory.makeSeries(self.branch))
        ClearSeriesBranch(series, self.branch)()
        self.assertEqual(None, series.user_branch)

    def test_ClearSeriesImportBranch(self):
        """ClearSeriesBranch.__call__ must clear the import branch."""
        series = removeSecurityProxy(
            self.factory.makeSeries(import_branch=self.branch))
        ClearSeriesBranch(series, self.branch)()
        self.assertEqual(None, series.import_branch)

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
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
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


class BranchAddLandingTarget(TestCase):
    """Exercise all the code paths for adding a landing target."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)
        self.branch_set = BranchSet()
        self.product = getUtility(IProductSet).getByName('firefox')

        self.user = getUtility(IPersonSet).getByName('no-priv')
        self.source = self.branch_set.new(
            BranchType.HOSTED, 'source-branch', self.user, self.user,
            self.product, None)
        self.target = self.branch_set.new(
            BranchType.HOSTED, 'target-branch', self.user, self.user,
            self.product, None)
        self.dependent = self.branch_set.new(
            BranchType.HOSTED, 'dependent-branch', self.user, self.user,
            self.product, None)

    def tearDown(self):
        logout()

    def test_junkSource(self):
        """Junk branches cannot be used as a source for merge proposals."""
        self.source.product = None
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

    def test_targetProduct(self):
        """The product of the target branch must match the product of the
        source branch.
        """
        self.target.product = None
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

        self.target.product = getUtility(IProductSet).getByName('bzr')
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target)

    def test_targetIsABranch(self):
        """The target of must be a branch."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.product)

    def test_targetMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.source)

    def test_dependentIsABranch(self):
        """The dependent branch, if it is there, must be a branch."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, dependent_branch=self.product)

    def test_dependentBranchSameProduct(self):
        """The dependent branch, if it is there, must be for the same product.
        """
        self.dependent.product = None
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.dependent)

        self.dependent.product = getUtility(IProductSet).getByName('bzr')
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.dependent)

    def test_dependentMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.source)

    def test_dependentMustNotBeTheTarget(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.target)

    def test_existingMergeProposal(self):
        """If there is an existing merge proposal for the source and target
        branch pair, then another landing target specifying the same pair
        raises.
        """
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.dependent)

        self.assertRaises(
            InvalidBranchMergeProposal, self.source.addLandingTarget,
            self.user, self.target, self.dependent)

    def test_existingRejectedMergeProposal(self):
        """If there is an existing rejected merge proposal for the source and
        target branch pair, then another landing target specifying the same
        pair is fine.
        """
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.dependent)
        proposal.rejectBranch(self.user, 'some_revision')
        syncUpdate(proposal)
        new_proposal = self.source.addLandingTarget(
            self.user, self.target, self.dependent)

    def test_attributeAssignment(self):
        """Smoke test to make sure the assignments are there."""
        whiteboard = u"Some whiteboard"
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.dependent, whiteboard)
        self.assertEqual(proposal.registrant, self.user)
        self.assertEqual(proposal.source_branch, self.source)
        self.assertEqual(proposal.target_branch, self.target)
        self.assertEqual(proposal.dependent_branch, self.dependent)
        self.assertEqual(proposal.whiteboard, whiteboard)


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

        bug.addBranch(branch, branch.owner)
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


class BranchSorting(TestCase):
    """Test cases for the sort_by option of BranchSet getBranch* methods."""

    layer = LaunchpadZopelessLayer

    def createPersonWithTwoBranches(self):
        """Create a person and two branches that belong to that person."""
        new_person, email = getUtility(IPersonSet).createPersonAndEmail(
            "test@example.com",
            PersonCreationRationale.OWNER_CREATED_LAUNCHPAD)

        branch_set = getUtility(IBranchSet)
        branch_a = branch_set.new(
            BranchType.MIRRORED, "a", new_person, new_person, None,
            "http://bzr.example.com/a")
        branch_b = branch_set.new(
            BranchType.MIRRORED, "b", new_person, new_person, None,
            "http://bzr.example.com/b")

        return new_person, branch_a, branch_b

    def assertEqualByID(self, first, second):
        """Compare two lists of database objects by id."""
        # XXX: 2007-10-22 MichaelHudson bug=154016: This is only needed
        # because getBranchesForContext queries the BranchWithSortKeys table
        # and we want to compare the results with objects from the Branch
        # table.  This method can be removed when we can get rid of
        # BranchWithSortKeys.
        self.assertEqual([a.id for a in first], [b.id for b in second])

    def xmas(self, year):
        """Create a UTC datetime for Christmas of the given year."""
        return datetime(year=year, month=12, day=25, tzinfo=UTC)

    def test_sortByRecentChanges(self):
        """Test the MOST/LEAST_RECENTLY_CHANGED_FIRST options."""
        new_person, modified_in_2005, modified_in_2006 = (
            self.createPersonWithTwoBranches())

        modified_in_2005.date_last_modified = self.xmas(2005)
        modified_in_2006.date_last_modified = self.xmas(2006)

        syncUpdate(modified_in_2005)
        syncUpdate(modified_in_2006)

        getBranchesForContext = getUtility(IBranchSet).getBranchesForContext
        self.assertEqualByID(
            getBranchesForContext(
                new_person,
                sort_by=BranchListingSort.MOST_RECENTLY_CHANGED_FIRST),
            [modified_in_2006, modified_in_2005])
        self.assertEqualByID(
            getBranchesForContext(
                new_person,
                sort_by=BranchListingSort.LEAST_RECENTLY_CHANGED_FIRST),
            [modified_in_2005, modified_in_2006])

    def test_sortByAge(self):
        """Test the NEWEST_FIRST and OLDEST_FIRST options."""
        new_person, created_in_2005, created_in_2006 = (
            self.createPersonWithTwoBranches())

        # In the normal course of things date_created is not writable and so
        # we have to use removeSecurityProxy() here.
        removeSecurityProxy(created_in_2005).date_created = self.xmas(2005)
        removeSecurityProxy(created_in_2006).date_created = self.xmas(2006)

        syncUpdate(created_in_2005)
        syncUpdate(created_in_2006)

        getBranchesForContext = getUtility(IBranchSet).getBranchesForContext
        self.assertEqualByID(
            getBranchesForContext(
                new_person, sort_by=BranchListingSort.NEWEST_FIRST),
            [created_in_2006, created_in_2005])
        self.assertEqualByID(
            getBranchesForContext(
                new_person, sort_by=BranchListingSort.OLDEST_FIRST),
            [created_in_2005, created_in_2006])


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


class TestGetByUrl(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def makeProductBranch(self):
        """Create a branch with aa/b/c as its unique name."""
        # XXX: JonathanLange 2009-01-13 spec=package-branches: This test is
        # bad because it assumes that the interesting branches for testing are
        # product branches.
        owner = self.factory.makePerson(name='aa')
        product = self.factory.makeProduct('b')
        return self.factory.makeProductBranch(
            owner=owner, product=product, name='c')

    def test_getByUrl_with_http(self):
        """getByUrl recognizes LP branches for http URLs."""
        branch = self.makeProductBranch()
        branch_set = getUtility(IBranchSet)
        branch2 = branch_set.getByUrl('http://bazaar.launchpad.dev/~aa/b/c')
        self.assertEqual(branch, branch2)

    def test_getByUrl_with_ssh(self):
        """getByUrl recognizes LP branches for bzr+ssh URLs."""
        branch = self.makeProductBranch()
        branch_set = getUtility(IBranchSet)
        branch2 = branch_set.getByUrl(
            'bzr+ssh://bazaar.launchpad.dev/~aa/b/c')
        self.assertEqual(branch, branch2)

    def test_getByUrl_with_sftp(self):
        """getByUrl recognizes LP branches for sftp URLs."""
        branch = self.makeProductBranch()
        branch_set = getUtility(IBranchSet)
        branch2 = branch_set.getByUrl('sftp://bazaar.launchpad.dev/~aa/b/c')
        self.assertEqual(branch, branch2)

    def test_getByUrl_with_ftp(self):
        """getByUrl does not recognize LP branches for ftp URLs.

        This is because Launchpad doesn't currently support ftp.
        """
        branch = self.makeProductBranch()
        branch_set = getUtility(IBranchSet)
        branch2 = branch_set.getByUrl('ftp://bazaar.launchpad.dev/~aa/b/c')
        self.assertIs(None, branch2)

    def test_getByURL_with_lp_prefix(self):
        """lp: URLs for the configured prefix are supported."""
        branch_set = getUtility(IBranchSet)
        url = '%s~aa/b/c' % config.codehosting.bzr_lp_prefix
        self.assertRaises(NoSuchPerson, branch_set.getByUrl, url)
        owner = self.factory.makePerson(name='aa')
        product = self.factory.makeProduct('b')
        branch2 = branch_set.getByUrl(url)
        self.assertIs(None, branch2)
        branch = self.factory.makeProductBranch(
            owner=owner, product=product, name='c')
        branch2 = branch_set.getByUrl(url)
        self.assertEqual(branch, branch2)

    def test_getByURL_for_production(self):
        """test_getByURL works with production values."""
        branch_set = getUtility(IBranchSet)
        branch = self.makeProductBranch()
        self.pushConfig('codehosting', lp_url_hosts='edge,production,,')
        branch2 = branch_set.getByUrl('lp://staging/~aa/b/c')
        self.assertIs(None, branch2)
        branch2 = branch_set.getByUrl('lp://asdf/~aa/b/c')
        self.assertIs(None, branch2)
        branch2 = branch_set.getByUrl('lp:~aa/b/c')
        self.assertEqual(branch, branch2)
        branch2 = branch_set.getByUrl('lp://production/~aa/b/c')
        self.assertEqual(branch, branch2)
        branch2 = branch_set.getByUrl('lp://edge/~aa/b/c')
        self.assertEqual(branch, branch2)


class TestGetByLPPath(TestCaseWithFactory):
    """Ensure URLs are correctly expanded."""

    layer = DatabaseFunctionalLayer

    # XXX: JonathanLange 2009-01-13 spec=package-branches: All of these tests
    # should be adjusted to assume less about the structure of branch names.
    # In particular, they should not call factory.makeBranch unless they have
    # to, instead calling the helper aliases.

    def test_getByLPPath_with_three_parts(self):
        """Test the behaviour with three-part names."""
        branch_set = getUtility(IBranchSet)
        self.assertRaises(
            InvalidBranchIdentifier, branch_set.getByLPPath, 'a/b/c')
        self.assertRaises(
            NoSuchPerson, branch_set.getByLPPath, '~aa/bb/c')
        owner = self.factory.makePerson(name='aa')
        self.assertRaises(NoSuchProduct, branch_set.getByLPPath, '~aa/bb/c')
        product = self.factory.makeProduct('bb')
        self.assertRaises(NoSuchBranch, branch_set.getByLPPath, '~aa/bb/c')
        branch = self.factory.makeProductBranch(
            owner=owner, product=product, name='c')
        self.assertEqual(
            (branch, None, None), branch_set.getByLPPath('~aa/bb/c'))

    def test_getByLPPath_with_junk_branch(self):
        """Test the behaviour with junk branches."""
        owner = self.factory.makePerson(name='aa')
        branch_set = getUtility(IBranchSet)
        self.assertRaises(NoSuchBranch, branch_set.getByLPPath, '~aa/+junk/c')
        branch = self.factory.makePersonalBranch(owner=owner, name='c')
        self.assertEqual(
            (branch, None, None), branch_set.getByLPPath('~aa/+junk/c'))

    def test_getByLPPath_with_two_parts(self):
        """Test the behaviour with two-part names."""
        branch_set = getUtility(IBranchSet)
        self.assertRaises(NoSuchProduct, branch_set.getByLPPath, 'bb/dd')
        product = self.factory.makeProduct('bb')
        self.assertRaises(NoSuchSeries, branch_set.getByLPPath, 'bb/dd')
        series = self.factory.makeSeries(name='dd', product=product)
        self.assertRaises(NoBranchForSeries, branch_set.getByLPPath, 'bb/dd')
        series.user_branch = self.factory.makeAnyBranch()
        self.assertEqual(
            (series.user_branch, None, series),
            branch_set.getByLPPath('bb/dd'))

    def test_getByLPPath_with_one_part(self):
        """Test the behaviour with one names."""
        branch_set = getUtility(IBranchSet)
        self.assertRaises(
            InvalidProductIdentifier, branch_set.getByLPPath, 'b')
        self.assertRaises(NoSuchProduct, branch_set.getByLPPath, 'bb')
        # We are not testing the security proxy here, so remove it.
        product = removeSecurityProxy(self.factory.makeProduct('bb'))
        self.assertRaises(NoBranchForSeries, branch_set.getByLPPath, 'bb')
        branch = self.factory.makeAnyBranch()
        product.development_focus.user_branch = branch
        self.assertEqual(
            (branch, None, product.development_focus),
            branch_set.getByLPPath('bb'))


class TestGetBranchForContextVisibleUser(TestCaseWithFactory):
    """Tests the visible_by_user checks for getBranchesForContext."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin user to set branch privacy easily.
        TestCaseWithFactory.setUp(self, 'admin@canonical.com')
        self.product = self.factory.makeProduct()
        self.public_branch = self.factory.makeProductBranch(
            product=self.product)
        self.private_branch_1 = self.factory.makeProductBranch(
            product=self.product, private=True)
        # Need a second private branch by another owner.
        self.private_branch_2 = self.factory.makeProductBranch(
            product=self.product, private=True)
        self.public_only = set([self.public_branch])
        self.all_branches = set(
            [self.public_branch, self.private_branch_1,
             self.private_branch_2])

    def _getBranches(self, visible_by_user=None):
        branches = getUtility(IBranchSet).getBranchesForContext(
            context=self.product, visible_by_user=visible_by_user)
        return set(branches)

    def test_anonymous_only_sees_public(self):
        # An anonymous user will only see public branches.
        self.assertEqual(self.public_only, self._getBranches())

    def test_normal_user_only_sees_public(self):
        # A user who is not the owner nor special only sees public branches.
        self.assertEqual(self.public_only, self._getBranches())

    def test_private_owner_sees_public_and_own(self):
        # A private branch owner can see their private branches and the public
        # branches.
        self.assertEqual(set([self.public_branch, self.private_branch_1]),
                         self._getBranches(self.private_branch_1.owner))

    def test_launchpad_services_sees_all(self):
        # The special launchpad services identity can see all branches.
        self.assertEqual(self.all_branches,
                         self._getBranches(LAUNCHPAD_SERVICES))

    def test_admins_see_all(self):
        # Launchpad admins see all.
        admin_user = self.factory.makePerson()
        celebs = getUtility(ILaunchpadCelebrities)
        celebs.admin.addMember(admin_user, celebs.admin.teamowner)

        self.assertEqual(self.all_branches, self._getBranches(admin_user))

    def test_bazaar_experts_see_all(self):
        # Bazaar experts see all.
        expert = self.factory.makePerson()
        celebs = getUtility(ILaunchpadCelebrities)
        celebs.bazaar_experts.addMember(
            expert, celebs.bazaar_experts.teamowner)

        self.assertEqual(self.all_branches, self._getBranches(expert))


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


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
