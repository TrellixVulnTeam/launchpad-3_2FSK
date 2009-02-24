# Copyright 2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Database class for branch merge prosals."""

__metaclass__ = type
__all__ = [
    'BranchMergeProposal',
    'BranchMergeProposalGetter',
    'CreateMergeProposalJob',
    'is_valid_transition',
    ]

from email.Utils import make_msgid

from lazr.delegates import delegates
from storm.expr import And
from storm.store import Store
from zope.component import getUtility
from zope.event import notify
from zope.interface import classProvides, implements

from storm.expr import Desc, Join, LeftJoin
from storm.locals import Int, Reference
from sqlobject import ForeignKey, IntCol, StringCol, SQLMultipleJoin

from canonical.config import config
from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import quote, SQLBase, sqlvalues

from canonical.launchpad.database.branchrevision import BranchRevision
from canonical.launchpad.database.codereviewcomment import CodeReviewComment
from canonical.launchpad.database.codereviewvote import (
    CodeReviewVoteReference)
from canonical.launchpad.database.diff import Diff, PreviewDiff
from canonical.launchpad.database.job import Job
from canonical.launchpad.database.message import (
    Message, MessageChunk, MessageJob, MessageJobAction)
from canonical.launchpad.database.person import Person
from canonical.launchpad.event.branchmergeproposal import (
    BranchMergeProposalStatusChangeEvent, NewCodeReviewCommentEvent,
    ReviewerNominatedEvent)
from canonical.launchpad.interfaces.branch import IBranchNavigationMenu
from canonical.launchpad.interfaces.branchcollection import IAllBranches
from canonical.launchpad.interfaces.branchmergeproposal import (
    BadBranchMergeProposalSearchContext, BadStateTransition,
    BranchMergeProposalStatus, BRANCH_MERGE_PROPOSAL_FINAL_STATES,
    IBranchMergeProposal, IBranchMergeProposalGetter, ICreateMergeProposalJob,
    ICreateMergeProposalJobSource, UserNotBranchReviewer,
    WrongBranchMergeProposal)
from canonical.launchpad.interfaces.codereviewcomment import CodeReviewVote
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.message import IMessageJob
from canonical.launchpad.interfaces.person import IPerson
from canonical.launchpad.interfaces.product import IProduct
from canonical.launchpad.mailout.branch import RecipientReason
from canonical.launchpad.validators.person import validate_public_person
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, MASTER_FLAVOR)


VALID_TRANSITION_GRAPH = {
    # It is valid to transition to any state from work in progress or needs
    # review, although additional user checks are requried.
    BranchMergeProposalStatus.WORK_IN_PROGRESS:
        BranchMergeProposalStatus.items,
    BranchMergeProposalStatus.NEEDS_REVIEW:
        BranchMergeProposalStatus.items,
    # If the proposal has been approved, any transition is valid.
    BranchMergeProposalStatus.CODE_APPROVED: BranchMergeProposalStatus.items,
    # Rejected is mostly terminal, can only resubmitted.
    BranchMergeProposalStatus.REJECTED: [
        BranchMergeProposalStatus.SUPERSEDED,
        ],
    # Merged is truly terminal, so nothing is valid.
    BranchMergeProposalStatus.MERGED: [],
    # It is valid to transition to any state from merge failed, although
    # additional user checks are requried.
    BranchMergeProposalStatus.MERGE_FAILED:
        BranchMergeProposalStatus.items,
    # Queued can only be transitioned to merged or merge failed.
    # Dequeing is a special case.
    BranchMergeProposalStatus.QUEUED: [
        BranchMergeProposalStatus.MERGED,
        BranchMergeProposalStatus.MERGE_FAILED,
        ],
    # Superseded is truly terminal, so nothing is valid.
    BranchMergeProposalStatus.SUPERSEDED: [],
    }


def is_valid_transition(proposal, from_state, next_state, user=None):
    """Is it valid for the proposal to move to next_state from from_state?"""
    # Trivial acceptance case.
    if from_state == next_state:
        return True

    [wip, needs_review, code_approved, rejected,
     merged, merge_failed, queued, superseded
     ] = BranchMergeProposalStatus.items
    # Transitioning to code approved, rejected or queued from
    # work in progress, needs review or merge failed needs the
    # user to be a valid reviewer, other states are fine.
    valid_reviewer = proposal.isPersonValidReviewer(user)
    if (next_state == rejected and not valid_reviewer):
        return False
    elif (next_state in (code_approved, queued) and
          from_state in (wip, needs_review, merge_failed)
          and not valid_reviewer):
        return False

    return next_state in VALID_TRANSITION_GRAPH[from_state]


class BranchMergeProposal(SQLBase):
    """A relationship between a person and a branch."""

    implements(IBranchMergeProposal, IBranchNavigationMenu)

    _table = 'BranchMergeProposal'
    _defaultOrder = ['-date_created', 'id']

    registrant = ForeignKey(
        dbName='registrant', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)

    source_branch = ForeignKey(
        dbName='source_branch', foreignKey='Branch', notNull=True)

    target_branch = ForeignKey(
        dbName='target_branch', foreignKey='Branch', notNull=True)

    dependent_branch = ForeignKey(
        dbName='dependent_branch', foreignKey='Branch', notNull=False)

    whiteboard = StringCol(default=None)

    queue_status = EnumCol(
        enum=BranchMergeProposalStatus, notNull=True,
        default=BranchMergeProposalStatus.WORK_IN_PROGRESS)

    reviewer = ForeignKey(
        dbName='reviewer', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False,
        default=None)

    review_diff = ForeignKey(
        foreignKey='StaticDiff', notNull=False, default=None)

    preview_diff_id = Int(name='merge_diff')
    preview_diff = Reference(preview_diff_id, 'PreviewDiff.id')

    reviewed_revision_id = StringCol(default=None)

    commit_message = StringCol(default=None)

    queue_position = IntCol(default=None)

    queuer = ForeignKey(
        dbName='queuer', foreignKey='Person', notNull=False,
        default=None)
    queued_revision_id = StringCol(default=None)

    date_merged = UtcDateTimeCol(default=None)
    merged_revno = IntCol(default=None)

    merge_reporter = ForeignKey(
        dbName='merge_reporter', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False,
        default=None)

    @property
    def address(self):
        return 'mp+%d@%s' % (self.id, config.launchpad.code_domain)

    superseded_by = ForeignKey(
        dbName='superseded_by', foreignKey='BranchMergeProposal',
        notNull=False, default=None)

    supersedes = Reference("<primary key>", "superseded_by", on_remote=True)

    date_created = UtcDateTimeCol(notNull=True, default=DEFAULT)
    date_review_requested = UtcDateTimeCol(notNull=False, default=None)
    date_reviewed = UtcDateTimeCol(notNull=False, default=None)

    @property
    def root_comment(self):
        return CodeReviewComment.selectOne("""
            CodeReviewMessage.id in (
                SELECT CodeReviewMessage.id
                    FROM CodeReviewMessage, Message
                    WHERE CodeReviewMessage.branch_merge_proposal = %d AND
                          CodeReviewMessage.message = Message.id
                    ORDER BY Message.datecreated LIMIT 1)
            """ % self.id)

    root_message_id = StringCol(default=None)

    @property
    def title(self):
        """See `IBranchMergeProposal`."""
        return "[Merge] %(source)s into %(target)s" % {
            'source': self.source_branch.bzr_identity,
            'target': self.target_branch.bzr_identity}

    @property
    def all_comments(self):
        """See `IBranchMergeProposal`."""
        return CodeReviewComment.selectBy(branch_merge_proposal=self.id)

    def getComment(self, id):
        """See `IBranchMergeProposal`.

        This function can raise WrongBranchMergeProposal."""
        comment = CodeReviewComment.get(id)
        if comment.branch_merge_proposal != self:
            raise WrongBranchMergeProposal
        return comment

    def getVoteReference(self, id):
        """See `IBranchMergeProposal`.

        This function can raise WrongBranchMergeProposal."""
        vote = CodeReviewVoteReference.get(id)
        if vote.branch_merge_proposal != self:
            raise WrongBranchMergeProposal
        return vote

    date_queued = UtcDateTimeCol(notNull=False, default=None)

    votes = SQLMultipleJoin(
        'CodeReviewVoteReference', joinColumn='branch_merge_proposal')

    def getNotificationRecipients(self, min_level):
        """See IBranchMergeProposal.getNotificationRecipients"""
        recipients = {}
        branch_identity_cache = {
            self.source_branch: self.source_branch.bzr_identity,
            self.target_branch: self.target_branch.bzr_identity,
            }
        branches = [self.source_branch, self.target_branch]
        if self.dependent_branch is not None:
            branches.append(self.dependent_branch)
        for branch in branches:
            branch_recipients = branch.getNotificationRecipients()
            for recipient in branch_recipients:
                subscription, rationale = branch_recipients.getReason(
                    recipient)
                if (subscription.review_level < min_level):
                    continue
                recipients[recipient] = RecipientReason.forBranchSubscriber(
                    subscription, recipient, rationale, self,
                    branch_identity_cache=branch_identity_cache)
        # Add in all the individuals that have been asked for a review,
        # or who have reviewed.  These people get added to the recipients
        # with the rationale of "Reviewer".
        # Don't add a team reviewer to the recipients as they are only going
        # to get emails normally if they are subscribed to one of the
        # branches, and if they are subscribed, they'll be getting this email
        # aleady.
        for review in self.votes:
            reviewer = review.reviewer
            if not reviewer.is_team:
                recipients[reviewer] = RecipientReason.forReviewer(
                    review, reviewer,
                    branch_identity_cache=branch_identity_cache)

        return recipients

    def isValidTransition(self, next_state, user=None):
        """See `IBranchMergeProposal`."""
        return is_valid_transition(self, self.queue_status, next_state, user)

    def _transitionToState(self, next_state, user=None):
        """Update the queue_status of the proposal.

        Raise an error if the proposal is in a final state.
        """
        if not self.isValidTransition(next_state, user):
            raise BadStateTransition(
                'Invalid state transition for merge proposal: %s -> %s'
                % (self.queue_status.title, next_state.title))
        # Transition to the same state occur in two particular
        # situations:
        #  * stale posts
        #  * approving a later revision
        # In both these cases, there is no real reason to disallow
        # transitioning to the same state.
        self.queue_status = next_state

    def setAsWorkInProgress(self):
        """See `IBranchMergeProposal`."""
        self._transitionToState(BranchMergeProposalStatus.WORK_IN_PROGRESS)
        self.date_review_requested = None
        self.reviewer = None
        self.date_reviewed = None
        self.reviewed_revision_id = None

    def requestReview(self):
        """See `IBranchMergeProposal`."""
        # Don't reset the date_review_requested if we are already in the
        # review state.
        if self.queue_status != BranchMergeProposalStatus.NEEDS_REVIEW:
            self._transitionToState(BranchMergeProposalStatus.NEEDS_REVIEW)
            self.date_review_requested = UTC_NOW

    def isPersonValidReviewer(self, reviewer):
        """See `IBranchMergeProposal`."""
        if reviewer is None:
            return False
        # We trust Launchpad admins.
        lp_admins = getUtility(ILaunchpadCelebrities).admin
        return (reviewer.inTeam(self.target_branch.code_reviewer) or
                reviewer.inTeam(lp_admins))

    def isMergable(self):
        """See `IBranchMergeProposal`."""
        # As long as the source branch has not been merged, rejected
        # or superseded, then it is valid to be merged.
        return (self.queue_status not in
                BRANCH_MERGE_PROPOSAL_FINAL_STATES)

    def _reviewProposal(self, reviewer, next_state, revision_id):
        """Set the proposal to one of the two review statuses."""
        # Check the reviewer can review the code for the target branch.
        old_state = self.queue_status
        if not self.isPersonValidReviewer(reviewer):
            raise UserNotBranchReviewer
        # Check the current state of the proposal.
        self._transitionToState(next_state, reviewer)
        # Record the reviewer
        self.reviewer = reviewer
        self.date_reviewed = UTC_NOW
        # Record the reviewed revision id
        self.reviewed_revision_id = revision_id
        notify(BranchMergeProposalStatusChangeEvent(
                self, reviewer, old_state, next_state))

    def approveBranch(self, reviewer, revision_id):
        """See `IBranchMergeProposal`."""
        self._reviewProposal(
            reviewer, BranchMergeProposalStatus.CODE_APPROVED, revision_id)

    def rejectBranch(self, reviewer, revision_id):
        """See `IBranchMergeProposal`."""
        self._reviewProposal(
            reviewer, BranchMergeProposalStatus.REJECTED, revision_id)

    def enqueue(self, queuer, revision_id):
        """See `IBranchMergeProposal`."""
        if self.queue_status != BranchMergeProposalStatus.CODE_APPROVED:
            self.approveBranch(queuer, revision_id)

        last_entry = BranchMergeProposal.selectOne("""
            BranchMergeProposal.queue_position = (
                SELECT coalesce(MAX(queue_position), 0)
                FROM BranchMergeProposal)
            """)

        # The queue_position will wrap if we ever get to
        # two billion queue entries where the queue has
        # never become empty.  Perhaps sometime in the future
        # we may want to (maybe) consider keeping track of
        # the maximum value here.  I doubt that it'll ever be
        # a problem -- thumper.
        if last_entry is None:
            position = 1
        else:
            position = last_entry.queue_position + 1

        self.queue_status = BranchMergeProposalStatus.QUEUED
        self.queue_position = position
        self.queuer = queuer
        self.queued_revision_id = revision_id
        self.date_queued = UTC_NOW
        self.syncUpdate()

    def dequeue(self):
        """See `IBranchMergeProposal`."""
        if self.queue_status != BranchMergeProposalStatus.QUEUED:
            raise BadStateTransition(
                'Invalid state transition for merge proposal: %s -> %s'
                % (self.queue_state.title,
                   BranchMergeProposalStatus.QUEUED.title))
        self.queue_status = BranchMergeProposalStatus.CODE_APPROVED
        # Clear out the queued values.
        self.queuer = None
        self.queued_revision_id = None
        self.date_queued = None
        # Remove from the queue.
        self.queue_position = None

    def moveToFrontOfQueue(self):
        """See `IBranchMergeProposal`."""
        if self.queue_status != BranchMergeProposalStatus.QUEUED:
            return
        first_entry = BranchMergeProposal.selectOne("""
            BranchMergeProposal.queue_position = (
                SELECT MIN(queue_position)
                FROM BranchMergeProposal)
            """)

        self.queue_position = first_entry.queue_position - 1
        self.syncUpdate()

    def mergeFailed(self, merger):
        """See `IBranchMergeProposal`."""
        self._transitionToState(
            BranchMergeProposalStatus.MERGE_FAILED, merger)
        self.merger = merger
        # Remove from the queue.
        self.queue_position = None

    def markAsMerged(self, merged_revno=None, date_merged=None,
                     merge_reporter=None):
        """See `IBranchMergeProposal`."""
        self._transitionToState(
            BranchMergeProposalStatus.MERGED, merge_reporter)
        self.merged_revno = merged_revno
        self.merge_reporter = merge_reporter
        # Remove from the queue.
        self.queue_position = None

        if merged_revno is not None:
            branch_revision = BranchRevision.selectOneBy(
                branch=self.target_branch, sequence=merged_revno)
            if branch_revision is not None:
                date_merged = branch_revision.revision.revision_date

        if date_merged is None:
            date_merged = UTC_NOW
        self.date_merged = date_merged

    def resubmit(self, registrant):
        """See `IBranchMergeProposal`."""
        # You can transition from REJECTED to SUPERSEDED, but
        # not from MERGED or SUPERSEDED.
        self._transitionToState(
            BranchMergeProposalStatus.SUPERSEDED, registrant)
        # This sync update is needed as the add landing target does
        # a database query to identify if there are any active proposals
        # with the same source and target branches.
        self.syncUpdate()
        proposal = self.source_branch.addLandingTarget(
            registrant=registrant,
            target_branch=self.target_branch,
            dependent_branch=self.dependent_branch,
            whiteboard=self.whiteboard,
            needs_review=True)
        self.superseded_by = proposal
        # This sync update is needed to ensure that the transitive
        # properties of supersedes and superseded_by are visible to
        # the old and the new proposal.
        self.syncUpdate()
        return proposal

    def nominateReviewer(self, reviewer, registrant, review_type=None,
                         _date_created=DEFAULT, _notify_listeners=True):
        """See `IBranchMergeProposal`."""
        # Return the existing vote reference or create a new one.
        # Lower case the review type.
        if review_type is not None:
            review_type = review_type.lower()
        vote_reference = self.getUsersVoteReference(reviewer, review_type)
        if vote_reference is None:
            vote_reference = CodeReviewVoteReference(
                branch_merge_proposal=self,
                registrant=registrant,
                reviewer=reviewer,
                date_created=_date_created)
        vote_reference.review_type = review_type
        if _notify_listeners:
            notify(ReviewerNominatedEvent(vote_reference))
        return vote_reference

    def deleteProposal(self):
        """See `IBranchMergeProposal`."""
        # Delete this proposal, but keep the superseded chain linked.
        if self.supersedes is not None:
            self.supersedes.superseded_by = self.superseded_by
        # Delete the related CodeReviewVoteReferences.
        for vote in self.votes:
            vote.destroySelf()
        # Delete the related CodeReviewComments.
        for comment in self.all_comments:
            comment.destroySelf()
        self.destroySelf()

    def getUnlandedSourceBranchRevisions(self):
        """See `IBranchMergeProposal`."""
        return BranchRevision.select('''
            BranchRevision.branch = %s AND
            BranchRevision.sequence IS NOT NULL AND
            BranchRevision.revision NOT IN (
              SELECT revision FROM BranchRevision
              WHERE branch = %s)
            ''' % sqlvalues(self.source_branch, self.target_branch),
            prejoins=['revision'], orderBy='-sequence', limit=10)

    def createComment(self, owner, subject, content=None, vote=None,
                      review_type=None, parent=None, _date_created=DEFAULT,
                      _notify_listeners=True):
        """See `IBranchMergeProposal`."""
        #:param _date_created: The date the message was created.  Provided
        #    only for testing purposes, as it can break
        # BranchMergeProposal.root_message.
        assert owner is not None, 'Merge proposal messages need a sender'
        parent_message = None
        if parent is not None:
            assert parent.branch_merge_proposal == self, \
                    'Replies must use the same merge proposal as their parent'
            parent_message = parent.message
        if not subject:
            # Get the subject from the parent if there is one, or use a nice
            # default.
            if parent is None:
                subject = self.title
            else:
                subject = parent.message.subject
            if not subject.startswith('Re: '):
                subject = 'Re: ' + subject

        msgid = make_msgid('codereview')
        message = Message(
            parent=parent_message, owner=owner, rfc822msgid=msgid,
            subject=subject, datecreated=_date_created)
        chunk = MessageChunk(message=message, content=content, sequence=1)
        return self.createCommentFromMessage(
            message, vote, review_type, _notify_listeners=_notify_listeners)

    def getUsersVoteReference(self, user, review_type=None):
        """Get the existing vote reference for the given user."""
        # Lower case the review type.
        if review_type is not None:
            review_type = review_type.lower()
        if user is None:
            return None
        if user.is_team:
            query = And(CodeReviewVoteReference.reviewer == user,
                        CodeReviewVoteReference.review_type == review_type)
        else:
            query = CodeReviewVoteReference.reviewer == user
        return Store.of(self).find(
            CodeReviewVoteReference,
            CodeReviewVoteReference.branch_merge_proposal == self,
            query).one()

    def _getTeamVoteReference(self, user, review_type):
        """Get a vote reference where the user is in the review team.

        Only return those reviews where the review_type matches.
        """
        refs = Store.of(self).find(
            CodeReviewVoteReference,
            CodeReviewVoteReference.branch_merge_proposal == self,
            CodeReviewVoteReference.review_type == review_type,
            CodeReviewVoteReference.comment == None)
        for ref in refs:
            if user.inTeam(ref.reviewer):
                return ref
        return None

    def _getVoteReference(self, user, review_type):
        """Get the vote reference for the user.

        The returned vote reference will either:
          * the existing vote reference for the user
          * a vote reference of the same type that has been requested of a
            team that the user is a member of
          * a new vote reference for the user
        """
        # Firstly look for a vote reference for the user.
        ref = self.getUsersVoteReference(user)
        if ref is not None:
            return ref
        # Get all the unclaimed CodeReviewVoteReferences with the review_type
        # specified.
        team_ref = self._getTeamVoteReference(user, review_type)
        if team_ref is not None:
            return team_ref
        # If the review_type is not None, check to see if there is an
        # outstanding team review requested with no specified type.
        if review_type is not None:
            team_ref = self._getTeamVoteReference(user, None)
            if team_ref is not None:
                return team_ref
        # Create a new reference.
        return CodeReviewVoteReference(
            branch_merge_proposal=self,
            registrant=user,
            reviewer=user,
            review_type=review_type)

    def createCommentFromMessage(self, message, vote, review_type,
                                 original_email=None, _notify_listeners=True):
        """See `IBranchMergeProposal`."""
        # Lower case the review type.
        if review_type is not None:
            review_type = review_type.lower()
        code_review_message = CodeReviewComment(
            branch_merge_proposal=self, message=message, vote=vote,
            vote_tag=review_type)
        # Get the appropriate CodeReviewVoteReference for the reviewer.
        # If there isn't one, then create one, otherwise set the comment
        # reference.
        if vote is not None:
            vote_reference = self._getVoteReference(
                message.owner, review_type)
            # Just set the reviewer and review type again on the off chance
            # that the user has edited the review_type or claimed a team
            # review.
            vote_reference.reviewer = message.owner
            vote_reference.review_type = review_type
            vote_reference.comment = code_review_message
        if _notify_listeners:
            notify(NewCodeReviewCommentEvent(
                    code_review_message, original_email))
        return code_review_message

    def updatePreviewDiff(self, diff_content, diff_stat,
                          source_revision_id, target_revision_id,
                          dependent_revision_id=None, conflicts=None):
        """See `IBranchMergeProposal`."""
        if self.preview_diff is None:
            # Create the PreviewDiff.
            preview = PreviewDiff()
            preview.diff = Diff()
            self.preview_diff = preview

        self.preview_diff.update(
            diff_content, diff_stat, source_revision_id, target_revision_id,
            dependent_revision_id, conflicts)
        return self.preview_diff


class BranchMergeProposalGetter:
    """See `IBranchMergeProposalGetter`."""

    implements(IBranchMergeProposalGetter)

    @staticmethod
    def get(id):
        """See `IBranchMergeProposalGetter`."""
        return BranchMergeProposal.get(id)

    @staticmethod
    def getProposalsForContext(context, status=None, visible_by_user=None):
        """See `IBranchMergeProposalGetter`."""
        collection = getUtility(IAllBranches).visibleByUser(visible_by_user)
        if context is None:
            pass
        elif IProduct.providedBy(context):
            collection = collection.inProduct(context)
        elif IPerson.providedBy(context):
            collection = collection.ownedBy(context)
        else:
            raise BadBranchMergeProposalSearchContext(context)
        return collection.getMergeProposals(status)

    @staticmethod
    def getProposalsForReviewer(reviewer, status=None, visible_by_user=None):
        """See `IBranchMergeProposalGetter`."""
        # XXX: This doesn't actually use visible_by_user!
        store = Store.of(reviewer)
        tables = [
            BranchMergeProposal,
            Join(CodeReviewVoteReference,
                 CodeReviewVoteReference.branch_merge_proposalID == \
                 BranchMergeProposal.id),
            LeftJoin(CodeReviewComment,
                 CodeReviewVoteReference.commentID == CodeReviewComment.id)]
        result = store.using(*tables).find(
            BranchMergeProposal,
            BranchMergeProposal.queue_status.is_in(status),
            CodeReviewVoteReference.reviewer == reviewer)
        result.order_by(Desc(CodeReviewComment.vote))

        return result

    @staticmethod
    def getVotesForProposals(proposals):
        """See `IBranchMergeProposalGetter`."""
        if len(proposals) == 0:
            return {}
        ids = [proposal.id for proposal in proposals]
        store = Store.of(proposals[0])
        result = dict([(proposal, []) for proposal in proposals])
        # Make sure that the Person and the review comment are loaded in the
        # storm cache as the reviewer is displayed in a title attribute on the
        # merge proposal listings page, and the message is needed to get to
        # the actual vote for that person.
        tables = [
            CodeReviewVoteReference,
            Join(Person, CodeReviewVoteReference.reviewerID == Person.id),
            LeftJoin(
                CodeReviewComment,
                CodeReviewVoteReference.commentID == CodeReviewComment.id)]
        results = store.using(*tables).find(
            (CodeReviewVoteReference, Person, CodeReviewComment),
            CodeReviewVoteReference.branch_merge_proposalID.is_in(ids))
        for reference, person, comment in results:
            result[reference.branch_merge_proposal].append(reference)
        return result

    @staticmethod
    def getVoteSummariesForProposals(proposals):
        """See `IBranchMergeProposalGetter`."""
        if len(proposals) == 0:
            return {}
        ids = quote([proposal.id for proposal in proposals])
        store = Store.of(proposals[0])
        # First get the count of comments.
        query = """
            SELECT bmp.id, count(crm.*)
            FROM BranchMergeProposal bmp, CodeReviewMessage crm,
                 Message m, MessageChunk mc
            WHERE bmp.id IN %s
              AND bmp.id = crm.branch_merge_proposal
              AND crm.message = m.id
              AND mc.message = m.id
              AND mc.content is not NULL
            GROUP BY bmp.id
            """ % ids
        comment_counts = dict(store.execute(query))
        # Now get the vote counts.
        query = """
            SELECT bmp.id, crm.vote, count(crv.*)
            FROM BranchMergeProposal bmp, CodeReviewVote crv,
                 CodeReviewMessage crm
            WHERE bmp.id IN %s
              AND bmp.id = crv.branch_merge_proposal
              AND crv.vote_message = crm.id
            GROUP BY bmp.id, crm.vote
            """ % ids
        vote_counts = {}
        for proposal_id, vote_value, count in store.execute(query):
            vote = CodeReviewVote.items[vote_value]
            vote_counts.setdefault(proposal_id, {})[vote] = count
        # Now assemble the resulting dict.
        result = {}
        for proposal in proposals:
            summary = result.setdefault(proposal, {})
            summary['comment_count'] = (
                comment_counts.get(proposal.id, 0))
            summary.update(vote_counts.get(proposal.id, {}))
        return result


class CreateMergeProposalJob(object):
    """See `ICreateMergeProposalJob` and `ICreateMergeProposalJobSource`."""

    classProvides(ICreateMergeProposalJobSource)

    delegates(IMessageJob)

    class_action = MessageJobAction.CREATE_MERGE_PROPOSAL

    implements(ICreateMergeProposalJob)

    def __init__(self, context):
        """Create an instance of CreateMergeProposalJob.

        :param context: a MessageJob.
        """
        self.context = context

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.context == other.context)

    @classmethod
    def create(klass, message_bytes):
        """See `ICreateMergeProposalJobSource`."""
        context = MessageJob(
            message_bytes, MessageJobAction.CREATE_MERGE_PROPOSAL)
        return klass(context)

    @classmethod
    def iterReady(klass):
        """Iterate through all ready BranchMergeProposalJobs."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)
        jobs = store.find(
            (MessageJob),
            And(MessageJob.action == klass.class_action,
                MessageJob.job == Job.id,
                Job.id.is_in(Job.ready_jobs)))
        return (klass(job) for job in jobs)

    def run(self):
        """See `ICreateMergeProposalJob`."""
        # Avoid circular import
        from canonical.launchpad.mail.codehandler import CodeHandler
        from canonical.launchpad.mail.incoming import authenticateEmail
        message = self.getMessage()
        authenticateEmail(message)
        return CodeHandler().processMergeProposal(message)
