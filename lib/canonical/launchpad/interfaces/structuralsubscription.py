# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0213

"""StructuralSubscription interfaces."""

__metaclass__ = type

__all__ = [
    'BlueprintNotificationLevel',
    'BugNotificationLevel',
    'DeleteSubscriptionError',
    'DuplicateSubscriptionError',
    'IStructuralSubscription',
    'IStructuralSubscriptionForm',
    'IStructuralSubscriptionTarget'
    ]

from zope.interface import Attribute, Interface
from zope.schema import Bool, Choice, Datetime, Int

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


class IStructuralSubscriptionTarget(Interface):
    """A Launchpad Structure allowing users to subscribe to it."""

    def getSubscriptions(min_bug_notification_level,
                         min_blueprint_notification_level):
        """Return all the subscriptions with the specified levels.

        :min_bug_notification_level: The lowest bug notification level
          for which subscriptions should be returned.
        :min_blueprint_notification_level: The lowest bleuprint
          notification level for which subscriptions should
          be returned.
        :return: A sequence of `IStructuralSubscription`.
        """

    def addSubscription(subscriber, subscribed_by):
        """Add a subscription for this structure.

        :subscriber: The IPerson who will be subscribed.
        :subscribed_by: The IPerson creating the subscription.
        :return: The new subscription.
        """

    def addBugSubscription(subscriber, subscribed_by):
        """Add a bug subscription for this structure.

        :subscriber: The IPerson who will be subscribed.
        :subscribed_by: The IPerson creating the subscription.
        :return: The new bug subscription.
        """

    def removeBugSubscription(subscriber):
        """Remove a subscription to bugs from this structure.

        If subscription levels for other applications are set,
        set the subscription's `bug_notification_level` to
        `NOTHING`, otherwise, destroy the subscription.

        :subscriber: The IPerson who will be subscribed.
        """

    def isSubscribed(person):
        """Is `person` already subscribed to this structure?

        If yes, the subscription is returned. Otherwise False is returned.
        """


class IStructuralSubscriptionForm(Interface):
    """Schema for the structural subscription form."""
    subscribe_me = Bool(
        title=u"I want to subscribe to notifications.",
        required=False)


class DuplicateSubscriptionError(Exception):
    """Duplicate Subscription Error.

    Raised when trying to add a structural subscription that already exists.
    """


class DeleteSubscriptionError(Exception):
    """Delete Subscription Error.

    Raised when an error occurred trying to delete a
    structural subscription."""
