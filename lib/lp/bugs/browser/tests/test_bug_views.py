# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Bug Views."""

__metaclass__ = type

from zope.component import getUtility

from BeautifulSoup import BeautifulSoup

from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.interfaces import IOpenLaunchBag
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.launchpad.testing.pages import find_tag_by_id
from canonical.testing.layers import DatabaseFunctionalLayer

from lp.services.features.testing import FeatureFixture
from lp.services.features import get_relevant_feature_controller
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.views import create_initialized_view


class TestPrivateBugLinks(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def makeDupeOfPrivateBug(self):
        bug = self.factory.makeBug()
        dupe = self.factory.makeBug()
        with person_logged_in(bug.owner):
            bug.setPrivate(private=True, who=bug.owner)
            dupe.markAsDuplicate(bug)
        return dupe

    def test_private_bugs_are_not_linked_without_permission(self):
        bug = self.makeDupeOfPrivateBug()
        url = canonical_url(bug, rootsite="bugs")
        browser = self.getUserBrowser(url)
        dupe_warning = find_tag_by_id(
            browser.contents,
            'warning-comment-on-duplicate')
        # There is no link in the dupe_warning.
        self.assertTrue('href' not in dupe_warning)


class TestEmailObfuscated(BrowserTestCase):
    """Test for obfuscated emails on bug pages."""

    layer = DatabaseFunctionalLayer

    def getBrowserForBugWithEmail(self, email_address, no_login):
        bug = self.factory.makeBug(
            title="Title with %s contained" % email_address,
            description="Description with %s contained." % email_address)
        return self.getViewBrowser(bug, rootsite="bugs", no_login=no_login)

    def test_user_sees_email_address(self):
        """A logged-in user can see the email address on the page."""
        email_address = "mark@example.com"
        browser = self.getBrowserForBugWithEmail(
            email_address, no_login=False)
        self.assertEqual(6, browser.contents.count(email_address))

    def test_anonymous_sees_not_email_address(self):
        """The anonymous user cannot see the email address on the page."""
        email_address = "mark@example.com"
        browser = self.getBrowserForBugWithEmail(
            email_address, no_login=True)
        self.assertEqual(0, browser.contents.count(email_address))


class TestBugPortletSubscribers(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer
    feature_flag_1 = 'malone.advanced-subscriptions.enabled'
    feature_flag_2 = 'malone.advanced-structural-subscriptions.enabled'

    def setUp(self):
        super(TestBugPortletSubscribers, self).setUp()
        self.target = self.factory.makeProduct()
        bug_owner = self.factory.makePerson(name="bug-owner")
        self.bug = self.factory.makeBug(owner=bug_owner, product=self.target)
        # We need to put the Bug and default BugTask into the LaunchBag
        # because BugContextMenu relies on the LaunchBag to populate its
        # context property
        launchbag = getUtility(IOpenLaunchBag)
        launchbag.add(self.bug)
        launchbag.add(self.bug.default_bugtask)

    def test_edit_subscriptions_link_shown_when_feature_enabled(self):
        with FeatureFixture({self.feature_flag_2: 'on'}):
            request = LaunchpadTestRequest()
            request.features = get_relevant_feature_controller()
            view = create_initialized_view(
                self.bug, name="+portlet-subscription", request=request)
            html = view.render()
        self.assertTrue('menu-link-editsubscriptions' in html)
        self.assertTrue('/+subscriptions' in html)

    def test_edit_subscriptions_link_not_shown_when_feature_disabled(self):
        view = create_initialized_view(
            self.bug, name="+portlet-subscription")
        html = view.render()
        self.assertTrue('menu-link-editsubscriptions' not in html)
        self.assertTrue('/+subscriptions' not in html)

    def test_mute_subscription_link_not_shown_with_no_feature_flag(self):
        # Mute link is not shown when the feature flag is off.
        person = self.factory.makePerson()
        with person_logged_in(person):
            with FeatureFixture({self.feature_flag_1: None}):
                view = create_initialized_view(
                    self.bug, name="+portlet-subscription")
                self.assertFalse(view.user_should_see_mute_link)
                html = view.render()
                self.assertFalse('mute_subscription' in html)

    def _hasCSSClass(self, html, element_id, css_class):
        # Return True if element with ID `element_id` in `html` has
        # a CSS class `css_class`.
        soup = BeautifulSoup(html)
        element = soup.find(attrs={'id': element_id})
        return css_class in element['class'].split(' ')

    def test_bug_mute_for_individual_structural_subscription(self):
        # If the person has a structural subscription to the pillar,
        # then the mute link will be displayed to them.
        person = self.factory.makePerson(name="a-person")
        with FeatureFixture({self.feature_flag_1: 'on'}):
            with person_logged_in(person):
                self.target.addBugSubscription(person, person)
                self.assertFalse(self.bug.isMuted(person))
                view = create_initialized_view(
                    self.bug, name="+portlet-subscription")
                self.assertTrue(view.user_should_see_mute_link,
                                "User should see mute link.")
                contents = view.render()
                self.assertTrue('mute_subscription' in contents,
                                "'mute_subscription' not in contents.")
                self.assertFalse(
                    self._hasCSSClass(
                        contents, 'mute-link-container', 'hidden'))
                create_initialized_view(
                    self.bug.default_bugtask, name="+mute",
                    form={'field.actions.mute': 'Mute bug mail'})
                self.assertTrue(self.bug.isMuted(person))

    def test_mute_subscription_link_shown_for_team_subscription(self):
        # If the person belongs to a team with a structural subscription,
        # then the mute link will be displayed to them.
        person = self.factory.makePerson(name="a-person")
        team_owner = self.factory.makePerson(name="team-owner")
        team = self.factory.makeTeam(owner=team_owner, name="subscribed-team")
        with FeatureFixture({self.feature_flag_1: 'on'}):
            with person_logged_in(team_owner):
                team.addMember(person, team_owner)
                self.target.addBugSubscription(team, team_owner)
            with person_logged_in(person):
                self.assertFalse(self.bug.isMuted(person))
                self.assertTrue(
                    self.bug.personIsAlsoNotifiedSubscriber(
                        person), "Person should be a notified subscriber")
                view = create_initialized_view(
                    self.bug, name="+portlet-subscription")
                self.assertTrue(view.user_should_see_mute_link,
                                "User should see mute link.")
                contents = view.render()
                self.assertTrue('mute_subscription' in contents,
                                "'mute_subscription' not in contents.")
                self.assertFalse(
                    self._hasCSSClass(
                        contents, 'mute-link-container', 'hidden'))
                create_initialized_view(
                    self.bug.default_bugtask, name="+mute",
                    form={'field.actions.mute': 'Mute bug mail'})
                self.assertTrue(self.bug.isMuted(person))

    def test_mute_subscription_link_hidden_for_non_subscribers(self):
        # If a person is not already subscribed to a bug in some way,
        # the mute link will not be displayed to them.
        person = self.factory.makePerson()
        with person_logged_in(person):
            with FeatureFixture({self.feature_flag_1: 'on'}):
                # The user isn't subscribed or muted already.
                self.assertFalse(self.bug.isSubscribed(person))
                self.assertFalse(self.bug.isMuted(person))
                self.assertFalse(
                    self.bug.personIsAlsoNotifiedSubscriber(
                        person))
                view = create_initialized_view(
                    self.bug, name="+portlet-subscription")
                self.assertFalse(view.user_should_see_mute_link)
                html = view.render()
                self.assertTrue('mute_subscription' in html)
                # The template uses user_should_see_mute_link to decide
                # whether or not to display the mute link.
                self.assertTrue(
                    self._hasCSSClass(html, 'mute-link-container', 'hidden'),
                    'No "hidden" CSS class in mute-link-container.')

    def test_mute_subscription_link_not_rendered_for_anonymous(self):
        # If a person is not already subscribed to a bug in some way,
        # the mute link will not be displayed to them.
        with FeatureFixture({self.feature_flag_1: 'on'}):
            view = create_initialized_view(
                self.bug, name="+portlet-subscription")
            self.assertFalse(view.user_should_see_mute_link)
            html = view.render()
            self.assertFalse('mute_subscription' in html)

    def test_mute_subscription_link_shown_if_muted(self):
        # If a person is muted but not otherwise subscribed, they should still
        # see the (un)mute link.
        person = self.factory.makePerson()
        with person_logged_in(person):
            with FeatureFixture({self.feature_flag_1: 'on'}):
                self.bug.mute(person, person)
                # The user isn't subscribed already, but is muted.
                self.assertFalse(self.bug.isSubscribed(person))
                self.assertFalse(
                    self.bug.personIsAlsoNotifiedSubscriber(
                        person))
                self.assertTrue(self.bug.isMuted(person))
                view = create_initialized_view(
                    self.bug, name="+portlet-subscription")
                self.assertTrue(view.user_should_see_mute_link,
                                "User should see mute link.")
                contents = view.render()
                self.assertTrue('mute_subscription' in contents,
                                "'mute_subscription' not in contents.")
                self.assertFalse(
                    self._hasCSSClass(
                        contents, 'mute-link-container', 'hidden'))

    def test_mute_classes_work_for_anonymous_users(self):
        # If a user is not logged in, the template shouldn't break
        # horribly.
        bug = self.factory.makeBug()
        view = create_initialized_view(bug.default_bugtask, name="+index")
        self.assertEqual(
            'subscribed-false dup-subscribed-false',
            view.current_user_subscription_class)
        self.assertEqual(
            'muted-false hidden subscribed-false dup-subscribed-false',
            view.current_user_mute_class)


class TestBugSecrecyViews(TestCaseWithFactory):
    """Tests for the Bug secrecy views."""

    layer = DatabaseFunctionalLayer

    def createInitializedSecrecyView(self, person=None, bug=None):
        """Create and return an initialized BugSecrecyView."""
        if person is None:
            person = self.factory.makePerson()
        if bug is None:
            bug = self.factory.makeBug()
        with person_logged_in(person):
            view = create_initialized_view(
                bug.default_bugtask, name='+secrecy', form={
                    'field.private': 'on',
                    'field.security_related': '',
                    'field.actions.change': 'Change',
                    })
            return view

    def test_notification_shown_if_marking_private_and_not_subscribed(self):
        # If a user who is not subscribed to a bug marks that bug as
        # private, the user will be subscribed to the bug. This allows
        # them to un-mark the bug if they choose to, rather than being
        # blocked from doing so.
        view = self.createInitializedSecrecyView()
        message_text = (
            "Since you marked this bug as private you have "
            "automatically been subscribed to it.")
        notifications = view.request.response.notifications
        self.assertEqual(
            [message_text],
            [notification.message for notification in notifications])

    def test_no_notification_shown_if_marking_private_and_subscribed(self):
        # If a user who is subscribed to a bug marks that bug as
        # private, the user will see not notification.
        person = self.factory.makePerson()
        bug = self.factory.makeBug()
        with person_logged_in(person):
            bug.subscribe(person, person)
        view = self.createInitializedSecrecyView(person, bug)
        self.assertContentEqual([], view.request.response.notifications)

    def test_notification_includes_link_for_advanced_subscriptions(self):
        # If the advanced subscriptions feature flag is turned on, the
        # notification will include a link to the edit subscription
        # page and the mute page for the bug.
        with FeatureFixture({'malone.advanced-subscriptions.enabled': 'on'}):
            view = self.createInitializedSecrecyView()
            bug = view.context.bug
            self.assertEqual(1, len(view.request.response.notifications))
            notification = view.request.response.notifications[0].message
            mute_url = canonical_url(bug.default_bugtask, view_name='+mute')
            subscribe_url = canonical_url(
                bug.default_bugtask, view_name='+subscribe')
            self.assertIn(mute_url, notification)
            self.assertIn(subscribe_url, notification)
