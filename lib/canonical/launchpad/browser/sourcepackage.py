# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'SourcePackageNavigation',
    'SourcePackageFacets',
    'SourcePackageView',
    'SourcePackageBugsView']

# Python standard library imports
import cgi
import re

from zope.component import getUtility
from zope.app.form.interfaces import IInputWidget
from zope.app import zapi

from canonical.lp.batching import BatchNavigator
from canonical.lp.dbschema import PackagePublishingPocket
from canonical.launchpad import helpers
from canonical.launchpad.interfaces import (
    IPOTemplateSet, IPackaging, ICountry, ISourcePackage)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.browser.potemplate import POTemplateView
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.browser.packagerelationship import (
    PackageRelationship)

from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, ApplicationMenu, enabled_with_permission,
    structured, GetitemNavigation, stepto, redirection)

from apt_pkg import ParseSrcDepends


class SourcePackageNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = ISourcePackage

    def breadcrumb(self):
        return self.context.name

    @stepto('+pots')
    def pots(self):
        potemplateset = getUtility(IPOTemplateSet)
        return potemplateset.getSubset(
                   distrorelease=self.context.distrorelease,
                   sourcepackagename=self.context.sourcepackagename)

    @stepto('+filebug')
    def filebug(self):
        """Redirect to the IDistributionSourcePackage +filebug page."""
        sourcepackage = self.context
        distro_sourcepackage = sourcepackage.distribution.getSourcePackage(
            sourcepackage.name)

        return redirection(canonical_url(distro_sourcepackage) + "/+filebug")


def linkify_changelog(changelog, sourcepkgnametxt):
    if changelog is None:
        return changelog
    changelog = cgi.escape(changelog)
    # XXX cprov 20060207: use re.match and fmt:url instead of this nasty
    # url builder. Also we need an specification describing the syntax for
    # changelog linkification and processing (mostly bug interface),
    # bug # 30817
    changelog = re.sub(r'%s \(([^)]+)\)' % re.escape(sourcepkgnametxt),
                       r'%s (<a href="\1">\1</a>)' % sourcepkgnametxt,
                       changelog)
    return changelog


class SourcePackageFacets(StandardLaunchpadFacets):

    usedfor = ISourcePackage
    enable_only = ['overview', 'bugs', 'support', 'translations']

    def support(self):
        link = StandardLaunchpadFacets.support(self)
        link.enabled = True
        return link


class SourcePackageOverviewMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'overview'
    links = ['hct', 'changelog', 'builds']

    def hct(self):
        text = structured(
            '<abbr title="Hypothetical Changeset Tool">HCT</abbr> status')
        return Link('+hctstatus', text, icon='info')

    def changelog(self):
        return Link('+changelog', 'Change Log', icon='list')

    def upstream(self):
        return Link('+packaging', 'Edit Upstream Link', icon='edit')

    def builds(self):
        text = 'View Builds'
        return Link('+builds', text, icon='info')


class SourcePackageBugsMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'bugs'
    links = ['reportbug']

    def reportbug(self):
        text = 'Report a Bug'
        return Link('+filebug', text, icon='add')


class SourcePackageSupportMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'support'
    links = ['addticket', 'gethelp']

    def gethelp(self):
        return Link('+gethelp', 'Help and Support Options', icon='info')

    def addticket(self):
        return Link('+addticket', 'Request Support', icon='add')


class SourcePackageTranslationsMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'translations'
    links = ['help', 'templates']

    def help(self):
        return Link('+translate', 'How You Can Help', icon='info')

    @enabled_with_permission('launchpad.Edit')
    def templates(self):
        return Link('+potemplatenames', 'Edit Template Names', icon='edit')


class SourcePackageView(BuildRecordsView):

    def initialize(self):
        # lets add a widget for the product series to which this package is
        # mapped in the Packaging table
        raw_field = IPackaging['productseries']
        bound_field = raw_field.bind(self.context)
        self.productseries_widget = zapi.getViewProviding(bound_field,
            IInputWidget, self.request)
        self.productseries_widget.setRenderedValue(self.context.productseries)
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.languages = helpers.request_languages(self.request)
        self.status_message = None
        self.processForm()

    def processForm(self):
        # look for an update to any of the things we track
        form = self.request.form
        if form.has_key('packaging'):
            if self.productseries_widget.hasValidInput():
                new_ps = self.productseries_widget.getInputValue()
                # we need to create or update the packaging
                self.context.setPackaging(new_ps, self.user)
                self.productseries_widget.setRenderedValue(new_ps)
                self.status_message = 'Upstream branch updated, thank you!'
            else:
                self.status_message = 'Invalid upstream branch given.'

    def published_by_pocket(self):
        """This morfs the results of ISourcePackage.published_by_pocket into
        something easier to parse from a page template. It becomes a list of
        dictionaries, sorted in dbschema item order, each representing a
        pocket and the packages in it."""
        result = []
        thedict = self.context.published_by_pocket
        for pocket in PackagePublishingPocket.items:
            newdict = {'pocketdetails': pocket}
            newdict['packages'] = thedict[pocket]
            result.append(newdict)
        return result

    def binaries(self):
        """Format binary packages into binarypackagename and archtags"""

        all_arch = [] # all archtag in this distrorelease
        for arch in self.context.distrorelease.architectures:
            all_arch.append(arch.architecturetag)
        all_arch.sort()

        bins = self.context.currentrelease.binaries

        results = {}

        for bin in bins:
            if bin.name not in results.keys():
                if not bin.architecturespecific:
                    results[bin.name] = all_arch
                else:
                    results[bin.name] = \
                             [bin.build.distroarchrelease.architecturetag]
            else:
                if bin.architecturespecific:
                    results[bin.name].append(\
                                bin.build.distroarchrelease.architecturetag)
                    results[bin.name].sort()

        return results

    def builddepends(self):
        builddepends = self.context.currentrelease.builddepends

        if not builddepends:
            return []

        relationships = [L[0] for L in ParseSrcDepends(builddepends)]
        return [
            PackageRelationship(name, signal, version)
            for name, version, signal in relationships
            ]

    def builddependsindep(self):
        builddependsindep = self.context.currentrelease.builddependsindep

        if not builddependsindep:
            return []

        relationships = [L[0] for L in ParseSrcDepends(builddependsindep)]
        return [
            PackageRelationship(name, signal, version)
            for name, version, signal in relationships
            ]

    def has_build_depends(self):
        return self.context.currentrelease.builddependsindep or \
            self.context.currentrelease.builddepends

    def linkified_changelog(self):
        return linkify_changelog(
            self.context.changelog, self.context.sourcepackagename.name)

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def templateviews(self):
        """Return the view class of the IPOTemplate associated with the context.
        """
        templateview_list = [POTemplateView(template, self.request)
                for template in self.context.currentpotemplates]

        # Initialize the views.
        for templateview in templateview_list:
            templateview.initialize()

        return templateview_list

    def potemplatenames(self):
        potemplates = self.context.potemplates
        potemplatenames = set([p.potemplatename for p in potemplates])
        return sorted(potemplatenames, key=lambda item: item.name)


class SourcePackageBugsView:

    def __init__(self, context, request):
        self.context = context
        self.request = request

        results = self.bugtask_search()
        self.batchnav = BatchNavigator(results, request)

    def bugtask_search(self):
        return self.context.bugs

    def task_columns(self):
        return [
            "id", "title", "status", "priority", "severity",
            "submittedon", "submittedby", "assignedto", "actions"]
