# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Project-related View Classes"""

__metaclass__ = type

__all__ = [
    'ProjectNavigation',
    'ProjectSetNavigation',
    'ProjectSOP',
    'ProjectEditView',
    'ProjectAddProductView',
    'ProjectSetView',
    'ProjectAddView',
    'ProjectRdfView',
    ]

from urllib import quote as urlquote

from zope.component import getUtility
from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.form.browser import TextWidget
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.security.interfaces import Unauthorized

from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.interfaces import (
    ICalendarOwner, IPerson, IProduct, IProductSet, IProject, IProjectSet,
    ILaunchpadRoot, NotFoundError)
from canonical.launchpad import helpers
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.cal import CalendarTraversalMixin
from canonical.launchpad.browser.launchpad import StructuralObjectPresentation
from canonical.launchpad.webapp import (
    action, ApplicationMenu, canonical_url, ContextMenu, custom_widget,
    enabled_with_permission, LaunchpadEditFormView, Link, LaunchpadFormView,
    Navigation, RedirectionNavigation, StandardLaunchpadFacets, structured)


class ProjectNavigation(Navigation, CalendarTraversalMixin):

    usedfor = IProject

    def breadcrumb(self):
        return self.context.displayname

    def breadcrumb(self):
        return self.context.displayname

    def traverse(self, name):
        return self.context.getProduct(name)


class ProjectSetNavigation(RedirectionNavigation):

    usedfor = IProjectSet

    def breadcrumb(self):
        return 'Projects'

    @property
    def redirection_root_url(self):
        return canonical_url(getUtility(ILaunchpadRoot))

    def traverse(self, name):
        # Raise a 404 on an invalid project name
        if self.context.getByName(name) is None:
            raise NotFoundError(name)
        return RedirectionNavigation.traverse(self, name)


class ProjectSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        return self.context.title

    def listChildren(self, num):
        # XXX mpt 20061004: Products, alphabetically
        return []

    def countChildren(self):
        return 0

    def listAltChildren(self, num):
        return None

    def countAltChildren(self):
        raise NotImplementedError


class ProjectSetContextMenu(ContextMenu):

    usedfor = IProjectSet
    links = ['register', 'listall']

    @enabled_with_permission('launchpad.Admin')
    def register(self):
        text = 'Register a Project'
        return Link('+new', text, icon='add')

    def listall(self):
        text = 'List All Projects'
        return Link('+all', text, icon='list')


class ProjectFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IProject."""

    usedfor = IProject

    enable_only = ['overview', 'bugs', 'specifications']

    def calendar(self):
        target = '+calendar'
        text = 'Calendar'
        # only link to the calendar if it has been created
        enabled = ICalendarOwner(self.context).calendar is not None
        return Link(target, text, enabled=enabled)


class ProjectOverviewMenu(ApplicationMenu):

    usedfor = IProject
    facet = 'overview'
    links = ['edit', 'driver', 'reassign', 'rdf', 'changetranslators']

    def edit(self):
        text = 'Edit Project Details'
        return Link('+edit', text, icon='edit')

    def reassign(self):
        text = 'Change Admin'
        return Link('+reassign', text, icon='edit')

    def driver(self):
        text = 'Appoint driver'
        summary = 'Someone with permission to set goals for all products'
        return Link('+driver', text, summary, icon='edit')

    def rdf(self):
        text = structured(
            'Download <abbr title="Resource Description Framework">'
            'RDF</abbr> Metadata')
        return Link('+rdf', text, icon='download')

    def changetranslators(self):
        text = 'Change Translators'
        return Link('+changetranslators', text, icon='edit')


class ProjectBountiesMenu(ApplicationMenu):

    usedfor = IProject
    facet = 'bounties'
    links = ['new', 'link']

    def new(self):
        text = 'Register a Bounty'
        return Link('+addbounty', text, icon='add')

    def link(self):
        text = 'Link Existing Bounty'
        return Link('+linkbounty', text, icon='edit')


class ProjectSpecificationsMenu(ApplicationMenu):

    usedfor = IProject
    facet = 'specifications'
    links = ['listall', 'doc', 'roadmap', 'assignments',]

    def listall(self):
        text = 'List All'
        return Link('+specs?show=all', text, icon='info')

    def doc(self):
        text = 'Documentation'
        summary = 'Show all completed informational specifications'
        return Link('+documentation', text, summary, icon="info")

    def roadmap(self):
        text = 'Roadmap'
        return Link('+roadmap', text, icon='info')

    def assignments(self):
        text = 'Assignments'
        return Link('+assignments', text, icon='info')


class ProjectEditView(LaunchpadEditFormView):
    """View class that lets you edit a Project object."""

    schema = IProject
    field_names = [
        'name', 'displayname', 'title', 'summary', 'description',
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
            return canonical_url(getUtility(IProjectSet))


class ProjectAddProductView(LaunchpadFormView):

    schema = IProduct
    field_names = ['name', 'displayname', 'title', 'summary', 'description',
                   'homepageurl', 'sourceforgeproject', 'freshmeatproject',
                   'wikiurl', 'screenshotsurl', 'downloadurl',
                   'programminglang']
    custom_widget('homepageurl', TextWidget, displayWidth=30)
    custom_widget('screenshotsurl', TextWidget, displayWidth=30)
    custom_widget('wikiurl', TextWidget, displayWidth=30)
    custom_widget('downloadurl', TextWidget, displayWidth=30)

    label = "Register a product in this project"
    product = None

    @action(_('Add'), name='add')
    def add_action(self, action, data):
        # add the owner information for the product
        if not self.user:
            raise Unauthorized(
                "Need to have an authenticated user in order to create a bug"
                " on a product")
        # create the product
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
            project=self.context,
            owner=self.user)
        notify(ObjectCreatedEvent(self.product))

    @property
    def next_url(self):
        assert self.product is not None, 'No product has been created'
        return canonical_url(self.product)


class ProjectSetView(object):

    header = "Projects registered in Launchpad"

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.form = self.request.form
        self.soyuz = self.form.get('soyuz', None)
        self.rosetta = self.form.get('rosetta', None)
        self.malone = self.form.get('malone', None)
        self.bazaar = self.form.get('bazaar', None)
        self.text = self.form.get('text', None)
        self.searchrequested = False
        if (self.text is not None or
            self.bazaar is not None or
            self.malone is not None or
            self.rosetta is not None or
            self.soyuz is not None):
            self.searchrequested = True
        self.results = None
        self.matches = 0

    def searchresults(self):
        """Use searchtext to find the list of Projects that match
        and then present those as a list. Only do this the first
        time the method is called, otherwise return previous results.
        """
        if self.results is None:
            self.results = self.context.search(
                text=self.text,
                bazaar=self.bazaar,
                malone=self.malone,
                rosetta=self.rosetta,
                soyuz=self.soyuz)
        self.matches = self.results.count()
        return self.results


class ProjectAddView(LaunchpadFormView):

    schema = IProject
    field_names = ['name', 'displayname', 'title', 'summary',
                   'description', 'homepageurl']
    custom_widget('homepageurl', TextWidget, displayWidth=30)
    label = _('Register a project with Launchpad')
    project = None

    @action(_('Add'), name='add')
    def add_action(self, action, data):
        """Create the new Project from the form details."""
        self.project = getUtility(IProjectSet).new(
            name=data['name'].lower(),
            displayname=data['displayname'],
            title=data['title'],
            homepageurl=data['homepageurl'],
            summary=data['summary'],
            description=data['description'],
            owner=self.user)
        notify(ObjectCreatedEvent(self.project))

    @property
    def next_url(self):
        assert self.project is not None, 'No project has been created'
        return canonical_url(self.project)


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

