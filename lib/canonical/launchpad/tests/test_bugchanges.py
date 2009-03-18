# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Tests for recording changes done to a bug."""

import unittest

from zope.event import notify

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot

from canonical.launchpad.database import BugNotification
from canonical.launchpad.interfaces.bug import IBug
from canonical.launchpad.ftests import login, logout
from canonical.launchpad.testing.factory import LaunchpadObjectFactory
from canonical.testing import DatabaseFunctionalLayer


class TestBugChanges(unittest.TestCase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        login('foo.bar@canonical.com')
        self.factory = LaunchpadObjectFactory()
        self.user = self.factory.makePerson(displayname='Arthur Dent')
        self.bug = self.factory.makeBug(owner=self.user)
        self.saveOldChanges()

    def saveOldChanges(self):
        """Save the old changes to the bug.

        This method should be called after all the setup is done.
        """
        self.old_activities = list(self.bug.activity)
        self.old_notification_ids = [
            notification.id
            for notification in BugNotification.selectBy(bug=self.bug)]

    def changeAttribute(self, obj, attribute, new_value):
        """Set the value of `attribute` on `obj` to `new_value`.

        :return: The value of `attribute` before modification.
        """
        obj_before_modification = Snapshot(obj, providing=IBug)
        setattr(obj, attribute, new_value)
        notify(ObjectModifiedEvent(
            obj, obj_before_modification, [attribute], self.user))

        return getattr(obj_before_modification, attribute)

    def assertRecordedChange(self, expected_activity=None,
                             expected_notification=None, bug=None):
        """Assert that things were recorded as expected."""
        if bug is None:
            bug = self.bug

        new_activities = [
            activity for activity in bug.activity
            if activity not in self.old_activities]
        bug_notifications = BugNotification.selectBy(
            bug=bug, orderBy='id')
        new_notifications = [
            notification for notification in bug_notifications
            if notification.id not in self.old_notification_ids]
        if expected_activity is None:
            self.assertEqual(len(new_activities), 0)
        else:
            self.assertEqual(len(new_activities), 1)
            [added_activity] = new_activities
            self.assertEqual(
                added_activity.person, expected_activity['person'])
            self.assertEqual(
                added_activity.whatchanged, expected_activity['whatchanged'])
            self.assertEqual(
                added_activity.oldvalue, expected_activity.get('oldvalue'))
            self.assertEqual(
                added_activity.newvalue, expected_activity.get('newvalue'))
            self.assertEqual(
                added_activity.message, expected_activity.get('message'))

        if expected_notification is None:
            self.assertEqual(len(new_notifications), 0)
        else:
            self.assertEqual(len(new_notifications), 1)
            [added_notification] = new_notifications
            self.assertEqual(
                added_notification.message.text_contents,
                expected_notification['text'])
            self.assertEqual(
                added_notification.message.owner,
                expected_notification['person'])
            self.assertFalse(added_notification.is_comment)

    def test_subscribe(self):
        # Subscribing someone to a bug adds an item to the activity log,
        # but doesn't send an e-mail notification.
        subscriber = self.factory.makePerson(displayname='Mom')
        bug_subscription = self.bug.subscribe(self.user, subscriber)
        notify(ObjectCreatedEvent(bug_subscription, user=subscriber))
        subscribe_activity = dict(
            whatchanged='bug',
            message='added subscriber Arthur Dent',
            person=subscriber)
        self.assertRecordedChange(expected_activity=subscribe_activity)

    def test_unsubscribe(self):
        # Unsubscribing someone from a bug adds an item to the activity
        # log, but doesn't send an e-mail notification.
        subscriber = self.factory.makePerson(displayname='Mom')
        bug_subscription = self.bug.subscribe(self.user, subscriber)
        self.saveOldChanges()
        self.bug.unsubscribe(self.user, subscriber)
        unsubscribe_activity = dict(
            whatchanged='removed subscriber Arthur Dent',
            person=subscriber)
        self.assertRecordedChange(expected_activity=unsubscribe_activity)

    def test_title_changed(self):
        # Changing the title of a Bug adds items to the activity log and
        # the Bug's notifications.
        old_title = self.changeAttribute(self.bug, 'title', '42')

        title_change_activity = {
            'whatchanged': 'summary',
            'oldvalue': old_title,
            'newvalue': "42",
            'person': self.user,
            }

        title_change_notification = {
            'text': (
                "** Summary changed:\n\n"
                "- %s\n"
                "+ 42" % old_title),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=title_change_activity,
            expected_notification=title_change_notification)

    def test_description_changed(self):
        # Changing the description of a Bug adds items to the activity
        # log and the Bug's notifications.
        old_description = self.changeAttribute(
            self.bug, 'description', 'Hello, world')

        description_change_activity = {
            'person': self.user,
            'whatchanged': 'description',
            'oldvalue': old_description,
            'newvalue': 'Hello, world',
            }

        description_change_notification = {
            'text': (
                "** Description changed:\n\n"
                "- %s\n"
                "+ Hello, world" % old_description),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_notification=description_change_notification,
            expected_activity=description_change_activity)

    def test_make_private(self):
        # Marking a bug as private adds items to the bug's activity log
        # and notifications.
        bug_before_modification = Snapshot(self.bug, providing=IBug)
        self.bug.setPrivate(True, self.user)
        notify(ObjectModifiedEvent(
            self.bug, bug_before_modification, ['private'], self.user))

        visibility_change_activity = {
            'person': self.user,
            'whatchanged': 'visibility',
            'oldvalue': 'public',
            'newvalue': 'private',
            }

        visibility_change_notification = {
            'text': '** Visibility changed to: Private',
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=visibility_change_activity,
            expected_notification=visibility_change_notification)

    def test_make_public(self):
        # Marking a bug as public adds items to the bug's activity log
        # and notifications.
        private_bug = self.factory.makeBug(private=True)
        self.assertTrue(private_bug.private)

        bug_before_modification = Snapshot(private_bug, providing=IBug)
        private_bug.setPrivate(False, self.user)
        notify(ObjectModifiedEvent(
            private_bug, bug_before_modification, ['private'], self.user))

        visibility_change_activity = {
            'person': self.user,
            'whatchanged': 'visibility',
            'oldvalue': 'private',
            'newvalue': 'public',
            }

        visibility_change_notification = {
            'text': '** Visibility changed to: Public',
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=visibility_change_activity,
            expected_notification=visibility_change_notification,
            bug=private_bug)

    def test_mark_as_security_issue(self):
        # Marking a bug as a security vulnerability adds to the bug's
        # activity log and sends a notification.
        self.bug.security_related = False
        self.changeAttribute(self.bug, 'security_related', True)

        security_change_activity = {
            'person': self.user,
            'whatchanged': 'security issue',
            'oldvalue': 'no',
            'newvalue': 'yes',
            }

        security_change_notification = {
            'text': '** This bug has been flagged as a security issue',
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=security_change_activity,
            expected_notification=security_change_notification)

    def test_unmark_as_security_issue(self):
        # Unmarking a bug as a security vulnerability adds to the
        # bug's activity log and sends a notification.
        self.bug.security_related = True
        self.changeAttribute(self.bug, 'security_related', False)

        security_change_activity = {
            'person': self.user,
            'whatchanged': 'security issue',
            'oldvalue': 'yes',
            'newvalue': 'no',
            }

        security_change_notification = {
            'text': '** This bug is no longer flagged as a security issue',
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=security_change_activity,
            expected_notification=security_change_notification)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
