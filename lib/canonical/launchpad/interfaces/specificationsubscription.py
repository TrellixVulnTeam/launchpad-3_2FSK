# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Specification subscription interfaces."""

__metaclass__ = type

__all__ = [
    'ISpecificationSubscription',
    ]

from zope.interface import Interface
from zope.schema import Choice, Int, Bool
from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice

class ISpecificationSubscription(Interface):
    """A subscription for a person to a specification."""

    id = Int(
        title=_('ID'), required=True, readonly=True)
    person = PublicPersonChoice(
            title=_('Subscriber'), required=True,
            vocabulary='ValidPersonOrTeam', readonly=True,
            description=_(
            'The person you would like to subscribe to this blueprint. '
            'They will be notified of the subscription by e-mail, if they '
            'have an active Launchpad account.')
            )
    specification = Int(title=_('Specification'), required=True,
        readonly=True)
    essential = Bool(title=_('Participation essential'), required=True,
        description=_('Check this if participation in the design and '
        'discussion of the feature is essential. This will '
        'cause the meeting scheduler to try to ensure that this person '
        'attends meetings about this feature.'),
        default=False)

