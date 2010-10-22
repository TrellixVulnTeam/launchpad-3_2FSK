# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for branch listing."""

from __future__ import with_statement

__metaclass__ = type

from datetime import timedelta
from pprint import pformat
import re
import unittest

from lazr.uri import URI
from storm.expr import (
    Asc,
    Desc,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.testing.pages import (
    extract_text,
    find_tag_by_id,
    )
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.code.browser.branchlisting import (
    BranchListingSort,
    BranchListingView,
    GroupedDistributionSourcePackageBranchesView,
    SourcePackageBranchesView,
    )
from lp.code.enums import BranchVisibilityRule
from lp.code.interfaces.seriessourcepackagebranch import (
    IMakeOfficialBranchLinks,
    )
from lp.code.model.branch import Branch
from lp.registry.interfaces.person import (
    IPersonSet,
    PersonVisibility,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.person import Owner
from lp.registry.model.product import Product
from lp.testing import (
    BrowserTestCase,
    login_person,
    person_logged_in,
    TestCase,
    TestCaseWithFactory,
    time_counter,
    )
from lp.testing.factory import remove_security_proxy_and_shout_at_engineer
from lp.testing.sampledata import (
    ADMIN_EMAIL,
    COMMERCIAL_ADMIN_EMAIL,
    )
from lp.testing.views import create_initialized_view


class TestListingToSortOrder(TestCase):
    """Tests for the BranchSet._listingSortToOrderBy static method.

    This method translates values from the BranchListingSort enumeration into
    values suitable to pass to orderBy in queries against BranchWithSortKeys.
    """

    DEFAULT_BRANCH_LISTING_SORT = [
        Asc(Product.name),
        Desc(Branch.lifecycle_status),
        Asc(Owner.name),
        Asc(Branch.name),
        ]

    def assertColumnNotReferenced(self, column, order_by_list):
        """Ensure that column is not referenced in any way in order_by_list.
        """
        self.failIf(column in order_by_list or
                    ('-' + column) in order_by_list)

    def assertSortsEqual(self, sort_one, sort_two):
        """Assert that one list of sort specs is equal to another."""

        def sort_data(sort):
            return sort.suffix, sort.expr
        self.assertEqual(map(sort_data, sort_one), map(sort_data, sort_two))

    def test_default(self):
        """Test that passing None results in the default list."""
        self.assertSortsEqual(
            self.DEFAULT_BRANCH_LISTING_SORT,
            BranchListingView._listingSortToOrderBy(None))

    def test_lifecycle(self):
        """Test with an option that's part of the default sort.

        Sorting on LIFECYCYLE moves the lifecycle reference to the
        first element of the output."""
        # Check that this isn't a no-op.
        lifecycle_order = BranchListingView._listingSortToOrderBy(
            BranchListingSort.LIFECYCLE)
        self.assertSortsEqual(
            [Desc(Branch.lifecycle_status),
             Asc(Product.name),
             Asc(Owner.name),
             Asc(Branch.name)], lifecycle_order)

    def test_sortOnColumNotInDefaultSortOrder(self):
        """Test with an option that's not part of the default sort.

        This should put the passed option first in the list, but leave
        the rest the same.
        """
        registrant_order = BranchListingView._listingSortToOrderBy(
            BranchListingSort.OLDEST_FIRST)
        self.assertSortsEqual(
            [Asc(Branch.date_created)] + self.DEFAULT_BRANCH_LISTING_SORT,
            registrant_order)


class TestPersonOwnedBranchesView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()
        login_person(self.user)

        self.barney = self.factory.makePerson(name='barney')
        self.bambam = self.factory.makeProduct(name='bambam')

        time_gen = time_counter(delta=timedelta(days=-1))
        self.branches = [
            self.factory.makeProductBranch(
                product=self.bambam, owner=self.barney,
                date_created=time_gen.next())
            for i in range(5)]
        self.bug = self.factory.makeBug()
        self.bug.linkBranch(self.branches[0], self.barney)
        self.spec = self.factory.makeSpecification()
        self.spec.linkBranch(self.branches[1], self.barney)

    def test_branch_ids_with_bug_links(self):
        # _branches_for_current_batch should return a list of all branches in
        # the current batch.
        branch_ids = set([self.branches[0].id])

        view = create_initialized_view(
            self.barney, name="+branches", rootsite='code')
        self.assertEqual(
            view.branches().branch_ids_with_bug_links,
            branch_ids)

    def test_branch_ids_with_spec_links(self):
        # _branches_for_current_batch should return a list of all branches in
        # the current batch.
        branch_ids = set([self.branches[1].id])

        view = create_initialized_view(
            self.barney, name="+branches", rootsite='code')
        self.assertEqual(
            view.branches().branch_ids_with_spec_links,
            branch_ids)

    def test_branch_ids_with_merge_propoasls(self):
        # _branches_for_current_batch should return a list of all branches in
        # the current batch.
        branch_ids = set([])
        view = create_initialized_view(
            self.barney, name="+branches", rootsite='code')
        self.assertEqual(
            view.branches().branch_ids_with_merge_proposals,
            branch_ids)

    def test_tip_revisions(self):
        # _branches_for_current_batch should return a list of all branches in
        # the current batch.
        branch_ids = [branch.id for branch in self.branches]
        tip_revisions = {}
        for branch_id in branch_ids:
            tip_revisions[branch_id] = None

        view = create_initialized_view(
            self.barney, name="+branches", rootsite='code')
        self.assertEqual(
            view.branches().tip_revisions,
            tip_revisions)


class TestSourcePackageBranchesView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_distroseries_links(self):
        # There are some links at the bottom of the page to other
        # distroseries.
        distro = self.factory.makeDistribution()
        sourcepackagename = self.factory.makeSourcePackageName()
        packages = {}
        for version in ("1.0", "2.0", "3.0"):
            series = self.factory.makeDistroRelease(
                distribution=distro, version=version)
            package = self.factory.makeSourcePackage(
                distroseries=series, sourcepackagename=sourcepackagename)
            packages[version] = package
        request = LaunchpadTestRequest()
        view = SourcePackageBranchesView(packages["2.0"], request)
        self.assertEqual(
            [dict(series_name=packages["3.0"].distroseries.displayname,
                  package=packages["3.0"], linked=True,
                  num_branches='0 branches',
                  dev_focus_css='sourcepackage-dev-focus',
                  ),
             dict(series_name=packages["2.0"].distroseries.displayname,
                  package=packages["2.0"], linked=False,
                  num_branches='0 branches',
                  dev_focus_css='sourcepackage-not-dev-focus',
                  ),
             dict(series_name=packages["1.0"].distroseries.displayname,
                  package=packages["1.0"], linked=True,
                  num_branches='0 branches',
                  dev_focus_css='sourcepackage-not-dev-focus',
                  ),
             ],
            list(view.series_links))


class TestGroupedDistributionSourcePackageBranchesView(TestCaseWithFactory):
    """Test the groups for the branches of distribution source packages."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        # Make a distro with some series, a source package name, and a distro
        # source package.
        self.distro = self.factory.makeDistribution()
        for version in ("1.0", "2.0", "3.0"):
            self.factory.makeDistroRelease(
                distribution=self.distro, version=version)
        self.sourcepackagename = self.factory.makeSourcePackageName()
        self.distro_source_package = (
            self.factory.makeDistributionSourcePackage(
                distribution=self.distro,
                sourcepackagename=self.sourcepackagename))

    def test_groups_with_no_branches(self):
        # If there are no branches for a series, the groups are not there.
        view = GroupedDistributionSourcePackageBranchesView(
            self.distro_source_package, LaunchpadTestRequest())
        self.assertEqual([], view.groups)

    def makeBranches(self, branch_count, official_count=0):
        """Make some package branches.

        Make `branch_count` branches, and make `official_count` of those
        official branches.
        """
        distroseries = self.distro.series[0]
        # Make the branches created in the past in order.
        time_gen = time_counter(delta=timedelta(days=-1))
        branches = [
            self.factory.makePackageBranch(
                distroseries=distroseries,
                sourcepackagename=self.sourcepackagename,
                date_created=time_gen.next())
            for i in range(branch_count)]

        official = []
        # We don't care about who can make things official, so get rid of the
        # security proxy.
        series_set = removeSecurityProxy(getUtility(IMakeOfficialBranchLinks))
        # Sort the pocket items so RELEASE is last, and thus first popped.
        pockets = sorted(PackagePublishingPocket.items, reverse=True)
        for i in range(official_count):
            branch = branches.pop()
            pocket = pockets.pop()
            sspb = series_set.new(
                distroseries, pocket, self.sourcepackagename,
                branch, branch.owner)
            official.append(branch)

        return distroseries, branches, official

    def assertMoreBranchCount(self, expected, series):
        """Check that the more-branch-count is the expected value."""
        view = GroupedDistributionSourcePackageBranchesView(
            self.distro_source_package, LaunchpadTestRequest())
        series_group = view.groups[0]
        self.assertEqual(expected, series_group['more-branch-count'])

    def test_more_branch_count_zero(self):
        # If there are less than six branches, the more-branch-count is zero.
        series, ignored, ignored = self.makeBranches(5)
        self.assertMoreBranchCount(0, series)

    def test_more_branch_count_nonzero(self):
        # If there are more than five branches, the more-branch-count is the
        # total branch count less five.
        series, ignored, ignored = self.makeBranches(8)
        self.assertMoreBranchCount(3, series)

    def assertGroupBranchesEqual(self, expected, series):
        """Check that the branches part of the series dict match."""
        view = GroupedDistributionSourcePackageBranchesView(
            self.distro_source_package, LaunchpadTestRequest())
        series_group = view.groups[0]
        branches = series_group['branches']
        self.assertEqual(len(expected), len(branches),
                         "%s different length to %s" %
                         (pformat(expected), pformat(branches)))
        for b1, b2 in zip(expected, branches):
            # Since one is a branch and the other is a decorated branch,
            # just check the ids.
            self.assertEqual(b1.id, b2.id)

    def test_series_branch_order_no_official(self):
        # If there are no official branches, then the branches are in most
        # recently modified order, with at most five in the list.
        series, branches, official = self.makeBranches(8)
        self.assertGroupBranchesEqual(branches[:5], series)

    def test_series_branch_order_official_first(self):
        # If there is an official branch, it comes first in the list.
        series, branches, official = self.makeBranches(8, 1)
        expected = official + branches[:4]
        self.assertGroupBranchesEqual(expected, series)

    def test_series_branch_order_two_three(self):
        # If there are more than two official branches, and there are three or
        # more user branches, then only two of the official branches will be
        # shown, ordered by pocket.
        series, branches, official = self.makeBranches(8, 3)
        expected = official[:2] + branches[:3]
        self.assertGroupBranchesEqual(expected, series)

    def test_series_branch_order_three_two(self):
        # If there are more than two official branches, but there are less
        # than three user branches, then official branches are added in until
        # there are at most five branches.
        series, branches, official = self.makeBranches(6, 4)
        expected = official[:3] + branches
        self.assertGroupBranchesEqual(expected, series)


class TestDevelopmentFocusPackageBranches(TestCaseWithFactory):
    """Make sure that the bzr_identity of the branches are correct."""

    layer = DatabaseFunctionalLayer

    def test_package_development_focus(self):
        # Check the bzr_identity of a development focus package branch.
        branch = self.factory.makePackageBranch()
        series_set = removeSecurityProxy(getUtility(IMakeOfficialBranchLinks))
        sspb = series_set.new(
            branch.distroseries, PackagePublishingPocket.RELEASE,
            branch.sourcepackagename, branch, branch.owner)
        identity = "lp://dev/%s/%s" % (
            branch.distribution.name, branch.sourcepackagename.name)
        self.assertEqual(identity, branch.bzr_identity)
        # Now confirm that we get the same through the view.
        view = create_initialized_view(
            branch.distribution, name='+branches', rootsite='code')
        # There is only one branch.
        batch = view.branches()
        [view_branch] = batch.branches
        self.assertStatementCount(0, getattr, view_branch, 'bzr_identity')
        self.assertEqual(identity, view_branch.bzr_identity)


class TestProductSeriesTemplate(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_product_series_link(self):
        # The link from a series branch's listing to the series goes to the
        # series on the main site, not the code site.
        branch = self.factory.makeProductBranch()
        series = self.factory.makeProductSeries(product=branch.product)
        remove_security_proxy_and_shout_at_engineer(series).branch = branch
        browser = self.getUserBrowser(
            canonical_url(branch.product, rootsite='code'))
        link = browser.getLink(re.compile('^' + series.name + '$'))
        self.assertEqual('launchpad.dev', URI(link.url).host)


class TestPersonBranchesPage(BrowserTestCase):
    """Tests for the person branches page.

    This is the default page shown for a person on the code subdomain.
    """

    layer = DatabaseFunctionalLayer

    def _make_branch_for_private_team(self):
        private_team = self.factory.makeTeam(
            name='shh', displayname='Shh',
            visibility=PersonVisibility.PRIVATE)
        member = self.factory.makePerson(
            email='member@example.com', password='test')
        with person_logged_in(private_team.teamowner):
            private_team.addMember(member, private_team.teamowner)
        branch = self.factory.makeProductBranch(owner=private_team)
        return private_team, member, branch

    def test_private_team_membership_for_team_member(self):
        # If the logged in user can see the private teams, they are shown in
        # the related 'Branches owned by' section at the bottom of the page.
        private_team, member, branch = self._make_branch_for_private_team()
        browser = self.getUserBrowser(
            canonical_url(member, rootsite='code'), member)
        branches = find_tag_by_id(browser.contents, 'portlet-team-branches')
        text = extract_text(branches)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            'Branches owned by Shh', text)

    def test_private_team_membership_for_non_member(self):
        # Make sure that private teams are not shown (or attempted to be
        # shown) for people who can not see the private teams.
        private_team, member, branch = self._make_branch_for_private_team()
        browser = self.getUserBrowser(canonical_url(member, rootsite='code'))
        branches = find_tag_by_id(browser.contents, 'portlet-team-branches')
        # Since there are no teams with branches that the user can see, the
        # portlet isn't shown.
        self.assertIs(None, branches)


class TestProjectBranchListing(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProjectBranchListing, self).setUp()
        self.project = self.factory.makeProject()
        self.product = self.factory.makeProduct(project=self.project)

    def test_no_branches_gets_message_not_listing(self):
        # If there are no product branches on the project's products, then
        # the view shows the no code hosting message instead of a listing.
        browser = self.getUserBrowser(
            canonical_url(self.project, rootsite='code'))
        displayname = self.project.displayname
        expected_text = normalize_whitespace(
                            ("Launchpad does not know where any of %s's "
                             "projects host their code." % displayname))
        no_branch_div = find_tag_by_id(browser.contents, "no-branchtable")
        text = normalize_whitespace(extract_text(no_branch_div))
        self.assertEqual(expected_text, text)

    def test_branches_get_listing(self):
        # If a product has a branch, then the project view has a branch
        # listing.
        branch = self.factory.makeProductBranch(product=self.product)
        browser = self.getUserBrowser(
            canonical_url(self.project, rootsite='code'))
        table = find_tag_by_id(browser.contents, "branchtable")
        self.assertIsNot(None, table)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
