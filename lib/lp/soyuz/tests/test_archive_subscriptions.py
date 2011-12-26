# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Archive features."""

from zope.security.interfaces import Unauthorized

from lp.services.webapp.publisher import canonical_url
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.registry.interfaces.person import PersonVisibility
from lp.testing import (
    BrowserTestCase,
    celebrity_logged_in,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.mail_helpers import pop_notifications
from lp.testing.pages import (
    find_tag_by_id,
    setupBrowserForUser,
    )
from lp.testing.views import create_initialized_view


class TestArchiveSubscriptions(TestCaseWithFactory):
    """Edge-case tests for private PPA subscribers.

    See also lib/lp/soyuz/stories/ppa/xx-private-ppa-subscription-stories.txt
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Create a test archive."""
        super(TestArchiveSubscriptions, self).setUp()
        self.owner = self.factory.makePerson()
        self.private_team = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE,
            name="subscribertest", owner=self.owner)
        login_person(self.owner)
        self.archive = self.factory.makeArchive(
            private=True, owner=self.private_team)
        self.subscriber = self.factory.makePerson()

    def test_subscriber_can_access_private_team_ppa(self):
        # As per bug 597783, we need to make sure a subscriber can see
        # a private team's PPA after they have been given a subscription.
        # This is essentially allowing access for the subscriber to see
        # the private team.
        def get_name():
            return self.archive.owner.name

        # Before a subscription, accessing the team name will raise.
        login_person(self.subscriber)
        self.assertRaises(Unauthorized, get_name)

        login_person(self.owner)
        self.archive.newSubscription(
            self.subscriber, registrant=self.archive.owner)

        # When a subscription exists, it's fine.
        login_person(self.subscriber)
        self.assertEqual(self.archive.owner.name, "subscribertest")

    def test_subscriber_can_browse_private_team_ppa(self):
        # As per bug 597783, we need to make sure a subscriber can see
        # a private team's PPA after they have been given a subscription.
        # This test ensures the subscriber can correctly load the PPA's view,
        # thus ensuring that all attributes necessary to render the view have
        # the necessary security permissions.

        # Before a subscription, accessing the view name will raise.
        login_person(self.subscriber)
        view = create_initialized_view(
            self.archive, '+index', principal=self.subscriber)
        self.assertRaises(Unauthorized, view.render)

        login_person(self.owner)
        self.archive.newSubscription(
            self.subscriber, registrant=self.archive.owner)

        # When a subscription exists, it's fine.
        login_person(self.subscriber)
        self.assertIn(self.archive.displayname, view.render())

        # Just to double check, by default, the subscriber still can't see the
        # +packages view which requires extra permissions.
        self.assertRaises(
            Unauthorized, create_initialized_view,
            self.archive, '+packages', principal=self.subscriber)

    def test_new_subscription_sends_email(self):
        # Creating a new subscription sends an email to all members
        # of the person or team subscribed.
        self.assertEqual(0, len(pop_notifications()))

        self.archive.newSubscription(
            self.subscriber, registrant=self.archive.owner)

        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.assertEqual(
            self.subscriber.preferredemail.email,
            notifications[0]['to'])

    def test_new_commercial_subscription_no_email(self):
        # As per bug 611568, an email is not sent for commercial PPAs.
        with celebrity_logged_in('commercial_admin'):
            self.archive.commercial = True

        # Logging in as a celebrity team causes an email to be sent
        # because a person is added as a member of the team, so this
        # needs to be cleared out before calling newSubscription().
        pop_notifications()

        self.archive.newSubscription(
            self.subscriber, registrant=self.archive.owner)

        self.assertEqual(0, len(pop_notifications()))


class PrivateArtifactsViewTestCase(BrowserTestCase):
    """ Tests that private team archives can be viewed."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Create a test archive."""
        super(PrivateArtifactsViewTestCase, self).setUp()
        self.owner = self.factory.makePerson()
        self.private_team = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE,
            name="subscribertest", owner=self.owner)
        with person_logged_in(self.owner):
            self.archive = self.factory.makeArchive(
                private=True, owner=self.private_team)
        self.subscriber = self.factory.makePerson()

    def test_traverse_view_private_team_archive_subscriber(self):
        # A subscriber can traverse and view the archive.
        with person_logged_in(self.owner):
            self.archive.newSubscription(
                self.subscriber, registrant=self.archive.owner)
        with person_logged_in(self.subscriber):
            url = canonical_url(self.archive)
        browser = setupBrowserForUser(self.subscriber)
        browser.open(url)
        content = find_tag_by_id(browser.contents, 'document')
        self.assertIsNotNone(find_tag_by_id(content, 'ppa-install'))
        self.assertIsNotNone(
            find_tag_by_id(content, 'portlet-latest-updates'))
