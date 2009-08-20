# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser views for distributions."""

__metaclass__ = type

__all__ = [
    'DistributionAddView',
    'DistributionAllPackagesView',
    'DistributionArchiveMirrorsRSSView',
    'DistributionArchiveMirrorsView',
    'DistributionArchivesView',
    'DistributionBreadcrumbBuilder',
    'DistributionChangeMembersView',
    'DistributionChangeMirrorAdminView',
    'DistributionCountryArchiveMirrorsView',
    'DistributionDisabledMirrorsView',
    'DistributionEditView',
    'DistributionFacets',
    'DistributionLanguagePackAdminView',
    'DistributionNavigation',
    'DistributionPPASearchView',
    'DistributionPackageSearchView',
    'DistributionPendingReviewMirrorsView',
    'DistributionSeriesMirrorsRSSView',
    'DistributionSeriesMirrorsView',
    'DistributionSetActionNavigationMenu',
    'DistributionSetBreadcrumbBuilder',
    'DistributionSetContextMenu',
    'DistributionSetFacets',
    'DistributionSetNavigation',
    'DistributionSetView',
    'DistributionSpecificationsMenu',
    'DistributionUnofficialMirrorsView',
    'DistributionView',
    'UsesLaunchpadMixin',
    ]

import datetime

from zope.lifecycleevent import ObjectCreatedEvent
from zope.component import getUtility
from zope.event import notify
from zope.interface import implements
from zope.security.interfaces import Unauthorized

from canonical.cachedproperty import cachedproperty
from lp.registry.browser.announcement import HasAnnouncementsView
from lp.registry.browser.menu import (
    IRegistryCollectionNavigationMenu, RegistryCollectionActionMenuBase,
    TopLevelMenuMixin)
from lp.soyuz.browser.archive import traverse_distro_archive
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.soyuz.browser.build import BuildRecordsView
from lp.answers.browser.faqtarget import FAQTargetNavigationMixin
from canonical.launchpad.browser.feeds import FeedsMixin
from canonical.launchpad.browser.packagesearch import PackageSearchViewBase
from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet)
from canonical.launchpad.components.request_country import (
    ipaddress_from_request, request_country)
from lp.answers.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetTraversalMixin)
from lp.soyuz.interfaces.archive import (
    IArchiveSet, ArchivePurpose)
from lp.registry.interfaces.distribution import (
    IDistribution, IDistributionMirrorMenuMarker, IDistributionSet)
from lp.registry.interfaces.distributionmirror import (
    IDistributionMirrorSet, MirrorContent, MirrorSpeed)
from lp.registry.interfaces.product import IProduct
from lp.soyuz.interfaces.publishedpackage import (
    IPublishedPackageSet)
from canonical.launchpad.webapp import (
    action, ApplicationMenu, canonical_url, ContextMenu, custom_widget,
    enabled_with_permission, GetitemNavigation,
    LaunchpadFormView, LaunchpadView, Link, Navigation, redirection,
    StandardLaunchpadFacets, stepthrough, stepto)
from canonical.launchpad.webapp.interfaces import (
    ILaunchBag, NotFoundError)
from canonical.launchpad.helpers import english_list
from canonical.launchpad.webapp import NavigationMenu
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import BreadcrumbBuilder
from canonical.widgets.image import ImageChangeWidget

from lp.registry.browser import RegistryEditFormView


class UsesLaunchpadMixin:
    """This mixin is used for the overview page of products and distros."""

    @property
    def uses_launchpad_for(self):
        """Return a string of LP apps (comma-separated) this distro uses."""
        uses = []
        href_template = """<a href="%s"><strong>%s</strong></a>"""
        if self.context.official_answers:
            url = canonical_url(self.context, rootsite='answers')
            uses.append(href_template % (url, 'Answers'))
        if self.context.official_blueprints:
            url = canonical_url(self.context, rootsite='blueprints')
            uses.append(href_template % (url, 'Blueprints'))
        if self.context.official_malone:
            url = canonical_url(self.context, rootsite='bugs')
            uses.append(href_template % (url, 'Bug Tracking'))
        if IProduct.providedBy(self.context):
            if self.context.official_codehosting:
                url = canonical_url(self.context, rootsite='code')
                uses.append(href_template % (url, 'Code'))
        if self.context.official_rosetta:
            url = canonical_url(self.context, rootsite='translations')
            uses.append(href_template % (url, 'Translations'))

        if len(uses) == 0:
            text = None
        else:
            text = english_list(uses)

        return text


class DistributionNavigation(
    GetitemNavigation, BugTargetTraversalMixin, QuestionTargetTraversalMixin,
    FAQTargetNavigationMixin):

    usedfor = IDistribution

    @redirection('+source', status=301)
    def redirect_source(self):
        return canonical_url(self.context)

    @stepto('+packages')
    def packages(self):
        return getUtility(IPublishedPackageSet)

    @stepthrough('+mirror')
    def traverse_mirrors(self, name):
        return self.context.getMirrorByName(name)

    @stepthrough('+source')
    def traverse_sources(self, name):
        return self.context.getSourcePackage(name)

    @stepthrough('+milestone')
    def traverse_milestone(self, name):
        return self.context.getMilestone(name)

    @stepthrough('+announcement')
    def traverse_announcement(self, name):
        return self.context.getAnnouncement(name)

    @stepthrough('+spec')
    def traverse_spec(self, name):
        return self.context.getSpecification(name)

    @stepthrough('+archive')
    def traverse_archive(self, name):
        return traverse_distro_archive(self.context, name)


class DistributionSetNavigation(Navigation):

    usedfor = IDistributionSet

    def traverse(self, name):
        # Raise a 404 on an invalid distribution name
        distribution = self.context.getByName(name)
        if distribution is None:
            raise NotFoundError(name)
        return self.redirectSubTree(canonical_url(distribution))


class DistributionBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `IDistribution`."""
    @property
    def text(self):
        return self.context.displayname


class DistributionFacets(QuestionTargetFacetMixin, StandardLaunchpadFacets):

    usedfor = IDistribution

    enable_only = ['overview', 'branches', 'bugs', 'answers',
                   'specifications', 'translations']

    def specifications(self):
        text = 'Blueprints'
        summary = 'Feature specifications for %s' % self.context.displayname
        return Link('', text, summary)


class DistributionSetBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `IDistributionSet`."""
    text = 'Distributions'


class DistributionSetFacets(StandardLaunchpadFacets):

    usedfor = IDistributionSet

    enable_only = ['overview', ]


class DistributionSetContextMenu(ContextMenu):

    usedfor = IDistributionSet
    links = ['products', 'distributions', 'people', 'meetings']

    def distributions(self):
        return Link('/distros/', 'View distributions')

    def products(self):
        return Link('/projects/', 'View projects')

    def people(self):
        return Link('/people/', 'View people')

    def meetings(self):
        return Link('/sprints/', 'View meetings')


class DistributionMirrorsNavigationMenu(NavigationMenu):

    usedfor = IDistributionMirrorMenuMarker
    facet = 'overview'
    links = ('cdimage_mirrors',
             'archive_mirrors',
             'newmirror',
             'disabled_mirrors',
             'pending_review_mirrors',
             'unofficial_mirrors',
             )

    @property
    def distribution(self):
        """Helper method to return the distribution object.

        self.context is the view, so return *its* context.
        """
        return self.context.context

    def cdimage_mirrors(self):
        text = 'CD Mirrors'
        enabled = self.distribution.full_functionality
        return Link('+cdmirrors', text, enabled=enabled, icon='info')

    def archive_mirrors(self):
        text = 'Archive Mirrors'
        enabled = self.distribution.full_functionality
        return Link('+archivemirrors', text, enabled=enabled, icon='info')

    def newmirror(self):
        text = 'Register Mirror'
        enabled = self.distribution.full_functionality
        return Link('+newmirror', text, enabled=enabled, icon='add')

    def _userCanSeeNonPublicMirrorListings(self):
        """Does the user have rights to see non-public mirrors listings?"""
        user = getUtility(ILaunchBag).user
        return (self.distribution.full_functionality
                and user is not None
                and user.inTeam(self.distribution.mirror_admin))

    def disabled_mirrors(self):
        text = 'Disabled Mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link('+disabledmirrors', text, enabled=enabled, icon='info')

    def pending_review_mirrors(self):
        text = 'Pending-Review Mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link(
            '+pendingreviewmirrors', text, enabled=enabled, icon='info')

    def unofficial_mirrors(self):
        text = 'Unofficial Mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link('+unofficialmirrors', text, enabled=enabled, icon='info')


class DistributionNavigationMenu(NavigationMenu):

    usedfor = IDistribution
    facet = 'overview'
    links = ('details',
             'announcements',
             'mentoring',
             'mirrors',
             'builds',
             'ppas',
             )

    def details(self):
        target = ''
        text = 'Details'
        return Link(target, text)

    def announcements(self):
        # XXX: BradCrittenden 2009-08-19 bug=410491: When the distribution
        # index page is updated to UI 3.0 the text needs to read "Read all
        # announcements".
        target = '+announcements'
        text = 'Announcements'
        return Link(target, text)

    def mentoring(self):
        target = '+mentoring'
        text = "Mentoring"
        return Link(target, text)

    def mirrors(self):
        target = '+cdmirrors'
        text = 'Mirrors'
        menu = IDistributionMirrorMenuMarker
        return Link(target, text, menu=menu)

    def builds(self):
        target = '+builds'
        text = "Builds"
        return Link(target, text)

    def ppas(self):
        target = '+ppas'
        text = 'PPAs'
        return Link(target, text)


class DistributionOverviewMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'overview'
    links = ['edit', 'branding', 'driver', 'search', 'allpkgs', 'members',
             'mirror_admin', 'reassign', 'addseries', 'top_contributors',
             'mentorship', 'builds', 'cdimage_mirrors', 'archive_mirrors',
             'pending_review_mirrors', 'disabled_mirrors',
             'unofficial_mirrors', 'newmirror', 'announce', 'announcements',
             'ppas',]

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change distribution details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def branding(self):
        text = 'Change branding'
        return Link('+branding', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        text = 'Appoint driver'
        summary = 'Someone with permission to set goals for all series'
        return Link('+driver', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        text = 'Change registrant'
        return Link('+reassign', text, icon='edit')

    def newmirror(self):
        text = 'Register a new mirror'
        enabled = self.context.full_functionality
        return Link('+newmirror', text, enabled=enabled, icon='add')

    def top_contributors(self):
        text = u'\u00BB More contributors'
        return Link('+topcontributors', text)

    def mentorship(self):
        text = 'Mentoring available'
        return Link('+mentoring', text, icon='info')

    def cdimage_mirrors(self):
        text = 'Show CD mirrors'
        enabled = self.context.full_functionality
        return Link('+cdmirrors', text, enabled=enabled, icon='info')

    def archive_mirrors(self):
        text = 'Show archive mirrors'
        enabled = self.context.full_functionality
        return Link('+archivemirrors', text, enabled=enabled, icon='info')

    def _userCanSeeNonPublicMirrorListings(self):
        """Does the user have rights to see non-public mirrors listings?"""
        user = getUtility(ILaunchBag).user
        return (self.context.full_functionality
                and user is not None
                and user.inTeam(self.context.mirror_admin))

    def disabled_mirrors(self):
        text = 'Show disabled mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link('+disabledmirrors', text, enabled=enabled, icon='info')

    def pending_review_mirrors(self):
        text = 'Show pending-review mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link(
            '+pendingreviewmirrors', text, enabled=enabled, icon='info')

    def unofficial_mirrors(self):
        text = 'Show unofficial mirrors'
        enabled = self._userCanSeeNonPublicMirrorListings()
        return Link('+unofficialmirrors', text, enabled=enabled, icon='info')

    def allpkgs(self):
        text = 'List all packages'
        return Link('+allpackages', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def members(self):
        text = 'Change members team'
        return Link('+selectmemberteam', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def mirror_admin(self):
        text = 'Change mirror admins'
        enabled = self.context.full_functionality
        return Link('+selectmirroradmins', text, enabled=enabled, icon='edit')

    def search(self):
        text = 'Search packages'
        return Link('+search', text, icon='search')

    @enabled_with_permission('launchpad.Admin')
    def addseries(self):
        text = 'Add series'
        return Link('+addseries', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def announce(self):
        text = 'Make announcement'
        summary = 'Publish an item of news for this project'
        return Link('+announce', text, summary, icon='add')

    def announcements(self):
        text = 'Read all announcements'
        enabled = bool(self.context.getAnnouncements())
        return Link('+announcements', text, icon='info', enabled=enabled)

    def builds(self):
        text = 'Builds'
        return Link('+builds', text, icon='info')

    def ppas(self):
        text = 'Personal Package Archives'
        return Link('+ppas', text, icon='info')


class DistributionBugsMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'bugs'
    links = (
        'bugsupervisor',
        'securitycontact',
        'cve',
        'filebug',
        'subscribe',
        )

    def cve(self):
        text = 'CVE reports'
        return Link('+cve', text, icon='cve')

    @enabled_with_permission('launchpad.Edit')
    def bugsupervisor(self):
        text = 'Change bug supervisor'
        return Link('+bugsupervisor', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        text = 'Change security contact'
        return Link('+securitycontact', text, icon='edit')

    def filebug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='bug')

    def subscribe(self):
        text = 'Subscribe to bug mail'
        return Link('+subscribe', text)


class DistributionBountiesMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'bounties'
    links = ['new', 'link']

    def new(self):
        text = 'Register new bounty'
        return Link('+addbounty', text, icon='add')

    def link(self):
        text = 'Link existing bounty'
        return Link('+linkbounty', text, icon='edit')


class DistributionSpecificationsMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'specifications'
    links = ['listall', 'doc', 'assignments', 'new']

    def listall(self):
        text = 'List all blueprints'
        return Link('+specs?show=all', text, icon='info')

    def assignments(self):
        text = 'Assignments'
        return Link('+assignments', text, icon='info')

    def doc(self):
        text = 'Documentation'
        summary = 'List all complete informational specifications'
        return Link('+documentation', text, summary,
            icon='info')

    def new(self):
        text = 'Register a blueprint'
        summary = 'Register a new blueprint for %s' % self.context.title
        return Link('+addspec', text, summary, icon='add')


class DistributionPackageSearchView(PackageSearchViewBase):
    """Customised PackageSearchView for Distribution"""

    def initialize(self):
        """Save the search type if provided."""
        super(DistributionPackageSearchView, self).initialize()

        # If the distribution contains binary packages, then we'll
        # default to searches on binary names, but allow the user to
        # select.
        if self.context.has_published_binaries:
            self.search_type = self.request.get("search_type", 'binary')
        else:
            self.search_type = 'source'

    def contextSpecificSearch(self):
        """See `AbstractPackageSearchView`."""

        if self.search_by_binary_name:
            non_exact_matches = self.context.searchBinaryPackages(self.text)

            # XXX Michael Nelson 20090605 bug=217644
            # We are only using a decorated resultset here to conveniently
            # get around the storm bug whereby count returns the count
            # of non-distinct results, even though this result set
            # is configured for distinct results.
            def dummy_func(result):
                return result
            non_exact_matches = DecoratedResultSet(
                non_exact_matches, dummy_func)

        else:
            non_exact_matches = self.context.searchSourcePackageCaches(
                self.text)

            # The searchBinaryPackageCaches() method returns tuples, so we
            # use the DecoratedResultSet here to just get the
            # DistributionSourcePackag objects for the template.
            def tuple_to_package_cache(cache_name_tuple):
                return cache_name_tuple[0]

            non_exact_matches = DecoratedResultSet(
                non_exact_matches, tuple_to_package_cache)

        return non_exact_matches.config(distinct=True)

    @property
    def search_by_binary_name(self):
        """Return whether the search is on binary names.

        By default, we search by binary names, as this produces much
        better results. But the user may decide to search by sources, or
        in the case of other distributions, it will be the only option.
        """
        return self.search_type == "binary"

    @property
    def source_search_url(self):
        """Return the equivalent search on source packages.

        By default, we search by binary names, but also provide a link
        to the equivalent source package search in some circumstances.
        """
        return "%s/+search?search_type=source&%s" % (
            canonical_url(self.context),
            self.request.get('QUERY_STRING'),
            )

    @cachedproperty
    def exact_matches(self):
        return self.context.searchBinaryPackages(
            self.text, exact_match=True).order_by('name')

    @property
    def has_exact_matches(self):
        return self.exact_matches.count() > 0

    @property
    def has_matches(self):
        return self.matches > 0

    @cachedproperty
    def matching_binary_names(self):
        """Define the matching binary names for each result in the batch."""
        names = {}

        for package_cache in self.batchnav.currentBatch():
            names[package_cache.name] = self._listFirstFiveMatchingNames(
                self.text, package_cache.binpkgnames)

        return names

    def _listFirstFiveMatchingNames(self, match_text, space_separated_list):
        """Returns a comma-separated list of the first five matching items"""
        name_list = space_separated_list.split(' ')

        matching_names = [
            name for name in name_list if match_text in name]

        if len(matching_names) > 5:
            more_than_five = True
            matching_names = matching_names[:5]
            matching_names.append('...')

        return ", ".join(matching_names)

    @cachedproperty
    def distroseries_names(self):
        """Define the distroseries for each package name in exact matches."""
        names = {}
        for package_cache in self.exact_matches:
            package = package_cache.distributionsourcepackage

            # In the absense of Python3.0's set comprehension, we
            # create a list, convert the list to a set and back again:
            distroseries_list = [
                pubrec.distroseries.name
                    for pubrec in package.current_publishing_records
                        if pubrec.distroseries.active]
            distroseries_list = list(set(distroseries_list))

            # Yay for alphabetical series names.
            distroseries_list.sort()
            names[package.name] = ", ".join(distroseries_list)

        return names

    @property
    def display_exact_matches(self):
        """Return whether exact match results should be displayed."""
        if not self.search_by_binary_name:
            return False

        if self.batchnav.start > 0:
            return False

        return self.has_exact_matches

class DistributionView(HasAnnouncementsView, BuildRecordsView, FeedsMixin,
                       UsesLaunchpadMixin):
    """Default Distribution view class."""

    def linkedMilestonesForSeries(self, series):
        """Return a string of linkified milestones in the series."""
        # Listify to remove repeated queries.
        milestones = list(series.milestones)
        if len(milestones) == 0:
            return ""

        linked_milestones = []
        for milestone in milestones:
            linked_milestones.append(
                "<a href=%s>%s</a>" % (
                    canonical_url(milestone), milestone.name))

        return english_list(linked_milestones)


class DistributionArchivesView(LaunchpadView):

    @property
    def batchnav(self):
        """Return the batch navigator for the archives."""
        return BatchNavigator(self.archive_list, self.request)

    @cachedproperty
    def archive_list(self):
        """Returns the list of archives for the given distribution.

        The context may be an IDistroSeries or a users archives.
        """
        results = getUtility(IArchiveSet).getArchivesForDistribution(
            self.context, purposes=[ArchivePurpose.COPY], user=self.user)
        return results.order_by('date_created DESC')

class DistributionPPASearchView(LaunchpadView):
    """Search PPAs belonging to the Distribution in question."""

    def initialize(self):
        self.name_filter = self.request.get('name_filter')
        self.show_inactive = self.request.get('show_inactive')

    @property
    def search_results(self):
        """Process search form request."""
        if self.name_filter is None:
            return None

        # Preserve self.show_inactive state because it's used in the
        # template and build a boolean field to be passed for
        # searchPPAs.
        show_inactive = (self.show_inactive == 'on')

        ppas = self.context.searchPPAs(
            text=self.name_filter, show_inactive=show_inactive,
            user=self.user)

        self.batchnav = BatchNavigator(ppas, self.request)
        return self.batchnav.currentBatch()

    @property
    def number_of_registered_ppas(self):
        """The number of archives with PPA purpose.

        It doesn't include private PPAs.
        """
        return self.context.searchPPAs(show_inactive=True).count()

    @property
    def number_of_active_ppas(self):
        """The number of PPAs with at least one source publication.

        It doesn't include private PPAs.
        """
        return self.context.searchPPAs(show_inactive=False).count()

    @property
    def number_of_ppa_sources(self):
        """The number of sources published across all PPAs."""
        return getUtility(IArchiveSet).getNumberOfPPASourcesForDistribution(
            self.context)

    @property
    def number_of_ppa_binaries(self):
        """The number of binaries published across all PPAs."""
        return getUtility(IArchiveSet).getNumberOfPPABinariesForDistribution(
            self.context)

    @property
    def latest_ppa_source_publications(self):
        """Return the last 5 sources publication in the context PPAs."""
        archive_set = getUtility(IArchiveSet)
        return archive_set.getLatestPPASourcePublicationsForDistribution(
            distribution=self.context)

    @property
    def most_active_ppas(self):
        """Return the last 5 most active PPAs."""
        archive_set = getUtility(IArchiveSet)
        return archive_set.getMostActivePPAsForDistribution(
            distribution=self.context)


class DistributionAllPackagesView(LaunchpadView):
    def initialize(self):
        results = self.context.getSourcePackageCaches()
        self.batchnav = BatchNavigator(results, self.request)


class DistributionSetActionNavigationMenu(RegistryCollectionActionMenuBase):
    """Action menu for `DistributionSetView`."""

    usedfor = IDistributionSet
    links = ['register_team', 'register_project', 'create_account']


class DistributionSetView(LaunchpadView):
    """View for /distros top level collection."""

    implements(IRegistryCollectionNavigationMenu)

    page_title = 'Distributions registered in Launchpad'

    @cachedproperty
    def count(self):
        return self.context.count()


class DistributionAddView(LaunchpadFormView):

    schema = IDistribution
    label = "Register a new distribution"
    field_names = ["name", "displayname", "title", "summary", "description",
                   "domainname", "members",
                   "official_malone", "official_blueprints",
                   "official_rosetta", "official_answers"]

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @action("Save", name='save')
    def save_action(self, action, data):
        distribution = getUtility(IDistributionSet).new(
            name=data['name'],
            displayname=data['displayname'],
            title=data['title'],
            summary=data['summary'],
            description=data['description'],
            domainname=data['domainname'],
            members=data['members'],
            owner=self.user,
            )
        notify(ObjectCreatedEvent(distribution))
        self.next_url = canonical_url(distribution)


class DistributionEditView(RegistryEditFormView):

    schema = IDistribution
    field_names = ['displayname', 'title', 'summary', 'description',
                   'bug_reporting_guidelines', 'icon', 'logo', 'mugshot',
                   'official_malone', 'enable_bug_expiration',
                   'official_blueprints', 'official_rosetta',
                   'official_answers', 'translation_focus', ]

    custom_widget('icon', ImageChangeWidget, ImageChangeWidget.EDIT_STYLE)
    custom_widget('logo', ImageChangeWidget, ImageChangeWidget.EDIT_STYLE)
    custom_widget('mugshot', ImageChangeWidget, ImageChangeWidget.EDIT_STYLE)

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Change %s details' % self.context.displayname

    def validate(self, data):
        """Constrain bug expiration to Launchpad Bugs tracker."""
        # enable_bug_expiration is disabled by JavaScript when official_malone
        # is set False. The contraint is enforced here in case the JavaScript
        # fails to load or activate.
        official_malone = data.get('official_malone', False)
        if not official_malone:
            data['enable_bug_expiration'] = False


class DistributionChangeMirrorAdminView(RegistryEditFormView):
    """A view to change the mirror administrator."""
    schema = IDistribution
    field_names = ['mirror_admin']

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return "Change the %s mirror administrator" % self.context.displayname


class DistributionChangeMembersView(RegistryEditFormView):
    """A view to change the members team."""
    schema = IDistribution
    field_names = ['members']

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return "Change the %s members team" % self.context.displayname


class DistributionCountryArchiveMirrorsView(LaunchpadView):
    """A text/plain page that lists the mirrors in the country of the request.

    If there are no mirrors located in the country of the request, we fallback
    to the main Ubuntu repositories.
    """
    implements(IDistributionMirrorMenuMarker)

    def render(self):
        request = self.request
        if not self.context.full_functionality:
            request.response.setStatus(404)
            return u''
        ip_address = ipaddress_from_request(request)
        country = request_country(request)
        mirrors = getUtility(IDistributionMirrorSet).getBestMirrorsForCountry(
            country, MirrorContent.ARCHIVE)
        body = "\n".join(mirror.base_url for mirror in mirrors)
        request.response.setHeader('content-type', 'text/plain;charset=utf-8')
        if country is None:
            country_name = 'Unknown'
        else:
            country_name = country.name
        request.response.setHeader('X-Generated-For-Country', country_name)
        request.response.setHeader('X-Generated-For-IP', ip_address)
        # XXX: Guilherme Salgado 2008-01-09 bug=173729: These are here only
        # for debugging.
        request.response.setHeader(
            'X-REQUEST-HTTP_X_FORWARDED_FOR',
            request.get('HTTP_X_FORWARDED_FOR'))
        request.response.setHeader(
            'X-REQUEST-REMOTE_ADDR', request.get('REMOTE_ADDR'))
        return body.encode('utf-8')


class DistributionMirrorsView(LaunchpadView):

    implements(IDistributionMirrorMenuMarker)
    show_freshness = True

    @cachedproperty
    def mirror_count(self):
        return self.mirrors.count()

    def _sum_throughput(self, mirrors):
        """Given a list of mirrors, calculate the total bandwidth
        available.
        """
        throughput = 0
        # this would be a wonderful place to have abused DBItem.sort_key ;-)
        for mirror in mirrors:
            if mirror.speed == MirrorSpeed.S128K:
                throughput += 128
            elif mirror.speed == MirrorSpeed.S256K:
                throughput += 256
            elif mirror.speed == MirrorSpeed.S512K:
                throughput += 512
            elif mirror.speed == MirrorSpeed.S1M:
                throughput += 1000
            elif mirror.speed == MirrorSpeed.S2M:
                throughput += 2000
            elif mirror.speed == MirrorSpeed.S10M:
                throughput += 10000
            elif mirror.speed == MirrorSpeed.S45M:
                throughput += 45000
            elif mirror.speed == MirrorSpeed.S100M:
                throughput += 100000
            elif mirror.speed == MirrorSpeed.S1G:
                throughput += 1000000
            elif mirror.speed == MirrorSpeed.S2G:
                throughput += 2000000
            elif mirror.speed == MirrorSpeed.S4G:
                throughput += 4000000
            elif mirror.speed == MirrorSpeed.S10G:
                throughput += 10000000
            elif mirror.speed == MirrorSpeed.S20G:
                throughput += 20000000
            else:
                # need to be made aware of new values in
                # interfaces/distributionmirror.py MirrorSpeed
                return 'Indeterminate'
        if throughput < 1000:
            return str(throughput) + ' Kbps'
        elif throughput < 1000000:
            return str(throughput/1000) + ' Mbps'
        else:
            return str(throughput/1000000) + ' Gbps'

    @cachedproperty
    def total_throughput(self):
        return self._sum_throughput(self.mirrors)

    def getMirrorsGroupedByCountry(self):
        """Given a list of mirrors, create and return list of dictionaries
        containing the country names and the list of mirrors on that country.

        This list is ordered by country name.
        """
        mirrors_by_country = {}
        for mirror in self.mirrors:
            mirrors = mirrors_by_country.setdefault(mirror.country.name, [])
            mirrors.append(mirror)
        return [dict(country=country,
                     mirrors=mirrors,
                     number=len(mirrors),
                     throughput=self._sum_throughput(mirrors))
                for country, mirrors in sorted(mirrors_by_country.items())]


class DistributionArchiveMirrorsView(DistributionMirrorsView):

    heading = 'Official Archive Mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.archive_mirrors


class DistributionSeriesMirrorsView(DistributionMirrorsView):

    heading = 'Official CD Mirrors'
    show_freshness = False

    @cachedproperty
    def mirrors(self):
        return self.context.cdimage_mirrors


class DistributionMirrorsRSSBaseView(LaunchpadView):
    """A base class for RSS feeds of distribution mirrors."""

    def initialize(self):
        self.now = datetime.datetime.utcnow()

    def render(self):
        self.request.response.setHeader(
            'content-type', 'text/xml;charset=utf-8')
        body = LaunchpadView.render(self)
        return body.encode('utf-8')


class DistributionArchiveMirrorsRSSView(DistributionMirrorsRSSBaseView):
    """The RSS feed for archive mirrors."""

    heading = 'Archive Mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.archive_mirrors


class DistributionSeriesMirrorsRSSView(DistributionMirrorsRSSBaseView):
    """The RSS feed for series mirrors."""

    heading = 'CD Mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.cdimage_mirrors


class DistributionMirrorsAdminView(DistributionMirrorsView):

    def initialize(self):
        """Raise an Unauthorized exception if the user is not a member of this
        distribution's mirror_admin team.
        """
        # XXX: Guilherme Salgado 2006-06-16:
        # We don't want these pages to be public but we can't protect
        # them with launchpad.Edit because that would mean only people with
        # that permission on a Distribution would be able to see them. That's
        # why we have to do the permission check here.
        if not (self.user and self.user.inTeam(self.context.mirror_admin)):
            raise Unauthorized('Forbidden')


class DistributionUnofficialMirrorsView(DistributionMirrorsAdminView):

    heading = 'Unofficial Mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.unofficial_mirrors


class DistributionPendingReviewMirrorsView(DistributionMirrorsAdminView):

    heading = 'Pending-review mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.pending_review_mirrors


class DistributionDisabledMirrorsView(DistributionMirrorsAdminView):

    heading = 'Disabled Mirrors'

    @cachedproperty
    def mirrors(self):
        return self.context.disabled_mirrors
