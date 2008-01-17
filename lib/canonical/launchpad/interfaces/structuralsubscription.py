# Copyright 2008 Canonical Ltd.  All rights reserved.

"""StructuralSubscription interfaces."""

__metaclass__ = type

__all__ = [
    'BlueprintNotificationLevel',
    'BugNotificationLevel',
    'IStructuralSubscription'
    ]

from zope.interface import Attribute, Interface
from zope.schema import Int, Choice, Datetime

from canonical.launchpad import _

from canonical.lazr import DBEnumeratedType, DBItem

class BugNotificationLevel(DBEnumeratedType):
    """Bug Notification Level.

    The type and volume of bug notification email sent to subscribers.
    """

    NOTHING = DBItem(10, """
        Nothing

        Don't send any notifications about bugs.
        """)

    LIFECYCLE = DBItem(20, """
        Lifecycle

        Only send a low volume of notifications about new bugs registered, bugs removed or bug targetting.
        """)

    METADATA = DBItem(30, """
        Details

        Send bug lifecycle notifications, as well as notifications about changes to the bug's details like status and description.
        """)

    COMMENTS = DBItem(40, """
        Discussion

        Send bug lifecycle notifications, detail change notifications and notifications about new events in the bugs's discussion, like new comments.
        """)


class BlueprintNotificationLevel(DBEnumeratedType):
    """Bug Notification Level.

    The type and volume of blueprint notification email sent to subscribers.
    """

    NOTHING = DBItem(10, """
        Nothing

        Don't send any notifications about blueprints.
        """)

    LIFECYCLE = DBItem(20, """
        Lifecycle

        Only send a low volume of notifications about new blueprints registered, blueprints accepted or blueprint targetting.
        """)

    METADATA = DBItem(30, """
        Details

        Send blueprint lifecycle notifications, as well as notifications about changes to the blueprints's details like status and description.
        """)


class IStructuralSubscription(Interface):
    """A subscription to a Launchpad structure."""

    id = Int(title=_('ID'), readonly=True, required=True)
    product = Int(title=_('Product'), required=False, readonly=True)
    productseries = Int(
        title=_('Product series'), required=False, readonly=True)
    project = Int(title=_('Project'), required=False, readonly=True)
    milestone = Int(title=_('Milestone'), required=False, readonly=True)
    distribution = Int(title=_('Distribution'), required=False, readonly=True)
    distroseries = Int(
        title=_('Distribution series'), required=False, readonly=True)
    sourcepackagename = Int(
        title=_('Source package name'), required=False, readonly=True)
    subscriber = Choice(
        title=_('Subscriber'), required=True, vocabulary='ValidPersonOrTeam',
        readonly=True, description=_("The person subscribed."))
    subscribed_by = Choice(
        title=_('Subscribed by'), required=True,
        vocabulary='ValidPersonOrTeam', readonly=True,
        description=_("The person creating the subscription."))
    bug_notification_level = Choice(
        title=_("Bug notification level"), required=True,
        vocabulary=BugNotificationLevel,
        default=BugNotificationLevel.NOTHING,
        description=_("The volume and type of bug notifications "
                      "this subscription will generate."))
    blueprint_notification_level = Choice(
        title=_("Blueprint notification level"), required=True,
        vocabulary=BlueprintNotificationLevel,
        default=BlueprintNotificationLevel.NOTHING,
        description=_("The volume and type of blueprint notifications "
                      "this subscription will generate."))
    date_created = Datetime(
        title=_("The date on which this subscription was created."),
        required=False)
    date_last_updated = Datetime(
        title=_("The date on which this subscription was last updated."),
        required=False)

    target = Attribute("The structure to which this subscription belongs.")
