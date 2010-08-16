# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'TeamMembership',
    'TeamMembershipSet',
    'TeamParticipation',
    ]

from datetime import datetime, timedelta
import itertools
import pytz

from storm.locals import Store

from zope.component import getUtility
from zope.interface import implements

from sqlobject import ForeignKey, StringCol

from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.database.sqlbase import (
    flush_database_updates, SQLBase, sqlvalues)
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol

from canonical.config import config

from canonical.launchpad.mail import format_address, simple_sendmail
from canonical.launchpad.mailnotification import MailWrapper
from canonical.launchpad.helpers import (
    get_contact_email_addresses, get_email_template)
from lp.registry.interfaces.person import validate_public_person
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import (
    IPersonSet, TeamMembershipRenewalPolicy)
from lp.registry.interfaces.teammembership import (
    CyclicalTeamMembershipError, DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT,
    ITeamMembership, ITeamMembershipSet, ITeamParticipation,
    TeamMembershipStatus, UserCannotChangeMembershipSilently)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.tales import DurationFormatterAPI


ACTIVE_STATES = [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED]


class TeamMembership(SQLBase):
    """See `ITeamMembership`."""

    implements(ITeamMembership)

    _table = 'TeamMembership'
    _defaultOrder = 'id'

    team = ForeignKey(dbName='team', foreignKey='Person', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    last_changed_by = ForeignKey(
        dbName='last_changed_by', foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    proposed_by = ForeignKey(
        dbName='proposed_by', foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    acknowledged_by = ForeignKey(
        dbName='acknowledged_by', foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    reviewed_by = ForeignKey(
        dbName='reviewed_by', foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    status = EnumCol(
        dbName='status', notNull=True, enum=TeamMembershipStatus)
    # XXX: salgado, 2008-03-06: Need to rename datejoined and dateexpires to
    # match their db names.
    datejoined = UtcDateTimeCol(dbName='date_joined', default=None)
    dateexpires = UtcDateTimeCol(dbName='date_expires', default=None)
    date_created = UtcDateTimeCol(default=UTC_NOW)
    date_proposed = UtcDateTimeCol(default=None)
    date_acknowledged = UtcDateTimeCol(default=None)
    date_reviewed = UtcDateTimeCol(default=None)
    date_last_changed = UtcDateTimeCol(default=None)
    last_change_comment = StringCol(default=None)
    proponent_comment = StringCol(default=None)
    acknowledger_comment = StringCol(default=None)
    reviewer_comment = StringCol(default=None)

    def isExpired(self):
        """See `ITeamMembership`."""
        return self.status == TeamMembershipStatus.EXPIRED

    def canBeRenewedByMember(self):
        """See `ITeamMembership`."""
        ondemand = TeamMembershipRenewalPolicy.ONDEMAND
        admin = TeamMembershipStatus.APPROVED
        approved = TeamMembershipStatus.ADMIN
        date_limit = datetime.now(pytz.UTC) + timedelta(
            days=DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT)
        return (self.status in (admin, approved)
                and self.team.renewal_policy == ondemand
                and self.dateexpires is not None
                and self.dateexpires < date_limit)

    def sendSelfRenewalNotification(self):
        """See `ITeamMembership`."""
        team = self.team
        member = self.person
        assert team.renewal_policy == TeamMembershipRenewalPolicy.ONDEMAND

        from_addr = format_address(
            team.displayname, config.canonical.noreply_from_address)
        replacements = {'member_name': member.unique_displayname,
                        'team_name': team.unique_displayname,
                        'team_url': canonical_url(team),
                        'dateexpires': self.dateexpires.strftime('%Y-%m-%d')}
        subject = '%s extended their membership' % member.name
        template = get_email_template('membership-member-renewed.txt')
        admins_addrs = self.team.getTeamAdminsEmailAddresses()
        for address in admins_addrs:
            recipient = getUtility(IPersonSet).getByEmail(address)
            replacements['recipient_name'] = recipient.displayname
            msg = MailWrapper().format(
                template % replacements, force_wrap=True)
            simple_sendmail(from_addr, address, subject, msg)

    def sendAutoRenewalNotification(self):
        """See `ITeamMembership`."""
        team = self.team
        member = self.person
        assert team.renewal_policy == TeamMembershipRenewalPolicy.AUTOMATIC

        from_addr = format_address(
            team.displayname, config.canonical.noreply_from_address)
        replacements = {'member_name': member.unique_displayname,
                        'team_name': team.unique_displayname,
                        'team_url': canonical_url(team),
                        'dateexpires': self.dateexpires.strftime('%Y-%m-%d')}
        subject = '%s renewed automatically' % member.name

        if member.isTeam():
            member_addrs = get_contact_email_addresses(member.teamowner)
            template_name = 'membership-auto-renewed-bulk.txt'
        else:
            template_name = 'membership-auto-renewed-personal.txt'
            member_addrs = get_contact_email_addresses(member)
        template = get_email_template(template_name)
        for address in member_addrs:
            recipient = getUtility(IPersonSet).getByEmail(address)
            replacements['recipient_name'] = recipient.displayname
            msg = MailWrapper().format(
                template % replacements, force_wrap=True)
            simple_sendmail(from_addr, address, subject, msg)

        template_name = 'membership-auto-renewed-bulk.txt'
        admins_addrs = self.team.getTeamAdminsEmailAddresses()
        admins_addrs = set(admins_addrs).difference(member_addrs)
        template = get_email_template(template_name)
        for address in admins_addrs:
            recipient = getUtility(IPersonSet).getByEmail(address)
            replacements['recipient_name'] = recipient.displayname
            msg = MailWrapper().format(
                template % replacements, force_wrap=True)
            simple_sendmail(from_addr, address, subject, msg)

    def canChangeStatusSilently(self, user):
        """Ensure that the user is in the Launchpad Administrators group before
           silently making changes to their membership status."""
        return user.inTeam(getUtility(ILaunchpadCelebrities).admin)

    def canChangeExpirationDate(self, person):
        """See `ITeamMembership`."""
        person_is_admin = self.team in person.getAdministratedTeams()
        if (person.inTeam(self.team.teamowner) or
                person.inTeam(getUtility(ILaunchpadCelebrities).admin)):
            # The team owner and Launchpad admins can change the expiration
            # date of anybody's membership.
            return True
        elif person_is_admin and person != self.person:
            # A team admin can only change other member's expiration date.
            return True
        else:
            return False

    def setExpirationDate(self, date, user):
        """See `ITeamMembership`."""
        if date == self.dateexpires:
            return

        assert self.canChangeExpirationDate(user), (
            "This user can't change this membership's expiration date.")
        self._setExpirationDate(date, user)

    def _setExpirationDate(self, date, user):
        UTC = pytz.timezone('UTC')
        assert date is None or date.date() >= datetime.now(UTC).date(), (
            "The given expiration date must be None or be in the future: %s"
            % date.strftime('%Y-%m-%d'))
        self.dateexpires = date
        self.last_changed_by = user

    def sendExpirationWarningEmail(self):
        """See `ITeamMembership`."""
        assert self.dateexpires is not None, (
            'This membership has no expiration date')
        assert self.dateexpires > datetime.now(pytz.timezone('UTC')), (
            "This membership's expiration date must be in the future: %s"
            % self.dateexpires.strftime('%Y-%m-%d'))
        if self.team.renewal_policy == TeamMembershipRenewalPolicy.AUTOMATIC:
            # An email will be sent later by handleMembershipsExpiringToday()
            # when the membership is automatically renewed.
            raise AssertionError(
                'Team %r with automatic renewals should not send expiration '
                'warnings.' % self.team.name)
        member = self.person
        team = self.team
        if member.isTeam():
            recipient = member.teamowner
            templatename = 'membership-expiration-warning-bulk.txt'
            subject = '%s will expire soon from %s' % (member.name, team.name)
        else:
            recipient = member
            templatename = 'membership-expiration-warning-personal.txt'
            subject = 'Your membership in %s is about to expire' % team.name

        if team.renewal_policy == TeamMembershipRenewalPolicy.ONDEMAND:
            how_to_renew = (
                "If you want, you can renew this membership at\n"
                "<%s/+expiringmembership/%s>"
                % (canonical_url(member), team.name))
        elif not self.canChangeExpirationDate(recipient):
            admins_names = []
            admins = team.getDirectAdministrators()
            assert admins.count() >= 1
            if admins.count() == 1:
                admin = admins[0]
                how_to_renew = (
                    "To prevent this membership from expiring, you should "
                    "contact the\nteam's administrator, %s.\n<%s>"
                    % (admin.unique_displayname, canonical_url(admin)))
            else:
                for admin in admins:
                    # Do not tell the member to contact himself when he can't
                    # extend his membership.
                    if admin != member:
                        admins_names.append(
                            "%s <%s>" % (admin.unique_displayname,
                                         canonical_url(admin)))

                how_to_renew = (
                    "To prevent this membership from expiring, you should "
                    "get in touch\nwith one of the team's administrators:\n")
                how_to_renew += "\n".join(admins_names)
        else:
            how_to_renew = (
                "To stay a member of this team you should extend your "
                "membership at\n<%s/+member/%s>"
                % (canonical_url(team), member.name))

        to_addrs = get_contact_email_addresses(recipient)
        if len(to_addrs) == 0:
            # The user does not have a preferred email address, he was
            # probably suspended.
            return
        formatter = DurationFormatterAPI(
            self.dateexpires - datetime.now(pytz.timezone('UTC')))
        replacements = {
            'recipient_name': recipient.displayname,
            'member_name': member.unique_displayname,
            'team_url': canonical_url(team),
            'how_to_renew': how_to_renew,
            'team_name': team.unique_displayname,
            'expiration_date': self.dateexpires.strftime('%Y-%m-%d'),
            'approximate_duration': formatter.approximateduration()}

        msg = get_email_template(templatename) % replacements
        from_addr = format_address(
            team.displayname, config.canonical.noreply_from_address)
        simple_sendmail(from_addr, to_addrs, subject, msg)

    def setStatus(self, status, user, comment=None, silent=False):
        """See `ITeamMembership`."""
        if status == self.status:
            return False

        if silent and not self.canChangeStatusSilently(user):
            raise UserCannotChangeMembershipSilently(
                "Only Launchpad administrators may change membership statuses "
                "silently.")

        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        expired = TeamMembershipStatus.EXPIRED
        declined = TeamMembershipStatus.DECLINED
        deactivated = TeamMembershipStatus.DEACTIVATED
        proposed = TeamMembershipStatus.PROPOSED
        invited = TeamMembershipStatus.INVITED
        invitation_declined = TeamMembershipStatus.INVITATION_DECLINED

        self.person.clearInTeamCache()

        # Make sure the transition from the current status to the given one
        # is allowed. All allowed transitions are in the TeamMembership spec.
        state_transition = {
            admin: [approved, expired, deactivated],
            approved: [admin, expired, deactivated],
            deactivated: [proposed, approved, admin, invited],
            expired: [proposed, approved, admin, invited],
            proposed: [approved, admin, declined],
            declined: [proposed, approved, admin],
            invited: [approved, admin, invitation_declined],
            invitation_declined: [invited, approved, admin]}
        assert self.status in state_transition, (
            "Unknown status: %s" % self.status.name)
        assert status in state_transition[self.status], (
            "Bad state transition from %s to %s"
            % (self.status.name, status.name))

        if status in ACTIVE_STATES and self.team in self.person.allmembers:
            raise CyclicalTeamMembershipError(
                "Cannot make %(person)s a member of %(team)s because "
                "%(team)s is a member of %(person)s."
                % dict(person=self.person.name, team=self.team.name))

        old_status = self.status
        self.status = status

        now = datetime.now(pytz.timezone('UTC'))
        if status in [proposed, invited]:
            self.proposed_by = user
            self.proponent_comment = comment
            self.date_proposed = now
        elif ((status in ACTIVE_STATES and old_status not in ACTIVE_STATES)
              or status == declined):
            self.reviewed_by = user
            self.reviewer_comment = comment
            self.date_reviewed = now
            if self.datejoined is None and status in ACTIVE_STATES:
                # This is the first time this membership is made active.
                self.datejoined = now
        else:
            # No need to set proponent or reviewer.
            pass

        if old_status == invited:
            # This member has been invited by an admin and is now accepting or
            # declining the invitation.
            self.acknowledged_by = user
            self.date_acknowledged = now
            self.acknowledger_comment = comment

        self.last_changed_by = user
        self.last_change_comment = comment
        self.date_last_changed = now

        if status in ACTIVE_STATES:
            _fillTeamParticipation(self.person, self.team)
        elif old_status in ACTIVE_STATES:
            _cleanTeamParticipation(self.person, self.team)
        else:
            # Changed from an inactive state to another inactive one, so no
            # need to fill/clean the TeamParticipation table.
            pass

        # Flush all updates to ensure any subsequent calls to this method on
        # the same transaction will operate on the correct data.  That is the
        # case with our script to expire team memberships.
        flush_database_updates()

        # When a member proposes himself, a more detailed notification is
        # sent to the team admins by a subscriber of JoinTeamEvent; that's
        # why we don't send anything here.
        if ((self.person != self.last_changed_by or self.status != proposed)
            and not silent):
            self._sendStatusChangeNotification(old_status)
        return True

    def _sendStatusChangeNotification(self, old_status):
        """Send a status change notification to all team admins and the
        member whose membership's status changed.
        """
        team = self.team
        member = self.person
        reviewer = self.last_changed_by
        from_addr = format_address(
            team.displayname, config.canonical.noreply_from_address)
        new_status = self.status
        admins_emails = team.getTeamAdminsEmailAddresses()
        # self.person might be a team, so we can't rely on its preferredemail.
        member_email = get_contact_email_addresses(member)
        # Make sure we don't send the same notification twice to anybody.
        for email in member_email:
            if email in admins_emails:
                admins_emails.remove(email)

        if reviewer != member:
            reviewer_name = reviewer.unique_displayname
        else:
            # The user himself changed his membership.
            reviewer_name = 'the user himself'

        if self.last_change_comment:
            comment = ("\n%s said:\n %s\n" % (
                reviewer.displayname, self.last_change_comment.strip()))
        else:
            comment = ""

        replacements = {
            'member_name': member.unique_displayname,
            'recipient_name': member.displayname,
            'team_name': team.unique_displayname,
            'team_url': canonical_url(team),
            'old_status': old_status.title,
            'new_status': new_status.title,
            'reviewer_name': reviewer_name,
            'comment': comment}

        template_name = 'membership-statuschange'
        subject = ('Membership change: %(member)s in %(team)s'
                   % {'member': member.name, 'team': team.name})
        if new_status == TeamMembershipStatus.EXPIRED:
            template_name = 'membership-expired'
            subject = '%s expired from team' % member.name
        elif (new_status == TeamMembershipStatus.APPROVED and
              old_status != TeamMembershipStatus.ADMIN):
            if old_status == TeamMembershipStatus.INVITED:
                subject = ('Invitation to %s accepted by %s'
                           % (member.name, reviewer.name))
                template_name = 'membership-invitation-accepted'
            elif old_status == TeamMembershipStatus.PROPOSED:
                subject = '%s approved by %s' % (member.name, reviewer.name)
            else:
                subject = '%s added by %s' % (member.name, reviewer.name)
        elif new_status == TeamMembershipStatus.INVITATION_DECLINED:
            subject = ('Invitation to %s declined by %s'
                       % (member.name, reviewer.name))
            template_name = 'membership-invitation-declined'
        elif new_status == TeamMembershipStatus.DEACTIVATED:
            subject = '%s deactivated by %s' % (member.name, reviewer.name)
        elif new_status == TeamMembershipStatus.ADMIN:
            subject = '%s made admin by %s' % (member.name, reviewer.name)
        elif new_status == TeamMembershipStatus.DECLINED:
            subject = '%s declined by %s' % (member.name, reviewer.name)
        else:
            # Use the default template and subject.
            pass

        if admins_emails:
            admins_template = get_email_template(
                "%s-bulk.txt" % template_name)
            for address in admins_emails:
                recipient = getUtility(IPersonSet).getByEmail(address)
                replacements['recipient_name'] = recipient.displayname
                msg = MailWrapper().format(
                    admins_template % replacements, force_wrap=True)
                simple_sendmail(from_addr, address, subject, msg)

        # The member can be a team without any members, and in this case we
        # won't have a single email address to send this notification to.
        if member_email and reviewer != member:
            if member.isTeam():
                template = '%s-bulk.txt' % template_name
            else:
                template = '%s-personal.txt' % template_name
            member_template = get_email_template(template)
            for address in member_email:
                recipient = getUtility(IPersonSet).getByEmail(address)
                replacements['recipient_name'] = recipient.displayname
                msg = MailWrapper().format(
                    member_template % replacements, force_wrap=True)
                simple_sendmail(from_addr, address, subject, msg)


class TeamMembershipSet:
    """See `ITeamMembershipSet`."""

    implements(ITeamMembershipSet)

    _defaultOrder = ['Person.displayname', 'Person.name']

    def new(self, person, team, status, user, dateexpires=None, comment=None):
        """See `ITeamMembershipSet`."""
        proposed = TeamMembershipStatus.PROPOSED
        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        invited = TeamMembershipStatus.INVITED
        assert status in [proposed, approved, admin, invited]

        person.clearInTeamCache()

        tm = TeamMembership(
            person=person, team=team, status=status, dateexpires=dateexpires)

        now = datetime.now(pytz.timezone('UTC'))
        tm.proposed_by = user
        tm.date_proposed = now
        tm.proponent_comment = comment
        if status in [approved, admin]:
            tm.datejoined = now
            tm.reviewed_by = user
            tm.date_reviewed = now
            tm.reviewer_comment = comment
            _fillTeamParticipation(person, team)

        return tm

    def handleMembershipsExpiringToday(self, reviewer):
        """See `ITeamMembershipSet`."""
        memberships = self.getMembershipsToExpire()
        for membership in memberships:
            team = membership.team
            if team.renewal_policy == TeamMembershipRenewalPolicy.AUTOMATIC:
                # Keep the same status, change the expiration date and send a
                # notification explaining the membership has been renewed.
                assert (team.defaultrenewalperiod is not None
                        and team.defaultrenewalperiod > 0), (
                    'Teams with a renewal policy of AUTOMATIC must specify '
                    'a default renewal period greater than 0.')
                membership.dateexpires += timedelta(
                    days=team.defaultrenewalperiod)
                membership.sendAutoRenewalNotification()
            else:
                membership.setStatus(TeamMembershipStatus.EXPIRED, reviewer)

    def getByPersonAndTeam(self, person, team):
        """See `ITeamMembershipSet`."""
        return TeamMembership.selectOneBy(person=person, team=team)

    def getMembershipsToExpire(self, when=None, exclude_autorenewals=False):
        """See `ITeamMembershipSet`."""
        if when is None:
            when = datetime.now(pytz.timezone('UTC'))
        conditions = [
            TeamMembership.dateexpires <= when,
            TeamMembership.status.is_in(
                [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED])
            ]
        if exclude_autorenewals:
            # Avoid circular import.
            from lp.registry.model.person import Person
            conditions.append(TeamMembership.team == Person.id)
            conditions.append(
                Person.renewal_policy != TeamMembershipRenewalPolicy.AUTOMATIC)
        return IStore(TeamMembership).find(TeamMembership, *conditions)


class TeamParticipation(SQLBase):
    implements(ITeamParticipation)

    _table = 'TeamParticipation'

    team = ForeignKey(dbName='team', foreignKey='Person', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)


def _cleanTeamParticipation(person, team):
    """Remove relevant entries in TeamParticipation for <person> and <team>.

    Remove all tuples "person, team" from TeamParticipation for the given
    person and team (together with all its superteams), unless this person is
    an indirect member of the given team. More information on how to use the
    TeamParticipation table can be found in the TeamParticipationUsage spec or
    the teammembership.txt system doctest.
    """
    query = """
        SELECT EXISTS(
            SELECT 1 FROM TeamParticipation
            WHERE person = %(person_id)s AND team IN (
                    SELECT person
                    FROM TeamParticipation JOIN Person ON (person = Person.id)
                    WHERE team = %(team_id)s
                        AND person NOT IN (%(team_id)s, %(person_id)s)
                        AND teamowner IS NOT NULL
                 )
        )
        """ % dict(team_id=team.id, person_id=person.id)
    store = Store.of(person)
    (result, ) = store.execute(query).get_one()
    if result:
        # The person is a participant in this team by virtue of a membership
        # in another one, so don't attempt to remove anything.
        return

    # First of all, we remove <person> from <team> (and its superteams).
    _removeParticipantFromTeamAndSuperTeams(person, team)
    if not person.is_team:
        # Nothing else to do.
        return

    store = Store.of(person)

    # Clean the participation of all our participant subteams, that are
    # not a direct members of the target team.
    query = """
        -- All of my participant subteams...
        SELECT person
        FROM TeamParticipation JOIN Person ON (person = Person.id)
        WHERE team = %(person_id)s AND person != %(person_id)s
            AND teamowner IS NOT NULL
        EXCEPT
        -- that aren't a direct member of the team.
        SELECT person
        FROM TeamMembership
        WHERE team = %(team_id)s AND status IN %(active_states)s
        """ % dict(
            person_id=person.id, team_id=team.id,
            active_states=sqlvalues(ACTIVE_STATES)[0])

    # Avoid circular import.
    from lp.registry.model.person import Person
    for subteam in store.find(Person, "id IN (%s)" % query):
        _cleanTeamParticipation(subteam, team)

    # Then clean-up all the non-team participants. We can remove those
    # in a single query when the team graph is up to date.
    _removeAllIndividualParticipantsFromTeamAndSuperTeams(person, team)


def _removeParticipantFromTeamAndSuperTeams(person, team):
    """Remove participation of person in team.

    If <person> is a participant (that is, has a TeamParticipation entry)
    of any team that is a subteam of <team>, then <person> should be kept as
    a participant of <team> and (as a consequence) all its superteams.
    Otherwise, <person> is removed from <team> and we repeat this process for
    each superteam of <team>.
    """
    # Check if the person is a member of the given team through another team.
    query = """
        SELECT EXISTS(
            SELECT 1
            FROM TeamParticipation, TeamMembership
            WHERE
                TeamMembership.team = %(team_id)s AND
                TeamMembership.person = TeamParticipation.team AND
                TeamParticipation.person = %(person_id)s AND
                TeamMembership.status IN %(active_states)s)
        """ % dict(team_id=team.id, person_id=person.id,
                   active_states=sqlvalues(ACTIVE_STATES)[0])
    store = Store.of(person)
    (result, ) = store.execute(query).get_one()
    if result:
        # The person is a participant by virtue of a membership on another
        # team, so don't remove.
        return
    store.find(TeamParticipation, (
        (TeamParticipation.team == team) &
        (TeamParticipation.person == person))).remove()

    for superteam in _getSuperTeamsExcludingDirectMembership(person, team):
        _removeParticipantFromTeamAndSuperTeams(person, superteam)


def _removeAllIndividualParticipantsFromTeamAndSuperTeams(team, target_team):
    """Remove all non-team participants in <team> from <target_team>.

    All the non-team participants of <team> are removed from <target_team>
    and its super teams, unless they participate in <target_team> also from
    one of its sub team.
    """
    query = """
        DELETE FROM TeamParticipation
        WHERE team = %(target_team_id)s AND person IN (
            -- All the individual participants.
            SELECT person
            FROM TeamParticipation JOIN Person ON (person = Person.id)
            WHERE team = %(team_id)s AND teamowner IS NULL
            EXCEPT
            -- people participating through a subteam of target_team;
            SELECT person
            FROM TeamParticipation
            WHERE team IN (
                -- The subteams of target_team.
                SELECT person
                FROM TeamParticipation JOIN Person ON (person = Person.id)
                WHERE team = %(target_team_id)s
                    AND person NOT IN (%(target_team_id)s, %(team_id)s)
                    AND teamowner IS NOT NULL
                 )
            -- or people directly a member of the target team.
            EXCEPT
            SELECT person
            FROM TeamMembership
            WHERE team = %(target_team_id)s AND status IN %(active_states)s
        )
        """ % dict(
            team_id=team.id, target_team_id=target_team.id,
            active_states=sqlvalues(ACTIVE_STATES)[0])
    store = Store.of(team)
    store.execute(query)

    super_teams = _getSuperTeamsExcludingDirectMembership(team, target_team)
    for superteam in super_teams:
        _removeAllIndividualParticipantsFromTeamAndSuperTeams(team, superteam)


def _getSuperTeamsExcludingDirectMembership(person, team):
    """Return all the super teams of <team> where person isn't a member."""
    query = """
        -- All the super teams...
        SELECT team
        FROM TeamParticipation
        WHERE person = %(team_id)s AND team != %(team_id)s
        EXCEPT
        -- The one where person has an active membership.
        SELECT team
        FROM TeamMembership
        WHERE person = %(person_id)s AND status IN %(active_states)s
        """ % dict(
            person_id=person.id, team_id=team.id,
            active_states=sqlvalues(ACTIVE_STATES)[0])

    # Avoid circular import.
    from lp.registry.model.person import Person
    return Store.of(person).find(Person, "id IN (%s)" % query)


def _fillTeamParticipation(member, accepting_team):
    """Add relevant entries in TeamParticipation for given member and team.

    Add a tuple "member, team" in TeamParticipation for the given team and all
    of its superteams. More information on how to use the TeamParticipation
    table can be found in the TeamParticipationUsage spec.
    """
    if member.isTeam():
        # The submembers will be all the members of the team that is
        # being added as a member. The superteams will be all the teams
        # that the accepting_team belongs to, so all the members will
        # also be joining the superteams indirectly. It is important to
        # remember that teams are members of themselves, so the member
        # team will also be one of the submembers, and the
        # accepting_team will also be one of the superteams.
        query = """
            INSERT INTO TeamParticipation (person, team)
            SELECT submember.person, superteam.team
            FROM TeamParticipation submember
                JOIN TeamParticipation superteam ON TRUE
            WHERE submember.team = %(member)d
                AND superteam.person = %(accepting_team)d
                AND NOT EXISTS (
                    SELECT 1
                    FROM TeamParticipation
                    WHERE person = submember.person
                        AND team = superteam.team
                    )
            """ % dict(member=member.id, accepting_team=accepting_team.id)
    else:
        query = """
            INSERT INTO TeamParticipation (person, team)
            SELECT %(member)d, superteam.team
            FROM TeamParticipation superteam
            WHERE superteam.person = %(accepting_team)d
                AND NOT EXISTS (
                    SELECT 1
                    FROM TeamParticipation
                    WHERE person = %(member)d
                        AND team = superteam.team
                    )
            """ % dict(member=member.id, accepting_team=accepting_team.id)

    store = Store.of(member)
    store.execute(query)
