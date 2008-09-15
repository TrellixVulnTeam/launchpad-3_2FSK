# Copyright 2007-2008 Canonical Ltd.  All rights reserved.

"""Unit tests for BranchMergeProposals."""

__metaclass__ = type

from datetime import timedelta
import unittest

from canonical.launchpad.browser.branchmergeproposal import (
    BranchMergeProposalMergedView, BranchMergeProposalVoteView)
from canonical.launchpad.interfaces.codereviewcomment import (
    CodeReviewVote)
from canonical.launchpad.testing import TestCaseWithFactory, time_counter
from canonical.launchpad.webapp.interfaces import IPrimaryContext
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import DatabaseFunctionalLayer


class TestBranchMergeProposalPrimaryContext(TestCaseWithFactory):
    """Tests the adaptation of a merge proposal into a primary context."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin so we don't have to worry about launchpad.Edit
        # permissions on the merge proposals.
        TestCaseWithFactory.setUp(self, user="admin@canonical.com")

    def testPrimaryContext(self):
        # The primary context of a merge proposal is the same as the primary
        # context of the source_branch.
        bmp = self.factory.makeBranchMergeProposal()
        self.assertEqual(
            IPrimaryContext(bmp).context,
            IPrimaryContext(bmp.source_branch).context)


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
        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())
        self.assertEqual([], view.current_reviews)
        self.assertEqual([], view.requested_reviews)

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

    def testCurrentReviewOrdering(self):
        # Disapprove first, then Approve, lastly Abstain.
        # Request three reviews.
        albert = self.factory.makePerson(name='albert')
        bob = self.factory.makePerson(name='bob')
        charles = self.factory.makePerson(name='charles')

        owner = self.bmp.source_branch.owner

        self._createComment(albert, CodeReviewVote.APPROVE)
        self._createComment(bob, CodeReviewVote.ABSTAIN)
        self._createComment(charles, CodeReviewVote.DISAPPROVE)

        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())

        self.assertEqual(
            [charles, albert, bob],
            [review.reviewer for review in view.current_reviews])

    def testChangeOfVoteBringsToTop(self):
        # If albert changes his abstention to an approve, it comes before
        # other votes that occurred between the abstention and the approval.

        # Disapprove first, then Approve, lastly Abstain.
        # Request three reviews.
        albert = self.factory.makePerson(name='albert')
        bob = self.factory.makePerson(name='bob')

        owner = self.bmp.source_branch.owner

        self._createComment(albert, CodeReviewVote.ABSTAIN)
        self._createComment(bob, CodeReviewVote.APPROVE)
        self._createComment(albert, CodeReviewVote.APPROVE)

        view = BranchMergeProposalVoteView(self.bmp, LaunchpadTestRequest())

        self.assertEqual(
            [albert, bob],
            [review.reviewer for review in view.current_reviews])


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
