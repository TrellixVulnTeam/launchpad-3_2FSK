# Copyright 2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['TeamMembership', 'TeamMembershipSet', 'TeamParticipation']

from datetime import datetime
import itertools
import pytz

from zope.interface import implements

from sqlobject import ForeignKey, StringCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.config import config
from canonical.launchpad.mail import simple_sendmail, format_address
from canonical.launchpad.helpers import (
    get_email_template, contactEmailAddresses)
from canonical.launchpad.interfaces import (
    ITeamMembership, ITeamParticipation, ITeamMembershipSet)

from canonical.lp.dbschema import EnumCol, TeamMembershipStatus


class TeamMembership(SQLBase):
    """See ITeamMembership"""

    implements(ITeamMembership)

    _table = 'TeamMembership'
    _defaultOrder = 'id'

    team = ForeignKey(dbName='team', foreignKey='Person', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    reviewer = ForeignKey(dbName='reviewer', foreignKey='Person', default=None)
    status = EnumCol(
        dbName='status', notNull=True, schema=TeamMembershipStatus)
    datejoined = UtcDateTimeCol(dbName='datejoined', default=UTC_NOW,
                                notNull=True)
    dateexpires = UtcDateTimeCol(dbName='dateexpires', default=None)
    reviewercomment = StringCol(dbName='reviewercomment', default=None)

    @property
    def statusname(self):
        """See ITeamMembership"""
        return self.status.title

    @property
    def is_admin(self):
        """See ITeamMembership"""
        return self.status in [TeamMembershipStatus.ADMIN]

    @property
    def is_owner(self):
        """See ITeamMembership"""
        return self.person.id == self.team.teamowner.id

    def isExpired(self):
        """See ITeamMembership"""
        return self.status == TeamMembershipStatus.EXPIRED

    def setStatus(self, status, reviewer=None, reviewercomment=None):
        """See ITeamMembership"""
        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        expired = TeamMembershipStatus.EXPIRED
        declined = TeamMembershipStatus.DECLINED
        deactivated = TeamMembershipStatus.DEACTIVATED
        proposed = TeamMembershipStatus.PROPOSED

        # Flush the cache used by the Person.inTeam method
        self.person._inTeam_cache = {}

        # Make sure the transition from the current status to the given status
        # is allowed. All allowed transitions are in the TeamMembership spec.
        if self.status in [admin, approved]:
            assert status in [admin, approved, expired, deactivated]
        elif self.status in [deactivated]:
            assert status in [approved]
        elif self.status in [expired]:
            assert status in [approved]
        elif self.status in [proposed]:
            assert status in [approved, declined]
        elif self.status in [declined]:
            assert status in [proposed, approved]

        old_status = self.status
        self.status = status
        self.reviewer = reviewer
        self.reviewercomment = reviewercomment

        self.syncUpdate()

        # XXX: The logic here is not correct, as deactivated or expired
        # members should be able to propose themselves as members.
        # https://launchpad.net/bugs/5997
        if ((status == approved and self.status != admin) or
            (status == admin and self.status != approved)):
            _fillTeamParticipation(self.person, self.team)
        elif status in [deactivated, expired]:
            _cleanTeamParticipation(self.person, self.team)

        # Send status change notifications only if it wasn't the actual member
        # who declined/proposed himself. In the case where the member is
        # proposing himself, a more detailed notification is sent to the team
        # admins (by a subscriber of JoinTeamRequestEvent), explaining that
        # a new member is waiting for approval.
        if self.person != self.reviewer and self.status != proposed:
            self._sendStatusChangeNotification(old_status)

    def _getStatusChangeNotificationSubject(self, to_admins=False):
        return ('Launchpad: Membership change: %(member)s in %(team)s'
                % {'member': self.person.name, 'team': self.team.name})

    def _sendStatusChangeNotification(self, old_status):
        """Send a status change notification to all team admins and the
        member whose membership's status changed.
        """
        from_addr = format_address(
            "Launchpad Team Membership Notifier", config.noreply_from_address)
        new_status = self.status
        admins_emails = self.team.getTeamAdminsEmailAddresses()
        # self.person might be a team, so we can't rely on its preferredemail.
        member_email = contactEmailAddresses(self.person)
        # Make sure we don't send the same notification twice to anybody.
        for email in member_email:
            if email in admins_emails:
                admins_emails.remove(email)

        team = self.team
        member = self.person
        reviewer = self.reviewer

        if reviewer is not None:
            reviewer_name = '%s (%s)' % (reviewer.displayname, reviewer.name)
        else:
            # The user himself changed his membership.
            reviewer_name = 'the user himself'

        if self.reviewercomment:
            comment = ("Comment: \n%s\n\n" % self.reviewercomment.strip())
        else:
            comment = ""

        replacements = {
            'member_name': '%s (%s)' % (member.displayname, member.name),
            'team_name': '%s (%s)' % (team.displayname, team.name),
            'old_status': old_status.title,
            'new_status': new_status.title,
            'reviewer_name': reviewer_name,
            'comment': comment}

        if admins_emails:
            admins_subject = self._getStatusChangeNotificationSubject(
                to_admins=True)
            admins_template = get_email_template(
                'membership-statuschange-impersonal.txt')
            admins_msg = admins_template % replacements
            #import pdb; pdb.set_trace()
            simple_sendmail(
                from_addr, admins_emails, admins_subject, admins_msg)

        # The member can be a team without any members, and in this case we
        # won't have a single email address to send this notification to.
        if member_email:
            member_subject = self._getStatusChangeNotificationSubject()
            if member.isTeam():
                template = 'membership-statuschange-impersonal.txt'
            else:
                template = 'membership-statuschange-personal.txt'
            member_template = get_email_template(template)
            member_msg = member_template % replacements
            simple_sendmail(
                from_addr, member_email, member_subject, member_msg)


class TeamMembershipSet:
    """See ITeamMembershipSet"""

    implements(ITeamMembershipSet)

    _defaultOrder = ['Person.displayname', 'Person.name']

    def new(self, person, team, status, dateexpires=None, reviewer=None,
            reviewercomment=None):
        """See ITeamMembershipSet"""
        assert status in [TeamMembershipStatus.APPROVED,
                          TeamMembershipStatus.PROPOSED]
        tm = TeamMembership(
            person=person, team=team, status=status, dateexpires=dateexpires,
            reviewer=reviewer, reviewercomment=reviewercomment)

        if status == TeamMembershipStatus.APPROVED:
            _fillTeamParticipation(person, team)

        return tm

    def getByPersonAndTeam(self, person, team, default=None):
        """See ITeamMembershipSet"""
        result = TeamMembership.selectOneBy(person=person, team=team)
        if result is None:
            return default
        return result

    def getMembershipsToExpire(self):
        """See ITeamMembershipSet"""
        now = datetime.now(pytz.timezone('UTC'))
        query = """
            dateexpires <= %s
            AND status IN (%s, %s)
            """ % sqlvalues(now, TeamMembershipStatus.ADMIN,
                            TeamMembershipStatus.APPROVED)
        return TeamMembership.select(query)

    def getTeamMembersCount(self, team):
        """See ITeamMembershipSet"""
        return TeamMembership.selectBy(team=team).count()

    def _getMembershipsByStatuses(self, team, statuses, orderBy=None):
        if orderBy is None:
            orderBy = self._defaultOrder
        clauses = []
        for status in statuses:
            clauses.append("TeamMembership.status = %s" % sqlvalues(status))
        clauses = " OR ".join(clauses)
        query = ("(%s) AND Person.id = TeamMembership.person AND "
                 "TeamMembership.team = %d" % (clauses, team.id))
        return TeamMembership.select(query, clauseTables=['Person'],
                                     orderBy=orderBy)

    def getActiveMemberships(self, team, orderBy=None):
        """See ITeamMembershipSet"""
        statuses = [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED]
        return self._getMembershipsByStatuses(
            team, statuses, orderBy=orderBy)

    def getInactiveMemberships(self, team, orderBy=None):
        """See ITeamMembershipSet"""
        statuses = [TeamMembershipStatus.EXPIRED,
                    TeamMembershipStatus.DEACTIVATED]
        return self._getMembershipsByStatuses(
            team, statuses, orderBy=orderBy)

    def getProposedMemberships(self, team, orderBy=None):
        """See ITeamMembershipSet"""
        statuses = [TeamMembershipStatus.PROPOSED]
        return self._getMembershipsByStatuses(
            team, statuses, orderBy=orderBy)


class TeamParticipation(SQLBase):
    implements(ITeamParticipation)

    _table = 'TeamParticipation'

    team = ForeignKey(foreignKey='Person', dbName='team', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)


def _cleanTeamParticipation(person, team):
    """Remove relevant entries in TeamParticipation for <person> and <team>.

    Remove all tuples "person, team" from TeamParticipation for the given
    person and team (together with all its superteams), unless this person is
    an indirect member of the given team. More information on how to use the
    TeamParticipation table can be found in the TeamParticipationUsage spec or
    the teammembership.txt system doctest.
    """
    # First of all, we remove <person> from <team> (and its superteams).
    _removeParticipantFromTeamAndSuperTeams(person, team)

    # Then, if <person> is a team, we remove all its participants from <team>
    # (and its superteams).
    if person.isTeam():
        for submember in person.allmembers:
            if submember not in team.activemembers:
                _cleanTeamParticipation(submember, team)


def _removeParticipantFromTeamAndSuperTeams(person, team):
    """If <person> is a participant (that is, has a TeamParticipation entry)
    of any team that is a subteam of <team>, then <person> should be kept as
    a participant of <team> and (as a consequence) all its superteams.
    Otherwise, <person> is removed from <team> and we repeat this process for
    each superteam of <team>.
    """
    for subteam in team.getSubTeams():
        # There's no need to worry for the case where person == subteam because
        # a team doesn't have a teamparticipation entry for itself and then a
        # call to team.hasParticipationEntryFor(team) will always return
        # False.
        if person.hasParticipationEntryFor(subteam):
            # This is an indirect member of this team and thus it should
            # be kept as so.
            return

    result = TeamParticipation.selectOneBy(person=person, team=team)
    if result is not None:
        result.destroySelf()

    for superteam in team.getSuperTeams():
        if person not in superteam.activemembers:
            _removeParticipantFromTeamAndSuperTeams(person, superteam)


def _fillTeamParticipation(member, team):
    """Add relevant entries in TeamParticipation for given member and team.

    Add a tuple "member, team" in TeamParticipation for the given team and all
    of its superteams. More information on how to use the TeamParticipation 
    table can be found in the TeamParticipationUsage spec.
    """
    members = [member]
    if member.teamowner is not None:
        # The given member is, in fact, a team, and in this case we must 
        # add all of its members to the given team and to its superteams.
        members.extend(member.allmembers)

    for m in members:
        for t in itertools.chain(team.getSuperTeams(), [team]):
            if not m.hasParticipationEntryFor(t):
                TeamParticipation(person=m, team=t)

