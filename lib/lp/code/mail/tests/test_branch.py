# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for Branch-related mailings"""

import re
from unittest import TestLoader

from canonical.testing import DatabaseFunctionalLayer

from lp.code.enums import (
    BranchSubscriptionNotificationLevel, BranchSubscriptionDiffSize,
    CodeReviewNotificationLevel)
from lp.code.mail.branch import BranchMailer, RecipientReason
from lp.code.model.branch import Branch
from lp.testing import login_person, TestCaseWithFactory


class TestRecipientReason(TestCaseWithFactory):
    """Test the RecipientReason class."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Need to set target_branch.date_last_modified.
        TestCaseWithFactory.setUp(self, user='test@canonical.com')

    def makeProposalWithSubscription(self, subscriber=None):
        """Test fixture."""
        if subscriber is None:
            subscriber = self.factory.makePerson()
        source_branch = self.factory.makeProductBranch(title='foo')
        target_branch = self.factory.makeProductBranch(
            product=source_branch.product, title='bar')
        merge_proposal = source_branch.addLandingTarget(
            source_branch.owner, target_branch)
        subscription = merge_proposal.source_branch.subscribe(
            subscriber, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        return merge_proposal, subscription

    def test_forBranchSubscriber(self):
        """Test values when created from a branch subscription."""
        merge_proposal, subscription = self.makeProposalWithSubscription()
        subscriber = subscription.person
        reason = RecipientReason.forBranchSubscriber(
            subscription, subscriber, '', merge_proposal)
        self.assertEqual(subscriber, reason.subscriber)
        self.assertEqual(subscriber, reason.recipient)
        self.assertEqual(merge_proposal.source_branch, reason.branch)

    def makeReviewerAndSubscriber(self):
        """Return a tuple of vote_reference, subscriber."""
        merge_proposal, subscription = self.makeProposalWithSubscription()
        subscriber = subscription.person
        login_person(merge_proposal.registrant)
        vote_reference = merge_proposal.nominateReviewer(
            subscriber, subscriber)
        return merge_proposal, vote_reference, subscriber

    def test_forReviewer(self):
        """Test values when created from a branch subscription."""
        ignored, vote_reference, subscriber = self.makeReviewerAndSubscriber()
        reason = RecipientReason.forReviewer(vote_reference, subscriber)
        self.assertEqual(subscriber, reason.subscriber)
        self.assertEqual(subscriber, reason.recipient)
        self.assertEqual(
            vote_reference.branch_merge_proposal.source_branch, reason.branch)

    def test_getReasonReviewer(self):
        bmp, vote_reference, subscriber = self.makeReviewerAndSubscriber()
        reason = RecipientReason.forReviewer(vote_reference, subscriber)
        self.assertEqual(
            'You are requested to review the proposed merge of %s into %s.'
            % (bmp.source_branch.bzr_identity,
               bmp.target_branch.bzr_identity),
            reason.getReason())

    def test_getReasonPerson(self):
        """Ensure the correct reason is generated for individuals."""
        merge_proposal, subscription = self.makeProposalWithSubscription()
        reason = RecipientReason.forBranchSubscriber(
            subscription, subscription.person, '', merge_proposal)
        self.assertEqual(
            'You are subscribed to branch %s.'
            % merge_proposal.source_branch.bzr_identity, reason.getReason())

    def test_getReasonTeam(self):
        """Ensure the correct reason is generated for teams."""
        team_member = self.factory.makePerson(
            displayname='Foo Bar', email='foo@bar.com')
        team = self.factory.makeTeam(team_member, displayname='Qux')
        bmp, subscription = self.makeProposalWithSubscription(team)
        reason = RecipientReason.forBranchSubscriber(
            subscription, team_member, '', bmp)
        self.assertEqual(
            'Your team Qux is subscribed to branch %s.'
            % bmp.source_branch.bzr_identity, reason.getReason())

    def test_usesBranchIdentityCache(self):
        """Ensure that the cache is used for branches if provided."""
        branch = self.factory.makeAnyBranch()
        subscription = branch.getSubscription(branch.owner)
        branch_cache = {branch: 'lp://fake'}
        def blowup(self):
            raise AssertionError('boom')
        patched = Branch.bzr_identity
        Branch.bzr_identity = property(blowup)
        def cleanup():
            Branch.bzr_identity = patched
        self.addCleanup(cleanup)
        self.assertRaises(AssertionError, getattr, branch, 'bzr_identity')
        reason = RecipientReason.forBranchSubscriber(
            subscription, subscription.person, '',
            branch_identity_cache=branch_cache)
        self.assertEqual(
            'You are subscribed to branch lp://fake.',
            reason.getReason())


class TestBranchMailerHeaders(TestCaseWithFactory):
    """Check the headers are correct for Branch email."""

    layer = DatabaseFunctionalLayer

    def test_branch_modified(self):
        # Test the email headers for a branch modified email.
        bob = self.factory.makePerson(email='bob@example.com')
        branch = self.factory.makeProductBranch(owner=bob)
        branch.getSubscription(bob).notification_level = (
            BranchSubscriptionNotificationLevel.FULL)
        mailer = BranchMailer.forBranchModified(branch, branch.owner, None)
        mailer.message_id = '<foobar-example-com>'
        ctrl = mailer.generateEmail('bob@example.com', branch.owner)
        self.assertEqual(
            {'X-Launchpad-Branch': branch.unique_name,
             'X-Launchpad-Message-Rationale': 'Subscriber',
             'X-Launchpad-Notification-Type': 'branch-updated',
             'X-Launchpad-Project': branch.product.name,
             'Message-Id': '<foobar-example-com>'},
            ctrl.headers)

    def test_branch_revision(self):
        # Test the email headers for new revision email.
        bob = self.factory.makePerson(email='bob@example.com')
        branch = self.factory.makeProductBranch(owner=bob)
        branch.getSubscription(bob).notification_level = (
            BranchSubscriptionNotificationLevel.FULL)
        mailer = BranchMailer.forRevision(
            branch, 1, 'from@example.com', contents='', diff=None, subject='')
        mailer.message_id = '<foobar-example-com>'
        ctrl = mailer.generateEmail('bob@example.com', branch.owner)
        self.assertEqual(
            {'X-Launchpad-Branch': branch.unique_name,
             'X-Launchpad-Message-Rationale': 'Subscriber',
             'X-Launchpad-Notification-Type': 'branch-revision',
             'X-Launchpad-Branch-Revision-Number': '1',
             'X-Launchpad-Project': branch.product.name,
             'Message-Id': '<foobar-example-com>'},
            ctrl.headers)


class TestBranchMailerDiff(TestCaseWithFactory):
    """Check the diff is an attachment for Branch email."""

    layer = DatabaseFunctionalLayer

    def makeBobMailController(self, diff=None,
                              max_lines=BranchSubscriptionDiffSize.WHOLEDIFF):
        bob = self.factory.makePerson(email='bob@example.com')
        branch = self.factory.makeProductBranch(owner=bob)
        subscription = branch.getSubscription(bob)
        subscription.max_diff_lines = max_lines
        subscription.notification_level = (
            BranchSubscriptionNotificationLevel.FULL)
        mailer = BranchMailer.forRevision(
            branch, 1, 'from@example.com', contents='', diff=diff, subject='')
        return mailer.generateEmail('bob@example.com', branch.owner)

    def test_generateEmail_with_no_diff(self):
        """When there is no diff, no attachment should be included."""
        ctrl = self.makeBobMailController()
        self.assertEqual([], ctrl.attachments)
        self.assertNotIn('larger than your specified limit', ctrl.body)

    def test_generateEmail_with_diff(self):
        """When there is a diff, it should be an attachment, not inline."""
        ctrl = self.makeBobMailController(diff='hello')
        self.assertEqual(1, len(ctrl.attachments))
        diff = ctrl.attachments[0]
        self.assertEqual('hello', diff.get_payload(decode=True))
        self.assertEqual('text/x-diff', diff['Content-type'])
        self.assertEqual('inline; filename="revision.diff"',
                         diff['Content-disposition'])
        self.assertNotIn('hello', ctrl.body)
        self.assertNotIn('larger than your specified limit', ctrl.body)

    def test_generateEmail_with_oversize_diff(self):
        """When the diff is oversize, don't attach, add reason."""
        ctrl = self.makeBobMailController(diff='hello\n' * 5000,
            max_lines=BranchSubscriptionDiffSize.FIVEKLINES)
        self.assertEqual([], ctrl.attachments)
        self.assertIn('The size of the diff (5001 lines) is larger than your'
            ' specified limit of 5000 lines', ctrl.body)

    def test_generateEmail_with_subscription_no_diff(self):
        """When subscription forbids diffs, don't add reason."""
        ctrl = self.makeBobMailController(diff='hello\n',
            max_lines=BranchSubscriptionDiffSize.NODIFF)
        self.assertEqual([], ctrl.attachments)
        self.assertNotIn('larger than your specified limit', ctrl.body)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
