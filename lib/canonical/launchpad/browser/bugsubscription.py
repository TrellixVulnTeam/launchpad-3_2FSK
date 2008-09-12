# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Views for BugSubscription."""

__metaclass__ = type
__all__ = ['BugSubscriptionAddView']

from zope.event import notify

from canonical.launchpad.event import SQLObjectCreatedEvent
from canonical.launchpad.interfaces import IBugSubscription
from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadFormView)


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
        notify(SQLObjectCreatedEvent(subscription, user=self.user))
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
