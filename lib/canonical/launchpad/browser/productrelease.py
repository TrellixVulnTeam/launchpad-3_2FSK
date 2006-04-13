# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'ProductReleaseNavigation',
    'ProductReleaseContextMenu',
    'ProductReleaseEditView',
    'ProductReleaseAddView',
    'ProductReleaseRdfView',
    ]

# zope3
from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.component import getUtility
from zope.app.form.browser.add import AddView
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile

# launchpad
from canonical.launchpad.interfaces import (
    IProductRelease, IPOTemplateSet, IProductReleaseSet, ICountry,
    ILaunchBag)

from canonical.launchpad.browser.editview import SQLObjectEditView

from canonical.launchpad import helpers
from canonical.launchpad.webapp import (
    Navigation, canonical_url, ContextMenu, Link, enabled_with_permission)


class ProductReleaseNavigation(Navigation):

    usedfor = IProductRelease

    def breadcrumb(self):
        return 'Release ' + self.context.version


class ProductReleaseContextMenu(ContextMenu):

    usedfor = IProductRelease
    links = ['edit', 'administer', 'download']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit Details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+review', text, icon='edit')

    def download(self):
        text = 'Download RDF Metadata'
        return Link('+rdf', text, icon='download')


class ProductReleaseAddView(AddView):

    __used_for__ = IProductRelease

    _nextURL = '.'

    def nextURL(self):
        return self._nextURL

    def createAndAdd(self, data):
        prset = getUtility(IProductReleaseSet)
        user = getUtility(ILaunchBag).user
        newrelease = prset.new(
            data['version'], data['productseries'], user, 
            codename=data['codename'], summary=data['summary'],
            description=data['description'], changelog=data['changelog'])
        self._nextURL = canonical_url(newrelease)
        notify(ObjectCreatedEvent(newrelease))


class ProductReleaseEditView(SQLObjectEditView):
    """Edit view for ProductRelease objects"""

    def changed(self):
        self.request.response.redirect('.')


class ProductReleaseRdfView(object):
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile('../templates/productrelease-rdf.pt')

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
                                        'attachment; filename=%s-%s-%s.rdf' % (
                                            self.context.product.name,
                                            self.context.productseries.name,
                                            self.context.version))
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata
