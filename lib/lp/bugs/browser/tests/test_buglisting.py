# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from storm.expr import LeftJoin
from storm.store import Store
from testtools.matchers import Equals
from zope.component import getUtility

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.testing.pages import (
    extract_text,
    find_tag_by_id,
    find_tags_by_class,
    )
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.bugs.model.bugtask import BugTask
from lp.registry.model.person import Person
from lp.testing import (
    BrowserTestCase,
    login,
    login_person,
    logout,
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )

from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_initialized_view


class DeactivatedContextBugTaskTestCase(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(DeactivatedContextBugTaskTestCase, self).setUp()
        self.person = self.factory.makePerson()
        self.active_product = self.factory.makeProduct()
        self.inactive_product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=self.active_product)
        self.active_bugtask = self.factory.makeBugTask(
            bug=bug,
            target=self.active_product)
        self.inactive_bugtask = self.factory.makeBugTask(
            bug=bug,
            target=self.inactive_product)
        with person_logged_in(self.person):
            self.active_bugtask.transitionToAssignee(self.person)
            self.inactive_bugtask.transitionToAssignee(self.person)
        login('admin@canonical.com')
        self.inactive_product.active = False
        logout()

    def test_deactivated_listings_not_seen(self):
        # Someone without permission to see deactiveated projects does
        # not see bugtasks for deactivated projects.
        login('no-priv@canonical.com')
        view = create_initialized_view(self.person, "+bugs")
        self.assertEqual([self.active_bugtask], list(view.searchUnbatched()))


class TestBugTaskSearchListingPage(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def _makeDistributionSourcePackage(self):
        distro = self.factory.makeDistribution('test-distro')
        return self.factory.makeDistributionSourcePackage('test-dsp', distro)

    def test_distributionsourcepackage_unknown_bugtracker_message(self):
        # A DistributionSourcePackage whose Distro does not use
        # Launchpad for bug tracking should explain that.
        dsp = self._makeDistributionSourcePackage()
        url = canonical_url(dsp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        top_portlet = find_tags_by_class(
            browser.contents, 'top-portlet')
        self.assertTrue(len(top_portlet) > 0,
                        "Tag with class=top-portlet not found")
        self.assertTextMatchesExpressionIgnoreWhitespace("""
            test-dsp in test-distro does not use Launchpad for bug tracking.
            Getting started with bug tracking in Launchpad.""",
            extract_text(top_portlet[0]))

    def test_distributionsourcepackage_unknown_bugtracker_no_button(self):
        # A DistributionSourcePackage whose Distro does not use
        # Launchpad for bug tracking should not show the "Report a bug"
        # button.
        dsp = self._makeDistributionSourcePackage()
        url = canonical_url(dsp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None, find_tag_by_id(browser.contents, 'involvement'),
                      "Involvement portlet with Report-a-bug button should "
                      "not be shown")

    def test_distributionsourcepackage_unknown_bugtracker_no_filters(self):
        # A DistributionSourcePackage whose Distro does not use
        # Launchpad for bug tracking should not show links to "New
        # bugs", "Open bugs", etc.
        dsp = self._makeDistributionSourcePackage()
        url = canonical_url(dsp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None,
                      find_tag_by_id(browser.contents, 'portlet-bugfilters'),
                      "portlet-bugfilters should not be shown.")

    def test_distributionsourcepackage_unknown_bugtracker_no_tags(self):
        # A DistributionSourcePackage whose Distro does not use
        # Launchpad for bug tracking should not show links to search by
        # bug tags.
        dsp = self._makeDistributionSourcePackage()
        url = canonical_url(dsp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None, find_tag_by_id(browser.contents, 'portlet-tags'),
                      "portlet-tags should not be shown.")

    def _makeSourcePackage(self):
        distro = self.factory.makeDistribution('test-distro')
        series = self.factory.makeDistroRelease(
            distribution=distro, name='test-series')
        return self.factory.makeSourcePackage('test-sp', distro.currentseries)

    def test_sourcepackage_unknown_bugtracker_message(self):
        # A SourcePackage whose Distro does not use
        # Launchpad for bug tracking should explain that.
        sp = self._makeSourcePackage()
        url = canonical_url(sp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        top_portlet = find_tags_by_class(
            browser.contents, 'top-portlet')
        self.assertTrue(len(top_portlet) > 0,
                        "Tag with class=top-portlet not found")
        self.assertTextMatchesExpressionIgnoreWhitespace("""
            test-sp in Test-distro Test-series does not
            use Launchpad for bug tracking.
            Getting started with bug tracking in Launchpad.""",
            extract_text(top_portlet[0]))

    def test_sourcepackage_unknown_bugtracker_no_button(self):
        # A SourcePackage whose Distro does not use Launchpad for bug
        # tracking should not show the "Report a bug" button.
        sp = self._makeSourcePackage()
        url = canonical_url(sp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None, find_tag_by_id(browser.contents, 'involvement'),
                      "Involvement portlet with Report-a-bug button should "
                      "not be shown")

    def test_sourcepackage_unknown_bugtracker_no_filters(self):
        # A SourcePackage whose Distro does not use Launchpad for bug
        # tracking should not show links to "New bugs", "Open bugs",
        # etc.
        sp = self._makeSourcePackage()
        url = canonical_url(sp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None,
                      find_tag_by_id(browser.contents, 'portlet-bugfilters'),
                      "portlet-bugfilters should not be shown.")

    def test_sourcepackage_unknown_bugtracker_no_tags(self):
        # A SourcePackage whose Distro does not use Launchpad for bug
        # tracking should not show links to search by bug tags.
        sp = self._makeSourcePackage()
        url = canonical_url(sp, rootsite='bugs')
        browser = self.getUserBrowser(url)
        self.assertIs(None,
                      find_tag_by_id(browser.contents, 'portlet-tags'),
                      "portlet-tags should not be shown.")

    def test_searchUnbatched_can_preload_objects(self):
        # BugTaskSearchListingView.searchUnbatched() can optionally
        # preload objects while retrieving the bugtasks.
        product = self.factory.makeProduct()
        bugtask_1 = self.factory.makeBug(product=product).default_bugtask
        bugtask_2 = self.factory.makeBug(product=product).default_bugtask
        view = create_initialized_view(product, '+bugs')
        Store.of(product).invalidate()
        with StormStatementRecorder() as recorder:
            prejoins=[(Person, LeftJoin(Person, BugTask.owner==Person.id))]
            bugtasks = list(view.searchUnbatched(prejoins=prejoins))
            self.assertEqual(
                [bugtask_1, bugtask_2], bugtasks)
            # If the table prejoin failed, then this will issue two
            # additional SQL queries
            [bugtask.owner for bugtask in bugtasks]
        self.assertThat(recorder, HasQueryCount(Equals(2)))


class BugTargetTestCase(TestCaseWithFactory):
    """Test helpers for setting up `IBugTarget` tests."""

    def _makeBugTargetProduct(self, bug_tracker=None, packaging=False):
        """Return a product that may use Launchpad or an external bug tracker.

        bug_tracker may be None, 'launchpad', or 'external'.
        """
        product = self.factory.makeProduct()
        if bug_tracker is not None:
            with person_logged_in(product.owner):
                if bug_tracker == 'launchpad':
                    product.official_malone = True
                else:
                    product.bugtracker = self.factory.makeBugTracker()
        if packaging:
            self.factory.makePackagingLink(
                productseries=product.development_focus, in_ubuntu=True)
        return product


class TestBugTaskSearchListingViewProduct(BugTargetTestCase):

    layer = DatabaseFunctionalLayer

    def test_external_bugtracker_is_none(self):
        bug_target = self._makeBugTargetProduct()
        view = create_initialized_view(bug_target, '+bugs')
        self.assertEqual(None, view.external_bugtracker)

    def test_external_bugtracker(self):
        bug_target = self._makeBugTargetProduct(bug_tracker='external')
        view = create_initialized_view(bug_target, '+bugs')
        self.assertEqual(bug_target.bugtracker, view.external_bugtracker)

    def test_has_bugtracker_is_false(self):
        bug_target = self.factory.makeProduct()
        view = create_initialized_view(bug_target, '+bugs')
        self.assertEqual(False, view.has_bugtracker)

    def test_has_bugtracker_external_is_true(self):
        bug_target = self._makeBugTargetProduct(bug_tracker='external')
        view = create_initialized_view(bug_target, '+bugs')
        self.assertEqual(True, view.has_bugtracker)

    def test_has_bugtracker_launchpad_is_true(self):
        bug_target = self._makeBugTargetProduct(bug_tracker='launchpad')
        view = create_initialized_view(bug_target, '+bugs')
        self.assertEqual(True, view.has_bugtracker)

    def test_product_without_packaging_also_in_ubuntu_is_none(self):
        bug_target = self._makeBugTargetProduct(bug_tracker='launchpad')
        login_person(bug_target.owner)
        view = create_initialized_view(
            bug_target, '+bugs', principal=bug_target.owner)
        self.assertEqual(None, find_tag_by_id(view(), 'also-in-ubuntu'))

    def test_product_with_packaging_also_in_ubuntu(self):
        bug_target = self._makeBugTargetProduct(
            bug_tracker='launchpad', packaging=True)
        login_person(bug_target.owner)
        view = create_initialized_view(
            bug_target, '+bugs', principal=bug_target.owner)
        content = find_tag_by_id(view.render(), 'also-in-ubuntu')
        link = canonical_url(
            bug_target.ubuntu_packages[0], force_local_path=True)
        self.assertEqual(link, content.a['href'])


class TestBugTaskSearchListingViewDSP(BugTargetTestCase):

    layer = DatabaseFunctionalLayer

    def _getBugTarget(self, obj):
        """Return the `IBugTarget` under test.

        Return the object that was passed. Sub-classes can redefine
        this method.
        """
        return obj

    def test_package_with_upstream_launchpad_project(self):
        upstream_project = self._makeBugTargetProduct(
            bug_tracker='launchpad', packaging=True)
        login_person(upstream_project.owner)
        bug_target = self._getBugTarget(
            upstream_project.distrosourcepackages[0])
        view = create_initialized_view(
            bug_target, '+bugs', principal=upstream_project.owner)
        self.assertEqual(upstream_project, view.upstream_launchpad_project)
        content = find_tag_by_id(view.render(), 'also-in-upstream')
        link = canonical_url(upstream_project, rootsite='bugs')
        self.assertEqual(link, content.a['href'])

    def test_package_with_upstream_nonlaunchpad_project(self):
        upstream_project = self._makeBugTargetProduct(packaging=True)
        login_person(upstream_project.owner)
        bug_target = self._getBugTarget(
            upstream_project.distrosourcepackages[0])
        view = create_initialized_view(
            bug_target, '+bugs', principal=upstream_project.owner)
        self.assertEqual(None, view.upstream_launchpad_project)
        self.assertEqual(None, find_tag_by_id(view(), 'also-in-upstream'))

    def test_package_without_upstream_project(self):
        observer = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage(
            'test-dsp', distribution=getUtility(ILaunchpadCelebrities).ubuntu)
        bug_target = self._getBugTarget(dsp)
        login_person(observer)
        view = create_initialized_view(
            bug_target, '+bugs', principal=observer)
        self.assertEqual(None, view.upstream_launchpad_project)
        self.assertEqual(None, find_tag_by_id(view(), 'also-in-upstream'))


class TestBugTaskSearchListingViewSP(TestBugTaskSearchListingViewDSP):

        def _getBugTarget(self, dsp):
            """Return the current `ISourcePackage` for the dsp."""
            return dsp.development_version
