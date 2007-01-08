# Copyright 2004 Canonical Ltd

__metaclass__ = type

__all__ = [
    'PersonNavigation',
    'TeamNavigation',
    'PersonSetNavigation',
    'PeopleContextMenu',
    'PersonFacets',
    'PersonBranchesMenu',
    'PersonBugsMenu',
    'PersonSpecsMenu',
    'PersonOverviewMenu',
    'TeamOverviewMenu',
    'BaseListView',
    'PeopleListView',
    'TeamListView',
    'UbunteroListView',
    'FOAFSearchView',
    'PersonClaimView',
    'PersonSpecWorkLoadView',
    'PersonSpecFeedbackView',
    'PersonChangePasswordView',
    'PersonEditView',
    'PersonEditHomePageView',
    'PersonEmblemView',
    'PersonAssignedBugTaskSearchListingView',
    'ReportedBugTaskSearchListingView',
    'BugContactPackageBugsSearchListingView',
    'SubscribedBugTaskSearchListingView',
    'PersonRdfView',
    'PersonView',
    'PersonTranslationView',
    'PersonGPGView',
    'TeamJoinView',
    'TeamLeaveView',
    'PersonEditEmailsView',
    'RequestPeopleMergeView',
    'AdminRequestPeopleMergeView',
    'FinishedPeopleMergeRequestView',
    'RequestPeopleMergeMultipleEmailsView',
    'ObjectReassignmentView',
    'TeamReassignmentView',
    'RedirectToAssignedBugsView',
    'PersonAddView',
    'PersonLanguagesView',
    'RedirectToEditLanguagesView',
    'PersonLatestTicketsView',
    'PersonSearchTicketsView',
    'PersonSupportMenu',
    'SearchAnsweredTicketsView',
    'SearchAssignedTicketsView',
    'SearchCommentedTicketsView',
    'SearchCreatedTicketsView',
    'SearchNeedAttentionTicketsView',
    'SearchSubscribedTicketsView',
    ]

import cgi
import urllib
from StringIO import StringIO

from zope.event import notify
from zope.app.form.browser import TextAreaWidget, SelectWidget
from zope.app.form.browser.add import AddView
from zope.app.form.utility import setUpWidgets
from zope.app.content_types import guess_content_type
from zope.app.form.interfaces import (
        IInputWidget, ConversionError, WidgetInputError)
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.component import getUtility
from zope.security.interfaces import Unauthorized

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.searchbuilder import any, NULL
from canonical.lp.dbschema import (
    LoginTokenType, SSHKeyType, EmailAddressStatus, TeamMembershipStatus,
    TeamSubscriptionPolicy, SpecificationFilter, TicketParticipation,
    PersonCreationRationale)

from canonical.widgets import PasswordChangeWidget
from canonical.cachedproperty import cachedproperty

from canonical.launchpad.interfaces import (
    ISSHKeySet, IPersonSet, IEmailAddressSet, IWikiNameSet, ICountry,
    IJabberIDSet, IIrcIDSet, ILaunchBag, ILoginTokenSet, IPasswordEncryptor,
    ISignedCodeOfConductSet, IGPGKeySet, IGPGHandler, UBUNTU_WIKI_URL,
    ITeamMembershipSet, IObjectReassignment, ITeamReassignment, IPollSubset,
    IPerson, ICalendarOwner, ITeam, ILibraryFileAliasSet, IPollSet,
    IAdminRequestPeopleMerge, NotFoundError, UNRESOLVED_BUGTASK_STATUSES,
    IPersonChangePassword, GPGKeyNotFoundError, UnexpectedFormData,
    ILanguageSet, IRequestPreferredLanguages, IPersonClaim, IPOTemplateSet,
    ILaunchpadRoot, INewPerson)

from canonical.launchpad.browser.bugtask import BugTaskSearchListingView
from canonical.launchpad.browser.specificationtarget import (
    HasSpecificationsView)
from canonical.launchpad.browser.cal import CalendarTraversalMixin
from canonical.launchpad.browser.tickettarget import SearchTicketsView

from canonical.launchpad.helpers import obfuscateEmail, convertToHtmlCode

from canonical.launchpad.validators.email import valid_email
from canonical.launchpad.validators.name import valid_name

from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, canonical_url, ContextMenu, ApplicationMenu,
    enabled_with_permission, Navigation, stepto, stepthrough, smartquote,
    GeneralFormView, LaunchpadEditFormView, LaunchpadFormView, action,
    custom_widget, RedirectionNavigation)

from canonical.launchpad.event.team import JoinTeamRequestEvent

from canonical.launchpad import _


class BranchTraversalMixin:

    @stepto('+branch')
    def traverse_branch(self):
        """Branch of this person or team for the specified product and
        branch names.

        For example:

        * '/~ddaa/+branch/bazaar/devel' points to the branch whose owner
          name is 'ddaa', whose product name is 'bazaar', and whose branch name
          is 'devel'.

        * '/~sabdfl/+branch/+junk/junkcode' points to the branch whose
          owner name is 'sabdfl', with no associated product, and whose branch
          name is 'junkcode'.
        """
        stepstogo = self.request.stepstogo
        product_name = stepstogo.consume()
        branch_name = stepstogo.consume()
        if product_name is not None and branch_name is not None:
            return self.context.getBranch(product_name, branch_name)
        raise NotFoundError


class PersonNavigation(Navigation, CalendarTraversalMixin,
                       BranchTraversalMixin):

    usedfor = IPerson

    def breadcrumb(self):
        return self.context.displayname


class TeamNavigation(Navigation, CalendarTraversalMixin,
                     BranchTraversalMixin):

    usedfor = ITeam

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


class PersonSetNavigation(RedirectionNavigation):

    usedfor = IPersonSet

    def breadcrumb(self):
        return 'People'

    @property
    def redirection_root_url(self):
        return canonical_url(getUtility(ILaunchpadRoot))

    def traverse(self, name):
        # Raise a 404 on an invalid Person name
        if self.context.getByName(name) is None:
            raise NotFoundError(name)
        # Redirect to /~name
        return RedirectionNavigation.traverse(self, '~' + name)
            
    @stepto('+me')
    def me(self):
        me = getUtility(ILaunchBag).user
        if me is None:
            raise Unauthorized("You need to be logged in to view this URL.")
        try:
            # Not a permanent redirect, as it depends on who is logged in
            self.redirection_status = 303
            return RedirectionNavigation.traverse(self, '~' + me.name)
        finally:
            self.redirection_status = 301


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

    enable_only = ['overview', 'bugs', 'support', 'specifications',
                   'branches', 'translations']

    def overview(self):
        text = 'Overview'
        summary = 'General information about %s' % self.context.browsername
        return Link('', text, summary)

    def bugs(self):
        text = 'Bugs'
        summary = (
            'Bug reports that %s is involved with' % self.context.browsername)
        return Link('+assignedbugs', text, summary)

    def specifications(self):
        text = 'Features'
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

    def branches(self):
        text = 'Code'
        summary = ('Bazaar Branches and revisions registered and authored '
                   'by %s' % self.context.browsername)
        return Link('+branches', text, summary)

    def support(self):
        text = 'Support'
        summary = (
            'Support requests that %s is involved with' %
            self.context.browsername)
        return Link('+tickets', text, summary)

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


class PersonBranchesMenu(ApplicationMenu):

    usedfor = IPerson

    facet = 'branches'

    links = ['authored', 'registered', 'subscribed', 'addbranch']

    def authored(self):
        text = 'Branches Authored'
        return Link('+authoredbranches', text, icon='branch')

    def registered(self):
        text = 'Branches Registered'
        return Link('+registeredbranches', text, icon='branch')

    def subscribed(self):
        text = 'Branches Subscribed'
        return Link('+subscribedbranches', text, icon='branch')

    def addbranch(self):
        text = 'Register Branch'
        return Link('+addbranch', text, icon='add')



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
    links = ['assignee', 'drafter', 'approver',
             'subscriber', 'registrant', 'feedback',
             'workload', 'roadmap']

    def registrant(self):
        text = 'Registrant'
        summary = 'List specs registered by %s' % self.context.browsername
        return Link('+specs?role=registrant', text, summary, icon='spec')

    def approver(self):
        text = 'Approver'
        summary = 'List specs with %s is supposed to approve' % (
            self.context.browsername)
        return Link('+specs?role=approver', text, summary, icon='spec')

    def assignee(self):
        text = 'Assignee'
        summary = 'List specs for which %s is the assignee' % (
            self.context.browsername)
        return Link('+specs?role=assignee', text, summary, icon='spec')

    def drafter(self):
        text = 'Drafter'
        summary = 'List specs drafted by %s' % self.context.browsername
        return Link('+specs?role=drafter', text, summary, icon='spec')

    def subscriber(self):
        text = 'Subscriber'
        return Link('+specs?role=subscriber', text, icon='spec')

    def feedback(self):
        text = 'Feedback requests'
        summary = 'List specs where feedback has been requested from %s' % (
            self.context.browsername)
        return Link('+specfeedback', text, summary, icon='info')

    def workload(self):
        text = 'Workload'
        summary = 'Show all specification work assigned'
        return Link('+specworkload', text, summary, icon='info')

    def roadmap(self):
        text = 'Roadmap'
        summary = 'Show recommended sequence of feature implementation'
        return Link('+roadmap', text, summary, icon='info')


class CommonMenuLinks:

    @enabled_with_permission('launchpad.Edit')
    def common_edithomepage(self):
        target = '+edithomepage'
        text = 'Home Page'
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
             'editlanguages', 'editwikinames', 'editircnicknames',
             'editjabberids', 'editpassword', 'editsshkeys', 'editpgpkeys',
             'codesofconduct', 'administer', 'common_packages']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        target = '+edit'
        text = 'Personal Details'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editlanguages(self):
        target = '+editlanguages'
        text = 'Preferred Languages'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editemailaddresses(self):
        target = '+editemails'
        text = 'E-mail Addresses'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editwikinames(self):
        target = '+editwikinames'
        text = 'Wiki Names'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editircnicknames(self):
        target = '+editircnicknames'
        text = 'IRC Nicknames'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editjabberids(self):
        target = '+editjabberids'
        text = 'Jabber IDs'
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
        text = 'SSH Keys'
        summary = (
            'Used if %s stores code on the Supermirror' %
            self.context.browsername)
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editpgpkeys(self):
        target = '+editpgpkeys'
        text = 'OpenPGP Keys'
        summary = 'Used for the Supermirror, and when maintaining packages'
        return Link(target, text, summary, icon='edit')

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

    @enabled_with_permission('launchpad.Edit')
    def editemblem(self):
        target = '+editemblem'
        text = 'Change Emblem'
        return Link(target, text, icon='edit')

    def members(self):
        target = '+members'
        text = 'Members'
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


class BaseListView:

    header = ""

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def _getBatchNavigator(self, results):
        return BatchNavigator(results, self.request)

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

    header = "People Launchpad knows about"

    def getList(self):
        return self.getPeopleList()


class TeamListView(BaseListView):

    header = "Teams registered in Launchpad"

    def getList(self):
        return self.getTeamsList()


class UbunteroListView(BaseListView):

    header = "Ubunteros registered in Launchpad"

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

        if not name:
            return None

        searchfor = self.request.get("searchfor")
        if searchfor == "peopleonly":
            results = getUtility(IPersonSet).findPerson(name)
        elif searchfor == "teamsonly":
            results = getUtility(IPersonSet).findTeam(name)
        else:
            results = getUtility(IPersonSet).find(name)

        return BatchNavigator(results, self.request)


class PersonAddView(LaunchpadFormView):
    """The page where users can create new Launchpad profiles."""

    label = "Create a new Launchpad profile"
    schema = INewPerson
    custom_widget('creation_comment', TextAreaWidget, height=5, width=60)

    @action(_("Create Profile"), name="create")
    def create_action(self, action, data):
        emailaddress = data['emailaddress']
        displayname = data['displayname']
        creation_comment = data['creation_comment']
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            emailaddress, PersonCreationRationale.USER_CREATED,
            displayname=displayname, comment=creation_comment,
            registrant=self.user)
        self.next_url = canonical_url(person)
        logintokenset = getUtility(ILoginTokenSet)
        token = logintokenset.new(
            requester=self.user, requesteremail=self.user.preferredemail.email,
            email=emailaddress, tokentype=LoginTokenType.NEWPROFILE)
        token.sendProfileCreatedEmail(person, creation_comment)


class PersonClaimView(LaunchpadFormView):
    """The page where a user can claim an unvalidated profile."""

    schema = IPersonClaim

    def validate(self, data):
        emailaddress = data.get('emailaddress')
        if emailaddress is None:
            self.setFieldError(
                'emailaddress', 'Please enter the email address')
            return

        email = getUtility(IEmailAddressSet).getByEmail(emailaddress)
        error = ""
        if email is None:
            # Email not registered in launchpad, ask the user to try another
            # one.
            error = ("We couldn't find this email address. Please try another "
                     "one that could possibly be associated with this profile. "
                     "Note that this profile's name (%s) was generated based "
                     "on the email address it's associated with."
                     % self.context.name)
        elif email.person != self.context:
            if email.person.is_valid_person:
                error = ("This email address is associated with yet another "
                         "Launchpad profile, which you seem to have used at "
                         "some point. If that's the case, you can "
                         '<a href="/people/+requestmerge?field.dupeaccount=%s">'
                         "combine this profile with the other one</a> (you'll "
                         "have to log in with the other profile first, "
                         "though). If that's not the case, please try with a "
                         "different email address."
                         % self.context.name)
            else:
                # There seems to be another unvalidated profile for you!
                error = ("Although this email address is not associated with "
                         "this profile, it's associated with yet another one. "
                         'You can <a href="%s/+claim">claim that other '
                         'profile</a> and then later '
                         '<a href="/people/+requestmerge">combine</a> both of '
                         'them into a single one.'
                         % canonical_url(email.person))
        else:
            # Yay! You got the right email this time.
            pass
        if error:
            self.setFieldError('emailaddress', error)

    @property
    def next_url(self):
        return canonical_url(self.context)

    @action(_("E-mail Me"), name="confirm")
    def confirm_action(self, action, data):
        email = data['emailaddress']
        token = getUtility(ILoginTokenSet).new(
            requester=None, requesteremail=None, email=email,
            tokentype=LoginTokenType.PROFILECLAIM)
        token.sendClaimProfileEmail()
        self.request.response.addInfoNotification(_(
            "An email message was sent to '%(email)s'. Follow the "
            "instructions in that message to finish claiming this "
            "profile."), email=email)


class RedirectToEditLanguagesView(LaunchpadView):
    """Redirect the logged in user to his +editlanguages page.

    This view should always be registered with a launchpad.AnyPerson
    permission, to make sure the user is logged in. It exists so that
    we can keep the /rosetta/prefs link working and also provide a link
    for non logged in users that will require them to login and them send
    them straight to the page they want to go.
    """

    def initialize(self):
        self.request.response.redirect(
            '%s/+editlanguages' % canonical_url(self.user))


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


class PersonSpecWorkLoadView(LaunchpadView):
    """View used to render the specification workload for a particular person.

    It shows the set of specifications with which this person has a role.
    """

    def initialize(self):
        assert IPerson.providedBy(self.context), (
            'PersonSpecWorkLoadView should be used only on an IPerson.')

    class PersonSpec:
        """One record from the workload list."""

        def __init__(self, spec, person):
            self.spec = spec
            self.assignee = spec.assignee == person
            self.drafter = spec.drafter == person
            self.approver = spec.approver == person

    @cachedproperty
    def workload(self):
        """This code is copied in large part from browser/sprint.py. It may
        be worthwhile refactoring this to use a common code base.

        Return a structure that lists the specs for which this person is the
        approver, the assignee or the drafter.
        """
        return [PersonSpecWorkLoadView.PersonSpec(spec, self.context)
                for spec in self.context.specifications()]


class PersonSpecFeedbackView(HasSpecificationsView):

    @cachedproperty
    def feedback_specs(self):
        filter = [SpecificationFilter.FEEDBACK]
        return self.context.specifications(filter=filter)


class ReportedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs reported by someone."""

    columns_to_show = ["id", "summary", "targetname", "importance", "status"]

    def search(self):
        return BugTaskSearchListingView.search(
            self, extra_params={'owner': self.context})

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs reported by %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs Reported by %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs reported by %s" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+reportedbugs"

    def shouldShowReporterWidget(self):
        """Should the reporter widget be shown on the advanced search page?"""
        return False


class BugContactPackageBugsSearchListingView(BugTaskSearchListingView):
    """Bugs reported on packages for a bug contact."""

    columns_to_show = ["id", "summary", "importance", "status"]

    @property
    def current_package(self):
        """Get the package whose bugs are currently being searched."""
        if not (
            self.distribution_widget.hasInput() and
            self.distribution_widget.getInputValue()):
            raise UnexpectedFormData("A distribution is required")
        if not (
            self.sourcepackagename_widget.hasInput() and
            self.sourcepackagename_widget.getInputValue()):
            raise UnexpectedFormData("A sourcepackagename is required")

        distribution = self.distribution_widget.getInputValue()
        return distribution.getSourcePackage(
            self.sourcepackagename_widget.getInputValue())

    def search(self, searchtext=None):
        distrosourcepackage = self.current_package
        return BugTaskSearchListingView.search(
            self, searchtext=searchtext, context=distrosourcepackage)

    def getPackageBugCounts(self):
        """Return a list of dicts used for rendering the package bug counts."""
        package_bug_counts = []

        for package in self.context.getBugContactPackages():
            package_bug_counts.append({
                'package_name': package.displayname,
                'package_search_url':
                    self.getBugContactPackageSearchURL(package),
                'open_bugs_count': package.open_bugtasks.count(),
                'open_bugs_url': self.getOpenBugsURL(package),
                'critical_bugs_count': package.critical_bugtasks.count(),
                'critical_bugs_url': self.getCriticalBugsURL(package),
                'unassigned_bugs_count': package.unassigned_bugtasks.count(),
                'unassigned_bugs_url': self.getUnassignedBugsURL(package),
                'inprogress_bugs_count': package.inprogress_bugtasks.count(),
                'inprogress_bugs_url': self.getInProgressBugsURL(package)
            })

        return package_bug_counts

    def getOtherBugContactPackageLinks(self):
        """Return a list of the other packages for a bug contact.

        This excludes the current package.
        """
        current_package = self.current_package

        other_packages = [
            package for package in self.context.getBugContactPackages()
            if package != current_package]

        package_links = []
        for other_package in other_packages:
            package_links.append({
                'title': other_package.displayname,
                'url': self.getBugContactPackageSearchURL(other_package)})

        return package_links

    def getExtraSearchParams(self):
        """Overridden from BugTaskSearchListingView, to filter the search."""
        search_params = {}

        if self.status_widget.hasInput():
            search_params['status'] = any(*self.status_widget.getInputValue())
        if self.unassigned_widget.hasInput():
            search_params['assignee'] = NULL

        return search_params

    def getBugContactPackageSearchURL(self, distributionsourcepackage=None,
                                      advanced=False, extra_params=None):
        """Construct a default search URL for a distributionsourcepackage.

        Optional filter parameters can be specified as a dict with the
        extra_params argument.
        """
        if distributionsourcepackage is None:
            distributionsourcepackage = self.current_package

        params = {
            "field.distribution": distributionsourcepackage.distribution.name,
            "field.sourcepackagename": distributionsourcepackage.name,
            "search": "Search"}

        if extra_params is not None:
            # We must UTF-8 encode searchtext to play nicely with
            # urllib.urlencode, because it may contain non-ASCII characters.
            if extra_params.has_key("field.searchtext"):
                extra_params["field.searchtext"] = \
                    extra_params["field.searchtext"].encode("utf8")

            params.update(extra_params)

        person_url = canonical_url(self.context)
        query_string = urllib.urlencode(sorted(params.items()), doseq=True)

        if advanced:
            return person_url + '/+packagebugs-search?advanced=1&%s' % query_string
        else:
            return person_url + '/+packagebugs-search?%s' % query_string

    def getBugContactPackageAdvancedSearchURL(self,
                                              distributionsourcepackage=None):
        """Construct the advanced search URL for a distributionsourcepackage."""
        return self.getBugContactPackageSearchURL(advanced=True)

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
            'field.status': [], 'field.importance': "Critical"}

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

    def shouldShowSearchWidgets(self):
        # XXX: It's not possible to search amongst the bugs on maintained
        # software, so for now I'll be simply hiding the search widgets.
        # -- Guilherme Salgado, 2005-11-05
        return False

    # Methods that customize the advanced search form.
    def getAdvancedSearchPageHeading(self):
        return "Bugs in %s: Advanced Search" % self.current_package.displayname

    def getAdvancedSearchButtonLabel(self):
        return "Search bugs in %s" % self.current_package.displayname

    def getSimpleSearchURL(self):
        return self.getBugContactPackageSearchURL()


class PersonAssignedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs assigned to someone."""

    context_parameter = 'assignee'

    columns_to_show = ["id", "summary", "targetname", "importance", "status"]

    def search(self):
        """Return the open bugs assigned to a person."""
        return BugTaskSearchListingView.search(
            self, extra_params={'assignee': self.context})

    def shouldShowAssigneeWidget(self):
        """Should the assignee widget be shown on the advanced search page?"""
        return False

    def shouldShowAssignedToTeamPortlet(self):
        """Should the team assigned bugs portlet be shown?"""
        return True

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs assigned to %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs Assigned to %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs assigned to %s" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be usedas an href to the simple search."""
        return canonical_url(self.context) + "/+assignedbugs"


class RedirectToAssignedBugsView:

    def __call__(self):
        self.request.response.redirect(
            canonical_url(self.context) + "/+assignedbugs")


class SubscribedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs someone is subscribed to."""

    columns_to_show = ["id", "summary", "targetname", "importance", "status"]

    def search(self):
        return BugTaskSearchListingView.search(
            self, extra_params={'subscriber': self.context})

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs %s is subscribed to" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs %s is Cc'd to: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs %s is Cc'd to" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+subscribedbugs"


class PersonLanguagesView(LaunchpadView):

    def initialize(self):
        request = self.request
        if (request.method == "POST" and "SAVE-LANGS" in request.form):
            self.submitLanguages()

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return IRequestPreferredLanguages(self.request).getPreferredLanguages()

    def visible_checked_languages(self):
        return self.user.languages

    def visible_unchecked_languages(self):
        common_languages = getUtility(ILanguageSet).common_languages
        return sorted(set(common_languages) - set(self.user.languages),
                      key=lambda x: x.englishname)

    def getRedirectionURL(self):
        request = self.request
        referrer = request.getHeader('referer')
        if referrer and referrer.startswith(request.getApplicationURL()):
            return referrer
        else:
            return ''

    def submitLanguages(self):
        '''Process a POST request to the language preference form.

        This list of languages submitted is compared to the the list of
        languages the user has, and the latter is matched to the former.
        '''

        all_languages = getUtility(ILanguageSet)
        old_languages = self.user.languages
        new_languages = []

        for key in all_languages.keys():
            if self.request.has_key(key) and self.request.get(key) == u'on':
                new_languages.append(all_languages[key])

        # Add languages to the user's preferences.
        for language in set(new_languages) - set(old_languages):
            self.user.addLanguage(language)
            self.request.response.addInfoNotification(
                "Added %(language)s to your preferred languages." %
                {'language' : language.englishname})

        # Remove languages from the user's preferences.
        for language in set(old_languages) - set(new_languages):
            self.user.removeLanguage(language)
            self.request.response.addInfoNotification(
                "Removed %(language)s from your preferred languages." %
                {'language' : language.englishname})

        redirection_url = self.request.get('redirection_url')
        if redirection_url:
            self.request.response.redirect(redirection_url)


class PersonView(LaunchpadView):
    """A View class used in almost all Person's pages."""

    def initialize(self):
        self.info_message = None
        self.error_message = None
        self._karma_categories = None

    @cachedproperty
    def openpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getOpenPolls()

    @cachedproperty
    def closedpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getClosedPolls()

    @cachedproperty
    def notyetopenedpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getNotYetOpenedPolls()

    def viewingOwnPage(self):
        return self.user == self.context

    def hasCurrentPolls(self):
        """Return True if this team has any non-closed polls."""
        assert self.context.isTeam()
        return bool(self.openpolls) or bool(self.notyetopenedpolls)

    def no_bounties(self):
        return not (self.context.ownedBounties or
            self.context.reviewerBounties or
            self.context.subscribedBounties or
            self.context.claimedBounties)

    def userIsOwner(self):
        """Return True if the user is the owner of this Team."""
        if self.user is None:
            return False

        return self.user.inTeam(self.context.teamowner)

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
        if self.user is None:
            return None
        return getUtility(ITeamMembershipSet).getByPersonAndTeam(
            self.user, self.context)

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
        """Return a data structure used for display of raw SSH keys"""
        self.request.response.setHeader('Content-Type', 'text/plain')
        keys = []
        for key in self.context.sshkeys:
            if key.keytype == SSHKeyType.DSA:
                type_name = 'ssh-dss'
            elif key.keytype == SSHKeyType.RSA:
                type_name = 'ssh-rsa'
            else:
                type_name = 'Unknown key type'
            keys.append("%s %s %s" % (type_name, key.keytext, key.comment))
        return "\n".join(keys)

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
    permitted_actions = ['add_ssh', 'remove_ssh']

    def form_action(self):
        if self.request.method != "POST":
            # Nothing to do
            return ''

        action = self.request.form.get('action')

        if action and (action not in self.permitted_actions):
            raise UnexpectedFormData("Action was not defined")

        getattr(self, action)()

    def add_ssh(self):
        sshkey = self.request.form.get('sshkey')
        try:
            kind, keytext, comment = sshkey.split(' ', 2)
        except ValueError:
            self.error_message = 'Invalid public key'
            return

        if not (kind and keytext and comment):
            self.error_message = 'Invalid public key'
            return

        if kind == 'ssh-rsa':
            keytype = SSHKeyType.RSA
        elif kind == 'ssh-dss':
            keytype = SSHKeyType.DSA
        else:
            self.error_message = 'Invalid public key'
            return

        getUtility(ISSHKeySet).new(self.user, keytype, keytext, comment)
        self.info_message = 'SSH public key added.'

    def remove_ssh(self):
        key_id = self.request.form.get('key')
        if not key_id:
            raise UnexpectedFormData('SSH Key was not defined')

        sshkey = getUtility(ISSHKeySet).getByID(key_id)
        if sshkey is None:
            self.error_message = "Cannot remove a key that doesn't exist"
            return

        if sshkey.person != self.user:
            raise UnexpectedFormData("Cannot remove someone else's key")

        comment = sshkey.comment
        sshkey.destroySelf()
        self.info_message = 'Key "%s" removed' % comment


class PersonTranslationView(LaunchpadView):
    """View for translation-related Person pages."""
    @cachedproperty
    def batchnav(self):
        batchnav = BatchNavigator(self.context.translation_history,
                                  self.request)
        # XXX: See bug 60320. Because of a template reference to
        # pofile.potemplate.displayname, it would be ideal to also
        # prejoin inside translation_history:
        #   potemplate.potemplatename
        #   potemplate.productseries
        #   potemplate.productseries.product
        #   potemplate.distrorelease
        #   potemplate.distrorelease.distribution
        #   potemplate.sourcepackagename
        # However, a list this long may be actually suggesting that
        # displayname be cached in a table field; particularly given the
        # fact that it won't be altered very often. At any rate, the
        # code below works around this by caching all the templates in
        # one shot. The list() ensures that we materialize the query
        # before passing it on to avoid reissuing it. Note also that the
        # fact that we iterate over currentBatch() here means that the
        # translation_history query is issued again. Tough luck.
        #   -- kiko, 2006-03-17
        ids = set(record.pofile.potemplate.id
                  for record in batchnav.currentBatch())
        if ids:
            cache = list(getUtility(IPOTemplateSet).getByIDs(ids))
        return batchnav

    @cachedproperty
    def translation_groups(self):
        """Return translation groups a person is a member of."""
        return list(self.context.translation_groups)


class PersonGPGView(LaunchpadView):
    """View for the GPG-related actions for a Person

    Supports claiming (importing) a key, validating it and deactivating
    it. Also supports removing the token generated for validation (in
    the case you want to give up on importing the key).
    """
    key = None
    fingerprint = None

    key_ok = False
    invalid_fingerprint = False
    key_retrieval_failed = False
    key_already_imported = False

    error_message = None
    info_message = None

    def keyserver_url(self):
        assert self.fingerprint
        return getUtility(IGPGHandler).getURLForKeyInServer(self.fingerprint)

    def form_action(self):
        permitted_actions = [
            'claim_gpg', 'deactivate_gpg', 'remove_gpgtoken', 'reactivate_gpg']
        if self.request.method != "POST":
            return ''
        action = self.request.form.get('action')
        if action and (action not in permitted_actions):
            raise UnexpectedFormData("Action was not defined")
        getattr(self, action)()

    def claim_gpg(self):
        # XXX cprov 20050401 As "Claim GPG key" takes a lot of time, we
        # should process it throught the NotificationEngine.
        gpghandler = getUtility(IGPGHandler)
        fingerprint = self.request.form.get('fingerprint')
        self.fingerprint = gpghandler.sanitizeFingerprint(fingerprint)

        if not self.fingerprint:
            self.invalid_fingerprint = True
            return

        gpgkeyset = getUtility(IGPGKeySet)
        if gpgkeyset.getByFingerprint(self.fingerprint):
            self.key_already_imported = True
            return

        try:
            key = gpghandler.retrieveKey(self.fingerprint)
        except GPGKeyNotFoundError:
            self.key_retrieval_failed = True
            return

        self.key = key
        if not key.expired and not key.revoked:
            self._validateGPG(key)
            self.key_ok = True

    def deactivate_gpg(self):
        key_ids = self.request.form.get('DEACTIVATE_GPGKEY')

        if key_ids is None:
            self.error_message = 'No Key(s) selected for deactivation.'
            return

        # verify if we have multiple entries to deactive
        if not isinstance(key_ids, list):
            key_ids = [key_ids]

        gpgkeyset = getUtility(IGPGKeySet)

        deactivated_keys = []
        for key_id in key_ids:
            gpgkey = gpgkeyset.get(key_id)
            if gpgkey is None:
                continue
            if gpgkey.owner != self.user:
                self.error_message = "Cannot deactivate someone else's key"
                return
            gpgkey.active = False
            deactivated_keys.append(gpgkey.displayname)

        flush_database_updates()
        self.info_message = (
            'Deactivated key(s): %s' % ", ".join(deactivated_keys))

    def remove_gpgtoken(self):
        token_fingerprints = self.request.form.get('REMOVE_GPGTOKEN')

        if token_fingerprints is None:
            self.error_message = 'No key(s) pending validation selected.'
            return

        logintokenset = getUtility(ILoginTokenSet)
        if not isinstance(token_fingerprints, list):
            token_fingerprints = [token_fingerprints]

        cancelled_fingerprints = []
        for fingerprint in token_fingerprints:
            logintokenset.deleteByFingerprintRequesterAndType(
                fingerprint, self.user, LoginTokenType.VALIDATEGPG)
            logintokenset.deleteByFingerprintRequesterAndType(
                fingerprint, self.user, LoginTokenType.VALIDATESIGNONLYGPG)
            cancelled_fingerprints.append(fingerprint)

        self.info_message = ('Cancelled validation of key(s): %s'
                             % ", ".join(cancelled_fingerprints))

    def reactivate_gpg(self):
        key_ids = self.request.form.get('REACTIVATE_GPGKEY')

        if key_ids is None:
            self.error_message = 'No Key(s) selected for reactivation.'
            return

        found = []
        notfound = []
        # verify if we have multiple entries to deactive
        if not isinstance(key_ids, list):
            key_ids = [key_ids]

        gpghandler = getUtility(IGPGHandler)
        keyset = getUtility(IGPGKeySet)

        for key_id in key_ids:
            gpgkey = keyset.get(key_id)
            try:
                key = gpghandler.retrieveKey(gpgkey.fingerprint)
            except GPGKeyNotFoundError:
                notfound.append(gpgkey.fingerprint)
            else:
                found.append(key.displayname)
                self._validateGPG(key)

        comments = []
        if len(found) > 0:
            comments.append(
                'An email was sent to %s with instructions to reactivate '
                'the following key(s): %s'
                % (self.context.preferredemail.email, ', '.join(found)))
        if len(notfound) > 0:
            if len(notfound) == 1:
                comments.append(
                    'Launchpad failed to retrieve the following key from '
                    'the keyserver: %s. Please make sure this key is '
                    'published in a keyserver (such as '
                    '<a href="http://pgp.mit.edu">pgp.mit.edu</a>) before '
                    'trying to reactivate it again.' % (', '.join(notfound)))
            else:
                comments.append(
                    'Launchpad failed to retrieve the following keys from '
                    'the keyserver: %s. Please make sure these keys '
                    'are published in a keyserver (such as '
                    '<a href="http://pgp.mit.edu">pgp.mit.edu</a>) before '
                    'trying to reactivate them again.' % (', '.join(notfound)))

        self.info_message = '\n<br>\n'.join(comments)

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

        token.sendGPGValidationRequest(key)


class PersonChangePasswordView(LaunchpadFormView):

    label = "Change your password"
    schema = IPersonChangePassword
    field_names = ['currentpassword', 'password']
    custom_widget('password', PasswordChangeWidget)

    @property
    def next_url(self):
        return canonical_url(self.context)

    def validate(self, form_values):
        currentpassword = form_values.get('currentpassword')
        encryptor = getUtility(IPasswordEncryptor)
        if not encryptor.validate(currentpassword, self.context.password):
            self.setFieldError('currentpassword', _(
                "The provided password doesn't match your current password."))

    @action(_("Change Password"), name="submit")
    def submit_action(self, action, data):
        password = data['password']
        self.context.password = password
        self.request.response.addInfoNotification(_(
            "Password changed successfully"))


class BasePersonEditView(LaunchpadEditFormView):

    schema = IPerson
    field_names = []

    @action(_("Save"), name="save")
    def action_save(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)


class PersonEditHomePageView(BasePersonEditView):

    field_names = ['homepage_content']
    custom_widget(
        'homepage_content', TextAreaWidget, height=30, width=30)


class PersonEditView(BasePersonEditView):

    field_names = ['displayname', 'name', 'hide_email_addresses', 'timezone',
                   'gotchi']
    custom_widget('timezone', SelectWidget, size=15)


class PersonEmblemView(GeneralFormView):

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


class TeamJoinView(PersonView):

    def processForm(self):
        if self.request.method != "POST":
            # Nothing to do
            return

        user = self.user

        if self.request.form.get('join') and self.userCanRequestToJoin():
            user.join(self.context)
            notify(JoinTeamRequestEvent(user, self.context))
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

        if self.request.form.get('leave'):
            self.user.leave(self.context)

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
        emailset = set()
        emailset = emailset.union(e.email for e in self.context.guessedemails)
        emailset = emailset.union(e for e in self.context.unvalidatedemails)
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
            logintokenset.deleteByEmailRequesterAndType(
                email, self.context, LoginTokenType.VALIDATEEMAIL)

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
            owner_name = urllib.quote(owner.name)
            merge_url = ('%s/+requestmerge?field.dupeaccount=%s'
                         % (canonical_url(getUtility(IPersonSet)), owner_name))
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

        if emailaddress.status != EmailAddressStatus.VALIDATED:
            self.message = "%s is already set as your contact address." % email
            return
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

    _nextURL = '.'

    def nextURL(self):
        return self._nextURL

    def createAndAdd(self, data):
        user = getUtility(ILaunchBag).user
        dupeaccount = data['dupeaccount']
        if dupeaccount == user:
            # Please, don't try to merge you into yourself.
            return

        emails = getUtility(IEmailAddressSet).getByPerson(dupeaccount)
        emails_count = emails.count()
        if emails_count > 1:
            # The dupe account have more than one email address. Must redirect
            # the user to another page to ask which of those emails (s)he
            # wants to claim.
            self._nextURL = '+requestmerge-multiple?dupe=%d' % dupeaccount.id
            return

        assert emails_count == 1
        email = emails[0]
        login = getUtility(ILaunchBag).login
        logintokenset = getUtility(ILoginTokenSet)
        token = logintokenset.new(user, login, email.email,
                                  LoginTokenType.ACCOUNTMERGE)

        # XXX: SteveAlexander: an experiment to see if this improves
        #      problems with merge people tests.  2006-03-07
        import canonical.database.sqlbase
        canonical.database.sqlbase.flush_database_updates()
        token.sendMergeRequestEmail()
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


class FinishedPeopleMergeRequestView(LaunchpadView):
    """A simple view for a page where we only tell the user that we sent the
    email with further instructions to complete the merge.

    This view is used only when the dupe account has a single email address.
    """
    def initialize(self):
        user = getUtility(ILaunchBag).user
        try:
            dupe_id = int(self.request.get('dupe'))
        except (ValueError, TypeError):
            self.request.response.redirect(canonical_url(user))
            return

        dupe_account = getUtility(IPersonSet).get(dupe_id)
        results = getUtility(IEmailAddressSet).getByPerson(dupe_account)

        result_count = results.count()
        if not result_count:
            # The user came back to visit this page with nothing to
            # merge, so we redirect him away to somewhere useful.
            self.request.response.redirect(canonical_url(user))
            return
        assert result_count == 1
        self.dupe_email = results[0].email

    def render(self):
        if self.dupe_email:
            return LaunchpadView.render(self)
        else:
            return ''


class RequestPeopleMergeMultipleEmailsView:
    """A view for the page where the user asks a merge and the dupe account
    have more than one email address."""

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.form_processed = False
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

        self.form_processed = True
        user = getUtility(ILaunchBag).user
        login = getUtility(ILaunchBag).login
        logintokenset = getUtility(ILoginTokenSet)

        emails = self.request.form.get("selected")
        if emails is not None:
            # We can have multiple email adressess selected, and in this case
            # emails will be a list. Otherwise it will be a string and we need
            # to make a list with that value to use in the for loop.
            if not isinstance(emails, list):
                emails = [emails]

            for email in emails:
                emailaddress = emailaddrset.getByEmail(email)
                assert emailaddress in self.dupeemails
                token = logintokenset.new(
                    user, login, emailaddress.email,
                    LoginTokenType.ACCOUNTMERGE)
                token.sendMergeRequestEmail()
                self.notified_addresses.append(emailaddress.email)


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
    contextName property in your subclass.
    """

    ownerOrMaintainerAttr = 'owner'
    schema = IObjectReassignment
    callback = None

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user
        self.errormessage = ''
        setUpWidgets(self, self.schema, IInputWidget)

    @property
    def ownerOrMaintainer(self):
        return getattr(self.context, self.ownerOrMaintainerAttr)

    @property
    def contextName(self):
        return self.context.displayname or self.context.name

    nextUrl = '.'

    def processForm(self):
        if self.request.method == 'POST':
            self.changeOwner()

    def changeOwner(self):
        """Change the owner of self.context to the one choosen by the user."""
        newOwner = self._getNewOwner()
        if newOwner is None:
            return

        if not self.isValidOwner(newOwner):
            return

        oldOwner = getattr(self.context, self.ownerOrMaintainerAttr)
        setattr(self.context, self.ownerOrMaintainerAttr, newOwner)
        if callable(self.callback):
            self.callback(self.context, oldOwner, newOwner)
        self.request.response.redirect(self.nextUrl)

    def isValidOwner(self, newOwner):
        """Check whether the new owner is acceptable for the context object.

        If it's not acceptable, return False and assign an error message to
        self.errormessage to inform the user.
        """
        return True

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
        self.callback = self._addOwnerAsMember

    @property
    def contextName(self):
        return self.context.browsername

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


class PersonLatestTicketsView(LaunchpadView):
    """View used by the porlet displaying the latest requests made by
    a person.
    """

    @cachedproperty
    def getLatestTickets(self, quantity=5):
        """Return <quantity> latest tickets created for this target. """
        return self.context.searchTickets(
            participation=TicketParticipation.OWNER)[:quantity]


class PersonSearchTicketsView(SearchTicketsView):
    """View used to search and display tickets in which an IPerson is
    involved.
    """

    displayTargetColumn = True

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests involving $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests involving $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchAnsweredTicketsView(SearchTicketsView):
    """View used to search and display tickets answered by an IPerson."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(participation=TicketParticipation.ANSWERER)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests answered by $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests answered by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchAssignedTicketsView(SearchTicketsView):
    """View used to search and display tickets assigned to an IPerson."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(participation=TicketParticipation.ASSIGNEE)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests assigned to $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests assigned to $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchCommentedTicketsView(SearchTicketsView):
    """View used to search and display tickets commented on by an IPerson."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(participation=TicketParticipation.COMMENTER)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests commented on by $name ',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests commented on by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchCreatedTicketsView(SearchTicketsView):
    """View used to search and display tickets created by an IPerson."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(participation=TicketParticipation.OWNER)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests created by $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests created by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchNeedAttentionTicketsView(SearchTicketsView):
    """View used to search and display tickets needing an IPerson attention."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(needs_attention=True)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests needing $name attention',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests need $name attention.',
                 mapping=dict(name=self.context.displayname))


class SearchSubscribedTicketsView(SearchTicketsView):
    """View used to search and display tickets subscribed to by an IPerson."""

    displayTargetColumn = True

    def getDefaultFilter(self):
        """See SearchTicketsView."""
        return dict(participation=TicketParticipation.SUBSCRIBER)

    @property
    def pageheading(self):
        """See SearchTicketsView."""
        return _('Support requests $name is subscribed to',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See SearchTicketsView."""
        return _('No support requests subscribed to by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class PersonSupportMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'support'
    links = ['answered', 'assigned', 'created', 'commented', 'need_attention',
             'subscribed']

    def answered(self):
        summary = 'Support requests answered by %s' % self.context.displayname
        return Link('+answeredtickets', 'Answered', summary, icon='ticket')

    def assigned(self):
        summary = 'Support requests assigned to %s' % self.context.displayname
        return Link('+assignedtickets', 'Assigned', summary, icon='ticket')

    def created(self):
        summary = 'Support requests created by %s' % self.context.displayname
        return Link('+createdtickets', 'Created', summary, icon='ticket')

    def commented(self):
        summary = 'Support requests commented on by %s' % (
            self.context.displayname)
        return Link('+commentedtickets', 'Commented', summary, icon='ticket')

    def need_attention(self):
        summary = 'Support requests needing %s attention' % (
            self.context.displayname)
        return Link('+needattentiontickets', 'Need Attention', summary,
                    icon='ticket')

    def subscribed(self):
        text = 'Subscribed'
        summary = 'Support requests subscribed to by %s' % (
                self.context.displayname)
        return Link('+subscribedtickets', text, summary, icon='ticket')
