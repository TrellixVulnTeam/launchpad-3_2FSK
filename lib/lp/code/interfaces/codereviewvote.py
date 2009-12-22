# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""CodeReviewVoteReference interface."""

__metaclass__ = type
__all__ = [
    'ICodeReviewVoteReference',
    ]

from zope.interface import Interface
from zope.schema import Bool, Datetime, Int, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice
from lp.code.interfaces.branchmergeproposal import (
    IBranchMergeProposal)
from lp.code.interfaces.codereviewcomment import (
    ICodeReviewComment)
from lazr.restful.fields import Reference
from lazr.restful.declarations import (
    call_with, export_as_webservice_entry, export_destructor_operation,
    export_write_operation, exported, REQUEST_USER)


class ICodeReviewVoteReferencePublic(Interface):
    """The public attributes for code review vote references."""

    id = Int(
        title=_("The ID of the vote reference"))

    branch_merge_proposal = exported(
        Reference(
            title=_("The merge proposal that is the subject of this vote"),
            required=True, schema=IBranchMergeProposal))

    date_created = exported(
        Datetime(
            title=_('Date Created'), required=True, readonly=True))

    registrant = exported(
        PublicPersonChoice(
            title=_("The person who originally registered this vote"),
            required=True,
            vocabulary='ValidPersonOrTeam'))

    reviewer = exported(
        PublicPersonChoice(
            title=_('Reviewer'), required=True,
            description=_('A person who you want to review this.'),
            vocabulary='ValidPersonOrTeam'))

    review_type = exported(
        TextLine(
            title=_('Review type'), required=False,
            description=_(
                "Lowercase keywords describing the type of review.")))

    comment = exported(
        Reference(
            title=_(
                "The code review comment that contains the most recent vote."
                ),
            required=True, schema=ICodeReviewComment))

    is_pending = exported(
        Bool(title=_("Is the pending?"), required=True, readonly=True))


class ICodeReviewVoteReferenceEdit(Interface):
    """Method that require edit permissions."""

    @call_with(claimant=REQUEST_USER)
    @export_write_operation()
    def claimReview(claimant):
        """Change a pending review into a review for claimant.

        Pending team reviews can be claimed by members of that team.  This
        allows reviews to be moved of the general team todo list, and onto a
        personal todo list.

        :param claimant: The person claiming the team review.
        :raises ClaimReviewFailed: If the claimant already has a
            personal review, if the reviewer is not a team, if the
            claimant is not in the reviewer team, or if the review is
            not pending.
        """

    @export_destructor_operation()
    def delete():
        """Delete the pending review.

        :raises ReviewNotPending: If the review is not pending.
        """


class ICodeReviewVoteReference(ICodeReviewVoteReferencePublic,
                               ICodeReviewVoteReferenceEdit):
    """A reference to a vote on a IBranchMergeProposal.

    There is at most one reference to a vote for each reviewer on a given
    branch merge proposal.
    """

    export_as_webservice_entry()
