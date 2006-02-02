# Copyright 2004 Canonical Ltd

__metaclass__ = type

__all__ = [
    'PersonNavigation',
    'TeamNavigation',
    'PersonSetNavigation',
    'PeopleContextMenu',
    'PersonFacets',
    'PersonBugsMenu',
    'PersonSpecsMenu',
    'PersonSupportMenu',
    'PersonCodeMenu',
    'PersonOverviewMenu',
    'TeamOverviewMenu',
    'BaseListView',
    'PeopleListView',
    'TeamListView',
    'UbunteroListView',
    'FOAFSearchView',
    'PersonEditView',
    'PersonEmblemView',
    'PersonHackergotchiView',
    'PersonAssignedBugTaskSearchListingView',
    'ReportedBugTaskSearchListingView',
    'BugContactPackageBugsSearchListingView',
    'SubscribedBugTaskSearchListingView',
    'PersonRdfView',
    'PersonView',
    'TeamJoinView',
    'TeamLeaveView',
    'PersonEditEmailsView',
    'RequestPeopleMergeView',
    'AdminRequestPeopleMergeView',
    'FinishedPeopleMergeRequestView',
    'RequestPeopleMergeMultipleEmailsView',
    'ObjectReassignmentView',
    'TeamReassignmentView',
    ]

import cgi
import urllib
import itertools
import sets
from StringIO import StringIO

from zope.event import notify
from zope.security.proxy import isinstance as zope_isinstance
from zope.app.form.browser.add import AddView
from zope.app.form.utility import setUpWidgets
from zope.app.content_types import guess_content_type
from zope.app.form.interfaces import (
        IInputWidget, ConversionError, WidgetInputError)
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility, getView

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.searchbuilder import any, NULL
from canonical.lp.dbschema import (
    LoginTokenType, SSHKeyType, EmailAddressStatus, TeamMembershipStatus,
    TeamSubscriptionPolicy)
from canonical.lp.z3batching import Batch
from canonical.lp.batching import BatchNavigator

from canonical.launchpad.interfaces import (
    ISSHKeySet, IBugTaskSet, IPersonSet, IEmailAddressSet, IWikiNameSet,
    IJabberIDSet, IIrcIDSet, ILaunchBag, ILoginTokenSet, IPasswordEncryptor,
    ISignedCodeOfConductSet, IGPGKeySet, IGPGHandler, UBUNTU_WIKI_URL,
    ITeamMembershipSet, IObjectReassignment, ITeamReassignment, IPollSubset,
    IPerson, ICalendarOwner, ITeam, ILibraryFileAliasSet, IPollSet,
    IAdminRequestPeopleMerge, BugTaskSearchParams, NotFoundError,
    UNRESOLVED_BUGTASK_STATUSES, IDistributionSet)

from canonical.launchpad.browser.bugtask import (
    BugTaskSearchListingView, AdvancedBugTaskSearchView)
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.cal import CalendarTraversalMixin
from canonical.launchpad.helpers import (
        obfuscateEmail, convertToHtmlCode, sanitiseFingerprint)
from canonical.launchpad.validators.email import valid_email
from canonical.launchpad.validators.name import valid_name
from canonical.launchpad.mail.sendmail import simple_sendmail
from canonical.launchpad.event.team import JoinTeamRequestEvent
from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, canonical_url, ContextMenu, ApplicationMenu,
    enabled_with_permission, Navigation, stepto, stepthrough, smartquote,
    redirection, GeneralFormView)

from canonical.launchpad import _


class BranchTraversalMixin:

    @stepto('+branch')
    def traverse_branch(self):
        """Branch of this person or team for the specified product and
        branch names.

        For example:

        * '/people/ddaa/+branch/bazaar/devel' points to the branch whose owner
          name is 'ddaa', whose product name is 'bazaar', and whose branch name
          is 'devel'.

        * '/people/sabdfl/+branch/+junk/junkcode' points to the branch whose
          owner name is 'sabdfl', with no associated product, and whose branch
          name is 'junkcode'.
        """
        stepstogo = self.request.stepstogo
        product_name = stepstogo.consume()
        branch_name = stepstogo.consume()
        if product_name is not None and branch_name is not None:
            if product_name == '+junk':
                return self.context.getBranch(None, branch_name)
            else:
                return self.context.getBranch(product_name, branch_name)
        raise NotFoundError


class PersonNavigation(Navigation, CalendarTraversalMixin,
                       BranchTraversalMixin):

    usedfor = IPerson

    redirection("+bugs", "+assignedbugs")

    def breadcrumb(self):
        return self.context.displayname


class TeamNavigation(Navigation, CalendarTraversalMixin,
                     BranchTraversalMixin):

    usedfor = ITeam

    redirection("+bugs", "+assignedbugs")

    def breadcrumb(self):
        return smartquote('"%s" team') % self.context.displayname

    @stepthrough('+poll')
    def traverse_poll(self, name):
        return getUtility(IPollSet).getByTeamAndName(self.context, name)

    @stepthrough('+member')
    def traverse_member(self, name):
        person = getUtility(IPersonSet).getByName(name)
        if person is None:
            return None
        return getUtility(ITeamMembershipSet).getByPersonAndTeam(
            person, self.context)


class PersonSetNavigation(Navigation):

    usedfor = IPersonSet

    def breadcrumb(self):
        return 'People'

    @stepto('+me')
    def me(self):
        return getUtility(ILaunchBag).user

    def traverse(self, name):
        return self.context.getByName(name)


class PeopleContextMenu(ContextMenu):

    usedfor = IPersonSet

    links = ['peoplelist', 'teamlist', 'ubunterolist', 'newteam',
             'adminrequestmerge']

    def peoplelist(self):
        text = 'All People'
        return Link('+peoplelist', text, icon='people')

    def teamlist(self):
        text = 'All Teams'
        return Link('+teamlist', text, icon='people')

    def ubunterolist(self):
        text = 'All Ubunteros'
        return Link('+ubunterolist', text, icon='people')

    def newteam(self):
        text = 'Register a Team'
        return Link('+newteam', text, icon='add')

    @enabled_with_permission('launchpad.Admin')
    def adminrequestmerge(self):
        text = 'Admin Merge Accounts'
        return Link('+adminrequestmerge', text, icon='edit')


class PersonFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IPerson."""

    usedfor = IPerson

    enable_only = ['overview', 'bugs', 'support', 'bounties', 'specifications',
                   'translations', 'calendar', 'code']

    links = StandardLaunchpadFacets.links + ['code']

    def overview(self):
        text = 'Overview'
        summary = 'General information about %s' % self.context.browsername
        return Link('', text, summary)

    def bugs(self):
        text = 'Bugs'
        summary = (
            'Bug reports that %s is involved with' % self.context.browsername)
        return Link('+assignedbugs', text, summary)

    def support(self):
        text = 'Support'
        summary = (
            'Support requests that %s is involved with' %
            self.context.browsername)
        return Link('+tickets', text, summary)

    def specifications(self):
        text = 'Specifications'
        summary = (
            'Feature specifications that %s is involved with' %
            self.context.browsername)
        return Link('+specs', text, summary)

    def bounties(self):
        text = 'Bounties'
        summary = (
            'Bounty offers that %s is involved with' % self.context.browsername
            )
        return Link('+bounties', text, summary)

    def translations(self):
        target = '+translations'
        text = 'Translations'
        summary = (
            'Software that %s is involved in translating' %
            self.context.browsername)
        return Link(target, text, summary)

    def calendar(self):
        text = 'Calendar'
        summary = (
            u'%s\N{right single quotation mark}s scheduled events' %
            self.context.browsername)
        # only link to the calendar if it has been created
        enabled = ICalendarOwner(self.context).calendar is not None
        return Link('+calendar', text, summary, enabled=enabled)

    def code(self):
        text = 'Code'
        summary = 'Branches and revisions by %s' % self.context.browsername
        return Link('+branches', text, summary)


class PersonBugsMenu(ApplicationMenu):

    usedfor = IPerson

    facet = 'bugs'

    links = ['assignedbugs', 'reportedbugs', 'subscribedbugs', 'softwarebugs']

    def assignedbugs(self):
        text = 'Assigned'
        return Link('+assignedbugs', text, icon='bugs')

    def softwarebugs(self):
        text = 'Package Reports'
        return Link('+packagebugs', text, icon='bugs')

    def reportedbugs(self):
        text = 'Reported'
        return Link('+reportedbugs', text, icon='bugs')

    def subscribedbugs(self):
        text = 'Subscribed'
        return Link('+subscribedbugs', text, icon='bugs')


class TeamBugsMenu(PersonBugsMenu):

    usedfor = ITeam
    facet = 'bugs'
    links = ['assignedbugs', 'softwarebugs', 'subscribedbugs']
 

class PersonSpecsMenu(ApplicationMenu):

    usedfor = IPerson

    facet = 'specifications'

    links = ['created', 'assigned', 'drafted', 'review', 'approver',
             'subscribed']

    def created(self):
        text = 'Specifications Created'
        return Link('+createdspecs', text, icon='spec')

    def approver(self):
        text = 'Specifications for Approval'
        return Link('+approverspecs', text, icon='spec')

    def assigned(self):
        text = 'Specifications Assigned'
        return Link('+assignedspecs', text, icon='spec')

    def drafted(self):
        text = 'Specifications Drafted'
        return Link('+draftedspecs', text, icon='spec')

    def review(self):
        text = 'Feedback Requests'
        return Link('+reviewspecs', text, icon='spec')

    def subscribed(self):
        text = 'Specifications Subscribed'
        return Link('+subscribedspecs', text, icon='spec')


class PersonSupportMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'support'
    links = ['created', 'assigned', 'answered', 'subscribed']

    def created(self):
        text = 'Requests Made'
        return Link('+createdtickets', text, icon='ticket')

    def assigned(self):
        text = 'Requests Assigned'
        return Link('+assignedtickets', text, icon='ticket')

    def answered(self):
        text = 'Requests Answered'
        return Link('+answeredtickets', text, icon='ticket')

    def subscribed(self):
        text = 'Requests Subscribed'
        return Link('+subscribedtickets', text, icon='ticket')


class PersonCodeMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'code'
    links = ['authored', 'registered', 'subscribed', 'add']

    def authored(self):
        text = 'Branches Authored'
        return Link('+authoredbranches', text, icon='branch')

    def registered(self):
        text = 'Branches Registered'
        return Link('+registeredbranches', text, icon='branch')

    def subscribed(self):
        text = 'Branches Subscribed'
        return Link('+subscribedbranches', text, icon='branch')

    def add(self):
        text = 'Add Bazaar Branch'
        return Link('+addbranch', text, icon='add')


class CommonMenuLinks:

    @enabled_with_permission('launchpad.Edit')
    def common_edithomepage(self):
        target = '+edithomepage'
        text = 'Edit Home Page'
        return Link(target, text, icon='edit')

    def common_packages(self):
        target = '+packages'
        text = 'Packages'
        summary = 'Packages assigned to %s' % self.context.browsername
        return Link(target, text, summary, icon='packages')


class PersonOverviewMenu(ApplicationMenu, CommonMenuLinks):

    usedfor = IPerson
    facet = 'overview'
    links = ['karma', 'edit', 'common_edithomepage', 'editemailaddresses',
             'editwikinames', 'editircnicknames', 'editjabberids',
             'editpassword', 'edithackergotchi', 'editsshkeys', 'editgpgkeys',
             'codesofconduct', 'administer', 'common_packages']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        target = '+edit'
        text = 'Edit Personal Details'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editemailaddresses(self):
        target = '+editemails'
        text = 'Edit Email Addresses'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editwikinames(self):
        target = '+editwikinames'
        text = 'Edit Wiki Names'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editircnicknames(self):
        target = '+editircnicknames'
        text = 'Edit IRC Nicknames'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editjabberids(self):
        target = '+editjabberids'
        text = 'Edit Jabber IDs'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editpassword(self):
        target = '+changepassword'
        text = 'Change Password'
        return Link(target, text, icon='edit')

    def karma(self):
        target = '+karma'
        text = 'Karma'
        summary = (
            u'%s\N{right single quotation mark}s activities '
            u'in Launchpad' % self.context.browsername)
        return Link(target, text, summary, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def editsshkeys(self):
        target = '+editsshkeys'
        text = 'Edit SSH Keys'
        summary = (
            'Used if %s stores code on the Supermirror' %
            self.context.browsername)
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editgpgkeys(self):
        target = '+editgpgkeys'
        text = 'Edit OpenPGP Keys'
        summary = 'Used for the Supermirror, and when maintaining packages'
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def edithackergotchi(self):
        target = '+edithackergotchi'
        text = 'Edit Hackergotchi'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def codesofconduct(self):
        target = '+codesofconduct'
        text = 'Codes of Conduct'
        summary = (
            'Agreements to abide by the rules of a distribution or project')
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        target = '+review'
        text = 'Administer'
        return Link(target, text, icon='edit')


class TeamOverviewMenu(ApplicationMenu, CommonMenuLinks):

    usedfor = ITeam
    facet = 'overview'
    links = ['edit', 'common_edithomepage', 'editemblem', 'members',
             'editemail', 'polls', 'joinleave', 'reassign', 'common_packages']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        target = '+edit'
        text = 'Change Team Details'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def reassign(self):
        target = '+reassign'
        text = 'Change Owner'
        summary = 'Change the owner of the team'
        # alt="(Change owner)"
        return Link(target, text, summary, icon='edit')

    def editemblem(self):
        target = '+editemblem'
        text = 'Edit Emblem'
        return Link(target, text, icon='edit')

    def members(self):
        target = '+members'
        text = 'Edit Members'
        return Link(target, text, icon='people')

    def polls(self):
        target = '+polls'
        text = 'Polls'
        return Link(target, text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def editemail(self):
        target = '+editemail'
        text = 'Edit Contact Address'
        summary = (
            'The address Launchpad uses to contact %s' %
            self.context.browsername)
        return Link(target, text, summary, icon='mail')

    def joinleave(self):
        if userIsActiveTeamMember(self.context):
            target = '+leave'
            text = 'Leave the Team' # &#8230;
            icon = 'remove'
        else:
            target = '+join'
            text = 'Join the Team' # &#8230;
            icon = 'add'
        return Link(target, text, icon=icon)


##XXX: (batch_size+global) cprov 20041003
## really crap constant definition for BatchPages
BATCH_SIZE = 40


class BaseListView:

    header = ""

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def _getBatchNavigator(self, list):
        start = int(self.request.get('batch_start', 0))
        batch = Batch(list=list, start=start, size=BATCH_SIZE)
        return BatchNavigator(batch=batch, request=self.request)

    def getTeamsList(self):
        results = getUtility(IPersonSet).getAllTeams()
        return self._getBatchNavigator(results)

    def getPeopleList(self):
        results = getUtility(IPersonSet).getAllPersons()
        return self._getBatchNavigator(results)

    def getUbunterosList(self):
        results = getUtility(IPersonSet).getUbunteros()
        return self._getBatchNavigator(results)


class PeopleListView(BaseListView):

    header = "People List"

    def getList(self):
        return self.getPeopleList()


class TeamListView(BaseListView):

    header = "Team List"

    def getList(self):
        return self.getTeamsList()


class UbunteroListView(BaseListView):

    header = "Ubuntero List"

    def getList(self):
        return self.getUbunterosList()


class FOAFSearchView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.results = []

    def teamsCount(self):
        return getUtility(IPersonSet).teamsCount()

    def peopleCount(self):
        return getUtility(IPersonSet).peopleCount()

    def topPeople(self):
        return getUtility(IPersonSet).topPeople()

    def searchPeopleBatchNavigator(self):
        name = self.request.get("name")
        searchfor = self.request.get("searchfor")

        if not name:
            return None

        if searchfor == "all":
            results = getUtility(IPersonSet).find(name)
        elif searchfor == "peopleonly":
            results = getUtility(IPersonSet).findPerson(name)
        elif searchfor == "teamsonly":
            results = getUtility(IPersonSet).findTeam(name)

        start = int(self.request.get('batch_start', 0))
        batch = Batch(list=results, start=start, size=BATCH_SIZE)
        return BatchNavigator(batch=batch, request=self.request)


class PersonRdfView:
    """A view that sets its mime-type to application/rdf+xml"""

    template = ViewPageTemplateFile(
        '../templates/person-foaf.pt')

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        """Render RDF output, and return it as a string encoded in UTF-8.

        Render the page template to produce RDF output.
        The return value is string data encoded in UTF-8.

        As a side-effect, HTTP headers are set for the mime type
        and filename for download."""
        self.request.response.setHeader('content-type',
                                        'application/rdf+xml')
        self.request.response.setHeader('Content-Disposition',
                                        'attachment; filename=%s.rdf' %
                                            self.context.name)
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata

def userIsActiveTeamMember(team):
    """Return True if the user is an active member of this team."""
    user = getUtility(ILaunchBag).user
    if user is None:
        return False
    return user in team.activemembers


class BasePersonBugTaskSearchListingView(AdvancedBugTaskSearchView):
    """A Base view class to be used by all bug listings on a person page.
    
    All bug listings on a person page are in some way related to that person.
    This means that this person (our context) has to be in the
    BugTaskSearchParams that will be given to the searchTasks() method. To do
    this, subclasses must define an context_parameter class variable whose 
    value should be either 'owner', 'subscriber' or 'assignee'.

    Please note this is a base class that is not meant to be used as a view
    class. Instead, you should derive from it and use the derived class.
    """

    context_parameter = None

    def getExtraSearchParams(self):
        assert self.context_parameter is not None
        params = AdvancedBugTaskSearchView.getExtraSearchParams(self)
        params[self.context_parameter] = self.context
        return params

    def hasSimpleMode(self):
        return True

    def shouldShowAdvancedSearchWidgets(self):
        """Return True if this view's advanced form should be shown."""
        form = self.request.form
        if form.get('advanced') and not form.get('simple'):
            return True
        return False


class ReportedBugTaskSearchListingView(BasePersonBugTaskSearchListingView):
    """All bugs reported by someone."""

    context_parameter = 'owner'


class BugContactPackageBugsSearchListingView(BugTaskSearchListingView):
    """All bugs reported on software maintained by someone."""

    def search(self, searchtext=None, batch_start=None):
        distrosourcepackage = self.getPackage()
        return BugTaskSearchListingView.search(
            self, searchtext=searchtext, batch_start=batch_start,
            context=distrosourcepackage)

    def getExtraSearchParams(self):
        """Overridden from BugTaskSearchListingView, to filter the search."""
        search_params = {}

        if self.status_widget.hasInput():
            search_params['status'] = any(*self.status_widget.getInputValue())
        if self.unassigned_widget.hasInput():
            search_params['assignee'] = NULL

        return search_params

    def getBugContactPackageSearchURL(self, distributionsourcepackage=None,
                                      extra_params=None):
        if distributionsourcepackage is None:
            distributionsourcepackage = self.getPackage()

        params = {
            "field.distribution": distributionsourcepackage.distribution.name,
            "field.sourcepackagename": distributionsourcepackage.name,
            "search": "Search"}

        if extra_params is not None:
            params.update(extra_params)

        person_url = canonical_url(self.context)
        query_string = urllib.urlencode(sorted(params.items()), doseq=True)
        html_safe_query_string = cgi.escape(query_string)

        return person_url + '/+packagebugs-search?%s' % html_safe_query_string

    def getPackage(self):
        """Get the package whose bugs are currently being searched."""
        form = self.request.form
        distribution = getUtility(IDistributionSet).getByName(
            form.get("field.distribution"))

        return distribution.getSourcePackage(
            form.get("field.sourcepackagename"))

    def getOpenBugsURL(self, distributionsourcepackage):
        """Return the URL for open bugs on distributionsourcepackage."""
        status_params = {'field.status': []}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            status_params['field.status'].append(status.title)

        return self.getBugContactPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=status_params)

    def getCriticalBugsURL(self, distributionsourcepackage):
        """Return the URL for critical bugs on distributionsourcepackage."""
        critical_bugs_params = {
            'field.status': [], 'field.severity': "Critical"}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            critical_bugs_params["field.status"].append(status.title)

        return self.getBugContactPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=critical_bugs_params)

    def getUnassignedBugsURL(self, distributionsourcepackage):
        """Return the URL for unassigned bugs on distributionsourcepackage."""
        unassigned_bugs_params = {
            "field.status": [], "field.unassigned": "on"}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            unassigned_bugs_params["field.status"].append(status.title)

        return self.getBugContactPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=unassigned_bugs_params)

    def getInProgressBugsURL(self, distributionsourcepackage):
        """Return the URL for unassigned bugs on distributionsourcepackage."""
        inprogress_bugs_params = {"field.status": "In Progress"}

        return self.getBugContactPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=inprogress_bugs_params)

    def getSearchFilterLinks(self):
        """Return a dict of links to various parts of the current filter."""
        search_filter_links = []
        form = self.request.form

        # First, a link to all the bugs for the current package.
        current_package = self.getPackage()
        search_filter_links.append(
            (str(current_package.displayname),
             self.getBugContactPackageSearchURL(current_package)))

        # Add a link to the "unassigned" filter, if applicable.
        if form.get("field.unassigned") == "on":
            search_filter_links.append(
                ("unassigned", self.getUnassignedBugsURL(current_package)))

        return search_filter_links

    def getStatusFilterLinks(self):
        """Return links to filter on each status shown in the listing.

        This is a separate method because status filter links are displayed
        differently from other filter links, to communicate that they're an "OR"
        match.
        """
        status_filter_links = []
        form = self.request.form

        # If no statuses are provided in the URL, default to unresolved
        # statuses.
        filter_statuses = form.get(
            "field.status",
            [s.title for s in UNRESOLVED_BUGTASK_STATUSES])

        for status_name in filter_statuses:
            status_filter_links.append((
                status_name.lower(),
                self.getBugContactPackageSearchURL(
                    extra_params={"field.status": status_name})))

        return status_filter_links

    def getSearchTextFilterLink(self):
        form = self.request.form
        searchtext_filter_link = []

        searchtext = form.get("field.searchtext")
        if searchtext:
            searchtext_filter_link = (
                searchtext,
                self.getBugContactPackageSearchURL(
                    extra_params={"field.searchtext": searchtext}))

        return searchtext_filter_link

    def shouldShowSearchWidgets(self):
        # XXX: It's not possible to search amongst the bugs on maintained
        # software, so for now I'll be simply hiding the search widgets.
        # -- Guilherme Salgado, 2005-11-05
        return False


class PersonAssignedBugTaskSearchListingView(
        BasePersonBugTaskSearchListingView):
    """All bugs assigned to someone."""

    context_parameter = 'assignee'

    def shouldShowAssignee(self):
        """Should we show the assignee in the list of results?"""
        return False


class SubscribedBugTaskSearchListingView(BasePersonBugTaskSearchListingView):
    """All bugs someone is subscribed to."""

    context_parameter = 'subscriber'


class PersonView:
    """A View class used in almost all Person's pages."""

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.message = None
        self.user = getUtility(ILaunchBag).user
        self._karma_categories = None
        if context.isTeam():
            # These methods are called here because their return values are
            # going to be used in some other places (including
            # self.hasCurrentPolls()).
            pollsubset = IPollSubset(self.context)
            self.openpolls = pollsubset.getOpenPolls()
            self.closedpolls = pollsubset.getClosedPolls()
            self.notyetopenedpolls = pollsubset.getNotYetOpenedPolls()

    def hasCurrentPolls(self):
        """Return True if this team has any non-closed polls."""
        assert self.context.isTeam()
        return bool(self.openpolls) or bool(self.notyetopenedpolls)

    def sourcepackagerelease_open_bugs_count(self, sourcepackagerelease):
        """Return the number of open bugs targeted to the sourcepackagename
        and distrorelease of the given sourcepackagerelease.
        """
        params = BugTaskSearchParams(
            user=self.user,
            sourcepackagename=sourcepackagerelease.sourcepackagename,
            status=any(*UNRESOLVED_BUGTASK_STATUSES))
        params.setDistributionRelease(sourcepackagerelease.uploaddistrorelease)
        return getUtility(IBugTaskSet).search(params).count()

    def maintainedPackagesByPackageName(self):
        return self._groupSourcePackageReleasesByName(
            self.context.maintainedPackages())

    def uploadedButNotMaintainedPackagesByPackageName(self):
        return self._groupSourcePackageReleasesByName(
            self.context.uploadedButNotMaintainedPackages())

    class SourcePackageReleasesByName:
        """A class to hold a sourcepackagename and a list of
        sourcepackagereleases of that sourcepackagename.
        """

        def __init__(self, name, releases):
            self.name = name
            self.releases = releases

    def _groupSourcePackageReleasesByName(self, sourcepackagereleases):
        """Return a list of SourcePackageReleasesByName objects ordered by
        SourcePackageReleasesByName.name.
        
        Each SourcePackageReleasesByName object contains a name, which is the
        sourcepackagename and a list containing all sourcepackagereleases of
        that sourcepackagename.
        """
        allreleasesbyallnames = []
        keyfunc = lambda sprelease: sprelease.name
        for key, group in itertools.groupby(sourcepackagereleases, keyfunc):
            allreleasesbyallnames.append(
                PersonView.SourcePackageReleasesByName(key, list(group)))
        return sorted(allreleasesbyallnames, key=lambda s: s.name)

    def no_bounties(self):
        return not (self.context.ownedBounties or
            self.context.reviewerBounties or
            self.context.subscribedBounties or
            self.context.claimedBounties)

    def activeMembersCount(self):
        return len(self.context.activemembers)

    def userIsOwner(self):
        """Return True if the user is the owner of this Team."""
        user = getUtility(ILaunchBag).user
        if user is None:
            return False

        return user.inTeam(self.context.teamowner)

    def userHasMembershipEntry(self):
        """Return True if the logged in user has a TeamMembership entry for
        this Team."""
        return bool(self._getMembershipForUser())

    def userIsActiveMember(self):
        """Return True if the user is an active member of this team."""
        return userIsActiveTeamMember(self.context)

    def membershipStatusDesc(self):
        tm = self._getMembershipForUser()
        assert tm is not None, (
            'This method is not meant to be called for users which are not '
            'members of this team.')

        description = tm.status.description
        if (tm.status == TeamMembershipStatus.DEACTIVATED and
            tm.reviewercomment):
            description += ("The reason for the deactivation is: '%s'"
                            % tm.reviewercomment)
        return description

    def userCanRequestToLeave(self):
        """Return true if the user can request to leave this team.

        A given user can leave a team only if he's an active member.
        """
        return self.userIsActiveMember()

    def userCanRequestToJoin(self):
        """Return true if the user can request to join this team.

        The user can request if this is not a RESTRICTED team or if he never
        asked to join this team, if he already asked and the subscription
        status is DECLINED.
        """
        if (self.context.subscriptionpolicy ==
            TeamSubscriptionPolicy.RESTRICTED):
            return False

        tm = self._getMembershipForUser()
        if tm is None:
            return True

        adminOrApproved = [TeamMembershipStatus.APPROVED,
                           TeamMembershipStatus.ADMIN]
        if (tm.status == TeamMembershipStatus.DECLINED or
            (tm.status not in adminOrApproved and
             tm.team.subscriptionpolicy == TeamSubscriptionPolicy.OPEN)):
            return True
        else:
            return False

    def _getMembershipForUser(self):
        user = getUtility(ILaunchBag).user
        if user is None:
            return None
        return getUtility(ITeamMembershipSet).getByPersonAndTeam(
            user, self.context)

    def joinAllowed(self):
        """Return True if this is not a restricted team."""
        restricted = TeamSubscriptionPolicy.RESTRICTED
        return self.context.subscriptionpolicy != restricted

    def obfuscatedEmail(self):
        if self.context.preferredemail is not None:
            return obfuscateEmail(self.context.preferredemail.email)
        else:
            return None

    def htmlEmail(self):
        if self.context.preferredemail is not None:
            return convertToHtmlCode(self.context.preferredemail.email)
        else:
            return None

    def showSSHKeys(self):
        self.request.response.setHeader('Content-Type', 'text/plain')
        return "\n".join(["%s %s %s" % (key.keykind, key.keytext, key.comment)
                          for key in self.context.sshkeys])

    def sshkeysCount(self):
        return len(self.context.sshkeys)

    def gpgkeysCount(self):
        return self.context.gpgkeys.count()

    def signedcocsCount(self):
        return len(self.context.signedcocs)

    def performCoCChanges(self):
        """Make changes to code-of-conduct signature records for this
        person."""
        sig_ids = self.request.form.get("DEACTIVATE_SIGNATURE")

        if sig_ids is not None:
            sCoC_util = getUtility(ISignedCodeOfConductSet)

            # verify if we have multiple entries to deactive
            if not isinstance(sig_ids, list):
                sig_ids = [sig_ids]

            for sig_id in sig_ids:
                sig_id = int(sig_id)
                # Deactivating signature
                comment = 'Deactivated by Owner'
                sCoC_util.modifySignature(sig_id, self.user, comment, False)

            return True

    def processIRCForm(self):
        """Process the IRC nicknames form."""
        if self.request.method != "POST":
            # Nothing to do
            return ""

        form = self.request.form
        for ircnick in self.context.ircnicknames:
            # XXX: We're exposing IrcID IDs here because that's the only
            # unique column we have, so we don't have anything else that we
            # can use to make field names that allow us to uniquely identify
            # them. -- GuilhermeSalgado 25/08/2005
            if form.get('remove_%d' % ircnick.id):
                ircnick.destroySelf()
            else:
                nick = form.get('nick_%d' % ircnick.id)
                network = form.get('network_%d' % ircnick.id)
                if not (nick and network):
                    return "Neither Nickname nor Network can be empty."
                ircnick.nickname = nick
                ircnick.network = network

        nick = form.get('newnick')
        network = form.get('newnetwork')
        if nick or network:
            if nick and network:
                getUtility(IIrcIDSet).new(self.context, network, nick)
            else:
                self.newnick = nick
                self.newnetwork = network
                return "Neither Nickname nor Network can be empty."

        return ""

    def processJabberForm(self):
        """Process the Jabber ID form."""
        if self.request.method != "POST":
            # Nothing to do
            return ""

        form = self.request.form
        for jabber in self.context.jabberids:
            if form.get('remove_%s' % jabber.jabberid):
                jabber.destroySelf()
            else:
                jabberid = form.get('jabberid_%s' % jabber.jabberid)
                if not jabberid:
                    return "You cannot save an empty Jabber ID."
                jabber.jabberid = jabberid

        jabberid = form.get('newjabberid')
        if jabberid:
            jabberset = getUtility(IJabberIDSet)
            existingjabber = jabberset.getByJabberID(jabberid)
            if existingjabber is None:
                jabberset.new(self.context, jabberid)
            elif existingjabber.person != self.context:
                return ('The Jabber ID %s is already registered by '
                        '<a href="%s">%s</a>.'
                        % (jabberid, canonical_url(existingjabber.person),
                           cgi.escape(existingjabber.person.browsername)))
            else:
                return 'The Jabber ID %s already belongs to you.' % jabberid

        return ""

    def _sanitizeWikiURL(self, url):
        """Strip whitespaces and make sure :url ends in a single '/'."""
        if not url:
            return url
        return '%s/' % url.strip().rstrip('/')

    def processWikiForm(self):
        """Process the WikiNames form."""
        if self.request.method != "POST":
            # Nothing to do
            return ""

        form = self.request.form
        context = self.context
        wikinameset = getUtility(IWikiNameSet)
        ubuntuwikiname = form.get('ubuntuwikiname')
        existingwiki = wikinameset.getByWikiAndName(
            UBUNTU_WIKI_URL, ubuntuwikiname)

        if not ubuntuwikiname:
            return "Your Ubuntu WikiName cannot be empty."
        elif existingwiki is not None and existingwiki.person != context:
            return ('The Ubuntu WikiName %s is already registered by '
                    '<a href="%s">%s</a>.'
                    % (ubuntuwikiname, canonical_url(existingwiki.person),
                       cgi.escape(existingwiki.person.browsername)))
        context.ubuntuwiki.wikiname = ubuntuwikiname

        for w in context.otherwikis:
            # XXX: We're exposing WikiName IDs here because that's the only
            # unique column we have. If we don't do this we'll have to
            # generate the field names using the WikiName.wiki and
            # WikiName.wikiname columns (because these two columns make
            # another unique identifier for WikiNames), but that's tricky and
            # not worth the extra work. -- GuilhermeSalgado 25/08/2005
            if form.get('remove_%d' % w.id):
                w.destroySelf()
            else:
                wiki = self._sanitizeWikiURL(form.get('wiki_%d' % w.id))
                wikiname = form.get('wikiname_%d' % w.id)
                if not (wiki and wikiname):
                    return "Neither Wiki nor WikiName can be empty."
                # Try to make sure people will have only a single Ubuntu
                # WikiName registered. Although this is almost impossible
                # because they can do a lot of tricks with the URLs to make
                # them look different from UBUNTU_WIKI_URL but still point to
                # the same place.
                elif wiki == UBUNTU_WIKI_URL:
                    return "You cannot have two Ubuntu WikiNames."
                w.wiki = wiki
                w.wikiname = wikiname

        wiki = self._sanitizeWikiURL(form.get('newwiki'))
        wikiname = form.get('newwikiname')
        if wiki or wikiname:
            if wiki and wikiname:
                existingwiki = wikinameset.getByWikiAndName(wiki, wikiname)
                if existingwiki and existingwiki.person != context:
                    return ('The WikiName %s%s is already registered by '
                            '<a href="%s">%s</a>.'
                            % (wiki, wikiname,
                               canonical_url(existingwiki.person),
                               cgi.escape(existingwiki.person.browsername)))
                elif existingwiki:
                    return ('The WikiName %s%s already belongs to you.'
                            % (wiki, wikiname))
                elif wiki == UBUNTU_WIKI_URL:
                    return "You cannot have two Ubuntu WikiNames."
                wikinameset.new(context, wiki, wikiname)
            else:
                self.newwiki = wiki
                self.newwikiname = wikiname
                return "Neither Wiki nor WikiName can be empty."

        return ""

    # restricted set of methods to be proxied by form_action()
    permitted_actions = ['claim_gpg', 'deactivate_gpg', 'remove_gpgtoken',
                         'revalidate_gpg', 'add_ssh', 'remove_ssh']

    def form_action(self):
        if self.request.method != "POST":
            # Nothing to do
            return ''

        action = self.request.form.get('action')

        # primary check on restrict set of 'form-like' methods.
        if action and (action not in self.permitted_actions):
            return 'Forbidden Form Method: %s' % action

        # do not mask anything
        return getattr(self, action)()

    # XXX cprov 20050401
    # As "Claim GPG key" takes a lot of time, we should process it
    # throught the NotificationEngine.
    def claim_gpg(self):
        fingerprint = self.request.form.get('fingerprint')

        sanitisedfpr = sanitiseFingerprint(fingerprint)

        if not sanitisedfpr:
            return 'Malformed fingerprint:<code>%s</code>' % fingerprint

        fingerprint = sanitisedfpr

        gpgkeyset = getUtility(IGPGKeySet)

        if gpgkeyset.getByFingerprint(fingerprint):
            return 'OpenPGP key <code>%s</code> already imported' % fingerprint

        # import the key to the local keyring
        gpghandler = getUtility(IGPGHandler)
        result, key = gpghandler.retrieveKey(fingerprint)

        if not result:
            # use the content of 'key' for debug proposes; place it in a
            # blockquote because it often comes out empty.
            return (
                """Launchpad could not import your OpenPGP key.
                <ul>
                  <li>Did you enter your complete fingerprint correctly,
                  as produced by <kbd>gpg --fingerprint</kdb>?</li>
                  <li>Have you published your key to a public key
                  server, using <kbd>gpg --send-keys</kbd>?</li>
                  <li>If you have just published your key to the
                  keyserver, note that the keys take a while to be
                  synchronized to our internal keyserver.<br>Please wait at
                  least 30 minutes before attempting to import your
                  key.</li>
                </ul>
                <p>
                <blockquote>%s</blockquote>
                Try again later or cancel your request.""" % key)

        # revoked and expired keys can not be imported.
        if key.revoked:
            return (
                "The key %s cannot be validated because it has been "
                "publicly revoked. You will need to generate a new key "
                "(using <kbd>gpg --genkey</kbd>) and repeat the previous "
                "process to find and import the new key." % key.keyid)

        if key.expired:
            return (
                "The key %s cannot be validated because it has expired. "
                "You will need to generate a new key "
                "(using <kbd>gpg --genkey</kbd>) and repeat the previous "
                "process to find and import the new key." % key.keyid)

        self._validateGPG(key)

        return ('A message has been sent to <code>%s</code>, encrypted with '
                'the key <code>%s</code>. To confirm the key is yours, '
                'decrypt the message and follow the link inside.'
                % (self.context.preferredemail.email, key.displayname))

    def deactivate_gpg(self):
        key_ids = self.request.form.get('DEACTIVATE_GPGKEY')

        if key_ids is not None:
            comment = 'Key(s):<code>'

            # verify if we have multiple entries to deactive
            if not isinstance(key_ids, list):
                key_ids = [key_ids]

            gpgkeyset = getUtility(IGPGKeySet)

            for key_id in key_ids:
                gpgkeyset.deactivateGPGKey(key_id)
                gpgkey = gpgkeyset.get(key_id)
                comment += ' %s' % gpgkey.displayname

            comment += '</code> deactivated'
            flush_database_updates()
            return comment

        return 'No Key(s) selected for deactivation.'

    def remove_gpgtoken(self):
        tokenfprs = self.request.form.get('REMOVE_GPGTOKEN')

        if tokenfprs is not None:
            comment = 'Token(s) for:<code>'
            logintokenset = getUtility(ILoginTokenSet)

            # verify if we have multiple entries to deactive
            if not isinstance(tokenfprs, list):
                tokenfprs = [tokenfprs]

            for tokenfpr in tokenfprs:
                # retrieve token info
                logintokenset.deleteByFingerprintAndRequester(tokenfpr,
                                                              self.user)
                comment += ' %s' % tokenfpr

            comment += '</code> key fingerprint(s) deleted.'
            return comment

        return 'No Token(s) selected for deletion.'

    def revalidate_gpg(self):
        key_ids = self.request.form.get('REVALIDATE_GPGKEY')

        if key_ids is not None:
            found = []
            notfound = []
            # verify if we have multiple entries to deactive
            if not isinstance(key_ids, list):
                key_ids = [key_ids]

            gpghandler = getUtility(IGPGHandler)
            keyset = getUtility(IGPGKeySet)

            for key_id in key_ids:
                # retrieve key info from LP
                gpgkey = keyset.get(key_id)
                result, key = gpghandler.retrieveKey(gpgkey.fingerprint)
                if not result:
                    notfound.append(gpgkey.fingerprint)
                    continue
                self._validateGPG(key)
                found.append(key.displayname)

            comment = ''
            if len(found):
                comment += ('Key(s):<code>%s</code> revalidation email sent '
                            'to %s .' % (' '.join(found),
                                         self.context.preferredemail.email))
            if len(notfound):
                comment += ('Key(s):<code>%s</code> were skiped because could '
                            'not be retrived by Launchpad, verify if the key '
                            'is correctly published in the global key ring.' %
                            (''.join(notfound)))

            return comment

        return 'No Key(s) selected for revalidation.'

    def add_ssh(self):
        sshkey = self.request.form.get('sshkey')
        try:
            kind, keytext, comment = sshkey.split(' ', 2)
        except ValueError:
            return 'Invalid public key'

        if kind == 'ssh-rsa':
            keytype = SSHKeyType.RSA
        elif kind == 'ssh-dss':
            keytype = SSHKeyType.DSA
        else:
            return 'Invalid public key'

        getUtility(ISSHKeySet).new(self.user.id, keytype, keytext, comment)
        return 'SSH public key added.'

    def remove_ssh(self):
        try:
            id = self.request.form.get('key')
        except ValueError:
            return "Can't remove key that doesn't exist"

        sshkey = getUtility(ISSHKeySet).get(id)
        if sshkey is None:
            return "Can't remove key that doesn't exist"

        if sshkey.person != self.user:
            return "Cannot remove someone else's key"

        comment = sshkey.comment
        sshkey.destroySelf()
        return 'Key "%s" removed' % comment

    def _validateGPG(self, key):
        logintokenset = getUtility(ILoginTokenSet)
        bag = getUtility(ILaunchBag)

        preferredemail = bag.user.preferredemail.email
        login = bag.login

        if key.can_encrypt:
            tokentype = LoginTokenType.VALIDATEGPG
        else:
            tokentype = LoginTokenType.VALIDATESIGNONLYGPG
        
        token = logintokenset.new(self.context, login,
                                  preferredemail,
                                  tokentype,
                                  fingerprint=key.fingerprint)

        appurl = self.request.getApplicationURL()
        token.sendGPGValidationRequest(appurl, key)

    def processPasswordChangeForm(self):
        if self.request.method != 'POST':
            return

        form = self.request.form
        currentpassword = form.get('currentpassword')
        encryptor = getUtility(IPasswordEncryptor)
        if not encryptor.validate(currentpassword, self.context.password):
            self.message = (
                "The provided password doesn't match your current password.")
            return

        newpassword = form.get('newpassword')
        newpassword2 = form.get('newpassword2')
        if not (newpassword or newpassword2):
            self.message = "Your new password cannot be empty"
        elif newpassword != newpassword2:
            self.message = "Passwords did not match"
        else:
            self.context.password = encryptor.encrypt(newpassword)
            self.message = "Password changed successfully"


class PersonEditView(SQLObjectEditView):

    def changed(self):
        """Redirect to the person page.

        We need this because people can now change their names, and this will
        make their canonical_url to change too.
        """
        self.request.response.redirect(canonical_url(self.context))


class PersonEmblemView(GeneralFormView):

    # XXX: This is a workaround, while https://launchpad.net/malone/bugs/5792
    # isn't fixed. -- Guilherme Salgado, 2005-12-14
    __launchpad_facetname__ = 'overview'

    def process(self, emblem=None):
        # XXX use Bjorn's nice file upload widget when he writes it
        if emblem is not None:
            filename = self.request.get('field.emblem').filename
            content_type, encoding = guess_content_type(
                name=filename, body=emblem)
            self.context.emblem = getUtility(ILibraryFileAliasSet).create(
                name=filename, size=len(emblem), file=StringIO(emblem),
                contentType=content_type)
        self._nextURL = canonical_url(self.context)
        return 'Success'


class PersonHackergotchiView(GeneralFormView):

    # XXX: This is a workaround, while https://launchpad.net/malone/bugs/5792
    # isn't fixed. -- Guilherme Salgado, 2005-12-14
    __launchpad_facetname__ = 'overview'

    def process(self, hackergotchi=None):
        # XXX use Bjorn's nice file upload widget when he writes it
        if hackergotchi is not None:
            filename = self.request.get('field.hackergotchi').filename
            content_type, encoding = guess_content_type(
                name=filename, body=hackergotchi)
            hkg = getUtility(ILibraryFileAliasSet).create(
                name=filename, size=len(hackergotchi),
                file=StringIO(hackergotchi),
                contentType=content_type)
            self.context.hackergotchi = hkg
        self._nextURL = canonical_url(self.context)
        return 'Success'


class TeamJoinView(PersonView):

    def processForm(self):
        if self.request.method != "POST":
            # Nothing to do
            return

        user = getUtility(ILaunchBag).user

        if self.request.form.get('join') and self.userCanRequestToJoin():
            user.join(self.context)
            appurl = self.request.getApplicationURL()
            notify(JoinTeamRequestEvent(user, self.context, appurl))
            if (self.context.subscriptionpolicy ==
                TeamSubscriptionPolicy.MODERATED):
                self.request.response.addInfoNotification(
                    _('Subscription request pending approval.'))
            else:
                self.request.response.addInfoNotification(_(
                    'Successfully joined %s.' % self.context.displayname))
        self.request.response.redirect('./')


class TeamLeaveView(PersonView):

    def processForm(self):
        if self.request.method != "POST" or not self.userCanRequestToLeave():
            # Nothing to do
            return

        user = getUtility(ILaunchBag).user
        if self.request.form.get('leave'):
            user.leave(self.context)

        self.request.response.redirect('./')


class PersonEditEmailsView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.errormessage = None
        self.message = None
        self.badlyFormedEmail = None
        self.user = getUtility(ILaunchBag).user

    def unvalidatedAndGuessedEmails(self):
        """Return a Set containing all unvalidated and guessed emails."""
        emailset = sets.Set()
        emailset = emailset.union(
            [e.email for e in self.context.guessedemails])
        emailset = emailset.union([e for e in self.context.unvalidatedemails])
        return emailset

    def emailFormSubmitted(self):
        """Check if the user submitted the form and process it.

        Return True if the form was submitted or False if it was not.
        """
        form = self.request.form
        if "REMOVE_VALIDATED" in form:
            self._deleteValidatedEmail()
        elif "SET_PREFERRED" in form:
            self._setPreferred()
        elif "REMOVE_UNVALIDATED" in form:
            self._deleteUnvalidatedEmail()
        elif "VALIDATE" in form:
            self._validateEmail()
        elif "ADD_EMAIL" in form:
            self._addEmail()
        else:
            return False

        # Any self-posting page that updates the database and want to display
        # these updated values have to call flush_database_updates().
        flush_database_updates()
        return True

    def _validateEmail(self):
        """Send a validation url to the selected email address."""
        email = self.request.form.get("UNVALIDATED_SELECTED")
        if email is None:
            self.message = (
                "You must select the email address you want to confirm.")
            return

        token = getUtility(ILoginTokenSet).new(
                    self.context, getUtility(ILaunchBag).login, email,
                    LoginTokenType.VALIDATEEMAIL)
        token.sendEmailValidationRequest(self.request.getApplicationURL())

        self.message = ("A new email was sent to '%s' with instructions on "
                        "how to confirm that it belongs to you." % email)

    def _deleteUnvalidatedEmail(self):
        """Delete the selected email address, which is not validated.

        This email address can be either on the EmailAddress table marked with
        status new, or in the LoginToken table.
        """
        email = self.request.form.get("UNVALIDATED_SELECTED")
        if email is None:
            self.message = (
                "You must select the email address you want to remove.")
            return

        emailset = getUtility(IEmailAddressSet)
        logintokenset = getUtility(ILoginTokenSet)
        if email in [e.email for e in self.context.guessedemails]:
            emailaddress = emailset.getByEmail(email)
            # These asserts will fail only if someone poisons the form.
            assert emailaddress.person.id == self.context.id
            assert self.context.preferredemail.id != emailaddress.id
            emailaddress.destroySelf()

        if email in self.context.unvalidatedemails:
            logintokenset.deleteByEmailAndRequester(email, self.context)

        self.message = "The email address '%s' has been removed." % email

    def _deleteValidatedEmail(self):
        """Delete the selected email address, which is already validated."""
        email = self.request.form.get("VALIDATED_SELECTED")
        if email is None:
            self.message = (
                "You must select the email address you want to remove.")
            return

        emailset = getUtility(IEmailAddressSet)
        emailaddress = emailset.getByEmail(email)
        # These asserts will fail only if someone poisons the form.
        assert emailaddress.person.id == self.context.id
        assert self.context.preferredemail is not None
        if self.context.preferredemail == emailaddress:
            # This will happen only if a person is submitting a stale page.
            self.message = (
                "You can't remove %s because it's your contact email "
                "address." % self.context.preferredemail.email)
            return
        emailaddress.destroySelf()
        self.message = "The email address '%s' has been removed." % email

    def _addEmail(self):
        """Register a new email for the person in context.

        Check if the email is "well formed" and if it's not yet in our
        database and then register it to the person in context.
        """
        person = self.context
        emailset = getUtility(IEmailAddressSet)
        logintokenset = getUtility(ILoginTokenSet)
        newemail = self.request.form.get("newemail", "").strip().lower()
        if not valid_email(newemail):
            self.message = (
                "'%s' doesn't seem to be a valid email address." % newemail)
            self.badlyFormedEmail = newemail
            return

        email = emailset.getByEmail(newemail)
        if email is not None and email.person.id == person.id:
            self.message = (
                    "The email address '%s' is already registered as your "
                    "email address. This can be either because you already "
                    "added this email address before or because it have "
                    "been detected by our system as being yours. In case "
                    "it was detected by our systeam, it's probably shown "
                    "on this page and is waiting to be confirmed as being "
                    "yours." % email.email)
            return
        elif email is not None:
            # self.message is rendered using 'structure' on the page template,
            # so it's better to escape browsername because people can put
            # whatever they want in their name/displayname. On the other hand,
            # we don't need to escape email addresses because they are always
            # validated (which means they can't have html tags) before being
            # inserted in the database.
            owner = email.person
            browsername = cgi.escape(owner.browsername)
            merge_url = ('%s/+requestmerge?field.dupeaccount=%s'
                         % (canonical_url(getUtility(IPersonSet)), owner.name))
            self.message = (
                    "The email address '%s' is already registered by "
                    "<a href=\"%s\">%s</a>. If you think that is a "
                    "duplicated account, you can <a href=\"%s\">merge it</a> "
                    "into your account. "
                    % (email.email, canonical_url(owner), browsername,
                       merge_url))
            return

        token = logintokenset.new(
                    person, getUtility(ILaunchBag).login, newemail,
                    LoginTokenType.VALIDATEEMAIL)
        token.sendEmailValidationRequest(self.request.getApplicationURL())

        self.message = (
                "An email message was sent to '%s'. Follow the "
                "instructions in that message to confirm that the "
                "address is yours." % newemail)

    def _setPreferred(self):
        """Set the selected email as preferred for the person in context."""
        email = self.request.form.get("VALIDATED_SELECTED")
        if email is None:
            self.message = (
                "To set your contact address you have to choose an address "
                "from the list of confirmed addresses and click on Set as "
                "Contact Address.")
            return
        elif isinstance(email, list):
            self.message = (
                    "Only one email address can be set as your contact "
                    "address. Please select the one you want and click on "
                    "Set as Contact Address.")
            return

        emailset = getUtility(IEmailAddressSet)
        emailaddress = emailset.getByEmail(email)
        assert emailaddress.person.id == self.context.id, \
                "differing ids in emailaddress.person.id(%s,%d) == " \
                "self.context.id(%s,%d) (%s)" % \
                (emailaddress.person.name, emailaddress.person.id,
                 self.context.name, self.context.id, emailaddress.email)

        assert emailaddress.status == EmailAddressStatus.VALIDATED
        self.context.setPreferredEmail(emailaddress)
        self.message = "Your contact address has been changed to: %s" % email


class RequestPeopleMergeView(AddView):
    """The view for the page where the user asks a merge of two accounts.

    If the dupe account have only one email address we send a message to that
    address and then redirect the user to other page saying that everything
    went fine. Otherwise we redirect the user to another page where we list
    all email addresses owned by the dupe account and the user selects which
    of those (s)he wants to claim.
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request
        AddView.__init__(self, context, request)
        self._nextURL = '.'

    def nextURL(self):
        return self._nextURL

    def createAndAdd(self, data):
        kw = {}
        for key, value in data.items():
            kw[str(key)] = value

        user = getUtility(ILaunchBag).user
        dupeaccount = kw['dupeaccount']
        if dupeaccount == user:
            # Please, don't try to merge you into yourself.
            return

        emails = list(getUtility(IEmailAddressSet).getByPerson(dupeaccount))
        if len(emails) > 1:
            # The dupe account have more than one email address. Must redirect
            # the user to another page to ask which of those emails (s)he
            # wants to claim.
            self._nextURL = '+requestmerge-multiple?dupe=%d' % dupeaccount.id
            return

        assert len(emails) == 1
        email = emails[0]
        login = getUtility(ILaunchBag).login
        logintokenset = getUtility(ILoginTokenSet)
        token = logintokenset.new(user, login, email.email,
                                  LoginTokenType.ACCOUNTMERGE)
        dupename = dupeaccount.name
        sendMergeRequestEmail(
            token, dupename, self.request.getApplicationURL())
        self._nextURL = './+mergerequest-sent?dupe=%d' % dupeaccount.id


class AdminRequestPeopleMergeView(LaunchpadView):
    """The view for the page where an admin can merge two accounts."""

    def initialize(self):
        self.errormessages = [] 
        self.shouldShowConfirmationPage = False
        setUpWidgets(self, IAdminRequestPeopleMerge, IInputWidget)

    def processForm(self):
        form = self.request.form
        if 'continue' in form:
            # get data from the form
            self.dupe_account = self._getInputValue(self.dupe_account_widget)
            self.target_account = self._getInputValue(
                self.target_account_widget)
            if self.errormessages:
                return

            if self.dupe_account == self.target_account:
                self.errormessages.append(_(
                    "You can't merge %s into itself." 
                    % self.dupe_account.name))
                return

            emailset = getUtility(IEmailAddressSet) 
            self.emails = emailset.getByPerson(self.dupe_account)
            # display dupe_account email addresses and confirmation page
            self.shouldShowConfirmationPage = True

        elif 'merge' in form:
            self._performMerge()
            self.request.response.addInfoNotification(_(
                'Merge completed successfully.'))
            self.request.response.redirect(canonical_url(self.target_account))

    def _getInputValue(self, widget):
        name = self.request.get(widget.name)
        try:
            account = widget.getInputValue()
        except WidgetInputError:
            self.errormessages.append(_("You must choose an account.")) 
            return
        except ConversionError:
            self.errormessages.append(_("%s is an invalid account." % name)) 
            return
        return account

    def _performMerge(self):
        personset = getUtility(IPersonSet)
        emailset = getUtility(IEmailAddressSet)

        dupe_name = self.request.form.get('dupe_name')
        target_name = self.request.form.get('target_name')

        self.dupe_account = personset.getByName(dupe_name)
        self.target_account = personset.getByName(target_name) 

        emails = emailset.getByPerson(self.dupe_account)
        if emails:
            for email in emails:
                # transfer all emails from dupe to targe account
                email.person = self.target_account
                email.status = EmailAddressStatus.NEW

        getUtility(IPersonSet).merge(self.dupe_account, self.target_account)


class FinishedPeopleMergeRequestView:
    """A simple view for a page where we only tell the user that we sent the
    email with further instructions to complete the merge.
    
    This view is used only when the dupe account has a single email address.
    """

    def dupe_email(self):
        """Return the email address of the dupe account to which we sent the
        token.
        """
        dupe_account = getUtility(IPersonSet).get(self.request.get('dupe'))
        results = getUtility(IEmailAddressSet).getByPerson(dupe_account)
        assert len(results) == 1
        return results[0].email


class RequestPeopleMergeMultipleEmailsView:
    """A view for the page where the user asks a merge and the dupe account
    have more than one email address."""

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.formProcessed = False
        self.dupe = None
        self.notified_addresses = []

    def processForm(self):
        dupe = self.request.form.get('dupe')
        if dupe is None:
            # We just got redirected to this page and we don't have the dupe
            # hidden field in request.form.
            dupe = self.request.get('dupe')
            if dupe is None:
                return

        self.dupe = getUtility(IPersonSet).get(int(dupe))
        emailaddrset = getUtility(IEmailAddressSet)
        self.dupeemails = emailaddrset.getByPerson(self.dupe)

        if self.request.method != "POST":
            return

        self.formProcessed = True
        user = getUtility(ILaunchBag).user
        login = getUtility(ILaunchBag).login
        logintokenset = getUtility(ILoginTokenSet)

        ids = self.request.form.get("selected")
        if ids is not None:
            # We can have multiple email adressess selected, and in this case
            # ids will be a list. Otherwise ids will be str or int and we need
            # to make a list with that value to use in the for loop.
            if not isinstance(ids, list):
                ids = [ids]

            emailset = getUtility(IEmailAddressSet)
            for id in ids:
                email = emailset.get(id)
                assert email in self.dupeemails
                token = logintokenset.new(user, login, email.email,
                                          LoginTokenType.ACCOUNTMERGE)
                dupename = self.dupe.name
                url = self.request.getApplicationURL()
                sendMergeRequestEmail(token, dupename, url)
                self.notified_addresses.append(email.email)


def sendMergeRequestEmail(token, dupename, appurl):
    template = open(
        'lib/canonical/launchpad/emailtemplates/request-merge.txt').read()
    fromaddress = "Launchpad Account Merge <noreply@ubuntu.com>"

    replacements = {'longstring': token.token,
                    'dupename': dupename,
                    'requester': token.requester.name,
                    'requesteremail': token.requesteremail,
                    'toaddress': token.email,
                    'appurl': appurl}
    message = template % replacements

    subject = "Launchpad: Merge of Accounts Requested"
    simple_sendmail(fromaddress, str(token.email), subject, message)


class ObjectReassignmentView:
    """A view class used when reassigning an object that implements IHasOwner.

    By default we assume that the owner attribute is IHasOwner.owner and the
    vocabulary for the owner widget is ValidPersonOrTeam (which is the one
    used in IObjectReassignment). If any object has special needs, it'll be
    necessary to subclass ObjectReassignmentView and redefine the schema
    and/or ownerOrMaintainerAttr attributes.

    Subclasses can also specify a callback to be called after the reassignment
    takes place. This callback must accept three arguments (in this order):
    the object whose owner is going to be changed, the old owner and the new
    owner.

    Also, if the object for which you're using this view doesn't have a
    displayname or name attribute, you'll have to subclass it and define the
    contextName attribute in your subclass constructor.
    """

    ownerOrMaintainerAttr = 'owner'
    schema = IObjectReassignment
    callback = None

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user
        self.errormessage = ''
        self.ownerOrMaintainer = getattr(context, self.ownerOrMaintainerAttr)
        setUpWidgets(self, self.schema, IInputWidget)
        self.contextName = (getattr(self.context, 'displayname', None) or
                            getattr(self.context, 'name', None))

    def processForm(self):
        if self.request.method == 'POST':
            self.changeOwner()

    def changeOwner(self):
        """Change the owner of self.context to the one choosen by the user."""
        newOwner = self._getNewOwner()
        if newOwner is None:
            return

        oldOwner = getattr(self.context, self.ownerOrMaintainerAttr)
        setattr(self.context, self.ownerOrMaintainerAttr, newOwner)
        if callable(self.callback):
            self.callback(self.context, oldOwner, newOwner)
        self.request.response.redirect('.')

    def _getNewOwner(self):
        """Return the new owner for self.context, as specified by the user.

        If anything goes wrong, return None and assign an error message to
        self.errormessage to inform the user about what happened.
        """
        personset = getUtility(IPersonSet)
        request = self.request
        owner_name = request.form.get(self.owner_widget.name)
        if not owner_name:
            self.errormessage = (
                "You have to specify the name of the person/team that's "
                "going to be the new %s." % self.ownerOrMaintainerAttr)
            return None

        if request.form.get('existing') == 'existing':
            try:
                # By getting the owner using getInputValue() we make sure
                # it's valid according to the vocabulary of self.schema's
                # owner widget.
                owner = self.owner_widget.getInputValue()
            except WidgetInputError:
                self.errormessage = (
                    "The person/team named '%s' is not a valid owner for %s."
                    % (owner_name, self.contextName))
                return None
            except ConversionError:
                self.errormessage = (
                    "There's no person/team named '%s' in Launchpad."
                    % owner_name)
                return None
        else:
            if personset.getByName(owner_name):
                self.errormessage = (
                    "There's already a person/team with the name '%s' in "
                    "Launchpad. Please choose a different name or select "
                    "the option to make that person/team the new owner, "
                    "if that's what you want." % owner_name)
                return None

            if not valid_name(owner_name):
                self.errormessage = (
                    "'%s' is not a valid name for a team. Please make sure "
                    "it contains only the allowed characters and no spaces."
                    % owner_name)
                return None

            owner = personset.newTeam(
                self.user, owner_name, owner_name.capitalize())

        return owner


class TeamReassignmentView(ObjectReassignmentView):

    ownerOrMaintainerAttr = 'teamowner'
    schema = ITeamReassignment

    def __init__(self, context, request):
        ObjectReassignmentView.__init__(self, context, request)
        self.contextName = self.context.browsername
        self.callback = self._addOwnerAsMember

    def _addOwnerAsMember(self, team, oldOwner, newOwner):
        """Add the new and the old owners as administrators of the team.

        When a user creates a new team, he is added as an administrator of
        that team. To be consistent with this, we must make the new owner an
        administrator of the team. This rule is ignored only if the new owner
        is an inactive member of the team, as that means he's not interested
        in being a member. The same applies to the old owner.
        """
        # Both new and old owners won't be added as administrators of the team
        # only if they're inactive members. If they're either active or
        # proposed members they'll be made administrators of the team.
        if newOwner not in team.inactivemembers:
            team.addMember(newOwner)
        if oldOwner not in team.inactivemembers:
            team.addMember(oldOwner)

        # Need to flush all database updates, otherwise we won't see the
        # updated membership statuses in the rest of this method.
        flush_database_updates()
        if newOwner not in team.inactivemembers:
            team.setMembershipStatus(newOwner, TeamMembershipStatus.ADMIN)

        if oldOwner not in team.inactivemembers:
            team.setMembershipStatus(oldOwner, TeamMembershipStatus.ADMIN)

