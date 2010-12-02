# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test milestone views."""

__metaclass__ = type

from testtools.matchers import LessThan
from textwrap import dedent
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp import canonical_url
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.bugs.interfaces.bugtask import IBugTaskSet
from lp.testing import (
    ANONYMOUS,
    login,
    login_person,
    logout,
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.matchers import HasQueryCount
from lp.testing.memcache import MemcacheTestCase
from lp.testing.views import create_initialized_view
from lp.testing._webservice import QueryCollector


class TestMilestoneViews(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.product = self.factory.makeProduct()
        self.series = (
            self.factory.makeProductSeries(product=self.product))
        owner = self.product.owner
        login_person(owner)

    def test_add_milestone(self):
        form = {
            'field.name': '1.1',
            'field.actions.register': 'Register Milestone',
            }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        self.assertEqual([], view.errors)

    def test_add_milestone_with_good_date(self):
        form = {
            'field.name': '1.1',
            'field.dateexpected': '2010-10-10',
            'field.actions.register': 'Register Milestone',
            }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        # It's important to make sure no errors occured, but
        # but also confirm that the milestone was created.
        self.assertEqual([], view.errors)
        self.assertEqual('1.1', self.product.milestones[0].name)

    def test_add_milestone_with_bad_date(self):
        form = {
            'field.name': '1.1',
            'field.dateexpected': '1010-10-10',
            'field.actions.register': 'Register Milestone',
            }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        error_msg = view.errors[0].errors[0]
        expected_msg = (
            "Date could not be formatted. Provide a date formatted "
            "like YYYY-MM-DD format. The year must be after 1900.")
        self.assertEqual(expected_msg, error_msg)


class TestMilestoneMemcache(MemcacheTestCase):

    def setUp(self):
        super(TestMilestoneMemcache, self).setUp()
        product = self.factory.makeProduct()
        login_person(product.owner)
        series = self.factory.makeProductSeries(product=product)
        self.milestone = self.factory.makeMilestone(
            productseries=series, name="1.1")
        bugtask = self.factory.makeBugTask(target=product)
        bugtask.transitionToAssignee(product.owner)
        bugtask.milestone = self.milestone
        self.observer = self.factory.makePerson()

    def test_milestone_index_memcache_anonymous(self):
        # Miss the cache on first render.
        login(ANONYMOUS)
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Hit the cache on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheHit(
            '<dt>Assigned to you:</dt>',
            'anonymous, view/expire_cache_minutes minute', content)
        self.assertCacheHit(
            'id="milestone_bugtasks"',
            'anonymous, view/expire_cache_minutes minute', content)

    def test_milestone_index_memcache_no_cache_logged_in(self):
        login_person(self.observer)
        # Miss the cache on first render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Miss the cache again on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)

    def test_milestone_index_active_cache_time(self):
        # Verify the active milestone cache time.
        view = create_initialized_view(self.milestone, name='+index')
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)

    def test_milestone_index_inactive_cache_time(self):
        # Verify the inactive milestone cache time.
        self.milestone.active = False
        view = create_initialized_view(self.milestone, name='+index')
        self.assertFalse(view.milestone.active)
        self.assertEqual(360, view.expire_cache_minutes)


class TestMilestoneDeleteView(TestCaseWithFactory):
    """Test the delete rules applied by the Milestone Delete view."""

    layer = DatabaseFunctionalLayer

    def test_delete_conjoined_bugtask(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        master_bugtask = getUtility(IBugTaskSet).createTask(
            bug, productseries=product.development_focus, owner=product.owner)
        milestone = self.factory.makeMilestone(
            productseries=product.development_focus)
        login_person(product.owner)
        master_bugtask.transitionToMilestone(milestone, product.owner)
        form = {
            'field.actions.delete': 'Delete Milestone',
            }
        view = create_initialized_view(milestone, '+delete', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual([], list(product.all_milestones))
        self.assertEqual(0, product.development_focus.all_bugtasks.count())


class TestMilestoneIndexQueryCount(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestMilestoneIndexQueryCount, self).setUp()
        # Increase cache size so that the query counts aren't affected
        # by objects being removed from the cache early.
        config.push('storm-cache', dedent('''
            [launchpad]
            storm_cache_size: 1000
            '''))
        self.addCleanup(config.pop, 'storm-cache')
        owner = self.factory.makePerson(name='product-owner')
        self.product = self.factory.makeProduct(owner=owner)
        login_person(self.product.owner)
        self.milestone = self.factory.makeMilestone(
            productseries=self.product.development_focus)
        self.collector = QueryCollector()
        self.collector.register()
        self.addCleanup(self.collector.unregister)

    def add_bug(self, count):
        login_person(self.product.owner)
        for i in range(count):
            bug = self.factory.makeBug(
                product=self.product, private=True, owner=self.product.owner)
            bug.bugtasks[0].transitionToMilestone(
                self.milestone, self.product.owner)
            # This is necessary to test precaching of assignees.
            bug.bugtasks[0].transitionToAssignee(
                self.factory.makePerson())
        logout()

    def test_bugtasks_queries(self):
        # The view.bugtasks attribute will make four queries:
        #  1. Load bugtasks and bugs.
        #  2. Load assignees (Person, Account, and EmailAddress).
        #  3. Load links to specifications.
        #  4. Load links to branches.
        bugtask_count = 10
        self.add_bug(bugtask_count)
        login_person(self.product.owner)
        view = create_initialized_view(self.milestone, '+index')
        # Eliminate permission check for the admin team from the
        # recorded queries by loading it now. If the test ever breaks,
        # the person fixing it won't waste time trying to track this
        # query down.
        getUtility(ILaunchpadCelebrities).admin
        with StormStatementRecorder() as recorder:
            bugtasks = list(view.bugtasks)
        self.assertThat(recorder, HasQueryCount(LessThan(5)))
        self.assertEqual(bugtask_count, len(bugtasks))

    def test_milestone_eager_loading(self):
        # Verify that the number of queries does not increase with more
        # bugs with different assignees.
        milestone_url = canonical_url(self.milestone)
        query_limit = 34
        browser = self.getUserBrowser(user=self.product.owner)

        browser.open(milestone_url)
        self.assertThat(self.collector, HasQueryCount(LessThan(query_limit)))
        self.add_bug(3)
        browser.open(milestone_url)
        self.assertThat(self.collector, HasQueryCount(LessThan(query_limit)))

        self.add_bug(10)
        browser.open(milestone_url)
        self.assertThat(self.collector, HasQueryCount(LessThan(query_limit)))

    def test_more_private_bugs_query_count_is_constant(self):
        # This test tests that as we add more private bugs to a milestone
        # index page, the number of queries issued by the page does not
        # change. It also sets a cap on the queries for this page: if the
        # baseline were to increase, the test would fail. As the baseline
        # is very large already, if the test fails due to such a change,
        # please cut some more of the existing fat out of it rather than
        # increasing the cap.
        page_query_limit = 34
        product = self.factory.makeProduct()
        login_person(product.owner)
        milestone = self.factory.makeMilestone(
            productseries=product.development_focus)
        bug1 = self.factory.makeBug(product=product, private=True,
            owner=product.owner)
        bug1.bugtasks[0].transitionToMilestone(milestone, product.owner)
        # We look at the page as someone who is a member of a team and the
        # team is subscribed to the bugs, so that we don't get trivial
        # shortcuts avoiding queries : test the worst case.
        subscribed_team = self.factory.makeTeam()
        viewer = self.factory.makePerson(password="test")
        with person_logged_in(subscribed_team.teamowner):
            subscribed_team.addMember(viewer, subscribed_team.teamowner)
        bug1.subscribe(subscribed_team, product.owner)
        bug1_url = canonical_url(bug1)
        milestone_url = canonical_url(milestone)
        browser = self.getUserBrowser(user=viewer)
        # Seed the cookie cache and any other cross-request state we may gain
        # in future.  See canonical.launchpad.webapp.serssion: _get_secret.
        browser.open(milestone_url)
        collector = QueryCollector()
        collector.register()
        self.addCleanup(collector.unregister)
        browser.open(milestone_url)
        # Check that the test found the bug
        self.assertTrue(bug1_url in browser.contents)
        self.assertThat(collector, HasQueryCount(LessThan(page_query_limit)))
        with_1_private_bug = collector.count
        with_1_queries = ["%s: %s" % (pos, stmt[3]) for (pos, stmt) in
            enumerate(collector.queries)]
        login_person(product.owner)
        bug2 = self.factory.makeBug(product=product, private=True,
            owner=product.owner)
        bug2.bugtasks[0].transitionToMilestone(milestone, product.owner)
        bug2.subscribe(subscribed_team, product.owner)
        bug2_url = canonical_url(bug2)
        bug3 = self.factory.makeBug(product=product, private=True,
            owner=product.owner)
        bug3.bugtasks[0].transitionToMilestone(milestone, product.owner)
        bug3.subscribe(subscribed_team, product.owner)
        logout()
        browser.open(milestone_url)
        self.assertTrue(bug2_url in browser.contents)
        self.assertThat(collector, HasQueryCount(LessThan(page_query_limit)))
        with_3_private_bugs = collector.count
        with_3_queries = ["%s: %s" % (pos, stmt[3]) for (pos, stmt) in
            enumerate(collector.queries)]
        self.assertEqual(with_1_private_bug, with_3_private_bugs,
            "different query count: \n%s\n******************\n%s\n" % (
            '\n'.join(with_1_queries), '\n'.join(with_3_queries)))
