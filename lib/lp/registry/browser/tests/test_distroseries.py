# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `lp.registry.browser.distroseries`."""

__metaclass__ = type

import difflib
import re
from textwrap import TextWrapper

from BeautifulSoup import BeautifulSoup
from lxml import html
import soupmatchers
from storm.zope.interfaces import IResultSet
from testtools.content import (
    Content,
    text_content,
    )
from testtools.content_type import UTF8_TEXT
from testtools.matchers import (
    EndsWith,
    Equals,
    LessThan,
    Not,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import flush_database_caches
from canonical.launchpad.testing.pages import find_tag_by_id
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.interaction import get_current_principal
from canonical.launchpad.webapp.interfaces import BrowserNotificationLevel
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.debversion import Version
from lp.registry.browser.distroseries import (
    HIGHER_VERSION_THAN_PARENT,
    IGNORED,
    NON_IGNORED,
    RESOLVED,
    )
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.services.features import (
    get_relevant_feature_controller,
    getFeatureFlag,
    )
from lp.services.features.testing import FeatureFixture
from lp.soyuz.enums import (
    ArchivePermissionType,
    PackagePublishingStatus,
    SourcePackageFormat,
    )
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.distributionjob import (
    IDistroSeriesDifferenceJobSource,
    IInitialiseDistroSeriesJobSource,
    )
from lp.soyuz.interfaces.packagecopyjob import IPlainPackageCopyJobSource
from lp.soyuz.interfaces.sourcepackageformat import (
    ISourcePackageFormatSelectionSet,
    )
from lp.soyuz.model import distroseriesdifferencejob
from lp.soyuz.model.archivepermission import ArchivePermission
from lp.testing import (
    anonymous_logged_in,
    celebrity_logged_in,
    feature_flags,
    login_person,
    person_logged_in,
    set_feature_flag,
    StormStatementRecorder,
    TestCaseWithFactory,
    with_celebrity_logged_in,
    )
from lp.testing.fakemethod import FakeMethod
from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_initialized_view


def set_derived_series_ui_feature_flag(test_case):
    test_case.useFixture(FeatureFixture({
        u'soyuz.derived_series_ui.enabled': u'on',
        }))


def set_derived_series_sync_feature_flag(test_case):
    test_case.useFixture(FeatureFixture({
        u'soyuz.derived_series_sync.enabled': u'on',
        u'soyuz.derived_series_ui.enabled': u'on',
        }))


def set_derived_series_difference_jobs_feature_flag(test_case):
    test_case.useFixture(FeatureFixture({
        distroseriesdifferencejob.FEATURE_FLAG_ENABLE_MODULE: u'on',
        }))


class TestDistroSeriesView(TestCaseWithFactory):
    """Test the distroseries +index view."""

    layer = LaunchpadZopelessLayer

    def test_needs_linking(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        view = create_initialized_view(distroseries, '+index')
        self.assertEqual(view.needs_linking, None)

    def _createDifferenceAndGetView(self, difference_type):
        # Helper function to create a valid DSD.
        dsp = self.factory.makeDistroSeriesParent()
        self.factory.makeDistroSeriesDifference(
            derived_series=dsp.derived_series,
            difference_type=difference_type)
        return create_initialized_view(dsp.derived_series, '+index')

    def test_num_differences(self):
        diff_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
        view = self._createDifferenceAndGetView(diff_type)
        self.assertEqual(1, view.num_differences)

    def test_num_differences_in_parent(self):
        diff_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        view = self._createDifferenceAndGetView(diff_type)
        self.assertEqual(1, view.num_differences_in_parent)

    def test_num_differences_in_child(self):
        diff_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        view = self._createDifferenceAndGetView(diff_type)
        self.assertEqual(1, view.num_differences_in_child)


class DistroSeriesIndexFunctionalTestCase(TestCaseWithFactory):
    """Test the distroseries +index page."""

    layer = DatabaseFunctionalLayer

    def _setupDifferences(self, name, parent_names, nb_diff_versions,
                          nb_diff_child, nb_diff_parent):
        # Helper to create DSDs of the different types.
        derived_series = self.factory.makeDistroSeries(name=name)
        self.simple_user = self.factory.makePerson()
        # parent_names can be a list of parent names or a single name
        # for a single parent (e.g. ['parent1_name', 'parent2_name'] or
        # 'parent_name').
        # If multiple parents are created, the DSDs will be created with
        # the first one.
        if type(parent_names) == str:
            parent_names = [parent_names]
        dsps = []
        for parent_name in parent_names:
            parent_series = self.factory.makeDistroSeries(name=parent_name)
            dsps.append(self.factory.makeDistroSeriesParent(
                derived_series=derived_series, parent_series=parent_series))
        first_parent_series = dsps[0].parent_series
        for i in range(nb_diff_versions):
            diff_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series,
                difference_type=diff_type,
                parent_series=first_parent_series)
        for i in range(nb_diff_child):
            diff_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series,
                difference_type=diff_type,
                parent_series=first_parent_series)
        for i in range(nb_diff_parent):
            diff_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
            self.factory.makeDistroSeriesDifference(
                derived_series=derived_series,
                difference_type=diff_type,
                parent_series=first_parent_series)
        return derived_series

    def test_differences_no_flag_no_portlet(self):
        # The portlet is not displayed if the feature flag is not enabled.
        derived_series = self._setupDifferences('deri', 'sid', 1, 2, 2)
        portlet_header = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Derivation portlet header', 'h2',
                text='Derived from Sid'),
            )

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                derived_series,
                '+index',
                principal=self.simple_user)
            html_content = view()

        self.assertEqual(
            None, getFeatureFlag('soyuz.derived_series_ui.enabled'))
        self.assertThat(html_content, Not(portlet_header))

    def test_differences_portlet_all_differences(self):
        # The difference portlet shows the differences with the parent
        # series.
        set_derived_series_ui_feature_flag(self)
        derived_series = self._setupDifferences('deri', 'sid', 1, 2, 3)
        portlet_display = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Derivation portlet header', 'h2',
                text='Derived from Sid'),
            soupmatchers.Tag(
                'Differences link', 'a',
                text=re.compile('\s*1 package with differences\s*'),
                attrs={'href': re.compile('.*/\+localpackagediffs')}),
            soupmatchers.Tag(
                'Parent diffs link', 'a',
                text=re.compile('\s*2 packages only in Sid\s*'),
                attrs={'href': re.compile('.*/\+missingpackages')}),
            soupmatchers.Tag(
                'Child diffs link', 'a',
                text=re.compile('\s*3 packages only in Deri\s*'),
                attrs={'href': re.compile('.*/\+uniquepackages')}))

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                derived_series,
                '+index',
                principal=self.simple_user)
            # XXX rvb 2011-04-12 bug=758649: LaunchpadTestRequest overrides
            # self.features to NullFeatureController.
            view.request.features = get_relevant_feature_controller()
            html_content = view()

        self.assertThat(html_content, portlet_display)

    def test_differences_portlet_all_differences_multiple_parents(self):
        # The difference portlet shows the differences with the multiple
        # parent series.
        set_derived_series_ui_feature_flag(self)
        derived_series = self._setupDifferences(
            'deri', ['sid1', 'sid2'], 0, 1, 0)
        portlet_display = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Derivation portlet header', 'h2',
                text='Derived from 2 parents'),
            soupmatchers.Tag(
                'Parent diffs link', 'a',
                text=re.compile('\s*1 package only in a parent series\s*'),
                attrs={'href': re.compile('.*/\+missingpackages')}))

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                derived_series,
                '+index',
                principal=self.simple_user)
            # XXX rvb 2011-04-12 bug=758649: LaunchpadTestRequest overrides
            # self.features to NullFeatureController.
            view.request.features = get_relevant_feature_controller()
            html_text = view()

        self.assertThat(html_text, portlet_display)

    def test_differences_portlet_no_differences(self):
        # The difference portlet displays 'No differences' if there is no
        # differences with the parent.
        set_derived_series_ui_feature_flag(self)
        derived_series = self._setupDifferences('deri', 'sid', 0, 0, 0)
        portlet_display = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Derivation portlet header', 'h2',
                text='Derived from Sid'),
            soupmatchers.Tag(
                'Child diffs link', True,
                text=re.compile('\s*No differences\s*')),
              )

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                derived_series,
                '+index',
                principal=self.simple_user)
            # XXX rvb 2011-04-12 bug=758649: LaunchpadTestRequest overrides
            # self.features to NullFeatureController.
            view.request.features = get_relevant_feature_controller()
            html_content = view()

        self.assertThat(html_content, portlet_display)

    def test_differences_portlet_initialising(self):
        # The difference portlet displays 'The series is initialising.' if
        # there is an initialising job for the series.
        set_derived_series_ui_feature_flag(self)
        derived_series = self.factory.makeDistroSeries()
        parent_series = self.factory.makeDistroSeries()
        self.simple_user = self.factory.makePerson()
        job_source = getUtility(IInitialiseDistroSeriesJobSource)
        job_source.create(derived_series, [parent_series.id])
        portlet_display = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Derived series', 'h2',
                text='Series initialisation in progress'),
            soupmatchers.Tag(
                'Init message', True,
                text=re.compile('\s*This series is initialising.\s*')),
              )

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                derived_series,
                '+index',
                principal=self.simple_user)
            # XXX rvb 2011-04-12 bug=758649: LaunchpadTestRequest overrides
            # self.features to NullFeatureController.
            view.request.features = get_relevant_feature_controller()
            html_content = view()

        self.assertTrue(derived_series.is_initialising)
        self.assertThat(html_content, portlet_display)


class TestMilestoneBatchNavigatorAttribute(TestCaseWithFactory):
    """Test the series.milestone_batch_navigator attribute."""

    layer = LaunchpadZopelessLayer

    def test_distroseries_milestone_batch_navigator(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        for name in ('a', 'b', 'c', 'd'):
            distroseries.newMilestone(name)
        view = create_initialized_view(distroseries, name='+index')
        self._check_milestone_batch_navigator(view)

    def test_productseries_milestone_batch_navigator(self):
        product = self.factory.makeProduct()
        for name in ('a', 'b', 'c', 'd'):
            product.development_focus.newMilestone(name)

        view = create_initialized_view(
            product.development_focus, name='+index')
        self._check_milestone_batch_navigator(view)

    def _check_milestone_batch_navigator(self, view):
        config.push('default-batch-size', """
        [launchpad]
        default_batch_size: 2
        """)
        self.assert_(
            isinstance(view.milestone_batch_navigator, BatchNavigator),
            'milestone_batch_navigator is not a BatchNavigator object: %r'
            % view.milestone_batch_navigator)
        self.assertEqual(4, view.milestone_batch_navigator.batch.total())
        expected = [
            'd',
            'c',
            ]
        milestone_names = [
            item.name
            for item in view.milestone_batch_navigator.currentBatch()]
        self.assertEqual(expected, milestone_names)
        config.pop('default-batch-size')


class TestDistroSeriesAddView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_submit(self):
        # When creating a new DistroSeries via DistroSeriesAddView, the title
        # is set to the same as the displayname (title is, in any case,
        # deprecated), the description is left empty, and previous_series is
        # None (DistroSeriesInitializeView takes care of setting that).
        user = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=user)
        form = {
            "field.name": u"polished",
            "field.version": u"12.04",
            "field.displayname": u"Polished Polecat",
            "field.summary": u"Even The Register likes it.",
            "field.actions.create": u"Add Series",
            }
        with person_logged_in(user):
            create_initialized_view(distribution, "+addseries", form=form)
        distroseries = distribution.getSeries(u"polished")
        self.assertEqual(u"polished", distroseries.name)
        self.assertEqual(u"12.04", distroseries.version)
        self.assertEqual(u"Polished Polecat", distroseries.displayname)
        self.assertEqual(u"Polished Polecat", distroseries.title)
        self.assertEqual(u"Even The Register likes it.", distroseries.summary)
        self.assertEqual(u"", distroseries.description)
        self.assertIs(None, distroseries.previous_series)
        self.assertEqual(user, distroseries.owner)


class TestDistroSeriesInitializeView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_init(self):
        # There exists a +initseries view for distroseries.
        distroseries = self.factory.makeDistroSeries()
        view = create_initialized_view(distroseries, "+initseries")
        self.assertTrue(view)

    def test_is_derived_series_feature_enabled(self):
        # The feature is disabled by default, but can be enabled by setting
        # the soyuz.derived_series_ui.enabled flag.
        distroseries = self.factory.makeDistroSeries()
        view = create_initialized_view(distroseries, "+initseries")
        with feature_flags():
            self.assertFalse(view.is_derived_series_feature_enabled)
        with feature_flags():
            set_feature_flag(u"soyuz.derived_series_ui.enabled", u"true")
            self.assertTrue(view.is_derived_series_feature_enabled)

    def test_form_hidden_when_derived_series_feature_disabled(self):
        # The form is hidden when the feature flag is not set.
        distroseries = self.factory.makeDistroSeries()
        view = create_initialized_view(distroseries, "+initseries")
        with feature_flags():
            root = html.fromstring(view())
            self.assertEqual(
                [], root.cssselect("#initseries-form-container"))
            # Instead an explanatory message is shown.
            [message] = root.cssselect("p.error.message")
            self.assertIn(
                u"The Derivative Distributions feature is under development",
                message.text)

    def test_form_shown_when_derived_series_feature_enabled(self):
        # The form is shown when the feature flag is set.
        distroseries = self.factory.makeDistroSeries()
        view = create_initialized_view(distroseries, "+initseries")
        with feature_flags():
            set_feature_flag(u"soyuz.derived_series_ui.enabled", u"true")
            root = html.fromstring(view())
            self.assertNotEqual(
                [], root.cssselect("#initseries-form-container"))
            # A different explanatory message is shown for clients that don't
            # process Javascript.
            [message] = root.cssselect("p.error.message")
            self.assertIn(
                u"Javascript is required to use this page",
                message.text)
            self.assertIn(
                u"javascript-disabled",
                message.get("class").split())

    def test_form_hidden_when_distroseries_is_initialized(self):
        # The form is hidden when the feature flag is set but the series has
        # already been derived.
        distroseries = self.factory.makeDistroSeries()
        self.factory.makeDistroSeriesParent(derived_series=distroseries)
        view = create_initialized_view(distroseries, "+initseries")
        with feature_flags():
            set_feature_flag(u"soyuz.derived_series_ui.enabled", u"true")
            root = html.fromstring(view())
            self.assertEqual(
                [], root.cssselect("#initseries-form-container"))
            # Instead an explanatory message is shown.
            [message] = root.cssselect("p.error.message")
            self.assertEqual(
                u"This series has already been derived.",
                message.text.strip())


class DistroSeriesDifferenceMixin:
    """A helper class for testing differences pages"""

    def _test_packagesets(self, html_content, packageset_text,
                          packageset_class, msg_text):
        parent_packagesets = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                msg_text, 'td',
                attrs={'class': packageset_class},
                text=packageset_text))

        self.assertThat(html_content, parent_packagesets)

    def _createChildAndParent(self):
        derived_series = self.factory.makeDistroSeries(name='derilucid')
        parent_series = self.factory.makeDistroSeries(name='lucid')
        self.factory.makeDistroSeriesParent(
            derived_series=derived_series, parent_series=parent_series)
        return (derived_series, parent_series)

    def _createChildAndParents(self, other_parent_series=None):
        derived_series, parent_series = self._createChildAndParent()
        self.factory.makeDistroSeriesParent(
            derived_series=derived_series, parent_series=other_parent_series)
        return (derived_series, parent_series)


class TestDistroSeriesLocalDifferences(
    DistroSeriesDifferenceMixin, TestCaseWithFactory):
    """Test the distroseries +localpackagediffs page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistroSeriesLocalDifferences,
              self).setUp('foo.bar@canonical.com')
        set_derived_series_ui_feature_flag(self)
        self.simple_user = self.factory.makePerson()

    def test_filter_form_if_differences(self):
        # Test that the page includes the filter form if differences
        # are present
        login_person(self.simple_user)
        derived_series, parent_series = self._createChildAndParent()
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        view = create_initialized_view(
            derived_series, '+localpackagediffs', principal=self.simple_user)

        self.assertIsNot(
            None,
            find_tag_by_id(view(), 'distroseries-localdiff-search-filter'),
            "Form filter should be shown when there are differences.")

    def test_filter_noform_if_nodifferences(self):
        # Test that the page doesn't includes the filter form if no
        # differences are present
        login_person(self.simple_user)
        derived_series, parent_series = self._createChildAndParent()

        view = create_initialized_view(
            derived_series, '+localpackagediffs', principal=self.simple_user)

        self.assertIs(
            None,
            find_tag_by_id(view(), 'distroseries-localdiff-search-filter'),
            "Form filter should not be shown when there are no differences.")

    def test_parent_packagesets_localpackagediffs(self):
        # +localpackagediffs displays the parent packagesets.
        ds_diff = self.factory.makeDistroSeriesDifference()
        with celebrity_logged_in('admin'):
            ps = self.factory.makePackageset(
                packages=[ds_diff.source_package_name],
                distroseries=ds_diff.parent_series)

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                ds_diff.derived_series,
                '+localpackagediffs',
                principal=self.simple_user)
            html_content = view()

        packageset_text = re.compile('\s*' + ps.name)
        self._test_packagesets(
            html_content, packageset_text, 'parent-packagesets',
            'Parent packagesets')

    def test_parent_packagesets_localpackagediffs_sorts(self):
        # Multiple packagesets are sorted in a comma separated list.
        ds_diff = self.factory.makeDistroSeriesDifference()
        unsorted_names = [u"zzz", u"aaa"]
        with celebrity_logged_in('admin'):
            for name in unsorted_names:
                self.factory.makePackageset(
                    name=name,
                    packages=[ds_diff.source_package_name],
                    distroseries=ds_diff.parent_series)

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                ds_diff.derived_series,
                '+localpackagediffs',
                principal=self.simple_user)
            html_content = view()

        packageset_text = re.compile(
            '\s*' + ', '.join(sorted(unsorted_names)))
        self._test_packagesets(
            html_content, packageset_text, 'parent-packagesets',
            'Parent packagesets')


class TestDistroSeriesLocalDiffPerformance(TestCaseWithFactory,
                                           DistroSeriesDifferenceMixin):
    """Test the distroseries +localpackagediffs page's performance."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistroSeriesLocalDiffPerformance,
             self).setUp('foo.bar@canonical.com')
        set_derived_series_ui_feature_flag(self)
        self.simple_user = self.factory.makePerson()

    def _assertQueryCount(self, derived_series):
        # With no DistroSeriesDifferences the query count should be low and
        # fairly static. However, with some DistroSeriesDifferences the query
        # count will be higher, but it should remain the same no matter how
        # many differences there are.
        ArchivePermission(
            archive=derived_series.main_archive, person=self.simple_user,
            component=getUtility(IComponentSet)["main"],
            permission=ArchivePermissionType.QUEUE_ADMIN)
        login_person(self.simple_user)

        def add_differences(num):
            for index in xrange(num):
                version = self.factory.getUniqueInteger()
                versions = {
                    'base': u'1.%d' % version,
                    'derived': u'1.%dderived1' % version,
                    'parent': u'1.%d-1' % version,
                    }
                dsd = self.factory.makeDistroSeriesDifference(
                    derived_series=derived_series,
                    versions=versions)

                # Push a base_version in... not sure how better to do it.
                removeSecurityProxy(dsd).base_version = versions["base"]

                # Add a couple of comments.
                self.factory.makeDistroSeriesDifferenceComment(dsd)
                self.factory.makeDistroSeriesDifferenceComment(dsd)

                # Update the spr, some with recipes, some with signing keys.
                # SPR.uploader references both, and the uploader is referenced
                # in the page.
                spr = dsd.source_pub.sourcepackagerelease
                if index % 2 == 0:
                    removeSecurityProxy(spr).source_package_recipe_build = (
                        self.factory.makeSourcePackageRecipeBuild(
                            sourcename=spr.sourcepackagename.name,
                            distroseries=derived_series))
                else:
                    removeSecurityProxy(spr).dscsigningkey = (
                        self.factory.makeGPGKey(owner=spr.creator))

        def flush_and_render():
            flush_database_caches()
            # Pull in the calling user's location so that it isn't recorded in
            # the query count; it causes the total to be fragile for no
            # readily apparent reason.
            self.simple_user.location
            with StormStatementRecorder() as recorder:
                view = create_initialized_view(
                    derived_series, '+localpackagediffs',
                    principal=self.simple_user)
                view()
            return recorder, view.cached_differences.batch.trueSize

        def statement_differ(rec1, rec2):
            wrapper = TextWrapper(break_long_words=False)

            def prepare_statements(rec):
                for statement in rec.statements:
                    for line in wrapper.wrap(statement):
                        yield line
                    yield "-" * wrapper.width

            def statement_diff():
                diff = difflib.ndiff(
                    list(prepare_statements(rec1)),
                    list(prepare_statements(rec2)))
                for line in diff:
                    yield "%s\n" % line

            return statement_diff

        # Render without differences and check the query count isn't silly.
        recorder1, batch_size = flush_and_render()
        self.assertThat(recorder1, HasQueryCount(LessThan(30)))
        self.addDetail(
            "statement-count-0-differences",
            text_content(u"%d" % recorder1.count))
        # Add some differences and render.
        add_differences(2)
        recorder2, batch_size = flush_and_render()
        self.addDetail(
            "statement-count-2-differences",
            text_content(u"%d" % recorder2.count))
        # Add more differences and render again.
        add_differences(2)
        recorder3, batch_size = flush_and_render()
        self.addDetail(
            "statement-count-4-differences",
            text_content(u"%d" % recorder3.count))
        # The last render should not need more queries than the previous.
        self.addDetail(
            "statement-diff", Content(
                UTF8_TEXT, statement_differ(recorder2, recorder3)))
        # Details about the number of statements per row.
        statement_count_per_row = (
            (recorder3.count - recorder1.count) / float(batch_size))
        self.addDetail(
            "statement-count-per-row-average",
            text_content(u"%.2f" % statement_count_per_row))
        # Query count is ~O(1) (i.e. not dependent of the number of
        # differences displayed).
        self.assertThat(
            recorder3, HasQueryCount(Equals(recorder2.count)))

    def test_queries_single_parent(self):
        dsp = self.factory.makeDistroSeriesParent()
        derived_series = dsp.derived_series
        self._assertQueryCount(derived_series)

    def test_queries_multiple_parents(self):
        dsp = self.factory.makeDistroSeriesParent()
        derived_series = dsp.derived_series
        self.factory.makeDistroSeriesParent(
            derived_series=derived_series)
        self._assertQueryCount(derived_series)


class TestDistroSeriesLocalDifferencesZopeless(TestCaseWithFactory,
                                               DistroSeriesDifferenceMixin):
    """Test the distroseries +localpackagediffs view."""

    layer = LaunchpadFunctionalLayer

    def makePackageUpgrade(self, derived_series=None):
        """Create a `DistroSeriesDifference` for a package upgrade."""
        base_version = '1.%d' % self.factory.getUniqueInteger()
        versions = {
            'base': base_version,
            'parent': base_version + '-' + self.factory.getUniqueString(),
            'derived': base_version,
        }
        return self.factory.makeDistroSeriesDifference(
            derived_series=derived_series, versions=versions,
            set_base_version=True)

    def makeView(self, distroseries=None):
        """Create a +localpackagediffs view for `distroseries`."""
        if distroseries is None:
            distroseries = (
                self.factory.makeDistroSeriesParent().derived_series)
        # current_request=True causes the current interaction to end so we
        # must explicitly ask that the current principal be used for the
        # request.
        return create_initialized_view(
            distroseries, '+localpackagediffs',
            principal=get_current_principal(),
            current_request=True)

    def test_view_redirects_without_feature_flag(self):
        # If the feature flag soyuz.derived_series_ui.enabled is not set the
        # view simply redirects to the derived series.
        derived_series, parent_series = self._createChildAndParent()

        self.assertIs(
            None, getFeatureFlag('soyuz.derived_series_ui.enabled'))
        view = self.makeView(derived_series)

        response = view.request.response
        self.assertEqual(302, response.getStatus())
        self.assertEqual(
            canonical_url(derived_series), response.getHeader('location'))

    def test_label(self):
        # The view label includes the names of both series.
        derived_series, parent_series = self._createChildAndParent()

        view = self.makeView(derived_series)

        self.assertEqual(
            "Source package differences between 'Derilucid' and "
            "parent series 'Lucid'",
            view.label)

    def test_label_multiple_parents(self):
        # If the series has multiple parents, the view label mentions
        # the generic term 'parent series'.
        derived_series, parent_series = self._createChildAndParents()

        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        self.assertEqual(
            "Source package differences between 'Derilucid' and "
            "parent series",
            view.label)

    def test_batch_includes_needing_attention_only(self):
        # The differences attribute includes differences needing
        # attention only.
        derived_series, parent_series = self._createChildAndParent()
        current_difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.RESOLVED)

        view = self.makeView(derived_series)

        self.assertContentEqual(
            [current_difference], view.cached_differences.batch)

    def test_batch_includes_different_versions_only(self):
        # The view contains differences of type DIFFERENT_VERSIONS only.
        derived_series, parent_series = self._createChildAndParent()
        different_versions_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            difference_type=(
                DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES))

        view = self.makeView(derived_series)

        self.assertContentEqual(
            [different_versions_diff], view.cached_differences.batch)

    def test_template_includes_help_link(self):
        # The help link for popup help is included.
        derived_series, parent_series = self._createChildAndParent()
        set_derived_series_ui_feature_flag(self)
        view = self.makeView(derived_series)

        soup = BeautifulSoup(view())
        help_links = soup.findAll(
            'a', href='/+help/soyuz/derived-series-syncing.html')
        self.assertEqual(1, len(help_links))

    def test_diff_row_includes_last_comment_only(self):
        # The most recent comment is rendered for each difference.
        derived_series, parent_series = self._createChildAndParent()
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        with person_logged_in(derived_series.owner):
            difference.addComment(difference.owner, "Earlier comment")
            difference.addComment(difference.owner, "Latest comment")

        set_derived_series_ui_feature_flag(self)
        view = self.makeView(derived_series)

        # Find all the rows within the body of the table
        # listing the differences.
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        rows = diff_table.tbody.findAll('tr')

        self.assertEqual(1, len(rows))
        self.assertIn("Latest comment", unicode(rows[0]))
        self.assertNotIn("Earlier comment", unicode(rows[0]))

    def test_diff_row_links_to_extra_details(self):
        # The source package name links to the difference details.
        derived_series, parent_series = self._createChildAndParent()
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        view = self.makeView(derived_series)
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        row = diff_table.tbody.findAll('tr')[0]

        links = row.findAll('a', href=canonical_url(difference))
        self.assertEqual(1, len(links))
        self.assertEqual(difference.source_package_name.name, links[0].string)

    def test_multiple_parents_display(self):
        package_name = 'package-1'
        other_parent_series = self.factory.makeDistroSeries(name='other')
        derived_series, parent_series = self._createChildAndParents(
            other_parent_series=other_parent_series)
        versions = {
            'base': u'1.0',
            'derived': u'1.0derived1',
            'parent': u'1.0-1',
        }

        self.factory.makeDistroSeriesDifference(
            versions=versions,
            parent_series=other_parent_series,
            source_package_name_str=package_name,
            derived_series=derived_series)
        self.factory.makeDistroSeriesDifference(
            versions=versions,
            parent_series=parent_series,
            source_package_name_str=package_name,
            derived_series=derived_series)
        set_derived_series_ui_feature_flag(self)
        view = create_initialized_view(
            derived_series, '+localpackagediffs')
        multiple_parents_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Parent table header", 'th',
                text=re.compile("\s*Parent\s")),
            soupmatchers.Tag(
                "Parent version table header", 'th',
                text=re.compile("\s*Parent version\s*")),
            soupmatchers.Tag(
                "Parent name", 'a',
                attrs={'class': 'parent-name'},
                text=re.compile("\s*Other\s*")),
             )
        self.assertThat(view.render(), multiple_parents_matches)

    def test_diff_row_shows_version_attached(self):
        # The +localpackagediffs page shows the version attached to the
        # DSD and not the last published version (bug=745776).
        package_name = 'package-1'
        derived_series, parent_series = self._createChildAndParent()
        versions = {
            'base': u'1.0',
            'derived': u'1.0derived1',
            'parent': u'1.0-1',
        }
        new_version = u'1.2'

        difference = self.factory.makeDistroSeriesDifference(
            versions=versions,
            source_package_name_str=package_name,
            derived_series=derived_series)

        # Create a more recent source package publishing history.
        sourcepackagename = self.factory.getOrMakeSourcePackageName(
            package_name)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=sourcepackagename,
            distroseries=derived_series,
            version=new_version)

        set_derived_series_ui_feature_flag(self)
        view = self.makeView(derived_series)
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        row = diff_table.tbody.tr
        links = row.findAll('a', {'class': 'derived-version'})

        # The version displayed is the version attached to the
        # difference.
        self.assertEqual(1, len(links))
        self.assertEqual(versions['derived'], links[0].string.strip())

        link = canonical_url(difference.source_pub.sourcepackagerelease)
        self.assertTrue(link, EndsWith(new_version))
        # The link points to the sourcepackagerelease referenced in the
        # difference.
        self.assertTrue(
            links[0].get('href'), EndsWith(difference.source_version))

    def test_diff_row_no_published_version(self):
        # The +localpackagediffs page shows only the version (no link)
        # if we fail to fetch the published version.
        package_name = 'package-1'
        derived_series, parent_series = self._createChildAndParent()
        versions = {
            'base': u'1.0',
            'derived': u'1.0derived1',
            'parent': u'1.0-1',
        }

        difference = self.factory.makeDistroSeriesDifference(
            versions=versions,
            source_package_name_str=package_name,
            derived_series=derived_series)

        # Delete the publications.
        with celebrity_logged_in("admin"):
            difference.source_pub.status = (
                PackagePublishingStatus.DELETED)
            difference.parent_source_pub.status = (
                PackagePublishingStatus.DELETED)
        # Flush out the changes and invalidate caches (esp. property caches).
        flush_database_caches()

        set_derived_series_ui_feature_flag(self)
        view = self.makeView(derived_series)
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        row = diff_table.tbody.tr

        # The table feature a simple span since we were unable to fetch a
        # published sourcepackage.
        derived_span = row.findAll('span', {'class': 'derived-version'})
        parent_span = row.findAll('span', {'class': 'parent-version'})
        self.assertEqual(1, len(derived_span))
        self.assertEqual(1, len(parent_span))

        # The versions displayed are the versions attached to the
        # difference.
        self.assertEqual(versions['derived'], derived_span[0].string.strip())
        self.assertEqual(versions['parent'], parent_span[0].string.strip())

    def test_getUpgrades_shows_updates_in_parent(self):
        # The view's getUpgrades methods lists packages that can be
        # trivially upgraded: changed in the parent, not changed in the
        # derived series, but present in both.
        dsd = self.makePackageUpgrade()
        view = self.makeView(dsd.derived_series)
        self.assertContentEqual([dsd], view.getUpgrades())

    def enableDerivedSeriesSyncFeature(self):
        self.useFixture(
            FeatureFixture(
                {u'soyuz.derived_series_sync.enabled': u'on'}))

    @with_celebrity_logged_in("admin")
    def test_upgrades_offered_only_with_feature_flag(self):
        # The "Upgrade Packages" button will only be shown when a specific
        # feature flag is enabled.
        view = self.makeView()
        self.makePackageUpgrade(view.context)
        self.assertFalse(view.canUpgrade())
        self.enableDerivedSeriesSyncFeature()
        self.assertTrue(view.canUpgrade())

    def test_upgrades_are_offered_if_appropriate(self):
        # The "Upgrade Packages" button will only be shown to privileged
        # users.
        self.enableDerivedSeriesSyncFeature()
        dsd = self.makePackageUpgrade()
        view = self.makeView(dsd.derived_series)
        with celebrity_logged_in("admin"):
            self.assertTrue(view.canUpgrade())
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(view.canUpgrade())
        with anonymous_logged_in():
            self.assertFalse(view.canUpgrade())

    @with_celebrity_logged_in("admin")
    def test_upgrades_offered_only_if_available(self):
        # If there are no upgrades, the "Upgrade Packages" button won't
        # be shown.
        self.enableDerivedSeriesSyncFeature()
        view = self.makeView()
        self.assertFalse(view.canUpgrade())
        self.makePackageUpgrade(view.context)
        self.assertTrue(view.canUpgrade())

    @with_celebrity_logged_in("admin")
    def test_upgrades_not_offered_after_feature_freeze(self):
        # There won't be an "Upgrade Packages" button once feature
        # freeze has occurred.  Mass updates would not make sense after
        # that point.
        self.enableDerivedSeriesSyncFeature()
        upgradeable = {}
        for status in SeriesStatus.items:
            dsd = self.makePackageUpgrade()
            dsd.derived_series.status = status
            view = self.makeView(dsd.derived_series)
            upgradeable[status] = view.canUpgrade()
        expected = {
            SeriesStatus.FUTURE: True,
            SeriesStatus.EXPERIMENTAL: True,
            SeriesStatus.DEVELOPMENT: True,
            SeriesStatus.FROZEN: False,
            SeriesStatus.CURRENT: False,
            SeriesStatus.SUPPORTED: False,
            SeriesStatus.OBSOLETE: False,
        }
        self.assertEqual(expected, upgradeable)

    def test_upgrade_creates_sync_jobs(self):
        # requestUpgrades generates PackageCopyJobs for the upgrades
        # that need doing.
        dsd = self.makePackageUpgrade()
        series = dsd.derived_series
        view = self.makeView(series)
        view.requestUpgrades()
        job_source = getUtility(IPlainPackageCopyJobSource)
        jobs = list(
            job_source.getActiveJobs(series.distribution.main_archive))
        self.assertEquals(1, len(jobs))
        job = jobs[0]
        self.assertEquals(series, job.target_distroseries)
        self.assertEqual(dsd.source_package_name.name, job.package_name)
        self.assertEqual(dsd.parent_source_version, job.package_version)

    def test_upgrade_gives_feedback(self):
        # requestUpgrades doesn't instantly perform package upgrades,
        # but it shows the user a notice that the upgrades have been
        # requested.
        dsd = self.makePackageUpgrade()
        view = self.makeView(dsd.derived_series)
        view.requestUpgrades()
        expected = {
            "level": BrowserNotificationLevel.INFO,
            "message":
                ("Upgrades of {0.displayname} packages have been "
                 "requested. Please give Launchpad some time to "
                 "complete these.").format(dsd.derived_series),
            }
        observed = map(vars, view.request.response.notifications)
        self.assertEqual([expected], observed)

    def test_requestUpgrade_is_efficient(self):
        # A single web request may need to schedule large numbers of
        # package upgrades.  It must do so without issuing large numbers
        # of database queries.
        derived_series, parent_series = self._createChildAndParent()
        # Take a baseline measure of queries.
        self.makePackageUpgrade(derived_series=derived_series)
        flush_database_caches()
        with StormStatementRecorder() as recorder1:
            self.makeView(derived_series).requestUpgrades()
        self.assertThat(recorder1, HasQueryCount(LessThan(10)))
        # Creating Jobs and DistributionJobs takes 2 extra queries per
        # requested sync.
        requested_syncs = 3
        for index in xrange(requested_syncs):
            self.makePackageUpgrade(derived_series=derived_series)
        flush_database_caches()
        with StormStatementRecorder() as recorder2:
            self.makeView(derived_series).requestUpgrades()
        self.assertThat(
            recorder2,
            HasQueryCount(Equals(recorder1.count + 2 * requested_syncs)))


class TestDistroSeriesLocalDifferencesFunctional(TestCaseWithFactory,
                                                 DistroSeriesDifferenceMixin):

    layer = LaunchpadFunctionalLayer

    def makeDSDJob(self, dsd):
        """Create a `DistroSeriesDifferenceJob` to update `dsd`."""
        job_source = getUtility(IDistroSeriesDifferenceJobSource)
        jobs = job_source.createForPackagePublication(
            dsd.derived_series, dsd.source_package_name,
            PackagePublishingPocket.RELEASE)
        return jobs[0]

    def test_higher_radio_mentions_parent(self):
        # The user is shown an option to display only the blacklisted
        # package with a higer version than in the parent.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        radio_title = \
            "&nbsp;Ignored packages with a higher version than in 'Lucid'"
        radio_option_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "radio displays parent's name", 'label',
                text=radio_title),
            )
        self.assertThat(view.render(), radio_option_matches)

    def test_higher_radio_mentions_parents(self):
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParents()
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        radio_title = \
            "&nbsp;Ignored packages with a higher version than in parent"
        radio_option_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "radio displays parent's name", 'label',
                text=radio_title),
            )
        self.assertThat(view.render(), radio_option_matches)

    def _set_source_selection(self, series):
        # Set up source package format selection so that copying will
        # work with the default dsc_format used in
        # makeSourcePackageRelease.
        getUtility(ISourcePackageFormatSelectionSet).add(
            series, SourcePackageFormat.FORMAT_1_0)

    def test_batch_filtered(self):
        # The name_filter parameter allows filtering of packages by name.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()
        diff1 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        diff2 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-second-src-package")

        filtered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.name_filter=my-src-package')
        unfiltered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [diff1], filtered_view.cached_differences.batch)
        self.assertContentEqual(
            [diff2, diff1], unfiltered_view.cached_differences.batch)

    def test_batch_non_blacklisted(self):
        # The default filter is all non blacklisted differences.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()
        diff1 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        diff2 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-second-src-package")
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        filtered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' % NON_IGNORED)
        filtered_view2 = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [diff2, diff1], filtered_view.cached_differences.batch)
        self.assertContentEqual(
            [diff2, diff1], filtered_view2.cached_differences.batch)

    def test_batch_differences_packages(self):
        # field.package_type parameter allows to list only
        # blacklisted differences.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()
        blacklisted_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        blacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' % IGNORED)
        unblacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [blacklisted_diff], blacklisted_view.cached_differences.batch)
        self.assertContentEqual(
            [], unblacklisted_view.cached_differences.batch)

    def test_batch_blacklisted_differences_with_higher_version(self):
        # field.package_type parameter allows to list only
        # blacklisted differences with a child's version higher than parent's.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()
        blacklisted_diff_higher = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            versions={'base': '1.1', 'parent': '1.3', 'derived': '1.10'})
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            versions={'base': '1.1', 'parent': '1.12', 'derived': '1.10'})

        blacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' % HIGHER_VERSION_THAN_PARENT)
        unblacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [blacklisted_diff_higher],
            blacklisted_view.cached_differences.batch)
        self.assertContentEqual(
            [], unblacklisted_view.cached_differences.batch)

    def test_batch_resolved_differences(self):
        # Test that we can search for differences that we marked
        # resolved.
        set_derived_series_ui_feature_flag(self)
        derived_series, parent_series = self._createChildAndParent()

        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-second-src-package")
        resolved_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.RESOLVED)

        filtered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' % RESOLVED)

        self.assertContentEqual(
            [resolved_diff], filtered_view.cached_differences.batch)

    def _setUpDSD(self, src_name='src-name', versions=None,
                  difference_type=None, distribution=None):
        # Helper to create a derived series with fixed names and proper
        # source package format selection along with a DSD.
        parent_series = self.factory.makeDistroSeries(name='warty')
        if distribution == None:
            distribution = self.factory.makeDistribution('deribuntu')
        derived_series = self.factory.makeDistroSeries(
            distribution=distribution,
            name='derilucid')
        self.factory.makeDistroSeriesParent(
            derived_series=derived_series, parent_series=parent_series)
        self._set_source_selection(derived_series)
        diff = self.factory.makeDistroSeriesDifference(
            source_package_name_str=src_name,
            derived_series=derived_series, versions=versions,
            difference_type=difference_type)
        sourcepackagename = self.factory.getOrMakeSourcePackageName(
            src_name)
        set_derived_series_ui_feature_flag(self)
        return derived_series, parent_series, sourcepackagename, str(diff.id)

    def test_canPerformSync_anon(self):
        # Anonymous users cannot sync packages.
        derived_series = self._setUpDSD()[0]
        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        self.assertFalse(view.canPerformSync())

    def test_canPerformSync_non_anon_no_perm_dest_archive(self):
        # Logged-in users with no permission on the destination archive
        # are not presented with options to perform syncs.
        derived_series = self._setUpDSD()[0]
        with person_logged_in(self.factory.makePerson()):
            view = create_initialized_view(
                derived_series, '+localpackagediffs')

            self.assertFalse(view.canPerformSync())

    def _setUpPersonWithPerm(self, derived_series):
        # Helper to create a person with an upload permission on the
        # series' archive.
        person = self.factory.makePerson()
        ArchivePermission(
            archive=derived_series.main_archive, person=person,
            component=getUtility(IComponentSet)["main"],
            permission=ArchivePermissionType.QUEUE_ADMIN)
        return person

    def test_canPerformSync_non_anon(self):
        # Logged-in users with a permission on the destination archive
        # are presented with options to perform syncs.
        # Note that a more fine-grained perm check is done on each
        # synced package.
        derived_series = self._setUpDSD()[0]
        person = self._setUpPersonWithPerm(derived_series)
        set_derived_series_sync_feature_flag(self)
        with person_logged_in(person):
            view = create_initialized_view(
                derived_series, '+localpackagediffs')

            self.assertTrue(view.canPerformSync())

    def test_canPerformSync_non_anon_feature_disabled(self):
        # Logged-in users with a permission on the destination archive
        # are not presented with options to perform syncs when the
        # feature flag is not enabled.
        self.assertIs(
            None, getFeatureFlag('soyuz.derived_series_sync.enabled'))
        derived_series = self._setUpDSD()[0]
        person = self._setUpPersonWithPerm(derived_series)
        with person_logged_in(person):
            view = create_initialized_view(
                derived_series, '+localpackagediffs')

            self.assertFalse(view.canPerformSync())

    def test_hasPendingDSDUpdate_returns_False_if_no_pending_update(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertFalse(view.hasPendingDSDUpdate(dsd))

    def test_hasPendingDSDUpdate_returns_True_if_pending_update(self):
        set_derived_series_difference_jobs_feature_flag(self)
        dsd = self.factory.makeDistroSeriesDifference()
        self.makeDSDJob(dsd)
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertTrue(view.hasPendingDSDUpdate(dsd))

    def test_hasPendingSync_returns_False_if_no_pending_sync(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertFalse(view.hasPendingSync(dsd))

    def test_hasPendingSync_returns_True_if_pending_sync(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.pending_syncs = {dsd.source_package_name.name: object()}
        self.assertTrue(view.hasPendingSync(dsd))

    def test_isNewerThanParent_compares_versions_not_strings(self):
        # isNewerThanParent compares Debian-style version numbers, not
        # raw version strings.  So it's possible for a child version to
        # be considered newer than the corresponding parent version even
        # though a string comparison goes the other way.
        versions = dict(base='1.0', parent='1.1c', derived='1.10')
        dsd = self.factory.makeDistroSeriesDifference(versions=versions)
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')

        # Assumption for the test: the child version is greater than the
        # parent version, but a string comparison puts them the other
        # way around.
        self.assertFalse(versions['parent'] < versions['derived'])
        self.assertTrue(
            Version(versions['parent']) < Version(versions['derived']))

        # isNewerThanParent is not fooled by the misleading string
        # comparison.
        self.assertTrue(view.isNewerThanParent(dsd))

    def test_isNewerThanParent_is_False_for_parent_update(self):
        dsd = self.factory.makeDistroSeriesDifference(
            versions=dict(base='1.0', parent='1.1', derived='1.0'))
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertFalse(view.isNewerThanParent(dsd))

    def test_isNewerThanParent_is_False_for_equivalent_updates(self):
        # Some non-identical version numbers compare as "equal."  If the
        # child and parent versions compare as equal, the child version
        # is not considered newer.
        dsd = self.factory.makeDistroSeriesDifference(
            versions=dict(base='1.0', parent='1.1', derived='1.1'))
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertFalse(view.isNewerThanParent(dsd))

    def test_isNewerThanParent_is_True_for_child_update(self):
        dsd = self.factory.makeDistroSeriesDifference(
            versions=dict(base='1.0', parent='1.0', derived='1.1'))
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertTrue(view.isNewerThanParent(dsd))

    def test_canRequestSync_returns_False_if_pending_sync(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.pending_syncs = {dsd.source_package_name.name: object()}
        self.assertFalse(view.canRequestSync(dsd))

    def test_canRequestSync_returns_False_if_child_is_newer(self):
        dsd = self.factory.makeDistroSeriesDifference(
            versions=dict(base='1.0', parent='1.0', derived='1.1'))
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertFalse(view.canRequestSync(dsd))

    def test_canRequestSync_returns_True_if_sync_makes_sense(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertTrue(view.canRequestSync(dsd))

    def test_canRequestSync_ignores_DSDJobs(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.hasPendingDSDUpdate = FakeMethod(result=True)
        self.assertTrue(view.canRequestSync(dsd))

    def test_describeJobs_returns_None_if_no_jobs(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertIs(None, view.describeJobs(dsd))

    def test_describeJobs_reports_pending_update(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.hasPendingDSDUpdate = FakeMethod(result=True)
        view.hasPendingSync = FakeMethod(result=False)
        self.assertEqual("updating&hellip;", view.describeJobs(dsd))

    def test_describeJobs_reports_pending_sync(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.hasPendingDSDUpdate = FakeMethod(result=False)
        view.hasPendingSync = FakeMethod(result=True)
        self.assertEqual("synchronizing&hellip;", view.describeJobs(dsd))

    def test_describeJobs_reports_pending_sync_and_update(self):
        dsd = self.factory.makeDistroSeriesDifference()
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        view.hasPendingDSDUpdate = FakeMethod(result=True)
        view.hasPendingSync = FakeMethod(result=True)
        self.assertEqual(
            "updating and synchronizing&hellip;", view.describeJobs(dsd))

    def _syncAndGetView(self, derived_series, person, sync_differences,
                        difference_type=None, view_name='+localpackagediffs'):
        # A helper to get the POST'ed sync view.
        with person_logged_in(person):
            view = create_initialized_view(
                derived_series, view_name,
                method='POST', form={
                    'field.selected_differences': sync_differences,
                    'field.actions.sync': 'Sync',
                    })
            return view

    def test_sync_error_nothing_selected(self):
        # An error is raised when a sync is requested without any selection.
        derived_series = self._setUpDSD()[0]
        person = self._setUpPersonWithPerm(derived_series)
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(derived_series, person, [])

        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            'No differences selected.', view.errors[0])

    def test_sync_error_invalid_selection(self):
        # An error is raised when an invalid difference is selected.
        derived_series, unused, unused2, diff_id = self._setUpDSD(
            'my-src-name')
        person = self._setUpPersonWithPerm(derived_series)
        another_id = str(int(diff_id) + 1)
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(
            derived_series, person, [another_id])

        self.assertEqual(2, len(view.errors))
        self.assertEqual(
            'No differences selected.', view.errors[0])
        self.assertEqual(
            'Invalid value', view.errors[1].error_name)

    def test_sync_error_no_perm_dest_archive(self):
        # A user without upload rights on the destination archive cannot
        # sync packages.
        derived_series, unused, unused2, diff_id = self._setUpDSD(
            'my-src-name')
        person = self._setUpPersonWithPerm(derived_series)
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(
            derived_series, person, [diff_id])

        self.assertEqual(1, len(view.errors))
        self.assertTrue(
            "The signer of this package has no upload rights to this "
            "distribution's primary archive" in view.errors[0])

    def makePersonWithComponentPermission(self, archive, component=None):
        person = self.factory.makePerson()
        if component is None:
            component = self.factory.makeComponent()
        removeSecurityProxy(archive).newComponentUploader(
            person, component)
        return person, component

    def test_sync_success_perm_component(self):
        # A user with upload rights on the destination component
        # can sync packages.
        derived_series, parent_series, sp_name, diff_id = self._setUpDSD(
            'my-src-name')
        person, _ = self.makePersonWithComponentPermission(
            derived_series.main_archive,
            derived_series.getSourcePackage(
                sp_name).latest_published_component)
        view = self._syncAndGetView(
            derived_series, person, [diff_id])

        self.assertEqual(0, len(view.errors))

    def test_sync_error_no_perm_component(self):
        # A user without upload rights on the destination component
        # will get an error when he syncs packages to this component.
        derived_series, parent_series, unused, diff_id = self._setUpDSD(
            'my-src-name')
        person, another_component = self.makePersonWithComponentPermission(
            derived_series.main_archive)
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(
            derived_series, person, [diff_id])

        self.assertEqual(1, len(view.errors))
        self.assertTrue(
            "Signer is not permitted to upload to the "
            "component" in view.errors[0])

    def assertPackageCopied(self, series, src_name, version, view):
        # Helper to check that a package has been copied.
        # The new version should now be in the destination series.
        pub = series.main_archive.getPublishedSources(
            name=src_name, version=version,
            distroseries=series).one()
        self.assertIsNot(None, pub)
        self.assertEqual(version, pub.sourcepackagerelease.version)

        # The view should show no errors, and the notification should
        # confirm the sync worked.
        self.assertEqual(0, len(view.errors))
        notifications = view.request.response.notifications
        self.assertEqual(1, len(notifications))
        self.assertEqual(
            '<p>Packages copied to '
            '<a href="http://launchpad.dev/%s/%s"'
            '>Derilucid</a>:</p>\n<ul>\n<li>my-src-name 1.0-1 in '
            'derilucid</li>\n</ul>' % (series.parent.name, series.name),
            notifications[0].message)
        # 302 is a redirect back to the same page.
        self.assertEqual(302, view.request.response.getStatus())

    def test_sync_notification_on_success(self):
        # A user with upload rights on the destination archive can
        # sync packages. Notifications about the synced packages are
        # displayed and the packages are copied inside the destination
        # series.
        versions = {
            'base': '1.0',
            'derived': '1.0derived1',
            'parent': '1.0-1',
        }
        derived_series, parent_series, sp_name, diff_id = self._setUpDSD(
            'my-src-name', versions=versions)

        # Setup a user with upload rights.
        person = self.factory.makePerson()
        removeSecurityProxy(derived_series.main_archive).newPackageUploader(
            person, sp_name)

        # The inital state is that 1.0-1 is not in the derived series.
        pubs = derived_series.main_archive.getPublishedSources(
            name='my-src-name', version=versions['parent'],
            distroseries=derived_series).any()
        self.assertIs(None, pubs)

        # Now, sync the source from the parent using the form.
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(
            derived_series, person, [diff_id])

        # The parent's version should now be in the derived series and
        # the notifications displayed:
        self.assertPackageCopied(
            derived_series, 'my-src-name', versions['parent'], view)

    def test_sync_success_not_yet_in_derived_series(self):
        # If the package to sync does not exist yet in the derived series,
        # upload right to any component inside the destination series will be
        # enough to sync the package.
        versions = {
            'parent': '1.0-1',
        }
        missing = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        derived_series, parent_series, unused, diff_id = self._setUpDSD(
            'my-src-name', difference_type=missing, versions=versions)
        person, another_component = self.makePersonWithComponentPermission(
            derived_series.main_archive)
        set_derived_series_sync_feature_flag(self)
        view = self._syncAndGetView(
            derived_series, person, [diff_id],
            view_name='+missingpackages')

        self.assertPackageCopied(
            derived_series, 'my-src-name', versions['parent'], view)

    def test_sync_in_released_series_in_updates(self):
        # If the destination series is released, the sync packages end
        # up in the updates pocket.
        versions = {
            'parent': '1.0-1',
            }
        derived_series, parent_series, sp_name, diff_id = self._setUpDSD(
            'my-src-name', versions=versions)
        # Update destination series status to current and update
        # daterelease.
        with celebrity_logged_in('admin'):
            derived_series.status = SeriesStatus.CURRENT
            derived_series.datereleased = UTC_NOW

        set_derived_series_sync_feature_flag(self)
        person = self.factory.makePerson()
        removeSecurityProxy(derived_series.main_archive).newPackageUploader(
            person, sp_name)
        self._syncAndGetView(
            derived_series, person, [diff_id])
        parent_pub = parent_series.main_archive.getPublishedSources(
            name='my-src-name', version=versions['parent'],
            distroseries=parent_series).one()
        pub = derived_series.main_archive.getPublishedSources(
            name='my-src-name', version=versions['parent'],
            distroseries=derived_series).one()
        self.assertEqual(self.factory.getAnyPocket(), parent_pub.pocket)
        self.assertEqual(PackagePublishingPocket.UPDATES, pub.pocket)


class TestDistroSeriesNeedsPackagesView(TestCaseWithFactory):
    """Test the distroseries +needs-packaging view."""

    layer = LaunchpadZopelessLayer

    def test_cached_unlinked_packages(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        view = create_initialized_view(distroseries, '+needs-packaging')
        self.assertTrue(
            IResultSet.providedBy(
                view.cached_unlinked_packages.currentBatch().list),
            '%s should batch IResultSet so that slicing will limit the '
            'query' % view.cached_unlinked_packages.currentBatch().list)


class DistroSeriesMissingPackageDiffsTestCase(TestCaseWithFactory):
    """Test the distroseries +missingpackages view."""

    layer = LaunchpadZopelessLayer

    def test_missingpackages_differences(self):
        # The view fetches the differences with type
        # MISSING_FROM_DERIVED_SERIES.
        dsp = self.factory.makeDistroSeriesParent()
        derived_series = dsp.derived_series

        missing_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        # Missing blacklisted diff.
        self.factory.makeDistroSeriesDifference(
            difference_type=missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        missing_diff = self.factory.makeDistroSeriesDifference(
            difference_type=missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.NEEDS_ATTENTION)

        view = create_initialized_view(
            derived_series, '+missingpackages')

        self.assertContentEqual(
            [missing_diff], view.cached_differences.batch)

    def test_missingpackages_differences_empty(self):
        # The view is empty if there is no differences with type
        # MISSING_FROM_DERIVED_SERIES.
        dsp = self.factory.makeDistroSeriesParent()
        derived_series = dsp.derived_series

        not_missing_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS

        # Missing diff.
        self.factory.makeDistroSeriesDifference(
            difference_type=not_missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.NEEDS_ATTENTION)

        view = create_initialized_view(
            derived_series, '+missingpackages')

        self.assertContentEqual(
            [], view.cached_differences.batch)

    def test_isNewerThanParent_is_False_if_missing_from_child(self):
        # If a package is missing from the child series,
        # isNewerThanParent returns False.
        missing_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        dsd = self.factory.makeDistroSeriesDifference(
            difference_type=missing_type)
        view = create_initialized_view(dsd.derived_series, '+missingpackages')
        self.assertFalse(view.isNewerThanParent(dsd))


class DistroSeriesMissingPackagesPageTestCase(TestCaseWithFactory,
                                              DistroSeriesDifferenceMixin):
    """Test the distroseries +missingpackages page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(DistroSeriesMissingPackagesPageTestCase,
              self).setUp('foo.bar@canonical.com')
        set_derived_series_ui_feature_flag(self)
        self.simple_user = self.factory.makePerson()

    def test_parent_packagesets_missingpackages(self):
        # +missingpackages displays the packagesets in the parent.
        missing_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        self.ds_diff = self.factory.makeDistroSeriesDifference(
            difference_type=missing_type)

        with celebrity_logged_in('admin'):
            ps = self.factory.makePackageset(
                packages=[self.ds_diff.source_package_name],
                distroseries=self.ds_diff.parent_series)

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                self.ds_diff.derived_series,
                '+missingpackages',
                principal=self.simple_user)
            html_content = view()

        packageset_text = re.compile('\s*' + ps.name)
        self._test_packagesets(
            html_content, packageset_text, 'parent-packagesets',
            'Parent packagesets')


class DistroSerieUniquePackageDiffsTestCase(TestCaseWithFactory,
                                            DistroSeriesDifferenceMixin):
    """Test the distroseries +uniquepackages view."""

    layer = LaunchpadZopelessLayer

    def test_uniquepackages_differences(self):
        # The view fetches the differences with type
        # UNIQUE_TO_DERIVED_SERIES.
        derived_series, parent_series = self._createChildAndParent()

        missing_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        # Missing blacklisted diff.
        self.factory.makeDistroSeriesDifference(
            difference_type=missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        missing_diff = self.factory.makeDistroSeriesDifference(
            difference_type=missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.NEEDS_ATTENTION)

        view = create_initialized_view(
            derived_series, '+uniquepackages')

        self.assertContentEqual(
            [missing_diff], view.cached_differences.batch)

    def test_uniquepackages_differences_empty(self):
        # The view is empty if there is no differences with type
        # UNIQUE_TO_DERIVED_SERIES.
        derived_series, parent_series = self._createChildAndParent()

        not_missing_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS

        # Missing diff.
        self.factory.makeDistroSeriesDifference(
            difference_type=not_missing_type,
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.NEEDS_ATTENTION)

        view = create_initialized_view(
            derived_series, '+uniquepackages')

        self.assertContentEqual(
            [], view.cached_differences.batch)

    def test_isNewerThanParent_is_True_if_unique_to_child(self):
        unique_to_child = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        dsd = self.factory.makeDistroSeriesDifference(
            difference_type=unique_to_child)
        view = create_initialized_view(
            dsd.derived_series, '+localpackagediffs')
        self.assertTrue(view.isNewerThanParent(dsd))


class DistroSeriesUniquePackagesPageTestCase(TestCaseWithFactory,
                                             DistroSeriesDifferenceMixin):
    """Test the distroseries +uniquepackages page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(DistroSeriesUniquePackagesPageTestCase,
              self).setUp('foo.bar@canonical.com')
        set_derived_series_ui_feature_flag(self)
        self.simple_user = self.factory.makePerson()

    def test_packagesets_uniquepackages(self):
        # +uniquepackages displays the packagesets in the parent.
        missing_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        self.ds_diff = self.factory.makeDistroSeriesDifference(
            difference_type=missing_type)

        with celebrity_logged_in('admin'):
            ps = self.factory.makePackageset(
                packages=[self.ds_diff.source_package_name],
                distroseries=self.ds_diff.derived_series)

        with person_logged_in(self.simple_user):
            view = create_initialized_view(
                self.ds_diff.derived_series,
                '+uniquepackages',
                principal=self.simple_user)
            html = view()

        packageset_text = re.compile('\s*' + ps.name)
        self._test_packagesets(
            html, packageset_text, 'packagesets', 'Packagesets')
