# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the bugsubscription module."""

__metaclass__ = type

from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.testing import DatabaseFunctionalLayer
from lp.bugs.interfaces.bugtask import (
    BugTaskImportance,
    BugTaskStatus,
    )
from lp.bugs.model.bugsubscriptionfilter import BugSubscriptionFilter
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from canonical.launchpad import searchbuilder


class TestBugSubscriptionFilter(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugSubscriptionFilter, self).setUp()
        self.target = self.factory.makeProduct()
        self.subscriber = self.target.owner
        login_person(self.subscriber)
        self.subscription = self.target.addBugSubscription(
            self.subscriber, self.subscriber)

    def test_basics(self):
        """Test the basic operation of `BugSubscriptionFilter` objects."""
        # Create.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.structural_subscription = self.subscription
        bug_subscription_filter.find_all_tags = True
        bug_subscription_filter.include_any_tags = True
        bug_subscription_filter.exclude_any_tags = True
        bug_subscription_filter.other_parameters = u"foo"
        bug_subscription_filter.description = u"bar"
        # Flush and reload.
        IStore(bug_subscription_filter).flush()
        IStore(bug_subscription_filter).reload(bug_subscription_filter)
        # Check.
        self.assertIsNot(None, bug_subscription_filter.id)
        self.assertEqual(
            self.subscription.id,
            bug_subscription_filter.structural_subscription_id)
        self.assertEqual(
            self.subscription,
            bug_subscription_filter.structural_subscription)
        self.assertIs(True, bug_subscription_filter.find_all_tags)
        self.assertIs(True, bug_subscription_filter.include_any_tags)
        self.assertIs(True, bug_subscription_filter.exclude_any_tags)
        self.assertEqual(u"foo", bug_subscription_filter.other_parameters)
        self.assertEqual(u"bar", bug_subscription_filter.description)

    def test_defaults(self):
        """Test the default values of `BugSubscriptionFilter` objects."""
        # Create.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.structural_subscription = self.subscription
        # Check.
        self.assertIs(False, bug_subscription_filter.find_all_tags)
        self.assertIs(False, bug_subscription_filter.include_any_tags)
        self.assertIs(False, bug_subscription_filter.exclude_any_tags)
        self.assertIs(None, bug_subscription_filter.other_parameters)
        self.assertIs(None, bug_subscription_filter.description)

    def test_statuses(self):
        # The statuses property is a frozenset of the statuses that are
        # filtered upon.
        bug_subscription_filter = BugSubscriptionFilter()
        self.assertEqual(frozenset(), bug_subscription_filter.statuses)

    def test_statuses_set(self):
        # Assigning any iterable to statuses updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.statuses = [
            BugTaskStatus.NEW, BugTaskStatus.INCOMPLETE]
        self.assertEqual(
            frozenset((BugTaskStatus.NEW, BugTaskStatus.INCOMPLETE)),
            bug_subscription_filter.statuses)
        # Assigning a subset causes the other status filters to be removed.
        bug_subscription_filter.statuses = [BugTaskStatus.NEW]
        self.assertEqual(
            frozenset((BugTaskStatus.NEW,)),
            bug_subscription_filter.statuses)

    def test_statuses_set_empty(self):
        # Assigning an empty iterable to statuses updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.statuses = []
        self.assertEqual(frozenset(), bug_subscription_filter.statuses)

    def test_importances(self):
        # The importances property is a frozenset of the importances that are
        # filtered upon.
        bug_subscription_filter = BugSubscriptionFilter()
        self.assertEqual(frozenset(), bug_subscription_filter.importances)

    def test_importances_set(self):
        # Assigning any iterable to importances updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.importances = [
            BugTaskImportance.HIGH, BugTaskImportance.LOW]
        self.assertEqual(
            frozenset((BugTaskImportance.HIGH, BugTaskImportance.LOW)),
            bug_subscription_filter.importances)
        # Assigning a subset causes the other importance filters to be
        # removed.
        bug_subscription_filter.importances = [BugTaskImportance.HIGH]
        self.assertEqual(
            frozenset((BugTaskImportance.HIGH,)),
            bug_subscription_filter.importances)

    def test_importances_set_empty(self):
        # Assigning an empty iterable to importances updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.importances = []
        self.assertEqual(frozenset(), bug_subscription_filter.importances)

    def test_tags(self):
        # The tags property is a frozenset of the tags that are filtered upon.
        bug_subscription_filter = BugSubscriptionFilter()
        self.assertEqual(frozenset(), bug_subscription_filter.tags)

    def test_tags_set(self):
        # Assigning any iterable to tags updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.tags = [u"foo", u"-bar"]
        self.assertEqual(
            frozenset((u"foo", u"-bar")),
            bug_subscription_filter.tags)
        # Assigning a subset causes the other tag filters to be removed.
        bug_subscription_filter.tags = [u"foo"]
        self.assertEqual(
            frozenset((u"foo",)),
            bug_subscription_filter.tags)

    def test_tags_set_empty(self):
        # Assigning an empty iterable to tags updates the database.
        bug_subscription_filter = BugSubscriptionFilter()
        bug_subscription_filter.tags = []
        self.assertEqual(frozenset(), bug_subscription_filter.tags)

    def test_tags_set_wildcard(self):
        # Setting one or more wildcard tags may update include_any_tags or
        # exclude_any_tags.
        bug_subscription_filter = BugSubscriptionFilter()
        self.assertEqual(frozenset(), bug_subscription_filter.tags)
        self.assertFalse(bug_subscription_filter.include_any_tags)
        self.assertFalse(bug_subscription_filter.exclude_any_tags)

        bug_subscription_filter.tags = [u"*"]
        self.assertEqual(frozenset((u"*",)), bug_subscription_filter.tags)
        self.assertTrue(bug_subscription_filter.include_any_tags)
        self.assertFalse(bug_subscription_filter.exclude_any_tags)

        bug_subscription_filter.tags = [u"-*"]
        self.assertEqual(frozenset((u"-*",)), bug_subscription_filter.tags)
        self.assertFalse(bug_subscription_filter.include_any_tags)
        self.assertTrue(bug_subscription_filter.exclude_any_tags)

        bug_subscription_filter.tags = [u"*", u"-*"]
        self.assertEqual(
            frozenset((u"*", u"-*")), bug_subscription_filter.tags)
        self.assertTrue(bug_subscription_filter.include_any_tags)
        self.assertTrue(bug_subscription_filter.exclude_any_tags)

        bug_subscription_filter.tags = []
        self.assertEqual(frozenset(), bug_subscription_filter.tags)
        self.assertFalse(bug_subscription_filter.include_any_tags)
        self.assertFalse(bug_subscription_filter.exclude_any_tags)

    def test_tags_with_any_and_all(self):
        # If the tags are bundled in a c.l.searchbuilder.any or .all, the
        # find_any_tags attribute will also be updated.
        bug_subscription_filter = BugSubscriptionFilter()
        self.assertEqual(frozenset(), bug_subscription_filter.tags)
        self.assertFalse(bug_subscription_filter.find_all_tags)

        bug_subscription_filter.tags = searchbuilder.all(u"foo")
        self.assertEqual(frozenset((u"foo",)), bug_subscription_filter.tags)
        self.assertTrue(bug_subscription_filter.find_all_tags)

        # Not using `searchbuilder.any` or `.all` leaves find_all_tags
        # unchanged.
        bug_subscription_filter.tags = [u"-bar"]
        self.assertEqual(frozenset((u"-bar",)), bug_subscription_filter.tags)
        self.assertTrue(bug_subscription_filter.find_all_tags)

        bug_subscription_filter.tags = searchbuilder.any(u"baz")
        self.assertEqual(frozenset((u"baz",)), bug_subscription_filter.tags)
        self.assertFalse(bug_subscription_filter.find_all_tags)
