# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Helper functions/classes to be used when testing the karma framework."""

__metaclass__ = type

from canonical.launchpad.ftests.event import TestEventListener
from canonical.launchpad.event.interfaces import IKarmaAssignedEvent
from canonical.launchpad.interfaces import IPerson


class KarmaAssignedEventListener:
    """Test helper class that registers a listener printing information
    whenever Karma is assigned.

    No karma assignments will be printed until the register_listener()
    method is called. 

    Each time Karma is assigned to a Person, a line in the following format
    will be printed:

        Karma added: action=<action>, [product|distribution]=<contextname>

    A set of KarmaAction objects assigned since the register_listener()
    method was called is available in the added_listener_actions property.
    """

    def __init__(self):
        self.added_karma_actions = set()

    def _on_assigned_event(self, object, event):
        action = event.karma.action
        self.added_karma_actions.add(action)
        text = "Karma added: action=%s," % action.name
        if event.karma.product is not None:
            text += " product=%s" % event.karma.product.name
        elif event.karma.distribution is not None:
            text += " distribution=%s" % event.karma.distribution.name
        print text

    def register_listener(self):
        self.listener = TestEventListener(
            IPerson, IKarmaAssignedEvent, self._on_assigned_event)

    def unregister_listener(self):
        self.listener.unregister()

