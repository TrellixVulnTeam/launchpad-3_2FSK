# Copyright 2004 Canonical Ltd.  All rights reserved.

"""Browser views for products."""

__metaclass__ = type

__all__ = [
    'ProductNavigation',
    'ProductSetNavigation',
    'ProductFacets',
    'ProductOverviewMenu',
    'ProductBugsMenu',
    'ProductSupportMenu',
    'ProductSpecificationsMenu',
    'ProductBountiesMenu',
    'ProductTranslationsMenu',
    'ProductSetContextMenu',
    'ProductView',
    'ProductEditView',
    'ProductSeriesAddView',
    'ProductRdfView',
    'ProductSetView',
    'ProductAddView',
    'ProductBugContactEditView'
    ]

from warnings import warn

import zope.security.interfaces
from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser.add import AddView
from zope.app.event.objectevent import ObjectCreatedEvent 
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile

from canonical.launchpad.interfaces import (
    IPerson, IPersonSet, IProduct, IProductSet, IProductSeries, ISourcePackage,
    ICountry, ICalendarOwner, NotFoundError)
from canonical.launchpad import helpers
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.potemplate import POTemplateView
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.cal import CalendarTraversalMixin
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, canonical_url, ContextMenu, ApplicationMenu,
    enabled_with_permission, structured, GetitemNavigation, Navigation,
    stepthrough)


class ProductNavigation(
    Navigation, BugTargetTraversalMixin, CalendarTraversalMixin):

    usedfor = IProduct

    def breadcrumb(self):
        return self.context.displayname

    @stepthrough('+spec')
    def traverse_spec(self, name):
        return self.context.getSpecification(name)

    @stepthrough('+series')
    def traverse_series(self, name):
        return self.context.getSeries(name)

    @stepthrough('+milestone')
    def traverse_milestone(self, name):
        return self.context.getMilestone(name)

    @stepthrough('+ticket')
    def traverse_ticket(self, name):
        # tickets should be ints
        try:
            ticket_num = int(name)
        except ValueError:
            raise NotFoundError
        return self.context.getTicket(ticket_num)

    def traverse(self, name):
        return self.context.getRelease(name)


class ProductSetNavigation(GetitemNavigation):

    usedfor = IProductSet

    def breadcrumb(self):
        return 'Products'


class ProductFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IProduct."""

    usedfor = IProduct

    enable_only = ['overview', 'bugs', 'support', 'bounties', 'specifications',
                   'translations', 'calendar']

    links = StandardLaunchpadFacets.links

    def overview(self):
        target = ''
        text = 'Overview'
        summary = 'General information about %s' % self.context.displayname
        return Link(target, text, summary)

    def bugs(self):
        target = '+bugs'
        text = 'Bugs'
        summary = 'Bugs reported about %s' % self.context.displayname
        return Link(target, text, summary)

    def support(self):
        target = '+tickets'
        text = 'Support'
        summary = (
            'Technical support requests for %s' % self.context.displayname)
        return Link(target, text, summary)

    def bounties(self):
        target = '+bounties'
        text = 'Bounties'
        summary = 'Bounties related to %s' % self.context.displayname
        return Link(target, text, summary)

    def specifications(self):
        target = '+specs'
        text = 'Specifications'
        summary = 'Feature specifications for %s' % self.context.displayname
        return Link(target, text, summary)

    def translations(self):
        target = '+translations'
        text = 'Translations'
        summary = 'Translations of %s in Rosetta' % self.context.displayname
        return Link(target, text, summary)

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
        'edit', 'reassign', 'distributions', 'packages',
        'branches', 'branch_add', 'series_add', 'milestone_add',
        'launchpad_usage', 'administer', 'rdf']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit Product Details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        text = 'Change Maintainer'
        return Link('+reassign', text, icon='edit')

    def distributions(self):
        text = 'Distributions'
        return Link('+distributions', text, icon='info')

    def packages(self):
        text = 'Packages'
        return Link('+packages', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def series_add(self):
        text = 'Add Release Series'
        return Link('+addseries', text, icon='add')

    def branches(self):
        summary = 'Bazaar Branches for %s' % self.context.displayname
        return Link('+branches', 'Branches', icon='info', summary=summary)

    def branch_add(self):
        text = 'Register Branch'
        return Link('+addbranch', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def milestone_add(self):
        text = 'Add Milestone'
        return Link('+addmilestone', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def launchpad_usage(self):
        text = 'Define Launchpad Usage'
        return Link('+launchpad', text, icon='edit')

    def rdf(self):
        text = structured(
            'Download <abbr title="Resource Description Framework">'
            'RDF</abbr> Metadata')
        return Link('+rdf', text, icon='download')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+review', text, icon='edit')


class ProductBugsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'bugs'
    links = ['filebug', 'editbugcontact']

    def filebug(self):
        text = 'Report a Bug'
        return Link('+filebug', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def editbugcontact(self):
        text = 'Change Bug Contact'
        return Link('+editbugcontact', text, icon='edit')


class ProductSupportMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'support'
    links = ['new']

    def new(self):
        text = 'Request Support'
        return Link('+addticket', text, icon='add')


class ProductSpecificationsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'specifications'
    links = ['roadmap', 'table', 'workload', 'new']

    def roadmap(self):
        text = 'Roadmap'
        return Link('+specplan', text, icon='info')

    def table(self):
        text = 'Assignments'
        return Link('+specstable', text, icon='info')

    def workload(self):
        text = 'Workload'
        return Link('+workload', text, icon='info')

    def new(self):
        text = 'Register a Specification'
        return Link('+addspec', text, icon='add')


class ProductBountiesMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'bounties'
    links = ['new', 'link']

    def new(self):
        text = 'Register a Bounty'
        return Link('+addbounty', text, icon='add')

    def link(self):
        text = 'Link Existing Bounty'
        return Link('+linkbounty', text, icon='edit')


class ProductTranslationsMenu(ApplicationMenu):

    usedfor = IProduct
    facet = 'translations'
    links = ['translators', 'edit']

    def translators(self):
        text = 'Change Translators'
        return Link('+changetranslators', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def edit(self):
        text = 'Edit Template Names'
        return Link('+potemplatenames', text, icon='edit')


def _sort_distros(a, b):
    """Put Ubuntu first, otherwise in alpha order."""
    if a['name'] == 'ubuntu':
        return -1
    return cmp(a['name'], b['name'])


class ProductSetContextMenu(ContextMenu):

    usedfor = IProductSet
    links = ['register', 'listall']

    def register(self):
        text = 'Register a Product'
        return Link('+new', text, icon='add')

    def listall(self):
        text = 'List All Products'
        return Link('+all', text, icon='list')


class ProductView:

    __used_for__ = IProduct

    def __init__(self, context, request):
        self.context = context
        self.product = context
        self.request = request
        self.form = request.form
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.languages = helpers.request_languages(request)
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
                        sourcepackage.distrorelease.name,
                        sourcepackage.name)
                    }

            elif IProductSeries.providedBy(translatable):
                productseries = translatable

                object_translatable = {
                    'title': productseries.title,
                    'potemplates': productseries.currentpotemplates,
                    'base_url': '/products/%s/+series/%s' %(
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

    def templateviews(self):
        """Return the view class of the IPOTemplate associated with the context.
        """
        target = self.context.primary_translatable
        if target is None:
            return []
        templateview_list = [
            POTemplateView(template, self.request)
            for template in target.currentpotemplates
            ]

        # Initialize the views.
        for templateview in templateview_list:
            templateview.initialize()

        return templateview_list

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
        for series in self.context.serieslist:
            for packaging in series.packagings:
                all_packagings.append(packaging)
        # we sort it so that the packagings will always be displayed in the
        # distrorelease version, then productseries name order
        all_packagings.sort(key=lambda a: (a.distrorelease.version,
            a.productseries.name, a.id))
        for packaging in all_packagings:
            if distros.has_key(packaging.distrorelease.distribution.name):
                distro = distros[packaging.distrorelease.distribution.name]
            else:
                distro = {}
                distro['name'] = packaging.distrorelease.distribution.name
                distro['title'] = packaging.distrorelease.distribution.title
                distro['packagings'] = []
                distros[packaging.distrorelease.distribution.name] = distro
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

        for series in self.context.serieslist:
            for potemplate in series.potemplates:
                potemplatenames.add(potemplate.potemplatename)

        return sorted(potemplatenames, key=lambda item: item.name)


class ProductEditView(SQLObjectEditView):
    """View class that lets you edit a Product object."""

    def changed(self):
        # If the name changed then the URL will have changed
        if self.context.active:
            self.request.response.redirect(canonical_url(self.context))
        else:
            productset = getUtility(IProductSet)
            self.request.response.redirect(canonical_url(productset))


class ProductSeriesAddView(AddView):
    """Generates a form to add new product release series"""

    series = None

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.form = request.form
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        """Handle a request to create a new series for this product."""
        # Ensure series name is lowercase
        self.series = self.context.newSeries(
            data["name"], data["displayname"], data["summary"])

    def nextURL(self):
        assert self.series
        return '+series/%s' % self.series.name


class ProductRdfView(object):
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


class ProductSetView:

    __used_for__ = IProductSet

    def __init__(self, context, request):

        self.context = context
        self.request = request
        form = self.request.form
        self.soyuz = form.get('soyuz')
        self.rosetta = form.get('rosetta')
        self.malone = form.get('malone')
        self.bazaar = form.get('bazaar')
        self.text = form.get('text')
        self.matches = 0
        self.results = None

        self.searchrequested = False
        if (self.text is not None or
            self.bazaar is not None or
            self.malone is not None or
            self.rosetta is not None or
            self.soyuz is not None):
            self.searchrequested = True

        if form.get('exact_name'):
            # If exact_name is supplied, we try and locate this name in
            # the ProductSet -- if we find it, bingo, redirect. This
            # argument can be optionally supplied by callers.
            try:
                product = self.context[self.text]
            except NotFoundError:
                product = None
            if product is not None:
                self.request.response.redirect(product.name)

    def searchresults(self):
        """Use searchtext to find the list of Products that match
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


class ProductAddView(AddView):

    __used_for__ = IProduct

    def __init__(self, context, request):
        fields = ["name",
                  "displayname",
                  "title",
                  "summary",
                  "description",
                  "project",
                  "homepageurl",
                  "sourceforgeproject",
                  "freshmeatproject",
                  "wikiurl",
                  "screenshotsurl",
                  "downloadurl",
                  "programminglang"]
        owner = IPerson(request.principal, None)
        if self.isButtSource(owner):
            # Buttsource members get it easy and are able to change this
            # stuff during the edit process; this saves time wasted on
            # getting to product/+admin.
            fields.insert(1, "owner")
            fields.append("reviewed")
        self.fieldNames = fields
        self.context = context
        self.request = request
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def isButtSource(self, owner):
        if owner is None:
            return False
        personset = getUtility(IPersonSet)
        buttsource = personset.getByName('buttsource')
        return owner.inTeam(buttsource)

    def createAndAdd(self, data):
        # add the owner information for the product
        owner = IPerson(self.request.principal, None)
        if owner is None:
            raise zope.security.interfaces.Unauthorized(
                "Need an authenticated Launchpad owner")
        if self.isButtSource(owner):
            owner = data["owner"]
            reviewed = data["reviewed"]
        else:
            # Zope makes sure these are never set, since they are not in
            # self.fieldNames
            assert "owner" not in data
            assert "reviewed" not in data
            reviewed = False
        productset = getUtility(IProductSet)
        product = productset.createProduct(owner=owner,
                                           reviewed=reviewed,
                                           name=data.get("name"),
                                           displayname=data.get("displayname"),
                                           title=data.get("title"),
                                           summary=data.get("summary"),
                                           description=data.get("description"),
                                           project=data.get("project"),
                                           homepageurl=data.get("homepageurl"),
                                           screenshotsurl=data.get("screenshotsurl"),
                                           wikiurl=data.get("wikiurl"),
                                           downloadurl=data.get("downloadurl"),
                                           freshmeatproject=data.get("freshmeatproject"),
                                           sourceforgeproject=data.get("sourceforgeproject"))
        notify(ObjectCreatedEvent(product))
        self._nextURL = data['name']
        return product

    def nextURL(self):
        return self._nextURL


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
                "product. You can set the bug contact again at any time.")

        self.request.response.redirect(canonical_url(product))
