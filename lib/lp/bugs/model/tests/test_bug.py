# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.bugs.enum import BugNotificationLevel
from lp.bugs.model.bug import BugSubscriptionInfo
from lp.registry.interfaces.person import PersonVisibility
from lp.testing import (
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )


class TestBug(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_get_subscribers_for_person_unsubscribed(self):
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        self.assertTrue(bug.getSubscribersForPerson(person).is_empty())

    def test_get_subscribers_for_person_direct_subscription(self):
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        with person_logged_in(person):
            bug.subscribe(person, person)
        self.assertEqual([person], list(bug.getSubscribersForPerson(person)))

    def test_get_subscribers_for_person_indirect_subscription(self):
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        team1 = self.factory.makeTeam(members=[person])
        self.factory.makeTeam(members=[person])
        with person_logged_in(person):
            bug.subscribe(team1, person)
        self.assertEqual([team1], list(bug.getSubscribersForPerson(person)))

    def test_get_subscribers_for_person_many_subscriptions(self):
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        team1 = self.factory.makeTeam(members=[person])
        team2 = self.factory.makeTeam(members=[person])
        with person_logged_in(person):
            bug.subscribe(team1, person)
            bug.subscribe(team2, person)
            bug.subscribe(person, person)
        self.assertEqual(
            set([person, team1, team2]),
            set(bug.getSubscribersForPerson(person)))

    def test_get_subscribers_for_person_from_duplicates_too(self):
        bug = self.factory.makeBug()
        real_bug = self.factory.makeBug()
        person = self.factory.makePerson()
        team1 = self.factory.makeTeam(members=[person])
        team2 = self.factory.makeTeam(members=[person])
        with person_logged_in(person):
            bug.subscribe(team1, person)
            bug.subscribe(team2, person)
            bug.subscribe(person, person)
            bug.markAsDuplicate(real_bug)
        self.assertEqual(
            set([person, team1, team2]),
            set(real_bug.getSubscribersForPerson(person)))

    def test_getSubscriptionsFromDuplicates(self):
        # getSubscriptionsFromDuplicates() will return only the earliest
        # subscription if a user is subscribed to a bug via more than one
        # duplicate.
        user = self.factory.makePerson()
        login_person(user)
        bug = self.factory.makeBug(owner=user)
        dupe1 = self.factory.makeBug(owner=user)
        dupe1.markAsDuplicate(bug)
        subscription = dupe1.subscribe(user, user)
        dupe2 = self.factory.makeBug(owner=user)
        dupe2.markAsDuplicate(bug)
        dupe2.subscribe(user, user)
        self.assertEqual(
            [subscription], list(bug.getSubscriptionsFromDuplicates()))

    def test_get_also_notified_subscribers_with_private_team(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        member = self.factory.makePerson()
        team = self.factory.makeTeam(
            owner=member, visibility=PersonVisibility.PRIVATE)
        with person_logged_in(member):
            product.addSubscription(team, member)
        self.assertTrue(team in bug.getAlsoNotifiedSubscribers())

    def test_get_indirect_subscribers_with_private_team(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        member = self.factory.makePerson()
        team = self.factory.makeTeam(
            owner=member, visibility=PersonVisibility.PRIVATE)
        with person_logged_in(member):
            product.addSubscription(team, member)
        self.assertTrue(team in bug.getIndirectSubscribers())

    def test_get_direct_subscribers_with_private_team(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        member = self.factory.makePerson()
        team = self.factory.makeTeam(
            owner=member, visibility=PersonVisibility.PRIVATE)
        with person_logged_in(member):
            bug.subscribe(team, member)
        self.assertTrue(team in bug.getDirectSubscribers())

    def test_get_subscribers_from_duplicates_with_private_team(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        dupe_bug = self.factory.makeBug()
        member = self.factory.makePerson()
        team = self.factory.makeTeam(
            owner=member, visibility=PersonVisibility.PRIVATE)
        with person_logged_in(member):
            dupe_bug.subscribe(team, member)
            dupe_bug.markAsDuplicate(bug)
        self.assertTrue(team in bug.getSubscribersFromDuplicates())

    def test_subscribe_with_level(self):
        # It's possible to subscribe to a bug at a different
        # BugNotificationLevel by passing a `level` parameter to
        # subscribe().
        bug = self.factory.makeBug()
        for level in BugNotificationLevel.items:
            subscriber = self.factory.makePerson()
            with person_logged_in(subscriber):
                subscription = bug.subscribe(
                    subscriber, subscriber, level=level)
            self.assertEqual(level, subscription.bug_notification_level)

    def test_resubscribe_with_level(self):
        # If you pass a new level to subscribe with an existing subscription,
        # the level is set on the existing subscription.
        bug = self.factory.makeBug()
        subscriber = self.factory.makePerson()
        levels = list(BugNotificationLevel.items)
        with person_logged_in(subscriber):
            subscription = bug.subscribe(
                subscriber, subscriber, level=levels[-1])
        for level in levels:
            with person_logged_in(subscriber):
                bug.subscribe(subscriber, subscriber, level=level)
            self.assertEqual(level, subscription.bug_notification_level)

    def test_get_direct_subscribers_with_level(self):
        # It's possible to pass a level parameter to
        # getDirectSubscribers() to filter the subscribers returned.
        # When a `level` is passed to getDirectSubscribers(), the
        # subscribers returned will be those of that level of
        # subscription or higher.
        bug = self.factory.makeBug()
        # We unsubscribe the bug's owner because if we don't there will
        # be two COMMENTS-level subscribers.
        with person_logged_in(bug.owner):
            bug.unsubscribe(bug.owner, bug.owner)
        reversed_levels = sorted(
            BugNotificationLevel.items, reverse=True)
        subscribers = []
        for level in reversed_levels:
            subscriber = self.factory.makePerson()
            subscribers.append(subscriber)
            with person_logged_in(subscriber):
                bug.subscribe(subscriber, subscriber, level=level)
            direct_subscribers = bug.getDirectSubscribers(level=level)

            # All the previous subscribers will be included because
            # their level of subscription is such that they also receive
            # notifications at the current level.
            self.assertEqual(
                set(subscribers), set(direct_subscribers),
                "Subscribers did not match expected value.")

    def test_get_direct_subscribers_default_level(self):
        # If no `level` parameter is passed to getDirectSubscribers(),
        # the assumed `level` is BugNotification.LIFECYCLE.
        bug = self.factory.makeBug()
        # We unsubscribe the bug's owner because if we don't there will
        # be two COMMENTS-level subscribers.
        with person_logged_in(bug.owner):
            bug.unsubscribe(bug.owner, bug.owner)
        subscribers = []
        for level in BugNotificationLevel.items:
            subscriber = self.factory.makePerson()
            subscribers.append(subscriber)
            with person_logged_in(subscriber):
                bug.subscribe(subscriber, subscriber, level=level)

        # All the subscribers should be returned by
        # getDirectSubscribers() because it defaults to returning
        # subscribers at level LIFECYCLE, which everything is higher than.
        direct_subscribers = bug.getDirectSubscribers()
        self.assertEqual(
            set(subscribers), set(direct_subscribers),
            "Subscribers did not match expected value.")

    def test_get_direct_subscribers_with_details(self):
        # getDirectSubscribersWithDetails() returns both
        # Person and BugSubscription records in one go.
        bug = self.factory.makeBug()
        with person_logged_in(bug.owner):
            # Unsubscribe bug owner so it doesn't taint the result.
            bug.unsubscribe(bug.owner, bug.owner)
        subscriber = self.factory.makePerson()
        with person_logged_in(subscriber):
            subscription = bug.subscribe(
                subscriber, subscriber, level=BugNotificationLevel.LIFECYCLE)

        self.assertContentEqual(
            [(subscriber, subscription)],
            bug.getDirectSubscribersWithDetails())

    def test_get_direct_subscribers_with_details_mute_excludes(self):
        # getDirectSubscribersWithDetails excludes muted subscriptions.
        bug = self.factory.makeBug()
        with person_logged_in(bug.owner):
            # Unsubscribe bug owner so it doesn't taint the result.
            bug.unsubscribe(bug.owner, bug.owner)
        subscriber = self.factory.makePerson()
        with person_logged_in(subscriber):
            bug.subscribe(
                subscriber, subscriber, level=BugNotificationLevel.LIFECYCLE)
            bug.mute(subscriber, subscriber)

        self.assertContentEqual(
            [], bug.getDirectSubscribersWithDetails())

    def test_subscribers_from_dupes_uses_level(self):
        # When getSubscribersFromDuplicates() is passed a `level`
        # parameter it will include only subscribers subscribed to
        # duplicates at that BugNotificationLevel or higher.
        bug = self.factory.makeBug()
        duplicate_bug = self.factory.makeBug()
        with person_logged_in(duplicate_bug.owner):
            duplicate_bug.markAsDuplicate(bug)
            # We unsubscribe the owner of the duplicate to avoid muddling
            # the results retuned by getSubscribersFromDuplicates()
            duplicate_bug.unsubscribe(
                duplicate_bug.owner, duplicate_bug.owner)
        for level in BugNotificationLevel.items:
            subscriber = self.factory.makePerson()
            with person_logged_in(subscriber):
                duplicate_bug.subscribe(subscriber, subscriber, level=level)
            # Only the most recently subscribed person will be included
            # because the previous subscribers are subscribed at a lower
            # level.
            self.assertEqual(
                (subscriber,),
                bug.getSubscribersFromDuplicates(level=level))

    def test_subscribers_from_dupes_overrides_using_level(self):
        # Bug.getSubscribersFromDuplicates() does not return subscribers
        # who also have a direct subscription to the master bug provided
        # that the subscription to the master bug is of the same level
        # or higher as the subscription to the duplicate.
        bug = self.factory.makeBug()
        duplicate_bug = self.factory.makeBug()
        with person_logged_in(duplicate_bug.owner):
            duplicate_bug.markAsDuplicate(bug)
            # We unsubscribe the owner of the duplicate to avoid muddling
            # the results retuned by getSubscribersFromDuplicates()
            duplicate_bug.unsubscribe(
                duplicate_bug.owner, duplicate_bug.owner)
        subscriber = self.factory.makePerson()
        with person_logged_in(subscriber):
            bug.subscribe(
                subscriber, subscriber, level=BugNotificationLevel.LIFECYCLE)
            duplicate_bug.subscribe(
                subscriber, subscriber, level=BugNotificationLevel.METADATA)
        duplicate_subscribers = bug.getSubscribersFromDuplicates()
        self.assertTrue(
            subscriber not in duplicate_subscribers,
            "Subscriber should not be in duplicate_subscribers.")

    def test_getSubscriptionInfo(self):
        # getSubscriptionInfo() returns a BugSubscriptionInfo object.
        bug = self.factory.makeBug()
        with person_logged_in(bug.owner):
            info = bug.getSubscriptionInfo()
        self.assertIsInstance(info, BugSubscriptionInfo)
        self.assertEqual(bug, info.bug)
        self.assertEqual(BugNotificationLevel.LIFECYCLE, info.level)
        # A level can also be specified.
        with person_logged_in(bug.owner):
            info = bug.getSubscriptionInfo(BugNotificationLevel.METADATA)
        self.assertEqual(BugNotificationLevel.METADATA, info.level)

    def test_setPrivate_subscribes_person_who_makes_bug_private(self):
        # When setPrivate(True) is called on a bug, the person who is
        # marking the bug private is subscribed to the bug.
        bug = self.factory.makeBug()
        person = self.factory.makePerson()
        with person_logged_in(person):
            bug.setPrivate(True, person)
            self.assertTrue(bug.personIsDirectSubscriber(person))

    def test_setPrivate_does_not_subscribe_member_of_subscribed_team(self):
        # When setPrivate(True) is called on a bug, the person who is
        # marking the bug private will not be subscribed if they're
        # already a member of a team which is a direct subscriber.
        bug = self.factory.makeBug()
        team = self.factory.makeTeam()
        person = team.teamowner
        with person_logged_in(person):
            bug.subscribe(team, person)
            bug.setPrivate(True, person)
            self.assertFalse(bug.personIsDirectSubscriber(person))
