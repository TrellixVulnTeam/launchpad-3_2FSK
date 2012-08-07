# Copyright 2010-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test milestone views."""

__metaclass__ = type

from textwrap import dedent

from testtools.matchers import LessThan
from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.interfaces.bugtask import IBugTaskSet
from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams
from lp.registry.enums import InformationType
from lp.registry.interfaces.person import TeamSubscriptionPolicy
from lp.registry.model.milestonetag import ProjectGroupMilestoneTag
from lp.services.config import config
from lp.services.webapp import canonical_url
from lp.testing import (
    login_person,
    login_team,
    logout,
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing._webservice import QueryCollector
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import (
    BrowsesWithQueryLimit,
    HasQueryCount,
    )
from lp.testing.views import create_initialized_view


class TestMilestoneViews(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_distroseries_milestone(self):
        # Distribution milestone with an untargeted blueprint containing
        # work items targeted to the milestone lists this blueprint
        # with a special note.
        distro_series = self.factory.makeDistroSeries()
        distribution = distro_series.distribution
        milestone = self.factory.makeMilestone(distroseries=distro_series)
        specification = self.factory.makeSpecification(
            distribution=distribution)
        self.factory.makeSpecificationWorkItem(
            specification=specification, milestone=milestone)
        view = create_initialized_view(milestone, '+index')
        self.assertIn('some work for this milestone', view.render())


class TestAddMilestoneViews(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.product = self.factory.makeProduct()
        self.series = (
            self.factory.makeProductSeries(product=self.product))
        self.owner = self.product.owner
        login_person(self.owner)

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
        # It's important to make sure no errors occured,
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

    def test_add_milestone_with_tags(self):
        tags = u'zed alpha'
        form = {
            'field.name': '1.1',
            'field.tags': tags,
            'field.actions.register': 'Register Milestone',
            }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        self.assertEqual([], view.errors)
        expected = sorted(tags.split())
        self.assertEqual(expected, self.product.milestones[0].getTags())


class TestMilestoneEditView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.product = self.factory.makeProduct()
        self.milestone = self.factory.makeMilestone(
            name='orig-name', product=self.product)
        self.owner = self.product.owner
        login_person(self.owner)

    def test_edit_milestone_with_tags(self):
        orig_tags = u'b a c'
        self.milestone.setTags(orig_tags.split(), self.owner)
        new_tags = u'z a B'
        form = {
            'field.name': 'new-name',
            'field.tags': new_tags,
            'field.actions.update': 'Update',
            }
        view = create_initialized_view(
            self.milestone, '+edit', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual('new-name', self.milestone.name)
        expected = sorted(new_tags.lower().split())
        self.assertEqual(expected, self.milestone.getTags())

    def test_edit_milestone_clear_tags(self):
        orig_tags = u'b a c'
        self.milestone.setTags(orig_tags.split(), self.owner)
        form = {
            'field.name': 'new-name',
            'field.tags': '',
            'field.actions.update': 'Update',
            }
        view = create_initialized_view(
            self.milestone, '+edit', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual('new-name', self.milestone.name)
        expected = []
        self.assertEqual(expected, self.milestone.getTags())


class TestMilestoneDeleteView(TestCaseWithFactory):
    """Test the delete rules applied by the Milestone Delete view."""

    layer = DatabaseFunctionalLayer

    def test_delete_conjoined_bugtask(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        master_bugtask = getUtility(IBugTaskSet).createTask(
            bug, product.owner, product.development_focus)
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
        tasks = product.development_focus.searchTasks(
            BugTaskSearchParams(user=None))
        self.assertEqual(0, tasks.count())


class TestQueryCountBase(TestCaseWithFactory):

    def assert_bugtasks_query_count(self, milestone, bugtask_count,
                                    query_limit):
        # Assert that the number of queries run by view.bugtasks is low.
        self.add_bug(bugtask_count)
        login_person(self.owner)
        view = create_initialized_view(milestone, '+index')
        # Eliminate permission check for the admin team from the
        # recorded queries by loading it now. If the test ever breaks,
        # the person fixing it won't waste time trying to track this
        # query down.
        getUtility(ILaunchpadCelebrities).admin
        with StormStatementRecorder() as recorder:
            bugtasks = list(view.bugtasks)
        self.assertThat(recorder, HasQueryCount(LessThan(query_limit)))
        self.assertEqual(bugtask_count, len(bugtasks))


class TestProjectMilestoneIndexQueryCount(TestQueryCountBase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProjectMilestoneIndexQueryCount, self).setUp()
        # Increase cache size so that the query counts aren't affected
        # by objects being removed from the cache early.
        config.push('storm-cache', dedent('''
            [launchpad]
            storm_cache_size: 1000
            '''))
        self.addCleanup(config.pop, 'storm-cache')
        self.owner = self.factory.makePerson(name='product-owner')
        self.product = self.factory.makeProduct(owner=self.owner)
        login_person(self.product.owner)
        self.milestone = self.factory.makeMilestone(
            productseries=self.product.development_focus)

    def add_bug(self, count):
        login_person(self.product.owner)
        for i in range(count):
            bug = self.factory.makeBug(product=self.product)
            bug.bugtasks[0].transitionToMilestone(
                self.milestone, self.product.owner)
            # This is necessary to test precaching of assignees.
            bug.bugtasks[0].transitionToAssignee(
                self.factory.makePerson())
        logout()

    def test_bugtasks_queries(self):
        # The view.bugtasks attribute will make several queries:
        #  1. Search for bugtask IDs.
        #  2. Load bugtasks
        #  3. Load bugs.
        #  4. Loads the target (sourcepackagename / product)
        #  5. Load assignees (Person, Account, and EmailAddress).
        #  6. Load links to specifications.
        #  7. Load links to branches.
        #  8. Loads milestones
        #  9. Loads tags
        #  10. All related people
        bugtask_count = 10
        self.assert_bugtasks_query_count(
            self.milestone, bugtask_count, query_limit=11)

    def test_milestone_eager_loading(self):
        # Verify that the number of queries does not increase with more
        # bugs with different assignees.
        browses_under_limit = BrowsesWithQueryLimit(36, self.owner)
        self.add_bug(3)
        self.assertThat(self.milestone, browses_under_limit)
        self.add_bug(10)
        self.assertThat(self.milestone, browses_under_limit)

    def test_more_private_bugs_query_count_is_constant(self):
        # This test tests that as we add more private bugs to a milestone
        # index page, the number of queries issued by the page does not
        # change. It also sets a cap on the queries for this page: if the
        # baseline were to increase, the test would fail. As the baseline
        # is very large already, if the test fails due to such a change,
        # please cut some more of the existing fat out of it rather than
        # increasing the cap.
        page_query_limit = 37
        product = self.factory.makeProduct()
        login_person(product.owner)
        milestone = self.factory.makeMilestone(
            productseries=product.development_focus)
        bug1 = self.factory.makeBug(
            product=product, information_type=InformationType.USERDATA,
            owner=product.owner)
        bug1.bugtasks[0].transitionToMilestone(milestone, product.owner)
        # We look at the page as someone who is a member of a team and the
        # team is subscribed to the bugs, so that we don't get trivial
        # shortcuts avoiding queries : test the worst case.
        subscribed_team = self.factory.makeTeam(
            subscription_policy=TeamSubscriptionPolicy.MODERATED)
        viewer = self.factory.makePerson()
        with person_logged_in(subscribed_team.teamowner):
            subscribed_team.addMember(viewer, subscribed_team.teamowner)
        bug1.subscribe(subscribed_team, product.owner)
        bug1_url = canonical_url(bug1)
        milestone_url = canonical_url(milestone)
        browser = self.getUserBrowser(user=viewer)
        # Seed the cookie cache and any other cross-request state we may gain
        # in future.  See lp.services.webapp.serssion: _get_secret.
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
        bug2 = self.factory.makeBug(
            product=product, information_type=InformationType.USERDATA,
            owner=product.owner)
        bug2.bugtasks[0].transitionToMilestone(milestone, product.owner)
        bug2.subscribe(subscribed_team, product.owner)
        bug2_url = canonical_url(bug2)
        bug3 = self.factory.makeBug(
            product=product, information_type=InformationType.USERDATA,
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


class TestProjectGroupMilestoneIndexQueryCount(TestQueryCountBase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProjectGroupMilestoneIndexQueryCount, self).setUp()
        # Increase cache size so that the query counts aren't affected
        # by objects being removed from the cache early.
        config.push('storm-cache', dedent('''
            [launchpad]
            storm_cache_size: 1000
            '''))
        self.addCleanup(config.pop, 'storm-cache')
        self.owner = self.factory.makePerson(name='product-owner')
        self.project_group = self.factory.makeProject(owner=self.owner)
        login_person(self.owner)
        self.milestone_name = 'foo'
        # A ProjectGroup milestone doesn't exist unless one of its
        # Projects has a milestone of that name.
        product = self.factory.makeProduct(
            owner=self.owner, project=self.project_group)
        self.product_milestone = self.factory.makeMilestone(
            productseries=product.development_focus,
            name=self.milestone_name)
        self.milestone = self.project_group.getMilestone(
            self.milestone_name)

    def add_bug(self, count):
        login_person(self.owner)
        for i in range(count):
            bug = self.factory.makeBug(product=self.product_milestone.product)
            bug.bugtasks[0].transitionToMilestone(
                self.product_milestone, self.owner)
            # This is necessary to test precaching of assignees.
            bug.bugtasks[0].transitionToAssignee(
                self.factory.makePerson())
        logout()

    def test_bugtasks_queries(self):
        # The view.bugtasks attribute will make several queries:
        #  1. For each project in the group load all the dev focus series ids.
        #  2. Search for bugtask IDs.
        #  3. Load bugtasks.
        #  4. Load bugs.
        #  5. Load assignees (Person, Account, and EmailAddress).
        #  6. Load links to specifications.
        #  7. Load links to branches.
        #  8. Loads milestones.
        #  9. Loads tags.
        #  10. All related people.
        bugtask_count = 10
        self.assert_bugtasks_query_count(
            self.milestone, bugtask_count, query_limit=11)

    def test_milestone_eager_loading(self):
        # Verify that the number of queries does not increase with more
        # bugs with different assignees as long as the number of
        # projects doesn't increase.
        browses_under_limit = BrowsesWithQueryLimit(37, self.owner)
        self.add_bug(1)
        self.assertThat(self.milestone, browses_under_limit)
        self.add_bug(10)
        self.assertThat(self.milestone, browses_under_limit)


class TestDistributionMilestoneIndexQueryCount(TestQueryCountBase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionMilestoneIndexQueryCount, self).setUp()
        # Increase cache size so that the query counts aren't affected
        # by objects being removed from the cache early.
        config.push('storm-cache', dedent('''
            [launchpad]
            storm_cache_size: 1000
            '''))
        self.addCleanup(config.pop, 'storm-cache')
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.owner = self.factory.makePerson(name='test-owner')
        login_team(self.ubuntu.owner)
        self.ubuntu.owner = self.owner
        self.sourcepackagename = self.factory.makeSourcePackageName(
            'foo-package')
        login_person(self.owner)
        self.milestone = self.factory.makeMilestone(
            distribution=self.ubuntu)

    def add_bug(self, count):
        login_person(self.owner)
        for i in range(count):
            bug = self.factory.makeBug(distribution=self.ubuntu)
            distrosourcepackage = self.factory.makeDistributionSourcePackage(
                distribution=self.ubuntu)
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=self.ubuntu.currentseries,
                sourcepackagename=distrosourcepackage.sourcepackagename)
            bug.bugtasks[0].transitionToTarget(distrosourcepackage, self.owner)
            bug.bugtasks[0].transitionToMilestone(
                self.milestone, self.owner)
            # This is necessary to test precaching of assignees.
            bug.bugtasks[0].transitionToAssignee(
                self.factory.makePerson())
        logout()

    def test_bugtasks_queries(self):
        # The view.bugtasks attribute will make seven queries:
        #  1. Load ubuntu.currentseries.
        #  2. Check if the user is in the admin team.
        #  3. Check if the user is in the owner of the admin team.
        #  4. Load bugtasks and bugs.
        #  5. load the source package names.
        #  6. Load assignees (Person, Account, and EmailAddress).
        #  7. Load links to specifications.
        #  8. Load links to branches.
        #  9. Load links to milestones.
        bugtask_count = 10
        self.assert_bugtasks_query_count(
            self.milestone, bugtask_count, query_limit=11)

    def test_milestone_eager_loading(self):
        # Verify that the number of queries does not increase with more
        # bugs with different assignees.
        browses_under_limit = BrowsesWithQueryLimit(35, self.owner)
        self.add_bug(4)
        self.assertThat(self.milestone, browses_under_limit)
        self.add_bug(10)
        self.assertThat(self.milestone, browses_under_limit)


class TestMilestoneTagView(TestQueryCountBase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestMilestoneTagView, self).setUp()
        self.tags = [u'tag1']
        self.owner = self.factory.makePerson()
        self.project_group = self.factory.makeProject(owner=self.owner)
        self.product = self.factory.makeProduct(
            name="product1",
            owner=self.owner,
            project=self.project_group)
        self.milestone = self.factory.makeMilestone(product=self.product)
        with person_logged_in(self.owner):
            self.milestone.setTags(self.tags, self.owner)
        self.milestonetag = ProjectGroupMilestoneTag(
            target=self.project_group, tags=self.tags)

    def add_bug(self, count):
        with person_logged_in(self.owner):
            for n in range(count):
                self.factory.makeBug(
                    product=self.product, owner=self.owner,
                    milestone=self.milestone)

    def _make_form(self, tags):
        return {
            u'field.actions.search': u'Search',
            u'field.tags': u' '.join(tags),
            }

    def _url_tail(self, url, separator='/'):
        return url.rsplit(separator, 1)[1],

    def test_view_properties(self):
        # Ensure that the view is correctly initialized.
        view = create_initialized_view(self.milestonetag, '+index')
        self.assertEqual(self.milestonetag, view.context)
        self.assertEqual(self.milestonetag.title, view.page_title)
        self.assertContentEqual(self.tags, view.context.tags)

    def test_view_form_redirect(self):
        # Ensure a correct redirection is performed when tags are searched.
        tags = [u'tag1', u'tag2']
        form = self._make_form(tags)
        view = create_initialized_view(self.milestonetag, '+index', form=form)
        self.assertEqual(302, view.request.response.getStatus())
        new_milestonetag = ProjectGroupMilestoneTag(
            target=self.project_group, tags=tags)
        self.assertEqual(
            self._url_tail(canonical_url(new_milestonetag)),
            self._url_tail(view.request.response.getHeader('Location')))

    def test_view_form_error(self):
        # Ensure the form correctly handles invalid submissions.
        tags = [u'tag1', u't']  # One char tag is not valid.
        form = self._make_form(tags)
        view = create_initialized_view(self.milestonetag, '+index', form=form)
        self.assertEqual(1, len(view.errors))
        self.assertEqual('tags', view.errors[0].field_name)

    def test_bugtask_query_count(self):
        # Ensure that a correct number of queries is executed for
        # bugtasks retrieval.
        bugtask_count = 10
        self.assert_bugtasks_query_count(
            self.milestonetag, bugtask_count, query_limit=11)
