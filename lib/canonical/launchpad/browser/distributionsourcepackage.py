# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'DistributionSourcePackageNavigation',
    'DistributionSourcePackageSOP',
    'DistributionSourcePackageFacets',
    'DistributionSourcePackageNavigation',
    'DistributionSourcePackageOverviewMenu',
    'DistributionSourcePackageBugContactsView'
    ]

from operator import attrgetter

from zope.formlib import form
from zope.schema import Choice, List
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.interfaces import (
    IDistributionSourcePackage, IDistributionSourcePackageManageBugcontacts,
    DuplicateBugContactError)
from canonical.launchpad.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.launchpad import StructuralObjectPresentation
from canonical.launchpad.browser.questiontarget import (
        QuestionTargetFacetMixin, QuestionTargetTraversalMixin)
from canonical.launchpad.webapp import (
    action, StandardLaunchpadFacets, Link, ApplicationMenu,
    GetitemNavigation, canonical_url, redirection, LaunchpadFormView,
    custom_widget)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.widgets import LabeledMultiCheckBoxWidget

class DistributionSourcePackageSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return self.context.distribution.title + ' source package:'

    def getMainHeading(self):
        return self.context.name

    def listChildren(self, num):
        # XXX mpt 2006-10-04: package releases, most recent first
        return self.context.releases

    def listAltChildren(self, num):
        return None


class DistributionSourcePackageFacets(QuestionTargetFacetMixin,
                                      StandardLaunchpadFacets):

    usedfor = IDistributionSourcePackage
    enable_only = ['overview', 'bugs', 'answers']


class DistributionSourcePackageOverviewMenu(ApplicationMenu):

    usedfor = IDistributionSourcePackage
    facet = 'overview'
    links = ['managebugcontacts']

    def managebugcontacts(self):
        return Link('+subscribe', 'Bugmail Settings', icon='edit')


class DistributionSourcePackageBugsMenu(DistributionSourcePackageOverviewMenu):

    usedfor = IDistributionSourcePackage
    facet = 'bugs'
    links = ['managebugcontacts']


class DistributionSourcePackageNavigation(GetitemNavigation,
    BugTargetTraversalMixin, QuestionTargetTraversalMixin):

    usedfor = IDistributionSourcePackage

    redirection("+editbugcontact", "+subscribe")

    def breadcrumb(self):
        return self.context.sourcepackagename.name


class DistributionSourcePackageBugContactsView(LaunchpadFormView):
    """View class for bug contact settings."""

    schema = IDistributionSourcePackageManageBugcontacts

    custom_widget('bugmail_contact_team', LabeledMultiCheckBoxWidget)
    custom_widget('remove_other_bugcontacts', LabeledMultiCheckBoxWidget)

    def setUpFields(self):
        """See LaunchpadFormView."""
        LaunchpadFormView.setUpFields(self)
        team_contacts = self._createTeamBugContactsField()
        if team_contacts:
            self.form_fields += form.Fields(team_contacts)
        if self.userIsDistributionDriver():
            add_other = form.Fields(self._createAddOtherBugContactField())
            self.form_fields += add_other
            remove_other = self._createRemoveOtherBugContactsField()
            if remove_other:
                self.form_fields += form.Fields(remove_other)

    def _createTeamBugContactsField(self):
        """Create field with a list of the teams the user is a member of.

        Return a FormField instance, if the user is a member of at least
        one team, else return None.
        """
        teams = list(self.user_teams)
        if not teams:
            return None
        teams.sort(key=attrgetter('displayname'))
        terms = [
            SimpleTerm(team, team.name, team.displayname)
            for team in teams]
        team_vocabulary = SimpleVocabulary(terms)
        team_contacts_field = List(
            __name__='bugmail_contact_team',
            title=u'Team bug contacts',
            description=(u'You can add the teams of which you are an '
                          'administrator to the bug contacts.'),
            value_type=Choice(vocabulary=team_vocabulary),
            required=False)
        return form.FormField(
            team_contacts_field,
            custom_widget=self.custom_widgets['bugmail_contact_team'])

    def _createRemoveOtherBugContactsField(self):
        """Create a field with a list of subscribers.

        Return a FormField instance, if bug contacts exist that can
        be removed, else return None.
        """
        teams = set(self.user_teams)
        other_contacts = set(
            contact.bugcontact for contact in self.context.bugcontacts)

        # Teams and the current user have their own UI elements. Remove
        # them to avoid duplicates.
        other_contacts.difference_update(teams)
        other_contacts.discard(self.user)

        if not other_contacts:
            return None

        other_contacts = sorted(other_contacts, key=attrgetter('displayname'))

        terms = [
            SimpleTerm(contact, contact.name, contact.displayname)
            for contact in other_contacts]
        
        contacts_vocabulary = SimpleVocabulary(terms)
        other_contacts_field = List(
            __name__='remove_other_bugcontacts',
            title=u'Remove bug contacts',
            value_type=Choice(vocabulary=contacts_vocabulary),
            required=False)
        return form.FormField(
            other_contacts_field,
            custom_widget=self.custom_widgets['remove_other_bugcontacts'])

    def _createAddOtherBugContactField(self):
        """Create a field for a new bug contact."""
        new_bugcontact_field = Choice(
            __name__='new_bugcontact',
            title=u'Add other bug contact',
            vocabulary='ValidPersonOrTeam',
            required=False)
        return form.FormField(new_bugcontact_field)

    @property
    def initial_values(self):
        """See `GeneralFormView`."""
        teams = set(self.user_teams)
        bugcontact_teams = set(team
                               for team in teams
                               if self.context.isBugContact(team))
        return {
            'make_me_a_bugcontact': self.currentUserIsBugContact(),
            'bugmail_contact_team': bugcontact_teams
            }
    
    def currentUserIsBugContact(self):
        """Return True, if the current user is a bug contact."""
        return self.context.isBugContact(self.user)

    @action(u'Save these changes', name='save')
    def save_action(self, action, data):
        """Process the bugmail settings submitted by the user."""
        self._handleUserSubscription(data)
        self._handleTeamSubscriptions(data)
        self._handleDriverChanges(data)
        self.next_url = canonical_url(self.context) + '/+subscribe'

    def _handleUserSubscription(self, data):
        """Process the bugmail settings for the use."""
        pkg = self.context
        # pkg.addBugContact raises an exception if called for an already
        # subscribed person, and pkg.removeBugContact raises an exception
        # for a non-subscriber, hence call these methods only, if the
        # subscription status changed.
        is_bugcontact = self.context.isBugContact(self.user)
        make_bugcontact = data['make_me_a_bugcontact']
        if (not is_bugcontact) and make_bugcontact:
            pkg.addBugContact(self.user)
            self.request.response.addNotification(
                "You have been successfully subscribed to all bugmail "
                "for %s" % pkg.displayname)
        elif is_bugcontact and not make_bugcontact:
            pkg.removeBugContact(self.user)
            self.request.response.addNotification(
                "You have been removed as a bug contact for %s. You "
                "will no longer automatically receive bugmail for this "
                "package." % pkg.displayname)
        else:
            # The subscription status did not change: nothing to do.
            pass

    def _handleTeamSubscriptions(self, data):
        """Process the bugmail settings for teams."""
        form_selected_teams = data.get('bugmail_contact_team', None)
        if form_selected_teams is None:
            return

        pkg = self.context
        teams = set(self.user_teams)
        form_selected_teams = teams & set(form_selected_teams)
        subscriptions = set(
            team for team in teams if self.context.isBugContact(team))

        for team in form_selected_teams - subscriptions:
            pkg.addBugContact(team)
            self.request.response.addNotification(
                'The "%s" team was successfully subscribed to all bugmail '
                'in %s' % (team.displayname, self.context.displayname))

        for team in subscriptions - form_selected_teams:
            pkg.removeBugContact(team)
            self.request.response.addNotification(
                'The "%s" team was successfully unsubscribed from all '
                'bugmail in %s' % (
                    team.displayname, self.context.displayname))

    def _handleDriverChanges(self, data):
        """Process the bugmail settings for other persons."""
        if not self.userIsDistributionDriver():
            return

        pkg = self.context
        new_bugcontact = data['new_bugcontact']
        if new_bugcontact is not None:
            try:
                pkg.addBugContact(new_bugcontact)
            except DuplicateBugContactError:
                self.request.response.addNotification(
                    '"%s" is already subscribed to all bugmail '
                    'in %s' % (
                        new_bugcontact.displayname,
                        self.context.displayname))
            else:
                self.request.response.addNotification(
                    '"%s" was successfully subscribed to all bugmail '
                    'in %s' % (
                        new_bugcontact.displayname,
                        self.context.displayname))

        contacts_to_remove = data.get('remove_other_bugcontacts', [])
        for contact in contacts_to_remove:
            pkg.removeBugContact(contact)
            self.request.response.addNotification(
                '"%s" was successfully unsubscribed from all bugmail '
                'in %s' % (
                    contact.displayname, self.context.displayname))

    def userIsDistributionDriver(self):
        """Has the current user driver permissions?"""
        return check_permission("launchpad.Driver", self.context.distribution)

    @cachedproperty
    def user_teams(self):
        """Return the teams that the current user is an administrator of."""
        return self.user.getAdministratedTeams()

