# Copyright 2004-2008 Canonical Ltd.  All rights reserved.

"""Browser views for sourcepackages."""

__metaclass__ = type

__all__ = [
    'SourcePackageNavigation',
    'SourcePackageSOP',
    'SourcePackageFacets',
    'SourcePackageTranslationsExportView',
    'SourcePackageView',
    ]

from apt_pkg import ParseSrcDepends
from zope.component import getUtility
from zope.app.form.interfaces import IInputWidget
from zope.app import zapi

from canonical.launchpad import helpers
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.browser.packagerelationship import (
    relationship_builder)
from canonical.launchpad.browser.poexportrequest import BaseExportView
from canonical.launchpad.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetAnswersMenu)
from canonical.launchpad.browser.translations import TranslationsMixin
from canonical.launchpad.interfaces import (
    IPOTemplateSet, IPackaging, ICountry, ISourcePackage,
    PackagePublishingPocket)
from canonical.launchpad.webapp import (
    ApplicationMenu, enabled_with_permission, GetitemNavigation, Link,
    redirection, StandardLaunchpadFacets, stepto)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interfaces import TranslationUnavailable
from canonical.launchpad.webapp.menu import structured

from canonical.lazr.utils import smartquote


class SourcePackageNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = ISourcePackage

    def breadcrumb(self):
        return smartquote('"%s" package') % (self.context.name)

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


class SourcePackageAnswersMenu(QuestionTargetAnswersMenu):

    usedfor = ISourcePackage
    facet = 'answers'

    links = QuestionTargetAnswersMenu.links + ['gethelp']

    def gethelp(self):
        return Link('+gethelp', 'Help and support options', icon='info')


class SourcePackageTranslationsMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'translations'
    links = ['help', 'imports', 'translationdownload']

    def imports(self):
        text = 'See import queue'
        return Link('+imports', text)

    @enabled_with_permission('launchpad.ExpensiveRequest')
    def translationdownload(self):
        text = 'Download translations'
        enabled = bool(self.context.getCurrentTranslationTemplates())
        return Link('+export', text, icon='download', enabled=enabled)

    def help(self):
        return Link('+translate', 'How you can help', icon='info')


class SourcePackageTranslationsExportView(BaseExportView):
    """Request tarball export of all translations for source package.
    """

    def processForm(self):
        """Process form submission requesting translations export."""
        templates = self.context.getCurrentTranslationTemplates()
        pofiles = []
        for template in templates:
            pofiles += list(template.pofiles)
        return (templates, pofiles)

    def getDefaultFormat(self):
        templates = self.context.getCurrentTranslationTemplates()
        if not templates:
            return None
        format = templates[0].source_file_format
        for template in templates:
            if template.source_file_format != format:
                self.request.response.addInfoNotification(
                    "This package has templates with different native "
                    "file formats.  If you proceed, all translations will be "
                    "exported in the single format you specify.")
        return format


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
        self.error_message = None
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
                self.error_message = structured('Invalid series given.')

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

    @property
    def builddepends(self):
        return self._relationship_parser(
            self.context.currentrelease.builddepends)

    @property
    def builddependsindep(self):
        return self._relationship_parser(
            self.context.currentrelease.builddependsindep)

    @property
    def build_conflicts(self):
        return self._relationship_parser(
            self.context.currentrelease.build_conflicts)

    @property
    def build_conflicts_indep(self):
        return self._relationship_parser(
            self.context.currentrelease.build_conflicts_indep)

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    @property
    def search_name(self):
        return False

    @property
    def default_build_state(self):
        """Default build state for sourcepackage builds.

        This overrides the default that is set on BuildRecordsView."""
        # None maps to "all states". The reason we display all states on
        # this page is because it's unlikely that there will be so
        # many builds that the listing will be overwhelming.
        return None
