# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Project-related View Classes"""

__metaclass__ = type

__all__ = [
    'ProjectActionMenu',
    'ProjectAddProductView',
    'ProjectAddQuestionView',
    'ProjectAddView',
    'ProjectAnswersMenu',
    'ProjectBrandingView',
    'ProjectBugsMenu',
    'ProjectEditView',
    'ProjectFacets',
    'ProjectMaintainerReassignmentView',
    'ProjectNavigation',
    'ProjectOverviewMenu',
    'ProjectRdfView',
    'ProjectReviewView',
    'ProjectSeriesSpecificationsMenu',
    'ProjectSetBreadcrumb',
    'ProjectSetContextMenu',
    'ProjectSetNavigation',
    'ProjectSetNavigationMenu',
    'ProjectSetView',
    'ProjectSpecificationsMenu',
    'ProjectView',
    ]

from zope.lifecycleevent import ObjectCreatedEvent
from zope.app.form.browser import TextWidget
from zope.component import getUtility
from zope.event import notify
from zope.formlib import form
from zope.interface import implements, Interface
from zope.schema import Choice

from z3c.ptcompat import ViewPageTemplateFile

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _
from canonical.launchpad.webapp.interfaces import NotFoundError
from canonical.launchpad.webapp.menu import NavigationMenu
from lp.blueprints.browser.specificationtarget import (
    HasSpecificationsMenuMixin)
from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.projectgroup import (
    IProjectGroup, IProjectGroupSeries, IProjectGroupSet)
from lp.registry.browser.announcement import HasAnnouncementsView
from lp.registry.browser.menu import (
    IRegistryCollectionNavigationMenu, RegistryCollectionActionMenuBase)
from lp.registry.browser.product import (
    ProductAddView, ProjectAddStepOne, ProjectAddStepTwo)
from lp.registry.browser.branding import BrandingChangeView
from canonical.launchpad.browser.feeds import FeedsMixin
from lp.registry.browser.structuralsubscription import (
    StructuralSubscriptionTargetTraversalMixin)
from lp.answers.browser.question import QuestionAddView
from lp.answers.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionCollectionAnswersMenu)
from lp.registry.browser.objectreassignment import (
    ObjectReassignmentView)
from canonical.launchpad.fields import PillarAliases, PublicPersonChoice
from canonical.launchpad.webapp import (
    ApplicationMenu, ContextMenu, LaunchpadEditFormView, LaunchpadFormView,
    LaunchpadView, Link, Navigation, StandardLaunchpadFacets, action,
    canonical_url, custom_widget, enabled_with_permission, stepthrough,
    structured)
from canonical.launchpad.webapp.breadcrumb import Breadcrumb


class ProjectNavigation(Navigation,
    StructuralSubscriptionTargetTraversalMixin):

    usedfor = IProjectGroup

    def traverse(self, name):
        return self.context.getProduct(name)

    @stepthrough('+milestone')
    def traverse_milestone(self, name):
        return self.context.getMilestone(name)

    @stepthrough('+announcement')
    def traverse_announcement(self, name):
        return self.context.getAnnouncement(name)

    @stepthrough('+series')
    def traverse_series(self, series_name):
        return self.context.getSeries(series_name)


class ProjectSetNavigation(Navigation):

    usedfor = IProjectGroupSet

    def traverse(self, name):
        # Raise a 404 on an invalid project name
        project = self.context.getByName(name)
        if project is None:
            raise NotFoundError(name)
        return self.redirectSubTree(canonical_url(project))


class ProjectSetBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IProjectGroupSet`."""
    text = 'Project Groups'


class ProjectSetContextMenu(ContextMenu):

    usedfor = IProjectGroupSet
    links = ['register', 'listall']

    @enabled_with_permission('launchpad.ProjectReview')
    def register(self):
        text = 'Register a project group'
        return Link('+new', text, icon='add')

    def listall(self):
        text = 'List all project groups'
        return Link('+all', text, icon='list')


class ProjectFacets(QuestionTargetFacetMixin, StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IProjectGroup."""

    usedfor = IProjectGroup

    enable_only = ['overview', 'branches', 'bugs', 'specifications',
                   'answers', 'translations']

    def branches(self):
        text = 'Code'
        return Link('', text, enabled=self.context.hasProducts())

    def bugs(self):
        site = 'bugs'
        text = 'Bugs'
        return Link('', text, enabled=self.context.hasProducts(), site=site)

    def answers(self):
        site = 'answers'
        text = 'Answers'
        return Link('', text, enabled=self.context.hasProducts(), site=site)

    def specifications(self):
        site = 'blueprints'
        text = 'Blueprints'
        return Link('', text, enabled=self.context.hasProducts(), site=site)

    def translations(self):
        site = 'translations'
        text = 'Translations'
        return Link('', text, enabled=self.context.hasProducts(), site=site)


class ProjectAdminMenuMixin:

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+review', text, icon='edit')


class ProjectEditMenuMixin(ProjectAdminMenuMixin):

    @enabled_with_permission('launchpad.Edit')
    def branding(self):
        text = 'Change branding'
        return Link('+branding', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        text = 'Change maintainer'
        summary = 'Change the maintainer of this project group'
        return Link('+reassign', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        text = 'Appoint driver'
        summary = 'Appoint the driver of this project group'
        return Link('+driver', text, summary, icon='edit')


class ProjectOverviewMenu(ProjectEditMenuMixin, ApplicationMenu):

    usedfor = IProjectGroup
    facet = 'overview'
    links = [
        'branding', 'driver', 'reassign', 'top_contributors',
        'announce', 'announcements', 'branch_visibility', 'rdf',
        'new_product', 'administer', 'milestones']

    @enabled_with_permission('launchpad.Edit')
    def new_product(self):
        text = 'Register a project in %s' % self.context.displayname
        return Link('+newproduct', text, icon='add')

    def top_contributors(self):
        text = 'More contributors'
        return Link('+topcontributors', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def announce(self):
        text = 'Make announcement'
        summary = 'Publish an item of news for this project'
        return Link('+announce', text, summary, icon='add')

    def announcements(self):
        text = 'Read all announcements'
        enabled = bool(self.context.getAnnouncements())
        return Link('+announcements', text, icon='info', enabled=enabled)

    def milestones(self):
        text = 'See all milestones'
        return Link('+milestones', text, icon='info')

    def rdf(self):
        text = structured(
            'Download <abbr title="Resource Description Framework">'
            'RDF</abbr> metadata')
        return Link('+rdf', text, icon='download-icon')

    @enabled_with_permission('launchpad.Admin')
    def branch_visibility(self):
        text = 'Define branch visibility'
        return Link('+branchvisibility', text, icon='edit', site='mainsite')


class IProjectGroupActionMenu(Interface):
    """Marker interface for views that use ProjectActionMenu."""


class ProjectActionMenu(ProjectAdminMenuMixin, NavigationMenu):

    usedfor = IProjectGroupActionMenu
    facet = 'overview'
    title = 'Action menu'
    links = ('subscribe', 'edit', 'administer')

    # XXX: salgado, bug=412178, 2009-08-10: This should be shown in the +index
    # page of the project's bugs facet, but that would require too much work
    # and I just want to convert this page to 3.0, so I'll leave it here for
    # now.
    def subscribe(self):
        text = 'Subscribe to bug mail'
        return Link('+subscribe', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')


class IProjectGroupEditMenu(Interface):
    """A marker interface for the 'Change details' navigation menu."""


class ProjectEditNavigationMenu(NavigationMenu, ProjectEditMenuMixin):
    """A sub-menu for different aspects of editing a Project's details."""

    usedfor = IProjectGroupEditMenu
    facet = 'overview'
    title = 'Change project group'
    links = ('branding', 'reassign', 'driver', 'administer')


class ProjectSpecificationsMenu(NavigationMenu,
                                HasSpecificationsMenuMixin):
    usedfor = IProjectGroup
    facet = 'specifications'
    links = ['listall', 'doc', 'assignments', 'new', 'register_sprint']


class ProjectAnswersMenu(QuestionCollectionAnswersMenu):
    """Menu for the answers facet of projects."""

    usedfor = IProjectGroup
    facet = 'answers'
    links = QuestionCollectionAnswersMenu.links + ['new']

    def new(self):
        text = 'Ask a question'
        return Link('+addquestion', text, icon='add')


class ProjectBugsMenu(ApplicationMenu):

    usedfor = IProjectGroup
    facet = 'bugs'
    links = ['new', 'subscribe']

    def new(self):
        text = 'Report a Bug'
        return Link('+filebug', text, icon='add')

    def subscribe(self):
        text = 'Subscribe to bug mail'
        return Link('+subscribe', text, icon='edit')


class ProjectView(HasAnnouncementsView, FeedsMixin):
    implements(IProjectGroupActionMenu)

    @cachedproperty
    def has_many_projects(self):
        """Does the projectgroup have many sub projects.

        The number of sub projects can break the preferred layout so the
        template may want to plan for a long list.
        """
        return self.context.products.count() > 10


class ProjectEditView(LaunchpadEditFormView):
    """View class that lets you edit a Project object."""
    implements(IProjectGroupEditMenu)

    label = "Change project group details"
    schema = IProjectGroup
    field_names = [
        'name', 'displayname', 'title', 'summary', 'description',
        'bug_reporting_guidelines', 'bug_reported_acknowledgement',
        'homepageurl', 'bugtracker', 'sourceforgeproject',
        'freshmeatproject', 'wikiurl']


    @action('Change Details', name='change')
    def edit(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        if self.context.active:
            return canonical_url(self.context)
        else:
            # If the project is inactive, we can't traverse to it
            # anymore.
            return canonical_url(getUtility(IProjectGroupSet))


class ProjectReviewView(ProjectEditView):

    label = "Review upstream project group details"
    field_names = ['name', 'owner', 'active', 'reviewed']

    def setUpFields(self):
        """Setup the normal fields from the schema plus adds 'Registrant'.

        The registrant is normally a read-only field and thus does not have a
        proper widget created by default.  Even though it is read-only, admins
        need the ability to change it.
        """
        super(ProjectReviewView, self).setUpFields()
        self.form_fields = (self._createAliasesField() + self.form_fields
                            + self._createRegistrantField())

    def _createAliasesField(self):
        """Return a PillarAliases field for IProjectGroup.aliases."""
        return form.Fields(
            PillarAliases(
                __name__='aliases', title=_('Aliases'),
                description=_('Other names (separated by space) under which '
                              'this project group is known.'),
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
                              'project group.  Distinct from the current '
                              'owner.  This is historical data and should '
                              'not be changed without good cause.'),
                vocabulary='ValidPersonOrTeam',
                required=True,
                readonly=False,
                ),
            render_context=self.render_context
            )


class ProjectGroupAddStepOne(ProjectAddStepOne):
    """project/+newproduct view class for creating a new project.

    The new project will automatically be a part of the project group.
    """
    page_title = "Register a project in your project group"

    @cachedproperty
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Register a project in Launchpad as a part of %s' % (
            self.context.displayname)

    @property
    def _next_step(self):
        """See `ProjectAddStepOne`."""
        return ProjectGroupAddStepTwo


class ProjectGroupAddStepTwo(ProjectAddStepTwo):
    """Step 2 (of 2) in the +newproduct project add wizard."""

    page_title = "Register a project in your project group"

    def create_product(self, data):
        """Create the product from the user data."""
        return getUtility(IProductSet).createProduct(
            owner=self.user,
            name=data['name'],
            title=data['title'],
            summary=data['summary'],
            displayname=data['displayname'],
            licenses=data['licenses'],
            license_info=data['license_info'],
            project=self.context,
            )

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Register %s (%s) in Launchpad as a part of %s' % (
            self.request.form['displayname'], self.request.form['name'],
            self.context.displayname)


class ProjectAddProductView(ProductAddView):
    """The controlling view for project/+newproduct."""

    @property
    def first_step(self):
        """See `MultiStepView`."""
        return ProjectGroupAddStepOne


class ProjectSetNavigationMenu(RegistryCollectionActionMenuBase):
    """Action menu for project group index."""
    usedfor = IProjectGroupSet
    links = [
        'register_team',
        'register_project',
        'create_account',
        'register_project_group',
        'view_all_project_groups',
        ]

    @enabled_with_permission('launchpad.ProjectReview')
    def register_project_group(self):
        text = 'Register a project group'
        return Link('+new', text, icon='add')

    def view_all_project_groups(self):
        text = 'View all project groups'
        return Link('+all', text, icon='list')


class ProjectSetView(LaunchpadView):
    """View for project group index page."""

    implements(IRegistryCollectionNavigationMenu)

    page_title = "Project groups registered in Launchpad"

    def __init__(self, context, request):
        super(ProjectSetView, self).__init__(context, request)
        self.form = self.request.form_ng
        self.soyuz = self.form.getOne('soyuz', None)
        self.rosetta = self.form.getOne('rosetta', None)
        self.malone = self.form.getOne('malone', None)
        self.bazaar = self.form.getOne('bazaar', None)
        self.search_string = self.form.getOne('text', None)
        self.search_requested = False
        if (self.search_string is not None or
            self.bazaar is not None or
            self.malone is not None or
            self.rosetta is not None or
            self.soyuz is not None):
            self.search_requested = True
        self.results = None

    @cachedproperty
    def search_results(self):
        """Use searchtext to find the list of Projects that match
        and then present those as a list. Only do this the first
        time the method is called, otherwise return previous results.
        """
        self.results = self.context.search(
            text=self.search_string,
            bazaar=self.bazaar,
            malone=self.malone,
            rosetta=self.rosetta,
            soyuz=self.soyuz,
            search_products=True)
        return self.results

    @property
    def matches(self):
        """Number of matches."""
        if self.results is None:
            return 0
        else:
            return self.results.count()


class ProjectAddView(LaunchpadFormView):

    schema = IProjectGroup
    field_names = [
        'name',
        'displayname',
        'title',
        'summary',
        'description',
        'owner',
        'homepageurl',
        ]
    custom_widget('homepageurl', TextWidget, displayWidth=30)
    label = _('Register a project group with Launchpad')
    page_title = label
    project = None

    @action(_('Add'), name='add')
    def add_action(self, action, data):
        """Create the new Project from the form details."""
        self.project = getUtility(IProjectGroupSet).new(
            name=data['name'].lower().strip(),
            displayname=data['displayname'],
            title=data['title'],
            homepageurl=data['homepageurl'],
            summary=data['summary'],
            description=data['description'],
            owner=data['owner'],
            )
        notify(ObjectCreatedEvent(self.project))

    @property
    def next_url(self):
        assert self.project is not None, 'No project has been created'
        return canonical_url(self.project)


class ProjectBrandingView(BrandingChangeView):

    schema = IProjectGroup
    field_names = ['icon', 'logo', 'mugshot']


class ProjectRdfView(object):
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile(
        '../templates/project-rdf.pt')

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
        self.request.response.setHeader(
            'Content-Disposition',
            'attachment; filename=%s-project.rdf' % self.context.name)
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


class ProjectAddQuestionView(QuestionAddView):
    """View used to create a question from an IProjectGroup context."""

    search_field_names = ['product'] + QuestionAddView.search_field_names

    def setUpFields(self):
        # Add a 'product' field to the beginning of the form.
        QuestionAddView.setUpFields(self)
        self.form_fields = self.createProductField() + self.form_fields

    def setUpWidgets(self):
        fields = self._getFieldsForWidgets()
        # We need to initialize the widget in two phases because
        # the language vocabulary factory will try to access the product
        # widget to find the final context.
        self.widgets = form.setUpWidgets(
            fields.select('product'),
            self.prefix, self.context, self.request,
            data=self.initial_values, ignore_request=False)
        self.widgets += form.setUpWidgets(
            fields.omit('product'),
            self.prefix, self.context, self.request,
            data=self.initial_values, ignore_request=False)

    def createProductField(self):
        """Create a Choice field to select one of the project's products."""
        return form.Fields(
            Choice(
                __name__='product', vocabulary='ProjectProducts',
                title=_('Project'),
                description=_(
                    '${context} is a group of projects, which specific '
                    'project do you have a question about?',
                    mapping=dict(context=self.context.title)),
                required=True),
            render_context=self.render_context)

    @property
    def page_title(self):
        """The current page title."""
        return _('Ask a question about a project in ${project}',
                 mapping=dict(project=self.context.displayname))

    @property
    def question_target(self):
        """The IQuestionTarget to use is the selected product."""
        if self.widgets['product'].hasValidInput():
            return self.widgets['product'].getInputValue()
        else:
            return None


class ProjectSeriesSpecificationsMenu(ApplicationMenu):

    usedfor = IProjectGroupSeries
    facet = 'specifications'
    links = ['listall', 'doc', 'assignments']

    def listall(self):
        text = 'List all blueprints'
        return Link('+specs?show=all', text, icon='info')

    def doc(self):
        text = 'List documentation'
        summary = 'Show all completed informational specifications'
        return Link('+documentation', text, summary, icon="info")

    def assignments(self):
        text = 'Assignments'
        return Link('+assignments', text, icon='info')


class ProjectMaintainerReassignmentView(ObjectReassignmentView):
    """View class for changing project maintainer."""
    ownerOrMaintainerName = 'maintainer'
