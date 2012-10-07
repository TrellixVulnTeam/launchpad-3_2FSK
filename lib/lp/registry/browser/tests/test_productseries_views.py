# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""View tests for ProductSeries pages."""

__metaclass__ = type


import soupmatchers
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.bugs.interfaces.bugtask import (
    BugTaskStatus,
    BugTaskStatusSearch,
    )
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import Contains
from lp.testing.views import create_initialized_view


class TestProductSeries(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_information_type_public(self):
        # A ProductSeries view should include its information_type,
        # which defaults to Public for new projects.
        series = self.factory.makeProductSeries()
        view = create_initialized_view(series, '+index')
        self.assertEqual('Public', view.information_type)

    def test_information_type_proprietary(self):
        # A ProductSeries view should get its information_type
        # from the related product even if the product is changed to
        # PROPRIETARY.
        product = self.factory.makeProduct()
        self.factory.makeCommercialSubscription(product)
        information_type = InformationType.PROPRIETARY
        removeSecurityProxy(product).information_type = information_type
        series = self.factory.makeProductSeries(product=product)
        view = create_initialized_view(series, '+index')
        self.assertEqual('Proprietary', view.information_type)

    def test_privacy_portlet(self):
        # A ProductSeries page should include a privacy portlet that
        # accurately describes the information_type.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct(owner=owner)
        self.factory.makeCommercialSubscription(product)
        information_type = InformationType.PROPRIETARY
        removeSecurityProxy(product).information_type = information_type
        series = self.factory.makeProductSeries(product=product)
        policy = self.factory.makeAccessPolicy(pillar=product)
        grant = self.factory.makeAccessPolicyGrant(
            policy=policy, grantee=owner)
        privacy_portlet = soupmatchers.Tag(
            'info-type-portlet', 'span',
            attrs={'id': 'information-type-summary'})
        privacy_portlet_proprietary = soupmatchers.Tag(
            'info-type-text', 'strong', attrs={'id': 'information-type'},
            text='Proprietary')
        browser = self.getViewBrowser(series, '+index', user=owner)
        # First, assert that the portlet exists.
        self.assertThat(
            browser.contents, soupmatchers.HTMLContains(privacy_portlet))
        # Then, assert that the text displayed matches the information_type.
        self.assertThat(
            browser.contents, soupmatchers.HTMLContains(
            privacy_portlet_proprietary))


class TestProductSeriesHelp(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_new_series_help(self):
        # The LP branch URL displayed to the user on the +code-summary page
        # for a product series will relate to that series instead of to the
        # default series for the Product.
        product = self.factory.makeProduct()
        series = self.factory.makeProductSeries(product=product)
        person = product.owner
        branch_url = "lp:~%s/%s/%s" % (person.name, product.name, series.name)
        with person_logged_in(person):
            self.factory.makeSSHKey(person=person)
            view = create_initialized_view(series, '+code-summary')
            self.assertThat(view(), Contains(branch_url))


class TestWithBrowser(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_timeline_graph(self):
        """Test that rendering the graph does not raise an exception."""
        productseries = self.factory.makeProductSeries()
        self.getViewBrowser(productseries, view_name='+timeline-graph')

    def test_meaningful_branch_name(self):
        """The displayed branch name should include the unique name."""
        branch = self.factory.makeProductBranch()
        series = self.factory.makeProductSeries(branch=branch)
        tag = soupmatchers.Tag('series-branch', 'a',
                               attrs={'id': 'series-branch'},
                               text='lp://dev/' + branch.unique_name)
        browser = self.getViewBrowser(series)
        self.assertThat(browser.contents, soupmatchers.HTMLContains(tag))


class TestProductSeriesStatus(TestCaseWithFactory):
    """Tests for ProductSeries:+status."""

    layer = DatabaseFunctionalLayer

    def test_bugtask_status_counts(self):
        """Test that `bugtask_status_counts` is sane."""
        product = self.factory.makeProduct()
        series = self.factory.makeProductSeries(product=product)
        for status in BugTaskStatusSearch.items:
            self.factory.makeBug(
                series=series, status=status,
                owner=product.owner)
        self.factory.makeBug(
            series=series, status=BugTaskStatus.UNKNOWN,
            owner=product.owner)
        expected = [
            (BugTaskStatus.NEW, 1),
            (BugTaskStatusSearch.INCOMPLETE_WITH_RESPONSE, 1),
            # 2 because INCOMPLETE is stored as INCOMPLETE_WITH_RESPONSE or
            # INCOMPLETE_WITHOUT_RESPONSE, and there was no response for the
            # bug created as INCOMPLETE.
            (BugTaskStatusSearch.INCOMPLETE_WITHOUT_RESPONSE, 2),
            (BugTaskStatus.OPINION, 1),
            (BugTaskStatus.INVALID, 1),
            (BugTaskStatus.WONTFIX, 1),
            (BugTaskStatus.EXPIRED, 1),
            (BugTaskStatus.CONFIRMED, 1),
            (BugTaskStatus.TRIAGED, 1),
            (BugTaskStatus.INPROGRESS, 1),
            (BugTaskStatus.FIXCOMMITTED, 1),
            (BugTaskStatus.FIXRELEASED, 1),
            (BugTaskStatus.UNKNOWN, 1),
            ]
        with person_logged_in(product.owner):
            view = create_initialized_view(series, '+status')
            observed = [
                (status_count.status, status_count.count)
                for status_count in view.bugtask_status_counts]
        self.assertEqual(expected, observed)
