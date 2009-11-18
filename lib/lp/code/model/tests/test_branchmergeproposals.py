# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=F0401

"""Tests for BranchMergeProposals."""

__metaclass__ = type

from datetime import datetime
from difflib import unified_diff
from unittest import TestCase, TestLoader

from pytz import UTC
from sqlobject import SQLObjectNotFound
from zope.component import getUtility
import transaction
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.testing import (
    DatabaseFunctionalLayer, LaunchpadFunctionalLayer, LaunchpadZopelessLayer)
from lazr.lifecycle.event import ObjectModifiedEvent

from canonical.launchpad.interfaces import IPrivacy
from canonical.launchpad.interfaces.message import IMessageJob
from canonical.launchpad.webapp.testing import verifyObject
from lp.code.event.branchmergeproposal import (
    NewBranchMergeProposalEvent, NewCodeReviewCommentEvent,
    ReviewerNominatedEvent)
from canonical.launchpad.ftests import (
    ANONYMOUS, import_secret_test_key, login, syncUpdate)
from lp.code.enums import (
    BranchMergeProposalStatus, BranchSubscriptionNotificationLevel,
    BranchType, CodeReviewNotificationLevel, CodeReviewVote,
    BranchVisibilityRule)
from lp.code.interfaces.branchmergeproposal import (
    BadStateTransition,
    BRANCH_MERGE_PROPOSAL_FINAL_STATES as FINAL_STATES,
    IBranchMergeProposal, IBranchMergeProposalGetter, IBranchMergeProposalJob,
    ICreateMergeProposalJob, ICreateMergeProposalJobSource,
    IMergeProposalCreatedJob, notify_modified, WrongBranchMergeProposal)
from lp.code.model.branchmergeproposaljob import (
    BranchMergeProposalJob, BranchMergeProposalJobType,
    CreateMergeProposalJob, MergeProposalCreatedJob, UpdatePreviewDiffJob)
from lp.code.model.branchmergeproposal import (
    BranchMergeProposal, BranchMergeProposalGetter, is_valid_transition)
from lp.code.model.diff import StaticDiff
from lp.code.model.tests.test_diff import DiffTestCase
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProductSet
from lp.services.job.runner import JobRunner
from lp.testing import (
    capture_events, login_person, TestCaseWithFactory, time_counter)
from lp.testing.factory import GPGSigningContext, LaunchpadObjectFactory
from lp.testing.mail_helpers import pop_notifications


class TestBranchMergeProposalInterface(TestCaseWithFactory):
    """Ensure that BranchMergeProposal implements its interface."""

    layer = DatabaseFunctionalLayer

    def test_BranchMergeProposal_implements_interface(self):
        """Ensure that BranchMergeProposal implements its interface."""
        bmp = self.factory.makeBranchMergeProposal()
        verifyObject(IBranchMergeProposal, bmp)


class TestBranchMergeProposalPrivacy(TestCaseWithFactory):
    """Ensure that BranchMergeProposal implements privacy."""

    layer = DatabaseFunctionalLayer

    def test_BranchMergeProposal_implements_interface(self):
        """Ensure that BranchMergeProposal implements privacy."""
        bmp = self.factory.makeBranchMergeProposal()
        verifyObject(IPrivacy, bmp)

    @staticmethod
    def setPrivate(branch):
        """Force a branch to be private."""
        login_person(branch.owner)
        branch.product.setBranchVisibilityTeamPolicy(
            branch.owner, BranchVisibilityRule.PRIVATE)
        branch.setPrivate(True)

    def test_private(self):
        """Private flag should be True if True for any involved branch."""
        bmp = self.factory.makeBranchMergeProposal()
        self.assertFalse(bmp.private)
        self.setPrivate(bmp.source_branch)
        self.assertTrue(bmp.private)
        bmp.source_branch.setPrivate(False)
        self.setPrivate(bmp.target_branch)
        self.assertTrue(bmp.private)
        bmp.target_branch.setPrivate(False)
        removeSecurityProxy(bmp).prerequisite_branch = (
            self.factory.makeBranch(product=bmp.source_branch.product))
        self.setPrivate(bmp.prerequisite_branch)
        self.assertTrue(bmp.private)


class TestBranchMergeProposalTransitions(TestCaseWithFactory):
    """Test the state transitions of branch merge proposals."""

    layer = DatabaseFunctionalLayer

    # All transitions between states are handled my method calls
    # on the proposal.
    transition_functions = {
        BranchMergeProposalStatus.WORK_IN_PROGRESS: 'setAsWorkInProgress',
        BranchMergeProposalStatus.NEEDS_REVIEW: 'requestReview',
        BranchMergeProposalStatus.CODE_APPROVED: 'approveBranch',
        BranchMergeProposalStatus.REJECTED: 'rejectBranch',
        BranchMergeProposalStatus.MERGED: 'markAsMerged',
        BranchMergeProposalStatus.MERGE_FAILED: 'mergeFailed',
        BranchMergeProposalStatus.QUEUED: 'enqueue',
        BranchMergeProposalStatus.SUPERSEDED: 'resubmit',
        }

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.target_branch = self.factory.makeProductBranch()
        login_person(self.target_branch.owner)

    def assertProposalState(self, proposal, state):
        """Assert that the `queue_status` of the `proposal` is `state`."""
        self.assertEqual(state, proposal.queue_status,
                         "Wrong state, expected %s, got %s"
                         % (state.title, proposal.queue_status.title))

    def _attemptTransition(self, proposal, to_state):
        """Try to transition the proposal into the state `to_state`."""
        method = getattr(proposal, self.transition_functions[to_state])
        if to_state in (BranchMergeProposalStatus.CODE_APPROVED,
                        BranchMergeProposalStatus.REJECTED,
                        BranchMergeProposalStatus.QUEUED):
            args = [proposal.target_branch.owner, 'some_revision_id']
        elif to_state in (BranchMergeProposalStatus.MERGE_FAILED,
                          BranchMergeProposalStatus.SUPERSEDED):
            args = [proposal.registrant]
        else:
            args = []
        method(*args)

    def assertGoodTransition(self, from_state, to_state):
        """Assert that we can go from `from_state` to `to_state`."""
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=from_state)
        self.assertProposalState(proposal, from_state)
        self._attemptTransition(proposal, to_state)
        self.assertProposalState(proposal, to_state)

    def assertBadTransition(self, from_state, to_state):
        """Assert that trying to go from `from_state` to `to_state` fails."""
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=from_state)
        self.assertProposalState(proposal, from_state)
        self.assertRaises(BadStateTransition,
                          self._attemptTransition,
                          proposal, to_state)

    def prepareDupeTransition(self, from_state):
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=from_state)
        if from_state == BranchMergeProposalStatus.SUPERSEDED:
            # Setting a proposal SUPERSEDED has the side effect of creating
            # an active duplicate proposal, so make it inactive.
            proposal.superseded_by.rejectBranch(self.target_branch.owner,
                                                None)
        self.assertProposalState(proposal, from_state)
        dupe = self.factory.makeBranchMergeProposal(
            target_branch=proposal.target_branch,
            source_branch=proposal.source_branch)
        return proposal

    def assertBadDupeTransition(self, from_state, to_state):
        """Assert that trying to go from `from_state` to `to_state` fails."""
        proposal = self.prepareDupeTransition(from_state)
        self.assertRaises(BadStateTransition,
                          self._attemptTransition,
                          proposal, to_state)


    def assertGoodDupeTransition(self, from_state, to_state):
        """Trying to go from `from_state` to `to_state` succeeds."""
        proposal = self.prepareDupeTransition(from_state)
        self._attemptTransition(proposal, to_state)
        self.assertProposalState(proposal, to_state)

    def assertAllTransitionsGood(self, from_state):
        """Assert that we can go from `from_state` to any state."""
        for status in BranchMergeProposalStatus.items:
            self.assertGoodTransition(from_state, status)

    def test_transitions_from_wip(self):
        """We can go from work in progress to any other state."""
        self.assertAllTransitionsGood(
            BranchMergeProposalStatus.WORK_IN_PROGRESS)

    def test_transitions_from_needs_review(self):
        """We can go from needs review to any other state."""
        self.assertAllTransitionsGood(
            BranchMergeProposalStatus.NEEDS_REVIEW)

    def test_transitions_from_code_approved(self):
        """We can go from code_approved to any other state."""
        self.assertAllTransitionsGood(
            BranchMergeProposalStatus.CODE_APPROVED)

    def test_transitions_from_rejected(self):
        """Rejected proposals can only be resubmitted."""
        # Test the transitions from rejected.
        self.assertAllTransitionsGood(BranchMergeProposalStatus.REJECTED)

    def test_transition_from_final_with_dupes(self):
        """Proposals cannot be set active if there are similar active ones.

        So transitioning from a final state to an active one should cause
        an exception, but transitioning from a final state to a different
        final state should be fine.
        """
        for from_status in FINAL_STATES:
            for to_status in BranchMergeProposalStatus.items:
                if to_status == BranchMergeProposalStatus.SUPERSEDED:
                    continue
                if to_status in FINAL_STATES:
                    self.assertGoodDupeTransition(from_status, to_status)
                else:
                    self.assertBadDupeTransition(from_status, to_status)

    def assertValidTransitions(self, expected, proposal, to_state, by_user):
        # Check the valid transitions for the merge proposal by the specified
        # user.
        valid = set()
        for state in BranchMergeProposalStatus.items:
            if is_valid_transition(proposal, state, to_state, by_user):
                valid.add(state)
        self.assertEqual(expected, valid)

    def test_transition_to_rejected_by_reviewer(self):
        # A proposal should be able to go from any states to rejected if the
        # user is a reviewer.
        valid_transitions = set(BranchMergeProposalStatus.items)
        proposal = self.factory.makeBranchMergeProposal()
        self.assertValidTransitions(
            valid_transitions, proposal, BranchMergeProposalStatus.REJECTED,
            proposal.target_branch.owner)

    def test_transition_to_rejected_by_non_reviewer(self):
        # A non-reviewer should not be able to set a proposal as rejected.
        proposal = self.factory.makeBranchMergeProposal()
        # It is always valid to go to the same state.
        self.assertValidTransitions(
            set([BranchMergeProposalStatus.REJECTED]),
            proposal, BranchMergeProposalStatus.REJECTED,
            proposal.source_branch.owner)

    def test_transitions_from_merge_failed(self):
        """We can go from merge failed to any other state."""
        self.assertAllTransitionsGood(BranchMergeProposalStatus.MERGE_FAILED)

    def test_transitions_from_queued_dequeue(self):
        # When a proposal is dequeued it is set to code approved, and the
        # queue position is reset.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.QUEUED)
        proposal.dequeue()
        self.assertProposalState(
            proposal, BranchMergeProposalStatus.CODE_APPROVED)
        self.assertIs(None, proposal.queue_position)
        self.assertIs(None, proposal.queuer)
        self.assertIs(None, proposal.queued_revision_id)
        self.assertIs(None, proposal.date_queued)

    def test_transitions_from_queued_to_merged(self):
        # When a proposal is marked as merged from queued, the queue_position
        # is reset.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.QUEUED)
        proposal.markAsMerged()
        self.assertProposalState(
            proposal, BranchMergeProposalStatus.MERGED)
        self.assertIs(None, proposal.queue_position)

    def test_transitions_from_queued_to_merge_failed(self):
        # When a proposal is marked as merged from queued, the queue_position
        # is reset.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.QUEUED)
        proposal.mergeFailed(None)
        self.assertProposalState(
            proposal, BranchMergeProposalStatus.MERGE_FAILED)
        self.assertIs(None, proposal.queue_position)

    def test_transitions_to_wip_resets_reviewer(self):
        # When a proposal was approved and is moved back into work in progress
        # the reviewer, date reviewed, and reviewed revision are all reset.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.CODE_APPROVED)
        self.assertIsNot(None, proposal.reviewer)
        self.assertIsNot(None, proposal.date_reviewed)
        self.assertIsNot(None, proposal.reviewed_revision_id)
        proposal.setAsWorkInProgress()
        self.assertIs(None, proposal.reviewer)
        self.assertIs(None, proposal.date_reviewed)
        self.assertIs(None, proposal.reviewed_revision_id)


class TestBranchMergeProposalSetStatus(TestCaseWithFactory):
    """Test the setStatus method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.target_branch = self.factory.makeProductBranch()
        login_person(self.target_branch.owner)

    def test_set_status_approved_to_work_in_progress(self):
        # setState can change an approved merge proposal to Work In Progress.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.CODE_APPROVED)
        proposal.setStatus(BranchMergeProposalStatus.WORK_IN_PROGRESS)
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.WORK_IN_PROGRESS)

    def test_set_status_wip_to_needs_review(self):
        # setState can change the merge proposal to Needs Review.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        proposal.setStatus(BranchMergeProposalStatus.NEEDS_REVIEW)
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.NEEDS_REVIEW)

    def test_set_status_wip_to_code_approved(self):
        # setState can change the merge proposal to Approved, which will
        # also set the reviewed_revision_id to the approved revision id.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        proposal.setStatus(BranchMergeProposalStatus.CODE_APPROVED,
            user=self.target_branch.owner, revision_id='500')
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.CODE_APPROVED)
        self.assertEqual(proposal.reviewed_revision_id, '500')

    def test_set_status_wip_to_queued(self):
        # setState can change the merge proposal to Queued, which will
        # also set the queued_revision_id to the specified revision id.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        proposal.setStatus(BranchMergeProposalStatus.QUEUED,
            user=self.target_branch.owner, revision_id='250')
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.QUEUED)
        self.assertEqual(proposal.queued_revision_id, '250')

    def test_set_status_wip_to_rejected(self):
        # setState can change the merge proposal to Rejected, which also
        # marks the reviewed_revision_id to the rejected revision id.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        proposal.setStatus(BranchMergeProposalStatus.REJECTED,
            user=self.target_branch.owner, revision_id='1000')
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.REJECTED)
        self.assertEqual(proposal.reviewed_revision_id, '1000')

    def test_set_status_wip_to_merged(self):
        # setState can change the merge proposal to Merged.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        proposal.setStatus(BranchMergeProposalStatus.MERGED)
        self.assertEqual(proposal.queue_status,
            BranchMergeProposalStatus.MERGED)

    def test_set_status_invalid_status(self):
        # IBranchMergeProposal.setStatus doesn't work in the case of
        # superseded branches since a superseded branch requires more than
        # just changing a few settings.  Because it's unknown, it should
        # raise an AssertionError.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS)
        self.assertRaises(AssertionError, proposal.setStatus,
            BranchMergeProposalStatus.SUPERSEDED)


class TestBranchMergeProposalRequestReview(TestCaseWithFactory):
    """Test the resetting of date_review_reqeuested."""

    layer = DatabaseFunctionalLayer

    def _createMergeProposal(self, needs_review):
        # Create and return a merge proposal.
        source_branch = self.factory.makeProductBranch()
        target_branch = self.factory.makeProductBranch(
            product=source_branch.product)
        login_person(target_branch.owner)
        return source_branch.addLandingTarget(
            source_branch.owner, target_branch,
            date_created=datetime(2000, 1, 1, 12, tzinfo=UTC),
            needs_review=needs_review)

    def test_date_set_on_change(self):
        # When the proposal changes to needs review state the date is
        # recoreded.
        proposal = self._createMergeProposal(needs_review=False)
        self.assertEqual(
            BranchMergeProposalStatus.WORK_IN_PROGRESS,
            proposal.queue_status)
        self.assertIs(None, proposal.date_review_requested)
        # Requesting the merge then sets the date review requested.
        proposal.requestReview()
        self.assertSqlAttributeEqualsDate(
            proposal, 'date_review_requested', UTC_NOW)

    def test_date_not_reset_on_rerequest(self):
        # When the proposal changes to needs review state the date is
        # recoreded.
        proposal = self._createMergeProposal(needs_review=True)
        self.assertEqual(
            BranchMergeProposalStatus.NEEDS_REVIEW,
            proposal.queue_status)
        self.assertEqual(
            proposal.date_created, proposal.date_review_requested)
        # Requesting the merge again will not reset the date review requested.
        proposal.requestReview()
        self.assertEqual(
            proposal.date_created, proposal.date_review_requested)


class TestBranchMergeProposalQueueing(TestCase):
    """Test the enqueueing and dequeueing of merge proposals."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        login(ANONYMOUS)
        factory = LaunchpadObjectFactory()
        owner = factory.makePerson()
        self.target_branch = factory.makeProductBranch(owner=owner)
        login(self.target_branch.owner.preferredemail.email)
        self.proposals = [
            factory.makeBranchMergeProposal(self.target_branch)
            for x in range(4)]

    def test_empty_target_queue(self):
        """If there are no proposals targeted to the branch, the queue has
        nothing in it."""
        queued_proposals = list(self.target_branch.getMergeQueue())
        self.assertEqual(0, len(queued_proposals),
                         "The initial merge queue should be empty.")

    def test_single_item_in_queue(self):
        """Enqueing a proposal makes it visible in the target branch queue."""
        proposal = self.proposals[0]
        proposal.enqueue(self.target_branch.owner, 'some-revision-id')
        queued_proposals = list(self.target_branch.getMergeQueue())
        self.assertEqual(1, len(queued_proposals),
                         "Should have one entry in the queue, got %s."
                         % len(queued_proposals))

    def test_queue_ordering(self):
        """Assert that the queue positions are based on the order the
        proposals were enqueued."""
        enqueued_order = []
        for proposal in self.proposals[:-1]:
            enqueued_order.append(proposal.source_branch.unique_name)
            proposal.enqueue(self.target_branch.owner, 'some-revision')
        queued_proposals = list(self.target_branch.getMergeQueue())
        queue_order = [proposal.source_branch.unique_name
                       for proposal in queued_proposals]
        self.assertEqual(
            enqueued_order, queue_order,
            "The queue should be in the order they were added. "
            "Expected %s, got %s" % (enqueued_order, queue_order))

        # Move the last one to the front.
        proposal = queued_proposals[-1]
        proposal.moveToFrontOfQueue()

        new_queue_order = enqueued_order[-1:] + enqueued_order[:-1]

        queued_proposals = list(self.target_branch.getMergeQueue())
        queue_order = [proposal.source_branch.unique_name
                       for proposal in queued_proposals]
        self.assertEqual(
            new_queue_order, queue_order,
            "The last should now be at the front. "
            "Expected %s, got %s" % (new_queue_order, queue_order))

        # Remove the proposal from the middle of the queue.
        proposal = queued_proposals[1]
        proposal.dequeue()
        syncUpdate(proposal)

        del new_queue_order[1]

        queued_proposals = list(self.target_branch.getMergeQueue())
        queue_order = [proposal.source_branch.unique_name
                       for proposal in queued_proposals]
        self.assertEqual(
            new_queue_order, queue_order,
            "There should be only two queued items now. "
            "Expected %s, got %s" % (new_queue_order, queue_order))


class TestRootComment(TestCase):
    """Test the behavior of the root_comment attribute"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        login('foo.bar@canonical.com')
        self.factory = LaunchpadObjectFactory()
        self.merge_proposal = self.factory.makeBranchMergeProposal()

    def test_orderedByDateNotInsertion(self):
        """Root is determined by create date, not insert order"""
        counter = time_counter()
        oldest_date, middle_date, newest_date = [counter.next() for index in
            (1, 2, 3)]
        comment1 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject",
            _date_created=middle_date)
        self.assertEqual(comment1, self.merge_proposal.root_comment)
        comment2 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject",
            _date_created=newest_date)
        self.assertEqual(comment1, self.merge_proposal.root_comment)
        comment3 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject",
            _date_created=oldest_date)
        self.assertEqual(comment3, self.merge_proposal.root_comment)


class TestCreateCommentNotifications(TestCaseWithFactory):
    """Test the notifications are raised at the right times."""

    layer = DatabaseFunctionalLayer

    def test_notify_on_nominate(self):
        # Ensure that a notification is emitted when a new comment is added.
        merge_proposal = self.factory.makeBranchMergeProposal()
        commenter = self.factory.makePerson()
        login_person(commenter)
        result, event = self.assertNotifies(
            NewCodeReviewCommentEvent,
            merge_proposal.createComment,
            owner=commenter,
            subject='A review.')
        self.assertEqual(result, event.object)

    def test_notify_on_nominate_suppressed_if_requested(self):
        # Ensure that the notification is supressed if the notify listeners
        # parameger is set to False.
        merge_proposal = self.factory.makeBranchMergeProposal()
        commenter = self.factory.makePerson()
        login_person(commenter)
        self.assertNoNotification(
            merge_proposal.createComment,
            owner=commenter,
            subject='A review.',
            _notify_listeners=False)


class TestMergeProposalAllComments(TestCase):
    """Tester for `BranchMergeProposal.all_comments`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        # Testing behavior, not permissions here.
        login('foo.bar@canonical.com')
        self.factory = LaunchpadObjectFactory()
        self.merge_proposal = self.factory.makeBranchMergeProposal()

    def test_all_comments(self):
        """Ensure all comments associated with the proposal are returned."""
        comment1 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject")
        comment2 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject")
        comment3 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject")
        self.assertEqual(
            set([comment1, comment2, comment3]),
            set(self.merge_proposal.all_comments))


class TestMergeProposalGetComment(TestCase):
    """Tester for `BranchMergeProposal.getComment`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        # Testing behavior, not permissions here.
        login('foo.bar@canonical.com')
        self.factory = LaunchpadObjectFactory()
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        self.merge_proposal2 = self.factory.makeBranchMergeProposal()
        self.comment = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject")

    def test_getComment(self):
        """Tests that we can get a comment."""
        self.assertEqual(
            self.comment, self.merge_proposal.getComment(self.comment.id))

    def test_getCommentWrongBranchMergeProposal(self):
        """Tests that we can get a comment."""
        self.assertRaises(WrongBranchMergeProposal,
                          self.merge_proposal2.getComment, self.comment.id)


class TestMergeProposalGetVoteReference(TestCaseWithFactory):
    """Tester for `BranchMergeProposal.getComment`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        # Testing behavior, not permissions here.
        login('foo.bar@canonical.com')
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        self.merge_proposal2 = self.factory.makeBranchMergeProposal()
        self.vote = self.merge_proposal.nominateReviewer(
            reviewer=self.merge_proposal.registrant,
            registrant=self.merge_proposal.registrant)

    def test_getVoteReference(self):
        """Tests that we can get a comment."""
        self.assertEqual(
            self.vote, self.merge_proposal.getVoteReference(
                self.vote.id))

    def test_getVoteReferenceWrongBranchMergeProposal(self):
        """Tests that we can get a comment."""
        self.assertRaises(WrongBranchMergeProposal,
                          self.merge_proposal2.getVoteReference,
                          self.vote.id)


class TestMergeProposalNotification(TestCaseWithFactory):
    """Test that events are created when merge proposals are manipulated"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def test_notifyOnCreate(self):
        """Ensure that a notification is emitted on creation"""
        source_branch = self.factory.makeProductBranch()
        target_branch = self.factory.makeProductBranch(
            product=source_branch.product)
        registrant = self.factory.makePerson()
        result, event = self.assertNotifies(
            NewBranchMergeProposalEvent,
            source_branch.addLandingTarget, registrant, target_branch)
        self.assertEqual(result, event.object)

    def test_getNotificationRecipients(self):
        """Ensure that recipients can be added/removed with subscribe"""
        bmp = self.factory.makeBranchMergeProposal()
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.source_branch.owner
        target_owner = bmp.target_branch.owner
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        subscriber_set = set([source_owner, target_owner])
        self.assertEqual(subscriber_set, set(recipients.keys()))
        source_subscriber = self.factory.makePerson()
        bmp.source_branch.subscribe(source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        subscriber_set.add(source_subscriber)
        self.assertEqual(subscriber_set, set(recipients.keys()))
        bmp.source_branch.subscribe(source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.NOEMAIL)
        # By specifying no email, they will no longer get email.
        subscriber_set.remove(source_subscriber)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        self.assertEqual(subscriber_set, set(recipients.keys()))

    def test_getNotificationRecipientLevels(self):
        """Ensure that only recipients with the right level are returned"""
        bmp = self.factory.makeBranchMergeProposal()
        full_subscriber = self.factory.makePerson()
        bmp.source_branch.subscribe(full_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        status_subscriber = self.factory.makePerson()
        bmp.source_branch.subscribe(status_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.STATUS)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.source_branch.owner
        target_owner = bmp.target_branch.owner
        self.assertEqual(set([full_subscriber, status_subscriber,
                              source_owner, target_owner]),
                         set(recipients.keys()))
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL)
        self.assertEqual(set([full_subscriber, source_owner, target_owner]),
                         set(recipients.keys()))

    def test_getNotificationRecipientsAnyBranch(self):
        prerequisite_branch = self.factory.makeProductBranch()
        bmp = self.factory.makeBranchMergeProposal(
            prerequisite_branch=prerequisite_branch)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.NOEMAIL)
        source_owner = bmp.source_branch.owner
        target_owner = bmp.target_branch.owner
        prerequisite_owner = bmp.prerequisite_branch.owner
        self.assertEqual(
            set([source_owner, target_owner, prerequisite_owner]),
            set(recipients.keys()))
        source_subscriber = self.factory.makePerson()
        bmp.source_branch.subscribe(source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        target_subscriber = self.factory.makePerson()
        bmp.target_branch.subscribe(target_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        prerequisite_subscriber = self.factory.makePerson()
        bmp.prerequisite_branch.subscribe(prerequisite_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL)
        self.assertEqual(
            set([source_subscriber, target_subscriber,
                 prerequisite_subscriber, source_owner, target_owner,
                 prerequisite_owner]),
            set(recipients.keys()))

    def test_getNotificationRecipientsIncludesReviewers(self):
        bmp = self.factory.makeBranchMergeProposal()
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.source_branch.owner
        target_owner = bmp.target_branch.owner
        login_person(source_owner)
        reviewer = self.factory.makePerson()
        bmp.nominateReviewer(reviewer, registrant=source_owner)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        subscriber_set = set([source_owner, target_owner, reviewer])
        self.assertEqual(subscriber_set, set(recipients.keys()))

    def test_getNotificationRecipients_Registrant(self):
        # If the registrant of the proposal is being notified of the
        # proposals, they get their rationale set to "Registrant".
        registrant = self.factory.makePerson()
        bmp = self.factory.makeBranchMergeProposal(registrant=registrant)
        # Make sure that the registrant is subscribed.
        bmp.source_branch.subscribe(registrant,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        reason = recipients[registrant]
        self.assertEqual("Registrant", reason.mail_header)
        self.assertEqual(
            "You proposed %s for merging." % bmp.source_branch.bzr_identity,
            reason.getReason())

    def test_getNotificationRecipients_Registrant_not_subscribed(self):
        # If the registrant of the proposal is not subscribed, we don't send
        # them any email.
        registrant = self.factory.makePerson()
        bmp = self.factory.makeBranchMergeProposal(registrant=registrant)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        self.assertFalse(registrant in recipients)

    def test_getNotificationRecipients_Owner(self):
        # If the owner of the source branch is subscribed (which is the
        # default), then they get a rationale telling them they are the Owner.
        bmp = self.factory.makeBranchMergeProposal()
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        reason = recipients[bmp.source_branch.owner]
        self.assertEqual("Owner", reason.mail_header)
        self.assertEqual(
            "You are the owner of %s." % bmp.source_branch.bzr_identity,
            reason.getReason())

    def test_getNotificationRecipients_team_owner(self):
        # If the owner of the source branch is subscribed (which is the
        # default), but the owner is a team, then none of the headers will say
        # Owner.
        team = self.factory.makeTeam()
        branch = self.factory.makeProductBranch(owner=team)
        bmp = self.factory.makeBranchMergeProposal(source_branch=branch)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        headers = set([reason.mail_header for reason in recipients.values()])
        self.assertFalse("Owner" in headers)

    def test_getNotificationRecipients_Owner_not_subscribed(self):
        # If the owner of the source branch has unsubscribed themselves, then
        # we don't send them eamil.
        bmp = self.factory.makeBranchMergeProposal()
        owner = bmp.source_branch.owner
        bmp.source_branch.unsubscribe(owner)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS)
        self.assertFalse(owner in recipients)

    def test_getNotificationRecipients_privacy(self):
        # If a user can see only one of the source and target branches, then
        # they do not get email about the proposal.
        bmp = self.factory.makeBranchMergeProposal()
        # Subscribe eric to the source branch only.
        eric = self.factory.makePerson()
        bmp.source_branch.subscribe(
            eric, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        # Subscribe bob to the target branch only.
        bob = self.factory.makePerson()
        bmp.target_branch.subscribe(
            bob, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        # Subscribe charlie to both.
        charlie = self.factory.makePerson()
        bmp.source_branch.subscribe(
            charlie, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        bmp.target_branch.subscribe(
            charlie, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        # Make both branches private.
        removeSecurityProxy(bmp.source_branch).private = True
        removeSecurityProxy(bmp.target_branch).private = True
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL)
        self.assertFalse(bob in recipients)
        self.assertFalse(eric in recipients)
        self.assertTrue(charlie in recipients)


class TestGetAddress(TestCaseWithFactory):
    """Test that the address property gives expected results."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def test_address(self):
        merge_proposal = self.factory.makeBranchMergeProposal()
        expected = 'mp+%d@code.launchpad.dev' % merge_proposal.id
        self.assertEqual(expected, merge_proposal.address)


class TestBranchMergeProposalGetter(TestCaseWithFactory):
    """Test that the BranchMergeProposalGetter behaves as expected."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def test_get(self):
        """Ensure the correct merge proposal is returned."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        self.assertEqual(merge_proposal,
            BranchMergeProposalGetter().get(merge_proposal.id))

    def test_get_as_utility(self):
        """Ensure the correct merge proposal is returned."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        utility = getUtility(IBranchMergeProposalGetter)
        retrieved = utility.get(merge_proposal.id)
        self.assertEqual(merge_proposal, retrieved)

    def test_getVotesForProposals(self):
        # Check the resulting format of the dict.  getVotesForProposals
        # returns a dict mapping merge proposals to a list of votes for that
        # proposal.
        mp_no_reviews = self.factory.makeBranchMergeProposal()
        mp_with_reviews = self.factory.makeBranchMergeProposal()
        reviewer = self.factory.makePerson()
        login_person(mp_with_reviews.registrant)
        vote_reference = mp_with_reviews.nominateReviewer(
            reviewer, mp_with_reviews.registrant)
        self.assertEqual(
            {mp_no_reviews: [],
             mp_with_reviews: [vote_reference]},
            getUtility(IBranchMergeProposalGetter).getVotesForProposals(
                [mp_with_reviews, mp_no_reviews]))

    def test_activeProposalsForBranches_different_branches(self):
        """Only proposals for the correct branches are returned."""
        mp = self.factory.makeBranchMergeProposal()
        mp2 = self.factory.makeBranchMergeProposal()
        active = BranchMergeProposalGetter.activeProposalsForBranches(
            mp.source_branch, mp.target_branch)
        self.assertEqual([mp], list(active))
        active2 = BranchMergeProposalGetter.activeProposalsForBranches(
            mp2.source_branch, mp2.target_branch)
        self.assertEqual([mp2], list(active2))

    def test_activeProposalsForBranches_different_states(self):
        """Only proposals for active states are returned."""
        for state in BranchMergeProposalStatus.items:
            mp = self.factory.makeBranchMergeProposal(set_state=state)
            active = BranchMergeProposalGetter.activeProposalsForBranches(
                mp.source_branch, mp.target_branch)
            # If a proposal is superseded, there is an active proposal which
            # supersedes it.
            if state == BranchMergeProposalStatus.SUPERSEDED:
                self.assertEqual([mp.superseded_by], list(active))
            elif state in FINAL_STATES:
                self.assertEqual([], list(active))
            else:
                self.assertEqual([mp], list(active))

class TestBranchMergeProposalGetterGetProposals(TestCaseWithFactory):
    """Test the getProposalsForContext method."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an administrator so the permission checks for things
        # like adding landing targets and setting privacy on the branches
        # are allowed.
        TestCaseWithFactory.setUp(self, user='foo.bar@canonical.com')

    def _make_merge_proposal(self, owner_name, product_name, branch_name,
                             needs_review=False, registrant=None):
        # A helper method to make the tests readable.
        owner = getUtility(IPersonSet).getByName(owner_name)
        if owner is None:
            owner = self.factory.makePerson(name=owner_name)
        product = getUtility(IProductSet).getByName(product_name)
        if product is None:
            product = self.factory.makeProduct(name=product_name)
        branch = self.factory.makeProductBranch(
            product=product, owner=owner, registrant=registrant,
            name=branch_name)
        if registrant is None:
            registrant = owner
        bmp = branch.addLandingTarget(
            registrant=registrant,
            target_branch=self.factory.makeProductBranch(product=product,
            owner=owner))
        if needs_review:
            bmp.requestReview()
        return bmp

    def _get_merge_proposals(self, context, status=None,
                             visible_by_user=None):
        # Helper method to return tuples of source branch details.
        results = BranchMergeProposalGetter.getProposalsForContext(
            context, status, visible_by_user)
        return sorted([bmp.source_branch.unique_name for bmp in results])

    def test_getProposalsForParticipant(self):
        # It's possible to get all the merge proposals for a single
        # participant.
        wally = self.factory.makePerson(name='wally')
        beaver = self.factory.makePerson(name='beaver')
        name12 = getUtility(IPersonSet).getByName('name12')

        bmp1 = self._make_merge_proposal('wally', 'gokart', 'turbo', True)
        bmp1.nominateReviewer(beaver, wally)
        bmp2 = self._make_merge_proposal('beaver', 'gokart', 'brakes', True)

        getter = BranchMergeProposalGetter
        wally_proposals = getter.getProposalsForParticipant(
            wally, [BranchMergeProposalStatus.NEEDS_REVIEW], wally)
        self.assertEqual(wally_proposals.count(), 1)

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.NEEDS_REVIEW], beaver)
        self.assertEqual(beave_proposals.count(), 2)

        bmp1.rejectBranch(wally, '1')

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.NEEDS_REVIEW], beaver)
        self.assertEqual(beave_proposals.count(), 1)

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.REJECTED], beaver)
        self.assertEqual(beave_proposals.count(), 1)


    def test_created_proposal_default_status(self):
        # When we create a merge proposal using the helper method, the default
        # status of the proposal is work in progress.
        in_progress = self._make_merge_proposal('albert', 'november', 'work')
        self.assertEqual(
            BranchMergeProposalStatus.WORK_IN_PROGRESS,
            in_progress.queue_status)

    def test_created_proposal_review_status(self):
        # If needs_review is set to True, the created merge proposal is set in
        # the needs review state.
        needs_review = self._make_merge_proposal(
            'bob', 'november', 'work', needs_review=True)
        self.assertEqual(
            BranchMergeProposalStatus.NEEDS_REVIEW,
            needs_review.queue_status)

    def test_all_for_product_restrictions(self):
        # Queries on product should limit results to that product.
        self._make_merge_proposal('albert', 'november', 'work')
        self._make_merge_proposal('bob', 'november', 'work')
        # And make a proposal for another product to make sure that it doesn't
        # appear
        self._make_merge_proposal('charles', 'mike', 'work')

        self.assertEqual(
            ['~albert/november/work', '~bob/november/work'],
            self._get_merge_proposals(
                getUtility(IProductSet).getByName('november')))

    def test_wip_for_product_restrictions(self):
        # Check queries on product limited on status.
        in_progress = self._make_merge_proposal('albert', 'november', 'work')
        needs_review = self._make_merge_proposal(
            'bob', 'november', 'work', needs_review=True)
        self.assertEqual(
            ['~albert/november/work'],
            self._get_merge_proposals(
                getUtility(IProductSet).getByName('november'),
                status=[BranchMergeProposalStatus.WORK_IN_PROGRESS]))

    def test_all_for_person_restrictions(self):
        # Queries on person should limit results to that person.
        self._make_merge_proposal('albert', 'november', 'work')
        self._make_merge_proposal('albert', 'mike', 'work')
        # And make a proposal for another product to make sure that it doesn't
        # appear
        self._make_merge_proposal('charles', 'mike', 'work')

        self.assertEqual(
            ['~albert/mike/work', '~albert/november/work'],
            self._get_merge_proposals(
                getUtility(IPersonSet).getByName('albert')))

    def test_wip_for_person_restrictions(self):
        # If looking for the merge proposals for a person, and the status is
        # specified, then the resulting proposals will have one of the states
        # specified.
        self._make_merge_proposal('albert', 'november', 'work')
        self._make_merge_proposal(
            'albert', 'november', 'review', needs_review=True)
        self.assertEqual(
            ['~albert/november/work'],
            self._get_merge_proposals(
                getUtility(IPersonSet).getByName('albert'),
                status=[BranchMergeProposalStatus.WORK_IN_PROGRESS]))

    def test_private_branches(self):
        # The resulting list of merge proposals is filtered by the actual
        # proposals that the logged in user is able to see.
        proposal = self._make_merge_proposal('albert', 'november', 'work')
        # Mark the source branch private.
        removeSecurityProxy(proposal.source_branch).private = True
        self._make_merge_proposal('albert', 'mike', 'work')

        albert = getUtility(IPersonSet).getByName('albert')
        # Albert can see his private branch.
        self.assertEqual(
            ['~albert/mike/work', '~albert/november/work'],
            self._get_merge_proposals(albert, visible_by_user=albert))
        # Anonymous people can't.
        self.assertEqual(
            ['~albert/mike/work'],
            self._get_merge_proposals(albert))
        # Other people can't.
        self.assertEqual(
            ['~albert/mike/work'],
            self._get_merge_proposals(
                albert, visible_by_user=self.factory.makePerson()))
        # A branch subscribers can.
        subscriber = self.factory.makePerson()
        proposal.source_branch.subscribe(
            subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.NOEMAIL)
        self.assertEqual(
            ['~albert/mike/work', '~albert/november/work'],
            self._get_merge_proposals(albert, visible_by_user=subscriber))

    def test_team_private_branches(self):
        # If both charles and albert are a member team xray, and albert
        # creates a branch in the team namespace, charles will be able to see
        # it.
        albert = self.factory.makePerson(name='albert')
        charles = self.factory.makePerson(name='charles')
        xray = self.factory.makeTeam(name='xray', owner=albert)
        xray.addMember(person=charles, reviewer=albert)

        proposal = self._make_merge_proposal(
            'xray', 'november', 'work', registrant=albert)
        # Mark the source branch private.
        removeSecurityProxy(proposal.source_branch).private = True

        november = getUtility(IProductSet).getByName('november')
        # The proposal is visible to charles.
        self.assertEqual(
            ['~xray/november/work'],
            self._get_merge_proposals(november, visible_by_user=charles))
        # Not visible to anonymous people.
        self.assertEqual([], self._get_merge_proposals(november))
        # Not visible to non team members.
        self.assertEqual(
            [],
            self._get_merge_proposals(
                november, visible_by_user=self.factory.makePerson()))


class TestBranchMergeProposalDeletion(TestCaseWithFactory):
    """Deleting a branch merge proposal deletes relevant objects."""

    layer = DatabaseFunctionalLayer

    def test_deleteProposal_deletes_job(self):
        """Deleting a branch merge proposal deletes all related jobs."""
        proposal = self.factory.makeBranchMergeProposal()
        job = MergeProposalCreatedJob.create(proposal)
        job.context.sync()
        job_id = job.context.id
        login_person(proposal.registrant)
        proposal.deleteProposal()
        self.assertRaises(
            SQLObjectNotFound, BranchMergeProposalJob.get, job_id)


class TestBranchMergeProposalBugs(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_related_bugs_includes_source_bugs(self):
        """related_bugs includes bugs linked to the source branch."""
        bmp = self.factory.makeBranchMergeProposal()
        source_branch = bmp.source_branch
        bug = self.factory.makeBug()
        source_branch.linkBug(bug, bmp.registrant)
        self.assertEqual(
            list(source_branch.linked_bugs), list(bmp.related_bugs))

    def test_related_bugs_excludes_target_bugs(self):
        """related_bugs ignores bugs linked to the source branch."""
        bmp = self.factory.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.target_branch.linkBug(bug, bmp.registrant)
        self.assertEqual([], list(bmp.related_bugs))

    def test_related_bugs_excludes_mutual_bugs(self):
        """related_bugs ignores bugs linked to both branches."""
        bmp = self.factory.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.source_branch.linkBug(bug, bmp.registrant)
        bmp.target_branch.linkBug(bug, bmp.registrant)
        self.assertEqual([], list(bmp.related_bugs))


class TestNotifyModified(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_notify_modified_generates_notification(self):
        """notify_modified generates an event.

        notify_modified runs the callable with the specified args and kwargs,
        and generates a ObjectModifiedEvent.
        """
        bmp = self.factory.makeBranchMergeProposal()
        login_person(bmp.target_branch.owner)
        # Approve branch to prevent enqueue from approving it, which would
        # generate an undesired event.
        bmp.approveBranch(bmp.target_branch.owner, revision_id='abc')
        self.assertNotifies(
            ObjectModifiedEvent, notify_modified, bmp, bmp.enqueue,
            bmp.target_branch.owner, revision_id='abc')
        self.assertEqual(BranchMergeProposalStatus.QUEUED, bmp.queue_status)
        self.assertEqual('abc', bmp.queued_revision_id)


class TestBranchMergeProposalJob(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_providesInterface(self):
        """BranchMergeProposalJob implements expected interfaces."""
        bmp = self.factory.makeBranchMergeProposal()
        job = BranchMergeProposalJob(
            bmp, BranchMergeProposalJobType.MERGE_PROPOSAL_CREATED, {})
        job.sync()
        verifyObject(IBranchMergeProposalJob, job)


class TestMergeProposalCreatedJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_providesInterface(self):
        """MergeProposalCreatedJob provides the expected interfaces."""
        bmp = self.factory.makeBranchMergeProposal()
        job = MergeProposalCreatedJob.create(bmp)
        verifyObject(IMergeProposalCreatedJob, job)
        verifyObject(IBranchMergeProposalJob, job)

    def test_run_makes_diff(self):
        """MergeProposalCreationJob.run creates a diff."""
        self.useBzrBranches()
        target, target_tree = self.create_branch_and_tree('target')
        target_tree.bzrdir.root_transport.put_bytes('foo', 'foo\n')
        target_tree.add('foo')
        rev1 = target_tree.commit('added foo')
        source, source_tree = self.create_branch_and_tree('source')
        source_tree.pull(target_tree.branch, stop_revision=rev1)
        source_tree.bzrdir.root_transport.put_bytes('foo', 'foo\nbar\n')
        source_tree.commit('added bar')
        target_tree.merge_from_branch(source_tree.branch)
        target_tree.commit('merged from source')
        source_tree.bzrdir.root_transport.put_bytes('foo', 'foo\nbar\nqux\n')
        source_tree.commit('added qux')
        bmp = BranchMergeProposal(
            source_branch=source, target_branch=target,
            registrant=source.owner)
        job = MergeProposalCreatedJob.create(bmp)
        transaction.commit()
        self.layer.switchDbUser(config.mpcreationjobs.dbuser)
        diff = job.run()
        self.assertIsNot(None, diff)
        self.assertEqual(diff, bmp.review_diff)
        self.assertIsNot(None, bmp.preview_diff)
        transaction.commit()
        self.checkDiff(diff)
        self.checkDiff(bmp.preview_diff)

    def checkDiff(self, diff):
        self.assertNotIn('+bar', diff.diff.text)
        self.assertIn('+qux', diff.diff.text)

    def createProposalWithEmptyBranches(self, review_diff=None):
        target_branch, tree = self.create_branch_and_tree()
        tree.commit('test')
        source_branch = self.factory.makeProductBranch(
            product=target_branch.product)
        self.createBzrBranch(source_branch, tree.branch)
        return self.factory.makeBranchMergeProposal(
            source_branch=source_branch, target_branch=target_branch,
            review_diff=review_diff)

    def test_run_skips_diff_if_present(self):
        """The review diff is only generated if not already assigned."""
        # We want to make sure that we don't try to do anything with the
        # bzr branch if there's already a diff.  So here, we create a
        # database branch that has no bzr branch.
        self.useBzrBranches()
        bmp = self.createProposalWithEmptyBranches()
        job = MergeProposalCreatedJob.create(bmp)
        diff_bytes = ''.join(unified_diff('', 'foo'))
        review_diff = StaticDiff.acquireFromText('rev1', 'rev2', diff_bytes)
        transaction.commit()
        removeSecurityProxy(bmp).review_diff = review_diff
        job.run()
        self.assertEqual(review_diff, bmp.review_diff)

    def test_run_sends_email(self):
        """MergeProposalCreationJob.run sends an email."""
        self.useBzrBranches()
        diff_bytes = ''.join(unified_diff('', 'foo'))
        review_diff = StaticDiff.acquireFromText('rev1', 'rev2', diff_bytes)
        transaction.commit()
        bmp = self.createProposalWithEmptyBranches(review_diff)
        job = MergeProposalCreatedJob.create(bmp)
        self.assertEqual([], pop_notifications())
        job.run()
        self.assertEqual(2, len(pop_notifications()))

    def test_iterReady_includes_ready_jobs(self):
        """Ready jobs should be listed."""
        # Suppress events to avoid creating a MergeProposalCreatedJob early.
        bmp = capture_events(self.factory.makeBranchMergeProposal)[0]
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        job = MergeProposalCreatedJob.create(bmp)
        job.job.sync()
        job.context.sync()
        self.assertEqual([job], list(MergeProposalCreatedJob.iterReady()))

    def test_iterReady_excludes_unready_jobs(self):
        """Unready jobs should not be listed."""
        # Suppress events to avoid creating a MergeProposalCreatedJob early.
        bmp = capture_events(self.factory.makeBranchMergeProposal)[0]
        job = MergeProposalCreatedJob.create(bmp)
        job.job.start()
        job.job.complete()
        self.assertEqual([], list(MergeProposalCreatedJob.iterReady()))

    def test_iterReady_excludes_hosted_needing_mirror(self):
        """Skip Jobs with a hosted source branch that needs mirroring."""
        # Suppress events to avoid creating a MergeProposalCreatedJob early.
        bmp = capture_events(self.factory.makeBranchMergeProposal)[0]
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        bmp.source_branch.requestMirror()
        job = MergeProposalCreatedJob.create(bmp)
        self.assertEqual([], list(MergeProposalCreatedJob.iterReady()))

    def test_iterReady_joins_properly(self):
        """An up-to-date branch does not cause a job for a needs-mirroring
        branch to be returned."""
        # Suppress events to avoid creating MergeProposalCreatedJobs early.
        bmp = capture_events(self.factory.makeBranchMergeProposal)[0]
        bmp2 = capture_events(self.factory.makeBranchMergeProposal)[0]
        # Give both branches some revisions.
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        self.factory.makeRevisionsForBranch(bmp2.source_branch, count=1)
        # Request a mirror and create a job for one of them.
        bmp.source_branch.requestMirror()
        MergeProposalCreatedJob.create(bmp)
        # No jobs are ready.
        self.assertEqual([], list(MergeProposalCreatedJob.iterReady()))

    def test_iterReady_includes_mirrored_needing_mirror(self):
        """Skip Jobs with a hosted source branch that needs mirroring."""
        source_branch = self.factory.makeProductBranch(
            branch_type=BranchType.MIRRORED)
        self.factory.makeRevisionsForBranch(source_branch, count=1)
        # Suppress events to avoid creating a MergeProposalCreatedJob early.
        bmp = capture_events(
            self.factory.makeBranchMergeProposal,
            source_branch=source_branch)[0]
        bmp.source_branch.requestMirror()
        job = MergeProposalCreatedJob.create(bmp)
        self.assertEqual([job], list(MergeProposalCreatedJob.iterReady()))

    def test_iterReady_excludes_branches_with_no_revisions(self):
        """Skip Jobs with a source branch that has no revisions."""
        # Suppress events to avoid creating a MergeProposalCreatedJob early.
        bmp = capture_events(self.factory.makeBranchMergeProposal)[0]
        bmp.source_branch.requestMirror()
        self.assertEqual(0, bmp.source_branch.revision_count)
        job = MergeProposalCreatedJob.create(bmp)
        self.assertEqual([], list(MergeProposalCreatedJob.iterReady()))

    def test_getOopsMailController(self):
        """The registrant is notified about merge proposal creation issues."""
        bmp = self.factory.makeBranchMergeProposal()
        bmp.source_branch.requestMirror()
        job = MergeProposalCreatedJob.create(bmp)
        ctrl = job.getOopsMailController('1234')
        self.assertEqual([bmp.registrant.preferredemail.email], ctrl.to_addrs)
        message = (
            'notifying people about the proposal to merge %s into %s' %
            (bmp.source_branch.bzr_identity, bmp.target_branch.bzr_identity))
        self.assertIn(message, ctrl.body)

    def test_MergeProposalCreateJob_with_sourcepackage_branch(self):
        """Jobs for merge proposals with sourcepackage branches work."""
        self.useBzrBranches()
        bmp = self.factory.makeBranchMergeProposal(
            target_branch=self.factory.makePackageBranch())
        tree = self.create_branch_and_tree(db_branch=bmp.target_branch)[1]
        tree.commit('Initial commit')
        self.createBzrBranch(bmp.source_branch, tree.branch)
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        job = MergeProposalCreatedJob.create(bmp)
        transaction.commit()
        self.layer.switchDbUser(config.mpcreationjobs.dbuser)
        job.run()


class TestBranchMergeProposalNominateReviewer(TestCaseWithFactory):
    """Test that the appropriate vote references get created."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def test_notify_on_nominate(self):
        # Ensure that a notification is emitted on nomination.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.source_branch.owner)
        reviewer = self.factory.makePerson()
        result, event = self.assertNotifies(
            ReviewerNominatedEvent,
            merge_proposal.nominateReviewer,
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner)
        self.assertEqual(result, event.object)

    def test_notify_on_nominate_suppressed_if_requested(self):
        # Ensure that a notification is suppressed if notify listeners is set
        # to False.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.source_branch.owner)
        reviewer = self.factory.makePerson()
        self.assertNoNotification(
            merge_proposal.nominateReviewer,
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner,
            _notify_listeners=False)

    def test_no_initial_votes(self):
        """A new merge proposal has no votes."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        self.assertEqual([], list(merge_proposal.votes))

    def test_nominate_creates_reference(self):
        """A new vote reference is created when a reviewer is nominated."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.source_branch.owner)
        reviewer = self.factory.makePerson()
        merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner,
            review_type='General')
        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(merge_proposal.source_branch.owner,
                         vote_reference.registrant)
        self.assertEqual('general', vote_reference.review_type)

    def test_nominate_multiple_with_different_types(self):
        # While an individual can only be requested to do one review
        # (test_nominate_updates_reference) a team can have multiple
        # nominations for different review types.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.source_branch.owner)
        reviewer = self.factory.makePerson()
        review_team = self.factory.makeTeam(owner=reviewer)
        merge_proposal.nominateReviewer(
            reviewer=review_team,
            registrant=merge_proposal.source_branch.owner,
            review_type='general-1')
        # Second nomination of the same type fails.
        merge_proposal.nominateReviewer(
            reviewer=review_team,
            registrant=merge_proposal.source_branch.owner,
            review_type='general-2')

        votes = list(merge_proposal.votes)
        self.assertEqual(
            ['general-1', 'general-2'],
            sorted([review.review_type for review in votes]))

    def test_nominate_updates_reference(self):
        """The existing reference is updated on re-nomination."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.source_branch.owner)
        reviewer = self.factory.makePerson()
        reference = merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner,
            review_type='General')
        self.assertEqual('general', reference.review_type)
        merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner,
            review_type='Specific')
        # Note we're using the reference from the first call
        self.assertEqual('specific', reference.review_type)

    def test_comment_with_vote_creates_reference(self):
        """A comment with a vote creates a vote reference."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        reviewer = self.factory.makePerson()
        comment = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.APPROVE)
        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(reviewer, vote_reference.registrant)
        self.assertTrue(vote_reference.review_type is None)
        self.assertEqual(comment, vote_reference.comment)

    def test_comment_without_a_vote_does_not_create_reference(self):
        """A comment with a vote creates a vote reference."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        reviewer = self.factory.makePerson()
        comment = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content')
        self.assertEqual([], list(merge_proposal.votes))

    def test_second_vote_by_person_just_alters_reference(self):
        """A second vote changes the comment reference only."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        reviewer = self.factory.makePerson()
        comment1 = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.DISAPPROVE)
        comment2 = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.APPROVE)
        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(reviewer, vote_reference.registrant)
        self.assertTrue(vote_reference.review_type is None)
        self.assertEqual(comment2, vote_reference.comment)

    def test_vote_by_nominated_reuses_reference(self):
        """A comment with a vote for a nominated reviewer alters reference."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        login(merge_proposal.source_branch.owner.preferredemail.email)
        reviewer = self.factory.makePerson()
        merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.source_branch.owner,
            review_type='general')
        comment = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.APPROVE, review_type='general')

        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(merge_proposal.source_branch.owner,
                         vote_reference.registrant)
        self.assertEqual('general', vote_reference.review_type)
        self.assertEqual(comment, vote_reference.comment)

    def test_claiming_team_review(self):
        # A person in a team claims a team review of the same type.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login(merge_proposal.source_branch.owner.preferredemail.email)
        reviewer = self.factory.makePerson()
        team = self.factory.makeTeam(owner=reviewer)
        merge_proposal.nominateReviewer(
            reviewer=team,
            registrant=merge_proposal.source_branch.owner,
            review_type='general')
        [vote] = list(merge_proposal.votes)
        self.assertEqual(team, vote.reviewer)
        comment = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.APPROVE, review_type='general')
        self.assertEqual(reviewer, vote.reviewer)
        self.assertEqual('general', vote.review_type)
        self.assertEqual(comment, vote.comment)

    def test_claiming_tagless_team_review_with_tag(self):
        # A person in a team claims a team review of the same type, or if
        # there isn't a team review with that specified type, but there is a
        # team review that doesn't have a review type set, then claim that
        # one.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login(merge_proposal.source_branch.owner.preferredemail.email)
        reviewer = self.factory.makePerson()
        team = self.factory.makeTeam(owner=reviewer)
        merge_proposal.nominateReviewer(
            reviewer=team,
            registrant=merge_proposal.source_branch.owner,
            review_type=None)
        [vote] = list(merge_proposal.votes)
        self.assertEqual(team, vote.reviewer)
        comment = merge_proposal.createComment(
            reviewer, 'Message subject', 'Message content',
            vote=CodeReviewVote.APPROVE, review_type='general')
        self.assertEqual(reviewer, vote.reviewer)
        self.assertEqual('general', vote.review_type)
        self.assertEqual(comment, vote.comment)
        # Still only one vote.
        self.assertEqual(1, len(list(merge_proposal.votes)))

class TestBranchMergeProposalResubmit(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_resubmit(self):
        """Ensure that resubmit performs its basic function.

        It should create a new merge proposal, mark the old one as superseded,
        and set its status to superseded.
        """
        bmp1 = self.factory.makeBranchMergeProposal()
        login_person(bmp1.registrant)
        bmp2 = bmp1.resubmit(bmp1.registrant)
        self.assertNotEqual(bmp1.id, bmp2.id)
        self.assertEqual(
            bmp1.queue_status, BranchMergeProposalStatus.SUPERSEDED)
        self.assertEqual(
            bmp2.queue_status, BranchMergeProposalStatus.NEEDS_REVIEW)
        self.assertEqual(
            bmp2, bmp1.superseded_by)

    def test_resubmit_re_requests_review(self):
        """Resubmit should request new reviews.

        Both those who have already reviewed and those who have been nominated
        to review should be requested to review the new proposal.
        """
        bmp1 = self.factory.makeBranchMergeProposal()
        nominee = self.factory.makePerson()
        login_person(bmp1.registrant)
        bmp1.nominateReviewer(nominee, bmp1.registrant, 'nominee')
        reviewer = self.factory.makePerson()
        bmp1.createComment(
            reviewer, 'I like', vote=CodeReviewVote.APPROVE,
            review_type='specious')
        bmp2 = bmp1.resubmit(bmp1.registrant)
        self.assertEqual(
            set([(nominee, 'nominee'), (reviewer, 'specious')]),
            set((vote.reviewer, vote.review_type) for vote in bmp2.votes))


class TestCreateMergeProposalJob(TestCaseWithFactory):
    """Tests for CreateMergeProposalJob."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def test_providesInterface(self):
        """The class and instances correctly implement their interfaces."""
        verifyObject(ICreateMergeProposalJobSource, CreateMergeProposalJob)
        file_alias = self.factory.makeMergeDirectiveEmail()[1]
        job = CreateMergeProposalJob.create(file_alias)
        job.context.sync()
        verifyObject(IMessageJob, job)
        verifyObject(ICreateMergeProposalJob, job)

    def test_run_creates_proposal(self):
        """CreateMergeProposalJob.run should create a merge proposal."""
        key = import_secret_test_key()
        signing_context = GPGSigningContext(key.fingerprint, password='test')
        message, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail(
                signing_context=signing_context))
        job = CreateMergeProposalJob.create(file_alias)
        transaction.commit()
        proposal, comment = job.run()
        self.assertEqual(proposal.source_branch, source)
        self.assertEqual(proposal.target_branch, target)

    def test_getOopsMailController(self):
        """The sender is notified when creating a bmp from email fails."""
        key = import_secret_test_key()
        signing_context = GPGSigningContext(key.fingerprint, password='test')
        message, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail(
                signing_context=signing_context))
        job = CreateMergeProposalJob.create(file_alias)
        transaction.commit()
        ctrl = job.getOopsMailController('1234')
        self.assertEqual([message['From']], ctrl.to_addrs)
        desc = ('creating a merge proposal from message with subject %s' %
                message['Subject'])
        self.assertIn(desc, ctrl.body)

    def test_iterReady_includes_ready_jobs(self):
        """Ready jobs should be listed."""
        file_alias = self.factory.makeMergeDirectiveEmail()[1]
        job = CreateMergeProposalJob.create(file_alias)
        self.assertEqual([job], list(CreateMergeProposalJob.iterReady()))

    def test_iterReady_excludes_unready_jobs(self):
        """Unready jobs should not be listed."""
        file_alias = self.factory.makeMergeDirectiveEmail()[1]
        job = CreateMergeProposalJob.create(file_alias)
        job.job.start()
        job.job.complete()
        self.assertEqual([], list(CreateMergeProposalJob.iterReady()))


class TestUpdatePreviewDiff(TestCaseWithFactory):
    """Test the updateMergeDiff method of BranchMergeProposal."""

    layer = LaunchpadFunctionalLayer

    def _updatePreviewDiff(self, merge_proposal):
        # Update the preview diff for the merge proposal.
        diff_text = (
            "=== modified file 'sample.py'\n"
            "--- sample\t2009-01-15 23:44:22 +0000\n"
            "+++ sample\t2009-01-29 04:10:57 +0000\n"
            "@@ -19,7 +19,7 @@\n"
            " from zope.interface import implements\n"
            "\n"
            " from storm.expr import Desc, Join, LeftJoin\n"
            "-from storm.references import Reference\n"
            "+from storm.locals import Int, Reference\n"
            " from sqlobject import ForeignKey, IntCol\n"
            "\n"
            " from canonical.config import config\n")
        diff_stat = {'sample': (1, 1)}
        login_person(merge_proposal.registrant)
        merge_proposal.updatePreviewDiff(
            diff_text, u"source_id", u"target_id")
        # Have to commit the transaction to make the Librarian file
        # available.
        transaction.commit()
        return diff_text, diff_stat

    def test_new_diff(self):
        # Test that both the PreviewDiff and the Diff get created.
        merge_proposal = self.factory.makeBranchMergeProposal()
        diff_text, diff_stat = self._updatePreviewDiff(merge_proposal)
        self.assertEqual(diff_text, merge_proposal.preview_diff.text)
        self.assertEqual(diff_stat, merge_proposal.preview_diff.diffstat)

    def test_update_diff(self):
        # Test that both the PreviewDiff and the Diff get updated.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.registrant)
        diff_bytes = ''.join(unified_diff('', 'random text'))
        merge_proposal.updatePreviewDiff(diff_bytes, u"a", u"b")
        transaction.commit()
        # Extract the primary key ids for the preview diff and the diff to
        # show that we are not reusing the objects.
        preview_diff_id = removeSecurityProxy(
            merge_proposal.preview_diff).id
        diff_id = removeSecurityProxy(
            merge_proposal.preview_diff).diff_id
        diff_text, diff_stat = self._updatePreviewDiff(merge_proposal)
        self.assertEqual(diff_text, merge_proposal.preview_diff.text)
        self.assertEqual(diff_stat, merge_proposal.preview_diff.diffstat)
        self.assertNotEqual(
            preview_diff_id,
            removeSecurityProxy(merge_proposal.preview_diff).id)
        self.assertNotEqual(
            diff_id,
            removeSecurityProxy(merge_proposal.preview_diff).diff_id)


class TestUpdatePreviewDiffJob(DiffTestCase):

    layer = LaunchpadZopelessLayer

    def test_run(self):
        self.useBzrBranches()
        bmp = self.createExampleMerge()[0]
        job = UpdatePreviewDiffJob.create(bmp)
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        bmp.source_branch.next_mirror_time = None
        transaction.commit()
        self.layer.switchDbUser(config.update_preview_diffs.dbuser)
        JobRunner.fromReady(UpdatePreviewDiffJob).runAll()
        transaction.commit()
        self.checkExampleMerge(bmp.preview_diff.text)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
