# Copyright 2008 Canonical Ltd.  All rights reserved.

"""CodeReviewVoteReference interface."""

__metaclass__ = type
__all__ = [
    'ICodeReviewVoteReference',
    ]

from zope.interface import Interface
from zope.schema import Datetime, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice
from canonical.launchpad.interfaces.branchmergeproposal import (
    IBranchMergeProposal)
from canonical.launchpad.interfaces.codereviewcomment import (
    ICodeReviewComment)
from canonical.launchpad.interfaces.person import IPerson
from canonical.lazr.fields import Reference
from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, exported)


class ICodeReviewVoteReference(Interface):
    """A reference to a vote on a IBranchMergeProposal.

    There is at most one reference to a vote for each reviewer on a given
    branch merge proposal.
    """
    export_as_webservice_entry()

    branch_merge_proposal = exported(
        Reference(
            title=_("The merge proposal that is the subject of this vote"),
            required=True, schema=IBranchMergeProposal))

    date_created = exported(
        Datetime(
            title=_('Date Created'), required=True, readonly=True))

    registrant = exported(
        Reference(
            title=_("The person who originally registered this vote"),
            required=True, schema=IPerson))

    reviewer = exported(
        PublicPersonChoice(
            title=_('Reviewer'), required=True,
            description=_('A person who you want to review this.'),
            vocabulary='ValidPersonOrTeam'))

    review_type = exported(
        TextLine(
            title=_('Review type'), required=False,
            description=_(
                "Lowercase keywords describing the type of review you're "
                "performing.")))

    comment = exported(
        Reference(
            title=_(
                "The code review comment that contains the most recent vote."
                ),
            required=True, schema=ICodeReviewComment))
