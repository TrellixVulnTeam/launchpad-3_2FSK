# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=F0401

"""Unit tests for TestP3APackages."""

__metaclass__ = type
__all__ = [
    'TestP3APackages',
    'TestPPAPackages',
    ]

from testtools.matchers import (
    Equals,
    LessThan,
    MatchesAny,
    )
from zope.security.interfaces import Unauthorized

from canonical.launchpad.webapp import canonical_url
from canonical.testing.layers import LaunchpadFunctionalLayer
from lp.soyuz.browser.archive import ArchiveNavigationMenu
from lp.testing import (
    login,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import ADMIN_EMAIL
from lp.testing.views import create_initialized_view
from lp.testing._webservice import QueryCollector


class TestP3APackages(TestCaseWithFactory):
    """P3A archive pages are rendered correctly."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestP3APackages, self).setUp()
        self.private_ppa = self.factory.makeArchive(description='Foo')
        login('admin@canonical.com')
        self.private_ppa.buildd_secret = 'blah'
        self.private_ppa.private = True
        self.joe = self.factory.makePerson(name='joe')
        self.fred = self.factory.makePerson(name='fred')
        self.mary = self.factory.makePerson(name='mary')
        login_person(self.private_ppa.owner)
        self.private_ppa.newSubscription(self.joe, self.private_ppa.owner)
        self.private_ppa.newComponentUploader(self.mary, 'main')

    def test_packages_unauthorized(self):
        """A person with no subscription will not be able to view +packages
        """
        login_person(self.fred)
        self.assertRaises(
            Unauthorized, create_initialized_view, self.private_ppa,
            "+packages")

    def test_packages_unauthorized_subscriber(self):
        """A person with a subscription will not be able to view +packages
        """
        login_person(self.joe)
        self.assertRaises(
            Unauthorized, create_initialized_view, self.private_ppa,
            "+packages")

    def test_packages_authorized(self):
        """A person with launchpad.{Append,Edit} will be able to do so"""
        login_person(self.private_ppa.owner)
        view = create_initialized_view(self.private_ppa, "+packages")
        menu = ArchiveNavigationMenu(view)
        self.assertTrue(menu.packages().enabled)

    def test_packages_uploader(self):
        """A person with launchpad.Append will also be able to do so"""
        login_person(self.mary)
        view = create_initialized_view(self.private_ppa, "+packages")
        menu = ArchiveNavigationMenu(view)
        self.assertTrue(menu.packages().enabled)

    def test_packages_link_unauthorized(self):
        login_person(self.fred)
        view = create_initialized_view(self.private_ppa, "+index")
        menu = ArchiveNavigationMenu(view)
        self.assertFalse(menu.packages().enabled)

    def test_packages_link_subscriber(self):
        login_person(self.joe)
        view = create_initialized_view(self.private_ppa, "+index")
        menu = ArchiveNavigationMenu(view)
        self.assertFalse(menu.packages().enabled)


class TestPPAPackages(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def getPackagesView(self, query_string=None):
        ppa = self.factory.makeArchive()
        return create_initialized_view(
            ppa, "+packages", query_string=query_string)

    def test_ppa_packages_menu_is_enabled(self):
        joe = self.factory.makePerson()
        ppa = self.factory.makeArchive()
        login_person(joe)
        view = create_initialized_view(ppa, "+index")
        menu = ArchiveNavigationMenu(view)
        self.assertTrue(menu.packages().enabled)

    def test_specified_name_filter_works(self):
        view = self.getPackagesView('field.name_filter=blah')
        self.assertEquals('blah', view.specified_name_filter)

    def test_specified_name_filter_returns_none_on_omission(self):
        view = self.getPackagesView()
        self.assertIs(None, view.specified_name_filter)

    def test_specified_name_filter_returns_none_on_empty_filter(self):
        view = self.getPackagesView('field.name_filter=')
        self.assertIs(None, view.specified_name_filter)

    def test_source_query_counts(self):
        query_baseline = 42
        # Assess the baseline.
        collector = QueryCollector()
        collector.register()
        self.addCleanup(collector.unregister)
        ppa = self.factory.makeArchive()
        viewer = self.factory.makePerson(password="test")
        browser = self.getUserBrowser(user=viewer)
        with person_logged_in(viewer):
            # The baseline has one package, because otherwise the short-circuit
            # prevents the packages iteration happening at all and we're not
            # actually measuring scaling appropriately.
            self.factory.makeSourcePackagePublishingHistory(archive=ppa)
            url = canonical_url(ppa) + "/+packages"
        browser.open(url)
        self.assertThat(collector, HasQueryCount(LessThan(query_baseline)))
        expected_count = collector.count
        # We scale with 1 query per distro series because of
        # getCurrentSourceReleases.
        expected_count += 1
        # We need a fuzz of one because if the test is the first to run a 
        # credentials lookup is done as well (and accrued to the collector).
        expected_count += 1
        # Use all new objects - avoids caching issues invalidating the gathered
        # metrics.
        login(ADMIN_EMAIL)
        ppa = self.factory.makeArchive()
        viewer = self.factory.makePerson(password="test")
        browser = self.getUserBrowser(user=viewer)
        with person_logged_in(viewer):
            for i in range(2):
                pkg = self.factory.makeSourcePackagePublishingHistory(
                    archive=ppa)
                self.factory.makeSourcePackagePublishingHistory(archive=ppa,
                    distroseries=pkg.distroseries)
            url = canonical_url(ppa) + "/+packages"
        browser.open(url)
        self.assertThat(collector, HasQueryCount(LessThan(expected_count)))

    def test_binary_query_counts(self):
        query_baseline = 26
        # Assess the baseline.
        collector = QueryCollector()
        collector.register()
        self.addCleanup(collector.unregister)
        ppa = self.factory.makeArchive()
        viewer = self.factory.makePerson(password="test")
        browser = self.getUserBrowser(user=viewer)
        with person_logged_in(viewer):
            # The baseline has one package, because otherwise the short-circuit
            # prevents the packages iteration happening at all and we're not
            # actually measuring scaling appropriately.
            self.factory.makeBinaryPackagePublishingHistory(archive=ppa)
            url = canonical_url(ppa) + "/+packages"
        browser.open(url)
        self.assertThat(collector, HasQueryCount(
            MatchesAny(LessThan(query_baseline), Equals(query_baseline))))
        expected_count = collector.count
        # Use all new objects - avoids caching issues invalidating the gathered
        # metrics.
        login(ADMIN_EMAIL)
        ppa = self.factory.makeArchive()
        viewer = self.factory.makePerson(password="test")
        browser = self.getUserBrowser(user=viewer)
        with person_logged_in(viewer):
            for i in range(2):
                pkg = self.factory.makeBinaryPackagePublishingHistory(
                    archive=ppa)
                self.factory.makeBinaryPackagePublishingHistory(archive=ppa,
                    distroarchseries=pkg.distroarchseries)
            url = canonical_url(ppa) + "/+packages"
        browser.open(url)
        self.assertThat(collector, HasQueryCount(
            MatchesAny(Equals(expected_count), LessThan(expected_count))))
