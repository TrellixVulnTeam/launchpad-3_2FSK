# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Browser views for sourcepackages."""

__metaclass__ = type

__all__ = [
    'SourcePackageNavigation',
    'SourcePackageSOP',
    'SourcePackageFacets',
    'SourcePackageView',
    'linkify_changelog'
    ]

# Python standard library imports
import cgi
import re
from apt_pkg import ParseSrcDepends

from zope.component import getUtility
from zope.app.form.interfaces import IInputWidget
from zope.app import zapi

from canonical.lp.dbschema import PackagePublishingPocket

from canonical.launchpad import helpers
from canonical.launchpad.interfaces import (
    IPOTemplateSet, IPackaging, ICountry, ISourcePackage)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interfaces import TranslationUnavailable
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.browser.launchpad import StructuralObjectPresentation
from canonical.launchpad.browser.packagerelationship import (
    relationship_builder)
from canonical.launchpad.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetAnswersMenu)
from canonical.launchpad.browser.rosetta import TranslationsMixin

from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, ApplicationMenu, enabled_with_permission,
    GetitemNavigation, stepto, redirection)


class SourcePackageNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = ISourcePackage

    def breadcrumb(self):
        return self.context.name

    @stepto('+pots')
    def pots(self):
        potemplateset = getUtility(IPOTemplateSet)
        sourcepackage_pots = potemplateset.getSubset(
            distroseries=self.context.distroseries,
            sourcepackagename=self.context.sourcepackagename)

        if (self.context.distroseries.hide_all_translations and
            not check_permission('launchpad.Admin', sourcepackage_pots)):
            raise TranslationUnavailable(
                'Translation updates are in progress. Only administrators '
                'may view translations for this source package.')

        return sourcepackage_pots

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


class SourcePackageSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return self.context.distribution.displayname + ' ' + \
               self.context.distroseries.version + ' source package:'

    def getMainHeading(self):
        return self.context.sourcepackagename

    def listChildren(self, num):
        # XXX mpt 20061004: Versions published, earliest first
        return []

    def countChildren(self):
        return 0

    def listAltChildren(self, num):
        return None

    def countAltChildren(self):
        raise NotImplementedError


class SourcePackageFacets(QuestionTargetFacetMixin, StandardLaunchpadFacets):

    usedfor = ISourcePackage
    enable_only = ['overview', 'bugs', 'answers', 'translations']


class SourcePackageOverviewMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'overview'
    links = ['packaging', 'edit_packaging', 'changelog', 'builds']

    def changelog(self):
        return Link('+changelog', 'View changelog', icon='list')

    def packaging(self):
        return Link('+packaging', 'Show upstream links', icon='info')

    def edit_packaging(self):
        return Link('+edit-packaging', 'Change upstream link', icon='edit')

    def builds(self):
        text = 'Show builds'
        return Link('+builds', text, icon='info')


class SourcePackageBugsMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'bugs'
    links = ['reportbug']

    def reportbug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='add')


class SourcePackageAnswersMenu(QuestionTargetAnswersMenu):

    usedfor = ISourcePackage
    facet = 'answers'

    links = QuestionTargetAnswersMenu.links + ['gethelp']

    def gethelp(self):
        return Link('+gethelp', 'Help and support options', icon='info')


class SourcePackageTranslationsMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'translations'
    links = ['help', 'templates']

    def help(self):
        return Link('+translate', 'How you can help', icon='info')

    @enabled_with_permission('launchpad.Edit')
    def templates(self):
        return Link('+potemplatenames', 'Edit template names', icon='edit')


class SourcePackageView(BuildRecordsView, TranslationsMixin):

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
                self.status_message = 'Upstream link updated, thank you!'
            else:
                self.status_message = 'Invalid series given.'

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
        results = {}
        all_arch = sorted([arch.architecturetag for arch in
                           self.context.distroseries.architectures])
        for bin in self.context.currentrelease.binaries:
            distroarchseries = bin.build.distroarchseries
            if bin.name not in results:
                results[bin.name] = []

            if bin.architecturespecific:
                results[bin.name].append(distroarchseries.architecturetag)
            else:
                results[bin.name] = all_arch
            results[bin.name].sort()

        return results

    def _relationship_parser(self, content):
        """Wrap the relationship_builder for SourcePackages.

        Define apt_pkg.ParseSrcDep as a relationship 'parser' and
        IDistroSeries.getBinaryPackage as 'getter'.
        """
        getter = self.context.distroseries.getBinaryPackage
        parser = ParseSrcDepends
        return relationship_builder(content, parser=parser, getter=getter)

    def builddepends(self):
        return self._relationship_parser(
            self.context.currentrelease.builddepends)

    def builddependsindep(self):
        return self._relationship_parser(
            self.context.currentrelease.builddependsindep)

    def has_build_depends(self):
        depends_indep = self.context.currentrelease.builddependsindep
        depends = self.context.currentrelease.builddepends
        if depends or depends_indep:
            return True
        return False

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def potemplatenames(self):
        potemplates = self.context.potemplates
        potemplatenames = set([p.potemplatename for p in potemplates])
        return sorted(potemplatenames, key=lambda item: item.name)

    def searchName(self):
        return False

