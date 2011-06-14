# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""View classes related to `IDistroSeries`."""

__metaclass__ = type

__all__ = [
    'DistroSeriesAddView',
    'DistroSeriesAdminView',
    'DistroSeriesBreadcrumb',
    'DistroSeriesEditView',
    'DistroSeriesFacets',
    'DistroSeriesInitializeView',
    'DistroSeriesLocalDifferencesView',
    'DistroSeriesMissingPackagesView',
    'DistroSeriesNavigation',
    'DistroSeriesPackageSearchView',
    'DistroSeriesPackagesView',
    'DistroSeriesUniquePackagesView',
    'DistroSeriesView',
    ]

import apt_pkg
from lazr.restful.interface import copy_field
from lazr.restful.interfaces import IJSONRequestCache
from zope.component import getUtility
from zope.event import notify
from zope.formlib import form
from zope.interface import Interface
from zope.lifecycleevent import ObjectCreatedEvent
from zope.schema import (
    Choice,
    List,
    TextLine,
    )
from zope.schema.vocabulary import (
    SimpleTerm,
    SimpleVocabulary,
    )

from canonical.database.constants import UTC_NOW
from canonical.launchpad import (
    _,
    helpers,
    )
from canonical.launchpad.webapp import (
    action,
    custom_widget,
    GetitemNavigation,
    StandardLaunchpadFacets,
    )
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.menu import (
    ApplicationMenu,
    enabled_with_permission,
    Link,
    NavigationMenu,
    structured,
    )
from canonical.launchpad.webapp.publisher import (
    canonical_url,
    LaunchpadView,
    stepthrough,
    stepto,
    )
from lp.app.browser.launchpadform import (
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.errors import NotFoundError
from lp.app.widgets.itemswidgets import (
    LabeledMultiCheckBoxWidget,
    LaunchpadDropdownWidget,
    LaunchpadRadioWidget,
    )
from lp.blueprints.browser.specificationtarget import (
    HasSpecificationsMenuMixin,
    )
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.bugs.browser.structuralsubscription import (
    expose_structural_subscription_data_to_js,
    StructuralSubscriptionMenuMixin,
    StructuralSubscriptionTargetTraversalMixin,
    )
from lp.registry.browser import (
    add_subscribe_link,
    MilestoneOverlayMixin,
    )
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifferenceSource,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty
from lp.services.worlddata.interfaces.country import ICountry
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.soyuz.browser.archive import PackageCopyingMixin
from lp.soyuz.browser.packagesearch import PackageSearchViewBase
from lp.soyuz.enums import PackageCopyPolicy
from lp.soyuz.interfaces.distributionjob import (
    IDistroSeriesDifferenceJobSource,
    )
from lp.soyuz.interfaces.packagecopyjob import IPlainPackageCopyJobSource
from lp.soyuz.interfaces.queue import IPackageUploadSet
from lp.soyuz.model.queue import PackageUploadQueue
from lp.translations.browser.distroseries import (
    check_distroseries_translations_viewable,
    )

# DistroSeries statuses that benefit from mass package upgrade support.
UPGRADABLE_SERIES_STATUSES = [
    SeriesStatus.FUTURE,
    SeriesStatus.EXPERIMENTAL,
    SeriesStatus.DEVELOPMENT,
    ]


class DistroSeriesNavigation(GetitemNavigation, BugTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin):

    usedfor = IDistroSeries

    @stepthrough('+lang')
    def traverse_lang(self, langcode):
        """Retrieve the DistroSeriesLanguage or a dummy if one it is None."""
        # We do not want users to see the 'en' pofile because
        # we store the messages we want to translate as English.
        if langcode == 'en':
            raise NotFoundError(langcode)

        langset = getUtility(ILanguageSet)
        try:
            lang = langset[langcode]
        except IndexError:
            # Unknown language code.
            raise NotFoundError

        distroserieslang = self.context.getDistroSeriesLanguageOrDummy(lang)

        # Check if user is able to view the translations for
        # this distribution series language.
        # If not, raise TranslationUnavailable.
        check_distroseries_translations_viewable(self.context)

        return distroserieslang

    @stepthrough('+source')
    def source(self, name):
        return self.context.getSourcePackage(name)

    # sabdfl 17/10/05 please keep this old location here for
    # LaunchpadIntegration on Breezy, unless you can figure out how to
    # redirect to the newer +source, defined above
    @stepthrough('+sources')
    def sources(self, name):
        return self.context.getSourcePackage(name)

    @stepthrough('+package')
    def package(self, name):
        return self.context.getBinaryPackage(name)

    @stepto('+latest-full-language-pack')
    def latest_full_language_pack(self):
        if self.context.last_full_language_pack_exported is None:
            return None
        else:
            return self.context.last_full_language_pack_exported.file

    @stepto('+latest-delta-language-pack')
    def redirect_latest_delta_language_pack(self):
        if self.context.last_delta_language_pack_exported is None:
            return None
        else:
            return self.context.last_delta_language_pack_exported.file

    @stepthrough('+upload')
    def traverse_queue(self, id):
        return getUtility(IPackageUploadSet).get(id)


class DistroSeriesBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IDistroSeries`."""

    @property
    def text(self):
        return self.context.named_version


class DistroSeriesFacets(StandardLaunchpadFacets):

    usedfor = IDistroSeries
    enable_only = ['overview', 'branches', 'bugs', 'specifications',
                   'translations']


class DistroSeriesOverviewMenu(
    ApplicationMenu, StructuralSubscriptionMenuMixin):

    usedfor = IDistroSeries
    facet = 'overview'

    @property
    def links(self):
        links = ['edit',
                 'driver',
                 'answers',
                 'packaging',
                 'needs_packaging',
                 'builds',
                 'queue',
                 'add_port',
                 'create_milestone',
                 ]
        add_subscribe_link(links)
        links.append('admin')
        return links

    @enabled_with_permission('launchpad.Admin')
    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        text = 'Appoint driver'
        summary = 'Someone with permission to set goals for this series'
        return Link('+driver', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def create_milestone(self):
        text = 'Create milestone'
        summary = 'Register a new milestone for this series'
        return Link('+addmilestone', text, summary, icon='add')

    def packaging(self):
        text = 'All upstream links'
        summary = 'A listing of source packages and their upstream projects'
        return Link('+packaging', text, summary=summary, icon='info')

    def needs_packaging(self):
        text = 'Needs upstream links'
        summary = 'A listing of source packages without upstream projects'
        return Link('+needs-packaging', text, summary=summary, icon='info')

    # A search link isn't needed because the distro series overview
    # has a search form.
    def answers(self):
        text = 'Ask a question'
        url = canonical_url(self.context.distribution) + '/+addquestion'
        return Link(url, text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def add_port(self):
        text = 'Add architecture'
        return Link('+addport', text, icon='add')

    @enabled_with_permission('launchpad.Moderate')
    def admin(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')

    def builds(self):
        text = 'Show builds'
        return Link('+builds', text, icon='info')

    def queue(self):
        text = 'Show uploads'
        return Link('+queue', text, icon='info')


class DistroSeriesBugsMenu(ApplicationMenu, StructuralSubscriptionMenuMixin):

    usedfor = IDistroSeries
    facet = 'bugs'

    @property
    def links(self):
        links = ['cve',
                 'nominations',
                 ]
        add_subscribe_link(links)
        return links

    def cve(self):
        return Link('+cve', 'CVE reports', icon='cve')

    def nominations(self):
        return Link('+nominations', 'Review nominations', icon='bug')


class DistroSeriesSpecificationsMenu(NavigationMenu,
                                     HasSpecificationsMenuMixin):

    usedfor = IDistroSeries
    facet = 'specifications'
    links = [
        'listall', 'listdeclined', 'assignments', 'setgoals',
        'new', 'register_sprint']


class DistroSeriesPackageSearchView(PackageSearchViewBase):
    """Customised PackageSearchView for DistroSeries"""

    def contextSpecificSearch(self):
        """See `AbstractPackageSearchView`."""
        return self.context.searchPackages(self.text)

    label = 'Search packages'


class SeriesStatusMixin:
    """A mixin that provides status field support."""

    def createStatusField(self):
        """Create the 'status' field.

        Create the status vocabulary according the current distroseries
        status:
         * stable   -> CURRENT, SUPPORTED, OBSOLETE
         * unstable -> EXPERIMENTAL, DEVELOPMENT, FROZEN, FUTURE, CURRENT
        """
        stable_status = (
            SeriesStatus.CURRENT,
            SeriesStatus.SUPPORTED,
            SeriesStatus.OBSOLETE,
            )

        if self.context.status not in stable_status:
            terms = [status for status in SeriesStatus.items
                     if status not in stable_status]
            terms.append(SeriesStatus.CURRENT)
        else:
            terms = stable_status

        status_vocabulary = SimpleVocabulary(
            [SimpleTerm(item, item.name, item.title) for item in terms])

        return form.Fields(
            Choice(__name__='status',
                   title=_('Status'),
                   default=self.context.status,
                   vocabulary=status_vocabulary,
                   description=_("Select the distroseries status."),
                   required=True))

    def updateDateReleased(self, status):
        """Update the datereleased field if the status is set to CURRENT."""
        if (self.context.datereleased is None and
            status == SeriesStatus.CURRENT):
            self.context.datereleased = UTC_NOW


class DerivedDistroSeriesMixin:

    @cachedproperty
    def has_unique_parent(self):
        return len(self.context.getParentSeries()) == 1

    @cachedproperty
    def unique_parent(self):
        if self.has_unique_parent:
            return self.context.getParentSeries()[0]
        else:
            None

    @cachedproperty
    def number_of_parents(self):
        return len(self.context.getParentSeries())

    def getParentName(self, multiple_parent_default=None):
        if self.has_unique_parent:
            return ("parent series '%s'" %
                self.unique_parent.displayname)
        else:
            if multiple_parent_default is not None:
                return multiple_parent_default
            else:
                return 'a parent series'


class DistroSeriesView(LaunchpadView, MilestoneOverlayMixin,
                       DerivedDistroSeriesMixin):

    def initialize(self):
        super(DistroSeriesView, self).initialize()
        self.displayname = '%s %s' % (
            self.context.distribution.displayname,
            self.context.version)
        expose_structural_subscription_data_to_js(
            self.context, self.request, self.user)

    @property
    def page_title(self):
        """Return the HTML page title."""
        return '%s %s in Launchpad' % (
        self.context.distribution.title, self.context.version)

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def redirectToDistroFileBug(self):
        """Redirect to the distribution's filebug page.

        Filing a bug on a distribution series is not directly
        permitted; we redirect to the distribution's file
        """
        distro_url = canonical_url(
            self.context.distribution, view_name='+filebug')
        if self.request.form.get('no-redirect') is not None:
            distro_url += '?no-redirect'
        return self.request.response.redirect(distro_url)

    @cachedproperty
    def num_linked_packages(self):
        """The number of linked packagings for this distroseries."""
        return self.context.packagings.count()

    @property
    def num_unlinked_packages(self):
        """The number of unlinked packagings for this distroseries."""
        return self.context.sourcecount - self.num_linked_packages

    @cachedproperty
    def recently_linked(self):
        """Return the packages that were most recently linked upstream."""
        return self.context.getMostRecentlyLinkedPackagings()

    @cachedproperty
    def needs_linking(self):
        """Return a list of 10 packages most in need of upstream linking."""
        # XXX sinzui 2010-02-26 bug=528648: This method causes a timeout.
        # return self.context.getPrioritizedUnlinkedSourcePackages()[:10]
        return None

    milestone_can_release = False

    @cachedproperty
    def milestone_batch_navigator(self):
        return BatchNavigator(self.context.all_milestones, self.request)

    def _num_differences(self, difference_type):
        differences = getUtility(
            IDistroSeriesDifferenceSource).getForDistroSeries(
                self.context,
                difference_type=difference_type,
                status=(DistroSeriesDifferenceStatus.NEEDS_ATTENTION,))
        return differences.count()

    @cachedproperty
    def num_differences(self):
        return self._num_differences(
            DistroSeriesDifferenceType.DIFFERENT_VERSIONS)

    @cachedproperty
    def num_differences_in_parent(self):
        return self._num_differences(
            DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES)

    @cachedproperty
    def num_differences_in_child(self):
        return self._num_differences(
            DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES)


class DistroSeriesEditView(LaunchpadEditFormView, SeriesStatusMixin):
    """View class that lets you edit a DistroSeries object.

    It redirects to the main distroseries page after a successful edit.
    """
    schema = IDistroSeries
    field_names = ['displayname', 'title', 'summary', 'description']
    custom_widget('status', LaunchpadDropdownWidget)

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Edit %s details' % self.context.title

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    def setUpFields(self):
        """See `LaunchpadFormView`.

        In addition to setting schema fields, also initialize the
        'status' field. See `createStatusField` method.
        """
        LaunchpadEditFormView.setUpFields(self)
        is_derivitive = not self.context.distribution.full_functionality
        has_admin = check_permission('launchpad.Admin', self.context)
        if has_admin or is_derivitive:
            # The user is an admin or this is an IDerivativeDistribution.
            self.form_fields = (
                self.form_fields + self.createStatusField())

    @action("Change")
    def change_action(self, action, data):
        """Update the context and redirects to its overviw page."""
        if not self.context.distribution.full_functionality:
            self.updateDateReleased(data.get('status'))
        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Your changes have been applied.')
        self.next_url = canonical_url(self.context)


class DistroSeriesAdminView(LaunchpadEditFormView, SeriesStatusMixin):
    """View class for administering a DistroSeries object.

    It redirects to the main distroseries page after a successful edit.
    """
    schema = IDistroSeries
    field_names = ['name', 'version', 'changeslist']
    custom_widget('status', LaunchpadDropdownWidget)

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Administer %s' % self.context.title

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    def setUpFields(self):
        """Override `LaunchpadFormView`.

        In addition to setting schema fields, also initialize the
        'status' field. See `createStatusField` method.
        """
        LaunchpadEditFormView.setUpFields(self)
        self.form_fields = (
            self.form_fields + self.createStatusField())

    @action("Change")
    def change_action(self, action, data):
        """Update the context and redirects to its overviw page.

        Also, set 'datereleased' when a unstable distroseries is made
        CURRENT.
        """
        self.updateDateReleased(data.get('status'))
        self.updateContextFromData(data)

        self.request.response.addInfoNotification(
            'Your changes have been applied.')
        self.next_url = canonical_url(self.context)


class IDistroSeriesAddForm(Interface):

    name = copy_field(
        IDistroSeries["name"], description=_(
            "The name of this series as used for URLs."))

    version = copy_field(
        IDistroSeries["version"], description=_(
            "The version of the new series."))

    displayname = copy_field(
        IDistroSeries["displayname"], description=_(
            "The name of the new series as it would "
            "appear in a paragraph."))

    summary = copy_field(IDistroSeries["summary"])


class DistroSeriesAddView(LaunchpadFormView):
    """A view to create an `IDistroSeries`."""
    schema = IDistroSeriesAddForm
    field_names = [
        'name',
        'version',
        'displayname',
        'summary',
        ]

    help_links = {
        "name": u"/+help/distribution-add-series.html#codename",
        }

    label = 'Add a series'
    page_title = label

    @action(_('Add Series'), name='create')
    def createAndAdd(self, action, data):
        """Create and add a new Distribution Series"""
        distroseries = self.context.newSeries(
            name=data['name'],
            displayname=data['displayname'],
            title=data['displayname'],
            summary=data['summary'],
            description=u"",
            version=data['version'],
            previous_series=None,
            registrant=self.user)
        notify(ObjectCreatedEvent(distroseries))
        self.next_url = canonical_url(distroseries)
        return distroseries

    @property
    def cancel_url(self):
        return canonical_url(self.context)


class EmptySchema(Interface):
    pass


class DistroSeriesInitializeView(LaunchpadFormView):
    """A view to initialize an `IDistroSeries`."""

    schema = EmptySchema
    label = 'Initialize series'
    page_title = label

    def initialize(self):
        super(DistroSeriesInitializeView, self).initialize()
        cache = IJSONRequestCache(self.request).objects
        distribution = self.context.distribution
        is_first_derivation = not distribution.has_published_sources
        cache['is_first_derivation'] = is_first_derivation
        if not is_first_derivation:
            def vocabularyValue(series):
                # Format the series fields like the series vocabulary
                # picker would do.
                return {
                    'value': series.id,
                    'title': '%s: %s'
                        % (series.distribution.displayname, series.title),
                    'api_uri': canonical_url(
                        series, path_only_if_possible=True)}

            cache['previous_series'] = vocabularyValue(
                self.context.previous_series)
            previous_parents = self.context.previous_series.getParentSeries()
            cache['previous_parents'] = [
                vocabularyValue(series) for series in previous_parents]

    @action(u"Initialize Series", name='initialize')
    def submit(self, action, data):
        """Stub for the Javascript in the page to use."""

    @property
    def is_derived_series_feature_enabled(self):
        return getFeatureFlag("soyuz.derived_series_ui.enabled") is not None

    @property
    def show_derivation_not_yet_available(self):
        return not self.is_derived_series_feature_enabled

    @property
    def show_derivation_form(self):
        return (
            self.is_derived_series_feature_enabled and
            not self.context.isInitializing() and
            not self.context.isInitialized())

    @property
    def show_already_initialized_message(self):
        return (
            self.is_derived_series_feature_enabled and
            self.context.isInitialized())

    @property
    def show_already_initializing_message(self):
        return (
            self.is_derived_series_feature_enabled and
            self.context.isInitializing())

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url


class DistroSeriesPackagesView(LaunchpadView):
    """A View to show series package to upstream package relationships."""

    label = 'All series packages linked to upstream project series'
    page_title = 'All upstream links'

    @cachedproperty
    def cached_packagings(self):
        """The batched upstream packaging links."""
        packagings = self.context.getPrioritizedPackagings()
        navigator = BatchNavigator(packagings, self.request, size=20)
        navigator.setHeadings('packaging', 'packagings')
        return navigator


# A helper to create package filtering radio button vocabulary.
NON_IGNORED = 'non-ignored'
IGNORED = 'ignored'
HIGHER_VERSION_THAN_PARENT = 'higher-than-parent'
RESOLVED = 'resolved'

DEFAULT_PACKAGE_TYPE = NON_IGNORED


def make_package_type_vocabulary(parent_name, higher_version_option=False):
    voc = [
        SimpleTerm(
            NON_IGNORED, NON_IGNORED, 'Non ignored packages'),
        SimpleTerm(IGNORED, IGNORED, 'Ignored packages'),
        SimpleTerm(RESOLVED, RESOLVED, "Resolved package differences")]
    if higher_version_option:
        higher_term = SimpleTerm(
            HIGHER_VERSION_THAN_PARENT,
            HIGHER_VERSION_THAN_PARENT,
            "Ignored packages with a higher version than in %s"
                % parent_name)
        voc.insert(2, higher_term)
    return SimpleVocabulary(tuple(voc))


class DistroSeriesNeedsPackagesView(LaunchpadView):
    """A View to show series package to upstream package relationships."""

    label = 'Packages that need upstream packaging links'
    page_title = 'Needs upstream links'

    @cachedproperty
    def cached_unlinked_packages(self):
        """The batched `ISourcePackage`s that needs packaging links."""
        packages = self.context.getPrioritizedUnlinkedSourcePackages()
        navigator = BatchNavigator(packages, self.request, size=20)
        navigator.setHeadings('package', 'packages')
        return navigator


class IDifferencesFormSchema(Interface):
    name_filter = TextLine(
        title=_("Package name contains"), required=False)

    selected_differences = List(
        title=_('Selected differences'),
        value_type=Choice(vocabulary=SimpleVocabulary([])),
        description=_("Select the differences for syncing."),
        required=True)


class DistroSeriesDifferenceBaseView(LaunchpadFormView,
                                     PackageCopyingMixin,
                                     DerivedDistroSeriesMixin):
    """Base class for all pages presenting differences between
    a derived series and its parent."""
    schema = IDifferencesFormSchema
    field_names = ['selected_differences']
    custom_widget('selected_differences', LabeledMultiCheckBoxWidget)
    custom_widget('package_type', LaunchpadRadioWidget)

    # Differences type to display. Can be overrided by sublasses.
    differences_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
    show_parent_version = True
    show_derived_version = True
    show_package_diffs = True
    # Packagesets display.
    show_parent_packagesets = False
    show_packagesets = False
    # Search vocabulary.
    search_higher_parent_option = False

    def initialize(self):
        """Redirect to the derived series if the feature is not enabled."""
        if not getFeatureFlag('soyuz.derived_series_ui.enabled'):
            self.request.response.redirect(canonical_url(self.context))
            return

        super(DistroSeriesDifferenceBaseView, self).initialize()

    def initialize_sync_label(self, label):
        self.__class__.actions.byname['actions.sync'].label = label

    @property
    def label(self):
        return NotImplementedError()

    def setupPackageFilterRadio(self):
        if self.has_unique_parent:
            parent_name = "'%s'" % self.unique_parent.displayname
        else:
            parent_name = 'parent'
        return form.Fields(Choice(
            __name__='package_type',
            vocabulary=make_package_type_vocabulary(
                parent_name,
                self.search_higher_parent_option),
            default=DEFAULT_PACKAGE_TYPE,
            required=True))

    def setUpFields(self):
        """Add the selected differences field.

        As this field depends on other search/filtering field values
        for its own vocabulary, we set it up after all the others.
        """
        super(DistroSeriesDifferenceBaseView, self).setUpFields()
        self.form_fields = (
            self.setupPackageFilterRadio() +
            self.form_fields)
        check_permission('launchpad.Edit', self.context)
        terms = [
            SimpleTerm(diff, diff.id)
                    for diff in self.cached_differences.batch]
        diffs_vocabulary = SimpleVocabulary(terms)
        choice = self.form_fields['selected_differences'].field.value_type
        choice.vocabulary = diffs_vocabulary

    def _sync_sources(self, action, data):
        """Synchronise packages from the parent series to this one."""
        # We're doing a direct copy sync here as an interim measure
        # until we work out if it's fast enough to work reliably.  If it
        # isn't, we need to implement a way of flagging sources 'to be
        # synced' and write a job runner to do it in the background.

        selected_differences = data['selected_differences']
        sources = [
            diff.parent_source_pub
            for diff in selected_differences]

        # PackageCopyingMixin.do_copy() does the work of copying and
        # setting up on-page notifications.
        series_url = canonical_url(self.context)
        series_title = self.context.displayname

        # If the series is released, sync packages in the "updates" pocket.
        if self.context.supported:
            destination_pocket = PackagePublishingPocket.UPDATES
        else:
            destination_pocket = PackagePublishingPocket.RELEASE

        # When syncing we *must* do it asynchronously so that a package
        # copy job is created.  This gives the job a chance to inspect
        # the copy and create a PackageUpload if required.
        if self.do_copy(
            'selected_differences', sources, self.context.main_archive,
            self.context, destination_pocket, include_binaries=False,
            dest_url=series_url, dest_display_name=series_title,
            person=self.user, force_async=True):
            # The copy worked so we can redirect back to the page to
            # show the results.
            self.next_url = self.request.URL

    def validate_sync(self, action, data):
        """Validate selected differences."""
        form.getWidgetsData(self.widgets, self.prefix, data)

        if len(data.get('selected_differences', [])) == 0:
            self.setFieldError(
                'selected_differences', 'No differences selected.')

    def canPerformSync(self, *args):
        """Return whether a sync can be performed.

        This method is used as a condition for the above sync action, as
        well as directly in the template.
        """
        if not getFeatureFlag('soyuz.derived_series_sync.enabled'):
            return False

        archive = self.context.main_archive
        has_perm = (self.user is not None and (
                        archive.hasAnyPermission(self.user) or
                        check_permission('launchpad.Append', archive)))
        return (has_perm and
                self.cached_differences.batch.total() > 0)

    @cachedproperty
    def pending_syncs(self):
        """Pending synchronization jobs for this distroseries.

        :return: A dict mapping package names to pending sync jobs.
        """
        job_source = getUtility(IPlainPackageCopyJobSource)
        return job_source.getPendingJobsPerPackage(self.context)

    @cachedproperty
    def pending_dsd_updates(self):
        """Pending `DistroSeriesDifference` update jobs.

        :return: A `set` of `DistroSeriesDifference`s that have pending
            `DistroSeriesDifferenceJob`s.
        """
        job_source = getUtility(IDistroSeriesDifferenceJobSource)
        return job_source.getPendingJobsForDifferences(
            self.context, self.cached_differences.batch)

    def hasPendingDSDUpdate(self, dsd):
        """Have there been changes that `dsd` is still being updated for?"""
        return dsd in self.pending_dsd_updates

    def hasPendingSync(self, dsd):
        """Is there a package-copying job pending to resolve `dsd`?"""
        pending_sync = self.pending_syncs.get(dsd.source_package_name.name)
        return pending_sync is not None

    def isNewerThanParent(self, dsd):
        """Is the child's version of this package newer than the parent's?

        If it is, there's no point in offering to sync it.

        Any version is considered "newer" than a missing version.
        """
        # This is trickier than it looks: versions are not totally
        # ordered.  Two non-identical versions may compare as equal.
        # Only consider cases where the child's version is conclusively
        # newer, not where the relationship is in any way unclear.
        if dsd.parent_source_version is None:
            # There is nothing to sync; the child is up to date and if
            # anything needs updating, it's the parent.
            return True
        if dsd.source_version is None:
            # The child doesn't have this package.  Treat that as the
            # parent being newer.
            return False
        comparison = apt_pkg.VersionCompare(
            dsd.parent_source_version, dsd.source_version)
        return comparison < 0

    def canRequestSync(self, dsd):
        """Does it make sense to request a sync for this difference?"""
        # There are two conditions for this: it doesn't make sense to
        # sync if the child's version of the package is newer than the
        # parent's version, or if there is already a sync pending.
        return (
            not self.isNewerThanParent(dsd) and not self.hasPendingSync(dsd))

    def describeJobs(self, dsd):
        """Describe any jobs that may be pending for `dsd`.

        Shows "synchronizing..." if the entry is being synchronized, and
        "updating..." if the DSD is being updated with package changes.

        :param dsd: A `DistroSeriesDifference` on the page.
        :return: An HTML text describing work that is pending or in
            progress for `dsd`; or None.
        """
        has_pending_dsd_update = self.hasPendingDSDUpdate(dsd)
        has_pending_sync = self.hasPendingSync(dsd)
        if not has_pending_dsd_update and not has_pending_sync:
            return None

        description = []
        if has_pending_dsd_update:
            description.append("updating")
        if has_pending_sync:
            description.append("synchronizing")
        return " and ".join(description) + "&hellip;"

    @property
    def specified_name_filter(self):
        """If specified, return the name filter from the GET form data."""
        requested_name_filter = self.request.query_string_params.get(
            'field.name_filter')

        if requested_name_filter and requested_name_filter[0]:
            return requested_name_filter[0]
        else:
            return None

    @property
    def specified_package_type(self):
        """If specified, return the package type filter from the GET form
        data.
        """
        package_type = self.request.query_string_params.get(
            'field.package_type')
        if package_type and package_type[0]:
            return package_type[0]
        else:
            return DEFAULT_PACKAGE_TYPE

    @cachedproperty
    def cached_differences(self):
        """Return a batch navigator of filtered results."""
        package_type_dsd_status = {
            NON_IGNORED: (
                DistroSeriesDifferenceStatus.NEEDS_ATTENTION,),
            IGNORED: DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            HIGHER_VERSION_THAN_PARENT: (
                DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT),
            RESOLVED: DistroSeriesDifferenceStatus.RESOLVED,
        }

        status = package_type_dsd_status[self.specified_package_type]
        child_version_higher = (
            self.specified_package_type == HIGHER_VERSION_THAN_PARENT)

        differences = getUtility(
            IDistroSeriesDifferenceSource).getForDistroSeries(
                self.context, difference_type=self.differences_type,
                source_package_name_filter=self.specified_name_filter,
                status=status, child_version_higher=child_version_higher)
        return BatchNavigator(differences, self.request)

    @cachedproperty
    def has_differences(self):
        """Whether or not differences between this derived series and
        its parent exist.
        """
        # Performance optimisation: save a query if we have differences
        # to show in the batch.
        if self.cached_differences.batch.total() > 0:
            return True
        else:
            # Here we check the whole dataset since the empty batch
            # might be filtered.
            differences = getUtility(
                IDistroSeriesDifferenceSource).getForDistroSeries(
                    self.context,
                    difference_type=self.differences_type,
                    status=(
                        DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
                        DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT))
            return not differences.is_empty()


class DistroSeriesLocalDifferencesView(DistroSeriesDifferenceBaseView,
                                       LaunchpadFormView):
    """Present differences of type DIFFERENT_VERSIONS between
    a derived series and its parent.
    """
    page_title = 'Local package differences'
    differences_type = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
    show_parent_packagesets = True
    search_higher_parent_option = True

    def initialize(self):
        # Update the label for sync action.
        if self.has_unique_parent:
            parent_name = "'%s'" % self.unique_parent.displayname
        else:
            parent_name = 'Parent'
        self.initialize_sync_label(
            "Sync Selected %s Versions into %s" % (
                parent_name,
                self.context.displayname,
                ))
        super(DistroSeriesLocalDifferencesView, self).initialize()

    @property
    def explanation(self):
        return structured(
            "Source packages shown here are present in both %s "
            "and %s, but are different somehow. "
            "Changes could be in either or both series so check the "
            "versions (and the diff if necessary) before syncing the parent "
            'version (<a href="/+help/soyuz/derived-series-syncing.html" '
            'target="help">Read more about syncing from a parent series'
            '</a>).',
            self.context.displayname,
            self.getParentName())

    @property
    def label(self):
        return (
            "Source package differences between '%s' and"
            " %s" % (
                self.context.displayname,
                self.getParentName(multiple_parent_default='parent series'),
                ))

    @action(_("Sync Sources"), name="sync", validator='validate_sync',
            condition='canPerformSync')
    def sync_sources(self, action, data):
        self._sync_sources(action, data)

    def getUpgrades(self):
        """Find straightforward package upgrades.

        These are updates for packages that this distroseries shares
        with a parent series, for which there have been updates in the
        parent, and which do not have any changes in this series that
        might complicate a sync.

        :return: A result set of `DistroSeriesDifference`s.
        """
        return getUtility(IDistroSeriesDifferenceSource).getSimpleUpgrades(
            self.context)

    @action(_("Upgrade Packages"), name="upgrade", condition='canUpgrade')
    def upgrade(self, action, data):
        """Request synchronization of straightforward package upgrades."""
        self.requestUpgrades()

    def requestUpgrades(self):
        """Request sync of packages that can be easily upgraded."""
        target_distroseries = self.context
        copies = [
            (
                dsd.source_package_name.name,
                dsd.parent_source_version,
                dsd.parent_series.main_archive,
                target_distroseries.main_archive,
                PackagePublishingPocket.RELEASE,
            )
            for dsd in self.getUpgrades()]
        getUtility(IPlainPackageCopyJobSource).createMultiple(
            target_distroseries, copies,
            copy_policy=PackageCopyPolicy.MASS_SYNC)

        self.request.response.addInfoNotification(
            (u"Upgrades of {context.displayname} packages have been "
             u"requested. Please give Launchpad some time to complete "
             u"these.").format(context=self.context))

    def canUpgrade(self, action=None):
        """Should the form offer a packages upgrade?"""
        if getFeatureFlag("soyuz.derived_series_sync.enabled") is None:
            return False
        elif self.context.status not in UPGRADABLE_SERIES_STATUSES:
            # A feature freeze precludes blanket updates.
            return False
        elif self.getUpgrades().is_empty():
            # There are no simple updates to perform.
            return False
        else:
            queue = PackageUploadQueue(self.context, None)
            return check_permission("launchpad.Edit", queue)


class DistroSeriesMissingPackagesView(DistroSeriesDifferenceBaseView,
                                      LaunchpadFormView):
    """Present differences of type MISSING_FROM_DERIVED_SERIES between
    a derived series and its parent.
    """
    page_title = 'Missing packages'
    differences_type = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
    show_derived_version = False
    show_package_diffs = False
    show_parent_packagesets = True

    def initialize(self):
        # Update the label for sync action.
        self.initialize_sync_label(
            "Include Selected packages into %s" % (
                self.context.displayname,
                ))
        super(DistroSeriesMissingPackagesView, self).initialize()

    @property
    def explanation(self):
        return structured(
            "Packages that are listed here are those that have been added to "
            "the specific packages in %s that were used to create %s. "
            "They are listed here so you can consider including them in %s.",
            self.getParentName(),
            self.context.displayname,
            self.context.displayname)

    @property
    def label(self):
        return (
            "Packages in %s but not in '%s'" % (
                self.getParentName(),
                self.context.displayname,
                ))

    @action(_("Sync Sources"), name="sync", validator='validate_sync',
            condition='canPerformSync')
    def sync_sources(self, action, data):
        self._sync_sources(action, data)


class DistroSeriesUniquePackagesView(DistroSeriesDifferenceBaseView,
                                     LaunchpadFormView):
    """Present differences of type UNIQUE_TO_DERIVED_SERIES between
    a derived series and its parent.
    """
    page_title = 'Unique packages'
    differences_type = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
    show_parent_version = False
    show_package_diffs = False
    show_packagesets = True

    def initialize(self):
        super(DistroSeriesUniquePackagesView, self).initialize()

    @property
    def explanation(self):
        return structured(
            "Packages that are listed here are those that have been added to "
            "%s but are not yet part of %s.",
            self.context.displayname,
            self.getParentName())

    @property
    def label(self):
        return (
            "Packages in '%s' but not in %s" % (
                self.context.displayname,
                self.getParentName(),
                ))

    def canPerformSync(self, *args):
        return False
