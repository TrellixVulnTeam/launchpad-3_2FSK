# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'DistributionNavigation',
    'DistributionSetNavigation',
    'DistributionFacets',
    'DistributionSpecificationsMenu',
    'DistributionView',
    'DistributionAllPackagesView',
    'DistributionEditView',
    'DistributionSetView',
    'DistributionSetAddView',
    'DistributionBugContactEditView',
    'DistributionArchiveMirrorsView',
    'DistributionReleaseMirrorsView',
    'DistributionDisabledMirrorsView',
    'DistributionUnofficialMirrorsView',
    'DistributionLaunchpadUsageEditView',
    ]

import operator

from zope.component import getUtility
from zope.app.form.browser.add import AddView
from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.security.interfaces import Unauthorized

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.launchpad.interfaces import (
    IDistribution, IDistributionSet, IPerson, IPublishedPackageSet,
    NotFoundError, ILaunchBag)
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.webapp import (
    action, ApplicationMenu, canonical_url, enabled_with_permission,
    GetitemNavigation, LaunchpadEditFormView, LaunchpadView, Link,
    redirection, RedirectionNavigation, StandardLaunchpadFacets,
    stepthrough, stepto)
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.lp.dbschema import DistributionReleaseStatus


class DistributionNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = IDistribution

    @redirection('+source', status=301)
    def redirect_source(self):
        return canonical_url(self.context)

    def breadcrumb(self):
        return self.context.displayname

    @stepto('+packages')
    def packages(self):
        return getUtility(IPublishedPackageSet)

    @stepthrough('+mirror')
    def traverse_mirrors(self, name):
        return self.context.getMirrorByName(name)

    @stepthrough('+source')
    def traverse_sources(self, name):
        return self.context.getSourcePackage(name)

    @stepthrough('+milestone')
    def traverse_milestone(self, name):
        return self.context.getMilestone(name)

    @stepthrough('+spec')
    def traverse_spec(self, name):
        return self.context.getSpecification(name)

    @stepthrough('+ticket')
    def traverse_ticket(self, name):
        # tickets should be ints
        try:
            ticket_id = int(name)
        except ValueError:
            raise NotFoundError
        return self.context.getTicket(ticket_id)

    redirection('+ticket', '+tickets')


class DistributionSetNavigation(RedirectionNavigation):

    usedfor = IDistributionSet

    def breadcrumb(self):
        return 'Distributions'

    redirection_root_url = config.launchpad.root_url

    def traverse(self, name):
        # Raise a 404 on an invalid distribution name
        if self.context.getByName(name) is None:
            raise NotFoundError(name)
        return RedirectionNavigation.traverse(self, name)


class DistributionFacets(StandardLaunchpadFacets):

    usedfor = IDistribution

    enable_only = ['overview', 'bugs', 'support', 'specifications',
                   'translations']

    def specifications(self):
        target = '+specs'
        text = 'Features'
        summary = 'Feature specifications for %s' % self.context.displayname
        return Link(target, text, summary)

    def support(self):
        target = '+tickets'
        text = 'Support'
        summary = (
            'Technical support requests for %s' % self.context.displayname)
        return Link(target, text, summary)


class DistributionOverviewMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'overview'
    links = ['edit', 'driver', 'search', 'allpkgs', 'members', 'mirror_admin',
             'reassign', 'addrelease', 'top_contributors', 'builds',
             'release_mirrors', 'archive_mirrors', 'disabled_mirrors',
             'unofficial_mirrors', 'newmirror', 'launchpad_usage',
             'upload_admin']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit Details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def driver(self):
        text = 'Appoint driver'
        summary = 'Someone with permission to set goals for all releases'
        return Link('+driver', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        text = 'Change Registrant'
        return Link('+reassign', text, icon='edit')

    def newmirror(self):
        text = 'Register a New Mirror'
        enabled = self.context.full_functionality
        return Link('+newmirror', text, enabled=enabled, icon='add')

    def top_contributors(self):
        text = 'Top Contributors'
        return Link('+topcontributors', text, icon='info')

    def release_mirrors(self):
        text = 'Show CD Mirrors'
        enabled = self.context.full_functionality
        return Link('+cdmirrors', text, enabled=enabled, icon='info')

    def archive_mirrors(self):
        text = 'Show Archive Mirrors'
        enabled = self.context.full_functionality
        return Link('+archivemirrors', text, enabled=enabled, icon='info')

    def disabled_mirrors(self):
        text = 'Show Disabled Mirrors'
        enabled = False
        user = getUtility(ILaunchBag).user
        if (self.context.full_functionality and user is not None and
            user.inTeam(self.context.mirror_admin)):
            enabled = True
        return Link('+disabledmirrors', text, enabled=enabled, icon='info')

    def unofficial_mirrors(self):
        text = 'Show Unofficial Mirrors'
        enabled = False
        user = getUtility(ILaunchBag).user
        if (self.context.full_functionality and user is not None and
            user.inTeam(self.context.mirror_admin)):
            enabled = True
        return Link('+unofficialmirrors', text, enabled=enabled, icon='info')

    def allpkgs(self):
        text = 'List All Packages'
        return Link('+allpackages', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def members(self):
        text = 'Change Members'
        return Link('+selectmemberteam', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def upload_admin(self):
        text = 'Change Upload Manager'
        summary = 'Someone with permission to manage uploads'
        return Link('+uploadadmin', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def mirror_admin(self):
        text = 'Change Mirror Admins'
        enabled = self.context.full_functionality
        return Link('+selectmirroradmins', text, enabled=enabled, icon='edit')

    def search(self):
        text = 'Search Packages'
        return Link('+search', text, icon='search')

    @enabled_with_permission('launchpad.Admin')
    def addrelease(self):
        text = 'Add Release'
        return Link('+addrelease', text, icon='add')

    def builds(self):
        text = 'Builds'
        return Link('+builds', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def launchpad_usage(self):
        text = 'Define Launchpad Usage'
        return Link('+launchpad', text, icon='edit')


class DistributionBugsMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'bugs'
    links = ['new', 'bugcontact', 'securitycontact', 'cve_list']

    def cve_list(self):
        text = 'CVE Reports'
        return Link('+cve', text, icon='cve')

    def new(self):
        text = 'Report a Bug'
        return Link('+filebug', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def bugcontact(self):
        text = 'Change Bug Contact'
        return Link('+bugcontact', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        text = 'Change Security Contact'
        return Link('+securitycontact', text, icon='edit')


class DistributionBountiesMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'bounties'
    links = ['new', 'link']

    def new(self):
        text = 'New Bounty'
        return Link('+addbounty', text, icon='add')

    def link(self):
        text = 'Link Existing Bounty'
        return Link('+linkbounty', text, icon='edit')


class DistributionSpecificationsMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'specifications'
    links = ['listall', 'doc', 'roadmap', 'assignments', 'new']

    def listall(self):
        text = 'List All'
        return Link('+specs?show=all', text, icon='info')

    def roadmap(self):
        text = 'Roadmap'
        return Link('+roadmap', text, icon='info')

    def assignments(self):
        text = 'Assignments'
        return Link('+assignments', text, icon='info')

    def doc(self):
        text = 'Documentation'
        summary = 'List all complete informational specifications'
        return Link('+documentation', text, summary,
            icon='info')

    def new(self):
        text = 'New Specification'
        return Link('+addspec', text, icon='add')


class DistributionSupportMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'support'
    links = ['new', 'support_contact']
    # XXX: MatthewPaulThomas, 2005-09-20
    # Add 'help' once +gethelp is implemented for a distribution

    def help(self):
        text = 'Help and Support Options'
        return Link('+gethelp', text, icon='info')

    def new(self):
        text = 'Request Support'
        return Link('+addticket', text, icon='add')

    def support_contact(self):
        text = 'Support Contact'
        return Link('+support-contact', text, icon='edit')


class DistributionTranslationsMenu(ApplicationMenu):

    usedfor = IDistribution
    facet = 'translations'
    links = ['edit']

    def edit(self):
        text = 'Change Translators'
        return Link('+changetranslators', text, icon='edit')


class DistributionView(BuildRecordsView):
    """Default Distribution view class."""

    def initialize(self):
        """Initialize template control fields.

        Also check if the search action was invoked and setup a batched
        list with the results if necessary.
        """
        # initialize control fields
        self.matches = 0

        # check if the user invoke search, if not dismiss
        self.text = self.request.form.get('text', None)
        if not self.text:
            self.search_requested = False
            return
        self.search_requested = True

        results = self.search_results()
        self.matches = len(results)
        if self.matches > 5:
            self.detailed = False
        else:
            self.detailed = True

        self.batchnav = BatchNavigator(results, self.request)

    @cachedproperty
    def translation_focus(self):
        """Return the IDistroRelease where the translators should work.

        If ther isn't a defined focus, we return latest release.
        """
        if self.context.translation_focus is None:
            return self.context.currentrelease
        else:
            return self.context.translation_focus

    def search_results(self):
        """Return IDistributionSourcePackages according given a text.

        Try to find the source packages in this distribution that match
        the given text.
        """
        return self.context.searchSourcePackages(self.text)

    def secondary_translatable_releases(self):
        """Return a list of IDistroRelease that aren't the translation_focus.

        It only includes the ones that are still supported.
        """
        releases = [
            release
            for release in self.context.releases
            if (release.releasestatus != DistributionReleaseStatus.OBSOLETE
                and (self.translation_focus is None or
                     self.translation_focus.id != release.id))
            ]

        return sorted(releases, key=operator.attrgetter('version'),
                      reverse=True)


class DistributionAllPackagesView(LaunchpadView):
    def initialize(self):
        results = self.context.source_package_caches
        self.batchnav = BatchNavigator(results, self.request)


class DistributionEditView(SQLObjectEditView):
    """View class that lets you edit a Distribution object.

    It redirects to the main distribution page after a successful edit.
    """

    def changed(self):
        self.request.response.redirect(canonical_url(self.context))


class DistributionLaunchpadUsageEditView(LaunchpadEditFormView):
    """View class for defining Launchpad usage."""

    schema = IDistribution
    field_names = ["official_rosetta", "official_malone"]
    label = "Describe Launchpad usage"

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)


class DistributionSetView:

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def count(self):
        return self.context.count()


class DistributionSetAddView(AddView):

    __used_for__ = IDistributionSet

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        # add the owner information for the distribution
        owner = IPerson(self.request.principal, None)
        if not owner:
            raise Unauthorized(
                "Need an authenticated user in order to create a"
                " distribution.")
        distribution = getUtility(IDistributionSet).new(
            name=data['name'],
            displayname=data['displayname'],
            title=data['title'],
            summary=data['summary'],
            description=data['description'],
            domainname=data['domainname'],
            members=data['members'],
            owner=owner)
        notify(ObjectCreatedEvent(distribution))
        self._nextURL = data['name']
        return distribution

    def nextURL(self):
        return self._nextURL


class DistributionBugContactEditView(SQLObjectEditView):
    """Browser view for editing the distribution bug contact."""
    def changed(self):
        """Redirect to the distribution page."""
        distribution = self.context
        contact_display_value = None

        if distribution.bugcontact:
            if distribution.bugcontact.preferredemail:
                contact_display_value = (
                    distribution.bugcontact.preferredemail.email)
            else:
                contact_display_value = distribution.bugcontact.displayname

        # The bug contact was set to a new person or team.
        if contact_display_value:
            self.request.response.addNotification(
                "Successfully changed the distribution bug contact to %s" %
                contact_display_value)
        else:
            # The bug contact was set to noone.
            self.request.response.addNotification(
                "Successfully cleared the distribution bug contact. This "
                "means that there is no longer a distro-wide contact for "
                "bugmail. You can, of course, set a distribution bug "
                "contact again whenever you want to.")

        self.request.response.redirect(canonical_url(distribution))


class DistributionMirrorsView(LaunchpadView):

    def _groupMirrorsByCountry(self, mirrors):
        """Given a list of mirrors, create and return list of dictionaries
        containing the country names and the list of mirrors on that country.

        This list is ordered by country name.
        """
        mirrors_by_country = {}
        for mirror in mirrors:
            mirrors = mirrors_by_country.setdefault(mirror.country.name, [])
            mirrors.append(mirror)
        return [dict(country=country, mirrors=mirrors)
                for country, mirrors in sorted(mirrors_by_country.items())]


class DistributionArchiveMirrorsView(DistributionMirrorsView):

    heading = 'Official Archive Mirrors'

    def getMirrorsGroupedByCountry(self):
        return self._groupMirrorsByCountry(self.context.archive_mirrors)


class DistributionReleaseMirrorsView(DistributionMirrorsView):

    heading = 'Official CD Mirrors'

    def getMirrorsGroupedByCountry(self):
        return self._groupMirrorsByCountry(self.context.release_mirrors)


class DistributionMirrorsAdminView(DistributionMirrorsView):

    def initialize(self):
        """Raise an Unauthorized exception if the user is not a member of this
        distribution's mirror_admin team.
        """
        # XXX: We don't want these pages to be public but we can't protect
        # them with launchpad.Edit because that would mean only people with
        # that permission on a Distribution would be able to see them. That's
        # why we have to do the permission check here.
        # -- Guilherme Salgado, 2006-06-16
        if not (self.user and self.user.inTeam(self.context.mirror_admin)):
            raise Unauthorized('Forbidden')


class DistributionUnofficialMirrorsView(DistributionMirrorsAdminView):

    heading = 'Unofficial Mirrors'

    def getMirrorsGroupedByCountry(self):
        return self._groupMirrorsByCountry(self.context.unofficial_mirrors)


class DistributionDisabledMirrorsView(DistributionMirrorsAdminView):

    heading = 'Disabled Mirrors'

    def getMirrorsGroupedByCountry(self):
        return self._groupMirrorsByCountry(self.context.disabled_mirrors)
