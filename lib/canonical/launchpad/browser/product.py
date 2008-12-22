# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Browser views for products."""

__metaclass__ = type

__all__ = [
    'ProductActiveReviewsView',
    'ProductAddSeriesView',
    'ProductAddView',
    'ProductAddViewBase',
    'ProductAdminView',
    'ProductApprovedMergesView',
    'ProductBountiesMenu',
    'ProductBranchListingView',
    'ProductBranchOverviewView',
    'ProductBranchesMenu',
    'ProductBranchesView',
    'ProductBrandingView',
    'ProductBreadcrumbBuilder',
    'ProductBugsMenu',
    'ProductChangeTranslatorsView',
    'ProductCodeIndexView',
    'ProductDownloadFileMixin',
    'ProductDownloadFilesView',
    'ProductEditNavigationMenu',
    'ProductEditPeopleView',
    'ProductEditView',
    'ProductFacets',
    'ProductNavigation',
    'ProductNavigationMenu',
    'ProductOverviewMenu',
    'ProductRdfView',
    'ProductReviewLicenseView',
    'ProductSetBreadcrumbBuilder',
    'ProductSetContextMenu',
    'ProductSetFacets',
    'ProductSetNavigation',
    'ProductSetReviewLicensesView',
    'ProductSetView',
    'ProductSpecificationsMenu',
    'ProductTranslationsMenu',
    'ProductView',
    ]

from operator import attrgetter
import urllib

import zope.security.interfaces
from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.lifecycleevent import ObjectCreatedEvent
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.interface import implements, Interface
from zope.formlib import form

from canonical.cachedproperty import cachedproperty

from canonical.config import config
from lazr.delegates import delegates
from canonical.launchpad import _
from canonical.launchpad.fields import PillarAliases, PublicPersonChoice
from canonical.launchpad.interfaces import (
    BranchLifecycleStatusFilter, BranchListingSort, IBranchSet, IBugTracker,
    ICountry, ILaunchBag, ILaunchpadCelebrities, ILibraryFileAliasSet,
    IPersonSet, IPillarNameSet, IProductReviewSearch, IRevisionSet,
    ITranslationImportQueue, License, NotFoundError,
    RESOLVED_BUGTASK_STATUSES, UnsafeFormGetSubmissionError)
from canonical.launchpad.interfaces.product import (
    IProduct, IProductSet, LicenseStatus)
from canonical.launchpad.interfaces.productrelease import (
    IProductRelease, IProductReleaseSet)
from canonical.launchpad.interfaces.productseries import (
    IProductSeries)
from canonical.launchpad.interfaces.branchmergeproposal import (
    IBranchMergeProposalGetter, BranchMergeProposalStatus)
from canonical.launchpad import helpers
from canonical.launchpad.browser.announcement import HasAnnouncementsView
from canonical.launchpad.browser.branding import BrandingChangeView
from canonical.launchpad.browser.branchlisting import BranchListingView
from canonical.launchpad.browser.branchmergeproposallisting import (
    BranchMergeProposalListingView)
from canonical.launchpad.browser.branchref import BranchRef
from canonical.launchpad.browser.bugtask import (
    BugTargetTraversalMixin, get_buglisting_search_filter_url)
from canonical.launchpad.browser.distribution import UsesLaunchpadMixin
from canonical.launchpad.browser.faqtarget import FAQTargetNavigationMixin
from canonical.launchpad.browser.feeds import (
    FeedsMixin, ProductBranchesFeedLink)
from canonical.launchpad.browser.productseries import get_series_branch_error
from canonical.launchpad.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetTraversalMixin)
from canonical.launchpad.browser.translations import TranslationsMixin
from canonical.launchpad.mail import format_address, simple_sendmail
from canonical.launchpad.webapp import (
    ApplicationMenu, ContextMenu, LaunchpadEditFormView, LaunchpadFormView,
    LaunchpadView, Link, Navigation, StandardLaunchpadFacets, action,
    canonical_url, custom_widget, enabled_with_permission,
    sorted_version_numbers, stepthrough, stepto, structured, urlappend)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import BreadcrumbBuilder
from canonical.launchpad.webapp.menu import NavigationMenu
from canonical.launchpad.webapp.uri import URI
from canonical.widgets.date import DateWidget
from canonical.widgets.itemswidgets import (
    CheckBoxMatrixWidget,
    LaunchpadRadioWidget)
from canonical.widgets.popup import SinglePopupWidget
from canonical.widgets.product import LicenseWidget, ProductBugTrackerWidget
from canonical.widgets.textwidgets import StrippedTextWidget


class ProductNavigation(
    Navigation, BugTargetTraversalMixin,
    FAQTargetNavigationMixin, QuestionTargetTraversalMixin):

    usedfor = IProduct

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

    @stepthrough('+announcement')
    def traverse_announcement(self, name):
        return self.context.getAnnouncement(name)

    def traverse(self, name):
        return self.context.getSeries(name)


class ProductSetNavigation(Navigation):

    usedfor = IProductSet

    def traverse(self, name):
        product = self.context.getByName(name)
        if product is None:
            raise NotFoundError(name)
        return self.redirectSubTree(canonical_url(product))


class ProductLicenseMixin:
    """Adds license validation and requests reviews of licenses.

    Subclasses must inherit from Launchpad[Edit]FormView as well.

    Requires the "product" attribute be set in the child
    classes' action handler.
    """
    def validate(self, data):
        """Validate 'licenses' and 'license_info'.

        'licenses' must not be empty unless the product already
        exists and never has had a license set.

        'license_info' must not be empty if "Other/Proprietary"
        or "Other/Open Source" is checked.
        """
        licenses = data.get('licenses', [])
        license_widget = self.widgets.get('licenses')
        if (len(licenses) == 0 and
            license_widget is not None and
            not license_widget.allow_pending_license):
            # License is optional on +edit page if not already set.
            self.setFieldError(
                'licenses',
                'Select all licenses for this software or select '
                'Other/Proprietary or Other/Open Source.')
        elif License.OTHER_PROPRIETARY in licenses:
            if not data.get('license_info'):
                self.setFieldError(
                    'license_info',
                    'A description of the "Other/Proprietary" '
                    'license you checked is required.')
        elif License.OTHER_OPEN_SOURCE in licenses:
            if not data.get('license_info'):
                self.setFieldError(
                    'license_info',
                    'A description of the "Other/Open Source" '
                    'license you checked is required.')
        else:
            # Launchpad is ok with all licenses used in this project.
            pass

    def notifyFeedbackMailingList(self):
        """Email feedback@canonical.com to review product license."""
        if (License.OTHER_PROPRIETARY in self.product.licenses
                or License.OTHER_OPEN_SOURCE in self.product.licenses):
            user = getUtility(ILaunchBag).user
            subject = "Project License Submitted for %s by %s" % (
                    self.product.name, user.name)
            fromaddress = format_address(
                "Launchpad", config.canonical.noreply_from_address)
            license_titles = '\n'.join(
                license.title for license in self.product.licenses)
            def indent(text):
                text = '\n    '.join(line for line in text.split('\n'))
                text = '    ' + text
                return text

            template = helpers.get_email_template('product-license.txt')
            message = template % dict(
                user_browsername=user.browsername,
                user_name=user.name,
                product_name=self.product.name,
                product_url=canonical_url(self.product),
                product_summary=indent(self.product.summary),
                license_titles=indent(license_titles),
                license_info=indent(self.product.license_info))

            reply_to = format_address(user.displayname,
                                      user.preferredemail.email)
            simple_sendmail(fromaddress,
                            'feedback@launchpad.net',
                            subject, message,
                            headers={'Reply-To': reply_to})

            self.request.response.addInfoNotification(_(
                "Launchpad is free to use for software under approved "
                "licenses. The Launchpad team will be in contact with "
                "you soon."))


class ProductBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `IProduct`."""
    @property
    def text(self):
        return self.context.displayname


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


class IProductEditMenu(Interface):
    """A marker interface for the 'Change details' navigation menu."""


class ProductNavigationMenu(NavigationMenu):

    usedfor = IProduct
    facet = 'overview'
    links = [
      'details',
      'announcements',
      'downloads',
      ]

    def details(self):
        text = 'Details'
        return Link('', text)

    def announcements(self):
        text = 'Announcements'
        return Link('+announcements', text)

    def downloads(self):
        text = 'Downloads'
        return Link('+download', text)


class ProductEditNavigationMenu(NavigationMenu):
    """A sub-menu for different aspects of editing a Product's details."""

    usedfor = IProductEditMenu
    facet = 'overview'
    title = 'Change project details'
    links = ('details', 'branding', 'people')

    def details(self):
        target = '+edit'
        text = 'Details'
        return Link(target, text)

    def branding(self):
        text = 'Branding'
        return Link('+branding', text)

    def people(self):
        text = 'People'
        summary = 'Someone with permission to set goals for all series'
        return Link('+edit-people', text, summary)


class ProductOverviewMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'overview'
    links = [
        'edit',
        'reassign',
        'top_contributors',
        'mentorship',
        'distributions',
        'packages',
        'series_add',
        'announce',
        'announcements',
        'administer',
        'review_license',
        'rdf',
        ]

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        text = 'Change maintainer'
        return Link('+edit-people', text, icon='edit')

    def top_contributors(self):
        text = u'\u00BB More contributors'
        return Link('+topcontributors', text)

    def distributions(self):
        text = 'Packaging information'
        return Link('+distributions', text, icon='info')

    def mentorship(self):
        text = 'Mentoring available'
        return Link('+mentoring', text, icon='info')

    def packages(self):
        text = 'Show distribution packages'
        return Link('+packages', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def series_add(self):
        text = 'Register a series'
        return Link('+addseries', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def announce(self):
        text = 'Make announcement'
        summary = 'Publish an item of news for this project'
        return Link('+announce', text, summary, icon='add')

    def announcements(self):
        text = u'\u00BB More announcements'
        enabled = bool(self.context.announcements())
        return Link('+announcements', text, enabled=enabled)

    def rdf(self):
        text = structured(
            '<abbr title="Resource Description Framework">'
            'RDF</abbr> metadata')
        return Link('+rdf', text, icon='download')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')

    @enabled_with_permission('launchpad.Commercial')
    def review_license(self):
        text = 'Review license'
        return Link('+review-license', text, icon='edit')


class ProductBugsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'bugs'
    links = (
        'filebug',
        'bugsupervisor',
        'securitycontact',
        'cve',
        'subscribe'
        )

    def filebug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='bug')

    def cve(self):
        return Link('+cve', 'CVE reports', icon='cve')

    @enabled_with_permission('launchpad.Edit')
    def bugsupervisor(self):
        text = 'Change bug supervisor'
        return Link('+bugsupervisor', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        text = 'Change security contact'
        return Link('+securitycontact', text, icon='edit')

    def subscribe(self):
        text = 'Subscribe to bug mail'
        return Link('+subscribe', text, icon='edit')


class ProductReviewCountMixin:
    """A mixin used by the menu and the code index view."""

    @cachedproperty
    def active_review_count(self):
        """Return the number of active reviews for the user."""
        query = getUtility(IBranchMergeProposalGetter).getProposalsForContext(
            self.context, [BranchMergeProposalStatus.NEEDS_REVIEW], self.user)
        return query.count()

    @cachedproperty
    def approved_merge_count(self):
        """Return the number of active reviews for the user."""
        query = getUtility(IBranchMergeProposalGetter).getProposalsForContext(
            self.context, [BranchMergeProposalStatus.CODE_APPROVED],
            self.user)
        return query.count()


class ProductBranchesMenu(ApplicationMenu, ProductReviewCountMixin):

    usedfor = IProduct
    facet = 'branches'
    links = [
        'branch_add',
        'list_branches',
        'active_reviews',
        'approved_merges',
        'code_import',
        'branch_visibility',
        ]

    def branch_add(self):
        text = 'Register a branch'
        summary = 'Register a new Bazaar branch for this project'
        return Link('+addbranch', text, summary, icon='add')

    def list_branches(self):
        text = 'List branches'
        summary = 'List the branches for this project'
        return Link('+branches', text, summary, icon='add')

    def active_reviews(self):
        if self.active_review_count == 1:
            text = 'pending proposal'
        else:
            text = 'pending proposals'
        return Link('+activereviews', text)

    def approved_merges(self):
        if self.approved_merge_count == 1:
            text = 'unmerged proposal'
        else:
            text = 'unmerged proposals'
        return Link('+approvedmerges', text)

    @enabled_with_permission('launchpad.Admin')
    def branch_visibility(self):
        text = 'Define branch visibility'
        return Link('+branchvisibility', text, icon='edit')

    def code_import(self):
        text = 'Import your project'
        enabled = not self.context.official_codehosting
        return Link('/+code-imports/+new', text, icon='add', enabled=enabled)


class ProductSpecificationsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'specifications'
    links = ['listall', 'doc', 'table', 'new']

    def listall(self):
        text = 'List all blueprints'
        summary = 'Show all specifications for %s' %  self.context.title
        return Link('+specs?show=all', text, summary, icon='info')

    def doc(self):
        text = 'List documentation'
        summary = 'List all complete informational specifications'
        return Link('+documentation', text, summary,
            icon='info')

    def table(self):
        text = 'Assignments'
        summary = 'Show the full assignment of work, drafting and approving'
        return Link('+assignments', text, summary, icon='info')

    def new(self):
        text = 'Register a blueprint'
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
    links = [
        'translators',
        'imports',
        'translationdownload',
        'help_translate',
        ]

    def imports(self):
        text = 'See import queue'
        return Link('+imports', text)

    @enabled_with_permission('launchpad.Edit')
    def translators(self):
        text = 'Change translators'
        return Link('+changetranslators', text, icon='edit')

    @enabled_with_permission('launchpad.AnyPerson')
    def translationdownload(self):
        text = 'Download translations'
        preferred_series = self.context.primary_translatable
        enabled = (self.context.official_rosetta and
            preferred_series is not None)
        link = ''
        if enabled:
            link = '%s/+export' % preferred_series.name

        return Link(link, text, icon='download', enabled=enabled)

    def help_translate(self):
        text = 'Help translate'
        link = canonical_url(self.context, rootsite='translations')
        return Link(link, text, icon='translation')


def _sort_distros(a, b):
    """Put Ubuntu first, otherwise in alpha order."""
    if a['name'] == 'ubuntu':
        return -1
    return cmp(a['name'], b['name'])


class ProductSetBreadcrumbBuilder(BreadcrumbBuilder):
    """Return a breadcrumb for an `IProductSet`."""
    text = "Projects"


class ProductSetFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for the IProductSet."""

    usedfor = IProductSet

    enable_only = ['overview']


class ProductSetContextMenu(ContextMenu):

    usedfor = IProductSet

    links = ['products', 'distributions', 'people', 'meetings',
             'all', 'register', 'register_team']

    def register(self):
        text = 'Register a project'
        # We link to the guided form, though people who know the URL can
        # just jump to +new directly. That might be considered a
        # feature!
        return Link('+new-guided', text, icon='add')

    def register_team(self):
        text = 'Register a team'
        return Link('/people/+newteam', text, icon='add')

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


class SortSeriesMixin:
    """Provide access to helpers for series."""

    @property
    def sorted_series_list(self):
        """Return a sorted list of series.

        The series list is sorted by version in reverse order.
        The development focus is always first in the list.
        """
        series_list = list(self.product.serieses)
        series_list.remove(self.product.development_focus)
        # Now sort the list by name with newer versions before older.
        series_list = sorted_version_numbers(series_list,
                                             key=attrgetter('name'))
        series_list.insert(0, self.product.development_focus)
        return series_list


class ProductWithSeries:
    """A decorated product that includes series data.

    The extra data is included in this class to avoid repeated
    database queries.  Rather than hitting the database, the data is
    cached locally and simply returned.
    """

    # These need to be predeclared to avoid delegates taking them
    # over.
    serieses = None
    development_focus = None
    delegates(IProduct, 'product')

    def __init__(self, product):
        self.product = product
        self.serieses = []
        self.series_by_id = {}

    def setSeries(self, serieses):
        """Set the serieses to the provided collection."""
        self.serieses = serieses
        self.series_by_id = dict(
            (series.id, series) for series in self.serieses)

    def getSeriesById(self, id):
        """Look up and return a ProductSeries by id."""
        return self.series_by_id.get(id)


class SeriesWithReleases:
    """A decorated series that includes releases.

    The extra data is included in this class to avoid repeated
    database queries.  Rather than hitting the database, the data is
    cached locally and simply returned.
    """

    # These need to be predeclared to avoid delegates taking them
    # over.
    releases = None
    delegates(IProductSeries, 'series')

    def __init__(self, series):
        self.series = series
        self.releases = []

    def addRelease(self, release):
        self.releases.append(release)

    @cachedproperty
    def release_files(self):
        files = set()
        for release in self.releases:
            files = files.union(release.files)
        return files


class ReleaseWithFiles:
    """A decorated release that includes product release files.

    The extra data is included in this class to avoid repeated
    database queries.  Rather than hitting the database, the data is
    cached locally and simply returned.
    """

    # These need to be predeclared to avoid delegates taking them
    # over.
    files = None
    delegates(IProductRelease, 'release')

    def __init__(self, release):
        self.release = release
        self.files = []

    def addFile(self, file):
        self.files.append(file)


class ProductDownloadFileMixin:
    """Provides methods for managing download files."""


    @cachedproperty
    def product(self):
        """Product with all series, release and file data cached.

        Decorated classes are created, and they contain cached data
        obtained with a few queries rather than many iterated queries.
        """
        # Create the decorated product and set the list of series.
        original_product = self.context

        product = ProductWithSeries(original_product)
        serieses = []
        for series in original_product.serieses:
            series_with_releases = SeriesWithReleases(series)
            serieses.append(series_with_releases)
            if original_product.development_focus == series:
                product.development_focus = series_with_releases

        product.setSeries(serieses)

        # Get all of the releases for all of the serieses in a single
        # query.  The query sorts the releases properly so we know the
        # resulting list is sorted correctly.
        release_set = getUtility(IProductReleaseSet)
        release_by_id = {}
        releases = release_set.getReleasesForSerieses(
            product.serieses)
        for release in releases:
            series = product.getSeriesById(
                release.productseries.id)
            decorated_release = ReleaseWithFiles(release)
            series.addRelease(decorated_release)
            release_by_id[release.id] = decorated_release

        # Get all of the files for all of the releases.  The query
        # returns all releases sorted properly.
        files = release_set.getFilesForReleases(releases)
        for file in files:
            release = release_by_id[file.productrelease.id]
            release.addFile(file)

        return product

    def deleteFiles(self, releases):
        """Delete the selected files from the set of releases.

        :param releases: A set of releases in the view.
        :return: The number of files deleted.
        """
        del_count = 0
        for release in releases:
            for release_file in release.files:
                if release_file.libraryfile.id in self.delete_ids:
                    release_file.destroySelf()
                    self.delete_ids.remove(release_file.libraryfile.id)
                    del_count += 1
        return del_count

    def getReleases(self):
        """Find the releases with download files for view."""
        raise NotImplementedError

    def fileURL(self, file_, release=None):
        """Create a download URL for the `LibraryFileAlias`."""
        if release is None:
            release = self.context
        url = urlappend(canonical_url(release), '+download')
        # Quote the filename to eliminate non-ascii characters which
        # are invalid in the url.
        url = urlappend(url, urllib.quote(file_.filename.encode('utf-8')))
        return str(URI(url).replace(scheme='http'))

    def md5URL(self, file_, release=None):
        """Create a URL for the MD5 digest."""
        baseurl = self.fileURL(file_, release)
        return urlappend(baseurl, '+md5')

    def processDeleteFiles(self):
        """If the 'delete_files' button was pressed, process the deletions."""
        del_count = None
        self.delete_ids = [int(value) for key, value in self.form.items()
                           if key.startswith('checkbox')]
        if 'delete_files' in self.form:
            if self.request.method == 'POST':
                del(self.form['delete_files'])
                releases = self.getReleases()
                del_count = self.deleteFiles(releases)
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

    def seriesHasDownloadFiles(self, series):
        """Determine whether a series has any download files."""
        for release in series.releases:
            if len(release.files) > 0:
                return True

    @cachedproperty
    def latest_release_with_download_files(self):
        """Return the latest release with download files."""
        for series in self.sorted_series_list:
            for release in series.releases:
                if len(list(release.files)) > 0:
                    return release
        return None


class ProductView(HasAnnouncementsView, SortSeriesMixin, FeedsMixin,
                  ProductDownloadFileMixin, UsesLaunchpadMixin):

    __used_for__ = IProduct

    def __init__(self, context, request):
        HasAnnouncementsView.__init__(self, context, request)
        self.form = request.form_ng

    def initialize(self):
        self.status_message = None

    @property
    def show_license_status(self):
        return self.context.license_status != LicenseStatus.OPEN_SOURCE

    @property
    def freshmeat_url(self):
        if self.context.freshmeatproject:
            return ("http://freshmeat.net/projects/%s"
                % self.context.freshmeatproject)
        return None

    @property
    def sourceforge_url(self):
        if self.context.sourceforgeproject:
            return ("http://sourceforge.net/projects/%s"
                % self.context.sourceforgeproject)
        return None

    @property
    def has_external_links(self):
        return (self.context.homepageurl or
                self.context.sourceforgeproject or
                self.context.freshmeatproject or
                self.context.wikiurl or
                self.context.screenshotsurl or
                self.context.downloadurl)

    @property
    def should_display_homepage(self):
        return (self.context.homepageurl and
                self.context.homepageurl not in
                    [self.freshmeat_url, self.sourceforge_url])

    @cachedproperty
    def uses_translations(self):
        """Whether this product has translatable templates."""
        return (self.context.official_rosetta and self.primary_translatable)

    @cachedproperty
    def primary_translatable(self):
        """Return a dictionary with the info for a primary translatable.

        If there is no primary translatable object, returns an empty
        dictionary.

        The dictionary has the keys:
         * 'title': The title of the translatable object.
         * 'potemplates': a set of PO Templates for this object.
         * 'base_url': The base URL to reach the base URL for this object.
        """
        translatable = self.context.primary_translatable

        if translatable is None:
            return {}

        return {
            'title': translatable.title,
            'potemplates': translatable.getCurrentTranslationTemplates(),
            'base_url': canonical_url(translatable)
            }

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

    def getClosedBugsURL(self, series):
        status = [status.title for status in RESOLVED_BUGTASK_STATUSES]
        url = canonical_url(series) + '/+bugs'
        return get_buglisting_search_filter_url(url, status=status)

    def getLatestBranches(self):
        return self.context.getLatestBranches(visible_by_user=self.user)

    @property
    def requires_commercial_subscription(self):
        """Whether to display notice to purchase a commercial subscription."""
        return (len(self.context.licenses) > 0
                and self.context.commercial_subscription_is_due)

    @property
    def can_purchase_subscription(self):
        return (check_permission('launchpad.Edit', self.context)
                and not self.context.qualifies_for_free_hosting)

    @cachedproperty
    def effective_driver(self):
        """Return the product driver or the project driver."""
        if self.context.driver is not None:
            driver = self.context.driver
        elif (self.context.project is not None and
              self.context.project.driver is not None):
            driver = self.context.project.driver
        else:
            driver = None
        return driver

    @cachedproperty
    def show_commercial_subscription_info(self):
        """Should subscription information be shown?

        Subscription information is only shown to the project maintainers,
        Launchpad admins, and members of the Launchpad commercial team.  The
        first two are allowed via the Launchpad.Edit permission.  The latter
        is allowed via Launchpad.Commercial.
        """
        return (check_permission('launchpad.Edit', self.context) or
                check_permission('launchpad.Commercial', self.context))


class ProductDownloadFilesView(LaunchpadView,
                               SortSeriesMixin,
                               ProductDownloadFileMixin):
    """View class for the product's file downloads page."""
    __used_for__ = IProduct

    def initialize(self):
        self.form = self.request.form
        # Manually process action for the 'Delete' button.
        self.processDeleteFiles()

    def getReleases(self):
        """See `ProductDownloadFileMixin`."""
        releases = set()
        for series in self.product.serieses:
            releases.update(series.releases)
        return releases

    @cachedproperty
    def has_download_files(self):
        """Across series and releases do any download files exist?"""
        for series in self.product.serieses:
            if self.seriesHasDownloadFiles(series):
                return True
        return False

    @cachedproperty
    def any_download_files_with_signatures(self):
        """Across series and releases do any download files have signatures?
        """
        for series in self.product.serieses:
            for release in series.releases:
                for file in release.files:
                    if file.signature:
                        return True
        return False

    @cachedproperty
    def milestones(self):
        """A mapping between series and releases that are milestones."""
        result = dict()
        for series in self.product.serieses:
            result[series.name] = set()
            milestone_list = [m.name for m in series.milestones]
            for release in series.releases:
                if release.version in milestone_list:
                    result[series.name].add(release.version)
        return result

    def is_milestone(self, series, release):
        """Determine whether a release is milestone for the series."""
        return (series.name in self.milestones and
                release.version in self.milestones[series.name])


class ProductBrandingView(BrandingChangeView):

    implements(IProductEditMenu)

    label = None
    schema = IProduct
    field_names = ['icon', 'logo', 'mugshot']


class ProductEditView(ProductLicenseMixin, LaunchpadEditFormView):
    """View class that lets you edit a Product object."""

    implements(IProductEditMenu)

    schema = IProduct
    field_names = [
        "displayname",
        "title",
        "summary",
        "description",
        "bug_reporting_guidelines",
        "project",
        "official_codehosting",
        "bugtracker",
        "enable_bug_expiration",
        "official_blueprints",
        "official_rosetta",
        "official_answers",
        "homepageurl",
        "sourceforgeproject",
        "freshmeatproject",
        "wikiurl",
        "screenshotsurl",
        "downloadurl",
        "programminglang",
        "development_focus",
        "licenses",
        "license_info",
    ]
    custom_widget(
        'licenses', LicenseWidget, column_count=3, orientation='vertical')
    custom_widget('bugtracker', ProductBugTrackerWidget)

    def setUpWidgets(self):
        super(ProductEditView, self).setUpWidgets()
        # Licenses are optional on +edit page if they have not already
        # been set. Subclasses may not have 'licenses' widget.
        # ('licenses' in self.widgets) is broken.
        if (len(self.context.licenses) == 0 and
            self.widgets.get('licenses') is not None):
            self.widgets['licenses'].allow_pending_license = True

    def validate(self, data):
        """Constrain bug expiration to Launchpad Bugs tracker."""
        # enable_bug_expiration is disabled by JavaScript when bugtracker
        # is not 'In Launchpad'. The contraint is enforced here in case the
        # JavaScript fails to activate or run. Note that the bugtracker
        # name : values are {'In Launchpad' : object, 'Somewhere else' : None
        # 'In a registered bug tracker' : IBugTracker}.
        bugtracker = data.get('bugtracker', None)
        if bugtracker is None or IBugTracker.providedBy(bugtracker):
            data['enable_bug_expiration'] = False
        ProductLicenseMixin.validate(self, data)

    @action("Change", name='change')
    def change_action(self, action, data):
        previous_licenses = self.context.licenses
        self.updateContextFromData(data)
        # only send email the first time licenses are set
        if len(previous_licenses) == 0:
            # self.product is expected by notifyFeedbackMailingList
            self.product = self.context
            self.notifyFeedbackMailingList()

    @property
    def next_url(self):
        if self.context.active:
            return canonical_url(self.context)
        else:
            return canonical_url(getUtility(IProductSet))


class ProductChangeTranslatorsView(TranslationsMixin, ProductEditView):
    label = "Select a new translation group"
    field_names = ["translationgroup", "translationpermission"]


class ProductAdminView(ProductEditView):
    label = "Administer project details"
    field_names = ["name", "owner", "active", "autoupdate", "private_bugs"]
    custom_widget('registrant', SinglePopupWidget)

    def setUpFields(self):
        """Setup the normal fields from the schema plus adds 'Registrant'.

        The registrant is normally a read-only field and thus does not have a
        proper widget created by default.  Even though it is read-only, admins
        need the ability to change it.
        """
        super(ProductAdminView, self).setUpFields()
        self.form_fields = (self._createAliasesField() + self.form_fields
                            + self._createRegistrantField())

    def _createAliasesField(self):
        """Return a PillarAliases field for IProduct.aliases."""
        return form.Fields(
            PillarAliases(
                __name__='aliases', title=_('Aliases'),
                description=_('Other names (separated by space) under which '
                              'this project is known.'),
                required=False, readonly=False),
            render_context=self.render_context)

    def _createRegistrantField(self):
        """Return a popup widget person selector for the registrant.

        This custom field is necessary because *normally* the registrant is
        read-only but we want the admins to have the ability to correct legacy
        data that was set before the registrant field existed.
        """
        return form.Fields(
            PublicPersonChoice(
                __name__='registrant',
                title=_('Project Registrant'),
                description=_('The person who originally registered the '
                              'product.  Distinct from the current '
                              'owner.  This is historical data and should '
                              'not be changed without good cause.'),
                vocabulary='ValidPersonOrTeam',
                required=True,
                readonly=False,
                ),
            render_context=self.render_context
            )

    def validate(self, data):
        if data.get('private_bugs') and self.context.bug_supervisor is None:
            self.setFieldError('private_bugs',
                structured(
                    'Set a <a href="%s/+bugsupervisor">bug supervisor</a> '
                    'for this project first.',
                    canonical_url(self.context, rootsite="bugs")))

    @property
    def cancel_url(self):
        return canonical_url(self.context)


class ProductReviewLicenseView(ProductEditView):
    label = "Review project licensing"
    field_names = [
        "active",
        "private_bugs",
        "license_reviewed",
        "license_approved",
        "reviewer_whiteboard",
        ]

    def validate(self, data):
        """Validate approval.

        A project can only be approved if it has OTHER_OPEN_SOURCE as one of
        its licenses and not OTHER_PROPRIETARY.
        """
        licenses = self.context.licenses
        license_approved = data.get('license_approved', False)
        if license_approved:
            if License.OTHER_PROPRIETARY in licenses:
                self.setFieldError(
                    'license_approved',
                    'Proprietary projects may not be manually '
                    'approved to use Launchpad.  Proprietary projects '
                    'must use the commercial subscription voucher system '
                    'to be allowed to use Launchpad.')
            elif License.OTHER_OPEN_SOURCE not in licenses:
                self.setFieldError(
                    'license_approved',
                    'Only "Other/Open Source" licenses may be '
                    'manually approved to use Launchpad.')
            else:
                # An Other/Open Source license was specified so it may be
                # approved.
                pass

    @property
    def next_url(self):
        """Successful form submission should send to this URL."""
        # The referer header we want is only available before the view's
        # form submits to itself. This field is a hidden input in the form.
        referrer = self.request.form.get('next_url')
        if referrer is None:
            referrer = self.request.getHeader('referer')

        if (referrer is not None
            and referrer.startswith(self.request.getApplicationURL())):
            return referrer
        else:
            return canonical_url(self.context)

    @property
    def cancel_url(self):
        return self.next_url


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


class Icon:
    """An icon for use with image:icon."""

    def __init__(self, library_id):
        self.library_alias = getUtility(ILibraryFileAliasSet)[library_id]

    def getURL(self):
        return self.library_alias.getURL()


class ProductSetView(LaunchpadView):

    __used_for__ = IProductSet

    max_results_to_display = config.launchpad.default_batch_size
    results = None
    searchrequested = False

    def initialize(self):
        form = self.request.form_ng
        self.search_string = form.getOne('text')
        if self.search_string is not None:
            self.searchrequested = True

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
        return getUtility(IPillarNameSet).search(search_string, limit)

    def tooManyResultsFound(self):
        return self.matches > self.max_results_to_display


class ProductSetReviewLicensesView(LaunchpadFormView):
    """View for searching products to be reviewed."""

    schema = IProductReviewSearch

    full_row_field_names = [
        'search_text',
        'active',
        'license_reviewed',
        'license_info_is_empty',
        'licenses',
        'has_zero_licenses',
        ]

    side_by_side_field_names = [
        ('created_after', 'created_before'),
        ('subscription_expires_after', 'subscription_expires_before'),
        ('subscription_modified_after', 'subscription_modified_before'),
        ]

    custom_widget(
        'licenses', CheckBoxMatrixWidget, column_count=4,
        orientation='vertical')
    custom_widget('active', LaunchpadRadioWidget,
                  _messageNoValue="(do not filter)")
    custom_widget('license_reviewed', LaunchpadRadioWidget,
                  _messageNoValue="(do not filter)")
    custom_widget('license_info_is_empty', LaunchpadRadioWidget,
                  _messageNoValue="(do not filter)")
    custom_widget('has_zero_licenses', LaunchpadRadioWidget,
                  _messageNoValue="(do not filter)")
    custom_widget('created_after', DateWidget)
    custom_widget('created_before', DateWidget)
    custom_widget('subscription_expires_after', DateWidget)
    custom_widget('subscription_expires_before', DateWidget)
    custom_widget('subscription_modified_after', DateWidget)
    custom_widget('subscription_modified_before', DateWidget)

    @property
    def left_side_widgets(self):
        return (self.widgets.get(left)
                for left, right in self.side_by_side_field_names)

    @property
    def right_side_widgets(self):
        return (self.widgets.get(right)
                for left, right in self.side_by_side_field_names)

    @property
    def full_row_widgets(self):
        return (self.widgets[name] for name in self.full_row_field_names)

    def forReviewBatched(self):
        # Calling _validate populates the data dictionary as a side-effect
        # of validation.
        data = {}
        self._validate(None, data)
        # Get default values from the schema since the form defaults
        # aren't available until the search button is pressed.
        search_params = {}
        for name in self.schema:
            search_params[name] = self.schema[name].default
        # Override the defaults with the form values if available.
        search_params.update(data)
        return BatchNavigator(self.context.forReview(**search_params),
                              self.request, size=10)


class ProductAddViewBase(ProductLicenseMixin, LaunchpadFormView):
    """Abstract class for adding a new product.

    ProductLicenseMixin requires the "product" attribute be set in the
    child classes' action handler.
    """

    schema = IProduct
    product = None
    field_names = ['name', 'displayname', 'title', 'summary',
                   'description', 'homepageurl', 'sourceforgeproject',
                   'freshmeatproject', 'wikiurl', 'screenshotsurl',
                   'downloadurl', 'programminglang',
                   'licenses', 'license_info']
    custom_widget(
        'licenses', LicenseWidget, column_count=3, orientation='vertical')
    custom_widget('homepageurl', TextWidget, displayWidth=30)
    custom_widget('screenshotsurl', TextWidget, displayWidth=30)
    custom_widget('wikiurl', TextWidget, displayWidth=30)
    custom_widget('downloadurl', TextWidget, displayWidth=30)

    @property
    def next_url(self):
        assert self.product is not None, 'No product has been created'
        return canonical_url(self.product)


class ProductAddView(ProductAddViewBase):

    field_names = (ProductAddViewBase.field_names
                   + ['owner', 'project', 'license_reviewed'])

    label = "Register an upstream open source project"
    product = None

    def isVCSImport(self):
        if self.user is None:
            return False
        vcs_imports = getUtility(ILaunchpadCelebrities).vcs_imports
        return self.user.inTeam(vcs_imports)

    def setUpFields(self):
        super(ProductAddView, self).setUpFields()
        if not self.isVCSImport():
            # vcs-imports members get it easy and are able to change
            # the owner and reviewed status during the edit process;
            # this saves time wasted on getting to product/+admin.
            # The fields are not displayed for other people though.
            self.form_fields = self.form_fields.omit('owner',
                                                     'license_reviewed')

    @action(_('Add'), name='add')
    def add_action(self, action, data):
        if self.user is None:
            raise zope.security.interfaces.Unauthorized(
                "Need an authenticated Launchpad owner")
        if not self.isVCSImport():
            # Zope makes sure these are never set, since they are not in
            # self.form_fields
            assert "owner" not in data
            assert "license_reviewed" not in data
            data['owner'] = self.user
            data['license_reviewed'] = False
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
            registrant=self.user,
            license_reviewed=data['license_reviewed'],
            licenses = data['licenses'],
            license_info=data['license_info'])
        self.notifyFeedbackMailingList()
        notify(ObjectCreatedEvent(self.product))


class ProductEditPeopleView(LaunchpadEditFormView):
    """Enable editing of important people on the project."""

    implements(IProductEditMenu)

    schema = IProduct
    field_names = [
        'owner',
        'driver',
        ]

    @action(_('Save changes'), name='save')
    def save_action(self, action, data):
        old_owner = self.context.owner
        old_driver = self.context.driver
        self.updateContextFromData(data)
        self._reassignProductDependencies(
            self.context, old_owner, self.context.owner)
        if self.context.owner != old_owner:
            self.request.response.addNotification(
                "Successfully changed the maintainer to %s"
                % self.context.owner.displayname)
        if self.context.driver != old_driver:
            if self.context.driver is not None:
                self.request.response.addNotification(
                    "Successfully changed the driver to %s"
                    % self.context.driver.displayname)
            else:
                self.request.response.addNotification(
                    "Successfully removed the driver")

    @property
    def next_url(self):
        return canonical_url(self.context)

    def _reassignProductDependencies(self, product, oldOwner, newOwner):
        """Reassign ownership of objects related to this product.

        Objects related to this product includes: ProductSeries,
        ProductReleases and TranslationImportQueueEntries that are owned
        by oldOwner of the product.

        """
        import_queue = getUtility(ITranslationImportQueue)
        for entry in import_queue.getAllEntries(target=product):
            if entry.importer == oldOwner:
                entry.importer = newOwner
        for series in product.serieses:
            if series.owner == oldOwner:
                series.owner = newOwner
        for release in product.releases:
            if release.owner == oldOwner:
                release.owner = newOwner

class ProductBranchOverviewView(LaunchpadView, SortSeriesMixin, FeedsMixin):
    """View for the product code overview."""

    __used_for__ = IProduct

    feed_types = (
        ProductBranchesFeedLink,
        )

    def initialize(self):
        self.product = self.context

    @property
    def codebrowse_root(self):
        """Return the link to codebrowse for this branch."""
        return config.codehosting.codebrowse_root


class ProductBranchListingView(BranchListingView):
    """A base class for product branch listings."""

    show_series_links = True
    no_sort_by = (BranchListingSort.PRODUCT,)

    @cachedproperty
    def branch_count(self):
        """The number of total branches the user can see."""
        return getUtility(IBranchSet).getBranchesForContext(
            context=self.context, visible_by_user=self.user).count()

    @cachedproperty
    def development_focus_branch(self):
        dev_focus_branch = self.context.development_focus.series_branch
        if dev_focus_branch is None:
            return None
        elif check_permission('launchpad.View', dev_focus_branch):
            return dev_focus_branch
        else:
            return None

    @property
    def no_branch_message(self):
        if (self.selected_lifecycle_status is not None
            and self.hasAnyBranchesVisibleByUser()):
            message = (
                'There are branches registered for %s '
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


class ProductCodeIndexView(ProductBranchListingView, SortSeriesMixin,
                           ProductDownloadFileMixin, ProductReviewCountMixin):
    """Initial view for products on the code virtual host."""

    show_set_development_focus = True

    def initialize(self):
        ProductBranchListingView.initialize(self)
        self.product = self.context

    @property
    def form_action(self):
        return "+branches"

    @property
    def initial_values(self):
        return {
            'lifecycle': BranchLifecycleStatusFilter.CURRENT,
            'sort_by': BranchListingSort.DEFAULT,
            }

    @cachedproperty
    def _recent_revisions(self):
        """Revisions for this project created in the last 30 days."""
        # The actual number of revisions for any given project are likely
        # to be small(ish).  We also need to be able to traverse over the
        # actual revision authors in order to get an accurate count.
        revisions = list(
            getUtility(IRevisionSet).getRecentRevisionsForProduct(
                product=self.context, days=30))
        # XXX: thumper 2008-04-24
        # How best to warn if the limit is getting too large?
        # And how much is too much anyway.
        return revisions

    @property
    def commit_count(self):
        """The number of new revisions in the last 30 days."""
        return len(self._recent_revisions)

    @cachedproperty
    def committer_count(self):
        """The number of committers in the last 30 days."""
        # Record a set of tuples where the first part is a launchpad
        # person name if know, and the second part is the revision author
        # text.  Only one part of the tuple will be set.
        committers = set()
        for (revision, author) in self._recent_revisions:
            if author.personID is None:
                committers.add((None, author.name))
            else:
                committers.add((author.personID, None))
        return len(committers)

    @cachedproperty
    def _branch_owners(self):
        """The owners of branches."""
        # Listify the owners, there really shouldn't be that many for any
        # one project.
        return list(getUtility(IPersonSet).getPeopleWithBranches(
                product=self.context))

    @cachedproperty
    def person_owner_count(self):
        """The number of individual people who own branches."""
        return len([person for person in self._branch_owners
                    if not person.isTeam()])

    @cachedproperty
    def team_owner_count(self):
        """The number of teams who own branches."""
        return len([person for person in self._branch_owners
                    if person.isTeam()])

    def _getSeriesBranches(self):
        """Get the series branches for the product, dev focus first."""
        # XXX: thumper 2008-04-22
        # When bug 181157 is fixed, only get branches for non-obsolete
        # series.

        # We want to show each series branch only once, always show the
        # development focus branch, no matter what's it lifecycle status, and
        # skip subsequent series where the lifecycle status is Merged or
        # Abandoned
        sorted_series = self.sorted_series_list
        def show_branch(branch):
            if self.selected_lifecycle_status is None:
                return True
            else:
                return (branch.lifecycle_status in
                    self.selected_lifecycle_status)
        # The series will always have at least one series, that of the
        # development focus.
        dev_focus_branch = sorted_series[0].series_branch
        if not check_permission('launchpad.View', dev_focus_branch):
            dev_focus_branch = None
        result = []
        if dev_focus_branch is not None and show_branch(dev_focus_branch):
            result.append(dev_focus_branch)
        for series in sorted_series[1:]:
            branch = series.series_branch
            if (branch is not None and
                branch not in result and
                check_permission('launchpad.View', branch) and
                show_branch(branch)):
                result.append(branch)
        return result

    @cachedproperty
    def initial_branches(self):
        """Return the series branches, followed by most recently changed."""
        series_branches = self._getSeriesBranches()
        branch_query = getUtility(IBranchSet).getBranchesForContext(
            context=self.context, visible_by_user=self.user,
            lifecycle_statuses=self.selected_lifecycle_status,
            sort_by=BranchListingSort.MOST_RECENTLY_CHANGED_FIRST)
        # We don't want the initial branch listing to be batched, so only get
        # the batch size - the number of series_branches.
        batch_size = config.launchpad.branchlisting_batch_size
        max_branches_from_query = batch_size - len(series_branches)
        # Since series branches are actual branches, and the query
        # returns the bastardised BranchWithSortColumns, we need to
        # check branch ids in the following list comprehension.
        series_branch_ids = set(branch.id for branch in series_branches)
        # We want to make sure that the series branches do not appear
        # in our branch list.
        branches = [
            branch for branch in branch_query[:max_branches_from_query]
            if branch.id not in series_branch_ids]
        series_branches.extend(branches)
        return series_branches

    def _branches(self, lifecycle_status):
        """Return the series branches, followed by most recently changed."""
        # The params are ignored, and only used by the listing view.
        return self.initial_branches

    @property
    def unseen_branch_count(self):
        """How many branches are not shown."""
        return self.branch_count - len(self.initial_branches)

    def hasAnyBranchesVisibleByUser(self):
        """See `BranchListingView`."""
        return self.branch_count > 0

    @property
    def has_development_focus_branch(self):
        """Is there a branch assigned as development focus?"""
        return self.development_focus_branch is not None

    def _getPluralText(self, count, singular, plural):
        if count == 1:
            return singular
        else:
            return plural

    @property
    def branch_text(self):
        return self._getPluralText(
            self.branch_count, _('branch'), _('branches'))

    @property
    def person_text(self):
        return self._getPluralText(
            self.person_owner_count, _('person'), _('people'))

    @property
    def team_text(self):
        return self._getPluralText(
            self.team_owner_count, _('team'), _('teams'))

    @property
    def commit_text(self):
        return self._getPluralText(
            self.commit_count, _('commit'), _('commits'))

    @property
    def committer_text(self):
        return self._getPluralText(
            self.committer_count, _('person'), _('people'))


class ProductBranchesView(ProductBranchListingView):
    """View for branch listing for a product."""

    def initialize(self):
        """Conditionally redirect to the default view.

        If the branch listing requests the default listing, redirect to the
        default view for the product.
        """
        ProductBranchListingView.initialize(self)
        if self.sort_by == BranchListingSort.DEFAULT:
            redirect_url = canonical_url(self.context)
            widget = self.widgets['lifecycle']
            if widget.hasValidInput():
                redirect_url += (
                    '?field.lifecycle=' + widget.getInputValue().name)
            self.request.response.redirect(redirect_url)

    @property
    def initial_values(self):
        return {
            'lifecycle': BranchLifecycleStatusFilter.CURRENT,
            'sort_by': BranchListingSort.LIFECYCLE,
            }


class ProductActiveReviewsView(BranchMergeProposalListingView):
    """Branch merge proposals for the product that are needing review."""

    extra_columns = ['date_review_requested', 'vote_summary']
    _queue_status = [BranchMergeProposalStatus.NEEDS_REVIEW]

    @property
    def heading(self):
        return "Active code reviews for %s" % self.context.displayname

    @property
    def no_proposal_message(self):
        """Shown when there is no table to show."""
        return "%s has no active code reviews." % self.context.displayname


class ProductApprovedMergesView(BranchMergeProposalListingView):
    """Branch merge proposals for the product that have been approved."""

    extra_columns = ['date_reviewed']
    _queue_status = [BranchMergeProposalStatus.CODE_APPROVED]

    @property
    def heading(self):
        return "Approved merges for %s" % self.context.displayname

    @property
    def no_proposal_message(self):
        """Shown when there is no table to show."""
        return "%s has no approved merges." % self.context.displayname
