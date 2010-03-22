# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""View classes for `IProductSeries`."""

__metaclass__ = type

__all__ = [
    'get_series_branch_error',
    'ProductSeriesBreadcrumb',
    'ProductSeriesBugsMenu',
    'ProductSeriesDeleteView',
    'ProductSeriesEditView',
    'ProductSeriesFacets',
    'ProductSeriesFileBugRedirect',
    'ProductSeriesLinkBranchView',
    'ProductSeriesLinkBranchFromCodeView',
    'ProductSeriesNavigation',
    'ProductSeriesOverviewMenu',
    'ProductSeriesOverviewNavigationMenu',
    'ProductSeriesRdfView',
    'ProductSeriesReviewView',
    'ProductSeriesSetBranchView',
    'ProductSeriesSourceListView',
    'ProductSeriesSpecificationsMenu',
    'ProductSeriesUbuntuPackagingView',
    'ProductSeriesView',
    ]

import cgi
from operator import attrgetter

from BeautifulSoup import BeautifulSoup
from bzrlib.revision import NULL_REVISION

from zope.component import getUtility
from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.formlib import form
from zope.interface import Interface
from zope.schema import Choice
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from z3c.ptcompat import ViewPageTemplateFile

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _
from canonical.launchpad.fields import URIField
from canonical.launchpad.validators import LaunchpadValidationError
from lp.blueprints.browser.specificationtarget import (
    HasSpecificationsMenuMixin)
from lp.blueprints.interfaces.specification import (
    ISpecificationSet, SpecificationImplementationStatus)
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.helpers import browserLanguages
from lp.code.browser.branchref import BranchRef
from lp.code.enums import RevisionControlSystems
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.branchjob import IRosettaUploadJobSource
from lp.code.interfaces.codeimport import (
    ICodeImport, ICodeImportSet)
from lp.services.worlddata.interfaces.country import ICountry
from lp.bugs.interfaces.bugtask import IBugTaskSet
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.browser import StatusCount
from lp.registry.browser.structuralsubscription import (
    StructuralSubscriptionMenuMixin,
    StructuralSubscriptionTargetTraversalMixin)
from lp.registry.interfaces.packaging import (
    IPackaging, IPackagingUtil)
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.productserieslanguage import (
    IProductSeriesLanguageSet)
from lp.services.worlddata.interfaces.language import ILanguageSet
from canonical.launchpad.webapp import (
    ApplicationMenu, canonical_url, enabled_with_permission, LaunchpadView,
    Link, Navigation, NavigationMenu, StandardLaunchpadFacets, stepthrough,
    stepto)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.interfaces import (
    NotFoundError, UnexpectedFormData)
from canonical.launchpad.webapp.launchpadform import (
    action, custom_widget, LaunchpadEditFormView, LaunchpadFormView)
from canonical.launchpad.webapp.menu import structured
from canonical.widgets.itemswidgets import LaunchpadRadioWidget
from canonical.widgets.textwidgets import StrippedTextWidget, URIWidget

from lp.registry.browser import (
    MilestoneOverlayMixin, RegistryDeleteViewMixin)
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.productseries import IProductSeries

from lazr.enum import DBItem
from lazr.restful.interface import copy_field, use_template


def quote(text):
    """Escape and quote text."""
    return cgi.escape(text, quote=True)


class ProductSeriesNavigation(Navigation, BugTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin):
    """A class to navigate `IProductSeries` URLs."""
    usedfor = IProductSeries

    @stepto('.bzr')
    def dotbzr(self):
        """Return the series branch."""
        if self.context.branch:
            return BranchRef(self.context.branch)
        else:
            return None

    @stepto('+pots')
    def pots(self):
        """Return the series templates."""
        potemplateset = getUtility(IPOTemplateSet)
        return potemplateset.getSubset(productseries=self.context)

    @stepthrough('+lang')
    def traverse_lang(self, langcode):
        """Retrieve the ProductSeriesLanguage or a dummy if it is None."""
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
        psl_set = getUtility(IProductSeriesLanguageSet)
        psl = psl_set.getProductSeriesLanguage(self.context, lang)

        return psl

    def traverse(self, name):
        """See `INavigation`."""
        return self.context.getRelease(name)


class ProductSeriesBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IProductSeries`."""

    @property
    def text(self):
        """See `IBreadcrumb`."""
        return 'Series ' + self.context.name


class ProductSeriesFacets(StandardLaunchpadFacets):
    """A class that provides the series facets."""
    usedfor = IProductSeries
    enable_only = [
        'overview', 'branches', 'bugs', 'specifications', 'translations']

    def branches(self):
        """Return a link to view the branches related to this series."""
        # Override to go to the branches for the product.
        text = 'Branches'
        summary = 'View related branches of code'
        link = canonical_url(self.context.product, rootsite='code')
        return Link(link, text, summary=summary)


class ProductSeriesOverviewMenu(
    ApplicationMenu, StructuralSubscriptionMenuMixin):
    """The overview menu."""
    usedfor = IProductSeries
    facet = 'overview'
    links = [
        'edit', 'delete', 'driver', 'link_branch', 'branch_add', 'ubuntupkg',
        'create_milestone', 'create_release', 'rdf', 'subscribe',
        ]

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        """Return a link to edit this series."""
        text = 'Change details'
        summary = 'Edit this series'
        return Link('+edit', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def delete(self):
        """Return a link to delete this series."""
        text = 'Delete series'
        summary = "Delete this series and all it's dependent items."
        return Link('+delete', text, summary, icon='trash-icon')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        """Return a link to set the release manager."""
        text = 'Appoint release manager'
        summary = 'Someone with permission to set goals this series'
        return Link('+driver', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def link_branch(self):
        """Return a link to set the bazaar branch for this series."""
        if self.context.branch is None:
            text = 'Link to branch'
            icon = 'add'
            summary = 'Set the branch for this series'
        else:
            text = "Change branch"
            icon = 'edit'
            summary = 'Change the branch for this series'
        return Link('+linkbranch', text, summary, icon=icon)

    def branch_add(self):
        text = 'Register a branch'
        summary = "Register a new Bazaar branch for this series' project"
        return Link('+addbranch', text, summary, icon='add')

    @enabled_with_permission('launchpad.AnyPerson')
    def ubuntupkg(self):
        """Return a link to link this series to an ubuntu sourcepackage."""
        text = 'Link to Ubuntu package'
        return Link('+ubuntupkg', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def create_milestone(self):
        """Return a link to create a milestone."""
        text = 'Create milestone'
        summary = 'Register a new milestone for this series'
        return Link('+addmilestone', text, summary, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def create_release(self):
        """Return a link to create a release."""
        text = 'Create release'
        return Link('+addrelease', text, icon='add')

    def rdf(self):
        """Return a link to download the series RDF data."""
        text = 'Download RDF metadata'
        return Link('+rdf', text, icon='download')


class ProductSeriesBugsMenu(ApplicationMenu, StructuralSubscriptionMenuMixin):
    """The bugs menu."""
    usedfor = IProductSeries
    facet = 'bugs'
    links = (
        'new',
        'nominations',
        'subscribe',
        )

    def new(self):
        """Return a link to report a bug in this series."""
        return Link('+filebug', 'Report a bug', icon='add')

    def nominations(self):
        """Return a link to review bugs nominated for this series."""
        return Link('+nominations', 'Review nominations', icon='bug')


class ProductSeriesSpecificationsMenu(NavigationMenu,
                                      HasSpecificationsMenuMixin):
    """Specs menu for ProductSeries.

    This menu needs to keep track of whether we are showing all the
    specs, or just those that are approved/declined/proposed. It should
    allow you to change the set your are showing while keeping the basic
    view intact.
    """

    usedfor = IProductSeries
    facet = 'specifications'
    links = [
        'listall', 'assignments', 'setgoals', 'listdeclined',
        'new', 'register_sprint']


class ProductSeriesOverviewNavigationMenu(NavigationMenu):
    """Overview navigation menus for `IProductSeries` objects."""
    # Suppress the ProductOverviewNavigationMenu from showing on series,
    # release, and milestone pages.
    usedfor = IProductSeries
    facet = 'overview'
    links = ()


def get_series_branch_error(product, branch):
    """Check if the given branch is suitable for the given product.

    Returns an HTML error message on error, and None otherwise.
    """
    if branch.product != product:
        return structured(
            '<a href="%s">%s</a> is not a branch of <a href="%s">%s</a>.',
            canonical_url(branch),
            branch.unique_name,
            canonical_url(product),
            product.displayname)
    return None


class ProductSeriesView(LaunchpadView, MilestoneOverlayMixin):
    """A view to show a series with translations."""

    @property
    def page_title(self):
        """Return the HTML page title."""
        return self.context.title

    def requestCountry(self):
        """The country associated with the IP of the request."""
        return ICountry(self.request, None)

    def browserLanguages(self):
        """The languages the user's browser requested."""
        return browserLanguages(self.request)

    @property
    def request_import_link(self):
        """A link to the page for requesting a new code import."""
        return canonical_url(self.context.product, view_name='+new-import')

    @property
    def user_branch_visible(self):
        """Can the logged in user see the user branch."""
        branch = self.context.branch
        return (branch is not None and
                check_permission('launchpad.View', branch))

    @property
    def is_obsolete(self):
        """Return True if the series is OBSOLETE.

        Obsolete series do not need to display as much information as other
        series. Accessing private bugs is an expensive operation and showing
        them for obsolete series can be a problem if many series are being
        displayed.
        """
        return self.context.status == SeriesStatus.OBSOLETE

    @cachedproperty
    def bugtask_status_counts(self):
        """A list StatusCounts summarising the targeted bugtasks."""
        bugtaskset = getUtility(IBugTaskSet)
        status_id_counts = bugtaskset.getStatusCountsForProductSeries(
            self.user, self.context)
        status_counts = dict([(BugTaskStatus.items[status_id], count)
                              for status_id, count in status_id_counts])
        return [StatusCount(status, status_counts[status])
                for status in sorted(status_counts,
                                     key=attrgetter('sortkey'))]

    @cachedproperty
    def specification_status_counts(self):
        """A list StatusCounts summarising the targeted specification."""
        specification_set = getUtility(ISpecificationSet)
        status_id_counts = specification_set.getStatusCountsForProductSeries(
            self.context)
        SpecStatus = SpecificationImplementationStatus
        status_counts = dict([(SpecStatus.items[status_id], count)
                              for status_id, count in status_id_counts])
        return [StatusCount(status, status_counts[status])
                for status in sorted(status_counts,
                                     key=attrgetter('sortkey'))]

    @property
    def latest_release_with_download_files(self):
        for release in self.context.releases:
            if len(list(release.files)) > 0:
                return release
        return None


class ProductSeriesUbuntuPackagingView(LaunchpadFormView):

    schema = IPackaging
    field_names = ['sourcepackagename', 'distroseries']
    page_title = 'Ubuntu source packaging'
    label = page_title

    def __init__(self, context, request):
        """Set the static packaging information for this series."""
        super(ProductSeriesUbuntuPackagingView, self).__init__(
            context, request)
        self._ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self._ubuntu_series = self._ubuntu.currentseries
        try:
            package = self.context.getPackage(self._ubuntu_series)
            self.default_sourcepackagename = package.sourcepackagename
        except NotFoundError:
            # The package has never been set.
            self.default_sourcepackagename = None

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    cancel_url = next_url

    def setUpFields(self):
        """See `LaunchpadFormView`.

        The packaging is restricted to ubuntu series and the default value
        is the current development series.
        """
        super(ProductSeriesUbuntuPackagingView, self).setUpFields()
        series_vocabulary = SimpleVocabulary(
            [SimpleTerm(series, series.name, series.named_version)
             for series in self._ubuntu.series])
        choice = Choice(__name__='distroseries',
            title=_('Series'),
            default=self._ubuntu_series,
            vocabulary=series_vocabulary,
            description=_(
                "Series where this package is published. The current series "
                "is most important to the Ubuntu community."),
            required=True)
        field = form.Fields(choice, render_context=self.render_context)
        self.form_fields = self.form_fields.omit(choice.__name__) + field

    def setUpWidgets(self):
        """See `LaunchpadFormView`.

        Set the current `ISourcePackageName` as the default value.
        """
        super(ProductSeriesUbuntuPackagingView, self).setUpWidgets()
        if self.default_sourcepackagename is not None:
            widget = self.widgets.get('sourcepackagename')
            widget.setRenderedValue(self.default_sourcepackagename)

    @property
    def default_distroseries(self):
        """The current Ubuntu distroseries"""
        return self._ubuntu_series

    @property
    def ubuntu_history(self):
        return self.context.getPackagingInDistribution(
            self.default_distroseries.distribution)

    def validate(self, data):
        productseries = self.context
        sourcepackagename = data.get('sourcepackagename', None)
        distroseries = data.get('distroseries', self.default_distroseries)

        if sourcepackagename == self.default_sourcepackagename:
            # The data has not changed, so nothing else needs to be done.
            return

        if sourcepackagename is None:
            message = "You must choose the source package name."
            self.setFieldError('sourcepackagename', message)
        # Do not allow users it create links to unpublished Ubuntu packages.
        elif distroseries.distribution.full_functionality:
            source_package = distroseries.getSourcePackage(sourcepackagename)
            if source_package.currentrelease is None:
                message = ("The source package is not published in %s." %
                    distroseries.displayname)
                self.setFieldError('sourcepackagename', message)
        else:
            pass
        packaging_util = getUtility(IPackagingUtil)
        if packaging_util.packagingEntryExists(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries):
            # The series packaging conflicts with itself.
            message = _(
                "This series is already packaged in %s." %
                distroseries.displayname)
            self.setFieldError('sourcepackagename', message)
        elif packaging_util.packagingEntryExists(
            sourcepackagename=sourcepackagename,
            distroseries=distroseries):
            # The series package conflicts with another series.
            sourcepackage = distroseries.getSourcePackage(
                sourcepackagename.name)
            message = structured(
                'The <a href="%s">%s</a> package in %s is already linked to '
                'another series.' %
                (canonical_url(sourcepackage),
                 sourcepackagename.name,
                 distroseries.displayname))
            self.setFieldError('sourcepackagename', message)
        else:
            # The distroseries and sourcepackagename are not already linked
            # to this series, or any other series.
            pass


    @action('Update', name='continue')
    def continue_action(self, action, data):
        # set the packaging record for this productseries in the current
        # ubuntu series. if none exists, one will be created
        sourcepackagename = data['sourcepackagename']
        if self.default_sourcepackagename == sourcepackagename:
            # There is no change.
            return
        self.context.setPackaging(
            self.default_distroseries, sourcepackagename, self.user)


class ProductSeriesEditView(LaunchpadEditFormView):
    """A View to edit the attributes of a series."""
    schema = IProductSeries
    field_names = [
        'name', 'summary', 'status', 'branch', 'releasefileglob']
    custom_widget('summary', TextAreaWidget, height=7, width=62)
    custom_widget('releasefileglob', StrippedTextWidget, displayWidth=40)

    @property
    def label(self):
        """The form label."""
        return 'Edit %s %s series' % (
            self.context.product.displayname, self.context.name)

    @property
    def page_title(self):
        """The page title."""
        return self.label

    def validate(self, data):
        """See `LaunchpadFormView`."""
        branch = data.get('branch')
        if branch is not None:
            message = get_series_branch_error(self.context.product, branch)
            if message:
                self.setFieldError('branch', message)

    @action(_('Change'), name='change')
    def change_action(self, action, data):
        """Update the series."""
        self.updateContextFromData(data)

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)


class ProductSeriesDeleteView(RegistryDeleteViewMixin, LaunchpadEditFormView):
    """A view to remove a productseries from a product."""
    schema = IProductSeries
    field_names = []

    @property
    def label(self):
        """The form label."""
        return 'Delete %s %s series' % (
            self.context.product.displayname, self.context.name)

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @cachedproperty
    def milestones(self):
        """A list of all the series `IMilestone`s."""
        return self.context.all_milestones

    @cachedproperty
    def bugtasks(self):
        """A list of all `IBugTask`s targeted to this series."""
        all_bugtasks = self._getBugtasks(self.context)
        for milestone in self.milestones:
            all_bugtasks.extend(self._getBugtasks(milestone))
        return all_bugtasks

    @cachedproperty
    def specifications(self):
        """A list of all `ISpecification`s targeted to this series."""
        all_specifications = self._getSpecifications(self.context)
        for milestone in self.milestones:
            all_specifications.extend(self._getSpecifications(milestone))
        return all_specifications

    @cachedproperty
    def has_bugtasks_and_specifications(self):
        """Does the series have any targeted bugtasks or specifications."""
        return len(self.bugtasks) > 0 or len(self.specifications) > 0

    @property
    def has_linked_branch(self):
        """Is the series linked to a branch."""
        return self.context.branch is not None

    @cachedproperty
    def product_release_files(self):
        """A list of all `IProductReleaseFile`s that belong to this series."""
        all_files = []
        for milestone in self.milestones:
            all_files.extend(self._getProductReleaseFiles(milestone))
        return all_files

    @cachedproperty
    def has_linked_packages(self):
        """Is the series linked to source packages."""
        return self.context.packagings.count() > 0

    @cachedproperty
    def linked_packages_message(self):
        url = canonical_url(self.context.product, view_name="+packages")
        return (
            "You cannot delete a series that is linked to packages in "
            "distributions. You can remove the links from the "
            '<a href="%s">project packaging</a> page.' % url)

    development_focus_message = _(
        "You cannot delete a series that is the focus of "
        "development. Make another series the focus of development "
        "before deleting this one.")

    @cachedproperty
    def has_translations(self):
        """Does the series have translations?"""
        return self.context.potemplate_count > 0

    translations_message = (
        "This series cannot be deleted because it has translations.")

    @cachedproperty
    def can_delete(self):
        """Can this series be delete."""
        return not (
            self.context.is_development_focus
            or self.has_linked_packages or self.has_translations)

    def canDeleteAction(self, action):
        """Is the delete action available."""
        if self.context.is_development_focus:
            self.addError(self.development_focus_message)
        if self.has_linked_packages:
            self.addError(structured(self.linked_packages_message))
        if self.has_translations:
            self.addError(self.translations_message)
        return self.can_delete

    @action('Delete this Series', name='delete', condition=canDeleteAction)
    def delete_action(self, action, data):
        """Detach and delete associated objects and remove the series."""
        product = self.context.product
        name = self.context.name
        self._deleteProductSeries(self.context)
        self.request.response.addInfoNotification(
            "Series %s deleted." % name)
        self.next_url = canonical_url(product)


LINK_LP_BZR = 'link-lp-bzr'
CREATE_NEW = 'create-new'
IMPORT_EXTERNAL = 'import-external'


def _getBranchTypeVocabulary():
    items = (
        (LINK_LP_BZR,
         _("Link to a Bazaar branch already on Launchpad")),
        (CREATE_NEW,
         _("Create a new, empty branch in Launchpad and "
           "link to this series")),
        (IMPORT_EXTERNAL,
         _("Import a branch hosted somewhere else")),
        )
    terms = [
        SimpleTerm(name, name, label) for name, label in items]
    return SimpleVocabulary(terms)


class RevisionControlSystemsExtended(RevisionControlSystems):
    """External RCS plus Bazaar."""
    BZR = DBItem(99, """
        Bazaar

        External Bazaar branch.
        """)


class SetBranchForm(Interface):
    """The fields presented on the form for setting a branch."""

    use_template(
        ICodeImport,
        ['cvs_module'])

    rcs_type = Choice(title=_("Type of RCS"),
        required=False, vocabulary=RevisionControlSystemsExtended,
        description=_(
            "The version control system to import from. "))

    repo_url = URIField(
        title=_("Branch URL"), required=False,
        description=_("The URL of the branch."),
        allowed_schemes=["http", "https", "svn", "git"],
        allow_userinfo=False,
        allow_port=True,
        allow_query=False,
        allow_fragment=False,
        trailing_slash=False)

    branch_location = copy_field(
        IProductSeries['branch'],
        __name__='branch_location',
        title=_('Branch'),
        description=_(
            "The Bazaar branch for this series in Launchpad, "
            "if one exists."),
        )

    branch_type = Choice(
        title=_('Import type'),
        vocabulary=_getBranchTypeVocabulary(),
        description=_("The type of import"),
        required=True)

    branch_name = copy_field(
        IBranch['name'],
        __name__='branch_name',
        title=_('Branch name'),
        description=_(''),
        )

    branch_owner = copy_field(
        IBranch['owner'],
        __name__='branch_owner',
        title=_('Branch owner'),
        description=_(''),
        )


class ProductSeriesSetBranchView(LaunchpadFormView, ProductSeriesView):
    """The view to set a branch for the ProductSeries."""

    schema = SetBranchForm
    # Set for_input to True to ensure fields marked read-only will be editable
    # upon creation.
    for_input = True

    custom_widget('rcs_type', LaunchpadRadioWidget)
    custom_widget('branch_type', LaunchpadRadioWidget)
    initial_values = {
        'rcs_type': RevisionControlSystemsExtended.BZR,
        'branch_type': LINK_LP_BZR,
        }

    def setUpWidgets(self):
        super(ProductSeriesSetBranchView, self).setUpWidgets()

        # Extract the radio buttons from the rcs_type widget, so we can
        # display them separately in the form.
        soup = BeautifulSoup(self.widgets['rcs_type']())
        fields = soup.findAll('input')
        [cvs_button, svn_button, git_button, hg_button,
         bzr_button, empty_marker] = [
            field for field in fields
            if field.get('value') in ['CVS', 'BZR_SVN', 'GIT', 'HG',
                                      'BZR', '1']]
        # The following attributes are used only in the page template.
        self.rcs_type_cvs = str(cvs_button)
        self.rcs_type_svn = str(svn_button)
        self.rcs_type_git = str(git_button)
        self.rcs_type_hg = str(hg_button)
        self.rcs_type_bzr = str(bzr_button)
        self.rcs_type_emptymarker = str(empty_marker)

        soup = BeautifulSoup(self.widgets['branch_type']())
        fields = soup.findAll('input')
        (link_button, create_button, import_button, emptymarker) = fields
        self.branch_type_link = str(link_button)
        self.branch_type_create = str(create_button)
        self.branch_type_import = str(import_button)
        self.branch_type_emptymarker = str(emptymarker)

    def validate(self, data):
        import pdb; pdb.set_trace(); # DO NOT COMMIT
        extra_schemes = {
            RevisionControlSystemsExtended.BZR_SVN:['svn'],
            RevisionControlSystemsExtended.GIT:['git'],
            }
        rcs_type = data.get('rcs_type')
        schemes = ['http', 'https'] + extra_schemes.get(rcs_type, [])
        # Get the repository URL field.
        repo_url_field = self.form_fields['repo_url']
        repo_url_field.field.allowed_schemes = schemes
        repo_url = data.get('repo_url')
        if repo_url is not None:
            try:
                repo_url_field.field._validate(repo_url)
            except LaunchpadValidationError, lve:
                self.setFieldError('repo_url', str(lve))

        branch_type = data['branch_type']
        if branch_type == IMPORT_EXTERNAL:
            # RCS type is mandatory.
            # This condition should never happen since an initial value is set.
            if rcs_type is None:
                # The error shows but does not identify the widget.
                self.setFieldError(
                    'rcs_type',
                    'You must specify the type of RCS for the remote host.')
        elif branch_type == LINK_LP_BZR:
            if 'branch_location' not in data:
                self.setFieldError(
                    'branch_location',
                    'The branch location must be set.')

        if branch_type in [CREATE_NEW, IMPORT_EXTERNAL]:
            if 'branch_name' not in data:
                self.setFieldError(
                    'branch_name',
                    'The branch name must be set.')
            if 'branch_owner' not in data:
                self.setFieldError(
                    'branch_owner',
                    'The branch owner must be set.')


    @action(_('Update'), name='update')
    def update_action(self, action, data):
        import pdb; pdb.set_trace(); # DO NOT COMMIT
        print action
        print data
        self.next_url = canonical_url(self.context)
        branch_type = data.get('branch_type')
        if branch_type == LINK_LP_BZR:
            branch_location = data.get('branch_location')
            if branch_location is None:
                # TODO: need to stay on the page or move this to the
                # validator.
                self.request.response.addErrorNotification(
                    'No Launchpad branch specified.')
                self.next_url = None

            else:
                self.request.response.addInfoNotification(
                    'Launchpad branch %s linked to the series.' %
                    branch_location.unique_name)
        else:
            branch_name = data.get('branch_name')
            branch_owner = data.get('branch_owner')
            if branch_type == CREATE_NEW:
                pass
            elif branch_type == IMPORT_EXTERNAL:
                pass
            else:
                raise UnexpectedFormData(branch_type)

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)


class ProductSeriesLinkBranchView(LaunchpadEditFormView, ProductSeriesView):
    """View to set the bazaar branch for a product series."""

    schema = IProductSeries
    field_names = ['branch']

    @property
    def label(self):
        """The form label."""
        return 'Link an existing branch to %s %s series' % (
            self.context.product.displayname, self.context.name)

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @action(_('Update'), name='update')
    def update_action(self, action, data):
        """Update the branch attribute."""
        if data['branch'] != self.context.branch:
            self.updateContextFromData(data)
            # Request an initial upload of translation files.
            getUtility(IRosettaUploadJobSource).create(
                self.context.branch, NULL_REVISION)
        else:
            self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Series code location updated.')

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)


class ProductSeriesLinkBranchFromCodeView(ProductSeriesLinkBranchView):
    """Set the branch link from the code overview page."""

    @property
    def next_url(self):
        """Take the user back to the code overview page."""
        return canonical_url(self.context.product, rootsite="code")


class ProductSeriesReviewView(LaunchpadEditFormView):
    """A view to review and change the series `IProduct` and name."""
    schema = IProductSeries
    field_names = ['product', 'name']
    custom_widget('name', TextWidget, width=20)

    @property
    def label(self):
        """The form label."""
        return 'Administer %s %s series' % (
            self.context.product.displayname, self.context.name)

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @action(_('Change'), name='change')
    def change_action(self, action, data):
        """Update the series."""
        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            _('This Series has been changed'))
        self.next_url = canonical_url(self.context)


class ProductSeriesRdfView(object):
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile(
        '../templates/productseries-rdf.pt')

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
                                        'attachment; filename=%s-%s.rdf' % (
                                            self.context.product.name,
                                            self.context.name))
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


class ProductSeriesSourceListView(LaunchpadView):
    """A listing of all the running imports.

    See `ICodeImportSet.getActiveImports` for our definition of running.
    """

    page_title = 'Available code imports'
    label = page_title

    def initialize(self):
        """See `LaunchpadFormView`."""
        self.text = self.request.get('text')
        results = getUtility(ICodeImportSet).getActiveImports(text=self.text)

        self.batchnav = BatchNavigator(results, self.request)


class ProductSeriesFileBugRedirect(LaunchpadView):
    """Redirect to the product's +filebug page."""

    def initialize(self):
        """See `LaunchpadFormView`."""
        filebug_url = "%s/+filebug" % canonical_url(self.context.product)
        self.request.response.redirect(filebug_url)
