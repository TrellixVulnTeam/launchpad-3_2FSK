# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Browser views for products."""

__metaclass__ = type

__all__ = [
    'ProductNavigation',
    'ProductDynMenu',
    'ProductShortLink',
    'ProductSOP',
    'ProductFacets',
    'ProductOverviewMenu',
    'ProductBugsMenu',
    'ProductSpecificationsMenu',
    'ProductBountiesMenu',
    'ProductBranchesMenu',
    'ProductTranslationsMenu',
    'ProductView',
    'ProductDownloadFilesView',
    'ProductAddView',
    'ProductBrandingView',
    'ProductEditView',
    'ProductChangeTranslatorsView',
    'ProductReviewView',
    'ProductAddSeriesView',
    'ProductBugContactEditView',
    'ProductReassignmentView',
    'ProductLaunchpadUsageEditView',
    'ProductRdfView',
    'ProductSetFacets',
    'ProductSetSOP',
    'ProductSetNavigation',
    'ProductSetContextMenu',
    'ProductSetView',
    'ProductBranchesView',
    'PillarSearchItem',
    ]

from operator import attrgetter
from warnings import warn

import zope.security.interfaces
from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.interface import alsoProvides, implements

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IProduct, IProductLaunchpadUsageForm,
    ICountry, IProductSet, IProductSeries, IProject, ISourcePackage,
    ICalendarOwner, ITranslationImportQueue, NotFoundError,
    IBranchSet, RESOLVED_BUGTASK_STATUSES,
    IPillarNameSet, IDistribution, IHasIcon, UnsafeFormGetSubmissionError)
from canonical.launchpad import helpers
from canonical.launchpad.browser.branding import BrandingChangeView
from canonical.launchpad.browser.branchlisting import BranchListingView
from canonical.launchpad.browser.branchref import BranchRef
from canonical.launchpad.browser.bugtask import (
    BugTargetTraversalMixin, get_buglisting_search_filter_url)
from canonical.launchpad.browser.cal import CalendarTraversalMixin
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.person import ObjectReassignmentView
from canonical.launchpad.browser.launchpad import (
    StructuralObjectPresentation, DefaultShortLink)
from canonical.launchpad.browser.productseries import get_series_branch_error
from canonical.launchpad.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetTraversalMixin)
from canonical.launchpad.browser.seriesrelease import (
    SeriesOrReleasesMixinDynMenu)
from canonical.launchpad.browser.sprint import SprintsMixinDynMenu
from canonical.launchpad.webapp import (
    action, ApplicationMenu, canonical_url, ContextMenu, custom_widget,
    enabled_with_permission, LaunchpadView, LaunchpadEditFormView,
    LaunchpadFormView, Link, Navigation, sorted_version_numbers,
    StandardLaunchpadFacets, stepto, stepthrough, structured)
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.dynmenu import DynMenu, neverempty
from canonical.librarian.interfaces import ILibrarianClient
from canonical.widgets.product import ProductBugTrackerWidget
from canonical.widgets.textwidgets import StrippedTextWidget


class ProductNavigation(
    Navigation, BugTargetTraversalMixin, CalendarTraversalMixin,
    QuestionTargetTraversalMixin):

    usedfor = IProduct

    def breadcrumb(self):
        return self.context.displayname

    @stepto('.bzr')
    def dotbzr(self):
        if self.context.development_focus.series_branch:
            return BranchRef(self.context.development_focus.series_branch)
        else:
            return None

    @stepthrough('+spec')
    def traverse_spec(self, name):
        return self.context.getSpecification(name)

    @stepthrough('+milestone')
    def traverse_milestone(self, name):
        return self.context.getMilestone(name)

    @stepthrough('+release')
    def traverse_release(self, name):
        return self.context.getRelease(name)

    def traverse(self, name):
        return self.context.getSeries(name)


class ProductSetNavigation(Navigation):

    usedfor = IProductSet

    def breadcrumb(self):
        return 'Projects'

    def traverse(self, name):
        # Raise a 404 on an invalid product name
        product = self.context.getByName(name)
        if product is None:
            raise NotFoundError(name)
        return self.redirectSubTree(canonical_url(product))


class ProductSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        return self.context.title

    def listChildren(self, num):
        # product series, most recent first
        return list(self.context.serieses[:num])

    def listAltChildren(self, num):
        return None


class ProductFacets(QuestionTargetFacetMixin, StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IProduct."""

    usedfor = IProduct

    enable_only = ['overview', 'bugs', 'answers', 'specifications',
                   'translations', 'branches']

    links = StandardLaunchpadFacets.links

    def overview(self):
        text = 'Overview'
        summary = 'General information about %s' % self.context.displayname
        return Link('', text, summary)

    def bugs(self):
        text = 'Bugs'
        summary = 'Bugs reported about %s' % self.context.displayname
        return Link('', text, summary)

    def bounties(self):
        target = '+bounties'
        text = 'Bounties'
        summary = 'Bounties related to %s' % self.context.displayname
        return Link(target, text, summary)

    def branches(self):
        text = 'Code'
        summary = 'Branches for %s' % self.context.displayname
        return Link('', text, summary)

    def specifications(self):
        text = 'Blueprints'
        summary = 'Feature specifications for %s' % self.context.displayname
        return Link('', text, summary)

    def translations(self):
        text = 'Translations'
        summary = 'Translations of %s in Launchpad' % self.context.displayname
        return Link('', text, summary)

    def calendar(self):
        target = '+calendar'
        text = 'Calendar'
        # only link to the calendar if it has been created
        enabled = ICalendarOwner(self.context).calendar is not None
        return Link(target, text, enabled=enabled)


class ProductOverviewMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'overview'
    links = [
        'edit', 'branding', 'driver', 'reassign', 'top_contributors',
        'mentorship', 'distributions', 'packages', 'files', 'branch_add',
        'series_add', 'launchpad_usage', 'administer', 'rdf']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
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
        text = 'Change maintainer'
        return Link('+reassign', text, icon='edit')

    def top_contributors(self):
        text = 'List top contributors'
        return Link('+topcontributors', text, icon='info')

    def distributions(self):
        text = 'Packaging information'
        return Link('+distributions', text, icon='info')

    def mentorship(self):
        text = 'Mentoring available'
        return Link('+mentoring', text, icon='info')

    def packages(self):
        text = 'Show distribution packages'
        return Link('+packages', text, icon='info')

    def files(self):
        text = 'Download project files'
        return Link('+download', text, icon='info')

    def series_add(self):
        text = 'Register a series'
        return Link('+addseries', text, icon='add')

    def branch_add(self):
        text = 'Register branch'
        return Link('+addbranch', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def launchpad_usage(self):
        text = 'Define Launchpad usage'
        return Link('+launchpad', text, icon='edit')

    def rdf(self):
        text = structured(
            'Download <abbr title="Resource Description Framework">'
            'RDF</abbr> metadata')
        return Link('+rdf', text, icon='download')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+review', text, icon='edit')


class ProductBugsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'bugs'
    links = ['filebug', 'bugcontact', 'securitycontact', 'cve']

    def filebug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='add')

    def cve(self):
        return Link('+cve', 'CVE reports', icon='cve')

    @enabled_with_permission('launchpad.Edit')
    def bugcontact(self):
        text = 'Change bug contact'
        return Link('+bugcontact', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        text = 'Change security contact'
        return Link('+securitycontact', text, icon='edit')


class ProductBranchesMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'branches'
    links = ['branch_add', ]

    def branch_add(self):
        text = 'Register branch'
        summary = 'Register a new Bazaar branch for this project'
        return Link('+addbranch', text, icon='add')


class ProductSpecificationsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'specifications'
    links = ['listall', 'doc', 'roadmap', 'table', 'new']

    def listall(self):
        text = 'List all blueprints'
        summary = 'Show all specifications for %s' %  self.context.title
        return Link('+specs?show=all', text, summary, icon='info')

    def doc(self):
        text = 'List documentation'
        summary = 'List all complete informational specifications'
        return Link('+documentation', text, summary,
            icon='info')

    def roadmap(self):
        text = 'Roadmap'
        summary = 'Show the recommended sequence of specification implementation'
        return Link('+roadmap', text, summary, icon='info')

    def table(self):
        text = 'Assignments'
        summary = 'Show the full assignment of work, drafting and approving'
        return Link('+assignments', text, summary, icon='info')

    def new(self):
        text = 'Register blueprint'
        summary = 'Register a new blueprint for %s' % self.context.title
        return Link('+addspec', text, summary, icon='add')


class ProductBountiesMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'bounties'
    links = ['new', 'link']

    def new(self):
        text = 'Register bounty'
        return Link('+addbounty', text, icon='add')

    def link(self):
        text = 'Link existing bounty'
        return Link('+linkbounty', text, icon='edit')


class ProductTranslationsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'translations'
    links = ['translators', 'edit']

    def translators(self):
        text = 'Change translators'
        return Link('+changetranslators', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def edit(self):
        text = 'Edit template names'
        return Link('+potemplatenames', text, icon='edit')


def _sort_distros(a, b):
    """Put Ubuntu first, otherwise in alpha order."""
    if a['name'] == 'ubuntu':
        return -1
    return cmp(a['name'], b['name'])


class ProductSetSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        return self.context.title

    def listChildren(self, num):
        return []

    def listAltChildren(self, num):
        return None


class ProductSetFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for the IProductSet."""

    usedfor = IProductSet

    enable_only = ['overview',]


class ProductSetContextMenu(ContextMenu):

    usedfor = IProductSet

    links = ['products', 'distributions', 'people', 'meetings',
             'all', 'register', ]

    def register(self):
        text = 'Register a project'
        return Link('+new', text, icon='add')

    def all(self):
        text = 'List all projects'
        return Link('+all', text, icon='list')

    def products(self):
        return Link('/projects/', 'View projects')

    def distributions(self):
        return Link('/distros/', 'View distributions')

    def people(self):
        return Link('/people/', 'View people')

    def meetings(self):
        return Link('/sprints/', 'View meetings')


class ProductView(LaunchpadView):

    __used_for__ = IProduct

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)
        self.form = request.form_ng

    def initialize(self):
        self.product = self.context
        self.status_message = None

    def primary_translatable(self):
        """Return a dictionary with the info for a primary translatable.

        If there is no primary translatable object, returns None.

        The dictionary has the keys:
         * 'title': The title of the translatable object.
         * 'potemplates': a set of PO Templates for this object.
         * 'base_url': The base URL to reach the base URL for this object.
        """
        translatable = self.context.primary_translatable

        if translatable is not None:
            if ISourcePackage.providedBy(translatable):
                sourcepackage = translatable

                object_translatable = {
                    'title': sourcepackage.title,
                    'potemplates': sourcepackage.currentpotemplates,
                    'base_url': '/distros/%s/%s/+sources/%s' % (
                        sourcepackage.distribution.name,
                        sourcepackage.distroseries.name,
                        sourcepackage.name)
                    }

            elif IProductSeries.providedBy(translatable):
                productseries = translatable

                object_translatable = {
                    'title': productseries.title,
                    'potemplates': productseries.currentpotemplates,
                    'base_url': '/projects/%s/%s' %(
                        self.context.name,
                        productseries.name)
                    }
            else:
                # The translatable object does not implements an
                # ISourcePackage nor a IProductSeries. As it's not a critical
                # failure, we log only it instead of raise an exception.
                warn("Got an unknown type object as primary translatable",
                     RuntimeWarning)
                return None

            return object_translatable

        else:
            return None

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def distro_packaging(self):
        """This method returns a representation of the product packagings
        for this product, in a special structure used for the
        product-distros.pt page template.

        Specifically, it is a list of "distro" objects, each of which has a
        title, and an attribute "packagings" which is a list of the relevant
        packagings for this distro and product.
        """
        distros = {}
        # first get a list of all relevant packagings
        all_packagings = []
        for series in self.context.serieses:
            for packaging in series.packagings:
                all_packagings.append(packaging)
        # we sort it so that the packagings will always be displayed in the
        # distroseries version, then productseries name order
        all_packagings.sort(key=lambda a: (a.distroseries.version,
            a.productseries.name, a.id))
        for packaging in all_packagings:
            if distros.has_key(packaging.distroseries.distribution.name):
                distro = distros[packaging.distroseries.distribution.name]
            else:
                distro = {}
                distro['name'] = packaging.distroseries.distribution.name
                distro['title'] = packaging.distroseries.distribution.title
                distro['packagings'] = []
                distros[packaging.distroseries.distribution.name] = distro
            distro['packagings'].append(packaging)
        # now we sort the resulting set of "distro" objects, and return that
        result = distros.values()
        result.sort(cmp=_sort_distros)
        return result

    def projproducts(self):
        """Return a list of other products from the same project as this
        product, excluding this product"""
        if self.context.project is None:
            return []
        return [product for product in self.context.project.products
                        if product.id != self.context.id]

    def potemplatenames(self):
        potemplatenames = set([])

        for series in self.context.serieses:
            for potemplate in series.potemplates:
                potemplatenames.add(potemplate.potemplatename)

        return sorted(potemplatenames, key=lambda item: item.name)

    def sorted_serieses(self):
        """Return the series list from the product with the dev focus first."""
        series_list = list(self.context.serieses)
        series_list.remove(self.context.development_focus)
        # now sort the list by name with newer versions before older
        series_list = sorted_version_numbers(series_list,
                                             key=attrgetter('name'))
        series_list.insert(0, self.context.development_focus)
        return series_list

    def getClosedBugsURL(self, series):
        status = [status.title for status in RESOLVED_BUGTASK_STATUSES]
        url = canonical_url(series) + '/+bugs'
        return get_buglisting_search_filter_url(url, status=status)

class ProductDownloadFilesView(LaunchpadView):

    __used_for__ = IProduct

    def initialize(self):
        self.form = self.request.form
        self.product = self.context
        del_count = None
        if 'delete_files' in self.form:
            if self.request.method == 'POST':
                del(self.form['delete_files'])
                del_count = self.delete_files(self.form)
            else:
                # If there is a form submission and it is not a POST then
                # raise an error.  This is to protect against XSS exploits.
                raise UnsafeFormGetSubmissionError(self.form['delete_files'])
        if del_count is not None:
            if del_count <= 0:
                self.request.response.addNotification(
                    "No files were deleted.")
            elif del_count == 1:
                self.request.response.addNotification(
                    "1 file has been deleted.")
            else:
                self.request.response.addNotification(
                    "%d files have been deleted." %
                    del_count)

    def delete_files(self, data):
        del_keys = [int(v) for k,v in data.items()
                    if k.startswith('checkbox')]
        del_count = 0
        for series in self.product.serieses:
            for release in series.releases:
                for f in release.files:
                    if f.libraryfile.id in del_keys:
                        release.deleteFileAlias(f.libraryfile)
                        del_keys.remove(f.libraryfile.id)
                        del_count += 1
        return del_count

    def file_url(self, series, release, file_):
        """Create a download URL for the file."""
        return "%s/+download/%s" % (canonical_url(release),
                                    file_.libraryfile.filename)

    @cachedproperty
    def milestones(self):
        """Compute a mapping between series and releases that are milestones."""
        result = dict()
        for series in self.product.serieses:
            result[series] = dict()
            milestone_list = [m.name for m in series.milestones]
            for release in series.releases:
                if release.version in milestone_list:
                    result[series][release] = True
        return result

    def is_milestone(self, series, release):
        """Determine whether a release is milestone for the series."""
        return (series in self.milestones and
                release in self.milestones[series])

class ProductBrandingView(BrandingChangeView):

    schema = IProduct
    field_names = ['icon', 'logo', 'mugshot']


class ProductEditView(LaunchpadEditFormView):
    """View class that lets you edit a Product object."""

    schema = IProduct
    label = "Edit details"
    field_names = [
        "project", "displayname", "title", "summary", "description",
        "homepageurl", "sourceforgeproject",
        "freshmeatproject", "wikiurl", "screenshotsurl", "downloadurl",
        "programminglang", "development_focus"]

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        if self.context.active:
            return canonical_url(self.context)
        else:
            return canonical_url(getUtility(IProductSet))


class ProductChangeTranslatorsView(ProductEditView):
    label = "Change translation group"
    field_names = ["translationgroup", "translationpermission"]


class ProductReviewView(ProductEditView):
    label = "Administer project details"
    field_names = ["name", "owner", "active", "autoupdate", "reviewed",
                   "private_bugs"]


class ProductLaunchpadUsageEditView(LaunchpadEditFormView):
    """View class for defining Launchpad usage."""

    schema = IProductLaunchpadUsageForm
    label = "Describe Launchpad usage"
    custom_widget('bugtracker', ProductBugTrackerWidget)

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)

    @property
    def adapters(self):
        return {self.schema: self.context}


class ProductAddSeriesView(LaunchpadFormView):
    """A form to add new product series"""

    schema = IProductSeries
    field_names = ['name', 'summary', 'user_branch', 'releasefileglob']
    custom_widget('summary', TextAreaWidget, height=7, width=62)
    custom_widget('releasefileglob', StrippedTextWidget, displayWidth=40)

    series = None

    def validate(self, data):
        branch = data.get('user_branch')
        if branch is not None:
            message = get_series_branch_error(self.context, branch)
            if message:
                self.setFieldError('user_branch', message)

    @action(_('Register Series'), name='add')
    def add_action(self, action, data):
        self.series = self.context.newSeries(
            owner=self.user,
            name=data['name'],
            summary=data['summary'],
            branch=data['user_branch'])

    @property
    def next_url(self):
        assert self.series is not None, 'No series has been created'
        return canonical_url(self.series)


class ProductRdfView:
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile(
        '../templates/product-rdf.pt')

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        """Render RDF output, and return it as a string encoded in UTF-8.

        Render the page template to produce RDF output.
        The return value is string data encoded in UTF-8.

        As a side-effect, HTTP headers are set for the mime type
        and filename for download."""
        self.request.response.setHeader('Content-Type', 'application/rdf+xml')
        self.request.response.setHeader('Content-Disposition',
                                        'attachment; filename=%s.rdf' %
                                        self.context.name)
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


class ProductDynMenu(
        DynMenu, SprintsMixinDynMenu, SeriesOrReleasesMixinDynMenu):

    menus = {
        '': 'mainMenu',
        'meetings': 'meetingsMenu',
        'series': 'seriesMenu',
        }

    @neverempty
    def mainMenu(self):
        yield self.makeLink('Meetings', page='+sprints', submenu='meetings')
        yield self.makeLink('Milestones', page='+milestones')
        yield self.makeLink('Series', page='+series', submenu='series')
        yield self.makeLink(
            'Related', submenu='related', context=self.context.project)


class Icon:
    """An icon for use with image:icon."""

    def __init__(self, library_id):
        self.library_id = library_id

    def getURL(self):
        http_url = getUtility(ILibrarianClient).getURLForAlias(self.library_id)
        if config.launchpad.vhosts.use_https:
            return http_url.replace('http', 'https', 1)
        else:
            return http_url


class PillarSearchItem:
    """A search result item representing a Pillar."""

    implements(IHasIcon)

    icon = None

    def __init__(self, pillar_type, name, displayname, summary, icon_id):
        self.pillar_type = pillar_type
        self.name = name
        self.displayname = displayname
        self.summary = summary
        if icon_id is not None:
            self.icon = Icon(icon_id)

        # Even though the object doesn't implement the interface properly, we
        # still say that it provides them so that the standard image:icon
        # formatter works.
        if pillar_type == 'project':
            alsoProvides(self, IProduct)
        elif pillar_type == 'distribution':
            alsoProvides(self, IDistribution)
        elif pillar_type == 'project group':
            alsoProvides(self, IProject)
        else:
            raise AssertionError("Unknown pillar type: %s" % pillar_type)


class ProductSetView(LaunchpadView):

    __used_for__ = IProductSet

    max_results_to_display = config.launchpad.default_batch_size

    def initialize(self):
        form = self.request.form_ng
        self.soyuz = form.getOne('soyuz')
        self.rosetta = form.getOne('rosetta')
        self.malone = form.getOne('malone')
        self.bazaar = form.getOne('bazaar')
        self.search_string = form.getOne('text')
        self.results = None

        self.searchrequested = False
        if (self.search_string is not None or
            self.bazaar is not None or
            self.malone is not None or
            self.rosetta is not None or
            self.soyuz is not None):
            self.searchrequested = True

        if form.getOne('exact_name'):
            # If exact_name is supplied, we try and locate this name in
            # the ProductSet -- if we find it, bingo, redirect. This
            # argument can be optionally supplied by callers.
            try:
                product = self.context[self.search_string]
            except NotFoundError:
                # No product found, perform a normal search instead.
                pass
            else:
                url = canonical_url(product)
                if form.getOne('malone'):
                    url = url + "/+bugs"
                self.request.response.redirect(url)
                return

    def all_batched(self):
        return BatchNavigator(self.context.all_active, self.request)

    @cachedproperty
    def matches(self):
        if not self.searchrequested:
            return None
        pillarset = getUtility(IPillarNameSet)
        return pillarset.count_search_matches(self.search_string)

    @cachedproperty
    def searchresults(self):
        search_string = self.search_string.lower()
        limit = self.max_results_to_display
        return [
            PillarSearchItem(
                pillar_type=item['type'], name=item['name'],
                displayname=item['title'], summary=item['description'],
                icon_id=item['icon'])
            for item in getUtility(IPillarNameSet).search(search_string, limit)
        ]

    def tooManyResultsFound(self):
        return self.matches > self.max_results_to_display


class ProductAddView(LaunchpadFormView):

    schema = IProduct
    field_names = ['name', 'owner', 'displayname', 'title', 'summary',
                   'description', 'project', 'homepageurl',
                   'sourceforgeproject', 'freshmeatproject',
                   'wikiurl', 'screenshotsurl', 'downloadurl',
                   'programminglang', 'reviewed']
    custom_widget('homepageurl', TextWidget, displayWidth=30)
    custom_widget('screenshotsurl', TextWidget, displayWidth=30)
    custom_widget('wikiurl', TextWidget, displayWidth=30)
    custom_widget('downloadurl', TextWidget, displayWidth=30)

    label = "Register an upstream open source project"
    product = None

    def isVCSImport(self):
        if self.user is None:
            return False
        vcs_imports = getUtility(ILaunchpadCelebrities).vcs_imports
        return self.user.inTeam(vcs_imports)

    def setUpFields(self):
        LaunchpadFormView.setUpFields(self)
        if not self.isVCSImport():
            # vcs-imports members get it easy and are able to change
            # the owner and reviewed status during the edit process;
            # this saves time wasted on getting to product/+admin.
            # The fields are not displayed for other people though.
            self.form_fields = self.form_fields.omit('owner', 'reviewed')

    @action(_('Add'), name='add')
    def add_action(self, action, data):
        if self.user is None:
            raise zope.security.interfaces.Unauthorized(
                "Need an authenticated Launchpad owner")
        if not self.isVCSImport():
            # Zope makes sure these are never set, since they are not in
            # self.form_fields
            assert "owner" not in data
            assert "reviewed" not in data
            data['owner'] = self.user
            data['reviewed'] = False
        self.product = getUtility(IProductSet).createProduct(
            name=data['name'],
            title=data['title'],
            summary=data['summary'],
            description=data['description'],
            displayname=data['displayname'],
            homepageurl=data['homepageurl'],
            downloadurl=data['downloadurl'],
            screenshotsurl=data['screenshotsurl'],
            wikiurl=data['wikiurl'],
            freshmeatproject=data['freshmeatproject'],
            sourceforgeproject=data['sourceforgeproject'],
            programminglang=data['programminglang'],
            project=data['project'],
            owner=data['owner'],
            reviewed=data['reviewed'],
            )
        notify(ObjectCreatedEvent(self.product))

    @property
    def next_url(self):
        assert self.product is not None, 'No product has been created'
        return canonical_url(self.product)


class ProductBugContactEditView(SQLObjectEditView):
    """Browser view class for editing the product bug contact."""

    def changed(self):
        """Redirect to the product page with a success message."""
        product = self.context

        bugcontact = product.bugcontact
        if bugcontact:
            contact_display_value = None
            if bugcontact.preferredemail:
                # The bug contact was set to a new person or team.
                contact_display_value = bugcontact.preferredemail.email
            else:
                # The bug contact doesn't have a preferred email address, so it
                # must be a team.
                assert bugcontact.isTeam(), (
                    "Expected bug contact with no email address to be a team.")
                contact_display_value = bugcontact.browsername

            self.request.response.addNotification(
                "Successfully changed the bug contact to %s" %
                contact_display_value)
        else:
            # The bug contact was set to noone.
            self.request.response.addNotification(
                "Successfully cleared the bug contact. There is no longer a "
                "contact address that will receive all bugmail for this "
                "project. You can set the bug contact again at any time.")

        self.request.response.redirect(canonical_url(product))


class ProductReassignmentView(ObjectReassignmentView):
    """Reassign product to a new owner."""

    def __init__(self, context, request):
        ObjectReassignmentView.__init__(self, context, request)
        self.callback = self._reassignProductDependencies

    def _reassignProductDependencies(self, product, oldOwner, newOwner):
        """Reassign ownership of objects related to this product.

        Objects related to this product includes: ProductSeries,
        ProductReleases and TranslationImportQueueEntries that are owned
        by oldOwner of the product.

        """
        import_queue = getUtility(ITranslationImportQueue)
        for series in product.serieses:
            for entry in import_queue.getEntryByProductSeries(series):
                if entry.importer == oldOwner:
                    entry.importer = newOwner
            if series.owner == oldOwner:
                series.owner = newOwner
        for release in product.releases:
            if release.owner == oldOwner:
                release.owner = newOwner

class ProductShortLink(DefaultShortLink):

    def getLinkText(self):
        return self.context.displayname


class ProductBranchesView(BranchListingView):
    """View for branch listing for a product."""

    extra_columns = ('author',)

    def _branches(self):
        return getUtility(IBranchSet).getBranchesForProduct(
            self.context, self.selected_lifecycle_status)

    @property
    def no_branch_message(self):
        if self.selected_lifecycle_status:
            message = (
                'There may be branches registered for %s '
                'but none of them match the current filter criteria '
                'for this page. Try filtering on "Any Status".')
        else:
            message = (
                'There are no branches registered for %s '
                'in Launchpad today. We recommend you visit '
                '<a href="http://www.bazaar-vcs.org">www.bazaar-vcs.org</a> '
                'for more information about how you can use the Bazaar '
                'revision control system to improve community participation '
                'in this project.')
        return message % self.context.displayname
