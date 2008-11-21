# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""View classes related to IDistroSeries."""

__metaclass__ = type

__all__ = [
    'DistroSeriesAddView',
    'DistroSeriesAdminView',
    'DistroSeriesBreadcrumbBuilder',
    'DistroSeriesEditView',
    'DistroSeriesFacets',
    'DistroSeriesFullLanguagePackRequestView',
    'DistroSeriesLanguagePackAdminView',
    'DistroSeriesNavigation',
    'DistroSeriesTranslationsAdminView',
    'DistroSeriesView',
    ]

from zope.lifecycleevent import ObjectCreatedEvent
from zope.app.form.browser.add import AddView
from zope.component import getUtility
from zope.event import notify
from zope.formlib import form
from zope.schema import Choice
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm

from canonical.cachedproperty import cachedproperty
from canonical.database.constants import UTC_NOW
from canonical.launchpad import _
from canonical.launchpad import helpers
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.browser.queue import QueueItemsView
from canonical.launchpad.browser.translations import TranslationsMixin
from canonical.launchpad.interfaces.country import ICountry
from canonical.launchpad.interfaces.distroseries import (
    DistroSeriesStatus, IDistroSeries)
from canonical.launchpad.interfaces.distroserieslanguage import (
    IDistroSeriesLanguageSet)
from canonical.launchpad.interfaces.language import ILanguageSet
from canonical.launchpad.interfaces.launchpad import (
    ILaunchBag, NotFoundError)
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, GetitemNavigation, action, custom_widget)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import BreadcrumbBuilder
from canonical.launchpad.webapp.interfaces import TranslationUnavailable
from canonical.launchpad.webapp.launchpadform import LaunchpadEditFormView
from canonical.launchpad.webapp.menu import (
    ApplicationMenu, Link, enabled_with_permission)
from canonical.launchpad.webapp.publisher import (
    canonical_url, stepthrough, stepto)
from canonical.widgets.itemswidgets import LaunchpadDropdownWidget


class DistroSeriesNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = IDistroSeries

    @stepthrough('+lang')
    def traverse_lang(self, langcode):
        """Retrieve the DistroSeriesLanguage or a dummy if one it is None."""
        # We do not want users to see the 'en' potemplate because
        # we store the messages we want to translate as English.
        if langcode == 'en':
            raise NotFoundError(langcode)

        langset = getUtility(ILanguageSet)
        try:
            lang = langset[langcode]
        except IndexError:
            # Unknown language code.
            raise NotFoundError
        distroserieslang = self.context.getDistroSeriesLanguage(lang)

        if distroserieslang is None:
            # There is no IDistroSeriesLanguage yet for this IDistroSeries,
            # but we still need to list it as an available language, so we
            # generate a dummy one so users have a chance to get to it in the
            # navigation and start adding translations for it.
            distroserieslangset = getUtility(IDistroSeriesLanguageSet)
            distroserieslang = distroserieslangset.getDummy(
                self.context, lang)

        if (self.context.hide_all_translations and
            not check_permission('launchpad.Admin', distroserieslang)):
            raise TranslationUnavailable(
                'Translation updates are in progress.  Only administrators '
                'may view translations for this distribution series.')

        return distroserieslang

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

    @stepto('+latest-full-language-pack')
    def latest_full_language_pack(self):
        if self.context.last_full_language_pack_exported is None:
            return None
        else:
            return self.context.last_full_language_pack_exported.file

    @stepto('+latest-delta-language-pack')
    def redirect_latest_delta_language_pack(self):
        if self.context.last_delta_language_pack_exported is None:
            return None
        else:
            return self.context.last_delta_language_pack_exported.file


class DistroSeriesBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `IDistroSeries`."""
    @property
    def text(self):
        return self.context.version


class DistroSeriesFacets(StandardLaunchpadFacets):

    usedfor = IDistroSeries
    enable_only = ['overview', 'bugs', 'specifications', 'translations']


class DistroSeriesOverviewMenu(ApplicationMenu):

    usedfor = IDistroSeries
    facet = 'overview'
    links = ['edit', 'reassign', 'driver', 'answers', 'packaging',
             'add_port', 'add_milestone', 'admin', 'builds', 'queue',
             'subscribe']

    @enabled_with_permission('launchpad.Admin')
    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        text = 'Appoint driver'
        summary = 'Someone with permission to set goals for this series'
        return Link('+driver', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def reassign(self):
        text = 'Change registrant'
        return Link('+reassign', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def add_milestone(self):
        text = 'Add milestone'
        summary = 'Register a new milestone for this series'
        return Link('+addmilestone', text, summary, icon='add')

    def packaging(self):
        text = 'Upstream links'
        return Link('+packaging', text, icon='info')

    # A search link isn't needed because the distro series overview
    # has a search form.

    def answers(self):
        text = 'Ask a question'
        url = canonical_url(self.context.distribution) + '/+addquestion'
        return Link(url, text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def add_port(self):
        text = 'Add architecture'
        return Link('+addport', text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def admin(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')

    def builds(self):
        text = 'Show builds'
        return Link('+builds', text, icon='info')

    def queue(self):
        text = 'Show uploads'
        return Link('+queue', text, icon='info')

    def subscribe(self):
        text = 'Subscribe to bug mail'
        return Link('+subscribe', text, icon='edit')


class DistroSeriesBugsMenu(ApplicationMenu):

    usedfor = IDistroSeries
    facet = 'bugs'
    links = (
        'cve',
        'nominations',
        'subscribe',
        )

    def cve(self):
        return Link('+cve', 'CVE reports', icon='cve')

    def nominations(self):
        return Link('+nominations', 'Review nominations', icon='bug')

    def subscribe(self):
        return Link('+subscribe', 'Subscribe to bug mail')


class DistroSeriesSpecificationsMenu(ApplicationMenu):

    usedfor = IDistroSeries
    facet = 'specifications'
    links = ['listall', 'table', 'setgoals', 'listdeclined', 'new']

    def listall(self):
        text = 'List all blueprints'
        return Link('+specs?show=all', text, icon='info')

    def listapproved(self):
        text = 'List approved blueprints'
        return Link('+specs?acceptance=accepted', text, icon='info')

    def listproposed(self):
        text = 'List proposed blueprints'
        return Link('+specs?acceptance=proposed', text, icon='info')

    def listdeclined(self):
        text = 'List declined blueprints'
        summary = 'Show the goals which have been declined'
        return Link('+specs?acceptance=declined', text, icon='info')

    def setgoals(self):
        text = 'Set series goals'
        summary = 'Approve or decline feature goals that have been proposed'
        return Link('+setgoals', text, icon='info')

    def table(self):
        text = 'Assignments'
        summary = 'Show the assignee, drafter and approver of these specs'
        return Link('+assignments', text, icon='info')

    def new(self):
        text = 'Register a blueprint'
        summary = 'Register a new blueprint for %s' % self.context.title
        return Link('+addspec', text, summary, icon='add')


class DistroSeriesTranslationsMenu(ApplicationMenu):

    usedfor = IDistroSeries
    facet = 'translations'
    links = [
        'admin', 'imports', 'language_packs', 'admin_language_packs',
        'full_language_pack_request']

    def imports(self):
        text = 'See import queue'
        return Link('+imports', text)

    @enabled_with_permission('launchpad.TranslationsAdmin')
    def admin(self):
        return Link('+admin', 'Administer translation options', icon='edit')

    def language_packs(self):
        return Link('+language-packs', 'See language packs')

    @enabled_with_permission('launchpad.TranslationsAdmin')
    def admin_language_packs(self):
        return Link(
            '+admin-language-packs', 'Administer language packs', icon='edit')

    @enabled_with_permission('launchpad.LanguagePacksAdmin')
    def full_language_pack_request(self):
        return Link(
            '+full-language-pack-request',
            'Request a full language pack export')


class DistroSeriesView(BuildRecordsView, QueueItemsView, TranslationsMixin):

    def initialize(self):
        self.text = self.request.form.get('text')
        self.matches = 0
        self._results = None

        self.searchrequested = False
        if self.text:
            self.searchrequested = True
            results = self.searchresults()
            self.matches = results.count()
            if self.matches > 5:
                self.detailed = False
            else:
                self.detailed = True

            self.batchnav = BatchNavigator(results, self.request)

        self.displayname = '%s %s' % (
            self.context.distribution.displayname,
            self.context.version)

        self.label = 'Language packs for %s' % self.displayname

    @cachedproperty
    def cached_packagings(self):
        # +packaging hits this many times, so avoid redoing the query
        # multiple times, in particular because it's gnarly.
        return list(self.context.packagings)

    @cachedproperty
    def unused_language_packs(self):
        unused_language_packs = helpers.shortlist(self.context.language_packs)

        if self.context.language_pack_base is not None:
            unused_language_packs.remove(self.context.language_pack_base)
        if self.context.language_pack_delta is not None:
            unused_language_packs.remove(self.context.language_pack_delta)
        if self.context.language_pack_proposed is not None:
            unused_language_packs.remove(self.context.language_pack_proposed)

        return unused_language_packs

    def searchresults(self):
        """Try to find the packages in this distro series that match
        the given text, then present those as a list.
        """
        if self._results is None:
            self._results = self.context.searchPackages(self.text)

        return self._results

    def requestDistroLangs(self):
        """Produce a set of DistroSeriesLanguage and
        DummyDistroSeriesLanguage objects for the languages the user
        currently is interested in (or which the users location and browser
        language prefs indicate might be interesting.
        """
        distroserieslangs = []
        for language in self.translatable_languages:
            distroserieslang = self.context.getDistroSeriesLanguageOrDummy(
                language)
            distroserieslangs.append(distroserieslang)
        return distroserieslangs

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    def distroserieslanguages(self):
        """Produces a list containing a DistroSeriesLanguage object for
        each language this distro has been translated into, and for each
        of the user's preferred languages. Where the series has no
        DistroSeriesLanguage for that language, we use a
        DummyDistroSeriesLanguage.
        """

        # find the existing DRLanguages
        distroserieslangs = list(self.context.distroserieslanguages)

        # make a set of the existing languages
        existing_languages = set([drl.language for drl in distroserieslangs])

        # find all the preferred languages which are not in the set of
        # existing languages, and add a dummydistroserieslanguage for each
        # of them
        distroserieslangset = getUtility(IDistroSeriesLanguageSet)
        for lang in self.translatable_languages:
            if lang not in existing_languages:
                distroserieslang = distroserieslangset.getDummy(
                    self.context, lang)
                distroserieslangs.append(distroserieslang)

        return sorted(distroserieslangs, key=lambda a: a.language.englishname)

    @cachedproperty
    def unlinked_translatables(self):
        """Return the sourcepackages that lack a link to a productseries."""
        return self.context.getUnlinkedTranslatableSourcePackages()

    def redirectToDistroFileBug(self):
        """Redirect to the distribution's filebug page.

        Filing a bug on a distribution series is not directly
        permitted; we redirect to the distribution's file
        """
        distro_url = canonical_url(self.context.distribution)
        return self.request.response.redirect(distro_url + "/+filebug")


class DistroSeriesEditView(LaunchpadEditFormView):
    """View class that lets you edit a DistroSeries object.

    It redirects to the main distroseries page after a successful edit.
    """
    schema = IDistroSeries
    field_names = ['displayname', 'title', 'summary', 'description']

    def initialize(self):
        """See `LaunchpadEditFormView`.

        Additionally set the 'label' attribute which will be used in the
        template.
        """
        LaunchpadEditFormView.initialize(self)
        self.label = 'Change %s details' % self.context.title

    @action("Change")
    def change_action(self, action, data):
        """Update the context and redirects to its overviw page."""
        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Your changes have been applied.')
        self.next_url = canonical_url(self.context)


class DistroSeriesAdminView(LaunchpadEditFormView):
    """View class for administering a DistroSeries object.

    It redirects to the main distroseries page after a successful edit.
    """
    schema = IDistroSeries
    field_names = ['name', 'version', 'changeslist']
    custom_widget('status', LaunchpadDropdownWidget)

    def initialize(self):
        """See `LaunchpadEditFormView`.

        Additionally set the 'label' attribute which will be used in the
        template.
        """
        LaunchpadEditFormView.initialize(self)
        self.label = 'Administer %s' % self.context.title

    def setUpFields(self):
        """Override `LaunchpadFormView`.

        In addition to setting schema fields, also initialize the
        'status' field. See `createStatusField` method.
        """
        LaunchpadEditFormView.setUpFields(self)
        self.form_fields = (
            self.form_fields + self.createStatusField())

    def createStatusField(self):
        """Create the 'status' field.

        Create the status vocabulary according the current distroseries
        status:
         * stable   -> CURRENT, SUPPORTED, OBSOLETE
         * unstable -> EXPERIMENTAL, DEVELOPMENT, FROZEN, FUTURE, CURRENT
        """
        stable_status = (
            DistroSeriesStatus.CURRENT,
            DistroSeriesStatus.SUPPORTED,
            DistroSeriesStatus.OBSOLETE,
            )

        if self.context.status not in stable_status:
            terms = [status for status in DistroSeriesStatus.items
                     if status not in stable_status]
            terms.append(DistroSeriesStatus.CURRENT)
        else:
            terms = stable_status

        status_vocabulary = SimpleVocabulary(
            [SimpleTerm(item, item.name, item.title) for item in terms])

        return form.Fields(
            Choice(__name__='status',
                   title=_('Status'),
                   vocabulary=status_vocabulary,
                   description=_("Select the the distroseries status."),
                   required=True))

    @action("Change")
    def change_action(self, action, data):
        """Update the context and redirects to its overviw page.

        Also, set 'datereleased' when a unstable distroseries is made
        CURRENT.
        """
        status = data.get('status')
        if (self.context.datereleased is None and
            status == DistroSeriesStatus.CURRENT):
            self.context.datereleased = UTC_NOW

        self.updateContextFromData(data)

        self.request.response.addInfoNotification(
            'Your changes have been applied.')
        self.next_url = canonical_url(self.context)


class DistroSeriesAddView(AddView):
    __used_for__ = IDistroSeries

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        """Create and add a new Distribution Series"""
        owner = getUtility(ILaunchBag).user

        assert owner is not None

        distroseries = self.context.newSeries(
            name = data['name'],
            displayname = data['displayname'],
            title = data['title'],
            summary = data['summary'],
            description = data['description'],
            version = data['version'],
            parent_series = data['parent_series'],
            owner = owner
            )
        notify(ObjectCreatedEvent(distroseries))
        self._nextURL = data['name']
        return distroseries

    def nextURL(self):
        return self._nextURL


class DistroSeriesTranslationsAdminView(LaunchpadEditFormView):
    schema = IDistroSeries

    field_names = ['hide_all_translations', 'defer_translation_imports']

    def initialize(self):
        LaunchpadEditFormView.initialize(self)
        self.label = 'Change translation options of %s' % self.context.title

    @action("Change")
    def change_action(self, action, data):
        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Your changes have been applied.')

        self.next_url = canonical_url(self.context)


class DistroSeriesLanguagePackAdminView(LaunchpadEditFormView):
    """Browser view to manage used language packs."""
    schema = IDistroSeries

    field_names = ['language_pack_base', 'language_pack_delta',
                   'language_pack_proposed']

    def initialize(self):
        LaunchpadEditFormView.initialize(self)
        self.label = 'Change language packs of %s' % self.context.title
        self.page_title = self.label

    @action("Change")
    def change_action(self, action, data):
        if ('language_pack_base' in data and
            data['language_pack_base'] != self.context.language_pack_base):
            # language_pack_base changed, the delta one must be invalidated.
            data['language_pack_delta'] = None

        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Your changes have been applied.')

        self.next_url = '%s/+language-packs' % canonical_url(self.context)


class DistroSeriesFullLanguagePackRequestView(LaunchpadEditFormView):
    """Browser view to store whether next export should be a full one."""
    schema = IDistroSeries

    field_names = ['language_pack_full_export_requested']

    def initialize(self):
        self.old_value = self.context.language_pack_full_export_requested
        LaunchpadEditFormView.initialize(self)
        self.label = 'Request a full language pack export of %s' % (
            self.context.title)
        self.page_title = self.label

    @action("Request")
    def request_action(self, action, data):
        self.updateContextFromData(data)
        if self.old_value != self.context.language_pack_full_export_requested:
            # There are changes.
            if self.context.language_pack_full_export_requested:
                self.request.response.addInfoNotification('''
Your request has been noted. Next language pack export will include all
available translations.
''')
            else:
                self.request.response.addInfoNotification('''
Your request has been noted. Next language pack export will be made relative
to the current base language pack.
''')
        else:
            self.request.response.addInfoNotification(
                "You didn't change anything.")

        self.next_url = '/'.join(
            [canonical_url(self.context), '+language-packs'])
