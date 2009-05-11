# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Tests for recording changes done to a bug."""

import unittest

from zope.component import getUtility
from zope.event import notify
from zope.interface import providedBy

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot

from canonical.launchpad.database import BugNotification
from canonical.launchpad.ftests import login
from canonical.launchpad.interfaces.bug import IBug
from canonical.launchpad.interfaces.cve import ICveSet
from canonical.launchpad.interfaces.bugtask import (
    BugTaskImportance, BugTaskStatus)
from canonical.launchpad.interfaces.structuralsubscription import (
    BugNotificationLevel)
from canonical.launchpad.testing.factory import LaunchpadObjectFactory
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.testing import LaunchpadFunctionalLayer


class TestBugChanges(unittest.TestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login('foo.bar@canonical.com')
        self.admin_user = getUtility(ILaunchBag).user
        self.factory = LaunchpadObjectFactory()
        self.user = self.factory.makePerson(displayname='Arthur Dent')
        self.product = self.factory.makeProduct(
            owner=self.user, official_malone=True)
        self.bug = self.factory.makeBug(product=self.product, owner=self.user)
        self.bug_task = self.bug.bugtasks[0]

        # Add some structural subscribers to show that notifications
        # aren't sent to LIFECYCLE subscribers by default.
        self.product_lifecycle_subscriber = self.newSubscriber(
            self.product, "product-lifecycle",
            BugNotificationLevel.LIFECYCLE)
        self.product_metadata_subscriber = self.newSubscriber(
            self.product, "product-metadata",
            BugNotificationLevel.METADATA)

        self.saveOldChanges()

    def newSubscriber(self, target, name, level):
        # Create a new bug subscription with a new person.
        subscriber = self.factory.makePerson(name=name)
        subscription = target.addBugSubscription(subscriber, subscriber)
        subscription.bug_notification_level = level
        return subscriber

    def saveOldChanges(self, bug=None):
        """Save the old changes to a bug.

        This method should be called after all the setup is done.
        """
        if bug is None:
            bug = self.bug
        self.old_activities = set(bug.activity)
        self.old_notification_ids = set(
            notification.id for notification in (
                BugNotification.selectBy(bug=bug)))

    def changeAttribute(self, obj, attribute, new_value):
        """Set the value of `attribute` on `obj` to `new_value`.

        :return: The value of `attribute` before modification.
        """
        obj_before_modification = Snapshot(obj, providing=providedBy(obj))
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
            if isinstance(expected_activity, dict):
                expected_activities = [expected_activity]
            else:
                expected_activities = expected_activity
            self.assertEqual(len(new_activities), len(expected_activities))
            for expected_activity in expected_activities:
                added_activity = new_activities.pop(0)
                self.assertEqual(
                    added_activity.person, expected_activity['person'])
                self.assertEqual(
                    added_activity.whatchanged,
                    expected_activity['whatchanged'])
                self.assertEqual(
                    added_activity.oldvalue,
                    expected_activity.get('oldvalue'))
                self.assertEqual(
                    added_activity.newvalue,
                    expected_activity.get('newvalue'))
                self.assertEqual(
                    added_activity.message, expected_activity.get('message'))

        if expected_notification is None:
            self.assertEqual(len(new_notifications), 0)
        else:
            if isinstance(expected_notification, dict):
                expected_notifications = [expected_notification]
            else:
                expected_notifications = expected_notification
            self.assertEqual(
                len(new_notifications), len(expected_notifications))
            for expected_notification in expected_notifications:
                added_notification = new_notifications.pop(0)
                self.assertEqual(
                    added_notification.message.text_contents,
                    expected_notification['text'])
                self.assertEqual(
                    added_notification.message.owner,
                    expected_notification['person'])
                self.assertEqual(
                    added_notification.is_comment,
                    expected_notification.get('is_comment', False))
                expected_recipients = expected_notification.get('recipients')
                if expected_recipients is None:
                    expected_recipients = bug.getBugNotificationRecipients(
                        level=BugNotificationLevel.METADATA)
                self.assertEqual(
                    set(recipient.person
                        for recipient in added_notification.recipients),
                    set(expected_recipients))

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

    def test_bugwatch_added(self):
        # Adding a BugWatch to a bug adds items to the activity
        # log and the Bug's notifications.
        bugtracker = self.factory.makeBugTracker()
        bug_watch = self.bug.addWatch(bugtracker, '42', self.user)

        bugwatch_activity = {
            'person': self.user,
            'whatchanged': 'bug watch added',
            'newvalue': bug_watch.url,
            }

        bugwatch_notification = {
            'text': (
                "** Bug watch added: %s #%s\n"
                "   %s" % (
                    bug_watch.bugtracker.title, bug_watch.remotebug,
                    bug_watch.url)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_notification=bugwatch_notification,
            expected_activity=bugwatch_activity)

    def test_bugwatch_added_from_comment(self):
        # Adding a bug comment containing a URL that looks like a link
        # to a remote bug causes a BugWatch to be added to the
        # bug. This adds to the activity log and sends a notification.
        self.assertEqual(self.bug.watches.count(), 0)
        self.bug.newMessage(
            content="http://bugs.example.com/view.php?id=1234",
            owner=self.user)
        self.assertEqual(self.bug.watches.count(), 1)
        [bug_watch] = self.bug.watches

        bugwatch_activity = {
            'person': self.user,
            'whatchanged': 'bug watch added',
            'newvalue': bug_watch.url,
            }

        bugwatch_notification = {
            'text': (
                "** Bug watch added: %s #%s\n"
                "   %s" % (
                    bug_watch.bugtracker.title, bug_watch.remotebug,
                    bug_watch.url)),
            'person': self.user,
            'recipients': [
                self.user, self.product_metadata_subscriber],
            }

        comment_notification = {
            'text': "http://bugs.example.com/view.php?id=1234",
            'person': self.user,
            'is_comment': True,
            'recipients': [self.user],
            }

        self.assertRecordedChange(
            expected_activity=bugwatch_activity,
            expected_notification=[
                bugwatch_notification, comment_notification])

    def test_bugwatch_removed(self):
        # Removing a BugWatch from a bug adds items to the activity
        # log and the Bug's notifications.
        bugtracker = self.factory.makeBugTracker()
        bug_watch = self.bug.addWatch(bugtracker, '42', self.user)
        self.saveOldChanges()
        self.bug.removeWatch(bug_watch, self.user)

        bugwatch_activity = {
            'person': self.user,
            'whatchanged': 'bug watch removed',
            'oldvalue': bug_watch.url,
            }

        bugwatch_notification = {
            'text': (
                "** Bug watch removed: %s #%s\n"
                "   %s" % (
                    bug_watch.bugtracker.title, bug_watch.remotebug,
                    bug_watch.url)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_notification=bugwatch_notification,
            expected_activity=bugwatch_activity)

    def test_bugwatch_modified(self):
        # Modifying a BugWatch is like removing and re-adding it.
        bugtracker = self.factory.makeBugTracker()
        bug_watch = self.bug.addWatch(bugtracker, '42', self.user)
        old_url = bug_watch.url
        self.saveOldChanges()
        old_remotebug = self.changeAttribute(bug_watch, 'remotebug', '84')

        bugwatch_removal_activity = {
            'person': self.user,
            'whatchanged': 'bug watch removed',
            'oldvalue': old_url,
            }
        bugwatch_addition_activity = {
            'person': self.user,
            'whatchanged': 'bug watch added',
            'newvalue': bug_watch.url,
            }

        bugwatch_removal_notification = {
            'text': (
                "** Bug watch removed: %s #%s\n"
                "   %s" % (
                    bug_watch.bugtracker.title, old_remotebug,
                    old_url)),
            'person': self.user,
            }
        bugwatch_addition_notification = {
            'text': (
                "** Bug watch added: %s #%s\n"
                "   %s" % (
                    bug_watch.bugtracker.title, bug_watch.remotebug,
                    bug_watch.url)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_notification=[bugwatch_removal_notification,
                                   bugwatch_addition_notification],
            expected_activity=[bugwatch_removal_activity,
                               bugwatch_addition_activity])

    def test_bugwatch_not_modified(self):
        # Firing off a modified event without actually modifying
        # anything intersting doesn't cause anything to be added to the
        # activity log.
        bug_watch = self.factory.makeBugWatch(bug=self.bug)
        self.saveOldChanges()
        self.changeAttribute(bug_watch, 'remotebug', bug_watch.remotebug)

        self.assertRecordedChange()

    def test_link_branch(self):
        # Linking a branch to a bug adds both to the activity log and
        # sends an e-mail notification.
        branch = self.factory.makeBranch()
        self.bug.addBranch(branch, self.user)
        added_activity = {
            'person': self.user,
            'whatchanged': 'branch linked',
            'newvalue': branch.bzr_identity,
            }
        added_notification = {
            'text': "** Branch linked: %s" % branch.bzr_identity,
            'person': self.user,
            }
        self.assertRecordedChange(
            expected_activity=added_activity,
            expected_notification=added_notification)

    def test_link_private_branch(self):
        # Linking a *private* branch to a bug adds *nothing* to the
        # activity log and does *not* send an e-mail notification.
        branch = self.factory.makeBranch(private=True)
        self.bug.addBranch(branch, self.user)
        self.assertRecordedChange()

    def test_unlink_branch(self):
        # Unlinking a branch from a bug adds both to the activity log and
        # sends an e-mail notification.
        branch = self.factory.makeBranch()
        self.bug.addBranch(branch, self.user)
        self.saveOldChanges()
        self.bug.removeBranch(branch, self.user)
        added_activity = {
            'person': self.user,
            'whatchanged': 'branch unlinked',
            'oldvalue': branch.bzr_identity,
            }
        added_notification = {
            'text': "** Branch unlinked: %s" % branch.bzr_identity,
            'person': self.user,
            }
        self.assertRecordedChange(
            expected_activity=added_activity,
            expected_notification=added_notification)

    def test_unlink_private_branch(self):
        # Unlinking a *private* branch from a bug adds *nothing* to
        # the activity log and does *not* send an e-mail notification.
        branch = self.factory.makeBranch(private=True)
        self.bug.addBranch(branch, self.user)
        self.saveOldChanges()
        self.bug.removeBranch(branch, self.user)
        self.assertRecordedChange()

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
        self.saveOldChanges(private_bug)
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

    def test_tags_added(self):
        # Adding tags to a bug will add BugActivity and BugNotification
        # entries.
        old_tags = self.changeAttribute(
            self.bug, 'tags', ['first-new-tag', 'second-new-tag'])

        tag_change_activity = {
            'person': self.user,
            'whatchanged': 'tags',
            'oldvalue': '',
            'newvalue': 'first-new-tag second-new-tag',
            }

        tag_change_notification = {
            'person': self.user,
            'text': '** Tags added: first-new-tag second-new-tag',
            }

        self.assertRecordedChange(
            expected_activity=tag_change_activity,
            expected_notification=tag_change_notification)

    def test_tags_removed(self):
        # Removing tags from a bug adds BugActivity and BugNotification
        # entries.
        self.bug.tags = ['first-new-tag', 'second-new-tag']
        self.saveOldChanges()
        old_tags = self.changeAttribute(
            self.bug, 'tags', ['first-new-tag'])

        tag_change_activity = {
            'person': self.user,
            'whatchanged': 'tags',
            'oldvalue': 'first-new-tag second-new-tag',
            'newvalue': 'first-new-tag',
            }

        tag_change_notification = {
            'person': self.user,
            'text': '** Tags removed: second-new-tag',
            }

        self.assertRecordedChange(
            expected_activity=tag_change_activity,
            expected_notification=tag_change_notification)

    def test_mark_as_security_vulnerability(self):
        # Marking a bug as a security vulnerability adds to the bug's
        # activity log and sends a notification.
        self.bug.security_related = False
        self.changeAttribute(self.bug, 'security_related', True)

        security_change_activity = {
            'person': self.user,
            'whatchanged': 'security vulnerability',
            'oldvalue': 'no',
            'newvalue': 'yes',
            }

        security_change_notification = {
            'text': (
                '** This bug has been flagged as '
                'a security vulnerability'),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=security_change_activity,
            expected_notification=security_change_notification)

    def test_unmark_as_security_vulnerability(self):
        # Unmarking a bug as a security vulnerability adds to the
        # bug's activity log and sends a notification.
        self.bug.security_related = True
        self.changeAttribute(self.bug, 'security_related', False)

        security_change_activity = {
            'person': self.user,
            'whatchanged': 'security vulnerability',
            'oldvalue': 'yes',
            'newvalue': 'no',
            }

        security_change_notification = {
            'text': (
                '** This bug is no longer flagged as '
                'a security vulnerability'),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=security_change_activity,
            expected_notification=security_change_notification)

    def test_link_cve(self):
        # Linking a CVE to a bug adds to the bug's activity log and
        # sends a notification.
        cve = getUtility(ICveSet)['1999-8979']
        self.bug.linkCVE(cve, self.user)

        cve_linked_activity = {
            'person': self.user,
            'whatchanged': 'cve linked',
            'oldvalue': None,
            'newvalue': cve.sequence,
            }

        cve_linked_notification = {
            'text': (
                '** CVE added: http://www.cve.mitre.org/'
                'cgi-bin/cvename.cgi?name=1999-8979'),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=cve_linked_activity,
            expected_notification=cve_linked_notification)

    def test_unlink_cve(self):
        # Unlinking a CVE from a bug adds to the bug's activity log and
        # sends a notification.
        cve = getUtility(ICveSet)['1999-8979']
        self.bug.linkCVE(cve, self.user)
        self.saveOldChanges()
        self.bug.unlinkCVE(cve, self.user)

        cve_unlinked_activity = {
            'person': self.user,
            'whatchanged': 'cve unlinked',
            'oldvalue': cve.sequence,
            'newvalue': None,
            }

        cve_unlinked_notification = {
            'text': (
                '** CVE removed: http://www.cve.mitre.org/'
                'cgi-bin/cvename.cgi?name=1999-8979'),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=cve_unlinked_activity,
            expected_notification=cve_unlinked_notification)

    def test_attachment_added(self):
        # Adding an attachment to a bug adds entries in both BugActivity
        # and BugNotification.
        message = self.factory.makeMessage(owner=self.user)
        self.bug.linkMessage(message)
        self.saveOldChanges()

        attachment = self.factory.makeBugAttachment(
            bug=self.bug, owner=self.user, comment=message)

        attachment_added_activity = {
            'person': self.user,
            'whatchanged': 'attachment added',
            'oldvalue': None,
            'newvalue': '%s %s' % (
                attachment.title, attachment.libraryfile.http_url),
            }

        attachment_added_notification = {
            'person': self.user,
            'text': '** Attachment added: "%s"\n   %s' % (
                attachment.title, attachment.libraryfile.http_url),
            }

        self.assertRecordedChange(
            expected_notification=attachment_added_notification,
            expected_activity=attachment_added_activity)

    def test_attachment_removed(self):
        # Removing an attachment from a bug adds entries in both BugActivity
        # and BugNotification.
        attachment = self.factory.makeBugAttachment(
            bug=self.bug, owner=self.user)
        self.saveOldChanges()
        attachment.removeFromBug(user=self.user)

        attachment_removed_activity = {
            'person': self.user,
            'whatchanged': 'attachment removed',
            'newvalue': None,
            'oldvalue': '%s %s' % (
                attachment.title, attachment.libraryfile.http_url),
            }

        attachment_removed_notification = {
            'person': self.user,
            'text': '** Attachment removed: "%s"\n   %s' % (
                attachment.title, attachment.libraryfile.http_url),
            }

        self.assertRecordedChange(
            expected_notification=attachment_removed_notification,
            expected_activity=attachment_removed_activity)

    def test_bugtask_added(self):
        # Adding a bug task adds entries in both BugActivity and
        # BugNotification.
        target = self.factory.makeProduct()
        added_task = self.bug.addTask(self.user, target)
        notify(ObjectCreatedEvent(added_task, user=self.user))

        task_added_activity = {
            'person': self.user,
            'whatchanged': 'bug task added',
            'newvalue': target.bugtargetname,
            }

        task_added_notification = {
            'person': self.user,
            'text': (
                '** Also affects: %s\n'
                '   Importance: %s\n'
                '       Status: %s' % (
                    target.bugtargetname, added_task.importance.title,
                    added_task.status.title))
            }

        self.assertRecordedChange(
            expected_notification=task_added_notification,
            expected_activity=task_added_activity)

    def test_bugtask_added_with_assignee(self):
        # Adding an assigned bug task adds entries in both BugActivity
        # and BugNotification.
        target = self.factory.makeProduct()
        added_task = self.bug.addTask(self.user, target)
        added_task.transitionToAssignee(self.factory.makePerson())
        notify(ObjectCreatedEvent(added_task, user=self.user))

        task_added_activity = {
            'person': self.user,
            'whatchanged': 'bug task added',
            'newvalue': target.bugtargetname,
            }

        task_added_notification = {
            'person': self.user,
            'text': (
                '** Also affects: %s\n'
                '   Importance: %s\n'
                '     Assignee: %s (%s)\n'
                '       Status: %s' % (
                    target.bugtargetname, added_task.importance.title,
                    added_task.assignee.displayname, added_task.assignee.name,
                    added_task.status.title))
            }

        self.assertRecordedChange(
            expected_notification=task_added_notification,
            expected_activity=task_added_activity)

    def test_bugtask_added_with_bugwatch(self):
        # Adding a bug task with a bug watch adds entries in both
        # BugActivity and BugNotification.
        target = self.factory.makeProduct()
        bug_watch = self.factory.makeBugWatch(bug=self.bug)
        self.saveOldChanges()
        added_task = self.bug.addTask(self.user, target)
        added_task.bugwatch = bug_watch
        notify(ObjectCreatedEvent(added_task, user=self.user))

        task_added_activity = {
            'person': self.user,
            'whatchanged': 'bug task added',
            'newvalue': target.bugtargetname,
            }

        task_added_notification = {
            'person': self.user,
            'text': (
                '** Also affects: %s via\n'
                '   %s\n'
                '   Importance: %s\n'
                '       Status: %s' % (
                    target.bugtargetname, bug_watch.url,
                    added_task.importance.title, added_task.status.title))
            }

        self.assertRecordedChange(
            expected_notification=task_added_notification,
            expected_activity=task_added_activity)

    def test_change_bugtask_importance(self):
        # When a bugtask's importance is changed, BugActivity and
        # BugNotification get updated.
        bug_task_before_modification = Snapshot(
            self.bug_task, providing=providedBy(self.bug_task))
        self.bug_task.transitionToImportance(
            BugTaskImportance.HIGH, user=self.user)
        notify(ObjectModifiedEvent(
            self.bug_task, bug_task_before_modification,
            ['importance'], user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: importance' % self.bug_task.bugtargetname,
            'oldvalue': 'Undecided',
            'newvalue': 'High',
            'message': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n   Importance: Undecided => High' %
                self.bug_task.bugtargetname),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_change_bugtask_status(self):
        # When a bugtask's status is changed, BugActivity and
        # BugNotification get updated.
        bug_task_before_modification = Snapshot(
            self.bug_task, providing=providedBy(self.bug_task))
        self.bug_task.transitionToStatus(
            BugTaskStatus.FIXRELEASED, user=self.user)
        notify(ObjectModifiedEvent(
            self.bug_task, bug_task_before_modification, ['status'],
            user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: status' % self.bug_task.bugtargetname,
            'oldvalue': 'New',
            'newvalue': 'Fix Released',
            'message': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n       Status: New => Fix Released' %
                self.bug_task.bugtargetname),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_target_bugtask_to_product(self):
        # When a bugtask's target is changed, BugActivity and
        # BugNotification get updated.
        bug_task_before_modification = Snapshot(
            self.bug_task, providing=providedBy(self.bug_task))

        new_target = self.factory.makeProduct(owner=self.user)
        self.bug_task.transitionToTarget(new_target)
        notify(ObjectModifiedEvent(
            self.bug_task, bug_task_before_modification,
            ['target', 'product'], user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': 'affects',
            'oldvalue': bug_task_before_modification.bugtargetname,
            'newvalue': self.bug_task.bugtargetname,
            }

        expected_notification = {
            'text': u"** Project changed: %s => %s" % (
                bug_task_before_modification.bugtargetname,
                self.bug_task.bugtargetname),
            'person': self.user,
            'recipients': [
                self.user, self.product_metadata_subscriber],
            }

        # The person who was subscribed to meta data changes for the old
        # product was notified.
        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_target_bugtask_to_sourcepackage(self):
        # When a bugtask's target is changed, BugActivity and
        # BugNotification get updated.
        target = self.factory.makeDistributionSourcePackage()
        metadata_subscriber = self.newSubscriber(
            target, "dsp-metadata", BugNotificationLevel.METADATA)
        lifecycle_subscriber = self.newSubscriber(
            target, "dsp-lifecycle", BugNotificationLevel.LIFECYCLE)
        new_target = self.factory.makeDistributionSourcePackage(
            distribution=target.distribution)

        source_package_bug = self.factory.makeBug(owner=self.user)
        source_package_bug_task = source_package_bug.addTask(
            owner=self.user, target=target)
        self.saveOldChanges(source_package_bug)

        bug_task_before_modification = Snapshot(
            source_package_bug_task,
            providing=providedBy(source_package_bug_task))
        source_package_bug_task.transitionToTarget(new_target)

        notify(ObjectModifiedEvent(
            source_package_bug_task, bug_task_before_modification,
            ['target', 'sourcepackagename'], user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': 'affects',
            'oldvalue': bug_task_before_modification.bugtargetname,
            'newvalue': source_package_bug_task.bugtargetname,
            }

        expected_recipients = [self.user, metadata_subscriber]
        expected_recipients.extend(
            bug_task.pillar.owner
            for bug_task in source_package_bug.bugtasks)

        expected_notification = {
            'text': u"** Package changed: %s => %s" % (
                bug_task_before_modification.bugtargetname,
                source_package_bug_task.bugtargetname),
            'person': self.user,
            'recipients': expected_recipients,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification,
            bug=source_package_bug)

    def test_add_bugwatch_to_bugtask(self):
        # Adding a BugWatch to a bug task records an entry in
        # BugActivity and BugNotification.
        bug_watch = self.factory.makeBugWatch()
        self.saveOldChanges()

        self.changeAttribute(self.bug_task, 'bugwatch', bug_watch)

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: remote watch' % self.product.bugtargetname,
            'oldvalue': None,
            'newvalue': bug_watch.title,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n Remote watch: None => %s' % (
                self.bug_task.bugtargetname, bug_watch.title)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_remove_bugwatch_from_bugtask(self):
        # Removing a BugWatch from a bug task records an entry in
        # BugActivity and BugNotification.
        bug_watch = self.factory.makeBugWatch()
        self.changeAttribute(self.bug_task, 'bugwatch', bug_watch)
        self.saveOldChanges()

        self.changeAttribute(self.bug_task, 'bugwatch', None)

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: remote watch' % self.product.bugtargetname,
            'oldvalue': bug_watch.title,
            'newvalue': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n Remote watch: %s => None' % (
                self.bug_task.bugtargetname, bug_watch.title)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_assign_bugtask(self):
        # Assigning a bug task to someone adds entries to the bug
        # activity and notifications sets.
        bug_task_before_modification = Snapshot(
            self.bug_task, providing=providedBy(self.bug_task))

        self.bug_task.transitionToAssignee(self.user)
        notify(ObjectModifiedEvent(
            self.bug_task, bug_task_before_modification,
            ['assignee'], user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: assignee' % self.bug_task.bugtargetname,
            'oldvalue': None,
            'newvalue': self.user.unique_displayname,
            'message': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n'
                u'     Assignee: (unassigned) => %s' % (
                    self.bug_task.bugtargetname,
                    self.user.unique_displayname)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_unassign_bugtask(self):
        # Unassigning a bug task to someone adds entries to the bug
        # activity and notifications sets.
        old_assignee = self.factory.makePerson()
        self.bug_task.transitionToAssignee(old_assignee)
        self.saveOldChanges()

        bug_task_before_modification = Snapshot(
            self.bug_task, providing=providedBy(self.bug_task))

        self.bug_task.transitionToAssignee(None)

        notify(ObjectModifiedEvent(
            self.bug_task, bug_task_before_modification,
            ['assignee'], user=self.user))

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: assignee' % self.bug_task.bugtargetname,
            'oldvalue': old_assignee.unique_displayname,
            'newvalue': None,
            'message': None,
            }

        # The old assignee got notified about the change, in addition
        # to the default recipients.
        expected_recipients = [
            self.user, self.product_metadata_subscriber, old_assignee]

        expected_notification = {
            'text': (
                u'** Changed in: %s\n'
                u'     Assignee: %s => (unassigned)' % (
                    self.bug_task.bugtargetname,
                    old_assignee.unique_displayname)),
            'person': self.user,
            'recipients': expected_recipients,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_target_bugtask_to_milestone(self):
        # When a bugtask is targetted to a milestone BugActivity and
        # BugNotification records will be created.
        milestone = self.factory.makeMilestone(product=self.product)
        self.changeAttribute(self.bug_task, 'milestone', milestone)

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: milestone' % self.bug_task.bugtargetname,
            'oldvalue': None,
            'newvalue': milestone.name,
            'message': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n    Milestone: None => %s' % (
                self.bug_task.bugtargetname, milestone.name)),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_untarget_bugtask_from_milestone(self):
        # When a bugtask is untargetted from a milestone both
        # BugActivity and BugNotification records will be created.
        milestone = self.factory.makeMilestone(product=self.product)
        self.changeAttribute(self.bug_task, 'milestone', milestone)
        self.saveOldChanges()
        old_milestone_subscriber = self.factory.makePerson()
        milestone.addBugSubscription(
            old_milestone_subscriber, old_milestone_subscriber)

        self.changeAttribute(self.bug_task, 'milestone', None)

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: milestone' % self.bug_task.bugtargetname,
            'newvalue': None,
            'oldvalue': milestone.name,
            'message': None,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n    Milestone: %s => None' % (
                self.bug_task.bugtargetname, milestone.name)),
            'person': self.user,
            'recipients': [
                self.user, self.product_metadata_subscriber,
                old_milestone_subscriber,
                ],
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_change_bugtask_milestone(self):
        # When a bugtask is retargeted from one milestone to another,
        # both BugActivity and BugNotification records are created.
        old_milestone = self.factory.makeMilestone(product=self.product)
        old_milestone_subscriber = self.factory.makePerson()
        old_milestone.addBugSubscription(
            old_milestone_subscriber, old_milestone_subscriber)
        new_milestone = self.factory.makeMilestone(product=self.product)
        new_milestone_subscriber = self.factory.makePerson()
        new_milestone.addBugSubscription(
            new_milestone_subscriber, new_milestone_subscriber)

        self.changeAttribute(self.bug_task, 'milestone', old_milestone)
        self.saveOldChanges()
        self.changeAttribute(self.bug_task, 'milestone', new_milestone)

        expected_activity = {
            'person': self.user,
            'whatchanged': '%s: milestone' % self.bug_task.bugtargetname,
            'newvalue': new_milestone.name,
            'oldvalue': old_milestone.name,
            }

        expected_notification = {
            'text': (
                u'** Changed in: %s\n'
                u'    Milestone: %s => %s' % (
                    self.bug_task.bugtargetname,
                    old_milestone.name, new_milestone.name)),
            'person': self.user,
            'recipients': [
                self.user, self.product_metadata_subscriber,
                old_milestone_subscriber, new_milestone_subscriber,
                ],
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_product_series_nominated(self):
        # Nominating a bug to be fixed in a product series adds an item
        # to the activity log only.
        product = self.factory.makeProduct()
        series = self.factory.makeProductSeries(product=product)
        self.bug.addTask(self.user, product)
        self.saveOldChanges()

        nomination = self.bug.addNomination(self.user, series)
        self.assertFalse(nomination.isApproved())

        expected_activity = {
            'person': self.user,
            'whatchanged': 'nominated for series',
            'newvalue': series.bugtargetname,
            }

        self.assertRecordedChange(expected_activity=expected_activity)

    def test_distro_series_nominated(self):
        # Nominating a bug to be fixed in a product series adds an item
        # to the activity log only.
        distribution = self.factory.makeDistribution()
        series = self.factory.makeDistroRelease(distribution=distribution)
        self.bug.addTask(self.user, distribution)
        self.saveOldChanges()

        nomination = self.bug.addNomination(self.user, series)
        self.assertFalse(nomination.isApproved())

        expected_activity = {
            'person': self.user,
            'whatchanged': 'nominated for series',
            'newvalue': series.bugtargetname,
            }

        self.assertRecordedChange(expected_activity=expected_activity)

    def test_series_nominated_and_approved(self):
        # When adding a nomination that is approved automatically, it's
        # like adding a new bug task for the series directly.
        product = self.factory.makeProduct(owner=self.user)
        product.driver = self.user
        series = self.factory.makeProductSeries(product=product)
        self.bug.addTask(self.user, product)
        self.saveOldChanges()

        nomination = self.bug.addNomination(self.user, series)
        self.assertTrue(nomination.isApproved())

        expected_activity = {
            'person': self.user,
            'newvalue': series.bugtargetname,
            'whatchanged': 'bug task added',
            'newvalue': series.bugtargetname,
            }

        task_added_notification = {
            'person': self.user,
            'text': (
                '** Also affects: %s\n'
                '   Importance: Undecided\n'
                '       Status: New' % (
                    series.bugtargetname)),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=task_added_notification)

    def test_nomination_approved(self):
        # When a nomination is approved, it's like adding a new bug
        # task for the series directly.
        product = self.factory.makeProduct()
        product.driver = product.owner
        series = self.factory.makeProductSeries(product=product)
        self.bug.addTask(self.user, product)

        nomination = self.bug.addNomination(self.user, series)
        self.assertFalse(nomination.isApproved())
        self.saveOldChanges()
        nomination.approve(product.owner)

        expected_activity = {
            'person': product.owner,
            'newvalue': series.bugtargetname,
            'whatchanged': 'bug task added',
            'newvalue': series.bugtargetname,
            }

        task_added_notification = {
            'person': product.owner,
            'text': (
                '** Also affects: %s\n'
                '   Importance: Undecided\n'
                '       Status: New' % (
                    series.bugtargetname)),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=task_added_notification)

    def test_marked_as_duplicate(self):
        # When a bug is marked as a duplicate, activity is recorded
        # and a notification is sent.
        duplicate_bug = self.factory.makeBug()
        self.saveOldChanges(duplicate_bug)
        self.changeAttribute(duplicate_bug, 'duplicateof', self.bug)

        expected_activity = {
            'person': self.user,
            'whatchanged': 'marked as duplicate',
            'oldvalue': None,
            'newvalue': str(self.bug.id),
            }

        expected_notification = {
            'person': self.user,
            'text': ("** This bug has been marked a duplicate of bug %d\n"
                     "   %s" % (self.bug.id, self.bug.title)),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification,
            bug=duplicate_bug)

    def test_unmarked_as_duplicate(self):
        # When a bug is unmarked as a duplicate, activity is recorded
        # and a notification is sent.
        duplicate_bug = self.factory.makeBug()
        duplicate_bug.duplicateof = self.bug
        self.saveOldChanges(duplicate_bug)
        self.changeAttribute(duplicate_bug, 'duplicateof', None)

        expected_activity = {
            'person': self.user,
            'whatchanged': 'removed duplicate marker',
            'oldvalue': str(self.bug.id),
            'newvalue': None,
            }

        expected_notification = {
            'person': self.user,
            'text': ("** This bug is no longer a duplicate of bug %d\n"
                     "   %s" % (self.bug.id, self.bug.title)),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification,
            bug=duplicate_bug)

    def test_changed_duplicate(self):
        # When a bug is changed from being a duplicate of one bug to
        # being a duplicate of another, activity is recorded and a
        # notification is sent.
        bug_one = self.factory.makeBug()
        bug_two = self.factory.makeBug()
        self.bug.duplicateof = bug_one
        self.saveOldChanges()
        self.changeAttribute(self.bug, 'duplicateof', bug_two)

        expected_activity = {
            'person': self.user,
            'whatchanged': 'changed duplicate marker',
            'oldvalue': str(bug_one.id),
            'newvalue': str(bug_two.id),
            }

        expected_notification = {
            'person': self.user,
            'text': ("** This bug is no longer a duplicate of bug %d\n"
                     "   %s\n"
                     "** This bug has been marked a duplicate of bug %d\n"
                     "   %s" % (bug_one.id, bug_one.title,
                                bug_two.id, bug_two.title)),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification)

    def test_convert_to_question_no_comment(self):
        # When a bug task is converted to a question, its status is
        # first set to invalid, which causes the normal notifications for
        # that to be added to the activity log and sent out as e-mail
        # notification. After that another item is added to the activity
        # log saying that the bug was converted to a question.
        self.bug.convertToQuestion(self.user)
        converted_question = self.bug.getQuestionCreatedFromBug()

        conversion_activity = {
            'person': self.user,
            'whatchanged': 'converted to question',
            'newvalue': str(converted_question.id),
            }
        status_activity = {
            'person': self.user,
            'whatchanged': '%s: status' % self.bug_task.bugtargetname,
            'newvalue': 'Invalid',
            'oldvalue': 'New',
            }

        conversion_notification = {
            'person': self.user,
            'text': (
                '** Converted to question:\n'
                '   %s' % canonical_url(converted_question))
            }
        status_notification = {
            'text': (
                '** Changed in: %s\n'
                '       Status: New => Invalid' %
                self.bug_task.bugtargetname),
            'person': self.user,
            }

        self.assertRecordedChange(
            expected_activity=[status_activity, conversion_activity],
            expected_notification=[status_notification,
                                   conversion_notification])

    def test_create_bug(self):
        # When a bug is created, activity is recorded and a comment
        # notification is sent.
        new_bug = self.factory.makeBug(
            product=self.product, owner=self.user, comment="ENOTOWEL")

        expected_activity = {
            'person': self.admin_user,
            'whatchanged': 'bug',
            'message': u"added bug",
            }

        expected_notification = {
            'person': self.user,
            'text': u"ENOTOWEL",
            'is_comment': True,
            'recipients': new_bug.getBugNotificationRecipients(
                level=BugNotificationLevel.COMMENTS),
            }

        self.assertRecordedChange(
            expected_activity=expected_activity,
            expected_notification=expected_notification,
            bug=new_bug)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
