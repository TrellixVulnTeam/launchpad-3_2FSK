# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""View classes related to IDistroRelease."""

__metaclass__ = type

__all__ = [
    'DistroReleaseNavigation',
    'DistroReleaseFacets',
    'DistroReleaseView',
    'DistroReleaseAddView',
    ]

from zope.component import getUtility
from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.form.browser.add import AddView

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import helpers
from canonical.launchpad.webapp import (
    canonical_url, StandardLaunchpadFacets, Link, ApplicationMenu,
    enabled_with_permission, GetitemNavigation, stepthrough)

from canonical.launchpad.interfaces import (
    IDistroReleaseLanguageSet, IDistroRelease, ICountry, IDistroReleaseSet,
    ILaunchBag, ILanguageSet, NotFoundError)

from canonical.launchpad.browser.potemplate import POTemplateView
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView


class DistroReleaseNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = IDistroRelease

    def breadcrumb(self):
        return self.context.version

    @stepthrough('+lang')
    def traverse_lang(self, langcode):
        langset = getUtility(ILanguageSet)
        try:
            lang = langset[langcode]
        except IndexError:
            # Unknown language code.
            raise NotFoundError
        drlang = self.context.getDistroReleaseLanguage(lang)
        if drlang is not None:
            return drlang
        else:
            drlangset = getUtility(IDistroReleaseLanguageSet)
            return drlangset.getDummy(self.context, lang)

    @stepthrough('+source')
    def source(self, name):
        return self.context.getSourcePackage(name)

    # sabdfl 17/10/05 please keep this old location here for
    # LaunchpadIntegration on Breezy, unless you can figure out how to
    # redirect to the newer +source, defined above
    @stepthrough('+sources')
    def sources(self, name):
        return self.context.getSourcePackage(name)

    @stepthrough('+package')
    def package(self, name):
        return self.context.getBinaryPackage(name)


class DistroReleaseFacets(StandardLaunchpadFacets):

    usedfor = IDistroRelease
    enable_only = ['overview', 'bugs', 'specifications', 'translations']


class DistroReleaseOverviewMenu(ApplicationMenu):

    usedfor = IDistroRelease
    facet = 'overview'
    links = ['support', 'packaging', 'edit', 'reassign',
             'addport', 'admin', 'builds']

    def edit(self):
        text = 'Edit Details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def reassign(self):
        text = 'Change Drivers'
        return Link('+reassign', text, icon='edit')

    def packaging(self):
        text = 'Upstream Links'
        return Link('+packaging', text, icon='info')

    # A search link isn't needed because the distro release overview has a search form.

    def support(self):
        text = 'Request Support'
        url = canonical_url(self.context.distribution) + '/+addticket'
        return Link(url, text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def addport(self):
        text = 'Add Port'
        return Link('+addport', text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def admin(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')

    def builds(self):
        text = 'View Builds'
        return Link('+builds', text, icon='info')


class DistroReleaseBugsMenu(ApplicationMenu):

    usedfor = IDistroRelease
    facet = 'bugs'
    links = ['new', 'cve']

    def new(self):
        return Link('+filebug', 'Report a Bug', icon='add')

    def cve(self):
        return Link('+cve', 'CVE List', icon='cve')


class DistroReleaseSpecificationsMenu(ApplicationMenu):

    usedfor = IDistroRelease
    facet = 'specifications'
    links = ['roadmap', 'table', 'setgoals', 'listdeclined',]

    def listall(self):
        text = 'Show All'
        return Link('+specs?show=all', text, icon='info')

    def listapproved(self):
        text = 'Show Approved'
        return Link('+specs?show=accepted', text, icon='info')

    def listproposed(self):
        text = 'Show Proposed'
        return Link('+specs?show=proposed', text, icon='info')

    def listdeclined(self):
        text = 'Show Declined'
        summary = 'Show the goals which have been declined'
        return Link('+specs?show=declined', text, icon='info')

    def setgoals(self):
        text = 'Set Goals'
        summary = 'Approve or decline feature goals that have been proposed'
        return Link('+setgoals', text, icon='info')

    def table(self):
        text = 'Assignments'
        summary = 'Show the assignee, drafter and approver of these specs'
        return Link('+assignments', text, icon='info')

    def roadmap(self):
        text = 'Roadmap'
        summary = 'Show the sequence in which specs should be implemented'
        return Link('+roadmap', text, icon='info')


class DistroReleaseView(BuildRecordsView):

    def initialize(self):
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.text = self.request.form.get('text')
        self.matches = 0
        self._results = None

        self.searchrequested = False
        if self.text:
            self.searchrequested = True

    @cachedproperty
    def cached_packagings(self):
        # +packaging hits this many times, so avoid redoing the query
        # multiple times, in particular because it's gnarly.
        return list(self.context.packagings)

    @property
    def languages(self):
        return helpers.request_languages(self.request)

    def searchresults(self):
        """Try to find the packages in this distro release that match
        the given text, then present those as a list.
        """
        if self._results is None:
            self._results = self.context.searchPackages(self.text)
        self.matches = len(self._results)
        return self._results

    def requestDistroLangs(self):
        """Produce a set of DistroReleaseLanguage and
        DummyDistroReleaseLanguage objects for the languages the user
        currently is interested in (or which the users location and browser
        language prefs indicate might be interesting.
        """
        drlangs = []
        for language in self.languages:
            drlang = self.context.getDistroReleaseLanguageOrDummy(language)
            drlangs.append(drlang)
        return drlangs

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def templateviews(self):
        """Return the view class of the IPOTemplate associated with the context.
        """
        templateview_list = [
            POTemplateView(template, self.request)
            for template in self.context.currentpotemplates
            ]

        # Initialize the views.
        for templateview in templateview_list:
            templateview.initialize()

        return templateview_list

    def distroreleaselanguages(self):
        """Produces a list containing a DistroReleaseLanguage object for
        each language this distro has been translated into, and for each
        of the user's preferred languages. Where the release has no
        DistroReleaseLanguage for that language, we use a
        DummyDistroReleaseLanguage.
        """

        # find the existing DRLanguages
        drlangs = list(self.context.distroreleaselanguages)

        # make a set of the existing languages
        existing_languages = set([drl.language for drl in drlangs])

        # find all the preferred languages which are not in the set of
        # existing languages, and add a dummydistroreleaselanguage for each
        # of them
        drlangset = getUtility(IDistroReleaseLanguageSet)
        for lang in self.languages:
            if lang not in existing_languages:
                drl = drlangset.getDummy(self.context, lang)
                drlangs.append(drl)

        return sorted(drlangs, key=lambda a: a.language.englishname)

    @cachedproperty
    def unlinked_translatables(self):
        """Return the sourcepackages that lack a link to a productseries."""
        result = []
        for sp in self.context.translatable_sourcepackages:
            # We check direct_packaging below because we only want to
            # indicate if this source package is unlinked in this
            # distribution release (and not all of them); this is a
            # slight performance improvement.
            if (sp.direct_packaging is None or
                sp.direct_packaging.productseries is None):
                result.append(sp)
        return list(result)

    def redirectToDistroFileBug(self):
        """Redirect to the distribution's filebug page.

        Filing a bug on a distribution release is not directly
        permitted; we redirect to the distribution's file
        """
        distro_url = canonical_url(self.context.distribution)
        return self.request.response.redirect(distro_url + "/+filebug")


class DistroReleaseAddView(AddView):
    __used_for__ = IDistroRelease

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        """Create and add a new Distribution Release"""
        owner = getUtility(ILaunchBag).user

        assert owner is not None

        distrorelease = getUtility(IDistroReleaseSet).new(
            name = data['name'],
            displayname = data['displayname'],
            title = data['title'],
            summary = data['summary'],
            description = data['description'],
            version = data['version'],
            distribution = self.context,
            parentrelease = data['parentrelease'],
            owner = owner
            )
        notify(ObjectCreatedEvent(distrorelease))
        self._nextURL = data['name']
        return distrorelease

    def nextURL(self):
        return self._nextURL

