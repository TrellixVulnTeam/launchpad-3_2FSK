# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test subscruber classes and functions."""

__metaclass__ = type

from datetime import datetime

from lazr.lifecycle.event import ObjectModifiedEvent
from lazr.lifecycle.interfaces import IObjectModifiedEvent
import pytz
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.person import IPersonViewRestricted
from lp.registry.interfaces.product import License
from lp.registry.subscribers import (
    LicenseNotification,
    person_alteration_security_notice,
    product_licenses_modified,
    )
from lp.services.verification.interfaces.logintoken import ILoginTokenSet
from lp.services.verification.interfaces.authtoken import LoginTokenType
from lp.services.webapp.publisher import get_current_browser_request
from lp.testing import (
    login_person,
    logout,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.event import TestEventListener
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.mail_helpers import pop_notifications


class ProductLicensesModifiedTestCase(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def make_product_event(self, licenses, edited_fields='licenses'):
        product = self.factory.makeProduct(licenses=licenses)
        pop_notifications()
        login_person(product.owner)
        event = ObjectModifiedEvent(
            product, product, edited_fields, user=product.owner)
        return product, event

    def test_product_licenses_modified_licenses_not_edited(self):
        product, event = self.make_product_event(
            [License.OTHER_PROPRIETARY], edited_fields='_owner')
        product_licenses_modified(product, event)
        notifications = pop_notifications()
        self.assertEqual(0, len(notifications))

    def test_product_licenses_modified_licenses_common_license(self):
        product, event = self.make_product_event([License.MIT])
        product_licenses_modified(product, event)
        notifications = pop_notifications()
        self.assertEqual(0, len(notifications))
        request = get_current_browser_request()
        self.assertEqual(0, len(request.response.notifications))

    def test_product_licenses_modified_licenses_other_proprietary(self):
        product, event = self.make_product_event([License.OTHER_PROPRIETARY])
        product_licenses_modified(product, event)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        request = get_current_browser_request()
        self.assertEqual(1, len(request.response.notifications))

    def test_product_licenses_modified_licenses_other_open_source(self):
        product, event = self.make_product_event([License.OTHER_OPEN_SOURCE])
        product_licenses_modified(product, event)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        request = get_current_browser_request()
        self.assertEqual(0, len(request.response.notifications))

    def test_product_licenses_modified_licenses_other_dont_know(self):
        product, event = self.make_product_event([License.DONT_KNOW])
        product_licenses_modified(product, event)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        request = get_current_browser_request()
        self.assertEqual(0, len(request.response.notifications))


class LicenseNotificationTestCase(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def make_product_user(self, licenses):
        # Setup an a view that implements ProductLicenseMixin.
        super(LicenseNotificationTestCase, self).setUp()
        user = self.factory.makePerson(
            name='registrant', email='registrant@launchpad.dev')
        login_person(user)
        product = self.factory.makeProduct(
            name='ball', owner=user, licenses=licenses)
        pop_notifications()
        return product, user

    def verify_whiteboard(self, product):
        # Verify that the review whiteboard was updated.
        naked_product = removeSecurityProxy(product)
        entries = naked_product.reviewer_whiteboard.split('\n')
        whiteboard, stamp = entries[-1].rsplit(' ', 1)
        self.assertEqual(
            'User notified of license policy on', whiteboard)

    def verify_user_email(self, notification):
        # Verify that the user was sent an email about the license change.
        self.assertEqual(
            'License information for ball in Launchpad',
            notification['Subject'])
        self.assertEqual(
            'Registrant <registrant@launchpad.dev>',
            notification['To'])
        self.assertEqual(
            'Commercial <commercial@launchpad.net>',
            notification['Reply-To'])

    def test_send_known_license(self):
        # A known license does not generate an email.
        product, user = self.make_product_user([License.GNU_GPL_V2])
        notification = LicenseNotification(product, user)
        result = notification.send()
        self.assertIs(False, result)
        self.assertEqual(0, len(pop_notifications()))

    def test_send_other_dont_know(self):
        # An Other/I don't know license sends one email.
        product, user = self.make_product_user([License.DONT_KNOW])
        notification = LicenseNotification(product, user)
        result = notification.send()
        self.assertIs(True, result)
        self.verify_whiteboard(product)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test_send_other_open_source(self):
        # An Other/Open Source license sends one email.
        product, user = self.make_product_user([License.OTHER_OPEN_SOURCE])
        notification = LicenseNotification(product, user)
        result = notification.send()
        self.assertIs(True, result)
        self.verify_whiteboard(product)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test_send_other_proprietary(self):
        # An Other/Proprietary license sends one email.
        product, user = self.make_product_user([License.OTHER_PROPRIETARY])
        notification = LicenseNotification(product, user)
        result = notification.send()
        self.assertIs(True, result)
        self.verify_whiteboard(product)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test_display_no_request(self):
        # If there is no request, there is no reason to show a message in
        # the browser.
        product, user = self.make_product_user([License.GNU_GPL_V2])
        notification = LicenseNotification(product, user)
        logout()
        result = notification.display()
        self.assertIs(False, result)

    def test_display_no_message(self):
        # A notification is not added if there is no message to show.
        product, user = self.make_product_user([License.GNU_GPL_V2])
        notification = LicenseNotification(product, user)
        result = notification.display()
        self.assertEqual('', notification.getCommercialUseMessage())
        self.assertIs(False, result)

    def test_display_has_message(self):
        # A notification is added if there is a message to show.
        product, user = self.make_product_user([License.OTHER_PROPRIETARY])
        notification = LicenseNotification(product, user)
        result = notification.display()
        message = notification.getCommercialUseMessage()
        self.assertIs(True, result)
        request = get_current_browser_request()
        self.assertEqual(1, len(request.response.notifications))
        self.assertIn(message, request.response.notifications[0].message)
        self.assertIn(
            '<a href="https://help.launchpad.net/CommercialHosting">',
            request.response.notifications[0].message)

    def test_display_escapee_user_data(self):
        # A notification is added if there is a message to show.
        product, user = self.make_product_user([License.OTHER_PROPRIETARY])
        product.displayname = '<b>Look</b>'
        notification = LicenseNotification(product, user)
        result = notification.display()
        self.assertIs(True, result)
        request = get_current_browser_request()
        self.assertEqual(1, len(request.response.notifications))
        self.assertIn(
            '&lt;b&gt;Look&lt;/b&gt;',
            request.response.notifications[0].message)

    def test_formatDate(self):
        # Verify the date format.
        now = datetime(2005, 6, 15, 0, 0, 0, 0, pytz.UTC)
        result = LicenseNotification._formatDate(now)
        self.assertEqual('2005-06-15', result)

    def test_getTemplateName_other_dont_know(self):
        product, user = self.make_product_user([License.DONT_KNOW])
        notification = LicenseNotification(product, user)
        self.assertEqual(
            'product-license-dont-know.txt',
            notification.getTemplateName())

    def test_getTemplateName_propietary(self):
        product, user = self.make_product_user([License.OTHER_PROPRIETARY])
        notification = LicenseNotification(product, user)
        self.assertEqual(
            'product-license-other-proprietary.txt',
            notification.getTemplateName())

    def test_getTemplateName_other_open_source(self):
        product, user = self.make_product_user([License.OTHER_OPEN_SOURCE])
        notification = LicenseNotification(product, user)
        self.assertEqual(
            'product-license-other-open-source.txt',
            notification.getTemplateName())

    def test_getCommercialUseMessage_without_commercial_subscription(self):
        product, user = self.make_product_user([License.MIT])
        notification = LicenseNotification(product, user)
        self.assertEqual('', notification.getCommercialUseMessage())

    def test_getCommercialUseMessage_with_complimentary_cs(self):
        product, user = self.make_product_user([License.OTHER_PROPRIETARY])
        notification = LicenseNotification(product, user)
        message = (
            "Ball's complimentary commercial subscription expires on %s." %
            product.commercial_subscription.date_expires.date().isoformat())
        self.assertEqual(message, notification.getCommercialUseMessage())

    def test_getCommercialUseMessage_with_commercial_subscription(self):
        product, user = self.make_product_user([License.MIT])
        self.factory.makeCommercialSubscription(product)
        product.licenses = [License.MIT, License.OTHER_PROPRIETARY]
        notification = LicenseNotification(product, user)
        message = (
            "Ball's commercial subscription expires on %s." %
            product.commercial_subscription.date_expires.date().isoformat())
        self.assertEqual(message, notification.getCommercialUseMessage())

    def test_getCommercialUseMessage_with_expired_cs(self):
        product, user = self.make_product_user([License.MIT])
        self.factory.makeCommercialSubscription(product, expired=True)
        product.licenses = [License.MIT, License.OTHER_PROPRIETARY]
        notification = LicenseNotification(product, user)
        message = (
            "Ball's commercial subscription expired on %s." %
            product.commercial_subscription.date_expires.date().isoformat())
        self.assertEqual(message, notification.getCommercialUseMessage())
        self.assertEqual(message, notification.getCommercialUseMessage())


class TestPersonDetailsModified(TestCaseWithFactory):
    """When some details of a person change, we need to notify the user."""
    layer = DatabaseFunctionalLayer

    def test_event_generates_notification(self):
        """Manually firing event should generate a proper notification."""
        person = self.factory.makePerson(email='test@pre.com')
        login_person(person)
        pop_notifications()
        # After/before objects and list of edited fields.
        event = ObjectModifiedEvent(person, person, ['preferredemail'])
        person_alteration_security_notice(person, event)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.assertTrue('test@pre.com' in notifications[0].get('To'))

    def test_preferred_email_modified(self):
        """Modifying the preferred email should get the notification."""
        person = self.factory.makePerson(email='test@pre.com')
        login_person(person)
        pop_notifications()
        new_email = self.factory.makeEmail('test@post.com', person)
        person.setPreferredEmail(new_email)
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.assertTrue('test@pre.com' in notifications[0].get('To'))
        self.assertTrue(
            'Preferred email address' in notifications[0].as_string())


class TestPersonDetailsModifiedEvent(TestCaseWithFactory):
    """Test that the events are fired when the person is changed."""

    layer = DatabaseFunctionalLayer
    event_listener = None

    def setup_event_listener(self):
        self.events = []
        if self.event_listener is None:
            self.event_listener = TestEventListener(
                IPersonViewRestricted, IObjectModifiedEvent, self.on_event)
        else:
            self.event_listener._active = True
        self.addCleanup(self.event_listener.unregister)

    def on_event(self, thing, event):
        self.events.append(event)

    def test_change_preferredemail(self):
        # The project_reviewed property is not reset, if the new licenses
        # are identical to the current licenses.
        pop_notifications()
        person = self.factory.makePerson(email='test@pre.com')
        new_email = self.factory.makeEmail('test@post.com', person)
        self.setup_event_listener()
        with person_logged_in(person):
            person.setPreferredEmail(new_email)
            # Assert form within the context manager to get access to the
            # email values.
            self.assertEqual('test@post.com', person.preferredemail.email)
            self.assertEqual(1, len(self.events))

            evt = self.events[0]
            self.assertEqual(person, evt.object)
            self.assertEqual('test@pre.com',
                evt.object_before_modification.preferredemail.email)
            self.assertEqual(['preferredemail'], evt.edited_fields)

    def test_no_event_on_no_change(self):
        """If there's no change to the preferred email there's no event"""
        pop_notifications()
        person = self.factory.makePerson(email='test@pre.com')
        self.setup_event_listener()
        with person_logged_in(person):
            person.displayname = 'changed'
            # Assert form within the context manager to get access to the
            # email values.
            self.assertEqual('test@pre.com', person.preferredemail.email)
            self.assertEqual(0, len(self.events))

    def test_removed_email_address(self):
        """When an email address is removed we should notify."""
        pop_notifications()
        self.setup_event_listener()
        person = self.factory.makePerson(email='test@pre.com')

        with person_logged_in(person):
            secondary_email = self.factory.makeEmail('test@second.com', person)
            secondary_email.destroySelf()
            # We should only have one email address, the preferred.
            self.assertEqual('test@pre.com', person.preferredemail.email)
            # The preferred email doesn't show in the list of validated emails
            # so there are none left once the destroy is done.
            self.assertEqual(0, person.validatedemails.count())
            self.assertEqual(1, len(self.events))
            evt = self.events[0]
            self.assertEqual(person, evt.object)
            self.assertEqual(['removedemail'], evt.edited_fields)

            # The notice of this should be going to the preferred email user.
            notifications = pop_notifications()
            self.assertTrue('test@pre.com' in notifications[0].get('To'))
            self.assertTrue(
                'Email address removed' in notifications[0].as_string())

    def test_new_email_request(self):
        """When an email address is added we should notify.

        We want to send the notification when the new email address is
        requested. This doesn't actually create an email address yet. It
        builds a LoginToken that the user must ack before the email address is
        added. The issue is security in alerting the owner of the account that
        a new address is being requested, so we need to notify at the time of
        request and not wait for the user to ack the new email address.
        """
        pop_notifications()
        self.setup_event_listener()
        person = self.factory.makePerson(email='test@pre.com')

        with person_logged_in(person):
            secondary_email = self.factory.makeEmail('test@second.com', person)
            # The way that a new email address gets requested is through the
            # LoginToken done in the browser/person action_add_email.
            getUtility(ILoginTokenSet).new(person,
                person.preferredemail.email,
                secondary_email.email,
                LoginTokenType.VALIDATEEMAIL)
            self.assertEqual(1, len(self.events))
            evt = self.events[0]
            self.assertEqual(person, evt.object)
            self.assertEqual(['newemail'], evt.edited_fields)

            # The notice of this should be going to the preferred email user.
            notifications = pop_notifications()
            self.assertTrue('test@pre.com' in notifications[0].get('To'))
            self.assertTrue(
                'Email address added' in notifications[0].as_string())

    def test_new_ssh_key(self):
        """We also want the notification when users add ssh keys."""
        pop_notifications()
        self.setup_event_listener()
        person = self.factory.makePerson(email='test@pre.com')

        with person_logged_in(person):
            # The factory method generates a fresh ssh key through the
            # SSHKeySet that we're bound into. The view uses the same ssh key
            # set .new method so it's safe to just let the factory trigger our
            # event for us.
            self.factory.makeSSHKey(person)
            self.assertEqual(1, len(self.events))
            evt = self.events[0]
            self.assertEqual(person, evt.object)
            self.assertEqual(['newsshkey'], evt.edited_fields)

            # The notice of this should be going to the preferred email user.
            notifications = pop_notifications()
            self.assertTrue('test@pre.com' in notifications[0].get('To'))
            self.assertTrue(
                'SSH key added' in notifications[0].as_string())

    def test_remove_ssh_key(self):
        """Notifications should fire when we remove an ssh key."""
        pop_notifications()
        self.setup_event_listener()
        person = self.factory.makePerson(email='test@pre.com')

        with person_logged_in(person):
            sshkey = self.factory.makeSSHKey(person)
            # Make sure to clear notifications/events before we remove the key.
            pop_notifications()
            self.events = []
            sshkey.destroySelf()
            self.assertEqual(1, len(self.events))
            evt = self.events[0]
            self.assertEqual(person, evt.object)
            self.assertEqual(['removedsshkey'], evt.edited_fields)

            # The notice of this should be going to the preferred email user.
            notifications = pop_notifications()
            self.assertTrue('test@pre.com' in notifications[0].get('To'))
            self.assertTrue(
                'SSH key removed' in notifications[0].as_string())

