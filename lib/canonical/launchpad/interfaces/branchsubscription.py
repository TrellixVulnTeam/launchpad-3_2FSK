# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Bug subscription interfaces."""

__metaclass__ = type

__all__ = ['IBranchSubscription']

from zope.interface import Interface, Attribute
from zope.schema import Choice, Int
from canonical.launchpad import _

class IBranchSubscription(Interface):
    """The relationship between a person and a branch."""

    person = Choice(
        title=_('Person'), required=True, vocabulary='ValidPersonOrTeam',
        readonly=True, description=_('Enter the launchpad id, or email '
        'address of the person you wish to subscribe to this branch. '
        'If you are unsure, use the "Choose..." option to find the '
        'person in Launchpad. You can only subscribe someone who is '
        'a registered user of the system.'))
    branch = Int(title=_('Branch ID'), required=True, readonly=True)
