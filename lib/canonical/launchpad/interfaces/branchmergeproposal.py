# Copyright 2007 Canonical Ltd.  All rights reserved.

"""The interface for branch merge proposals."""

__metaclass__ = type
__all__ = [
    'InvalidBranchMergeProposal',
    'IBranchMergeProposal',
    ]

from zope.interface import Interface
from zope.schema import Choice, Datetime, Int

from canonical.launchpad import _

from canonical.launchpad.fields import Whiteboard


class InvalidBranchMergeProposal(Exception):
    """Raised during the creation of a new branch merge proposal.

    The text of the exception is the rule violation.
    """


class IBranchMergeProposal(Interface):
    """Branch merge proposals show intent of landing one branch on another."""

    id = Int(
        title=_('DB ID'), required=True, readonly=True,
        description=_("The tracking number for this question."))

    registrant = Choice(
        title=_('Person'), required=True,
        vocabulary='ValidPersonOrTeam', readonly=True,
        description=_('The person who registered the landing target.'))

    source_branch = Choice(
        title=_('Source Branch'),
        vocabulary='Branch', required=True, readonly=True,
        description=_("The Bazaar branch that has code to land."))

    target_branch = Choice(
        title=_('Target Branch'),
        vocabulary='Branch', required=True, readonly=True,
        description=_("The branch that the source branch will be merged into."))

    dependent_branch = Choice(
        title=_('Dependent Branch'),
        vocabulary='Branch', required=False, readonly=True,
        description=_("The Bazaar branch that the source branch branched from."))

    whiteboard = Whiteboard(
        title=_('Whiteboard'), required=False,
        description=_('Notes about the merge.'))

    date_created = Datetime(
        title=_('Date Created'), required=True, readonly=True)
