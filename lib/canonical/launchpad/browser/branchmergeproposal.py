# Copyright 2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=C0322

"""Views, navigation and actions for BranchMergeProposals."""

__metaclass__ = type
__all__ = [
    'BranchMergeCandidateView',
    'BranchMergeProposalChangeStatusView',
    'BranchMergeProposalContextMenu',
    'BranchMergeProposalDeleteView',
    'BranchMergeProposalDequeueView',
    'BranchMergeProposalEditView',
    'BranchMergeProposalEnqueueView',
    'BranchMergeProposalInlineDequeueView',
    'BranchMergeProposalJumpQueueView',
    'BranchMergeProposalNavigation',
    'BranchMergeProposalMergedView',
    'BranchMergeProposalPrimaryContext',
    'BranchMergeProposalRequestReviewView',
    'BranchMergeProposalResubmitView',
    'BranchMergeProposalReviewView',
    'BranchMergeProposalSubscribersView',
    'BranchMergeProposalView',
    'BranchMergeProposalVoteLinkView',
    'BranchMergeProposalVoteView',
    'BranchMergeProposalWorkInProgressView',
    ]

import operator

from zope.component import getUtility
from zope.event import notify as zope_notify
from zope.formlib import form
from zope.interface import Interface, implements
from zope.schema import Choice, Int, TextLine
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm

from canonical.cachedproperty import cachedproperty
from canonical.config import config

from canonical.launchpad import _
from canonical.launchpad.components.branch import BranchMergeProposalDelta
from canonical.launchpad.event import SQLObjectModifiedEvent
from canonical.launchpad.fields import PublicPersonChoice, Summary, Whiteboard
from canonical.launchpad.interfaces import (
    BRANCH_MERGE_PROPOSAL_FINAL_STATES,
    BranchMergeProposalStatus,
    BranchType,
    IBranchMergeProposal,
    IMessageSet,
    WrongBranchMergeProposal)
from canonical.launchpad.interfaces.branchsubscription import (
    CodeReviewNotificationLevel)
from canonical.launchpad.interfaces.codereviewcomment import (
    CodeReviewVote)
from canonical.launchpad.interfaces.codereviewvote import (
    ICodeReviewVoteReference)
from canonical.launchpad.mailout.branchmergeproposal import (
    BMPMailer, RecipientReason)
from canonical.launchpad.webapp import (
    canonical_url, ContextMenu, Link, enabled_with_permission,
    LaunchpadEditFormView, LaunchpadView, action, stepthrough, Navigation)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interfaces import IPrimaryContext

from canonical.lazr import decorates


class BranchMergeProposalPrimaryContext:
    """The primary context is the proposal is that of the source branch."""

    implements(IPrimaryContext)

    def __init__(self, branch_merge_proposal):
        self.context = IPrimaryContext(
            branch_merge_proposal.source_branch).context


def notify(func):
    """Decorate a view method to send a notification."""
    def decorator(view, *args, **kwargs):
        snapshot = BranchMergeProposalDelta.snapshot(view.context)
        result = func(view, *args, **kwargs)
        zope_notify(SQLObjectModifiedEvent(view.context, snapshot, []))
        return result
    return decorator


def update_and_notify(func):
    """Decorate an action to update from a form and send a notification."""
    @notify
    def decorator(view, action, data):
        result = func(view, action, data)
        form.applyChanges(
            view.context, view.form_fields, data, view.adapters)
        return result
    return decorator


class BranchMergeCandidateView(LaunchpadView):
    """Provides a small fragment of landing targets"""

    def friendly_text(self):
        """Prints friendly text for a branch."""
        friendly_texts = {
            BranchMergeProposalStatus.WORK_IN_PROGRESS : 'On hold',
            BranchMergeProposalStatus.NEEDS_REVIEW : 'Ready for review',
            BranchMergeProposalStatus.CODE_APPROVED : 'Approved',
            BranchMergeProposalStatus.REJECTED : 'Rejected',
            BranchMergeProposalStatus.MERGED : 'Merged',
            BranchMergeProposalStatus.MERGE_FAILED :
                'Approved [Merge Failed]',
            BranchMergeProposalStatus.QUEUED : 'Queued',
            BranchMergeProposalStatus.SUPERSEDED : 'Superseded'
            }
        return friendly_texts[self.context.queue_status]

    @property
    def queue_location(self):
        """The location of the queue view."""
        # Will point to the target_branch queue, or the queue
        # with multiple targets if specified.
        return canonical_url(self.context.target_branch) + '/+merge-queue'


class BranchMergeProposalContextMenu(ContextMenu):
    """Context menu for branches."""

    usedfor = IBranchMergeProposal
    links = ['edit', 'delete', 'set_work_in_progress', 'request_review',
             'add_comment', 'review', 'merge', 'enqueue', 'dequeue',
             'resubmit', 'update_merge_revno', 'edit_status']

    @enabled_with_permission('launchpad.AnyPerson')
    def add_comment(self):
        return Link('+comment', 'Add a comment/review', icon='add')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit details'
        status = self.context.queue_status
        enabled = status not in BRANCH_MERGE_PROPOSAL_FINAL_STATES
        return Link('+edit', text, icon='edit', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def edit_status(self):
        text = 'Change status'
        status = self.context.queue_status
        # Can't change the status if Merged or Superseded
        enabled = status not in (BranchMergeProposalStatus.SUPERSEDED,
                                 BranchMergeProposalStatus.MERGED)
        return Link('+edit-status', text, icon='edit', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def delete(self):
        text = 'Delete proposal to merge'
        return Link('+delete', text, icon='remove')

    def _enabledForStatus(self, next_state):
        """True if the next_state is a valid transition for the current user.

        Return False if the current state is next_state.
        """
        status = self.context.queue_status
        if status == next_state:
            return False
        else:
            return self.context.isValidTransition(next_state, self.user)

    @enabled_with_permission('launchpad.Edit')
    def set_work_in_progress(self):
        text = 'Work in progress'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.WORK_IN_PROGRESS)
        return Link('+work-in-progress', text, enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def request_review(self):
        text = 'Request a review'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.NEEDS_REVIEW)
        if (self.context.queue_status ==
            BranchMergeProposalStatus.NEEDS_REVIEW):
            enabled = True
            if (self.context.votes.count()) > 0:
                text = 'Request another review'
        return Link('+request-review', text, icon='add', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def review(self):
        text = 'Review proposal'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.CODE_APPROVED)
        return Link('+review', text, enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def merge(self):
        text = 'Mark as merged'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.MERGED)
        return Link('+merged', text, enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def update_merge_revno(self):
        text = 'Update revision number'
        return Link('+merged', text)

    @enabled_with_permission('launchpad.Edit')
    def enqueue(self):
        text = 'Queue for merging'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.QUEUED)
        return Link('+enqueue', text, enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def dequeue(self):
        text = 'Remove from queue'
        enabled = (self.context.queue_status ==
                   BranchMergeProposalStatus.QUEUED)
        return Link('+dequeue', text, enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def resubmit(self):
        text = 'Resubmit proposal'
        enabled = self._enabledForStatus(
            BranchMergeProposalStatus.SUPERSEDED)
        return Link('+resubmit', text, enabled=enabled)


class UnmergedRevisionsMixin:
    """Provides the methods needed to show unmerged revisions."""

    @cachedproperty
    def unlanded_revisions(self):
        """Return the unlanded revisions from the source branch."""
        return self.context.getUnlandedSourceBranchRevisions()

    @property
    def codebrowse_url(self):
        """Return the link to codebrowse for this branch."""
        return (config.codehosting.codebrowse_root +
                self.context.source_branch.unique_name)


class BranchMergeProposalRevisionIdMixin:
    """A mixin class to provide access to the revision ids."""

    def _getRevisionNumberForRevisionId(self, revision_id):
        """Find the revision number that corresponds to the revision id.

        If there was no last reviewed revision, None is returned.

        If the reviewed revision is no longer in the revision history of
        the source branch, then a message is returned.
        """
        if revision_id is None:
            return None
        # If the source branch is REMOTE, then there won't be any ids.
        source_branch = self.context.source_branch
        if source_branch.branch_type == BranchType.REMOTE:
            return revision_id
        else:
            branch_revision = source_branch.getBranchRevision(
                revision_id=revision_id)
            if branch_revision is None:
                return "no longer in the source branch."
            elif branch_revision.sequence is None:
                return (
                    "no longer in the revision history of the source branch.")
            else:
                return branch_revision.sequence

    @cachedproperty
    def reviewed_revision_number(self):
        """Return the number of the reviewed revision."""
        return self._getRevisionNumberForRevisionId(
            self.context.reviewed_revision_id)

    @cachedproperty
    def queued_revision_number(self):
        """Return the number of the queued revision."""
        return self._getRevisionNumberForRevisionId(
            self.context.queued_revision_id)


class BranchMergeProposalNavigation(Navigation):
    """Navigation from BranchMergeProposal to CodeReviewComment views."""

    usedfor = IBranchMergeProposal

    @stepthrough('comments')
    def traverse_comment(self, id):
        try:
            id = int(id)
        except ValueError:
            return None
        try:
            return self.context.getComment(id)
        except WrongBranchMergeProposal:
            return None


class BranchMergeProposalView(LaunchpadView, UnmergedRevisionsMixin,
                              BranchMergeProposalRevisionIdMixin):
    """A basic view used for the index page."""

    label = "Proposal to merge branches"
    __used_for__ = IBranchMergeProposal

    @property
    def queue_location(self):
        """The location of the queue view."""
        # Will point to the target_branch queue, or the queue
        # with multiple targets if specified.
        return canonical_url(self.context.target_branch) + '/+merge-queue'

    @property
    def comment_location(self):
        """Location of page for commenting on this proposal."""
        return canonical_url(self.context, view_name='+comment')

    @property
    def comments(self):
        """Return comments associated with this proposal, plus styling info.

        Comments are in threaded order, and the style indicates indenting
        for use with threads.
        """
        message_to_comment = {}
        messages = []
        for comment in self.context.all_comments:
            message_to_comment[comment.message] = comment
            messages.append(comment.message)
        message_set = getUtility(IMessageSet)
        threads = message_set.threadMessages(messages)
        result = []
        for depth, message in message_set.flattenThreads(threads):
            comment = message_to_comment[message]
            style = 'margin-left: %dem;' % (2 * depth)
            result.append(dict(style=style, comment=comment))
        return result

    @property
    def has_bug_or_spec(self):
        """Return whether or not the merge proposal has a linked bug or spec.
        """
        branch = self.context.source_branch
        return branch.bug_branches or branch.spec_links


class DecoratedCodeReviewVoteReference:
    """Provide a code review vote that knows if it is important or not."""

    decorates(ICodeReviewVoteReference)

    def __init__(self, context):
        self.context = context

    @property
    def reviewer_relationship(self):
        """The relationship of the reviewer to the code review."""
        vote = self.context
        if vote.reviewer != vote.registrant:
            return _("Requested reviewer")
        target_branch = vote.branch_merge_proposal.target_branch
        if vote.reviewer.inTeam(target_branch.code_reviewer):
            return _("Target branch reviewer")
        else:
            return None

    @property
    def date_of_comment(self):
        """The date of the comment, not the date_created of the vote."""
        return self.context.comment.message.datecreated


class BranchMergeProposalVoteView(LaunchpadView):
    """The view used for the tables of votes and requested reviews."""

    __used_for__ = IBranchMergeProposal

    # Show hyperlinks to the comments?
    show_comment_links = False

    @cachedproperty
    def reviews(self):
        """Return the decorated votes for the proposal."""
        return [DecoratedCodeReviewVoteReference(vote)
                for vote in self.context.votes]

    def _getOrderedReviews(self, actual_vote):
        """Return votes with the specified vote ordered newest first."""
        reviews = [review for review in self.reviews
                   if (review.comment is not None and
                       review.comment.vote == actual_vote)]
        return sorted(reviews, key=operator.attrgetter('date_of_comment'),
                      reverse=True)

    @property
    def current_reviews(self):
        """The current votes ordered by vote then date."""
        # We want the reviews in a specific order.
        # Disapprovals first, then approvals, then abstentions.
        return (self._getOrderedReviews(CodeReviewVote.DISAPPROVE) +
                self._getOrderedReviews(CodeReviewVote.APPROVE) +
                self._getOrderedReviews(CodeReviewVote.ABSTAIN))

    @property
    def requested_reviews(self):
        """Reviews requested but not yet done."""
        reviews = [review for review in self.reviews
                   if review.comment is None]
        # Now sort so the most recently created is first.
        return sorted(reviews, key=operator.attrgetter('date_created'),
                      reverse=True)

class BranchMergeProposalVoteLinkView(BranchMergeProposalVoteView):
    """A view to show the votes with hyperlinks to the comments."""

    # Show hyperlinks to the comments?
    show_comment_links = True


class BranchMergeProposalWorkInProgressView(LaunchpadEditFormView):
    """The view used to set a proposal back to 'work in progress'."""

    schema = IBranchMergeProposal
    field_names = ["whiteboard"]
    label = "Set proposal as work in progress"

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    @action('Set as work in progress', name='wip')
    @notify
    def wip_action(self, action, data):
        """Set the status to 'Needs review'."""
        self.context.setAsWorkInProgress()
        self.updateContextFromData(data)

    def validate(self, data):
        """Ensure that the proposal is in an appropriate state."""
        if self.context.queue_status == BranchMergeProposalStatus.MERGED:
            self.addError("The merge proposal is not an a valid state to "
                          "mark as 'Work in progress'.")


class IReviewRequest(Interface):
    """Schema for requesting a review."""

    whiteboard = Whiteboard(
        title=_('Whiteboard'), required=False,
        description=_('Notes about the merge.'))

    review_candidate = PublicPersonChoice(
        title=_('Reviewer'), required=False,
        description=_('A person who you want to review this.'),
        vocabulary='ValidPersonOrTeam')

    review_type = TextLine(
        title=_('Review type'), required=False)


class BranchMergeProposalRequestReviewView(LaunchpadEditFormView):
    """The view used to request a review of the merge proposal."""

    schema = IReviewRequest
    label = "Request review"

    @property
    def initial_values(self):
        """Force the non-BMP values to None."""
        return {'review_candidate': None, 'review_type': None}

    @property
    def adapters(self):
        """Force IReviewRequest handling for BranchMergeProposal."""
        return {IReviewRequest: self.context}

    @property
    def is_needs_review(self):
        """Return True if queue status is NEEDS_REVIEW."""
        return (self.context.queue_status ==
            BranchMergeProposalStatus.NEEDS_REVIEW)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    def requestReview(self, candidate, review_type):
        """Request a `review_type` review from `candidate` and email them."""
        vote_reference = self.context.nominateReviewer(
            candidate, self.user, review_type)
        reason = RecipientReason.forReviewer(vote_reference, candidate)
        mailer = BMPMailer.forReviewRequest(reason, self.context, self.user)
        mailer.sendAll()

    @action('Request review', name='review')
    @notify
    def review_action(self, action, data):
        """Set 'Needs review' status, nominate reviewers, send emails."""
        self.context.requestReview()
        candidate = data.pop('review_candidate', None)
        review_type = data.pop('review_type', None)
        if candidate is not None:
            self.requestReview(candidate, review_type)
        form.applyChanges(self, self.form_fields, data, self.adapters)

    def validate(self, data):
        """Ensure that the proposal is in an appropriate state."""
        if self.context.queue_status == BranchMergeProposalStatus.MERGED:
            self.addError("The merge proposal is not an a valid state to "
                          "mark as 'Needs review'.")


class ReviewForm(Interface):
    """A simple interface to define the revision number field."""

    revision_number = Int(
        title=_("Reviewed Revision"), required=True,
        description=_("The revision number on the source branch which "
                      "has been reviewed."))

    whiteboard = Whiteboard(
        title=_('Whiteboard'), required=False,
        description=_('Notes about the merge.'))


class MergeProposalEditView(LaunchpadEditFormView,
                            BranchMergeProposalRevisionIdMixin):
    """A base class for merge proposal edit views."""

    def initialize(self):
        # Record next_url and cancel url now
        self.next_url = canonical_url(self.context)
        self.cancel_url = self.next_url
        super(MergeProposalEditView, self).initialize()


    def _getRevisionId(self, data):
        """Translate the revision number that was entered into a revision id.

        If the branch is REMOTE we won't have any scanned revisions to compare
        against, so store the raw integer revision number as the revision id.
        """
        source_branch = self.context.source_branch
        # Get the revision number out of the data.
        if source_branch.branch_type == BranchType.REMOTE:
            return str(data.pop('revision_number'))
        else:
            branch_revision = source_branch.getBranchRevision(
                sequence=data.pop('revision_number'))
            return branch_revision.revision.revision_id

    def _validateRevisionNumber(self, data, revision_name):
        """Check to make sure that the revision number entered is valid."""
        rev_no = data.get('revision_number')
        if rev_no is not None:
            try:
                rev_no = int(rev_no)
            except ValueError:
                self.setFieldError(
                    'revision_number',
                    'The %s revision must be a positive number.'
                    % revision_name)
            else:
                if rev_no < 1:
                    self.setFieldError(
                        'revision_number',
                        'The %s revision must be a positive number.'
                        % revision_name)
                # Accept any positive integer for a REMOTE branch.
                source_branch = self.context.source_branch
                if (source_branch.branch_type != BranchType.REMOTE and
                    rev_no > source_branch.revision_count):
                    self.setFieldError(
                        'revision_number',
                        'The %s revision cannot be larger than the '
                        'tip revision of the source branch.'
                        % revision_name)


class BranchMergeProposalResubmitView(MergeProposalEditView,
                                      UnmergedRevisionsMixin):
    """The view to resubmit a proposal to merge."""

    schema = IBranchMergeProposal
    label = "Resubmit proposal to merge"
    field_names = ["whiteboard"]

    @action('Resubmit', name='resubmit')
    @update_and_notify
    def resubmit_action(self, action, data):
        """Resubmit this proposal."""
        proposal = self.context.resubmit(self.user)
        self.request.response.addInfoNotification(_(
            "Please update the whiteboard for the new proposal."))
        self.next_url = canonical_url(proposal) + "/+edit"


class BranchMergeProposalReviewView(MergeProposalEditView,
                                    UnmergedRevisionsMixin):
    """The view to approve or reject a merge proposal."""

    schema = ReviewForm
    label = "Review proposal to merge"

    @property
    def adapters(self):
        """See `LaunchpadFormView`"""
        return {ReviewForm: self.context}

    @property
    def initial_values(self):
        # Default to reviewing the tip of the source branch.
        return {'revision_number': self.context.source_branch.revision_count}

    @action('Approve', name='approve')
    @update_and_notify
    def approve_action(self, action, data):
        """Set the status to approved."""
        self.context.approveBranch(self.user, self._getRevisionId(data))

    @action('Reject', name='reject')
    @update_and_notify
    def reject_action(self, action, data):
        """Set the status to rejected."""
        self.context.rejectBranch(self.user, self._getRevisionId(data))

    def validate(self, data):
        """Ensure that the proposal is in an appropriate state."""
        if self.context.queue_status == BranchMergeProposalStatus.MERGED:
            self.addError("The merge proposal is not an a valid state to "
                          "review.")
        self._validateRevisionNumber(data, 'reviewed')


class BranchMergeProposalEditView(MergeProposalEditView):
    """The view to control the editing of merge proposals."""
    schema = IBranchMergeProposal
    label = "Edit branch merge proposal"
    field_names = ["commit_message", "whiteboard"]

    @action('Update', name='update')
    def update_action(self, action, data):
        """Update the whiteboard and go back to the source branch."""
        self.updateContextFromData(data)


class BranchMergeProposalDeleteView(MergeProposalEditView):
    """The view to control the deletion of merge proposals."""
    schema = IBranchMergeProposal
    label = "Delete branch merge proposal"
    field_names = []

    def initialize(self):
        # Store the source branch for `next_url` to make sure that
        # it is available in the situation where the merge proposal
        # is deleted.
        self.source_branch = self.context.source_branch
        super(BranchMergeProposalDeleteView, self).initialize()

    @action('Delete proposal', name='delete')
    def delete_action(self, action, data):
        """Delete the merge proposal and go back to the source branch."""
        self.context.deleteProposal()
        # Override the next url to be the source branch.
        self.next_url = canonical_url(self.source_branch)


class BranchMergeProposalMergedView(LaunchpadEditFormView):
    """The view to mark a merge proposal as merged."""
    schema = IBranchMergeProposal
    label = "Edit branch merge proposal"
    field_names = ["merged_revno"]

    @property
    def initial_values(self):
        # Default to the tip of the target branch, on the assumption that the
        # source branch has just been merged into it.
        return {'merged_revno': self.context.target_branch.revision_count}

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    @action('Mark as Merged', name='mark_merged')
    @notify
    def mark_merged_action(self, action, data):
        """Update the whiteboard and go back to the source branch."""
        revno = data['merged_revno']
        if self.context.queue_status == BranchMergeProposalStatus.MERGED:
            self.context.merged_revno = revno
            self.request.response.addNotification(
                'The proposal\'s merged revision has been updated.')
        else:
            self.context.markAsMerged(revno, merge_reporter=self.user)
            self.request.response.addNotification(
                'The proposal has now been marked as merged.')

    def validate(self, data):
        # Ensure a positive integer value.
        revno = data.get('merged_revno')
        if revno is not None:
            if revno <= 0:
                self.setFieldError(
                    'merged_revno',
                    'Revision numbers must be positive integers.')


class EnqueueForm(Interface):
    """A simple interface to populate the form to enqueue a proposal."""

    revision_number = Int(
        title=_("Queue Revision"), required=True,
        description=_("The revision number of the source branch "
                      "which is to be merged into the target branch."))

    commit_message = Summary(
        title=_("Commit Message"), required=True,
        description=_("The commit message to be used when merging "
                      "the source branch."))

    whiteboard = Whiteboard(
        title=_('Whiteboard'), required=False,
        description=_('Notes about the merge.'))


class BranchMergeProposalEnqueueView(MergeProposalEditView,
                                     UnmergedRevisionsMixin):
    """The view to submit a merge proposal for merging."""

    schema = EnqueueForm
    label = "Queue branch for merging"

    @property
    def initial_values(self):
        # If the user is a valid reviewer, then default the revision
        # number to be the tip.
        if self.context.isPersonValidReviewer(self.user):
            revision_number = self.context.source_branch.revision_count
        else:
            revision_number = self._getRevisionNumberForRevisionId(
                self.context.reviewed_revision_id)

        return {'revision_number': revision_number}

    @property
    def adapters(self):
        """See `LaunchpadFormView`"""
        return {EnqueueForm: self.context}

    def setUpFields(self):
        super(BranchMergeProposalEnqueueView, self).setUpFields()
        # If the user is not a valid reviewer for the target branch,
        # then the revision number should be read only, so an
        # untrusted user cannot land changes that have not bee reviewed.
        if not self.context.isPersonValidReviewer(self.user):
            self.form_fields['revision_number'].for_display = True

    @action('Enqueue', name='enqueue')
    @update_and_notify
    def enqueue_action(self, action, data):
        """Update the whiteboard and enqueue the merge proposal."""
        if self.context.isPersonValidReviewer(self.user):
            revision_id = self._getRevisionId(data)
        else:
            revision_id = self.context.reviewed_revision_id
        self.context.enqueue(self.user, revision_id)

    def validate(self, data):
        """Make sure that the proposal has been reviewed.

        Or that the logged in user is able to review the branch as well.
        """
        if not self.context.isValidTransition(
            BranchMergeProposalStatus.QUEUED, self.user):
            self.addError(
                "The merge proposal is cannot be queued as it has not "
                "been reviewed.")

        self._validateRevisionNumber(data, 'enqueued')


class BranchMergeProposalDequeueView(LaunchpadEditFormView):
    """The view to remove a merge proposal from the merge queue."""

    schema = IBranchMergeProposal
    field_names = ["whiteboard"]

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    @action('Dequeue', name='dequeue')
    @update_and_notify
    def dequeue_action(self, action, data):
        """Update the whiteboard and remove the proposal from the queue."""
        self.context.dequeue()

    def validate(self, data):
        """Make sure the proposal is queued before removing."""
        if self.context.queue_status != BranchMergeProposalStatus.QUEUED:
            self.addError("The merge proposal is not queued.")


class BranchMergeProposalInlineDequeueView(LaunchpadEditFormView):
    """The view to provide a 'dequeue' button to the queue view."""

    schema = IBranchMergeProposal
    field_names = []

    @property
    def next_url(self):
        return canonical_url(self.context.target_branch) + '/+merge-queue'

    cancel_url = next_url

    @action('Dequeue', name='dequeue')
    @notify
    def dequeue_action(self, action, data):
        """Remove the proposal from the queue if queued."""
        if self.context.queue_status == BranchMergeProposalStatus.QUEUED:
            self.context.dequeue()

    @property
    def prefix(self):
        return "field%s" % self.context.id

    @property
    def action_url(self):
        return "%s/+dequeue-inline" % canonical_url(self.context)


class BranchMergeProposalJumpQueueView(LaunchpadEditFormView):
    """The view to provide a move the proposal to the front of the queue."""

    schema = IBranchMergeProposal
    field_names = []

    @property
    def next_url(self):
        return canonical_url(self.context.target_branch) + '/+merge-queue'

    @action('Move to front', name='move')
    @notify
    def move_action(self, action, data):
        """Move the proposal to the front of the queue (if queued)."""
        if (self.context.queue_status == BranchMergeProposalStatus.QUEUED and
            check_permission('launchpad.Edit', self.context.target_branch)):
            self.context.moveToFrontOfQueue()

    @property
    def prefix(self):
        return "field%s" % self.context.id

    @property
    def action_url(self):
        return "%s/+jump-queue" % canonical_url(self.context)


class BranchMergeProposalSubscribersView(LaunchpadView):
    """Used to show the pagelet subscribers on the main proposal page."""

    __used_for__ = IBranchMergeProposal

    def initialize(self):
        """See `LaunchpadView`."""
        # Get the subscribers and dump them into two sets.
        self._full_subscribers = set()
        self._status_subscribers = set()
        # Add subscribers from the source and target branches.
        self._add_subscribers_for_branch(self.context.source_branch)
        self._add_subscribers_for_branch(self.context.target_branch)
        # Remove all the people from the comment_subscribers from the
        # status_and_vote_subscribers as they recipients will get the email
        # only once, and for the most detailed subscription from the source
        # and target branches.
        self._status_subscribers = (
            self._status_subscribers - self._full_subscribers)

    def _add_subscribers_for_branch(self, branch):
        """Add the subscribers to the subscription sets for the branch."""
        for subscription in branch.subscriptions:
            level = subscription.review_level
            if level == CodeReviewNotificationLevel.FULL:
                self._full_subscribers.add(subscription.person)
            elif level == CodeReviewNotificationLevel.STATUS:
                self._status_subscribers.add(subscription.person)
            else:
                # We don't do anything right now with people who say they
                # don't want to see anything.
                pass

    @cachedproperty
    def full_subscribers(self):
        """A list of full subscribers ordered by displayname."""
        return sorted(
            self._full_subscribers, key=operator.attrgetter('displayname'))

    @cachedproperty
    def status_subscribers(self):
        """A list of full subscribers ordered by displayname."""
        return sorted(
            self._status_subscribers, key=operator.attrgetter('displayname'))

    @property
    def has_subscribers(self):
        """True if there are subscribers to the branch."""
        return len(self.full_subscribers) + len(self.status_subscribers)


class BranchMergeProposalChangeStatusView(MergeProposalEditView):

    label = "Change merge proposal status"
    schema = IBranchMergeProposal
    field_names = []

    def _createStatusVocabulary(self):
        # Create the vocabulary that is used for the status widget.
        curr_status = self.context.queue_status
        possible_next_states = (
            BranchMergeProposalStatus.WORK_IN_PROGRESS,
            BranchMergeProposalStatus.NEEDS_REVIEW,
            BranchMergeProposalStatus.CODE_APPROVED,
            BranchMergeProposalStatus.REJECTED,
            # BranchMergeProposalStatus.QUEUED,
            BranchMergeProposalStatus.MERGED)
        terms = [
            SimpleTerm(status, status.name, status.title)
            for status in possible_next_states
            if (self.context.isValidTransition(status, self.user)
                # Edge case here for removing a queued proposal, we do this by
                # setting the next state to code approved.
                or (status == BranchMergeProposalStatus.CODE_APPROVED and
                    curr_status == BranchMergeProposalStatus.QUEUED))
            ]
        # Resubmit edge case.
        if curr_status != BranchMergeProposalStatus.QUEUED:
            terms.append(SimpleTerm(
                    BranchMergeProposalStatus.SUPERSEDED, 'SUPERSEDED',
                    'Resubmit'))
        return SimpleVocabulary(terms)

    def setUpFields(self):
        MergeProposalEditView.setUpFields(self)
        # Add the custom restricted queue status widget.
        status_field = self.schema['queue_status']

        status_choice = Choice(
                __name__='queue_status', title=status_field.title,
                required=True, vocabulary=self._createStatusVocabulary())
        status_field = form.Fields(
            status_choice, render_context=self.render_context)
        self.form_fields = status_field + self.form_fields

    @action('Change Status', name='update')
    @notify
    def update_action(self, action, data):
        """Update the status."""

        curr_status = self.context.queue_status
        # If the status has been updated elsewhere to set the proposal to
        # merged or superseded, then return.
        if curr_status in (BranchMergeProposalStatus.SUPERSEDED,
                           BranchMergeProposalStatus.MERGED):
            return
        # Assume for now that the queue_status in the data is a valid
        # transition from where we are.
        rev_id = self.request.form['revno']
        new_status = data['queue_status']
        # Don't do anything if the user hasn't changed the status.
        if new_status == curr_status:
            return

        if new_status == BranchMergeProposalStatus.WORK_IN_PROGRESS:
            self.context.setAsWorkInProgress()
        elif new_status == BranchMergeProposalStatus.NEEDS_REVIEW:
            self.context.requestReview()
        elif new_status == BranchMergeProposalStatus.CODE_APPROVED:
            # Other half of the edge case.  If the status is currently queued,
            # we need to dequeue, otherwise we just approve the branch.
            if curr_status == BranchMergeProposalStatus.QUEUED:
                self.context.dequeue()
            else:
                self.context.approveBranch(self.user, rev_id)
        elif new_status == BranchMergeProposalStatus.REJECTED:
            self.context.rejectBranch(self.user, rev_id)
        elif new_status == BranchMergeProposalStatus.QUEUED:
            self.context.enqueue(self.user, rev_id)
        elif new_status == BranchMergeProposalStatus.MERGED:
            self.context.markAsMerged(merge_reporter=self.user)
        elif new_status == BranchMergeProposalStatus.SUPERSEDED:
            # Redirect the user to the resubmit view.
            self.next_url = canonical_url(self.context, view_name="+resubmit")
        else:
            raise AssertionError('Unexpected queue status: ' % new_status)

