# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for product views."""

__metaclass__ = type

import datetime

import pytz

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.launchpad.testing.pages import (
    find_tag_by_id,
    first_tag_by_class,
    )
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.app.enums import ServiceUsage
from lp.registry.browser.product import (
    ProductActionNavigationMenu,
    ProductLicenseMixin,
    )
from lp.registry.interfaces.product import (
    License,
    IProductSet,
    )
from lp.services.features import getFeatureFlag
from lp.services.features.testing import FeatureFixture
from lp.testing import (
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.mail_helpers import pop_notifications
from lp.testing.service_usage_helpers import set_service_usage
from lp.testing.views import (
    create_initialized_view,
    create_view,
    )

class TestProductLicenseMixin(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Setup an a view that implements ProductLicenseMixin.
        super(TestProductLicenseMixin, self).setUp()
        self.registrant = self.factory.makePerson(
            name='registrant', email='registrant@launchpad.dev')
        self.product = self.factory.makeProduct(
            name='ball', owner=self.registrant)
        self.view = create_view(self.product, '+edit')
        self.view.product = self.product
        login_person(self.registrant)

    def verify_whiteboard(self):
        # Verify that the review whiteboard was updated.
        naked_product = removeSecurityProxy(self.product)
        whiteboard, stamp = naked_product.reviewer_whiteboard.rsplit(' ', 1)
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

    def test_ProductLicenseMixin_instance(self):
        # The object under test is an instance of ProductLicenseMixin.
        self.assertTrue(isinstance(self.view, ProductLicenseMixin))

    def test_notifyCommercialMailingList_known_license(self):
        # A known license does not generate an email.
        self.product.licenses = [License.GNU_GPL_V2]
        self.view.notifyCommercialMailingList()
        self.assertEqual(0, len(pop_notifications()))

    def test_notifyCommercialMailingList_other_dont_know(self):
        # An Other/I don't know license sends one email.
        self.product.licenses = [License.DONT_KNOW]
        self.view.notifyCommercialMailingList()
        self.verify_whiteboard()
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test_notifyCommercialMailingList_other_open_source(self):
        # An Other/Open Source license sends one email.
        self.product.licenses = [License.OTHER_OPEN_SOURCE]
        self.product.license_info = 'http://www,boost.org/'
        self.view.notifyCommercialMailingList()
        self.verify_whiteboard()
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test_notifyCommercialMailingList_other_proprietary(self):
        # An Other/Proprietary license sends one email.
        self.product.licenses = [License.OTHER_PROPRIETARY]
        self.product.license_info = 'All mine'
        self.view.notifyCommercialMailingList()
        self.verify_whiteboard()
        notifications = pop_notifications()
        self.assertEqual(1, len(notifications))
        self.verify_user_email(notifications.pop())

    def test__formatDate(self):
        # Verify the date format.
        now = datetime.datetime(2005, 6, 15, 0, 0, 0, 0, pytz.UTC)
        result = self.view._formatDate(now)
        self.assertEqual('2005-06-15', result)


class TestProductConfiguration(TestCaseWithFactory):
    """Tests the configuration links and helpers."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductConfiguration, self).setUp()
        self.product = self.factory.makeProduct()

    def test_registration_not_done(self):
        # The registration done property on the product index view
        # tells you if all the configuration work is done, based on
        # usage enums.

        # At least one usage enum is unknown, so registration done is false.
        self.assertEqual(
            self.product.codehosting_usage,
            ServiceUsage.UNKNOWN)
        view = create_view(self.product, '+get-involved')
        self.assertFalse(view.registration_done)

        set_service_usage(
            self.product.name,
            codehosting_usage="EXTERNAL",
            bug_tracking_usage="LAUNCHPAD",
            answers_usage="EXTERNAL",
            translations_usage="NOT_APPLICABLE")
        view = create_view(self.product, '+get-involved')
        self.assertTrue(view.registration_done)


class TestProductAddView(TestCaseWithFactory):
    """Tests the configuration links and helpers."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductAddView, self).setUp()
        self.product_set = getUtility(IProductSet)
        # Marker allowing us to reset the config.
        config.push(self.id(), '')
        self.addCleanup(config.pop, self.id())

    def test_staging_message_is_not_demo(self):
        view = create_initialized_view(self.product_set, '+new')
        message = find_tag_by_id(view.render(), 'staging-message')
        self.assertTrue(message is not None)

    def test_staging_message_is_demo(self):
        config.push('staging-test', '''
            [launchpad]
            is_demo: true
            ''')
        view = create_initialized_view(self.product_set, '+new')
        message = find_tag_by_id(view.render(), 'staging-message')
        self.assertEqual(None, message)


class TestProductView(TestCaseWithFactory):
    """Tests the ProductView."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductView, self).setUp()
        self.product = self.factory.makeProduct()

    def test_show_programming_languages_without_languages(self):
        # show_programming_languages is false when there are no programming
        # languages set.
        view = create_initialized_view(self.product, '+index')
        self.assertEqual(None, self.product.programminglang)
        self.assertFalse(view.show_programming_languages)

    def test_show_programming_languages_with_languages(self):
        # show_programming_languages is true when programming languages
        # are set.
        with person_logged_in(self.product.owner):
            self.product.programminglang = 'C++'
        view = create_initialized_view(self.product, '+index')
        self.assertTrue(view.show_programming_languages)

    def test_show_license_info_without_other_license(self):
        # show_license_info is false when one of the "other" licenses is
        # not selected.
        view = create_initialized_view(self.product, '+index')
        self.assertEqual((License.GNU_GPL_V2, ), self.product.licenses)
        self.assertFalse(view.show_license_info)

    def test_show_license_info_with_other_open_source_license(self):
        # show_license_info is true when the Other/Open Source license is
        # selected.
        view = create_initialized_view(self.product, '+index')
        with person_logged_in(self.product.owner):
            self.product.licenses = [License.OTHER_OPEN_SOURCE]
        self.assertTrue(view.show_license_info)

    def test_show_license_info_with_other_open_proprietary_license(self):
        # show_license_info is true when the Other/Proprietary license is
        # selected.
        view = create_initialized_view(self.product, '+index')
        with person_logged_in(self.product.owner):
            self.product.licenses = [License.OTHER_PROPRIETARY]
        self.assertTrue(view.show_license_info)


class TestProductViewStructuralSubscriptions(TestCaseWithFactory):
    """Test structural subscriptions on the product view.

    The link to structural subscriptions is controlled by the feature flag
    'malone.advanced-structural-subscriptions.enabled'.  If it is false, the
    old link leading to +subscribe is shown.  If it is true then the new
    JavaScript control is used.
    """

    layer = DatabaseFunctionalLayer
    feature_flag = 'malone.advanced-structural-subscriptions.enabled'

    def setUp(self):
        super(TestProductViewStructuralSubscriptions, self).setUp()
        self.product = self.factory.makeProduct()

    def test_subscribe_link_feature_flag_off(self):
        # Test the old subscription link.
        with FeatureFixture({self.feature_flag: None}):
            self.assertEqual(None, getFeatureFlag(self.feature_flag))
            view = create_initialized_view(
                self.product, '+index', principal=self.product.owner)
            html = view.render()
            link = first_tag_by_class(html, 'menu-link-subscribe')
            self.assertTrue(link is not None)
            link = first_tag_by_class(
                html, 'menu-link-subscribe_to_bug_mail')
            self.assertEqual(None, link)

    def test_subscribe_link_feature_flag_on(self):
        # Test the new subscription link.
        with FeatureFixture({self.feature_flag: 'on'}):
            self.assertEqual('on', getFeatureFlag(self.feature_flag))
            view = create_initialized_view(
                self.product, '+index', principal=self.product.owner)
            html = view.render()
            link = first_tag_by_class(html, 'menu-link-subscribe')
            self.assertEqual(None, link)
            link = first_tag_by_class(
                html, 'menu-link-subscribe_to_bug_mail')
            self.assertTrue(link is not None)
