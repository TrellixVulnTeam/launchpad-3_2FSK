# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views for BugSubscription."""

__metaclass__ = type
__all__ = [
    'BugPortletSubcribersContents',
    'BugSubscriptionAddView',
    ]

from zope.event import notify

from lazr.delegates import delegates
from lazr.lifecycle.event import ObjectCreatedEvent

from lp.bugs.browser.bug import BugViewMixin
from lp.bugs.interfaces.bugsubscription import IBugSubscription
from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadFormView, LaunchpadView)
from canonical.launchpad.webapp.authorization import check_permission


class BugSubscriptionAddView(LaunchpadFormView):
    """Browser view class for subscribing someone else to a bug."""

    schema = IBugSubscription

    field_names = ['person']

    def setUpFields(self):
        """Set up 'person' as an input field."""
        super(BugSubscriptionAddView, self).setUpFields()
        self.form_fields['person'].for_input = True

    @action('Add', name='add')
    def add_action(self, action, data):
        person = data['person']
        subscription = self.context.bug.subscribe(person, self.user)
        notify(ObjectCreatedEvent(subscription, user=self.user))
        if person.isTeam():
            message = '%s team has been subscribed to this bug.'
        else:
            message = '%s has been subscribed to this bug.'
        self.request.response.addInfoNotification(message %
                                                  person.displayname)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    @property
    def label(self):
        return 'Subscribe someone else to bug #%i' % self.context.bug.id

    page_title = label


class BugPortletSubcribersContents(LaunchpadView, BugViewMixin):
    """View for the contents for the subscribers portlet."""

    def getSortedDirectSubscriptions(self):
        """Get the list of direct subscriptions to the bug.

        The list is sorted such that subscriptions you can unsubscribe appear
        before all other subscriptions.
        """
        direct_subscriptions = [
            SubscriptionAttrDecorator(subscription)
            for subscription in self.context.getDirectSubscriptions()]
        can_unsubscribe = []
        cannot_unsubscribe = []
        for subscription in direct_subscriptions:
            if not check_permission('launchpad.View', subscription.person):
                continue
            if subscription.person == self.user:
                can_unsubscribe = [subscription] + can_unsubscribe
            elif subscription.canBeUnsubscribedByUser(self.user):
                can_unsubscribe.append(subscription)
            else:
                cannot_unsubscribe.append(subscription)
        return can_unsubscribe + cannot_unsubscribe

    def getSortedSubscriptionsFromDuplicates(self):
        """Get the list of subscriptions to duplicates of this bug."""
        return [
            SubscriptionAttrDecorator(subscription)
            for subscription in self.context.getSubscriptionsFromDuplicates()]


class SubscriptionAttrDecorator:
    """A BugSubscription with added attributes for HTML/JS."""
    delegates(IBugSubscription, 'subscription')

    def __init__(self, subscription):
        self.subscription = subscription

    @property
    def css_name(self):
        return 'subscriber-%s' % self.subscription.person.id
