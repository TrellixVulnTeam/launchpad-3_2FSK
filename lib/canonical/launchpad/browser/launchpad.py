# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
"""Browser code for the launchpad application."""

__metaclass__ = type
__all__ = [
    'AppFrontPageSearchView',
    'Breadcrumbs',
    'LoginStatus',
    'MaintenanceMessage',
    'MenuBox',
    'RosettaContextMenu',
    'MaloneContextMenu',
    'LaunchpadRootNavigation',
    'MaloneApplicationNavigation',
    'SoftTimeoutView',
    'LaunchpadRootIndexView',
    'OneZeroTemplateStatus',
    'IcingFolder',
    'StructuralObjectPresentationView',
    'StructuralObjectPresentation',
    'ApplicationButtons',
    'SearchProjectsView',
    'DefaultShortLink',
    'BrowserWindowDimensions'
    ]

import cgi
from cookielib import domain_match
import errno
import urllib
import os
import re
import time
from datetime import timedelta, datetime

from zope.app.datetimeutils import parseDatetimetz, tzinfo, DateTimeError
from zope.component import getUtility
from zope.interface import implements
from zope.publisher.interfaces.xmlrpc import IXMLRPCRequest
from zope.security.interfaces import Unauthorized
from zope.app.content_types import guess_content_type
from zope.app.traversing.interfaces import ITraversable
from zope.app.publisher.browser.fileresource import setCacheControl
from zope.app.datetimeutils import rfc1123_date
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.publisher.interfaces import NotFound
from zope.security.proxy import isinstance as zope_isinstance

from BeautifulSoup import BeautifulStoneSoup, Comment

import canonical.launchpad.layers
from canonical.config import config
from canonical.launchpad.helpers import intOrZero
from canonical.launchpad.interfaces import (
	IAppFrontPageSearchForm,
    IBazaarApplication,
	IBinaryPackageNameSet,
	IBountySet,
	IBugSet,
	IBugTrackerSet,
	IBuilderSet,
	ICodeOfConductSet,
	ICveSet,
	IDistributionSet,
	IKarmaActionSet,
    ILaunchBag,
    ILaunchpadCelebrities,
	ILaunchpadRoot,
    ILoginTokenSet,
    IMaloneApplication,
	IPersonSet,
	IPillarNameSet,
	IPOTemplateNameSet,
	IProductSet,
	IProjectSet,
	IQuestionSet,
	IRegistryApplication,
    IRosettaApplication,
    ISourcePackageNameSet,
    ISpecificationSet,
	ISprintSet,
    IStructuralObjectPresentation,
    ITranslationGroupSet,
	ITranslationImportQueue,
	NotFoundError,
    )
from canonical.launchpad.components.cal import MergedCalendar
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, ContextMenu, Link, LaunchpadView,
    LaunchpadFormView, Navigation, stepto, canonical_url, custom_widget)
from canonical.launchpad.webapp.publisher import RedirectionView
from canonical.launchpad.webapp.uri import URI
from canonical.launchpad.webapp.vhosts import allvhosts
from canonical.widgets.project import ProjectScopeWidget


# XXX SteveAlexander, 2005-09-22, this is imported here because there is no
#     general timedelta to duration format adapter available.  This should
#     be factored out into a generally available adapter for both this
#     code and for TALES namespace code to use.
#     Same for MenuAPI.
from canonical.launchpad.webapp.tales import DurationFormatterAPI, MenuAPI


class MaloneApplicationNavigation(Navigation):

    usedfor = IMaloneApplication

    newlayer = canonical.launchpad.layers.BugsLayer

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
        firsttext = 'Home'

        L.append(
            '<li lpm:mid="root" class="item"><a href="%s"><em>%s</em></a></li>'
            % (firsturl, cgi.escape(firsttext)))

        if crumbs:

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
                         '<a href="%s"><em>%s</em></a>'
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

    enable_only = ['overview', 'bugs', 'answers', 'specifications',
                   'translations', 'branches']

    def overview(self):
        target = ''
        text = 'Overview'
        return Link(target, text)

    def translations(self):
        target = ''
        text = 'Translations'
        return Link(target, text)

    def bugs(self):
        target = ''
        text = 'Bugs'
        return Link(target, text)

    def answers(self):
        target = ''
        text = 'Answers'
        summary = 'Launchpad Answer Tracker'
        return Link(target, text, summary)

    def specifications(self):
        target = ''
        text = 'Blueprints'
        summary = 'Launchpad feature specification tracker.'
        return Link(target, text, summary)

    def bounties(self):
        target = 'bounties'
        text = 'Bounties'
        summary = 'The Launchpad Universal Bounty Tracker'
        return Link(target, text, summary)

    def branches(self):
        target = ''
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
        text = 'CVE tracker'
        return Link('cve/', text, icon='cve')


class RosettaContextMenu(ContextMenu):
    usedfor = IRosettaApplication
    links = ['about', 'preferences', 'import_queue', 'translation_groups']

    def about(self):
        text = 'About Rosetta'
        rosetta_application = getUtility(IRosettaApplication)
        url = '/'.join([canonical_url(rosetta_application), '+about'])
        return Link(url, text)

    def preferences(self):
        text = 'Translation preferences'
        rosetta_application = getUtility(IRosettaApplication)
        url = '/'.join([canonical_url(rosetta_application), 'prefs'])
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
        'codeofconduct': ICodeOfConductSet,
        'bugs': IMaloneApplication,
        'registry': IRegistryApplication,
        'specs': ISpecificationSet,
        'sprints': ISprintSet,
        'support': IQuestionSet,
        'translations': IRosettaApplication,
        '+builds': IBuilderSet,
        'bounties': IBountySet,
        '+code': IBazaarApplication,
        # These three have been renamed, and no redirects done, as the old
        # urls now point to the product pages.
        #'bazaar': IBazaarApplication,
        #'malone': IMaloneApplication,
        #'rosetta': IRosettaApplication,
        }

    def traverse(self, name):
        if name in self.stepto_utilities:
            return getUtility(self.stepto_utilities[name])

        # Allow traversal to ~foo for People
        if name.startswith('~'):
            person = getUtility(IPersonSet).getByName(name[1:].lower())
            return person

        # Dapper and Edgy shipped with https://launchpad.net/bazaar hard coded
        # into the Bazaar Launchpad plugin (part of Bazaar core). So in theory
        # we need to support this URL until 2011 (although I suspect the API
        # will break much sooner than that) or updates sent to
        # {dapper,edgy}-updates. Probably all irrelevant, as I suspect the
        # number of people using the plugin in edgy and dapper is 0.
        if name == 'bazaar' and IXMLRPCRequest.providedBy(self.request):
            return getUtility(IBazaarApplication)

        try:
            return getUtility(IPillarNameSet)[name.lower()]
        except NotFoundError:
            return None

    @stepto('calendar')
    def calendar(self):
        # XXX permission=launchpad.AnyPerson
        return MergedCalendar()

    def _getBetaRedirectionView(self):
        # If the inhibit_beta_redirect cookie is set, don't redirect:
        if self.request.cookies.get('inhibit_beta_redirect', '0') == '1':
            return None

        # If we are looking at the front page, don't redirect:
        if self.request['PATH_INFO'] == '/':
            return None
        
        # If no redirection host is set, don't redirect.
        mainsite_host = config.launchpad.vhosts.mainsite.hostname
        redirection_host = config.launchpad.beta_testers_redirection_host
        if redirection_host is None:
            return None
        # If the hostname for our URL isn't under the main site
        # (e.g. shipit.ubuntu.com), don't redirect.
        uri = URI(self.request.getURL())
        if not uri.host.endswith(mainsite_host):
            return None

        # Only redirect if the user is a member of beta testers team,
        # don't redirect.
        user = getUtility(ILaunchBag).user
        if user is None or not user.inTeam(
            getUtility(ILaunchpadCelebrities).launchpad_beta_testers):
            return None

        # Alter the host name to point at the redirection target:
        new_host = uri.host[:-len(mainsite_host)] + redirection_host
        uri = uri.replace(host=new_host)
        # Complete the URL from the environment:
        uri = uri.replace(path=self.request['PATH_INFO'])
        query_string = self.request.get('QUERY_STRING')
        if query_string:
            uri = uri.replace(query=query_string)

        # Empty the traversal stack, since we're redirecting.
        self.request.setTraversalStack([])
        
        # And perform a temporary redirect.
        return RedirectionView(str(uri), self.request, status=303)

    def publishTraverse(self, request, name):
        beta_redirection_view = self._getBetaRedirectionView()
        if beta_redirection_view is not None:
            return beta_redirection_view
        return Navigation.publishTraverse(self, request, name)


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


class LaunchpadRootIndexView(LaunchpadView):
    """An view for the default view of the LaunchpadRoot."""

    def _getCookieParams(self):
        """Return a string containing the 'domain' and 'secure' parameters."""
        params = '; Path=/'
        # XXX: 20070206 jamesh
        # This code to select the cookie domain comes from webapp/session.py
        # It should probably be factored out.
        uri = URI(self.request.getURL())
        if uri.scheme == 'https':
            params += '; Secure'
        for domain in config.launchpad.cookie_domains:
            assert not domain.startswith('.'), \
                   "domain should not start with '.'"
            dotted_domain = '.' + domain
            if (domain_match(uri.host, domain) or
                domain_match(uri.host, dotted_domain)):
                params += '; Domain=%s' % dotted_domain
                break
        return params

    def getInhibitRedirectScript(self):
        """Returns a Javascript function that inhibits redirection."""
        return '''
        function inhibit_beta_redirect() {
            var expire = new Date()
            expire.setTime(expire.getTime() + 2 * 60 * 60 * 1000)
            document.cookie = ('inhibit_beta_redirect=1%s; Expires=' +
                               expire.toGMTString())
            alert('You will not be redirected to the beta site for 2 hours');
            return false;
        }''' % self._getCookieParams()

    def getEnableRedirectScript(self):
        """Returns a Javascript function that enables beta redireciton."""
        return '''
        function enable_beta_redirect() {
            var expire = new Date()
            expire.setTime(expire.getTime() + 1000)
            document.cookie = ('inhibit_beta_redirect=0%s; Expires=' +
                               expire.toGMTString())
            alert('Redirection to the beta site has been enabled');
            return false;
        }''' % self._getCookieParams()

    def isRedirectInhibited(self):
        """Returns True if redirection has been inhibited."""
        return self.request.cookies.get('inhibit_beta_redirect', '0') == '1'
    
    def isBetaUser(self):
        """Return True if the user is in the beta testers team."""
        if config.launchpad.beta_testers_redirection_host is None:
            return False

        return self.user is not None and self.user.inTeam(
            getUtility(ILaunchpadCelebrities).launchpad_beta_testers)
        


class ObjectForTemplate:

    def __init__(self, **kw):
        for name, value in kw.items():
            setattr(self, name, value)


class OneZeroTemplateStatus(LaunchpadView):
    """A list showing how ready each template is for one-zero."""

    here = os.path.dirname(os.path.realpath(__file__))

    templatesdir = os.path.abspath(
            os.path.normpath(os.path.join(here, '..', 'templates'))
            )

    excluded_templates = set(['launchpad-onezerostatus.pt'])

    class PageStatus(ObjectForTemplate):
        filename = None
        status = None
        comment = ''
        helptext = ''

    valid_status_values = set(['new', 'todo', 'inprogress', 'done'])

    onezero_re = re.compile(r'\W*1-0\W+(\w+)\W+(.*)', re.DOTALL)

    def listExcludedTemplates(self):
        return sorted(self.excluded_templates)

    def initialize(self):
        self.pages = []
        self.portlets = []
        excluded = []
        filenames = [filename
                     for filename in os.listdir(self.templatesdir)
                     if filename.lower().endswith('.pt')
                        and filename not in self.excluded_templates
                     ]
        filenames.sort()
        for filename in filenames:
            data = open(os.path.join(self.templatesdir, filename)).read()
            soup = BeautifulStoneSoup(data)

            is_portlet = 'portlet' in filename

            if is_portlet:
                output_category = self.portlets
            else:
                output_category = self.pages

            num_one_zero_comments = 0
            html_comments = soup.findAll(text=lambda text:isinstance(text, Comment))
            for html_comment in html_comments:
                matchobj = self.onezero_re.match(html_comment)
                if matchobj:
                    num_one_zero_comments += 1
                    status, comment = matchobj.groups()
                    if status not in self.valid_status_values:
                        status = 'error'
                        comment = 'status not one of %s' % ', '.join(sorted(self.valid_status_values))

            if num_one_zero_comments == 0:
                is_page = soup.html is not None
                if is_page or is_portlet:
                    status = 'new'
                    comment = ''
                else:
                    excluded.append(filename)
                    continue
            elif num_one_zero_comments > 1:
                status = "error"
                comment = "There were %s one-zero comments in the document." % num_one_zero_comments

            xmlcomment = cgi.escape(comment)
            xmlcomment = xmlcomment.replace('\n', '<br />')

            helptextsoup = soup.find(attrs={'metal:fill-slot':'help'})
            if helptextsoup:
                #helptext = ''.join(unicode(t) for t in helptextsoup.findAll(recursive=False))
                helptext = unicode(helptextsoup)
            else:
                helptext = ''
            output_category.append(self.PageStatus(
                filename=filename,
                status=status,
                comment=xmlcomment,
                helptext=helptext))

        self.excluded_from_run = sorted(excluded)


class File:
    # Copied from zope.app.publisher.fileresource, which
    # unbelievably throws away the file data, and isn't
    # useful extensible.
    #
    def __init__(self, path, name):
        self.path = path

        f = open(path, 'rb')
        self.data = f.read()
        f.close()
        self.content_type, enc = guess_content_type(path, self.data)
        self.__name__ = name
        self.lmt = float(os.path.getmtime(path)) or time()
        self.lmh = rfc1123_date(self.lmt)

here = os.path.dirname(os.path.realpath(__file__))

class IcingFolder:
    """View that gives access to the files in a folder."""

    implements(IBrowserPublisher)

    folder = '../icing/'

    def __init__(self, context, request):
        """Initialize with context and request."""
        self.context = context
        self.request = request
        self.names = []

    def __call__(self):
        if not self.names:
            # Just the icing directory, so make this a 404.
            raise NotFound(self, '')
        elif len(self.names) > 1:
            # Too many path elements, so make this a 404.
            raise NotFound(self, self.names[-1])
        else:
            # Actually serve up the resource.
            name = self.names[0]
            return self.prepareDataForServing(name)

    def prepareDataForServing(self, name):
        """Set the response headers and return the data for this resource."""
        if os.path.sep in name:
            raise ValueError(
                'os.path.sep appeared in the resource name: %s' % name)
        filename = os.path.join(here, self.folder, name)
        try:
            fileobj = File(filename, name)
        except IOError, ioerror:
            if ioerror.errno == errno.ENOENT: # No such file or directory
                raise NotFound(self, name)
            else:
                # Some other IOError that we're not expecting.
                raise

        # TODO: Set an appropriate charset too.  There may be zope code we
        #       can reuse for this.
        response = self.request.response
        response.setHeader('Content-Type', fileobj.content_type)
        response.setHeader('Last-Modified', fileobj.lmh)
        setCacheControl(response)
        return fileobj.data

    # The following two zope methods publishTraverse and browserDefault
    # allow this view class to take control of traversal from this point
    # onwards.  Traversed names just end up in self.names.

    def publishTraverse(self, request, name):
        """Traverse to the given name."""
        self.names.append(name)
        return self

    def browserDefault(self, request):
        return self, ()


class StructuralObjectPresentationView(LaunchpadView):

    # Object attributes used by the page template:
    #   num_lists: 0, 1 or 2
    #   children: []
    #   has_more_children: True/False
    #   alt_children: []
    #   has_more_altchildren: True/False

    def initialize(self):
        self.structuralpresentation = IStructuralObjectPresentation(
            self.context)
        sop = self.structuralpresentation

        max_alt_children_to_present = 4

        # First, see if listAltChildren returns None.  If so, we have
        # just children.  If not, we have both alt-children and children.
        alt_children = sop.listAltChildren(max_alt_children_to_present + 1)
        if alt_children is None:
            max_children_to_present = 8

            # Note that self.has_more_alt_children and self.alt_children is
            # undefined when we have no alt_children.
            # The page template needs to check num_lists is 2 before reading
            # these attributes.
        else:
            max_children_to_present = 4

            assert zope_isinstance(alt_children, list)
            self.has_more_alt_children = len(alt_children) > max_alt_children_to_present
            self.alt_children = children[:max_alt_children_to_present]

        children = sop.listChildren(max_children_to_present + 1)
        assert zope_isinstance(children, list)

        self.has_more_children = len(children) > max_children_to_present
        self.children = children[:max_children_to_present]

        if alt_children is None:
            if not children:
                self.num_lists = 0
            else:
                self.num_lists = 1
        else:
            self.num_lists = 2

    def getIntroHeading(self):
        return self.structuralpresentation.getIntroHeading()

    def getMainHeading(self):
        return self.structuralpresentation.getMainHeading()

    def getGotchiURL(self):
        return '/+not-found-gotchi'


class StructuralObjectPresentation:
    """Base class for StructuralObjectPresentation adapters."""

    implements(IStructuralObjectPresentation)

    def __init__(self, context):
        self.context = context

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        raise NotImplementedError()

    def listChildren(self, num):
        return []

    def countChildren(self):
        raise NotImplementedError()

    def listAltChildren(self, num):
        return None

    def countAltChildren(self):
        raise NotImplementedError()


class DefaultStructuralObjectPresentation(StructuralObjectPresentation):

    def getMainHeading(self):
        if hasattr(self.context, 'title'):
            return self.context.title
        else:
            return 'no title'

    def listChildren(self, num):
        return []

    def listAltChildren(self, num):
        return None


class Button:

    def __init__(self, **kw):
        assert len(kw) == 1
        self.name = kw.keys()[0]
        self.text = kw.values()[0]
        self.replacement_dict = self.makeReplacementDict()

    def makeReplacementDict(self):
        return dict(
            url=allvhosts.configs[self.name].rooturl,
            buttonname=self.name,
            text=self.text)

    def renderActive(self):
        return (
            '<a href="%(url)s">\n'
            '  <img'
            '    alt=""'
            '    src="/+icing/app-%(buttonname)s-sml-active.gif"'
            '    title="%(text)s"'
            '  />\n'
            '</a>\n' % self.replacement_dict)

    def renderInactive(self):
        return (
            '<a href="%(url)s">\n'
            '  <img'
            '    alt=""'
            '    src="/+icing/app-%(buttonname)s-sml.gif"'
            '    title="%(text)s"'
            '  />\n'
            '</a>\n' % self.replacement_dict)

    def renderFrontPage(self):
        return (
            '<a href="%(url)s">\n'
            '  <img'
            '    alt=""'
            '    src="/+icing/app-%(buttonname)s.gif"'
            '    title="%(text)s"'
            '  />\n'
            '</a>\n' % self.replacement_dict)

    def renderButton(self, is_active, is_front_page):
        if (is_front_page):
            return self.renderFrontPage()
        elif is_active:
            return self.renderActive()
        else:
            return self.renderInactive()


class ProductsButton(Button):

    def makeReplacementDict(self):
        return dict(
            url='%sproducts/' % allvhosts.configs['mainsite'].rooturl,
            buttonname=self.name,
            text=self.text)


class ApplicationButtons(LaunchpadView):
    """Those buttons that you get on the index pages."""

    implements(ITraversable)

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)
        self.name = None

    buttons = [
        ProductsButton(
            register="Register your project so it can benefit from "
                     "Launchpad&rsquo;s features."),
        Button(code="Publish your code for people to merge and branch from."),
        Button(bugs="Share bug reports and fixes."),
        Button(
            blueprints="Track specifications to approval and implementation."),
        Button(translations="Localize software into your favorite language."),
        Button(answers="Ask and answer questions about software.")
        ]

    def render(self):
        L = []
        for button in self.buttons:
            if self.name:
                is_active = button.name == self.name
            else:
                is_active = True
            is_front_page = self.name == 'main'
            L.append(button.renderButton(is_active, is_front_page))
        return u'\n'.join(L)

    def traverse(self, name, furtherPath):
        self.name = name
        if furtherPath:
            raise AssertionError(
                'Max of one path item after +applicationbuttons')
        return self


class SearchProjectsView(LaunchpadView):
    """The page where people can search for Projects/Products/Distros."""

    results = None
    search_string = ""
    max_results_to_display = config.launchpad.default_batch_size

    def initialize(self):
        form = self.request.form
        self.search_string = form.get('q')
        if not self.search_string:
            return

        search_string = self.search_string.lower()
        # We use a limit bigger than self.max_results_to_display so that we
        # know when we had too many results and we can tell the user that some
        # of them are not being displayed.
        limit = self.max_results_to_display + 1
        self.results = getUtility(IPillarNameSet).search(search_string, limit)

    def tooManyResultsFound(self):
        return len(self.results) > self.max_results_to_display


class DefaultShortLink(LaunchpadView):
    """Render a short link to an object.

    This is a default implementation that assumes that context.title exists
    and is what we want.

    This class can be used as a base class for simple short links by
    overriding the getLinkText() method.
    """

    def getLinkText(self):
        return self.context.title

    def render(self):
        L = []
        L.append('<a href="%s">' % canonical_url(self.context))
        L.append(cgi.escape(self.getLinkText()).replace(' ', '&nbsp;'))
        L.append('</a>')
        return u''.join(L)


class AppFrontPageSearchView(LaunchpadFormView):

    schema = IAppFrontPageSearchForm
    custom_widget('scope', ProjectScopeWidget)

    @property
    def scope_css_class(self):
        """The CSS class for used in the scope widget."""
        if self.scope_error:
            return 'error'
        else:
            return None

    @property
    def scope_error(self):
        """The error message for the scope widget."""
        return self.getWidgetError('scope')


class BrowserWindowDimensions(LaunchpadView):
    """Allow capture of browser window dimensions."""

    def render(self):
        return u'Thanks.'
