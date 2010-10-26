# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=F0401

"""Unit tests for BranchMergeProposals."""

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
from difflib import unified_diff
import unittest

import pytz
import transaction
from zope.component import getMultiAdapter
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.database.message import MessageSet
from canonical.launchpad.webapp.interfaces import IPrimaryContext
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.code.browser.branch import RegisterBranchMergeProposalView
from lp.code.browser.branchmergeproposal import (
    BranchMergeProposalAddVoteView,
    BranchMergeProposalChangeStatusView,
    BranchMergeProposalContextMenu,
    BranchMergeProposalMergedView,
    BranchMergeProposalVoteView,
    DecoratedCodeReviewVoteReference,
    ICodeReviewNewRevisions,
    latest_proposals_for_each_branch,
    )
from lp.code.browser.codereviewcomment import CodeReviewDisplayComment
from lp.code.enums import (
    BranchMergeProposalStatus,
    CodeReviewVote,
    )
from lp.code.model.diff import (
    PreviewDiff,
    StaticDiff,
    )
from lp.code.tests.helpers import add_revision_to_branch
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    time_counter,
    )
from lp.testing.views import create_initialized_view


class TestBranchMergeProposalPrimaryContext(TestCaseWithFactory):
    """Tests the adaptation of a merge proposal into a primary context."""

    layer = DatabaseFunctionalLayer

    def testPrimaryContext(self):
        # The primary context of a merge proposal is the same as the primary
        # context of the source_branch.
        bmp = self.factory.makeBranchMergeProposal()
        self.assertEqual(
            IPrimaryContext(bmp).context,
            IPrimaryContext(bmp.source_branch).context)


class TestBranchMergeProposalContextMenu(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_add_comment_enabled_when_not_mergeable(self):
        """It should be possible to comment on an unmergeable proposal."""
        bmp = self.factory.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.REJECTED)
        login_person(bmp.registrant)
        menu = BranchMergeProposalContextMenu(bmp)
        self.assertTrue(menu.add_comment().enabled)


class TestDecoratedCodeReviewVoteReference(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_commentEnabled(self):
        """It should be possible to review an unmergeable proposal."""
        request = self.factory.makeCodeReviewVoteReference()
        bmp = request.branch_merge_proposal
        bmp.rejectBranch(bmp.target_branch.owner, 'foo')
        d = DecoratedCodeReviewVoteReference(request, request.reviewer, None)
        self.assertTrue(d.user_can_review)
        self.assertTrue(d.can_change_review)


class TestBranchMergeProposalMergedView(TestCaseWithFactory):
    """Tests for `BranchMergeProposalMergedView`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin so we don't have to worry about launchpad.Edit
        # permissions on the merge proposals for adding comments, or
        # nominating reviewers.
        TestCaseWithFactory.setUp(self, user="admin@canonical.com")
        self.bmp = self.factory.makeBranchMergeProposal()

    def test_initial_values(self):
        # The default merged_revno is the head revno of the target branch.
        view = BranchMergeProposalMergedView(self.bmp, LaunchpadTestRequest())
        self.bmp.source_branch.revision_count = 1
        self.bmp.target_branch.revision_count = 2
        self.assertEqual(
            {'merged_revno': self.bmp.target_branch.revision_count},
            view.initial_values)


class TestBranchMergeProposalAddVoteView(TestCaseWithFactory):
    """Test the AddVote view."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.bmp = self.factory.makeBranchMergeProposal()

    def _createView(self):
        # Construct the view and initialize it.
        view = BranchMergeProposalAddVoteView(
            self.bmp, LaunchpadTestRequest())
        view.initialize()
        return view

    def test_init_with_random_person(self):
        """Any random person ought to be able to vote."""
        login_person(self.factory.makePerson())
        self._createView()

    def test_init_with_anonymous(self):
        """Anonymous people cannot vote."""
        self.assertRaises(AssertionError, self._createView)


class TestBranchMergeProposalVoteView(TestCaseWithFactory):
    """Make sure that the votes are returned in the right order."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin so we don't have to worry about launchpad.Edit
        # permissions on the merge proposals for adding comments, or
        # nominating reviewers.
        TestCaseWithFactory.setUp(self, user="admin@canonical.com")
        self.bmp = self.factory.makeBranchMergeProposal()
        self.date_generator = time_counter(delta=timedelta(days=1))

    def _createComment(self, reviewer, vote):
        """Create a comment on the merge proposal."""
        self.bmp.createComment(
            owner=reviewer,
            subject=self.factory.getUniqueString('subject'),
            vote=vote,
            _date_created=self.date_generator.next())

    def _nominateReviewer(self, reviewer, registrant):
        """Nominate a reviewer for the merge proposal."""
        self.bmp.nominateReviewer(
            reviewer=reviewer, registrant=registrant,
            _date_created=self.date_generator.next())

    def testNoVotes(self):
        # No votes should return empty lists
        login_person(self.factory.makePerson())
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertEqual([], view.current_reviews)
        self.assertEqual([], view.requested_reviews)
        # The vote table should not be shown, because there are no votes, and
        # the logged-in user cannot request reviews.
        self.assertFalse(view.show_table)

    def testRequestedOrdering(self):
        # No votes should return empty lists
        # Request three reviews.
        albert = self.factory.makePerson(name='albert')
        bob = self.factory.makePerson(name='bob')
        charles = self.factory.makePerson(name='charles')

        owner = self.bmp.source_branch.owner

        self._nominateReviewer(albert, owner)
        self._nominateReviewer(bob, owner)
        self._nominateReviewer(charles, owner)

        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertEqual([], view.current_reviews)
        requested_reviews = view.requested_reviews
        self.assertEqual(3, len(requested_reviews))
        self.assertEqual(
            [charles, bob, albert],
            [review.reviewer for review in requested_reviews])

    def test_user_can_claim_self(self):
        """Someone cannot claim a review already assigned to them."""
        albert = self.factory.makePerson()
        owner = self.bmp.source_branch.owner
        self._nominateReviewer(albert, owner)
        login_person(albert)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertFalse(view.requested_reviews[0].user_can_claim)

    def test_user_can_claim_member(self):
        """Someone can claim a review already assigned to their team."""
        albert = self.factory.makePerson()
        review_team = self.factory.makeTeam()
        albert.join(review_team)
        owner = self.bmp.source_branch.owner
        self._nominateReviewer(review_team, owner)
        login_person(albert)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertTrue(view.requested_reviews[0].user_can_claim)

    def test_user_can_claim_nonmember(self):
        """A non-member cannot claim a team's review."""
        albert = self.factory.makePerson()
        review_team = self.factory.makeTeam()
        owner = self.bmp.source_branch.owner
        self._nominateReviewer(review_team, owner)
        login_person(albert)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertFalse(view.requested_reviews[0].user_can_claim)

    def makeReviewRequest(self, viewer=None, registrant=None):
        albert = self.factory.makePerson()
        if registrant is None:
            registrant = self.bmp.source_branch.owner
        self._nominateReviewer(albert, registrant)
        if viewer is None:
            viewer = albert
        login_person(viewer)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        return view.requested_reviews[0]

    def test_user_can_reassign_assignee(self):
        """The user can reassign if they are the assignee."""
        review_request = self.makeReviewRequest()
        self.assertTrue(review_request.user_can_reassign)

    def test_user_can_reassign_registrant(self):
        """The user can reassign if they are the registrant."""
        registrant = self.factory.makePerson()
        review_request = self.makeReviewRequest(registrant, registrant)
        self.assertTrue(review_request.user_can_reassign)

    def test_user_cannot_reassign_random_person(self):
        """Random people cannot reassign reviews."""
        viewer = self.factory.makePerson()
        review_request = self.makeReviewRequest(viewer)
        self.assertFalse(review_request.user_can_reassign)

    def testCurrentReviewOrdering(self):
        # Most recent first.
        # Request three reviews.
        albert = self.factory.makePerson(name='albert')
        bob = self.factory.makePerson(name='bob')
        charles = self.factory.makePerson(name='charles')
        self._createComment(albert, CodeReviewVote.APPROVE)
        self._createComment(bob, CodeReviewVote.ABSTAIN)
        self._createComment(charles, CodeReviewVote.DISAPPROVE)

        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())

        self.assertEqual(
            [charles, bob, albert],
            [review.reviewer for review in view.current_reviews])

    def testChangeOfVoteBringsToTop(self):
        # Changing the vote changes the vote date, so it comes to the top.
        # Request three reviews.
        albert = self.factory.makePerson(name='albert')
        bob = self.factory.makePerson(name='bob')
        self._createComment(albert, CodeReviewVote.ABSTAIN)
        self._createComment(bob, CodeReviewVote.APPROVE)
        self._createComment(albert, CodeReviewVote.APPROVE)

        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())

        self.assertEqual(
            [albert, bob],
            [review.reviewer for review in view.current_reviews])

    def addReviewTeam(self):
        review_team = self.factory.makeTeam(name='reviewteam')
        self.bmp.target_branch.reviewer = review_team

    def test_review_team_members_trusted(self):
        """Members of the target branch's review team are trusted."""
        self.addReviewTeam()
        albert = self.factory.makePerson(name='albert')
        albert.join(self.bmp.target_branch.reviewer)
        self._createComment(albert, CodeReviewVote.APPROVE)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertTrue(view.reviews[0].trusted)

    def test_review_team_nonmembers_untrusted(self):
        """Non-members of the target branch's review team are untrusted."""
        self.addReviewTeam()
        albert = self.factory.makePerson(name='albert')
        self._createComment(albert, CodeReviewVote.APPROVE)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertFalse(view.reviews[0].trusted)

    def test_no_review_team_untrusted(self):
        """If the target branch has no review team, everyone is untrusted."""
        albert = self.factory.makePerson(name='albert')
        self._createComment(albert, CodeReviewVote.APPROVE)
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertFalse(view.reviews[0].trusted)

    def test_render_all_vote_types(self):
        # A smoke test that the view knows how to render all types of vote.
        for vote in CodeReviewVote.items:
            self._createComment(
                self.factory.makePerson(), vote)

        view = getMultiAdapter(
            (self.bmp, LaunchpadTestRequest()), name='+votes')
        self.failUnless(
            isinstance(view, BranchMergeProposalVoteView),
            "The +votes page for a BranchMergeProposal is expected to be a "
            "BranchMergeProposalVoteView")
        # We just test that rendering does not raise.
        view.render()


class TestRegisterBranchMergeProposalView(TestCaseWithFactory):
    """Test the merge proposal registration view."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.target_branch = self.factory.makeProductBranch()
        self.source_branch = self.factory.makeProductBranch(
            product=self.target_branch.product)
        self.user = self.factory.makePerson()
        login_person(self.user)

    def _createView(self):
        # Construct the view and initialize it.
        view = RegisterBranchMergeProposalView(
            self.source_branch, LaunchpadTestRequest())
        view.initialize()
        return view

    def _getSourceProposal(self):
        # There will only be one proposal.
        landing_targets = list(self.source_branch.landing_targets)
        self.assertEqual(1, len(landing_targets))
        proposal = landing_targets[0]
        self.assertEqual(self.target_branch, proposal.target_branch)
        return proposal

    def assertNoPendingReviews(self, proposal):
        # There should be no votes recorded for the proposal.
        self.assertEqual([], list(proposal.votes))

    def assertOnePendingReview(self, proposal, reviewer, review_type=None):
        # There should be one pending vote for the reviewer with the specified
        # review type.
        votes = list(proposal.votes)
        self.assertEqual(1, len(votes))
        self.assertEqual(reviewer, votes[0].reviewer)
        self.assertEqual(self.user, votes[0].registrant)
        self.assertIs(None, votes[0].comment)
        if review_type is None:
            self.assertIs(None, votes[0].review_type)
        else:
            self.assertEqual(review_type, votes[0].review_type)

    def test_register_simplest_case(self):
        # This simplest case is where the user only specifies the target
        # branch, and not an initial comment or reviewer.
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'needs_review': True})
        proposal = self._getSourceProposal()
        self.assertNoPendingReviews(proposal)
        self.assertIs(None, proposal.description)

    def test_register_work_in_progress(self):
        # The needs review checkbox can be unchecked to create a work in
        # progress proposal.
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'needs_review': False})
        proposal = self._getSourceProposal()
        self.assertEqual(
            BranchMergeProposalStatus.WORK_IN_PROGRESS,
            proposal.queue_status)

    def test_register_with_commit_message(self):
        # A commit message can also be set during the register process.
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'needs_review': True,
             'commit_message': 'Fixed the bug!'})
        proposal = self._getSourceProposal()
        self.assertEqual('Fixed the bug!', proposal.commit_message)

    def test_register_initial_comment(self):
        # If the user specifies a description, this is recorded on the
        # proposal.
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'comment': "This is the description.",
             'needs_review': True})

        proposal = self._getSourceProposal()
        self.assertNoPendingReviews(proposal)
        self.assertEqual(proposal.description, "This is the description.")

    def test_register_request_reviewer(self):
        # If the user requests a reviewer, then a pending vote is added to the
        # proposal.
        reviewer = self.factory.makePerson()
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'reviewer': reviewer,
             'needs_review': True})

        proposal = self._getSourceProposal()
        self.assertOnePendingReview(proposal, reviewer)
        self.assertIs(None, proposal.description)

    def test_register_request_review_type(self):
        # We can request a specific review type of the reviewer.  If we do, it
        # is recorded along with the pending review.
        reviewer = self.factory.makePerson()
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'reviewer': reviewer,
             'review_type': 'god-like',
             'needs_review': True})

        proposal = self._getSourceProposal()
        self.assertOnePendingReview(proposal, reviewer, 'god-like')
        self.assertIs(None, proposal.description)

    def test_register_comment_and_review(self):
        # The user can give a description and request a review from
        # someone.
        reviewer = self.factory.makePerson()
        view = self._createView()
        view.register_action.success(
            {'target_branch': self.target_branch,
             'reviewer': reviewer,
             'review_type': 'god-like',
             'comment': "This is the description.",
             'needs_review': True})

        proposal = self._getSourceProposal()
        self.assertOnePendingReview(proposal, reviewer, 'god-like')
        self.assertEqual(proposal.description, "This is the description.")


class TestBranchMergeProposalView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()
        self.bmp = self.factory.makeBranchMergeProposal(registrant=self.user)
        login_person(self.user)

    def makeTeamReview(self):
        owner = self.bmp.source_branch.owner
        review_team = self.factory.makeTeam()
        return self.bmp.nominateReviewer(review_team, owner)

    def test_claim_action_team_member(self):
        """Claiming a review works for members of the requested team."""
        review = self.makeTeamReview()
        albert = self.factory.makePerson()
        removeSecurityProxy(albert).join(review.reviewer)
        login_person(albert)
        view = create_initialized_view(self.bmp, '+index')
        view.claim_action.success({'review_id': review.id})
        self.assertEqual(albert, review.reviewer)

    def test_claim_action_non_member(self):
        """Claiming a review does not work for non-members."""
        review = self.makeTeamReview()
        albert = self.factory.makePerson()
        login_person(albert)
        view = create_initialized_view(self.bmp, '+index')
        self.assertRaises(Unauthorized, view.claim_action.success,
                          {'review_id': review.id})

    def test_preview_diff_text_with_no_diff(self):
        """preview_diff_text should be None if context has no preview_diff."""
        view = create_initialized_view(self.bmp, '+index')
        self.assertIs(None, view.preview_diff_text)

    def test_preview_diff_utf8(self):
        """A preview_diff in utf-8 should decoded as utf-8."""
        text = ''.join(unichr(x) for x in range(255))
        diff_bytes = ''.join(unified_diff('', text)).encode('utf-8')
        self.setPreviewDiff(diff_bytes)
        transaction.commit()
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(diff_bytes.decode('utf-8'),
                         view.preview_diff_text)

    def test_preview_diff_all_chars(self):
        """preview_diff should work on diffs containing all possible bytes."""
        text = ''.join(chr(x) for x in range(255))
        diff_bytes = ''.join(unified_diff('', text))
        self.setPreviewDiff(diff_bytes)
        transaction.commit()
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(diff_bytes.decode('windows-1252', 'replace'),
                         view.preview_diff_text)

    def addReviewDiff(self):
        review_diff_bytes = ''.join(unified_diff('', 'review'))
        review_diff = StaticDiff.acquireFromText('x', 'y', review_diff_bytes)
        self.bmp.review_diff = review_diff
        return review_diff

    def addBothDiffs(self):
        self.addReviewDiff()
        preview_diff_bytes = ''.join(unified_diff('', 'preview'))
        return self.setPreviewDiff(preview_diff_bytes)

    def setPreviewDiff(self, preview_diff_bytes):
        preview_diff = PreviewDiff.create(
            preview_diff_bytes, u'a', u'b', None, u'')
        removeSecurityProxy(self.bmp).preview_diff = preview_diff
        return preview_diff

    def test_preview_diff_prefers_preview_diff(self):
        """The preview will be used for BMP with both a review and preview."""
        preview_diff = self.addBothDiffs()
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(preview_diff, view.preview_diff)

    def test_preview_diff_uses_review_diff(self):
        """The review diff will be used if there is no preview."""
        review_diff = self.addReviewDiff()
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(review_diff.diff,
                         view.preview_diff)

    def test_review_diff_text_prefers_preview_diff(self):
        """The preview will be used for BMP with both a review and preview."""
        preview_diff = self.addBothDiffs()
        transaction.commit()
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(
            preview_diff.text, view.preview_diff_text)

    def test_linked_bugs_excludes_mutual_bugs(self):
        """List bugs that are linked to the source only."""
        bug = self.factory.makeBug()
        self.bmp.source_branch.linkBug(bug, self.bmp.registrant)
        self.bmp.target_branch.linkBug(bug, self.bmp.registrant)
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual([], view.linked_bugs)

    def test_CodeReviewNewRevisions_implements_ICodeReviewNewRevisions(self):
        # The browser helper class implements its interface.
        review_date = datetime(2009, 9, 10, tzinfo=pytz.UTC)
        revision_date = review_date + timedelta(days=1)
        bmp = self.factory.makeBranchMergeProposal(
            date_created=review_date)
        revision = add_revision_to_branch(
            self.factory, bmp.source_branch, revision_date)

        view = create_initialized_view(bmp, '+index')
        new_revisions = view.conversation.comments[0]

        self.assertTrue(verifyObject(ICodeReviewNewRevisions, new_revisions))

    def test_include_superseded_comments(self):
        for x, time in zip(range(3), time_counter()):
            if x != 0:
                self.bmp = self.bmp.resubmit(self.user)
            self.bmp.createComment(
                self.user, 'comment %d' % x, _date_created=time)
        view = create_initialized_view(self.bmp, '+index')
        self.assertEqual(
            ['comment 0', 'comment 1', 'comment 2'],
            [comment.comment.message.subject for comment
             in view.conversation.comments])
        self.assertFalse(view.conversation.comments[2].from_superseded)
        self.assertTrue(view.conversation.comments[1].from_superseded)
        self.assertTrue(view.conversation.comments[0].from_superseded)


class TestBranchMergeProposalChangeStatusOptions(TestCaseWithFactory):
    """Test the status vocabulary generated for then +edit-status view."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()
        login_person(self.user)
        self.proposal = self.factory.makeBranchMergeProposal(
            registrant=self.user)

    def _createView(self):
        # Construct the view and initialize it.
        view = BranchMergeProposalChangeStatusView(
            self.proposal, LaunchpadTestRequest())
        view.initialize()
        return view

    def assertStatusVocabTokens(self, tokens, user):
        # Assert that the tokens specified are the only tokens in the
        # generated vocabulary.
        login_person(user)
        vocabulary = self._createView()._createStatusVocabulary()
        vocab_tokens = sorted([term.token for term in vocabulary])
        self.assertEqual(
            sorted(tokens), vocab_tokens)

    def assertAllStatusesAvailable(self, user, except_for=None):
        # All options should be available to the user, except for SUPERSEDED,
        # which is only provided through resubmit.
        desired_statuses = set([
            'WORK_IN_PROGRESS', 'NEEDS_REVIEW', 'MERGED', 'CODE_APPROVED',
            'REJECTED'])
        if except_for is not None:
            desired_statuses -= set(except_for)
        self.assertStatusVocabTokens(desired_statuses, user)

    def test_createStatusVocabulary_non_reviewer(self):
        # Neither the source branch owner nor the registrant should be
        # able to approve or reject their own code (assuming they don't have
        # rights on the target branch).
        status_options = [
            'WORK_IN_PROGRESS', 'NEEDS_REVIEW', 'MERGED']
        self.assertStatusVocabTokens(
            status_options, user=self.proposal.source_branch.owner)
        self.assertStatusVocabTokens(
            status_options, user=self.proposal.registrant)

    def test_createStatusVocabulary_reviewer(self):
        # The registrant should not be able to approve or reject
        # their own code (assuming they don't have rights on the target
        # branch).
        self.assertAllStatusesAvailable(self.proposal.target_branch.owner)

    def test_createStatusVocabulary_non_reviewer_approved(self):
        # Once the branch has been approved, the source owner or the
        # registrant can queue the branch.
        self.proposal.approveBranch(
            self.proposal.target_branch.owner, 'some-revision')
        status_options = [
            'WORK_IN_PROGRESS', 'NEEDS_REVIEW', 'CODE_APPROVED', 'MERGED']
        self.assertStatusVocabTokens(
            status_options, user=self.proposal.source_branch.owner)
        self.assertStatusVocabTokens(
            status_options, user=self.proposal.registrant)

    def test_createStatusVocabulary_reviewer_approved(self):
        # The target branch owner's options are not changed by whether or not
        # the proposal is currently approved.
        self.proposal.approveBranch(
            self.proposal.target_branch.owner, 'some-revision')
        self.assertAllStatusesAvailable(
            user=self.proposal.target_branch.owner)

    def test_createStatusVocabulary_rejected(self):
        # Only reviewers can change rejected proposals to approved.  All other
        # options for rejected proposals are the same regardless of user.
        self.proposal.rejectBranch(
            self.proposal.target_branch.owner, 'some-revision')
        self.assertAllStatusesAvailable(
            user=self.proposal.source_branch.owner,
            except_for=['CODE_APPROVED', 'QUEUED'])
        self.assertAllStatusesAvailable(user=self.proposal.registrant,
            except_for=['CODE_APPROVED', 'QUEUED'])
        self.assertAllStatusesAvailable(
            user=self.proposal.target_branch.owner)

    def test_createStatusVocabulary_queued(self):
        # Queued proposals can go to any status, but only reviewers can set
        # them to REJECTED.
        self.proposal.enqueue(
            self.proposal.target_branch.owner, 'some-revision')

        self.assertAllStatusesAvailable(
            user=self.proposal.source_branch.owner, except_for=['REJECTED'])
        self.assertAllStatusesAvailable(user=self.proposal.registrant,
                                        except_for=['REJECTED'])
        self.assertAllStatusesAvailable(
            user=self.proposal.target_branch.owner)


class TestCommentAttachmentRendering(TestCaseWithFactory):
    """Test diff attachments are rendered correctly."""

    layer = LaunchpadFunctionalLayer

    def _makeCommentFromEmailWithAttachment(self, attachment_body):
        # Make an email message with an attachment, and create a code
        # review comment from it.
        bmp = self.factory.makeBranchMergeProposal()
        login_person(bmp.registrant)
        msg = self.factory.makeEmailMessage(
            body='testing',
            attachments=[('test.diff', 'text/plain', attachment_body)])
        message = MessageSet().fromEmail(msg.as_string())
        return CodeReviewDisplayComment(
            bmp.createCommentFromMessage(message, None, None, msg))

    def test_nonascii_in_attachment_renders(self):
        # The view should render without errors.
        comment = self._makeCommentFromEmailWithAttachment('\xe2\x98\x95')
        # Need to commit in order to read the diff out of the librarian.
        transaction.commit()
        view = create_initialized_view(comment, '+comment-body')
        view()

    def test_nonascii_in_attachment_decoded(self):
        # The diff_text should be a unicode string.
        comment = self._makeCommentFromEmailWithAttachment('\xe2\x98\x95')
        # Need to commit in order to read the diff out of the librarian.
        transaction.commit()
        view = create_initialized_view(comment, '+comment-body')
        [diff_attachment] = view.comment.display_attachments
        self.assertEqual(u'\u2615', diff_attachment.diff_text)


class TestBranchMergeCandidateView(TestCaseWithFactory):
    """Test the status title for the view."""

    layer = DatabaseFunctionalLayer

    def test_needs_review_title(self):
        # No title is set for a proposal needing review.
        bmp = self.factory.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.NEEDS_REVIEW)
        view = create_initialized_view(bmp, '+link-summary')
        self.assertEqual('', view.status_title)

    def test_approved_shows_reviewer(self):
        # If the proposal is approved, the approver is shown in the title
        # along with when they approved it.
        bmp = self.factory.makeBranchMergeProposal()
        owner = bmp.target_branch.owner
        login_person(bmp.target_branch.owner)
        owner.displayname = 'Eric'
        bmp.approveBranch(owner, 'some-rev', datetime(
                year=2008, month=9, day=10, tzinfo=pytz.UTC))
        view = create_initialized_view(bmp, '+link-summary')
        self.assertEqual('Eric on 2008-09-10', view.status_title)

    def test_rejected_shows_reviewer(self):
        # If the proposal is rejected, the approver is shown in the title
        # along with when they approved it.
        bmp = self.factory.makeBranchMergeProposal()
        owner = bmp.target_branch.owner
        login_person(bmp.target_branch.owner)
        owner.displayname = 'Eric'
        bmp.rejectBranch(owner, 'some-rev', datetime(
                year=2008, month=9, day=10, tzinfo=pytz.UTC))
        view = create_initialized_view(bmp, '+link-summary')
        self.assertEqual('Eric on 2008-09-10', view.status_title)


class TestLatestProposalsForEachBranch(TestCaseWithFactory):
    """Confirm that the latest branch is returned."""

    layer = DatabaseFunctionalLayer

    def test_newest_first(self):
        # If each proposal targets a different branch, each will be returned.
        bmp1 = self.factory.makeBranchMergeProposal(
            date_created=(
                datetime(year=2008, month=9, day=10, tzinfo=pytz.UTC)))
        bmp2 = self.factory.makeBranchMergeProposal(
            date_created=(
                datetime(year=2008, month=10, day=10, tzinfo=pytz.UTC)))
        self.assertEqual(
            [bmp2, bmp1], latest_proposals_for_each_branch([bmp1, bmp2]))

    def test_visible_filtered_out(self):
        # If the proposal is not visible to the user, they are not returned.
        bmp1 = self.factory.makeBranchMergeProposal(
            date_created=(
                datetime(year=2008, month=9, day=10, tzinfo=pytz.UTC)))
        bmp2 = self.factory.makeBranchMergeProposal(
            date_created=(
                datetime(year=2008, month=10, day=10, tzinfo=pytz.UTC)))
        removeSecurityProxy(bmp2.source_branch).private = True
        self.assertEqual(
            [bmp1], latest_proposals_for_each_branch([bmp1, bmp2]))

    def test_same_target(self):
        # If the proposals target the same branch, then the most recent is
        # returned.
        bmp1 = self.factory.makeBranchMergeProposal(
            date_created=(
                datetime(year=2008, month=9, day=10, tzinfo=pytz.UTC)))
        bmp2 = self.factory.makeBranchMergeProposal(
            target_branch = bmp1.target_branch,
            date_created=(
                datetime(year=2008, month=10, day=10, tzinfo=pytz.UTC)))
        self.assertEqual(
            [bmp2], latest_proposals_for_each_branch([bmp1, bmp2]))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
