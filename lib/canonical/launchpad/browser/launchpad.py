# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Browser code for the launchpad application."""

__metaclass__ = type
__all__ = [
    'Breadcrumbs',
    'LoginStatus',
    'MaintenanceMessage',
    'MenuBox',
    'RosettaContextMenu',
    'MaloneContextMenu',
    'LaunchpadRootNavigation',
    'MaloneApplicationNavigation',
    'SoftTimeoutView',
    ]

import cgi
import urllib
import os.path
import time
from datetime import timedelta, datetime

from zope.app.datetimeutils import parseDatetimetz, tzinfo, DateTimeError
from zope.component import getUtility
from zope.security.interfaces import Unauthorized

import canonical.launchpad.layers
from canonical.config import config
from canonical.launchpad.helpers import intOrZero
from canonical.launchpad.interfaces import (
    ILaunchBag, ILaunchpadRoot, IRosettaApplication,
    IMaloneApplication, IProductSet, IShipItApplication, IPersonSet,
    IDistributionSet, ISourcePackageNameSet, IBinaryPackageNameSet,
    IProjectSet, ILoginTokenSet, IKarmaActionSet, IPOTemplateNameSet,
    IBazaarApplication, ICodeOfConductSet, IRegistryApplication,
    ISpecificationSet, ISprintSet, ITicketSet, IBuilderSet, IBountySet,
    ILaunchpadCelebrities, IBugSet, IBugTrackerSet, ICveSet,
    ITranslationImportQueue, ITranslationGroupSet)
from canonical.launchpad.components.cal import MergedCalendar
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, ContextMenu, Link, LaunchpadView, Navigation,
    stepto, canonical_url)

# XXX SteveAlexander, 2005-09-22, this is imported here because there is no
#     general timedelta to duration format adapter available.  This should
#     be factored out into a generally available adapter for both this
#     code and for TALES namespace code to use.
#     Same for MenuAPI.
from canonical.launchpad.webapp.tales import DurationFormatterAPI, MenuAPI


class MaloneApplicationNavigation(Navigation):

    usedfor = IMaloneApplication

    newlayer = canonical.launchpad.layers.MaloneLayer

    @stepto('bugs')
    def bugs(self):
        return getUtility(IBugSet)

    @stepto('bugtrackers')
    def bugtrackers(self):
        return getUtility(IBugTrackerSet)

    @stepto('cve')
    def cve(self):
        return getUtility(ICveSet)

    @stepto('distros')
    def distros(self):
        return getUtility(IDistributionSet)

    @stepto('projects')
    def projects(self):
        return getUtility(IProjectSet)

    @stepto('products')
    def products(self):
        return getUtility(IProductSet)

    def traverse(self, name):
        # Make /bugs/$bug.id, /bugs/$bug.name /malone/$bug.name and
        # /malone/$bug.id Just Work
        return getUtility(IBugSet).getByNameOrID(name)


class MenuBox(LaunchpadView):
    """View class that helps its template render the actions menu box.

    Nothing at all is rendered if there are no contextmenu items and also
    no applicationmenu items.

    If there is at least one item, the template is rendered.
    """

    usedfor = dict  # Really a TALES CONTEXTS object.

    def initialize(self):
        menuapi = MenuAPI(self.context)
        self.contextmenuitems = [
            link for link in menuapi.context() if link.enabled]
        self.applicationmenuitems = [
            link for link in menuapi.application() if link.enabled]

    def render(self):
        if not self.contextmenuitems and not self.applicationmenuitems:
            return ''
        else:
            return self.template()


class Breadcrumbs(LaunchpadView):
    """Page fragment to display the breadcrumbs text."""

    def render(self):
        """Render the breadcrumbs text.

        The breadcrumbs are taken from the request.breadcrumbs list.
        For each breadcrumb, breadcrumb.text is cgi escaped.  The last
        breadcrumb is made <strong>.
        """
        crumbs = list(self.request.breadcrumbs)
        if crumbs:
            # Discard the first breadcrumb, as we know it will be the
            # Launchpad one anyway.
            firstcrumb = crumbs.pop(0)
            assert firstcrumb.text == 'Launchpad'

        L = []
        firsturl = '/'
        firsttext = 'Launchpad'

        if not crumbs:
            L.append(
                '<li lpm:mid="root" class="item">'
                '<a href="%s">'
                '<img src="/@@/launchpad" alt="" /> %s'
                '</a>'
                '</li>'
                % (firsturl,
                   cgi.escape(firsttext)))
        else:
            L.append(
                '<li lpm:mid="root" class="item">'
                '<a href="%s">'
                '<img src="/@@/launchpad" alt="" /> %s'
                '</a>'
                '</li>'
                % (firsturl,
                   cgi.escape(firsttext)))

            #lastcrumb = crumbs.pop()

            for crumb in crumbs:
                # XXX: SteveAlexander, 2006-06-09, this is putting the
                #      full URL in as the lpm:mid.  We want just the path
                #      here instead.
                ##L.append('<li class="item" lpm:mid="%s/+menudata">'
                ##         '<a href="%s">%s</a>'
                ##         '</li>'
                ##         % (crumb.url, crumb.url, cgi.escape(crumb.text)))

                # Disable these menus for now.  To be re-enabled on the ui 1.0
                # branch.
                L.append('<li class="item">'
                         '<a href="%s">%s</a>'
                         '</li>'
                         % (crumb.url, cgi.escape(crumb.text)))

            #L.append(
            #    '<li class="item">'
            #    '<a href="%s">%s</a>'
            #    '</li>'
            #    % (lastcrumb.url, cgi.escape(lastcrumb.text)))
        return u'\n'.join(L)


class MaintenanceMessage:
    """Display a maintenance message if the control file is present and
    it contains a valid iso format time.

    The maintenance message shows the approximate time before launchpad will
    be taken offline for maintenance.

    The control file is +maintenancetime.txt in the launchpad root.

    If there is no maintenance message, an empty string is returned.

    If the maintenance time is too far in the future, then an empty string
    is returned.

    If the maintenance time is in the past, then the maintenance message says
    that Launchpad will go offline "very very soon".

    If the text in the maintenance message is poorly formatted, then an
    empty string is returned, and a warning should be logged.
    """

    timelefttext = None

    notmuchtime = timedelta(seconds=30)
    toomuchtime = timedelta(seconds=1800)  # 30 minutes

    def __call__(self):
        if os.path.exists('+maintenancetime.txt'):
            message = file('+maintenancetime.txt').read()
            try:
                maintenancetime = parseDatetimetz(message)
            except DateTimeError:
                # XXX log a warning here.
                #     SteveAlexander, 2005-09-22
                return ''
            nowtz = datetime.utcnow().replace(tzinfo=tzinfo(0))
            timeleft = maintenancetime - nowtz
            if timeleft > self.toomuchtime:
                return ''
            elif timeleft < self.notmuchtime:
                self.timelefttext = 'very very soon'
            else:
                self.timelefttext = 'in %s' % (
                    DurationFormatterAPI(timeleft).approximateduration())
            return self.index()
        return ''


class LaunchpadRootFacets(StandardLaunchpadFacets):

    usedfor = ILaunchpadRoot

    enable_only = ['overview', 'bugs', 'support', 'specifications',
                   'translations', 'branches']

    def overview(self):
        target = ''
        text = 'Overview'
        return Link(target, text)

    def translations(self):
        target = 'rosetta'
        text = 'Translations'
        return Link(target, text)

    def bugs(self):
        target = 'malone'
        text = 'Bugs'
        return Link(target, text)

    def support(self):
        target = 'support'
        text = 'Support'
        summary = 'Launchpad technical support tracker.'
        return Link(target, text, summary)

    def specifications(self):
        target = ''
        text = 'Features'
        summary = 'Launchpad feature specification tracker.'
        return Link(target, text, summary)

    def bounties(self):
        target = 'bounties'
        text = 'Bounties'
        summary = 'The Launchpad Universal Bounty Tracker'
        return Link(target, text, summary)

    def branches(self):
        target = 'bazaar'
        text = 'Code'
        summary = 'The Code Bazaar'
        return Link(target, text, summary)

    def calendar(self):
        target = 'calendar'
        text = 'Calendar'
        return Link(target, text)


class MaloneContextMenu(ContextMenu):
    usedfor = IMaloneApplication
    links = ['cvetracker']

    def cvetracker(self):
        text = 'CVE Tracker'
        return Link('cve/', text, icon='cve')


class RosettaContextMenu(ContextMenu):
    usedfor = IRosettaApplication
    links = ['about', 'import_queue', 'translation_groups']

    def about(self):
        text = 'About Rosetta'
        rosetta_application = getUtility(IRosettaApplication)
        url = '/'.join([canonical_url(rosetta_application), '+about'])
        return Link(url, text)

    def import_queue(self):
        text = 'Import queue'
        import_queue = getUtility(ITranslationImportQueue)
        url = canonical_url(import_queue)
        return Link(url, text)

    def translation_groups(self):
        text = 'Translation groups'
        translation_group_set = getUtility(ITranslationGroupSet)
        url = canonical_url(translation_group_set)
        return Link(url, text)


class LoginStatus:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user

    @property
    def login_shown(self):
        return (self.user is None and
                '+login' not in self.request['PATH_INFO'])

    @property
    def logged_in(self):
        return self.user is not None

    @property
    def login_url(self):
        query_string = self.request.get('QUERY_STRING', '')

        # If we have a query string, remove some things we don't want, and
        # keep it around.
        if query_string:
            query_dict = cgi.parse_qs(query_string, keep_blank_values=True)
            query_dict.pop('loggingout', None)
            query_string = urllib.urlencode(
                sorted(query_dict.items()), doseq=True)
            # If we still have a query_string after things we don't want
            # have been removed, add it onto the url.
            if query_string:
                query_string = '?' + query_string

        # The approach we're taking is to combine the application url with
        # the path_info, taking out path steps that are to do with virtual
        # hosting.  This is not exactly correct, as the application url
        # can have other path steps in it.  We're not using the feature of
        # having other path steps in the application url, so this will work
        # for us, assuming we don't need that in the future.

        # The application_url is typically like 'http://thing:port'. No
        # trailing slash.
        application_url = self.request.getApplicationURL()

        # We're going to use PATH_INFO to remove any spurious '+index' at the
        # end of the URL.  But, PATH_INFO will contain virtual hosting
        # configuration, if there is any.
        path_info = self.request['PATH_INFO']

        # Remove any virtual hosting segments.
        path_steps = []
        in_virtual_hosting_section = False
        for step in path_info.split('/'):
            if step.startswith('++vh++'):
                in_virtual_hosting_section = True
                continue
            if step == '++':
                in_virtual_hosting_section = False
                continue
            if not in_virtual_hosting_section:
                path_steps.append(step)
        path = '/'.join(path_steps)

        # Make the URL stop at the end of path_info so that we don't get
        # spurious '+index' at the end.
        full_url = '%s%s' % (application_url, path)
        if full_url.endswith('/'):
            full_url = full_url[:-1]
        logout_url_end = '/+logout'
        if full_url.endswith(logout_url_end):
            full_url = full_url[:-len(logout_url_end)]
        return '%s/+login%s' % (full_url, query_string)


class LaunchpadRootNavigation(Navigation):

    usedfor = ILaunchpadRoot

    def breadcrumb(self):
        return 'Launchpad'

    stepto_utilities = {
        'products': IProductSet,
        'people': IPersonSet,
        'distros': IDistributionSet,
        'sourcepackagenames': ISourcePackageNameSet,
        'binarypackagenames': IBinaryPackageNameSet,
        'projects': IProjectSet,
        'token': ILoginTokenSet,
        'karmaaction': IKarmaActionSet,
        'potemplatenames': IPOTemplateNameSet,
        'bazaar': IBazaarApplication,
        'codeofconduct': ICodeOfConductSet,
        'malone': IMaloneApplication,
        'bugs': IMaloneApplication,
        'registry': IRegistryApplication,
        'rosetta': IRosettaApplication,
        'specs': ISpecificationSet,
        'sprints': ISprintSet,
        'support': ITicketSet,
        '+builds': IBuilderSet,
        'bounties': IBountySet,
        }

    def traverse(self, name):
        if name in self.stepto_utilities:
            return getUtility(self.stepto_utilities[name])
        else:
            return None

    @stepto('calendar')
    def calendar(self):
        # XXX permission=launchpad.AnyPerson
        return MergedCalendar()


class SoftTimeoutView(LaunchpadView):

    def __call__(self):
        """Generate a soft timeout by sleeping enough time."""
        start_time = time.time()
        celebrities = getUtility(ILaunchpadCelebrities)
        if (self.user is None or
            not self.user.inTeam(celebrities.launchpad_developers)):
            raise Unauthorized

        self.request.response.setHeader('content-type', 'text/plain')
        soft_timeout = intOrZero(config.launchpad.soft_request_timeout)
        if soft_timeout == 0:
            return 'No soft timeout threshold is set.'

        time.sleep(soft_timeout/1000.0)
        time_to_generate_page = (time.time() - start_time) * 1000
        # In case we didn't sleep enogh time, sleep a while longer to
        # pass the soft timeout threshold.
        while time_to_generate_page < soft_timeout:
            time.sleep(0.1)
            time_to_generate_page = (time.time() - start_time) * 1000
        return (
            'Soft timeout threshold is set to %s ms. This page took'
            ' %s ms to render.' % (soft_timeout, time_to_generate_page))
