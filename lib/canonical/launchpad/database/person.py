# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'Person', 'PersonSet', 'EmailAddress', 'EmailAddressSet', 'GPGKey',
    'GPGKeySet', 'SSHKey', 'SSHKeySet', 'WikiName', 'WikiNameSet', 'JabberID',
    'JabberIDSet', 'IrcID', 'IrcIDSet']

import sets
from datetime import datetime, timedelta
import pytz
import sha

# Zope interfaces
from zope.interface import implements, directlyProvides, directlyProvidedBy
from zope.component import getUtility

# SQL imports
from sqlobject import (
    ForeignKey, IntCol, StringCol, BoolCol, MultipleJoin, SQLMultipleJoin,
    RelatedJoin, SQLObjectNotFound)
from sqlobject.sqlbuilder import AND
from canonical.database.sqlbase import (
    SQLBase, quote, quote_like, cursor, sqlvalues, flush_database_updates,
    flush_database_caches)
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database import postgresql
from canonical.launchpad.helpers import shortlist

from canonical.launchpad.interfaces import (
    IPerson, ITeam, IPersonSet, IEmailAddress, IWikiName, IIrcID, IJabberID,
    IIrcIDSet, ISSHKeySet, IJabberIDSet, IWikiNameSet, IGPGKeySet, ISSHKey,
    IGPGKey, IEmailAddressSet, IPasswordEncryptor, ICalendarOwner, IBugTaskSet,
    UBUNTU_WIKI_URL, ISignedCodeOfConductSet, ILoginTokenSet,
    KEYSERVER_QUERY_URL, EmailAddressAlreadyTaken,
    ILaunchpadStatisticSet)

from canonical.launchpad.database.cal import Calendar
from canonical.launchpad.database.codeofconduct import SignedCodeOfConduct
from canonical.launchpad.database.logintoken import LoginToken
from canonical.launchpad.database.pofile import POFile
from canonical.launchpad.database.karma import KarmaAction, Karma
from canonical.launchpad.database.potemplate import POTemplateSet
from canonical.launchpad.database.packagebugcontact import PackageBugContact
from canonical.launchpad.database.shipit import ShippingRequest
from canonical.launchpad.database.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.database.specification import Specification
from canonical.launchpad.database.specificationfeedback import (
    SpecificationFeedback)
from canonical.launchpad.database.specificationsubscription import (
    SpecificationSubscription)
from canonical.launchpad.database.teammembership import (
    TeamMembership, TeamParticipation, TeamMembershipSet)

from canonical.launchpad.database.branch import Branch

from canonical.lp.dbschema import (
    EnumCol, SSHKeyType, EmailAddressStatus, TeamSubscriptionPolicy,
    TeamMembershipStatus, GPGKeyAlgorithm, LoginTokenType,
    SpecificationSort, SpecificationFilter)

from canonical.foaf import nickname
from canonical.cachedproperty import cachedproperty


class ValidPersonOrTeamCache(SQLBase):
    """Flags if a Person or Team is active and usable in Launchpad.
    
    This is readonly, as the underlying table is maintained using
    database triggers.
    """
    # Look Ma, no columns! (apart from id)


class Person(SQLBase):
    """A Person."""

    implements(IPerson, ICalendarOwner)

    # XXX: We should be sorting on person_sort_key(displayname,name), but
    # SQLObject will not let us sort using a stored procedure.
    # -- StuartBishop 20060323
    sortingColumns = ['displayname', 'name']
    _defaultOrder = sortingColumns

    name = StringCol(dbName='name', alternateID=True, notNull=True)
    password = StringCol(dbName='password', default=None)
    displayname = StringCol(dbName='displayname', notNull=True)
    teamdescription = StringCol(dbName='teamdescription', default=None)
    homepage_content = StringCol(default=None)
    emblem = ForeignKey(dbName='emblem',
        foreignKey='LibraryFileAlias', default=None)
    hackergotchi = ForeignKey(dbName='hackergotchi',
        foreignKey='LibraryFileAlias', default=None)

    city = StringCol(default=None)
    phone = StringCol(default=None)
    country = ForeignKey(dbName='country', foreignKey='Country', default=None)
    province = StringCol(default=None)
    postcode = StringCol(default=None)
    addressline1 = StringCol(default=None)
    addressline2 = StringCol(default=None)
    organization = StringCol(default=None)

    teamowner = ForeignKey(dbName='teamowner', foreignKey='Person',
                           default=None)

    sshkeys = SQLMultipleJoin('SSHKey', joinColumn='person')

    karma_total_cache = SQLMultipleJoin('KarmaTotalCache', joinColumn='person')

    subscriptionpolicy = EnumCol(
        dbName='subscriptionpolicy',
        schema=TeamSubscriptionPolicy,
        default=TeamSubscriptionPolicy.MODERATED)
    defaultrenewalperiod = IntCol(dbName='defaultrenewalperiod', default=None)
    defaultmembershipperiod = IntCol(dbName='defaultmembershipperiod',
                                     default=None)

    merged = ForeignKey(dbName='merged', foreignKey='Person', default=None)

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    hide_email_addresses = BoolCol(notNull=True, default=False)

    # RelatedJoin gives us also an addLanguage and removeLanguage for free
    languages = RelatedJoin('Language', joinColumn='person',
                            otherColumn='language',
                            intermediateTable='PersonLanguage')

    subscribed_branches = RelatedJoin(
        'Branch', joinColumn='person', otherColumn='branch',
        intermediateTable='BranchSubscription', orderBy='-id')
    ownedBounties = SQLMultipleJoin('Bounty', joinColumn='owner',
        orderBy='id')
    reviewerBounties = SQLMultipleJoin('Bounty', joinColumn='reviewer',
        orderBy='id')
    # XXX: matsubara 2006-03-06: Is this really needed? There's no attribute 
    # 'claimant' in the Bounty database class or interface, but the column 
    # exists in the database. 
    # https://launchpad.net/products/launchpad/+bug/33935
    claimedBounties = MultipleJoin('Bounty', joinColumn='claimant',
        orderBy='id')
    subscribedBounties = RelatedJoin('Bounty', joinColumn='person',
        otherColumn='bounty', intermediateTable='BountySubscription',
        orderBy='id')
    karma_category_caches = SQLMultipleJoin('KarmaCache', joinColumn='person',
        orderBy='category')
    signedcocs = SQLMultipleJoin('SignedCodeOfConduct', joinColumn='owner')
    ircnicknames = SQLMultipleJoin('IrcID', joinColumn='person')
    jabberids = SQLMultipleJoin('JabberID', joinColumn='person')

    # specification-related joins
    @property
    def approver_specs(self):
        return shortlist(Specification.selectBy(approverID=self.id,
                                      orderBy=['-datecreated']))

    @property
    def assigned_specs(self):
        return shortlist(Specification.selectBy(assigneeID=self.id,
                                      orderBy=['-datecreated']))

    @property
    def created_specs(self):
        return shortlist(Specification.selectBy(ownerID=self.id,
                                      orderBy=['-datecreated']))

    @property
    def drafted_specs(self):
        return shortlist(Specification.selectBy(drafterID=self.id,
                                      orderBy=['-datecreated']))

    @property
    def feedback_specs(self):
        return shortlist(Specification.select(
            AND(Specification.q.id == SpecificationFeedback.q.specificationID,
                SpecificationFeedback.q.reviewerID == self.id),
            clauseTables=['SpecificationFeedback'],
            orderBy=['-datecreated']))

    @property
    def subscribed_specs(self):
        return shortlist(Specification.select(
            AND(Specification.q.id == SpecificationSubscription.q.specificationID,
                SpecificationSubscription.q.personID == self.id),
            clauseTables=['SpecificationSubscription'],
            orderBy=['-datecreated']))

    # ticket related joins
    answered_tickets = SQLMultipleJoin('Ticket', joinColumn='answerer',
        orderBy='-datecreated')
    assigned_tickets = SQLMultipleJoin('Ticket', joinColumn='assignee',
        orderBy='-datecreated')
    created_tickets = SQLMultipleJoin('Ticket', joinColumn='owner',
        orderBy='-datecreated')
    subscribed_tickets = RelatedJoin('Ticket', joinColumn='person',
        otherColumn='ticket', intermediateTable='TicketSubscription',
        orderBy='-datecreated')

    calendar = ForeignKey(dbName='calendar', foreignKey='Calendar',
                          default=None, forceDBName=True)

    def getOrCreateCalendar(self):
        if not self.calendar:
            self.calendar = Calendar(title=self.browsername,
                                     revision=0)
        return self.calendar

    timezone = StringCol(dbName='timezone', default='UTC')

    def get(cls, id, connection=None, selectResults=None):
        """Override the classmethod get from the base class.

        In this case when we're getting a team we mark it with ITeam.
        """
        # XXX: Use the same thing Bjorn used for malone here.
        #      -- SteveAlexander, 2005-04-23

        # This is simulating 'super' without using 'super' to show
        # how nasty sqlobject actually is.
        # -- SteveAlexander, 2005-04-23
        val = SQLBase.get.im_func(cls, id, connection=connection,
                                  selectResults=selectResults)
        if val.teamowner is not None:
            directlyProvides(val, directlyProvidedBy(val) + ITeam)
        return val
    get = classmethod(get)

    @property
    def browsername(self):
        """Return a name suitable for display on a web page.

        Originally, this was calculated but now we just use displayname.
        You should continue to use this method, however, as we may want to
        change again, such as returning '$displayname ($name)'.

        >>> class DummyPerson:
        ...     displayname = None
        ...     name = 'the_name'
        ...     # This next line is some special evil magic to allow us to
        ...     # unit test browsername in isolation.
        ...     browsername = Person.browsername.im_func
        ...
        >>> person = DummyPerson()

        Check with just the name.

        >>> person.browsername
        'the_name'

        >>> person.displayname = 'the_displayname'
        >>> person.browsername
        'the_displayname'
        """
        # Person.displayname is NOT NULL
        return self.displayname

    def specifications(self, sort=None, quantity=None, filter=[]):
        """See IHasSpecifications."""

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = ['-priority', 'status', 'name']
        elif sort == SpecificationSort.DATE:
            order = ['-datecreated', 'id']

        # figure out what set of specifications we are interested in. for
        # products, we need to be able to filter on the basis of:
        #
        #  - role (owner, drafter, approver, subscriber, assignee etc)
        #  - completeness.
        #  - informational.
        #

        # in this case the "base" is quite complicated because it is
        # determined by the roles so lets do that first

        # if no roles are given then we want everything
        linked = False
        for role in [
            SpecificationFilter.CREATOR,
            SpecificationFilter.ASSIGNEE,
            SpecificationFilter.DRAFTER,
            SpecificationFilter.APPROVER,
            SpecificationFilter.FEEDBACK,
            SpecificationFilter.SUBSCRIBER]:
            if role in filter:
                linked = True
        if not linked:
            filter.append(SpecificationFilter.CREATOR)
            filter.append(SpecificationFilter.ASSIGNEE)
            filter.append(SpecificationFilter.DRAFTER)
            filter.append(SpecificationFilter.APPROVER)
            filter.append(SpecificationFilter.FEEDBACK)
            filter.append(SpecificationFilter.SUBSCRIBER)

        base = '(1=0'  # we want to start with a FALSE and OR them
        if SpecificationFilter.CREATOR in filter:
            base += ' OR Specification.owner = %(my_id)d'
        if SpecificationFilter.ASSIGNEE in filter:
            base += ' OR Specification.assignee = %(my_id)d'
        if SpecificationFilter.DRAFTER in filter:
            base += ' OR Specification.drafter = %(my_id)d'
        if SpecificationFilter.APPROVER in filter:
            base += ' OR Specification.approver = %(my_id)d'
        if SpecificationFilter.SUBSCRIBER in filter:
            base += """ OR Specification.id in
                (SELECT specification FROM SpecificationSubscription
                 WHERE person = %(my_id)d)"""
        if SpecificationFilter.FEEDBACK in filter:
            base += """ OR Specification.id in
                (SELECT specification FROM SpecificationFeedback
                 WHERE reviewer = %(my_id)d)"""
        base += ') '
        
        base = base % {'my_id': self.id}

        query = base
        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += ' AND Specification.informational IS TRUE'
        
        # filter based on completion. see the implementation of
        # Specification.is_complete() for more details
        completeness =  Specification.completeness

        if SpecificationFilter.COMPLETE in filter:
            query += ' AND ( %s ) ' % completeness
        elif SpecificationFilter.INCOMPLETE in filter:
            query += ' AND NOT ( %s ) ' % completeness

        # ALL is the trump card
        if SpecificationFilter.ALL in filter:
            query = base
        
        # now do the query, and remember to prejoin to people
        results = Specification.select(query, orderBy=order, limit=quantity)
        results.prejoin(['assignee', 'approver', 'drafter'])
        return results

    def tickets(self, quantity=None):
        ret = set(self.created_tickets)
        ret = ret.union(self.answered_tickets)
        ret = ret.union(self.assigned_tickets)
        ret = ret.union(self.subscribed_tickets)
        ret = sorted(ret, key=lambda a: a.datecreated)
        ret.reverse()
        return ret[:quantity]

    @property
    def branches(self):
        """See IPerson."""
        S = set(self.authored_branches)
        S.update(self.registered_branches)
        S.update(self.subscribed_branches)
        return sorted(S, key=lambda x: -x.id)

    @property
    def registered_branches(self):
        """See IPerson."""
        query = """Branch.owner = %d AND
                   (Branch.author != %d OR Branch.author is NULL)"""
        return Branch.select(query % (self.id, self.id),
                             prejoins=["product"],
                             orderBy='-Branch.id')


    @property
    def authored_branches(self):
        """See IPerson."""
        # XXX: this should be moved back to SQLMultipleJoin when we
        # support prejoins in that -- kiko, 2006-03-17
        return Branch.select('Branch.author = %d' % self.id,
                             prejoins=["product"],
                             orderBy='-Branch.id')

    def getBugContactPackages(self):
        """See IPerson."""
        package_bug_contacts = shortlist(
            PackageBugContact.selectBy(bugcontactID=self.id),
            longest_expected=25)

        packages_for_bug_contact = [
            package_bug_contact.distribution.getSourcePackage(
                package_bug_contact.sourcepackagename)
            for package_bug_contact in package_bug_contacts]

        packages_for_bug_contact.sort(key=lambda x: x.name)

        return packages_for_bug_contact

    def getBranch(self, product_name, branch_name):
        """See IPerson."""
        # import here to work around a circular import problem
        from canonical.launchpad.database import Product

        if product_name is None:
            return Branch.selectOne(
                'owner=%d AND product is NULL AND name=%s'
                % (self.id, quote(branch_name)))
        else:
            product = Product.selectOneBy(name=product_name)
            if product is None:
                return None
            return Branch.selectOneBy(
                ownerID=self.id, productID=product.id, name=branch_name)

    def isTeam(self):
        """See IPerson."""
        return self.teamowner is not None

    def shippedShipItRequests(self):
        """See IPerson."""
        query = '''
            ShippingRequest.recipient = %s AND
            ShippingRequest.id IN (SELECT request FROM Shipment)
            ''' % sqlvalues(self.id)
        return ShippingRequest.select(query)

    def pastShipItRequests(self):
        """See IPerson."""
        query = '''
            ShippingRequest.recipient = %s AND
            (ShippingRequest.approved = false OR
             ShippingRequest.cancelled = true OR
             ShippingRequest.id IN (SELECT request FROM Shipment))
            ''' % sqlvalues(self.id)
        return ShippingRequest.select(query)

    def currentShipItRequest(self):
        """See IPerson."""
        query = '''
            (ShippingRequest.approved = true OR
             ShippingRequest.approved IS NULL)
            AND ShippingRequest.recipient = %s AND
            ShippingRequest.cancelled = false AND
            ShippingRequest.id NOT IN (SELECT request FROM Shipment)
            ''' % sqlvalues(self.id)
        return ShippingRequest.selectOne(query)

    def searchTasks(self, search_params):
        """See IPerson."""
        return getUtility(IBugTaskSet).search(search_params)

    @property
    def karma(self):
        """See IPerson."""
        try:
            return self.karma_total_cache[0].karma_total
        except IndexError:
            return 0

    @property
    def is_valid_person(self):
        """See IPerson."""
        try:
            if ValidPersonOrTeamCache.get(self.id) is not None:
                return True
        except SQLObjectNotFound:
            pass
        return False
        
    def assignKarma(self, action_name):
        """See IPerson."""
        # Teams don't get Karma. Inactive accounts don't get Karma.
        # No warning, as we don't want to place the burden on callsites
        # to check this.
        if not self.is_valid_person:
            return

        try:
            action = KarmaAction.byName(action_name)
        except SQLObjectNotFound:
            raise ValueError(
                "No KarmaAction found with name '%s'." % action_name)
        return Karma(person=self, action=action)

    def latestKarma(self, quantity=25):
        """See IPerson."""
        return Karma.selectBy(personID=self.id,
            orderBy='-datecreated')[:quantity]

    def inTeam(self, team):
        """See IPerson."""
        if team is None:
            return False
        tp = TeamParticipation.selectOneBy(teamID=team.id, personID=self.id)
        if tp is not None or self.id == team.teamownerID:
            return True
        elif team.teamowner is not None and not team.teamowner.inTeam(team):
            # The owner is not a member but must retain his rights over
            # this team. This person may be a member of the owner, and in this
            # case it'll also have rights over this team.
            return self.inTeam(team.teamowner)
        else:
            return False

    def hasMembershipEntryFor(self, team):
        """See IPerson."""
        return bool(TeamMembership.selectOneBy(personID=self.id,
                                               teamID=team.id))

    def hasParticipationEntryFor(self, team):
        """See IPerson."""
        return bool(TeamParticipation.selectOneBy(personID=self.id,
                                                  teamID=team.id))

    def leave(self, team):
        """See IPerson."""
        assert not ITeam.providedBy(self)

        active = [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED]
        tm = TeamMembership.selectOneBy(personID=self.id, teamID=team.id)
        if tm is None or tm.status not in active:
            # Ok, we're done. You are not an active member and still not being.
            return

        team.setMembershipStatus(self, TeamMembershipStatus.DEACTIVATED,
                                 tm.dateexpires)

    def join(self, team):
        """See IPerson."""
        assert not self.isTeam(), (
            "Teams take no actions in Launchpad, thus they can't join() "
            "another team. Instead, you have to addMember() them.")

        expired = TeamMembershipStatus.EXPIRED
        proposed = TeamMembershipStatus.PROPOSED
        approved = TeamMembershipStatus.APPROVED
        declined = TeamMembershipStatus.DECLINED
        deactivated = TeamMembershipStatus.DEACTIVATED

        if team.subscriptionpolicy == TeamSubscriptionPolicy.RESTRICTED:
            return False
        elif team.subscriptionpolicy == TeamSubscriptionPolicy.MODERATED:
            status = proposed
        elif team.subscriptionpolicy == TeamSubscriptionPolicy.OPEN:
            status = approved

        tm = TeamMembership.selectOneBy(personID=self.id, teamID=team.id)
        expires = team.defaultexpirationdate
        if tm is None:
            team.addMember(self, status)
        else:
            if (tm.status == declined and
                team.subscriptionpolicy == TeamSubscriptionPolicy.MODERATED):
                # The user is a DECLINED member, we just have to change the
                # status to PROPOSED.
                team.setMembershipStatus(self, status, expires)
            elif (tm.status in [expired, deactivated, declined] and
                  team.subscriptionpolicy == TeamSubscriptionPolicy.OPEN):
                team.setMembershipStatus(self, status, expires)
            else:
                return False

        return True

    #
    # ITeam methods
    #
    def getSuperTeams(self):
        """See IPerson."""
        query = ('Person.id = TeamParticipation.team AND '
                 'TeamParticipation.person = %d' % self.id)
        return Person.select(query, clauseTables=['TeamParticipation'])

    def getSubTeams(self):
        """See IPerson."""
        query = ('Person.id = TeamParticipation.person AND '
                 'TeamParticipation.team = %d AND '
                 'Person.teamowner IS NOT NULL' % self.id)
        return Person.select(query, clauseTables=['TeamParticipation'])

    def addMember(self, person, status=TeamMembershipStatus.APPROVED,
                  reviewer=None, comment=None):
        """See IPerson."""
        assert self.teamowner is not None

        if person.isTeam():
            assert not self.hasParticipationEntryFor(person), (
                "Team '%s' is a member of '%s'. As a consequence, '%s' can't "
                "be added as a member of '%s'" 
                % (self.name, person.name, person.name, self.name))

        if person in self.activemembers:
            # Make it a no-op if this person is already a member.
            return

        assert not person.hasMembershipEntryFor(self)

        expires = self.defaultexpirationdate
        TeamMembershipSet().new(
            person, self, status, dateexpires=expires, reviewer=reviewer,
            reviewercomment=comment)

    def setMembershipStatus(self, person, status, expires=None, reviewer=None,
                            comment=None):
        """See IPerson."""
        tm = TeamMembership.selectOneBy(personID=person.id, teamID=self.id)

        # XXX: Do we need this assert?
        #      -- SteveAlexander, 2005-04-23
        assert tm is not None

        now = datetime.now(pytz.timezone('UTC'))
        if expires is not None and expires <= now:
            status = TeamMembershipStatus.EXPIRED
            # XXX: This is a workaround while 
            # https://launchpad.net/products/launchpad/+bug/30649 isn't fixed.
            expires = now

        tm.setStatus(status)
        tm.dateexpires = expires
        tm.reviewer = reviewer
        tm.reviewercomment = comment

        tm.syncUpdate()

    def _getMembersByStatus(self, status):
        # XXX Needs a system doc test. SteveAlexander 2005-04-23
        query = ("TeamMembership.team = %s AND TeamMembership.status = %s "
                 "AND TeamMembership.person = Person.id" %
                 sqlvalues(self.id, status))
        return Person.select(query, clauseTables=['TeamMembership'])

    def _getEmailsByStatus(self, status):
        query = AND(EmailAddress.q.personID==self.id,
                    EmailAddress.q.status==status)
        return EmailAddress.select(query)

    @property
    def jabberids(self):
        """See IPerson."""
        return getUtility(IJabberIDSet).getByPerson(self)

    @property
    def ubuntuwiki(self):
        """See IPerson."""
        return getUtility(IWikiNameSet).getUbuntuWikiByPerson(self)

    @property
    def otherwikis(self):
        """See IPerson."""
        return getUtility(IWikiNameSet).getOtherWikisByPerson(self)

    @property
    def allwikis(self):
        return getUtility(IWikiNameSet).getAllWikisByPerson(self)

    @property
    def title(self):
        """See IPerson."""
        return self.browsername

    @property 
    def allmembers(self):
        """See IPerson."""
        query = ('Person.id = TeamParticipation.person AND '
                 'TeamParticipation.team = %d' % self.id)
        return Person.select(query, clauseTables=['TeamParticipation'])

    @property
    def all_member_count(self):
        """See IPerson."""
        return self.allmembers.count()

    @property
    def deactivatedmembers(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.DEACTIVATED)

    @property
    def expiredmembers(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.EXPIRED)

    @property
    def declinedmembers(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.DECLINED)

    @property
    def proposedmembers(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.PROPOSED)

    @property
    def administrators(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.ADMIN)

    @property
    def approvedmembers(self):
        """See IPerson."""
        return self._getMembersByStatus(TeamMembershipStatus.APPROVED)

    @property
    def activemembers(self):
        """See IPerson."""
        return self.approvedmembers.union(self.administrators)

    @property
    def active_member_count(self):
        """See IPerson."""
        return self.activemembers.count()

    @property
    def inactivemembers(self):
        """See IPerson."""
        return self.expiredmembers.union(self.deactivatedmembers)

    # XXX: myactivememberships and activememberships are rather
    # confusingly named, and I just fixed bug 2871 as a consequence of
    # this. Is there a way to improve it?
    #   -- kiko, 2005-10-07
    @property
    def myactivememberships(self):
        """See IPerson."""
        return TeamMembership.select("""
            TeamMembership.person = %s AND status in (%s, %s) AND 
            Person.id = TeamMembership.team
            """ % sqlvalues(self.id, TeamMembershipStatus.APPROVED,
                            TeamMembershipStatus.ADMIN),
            clauseTables=['Person'],
            orderBy=['Person.displayname'])

    @property
    def activememberships(self):
        """See IPerson."""
        return TeamMembership.select('''
            TeamMembership.team = %s AND status in (%s, %s) AND
            Person.id = TeamMembership.person
            ''' % sqlvalues(self.id, TeamMembershipStatus.APPROVED,
                TeamMembershipStatus.ADMIN),
            clauseTables=['Person'],
            orderBy=['Person.displayname'])

    @property
    def teams_participated_in(self):
        """See IPerson."""
        return Person.select("""
            Person.id = TeamParticipation.team
            AND TeamParticipation.person = %s
            AND Person.teamowner IS NOT NULL
            """ % sqlvalues(self.id), clauseTables=['TeamParticipation'],
            orderBy=['Person.name']
            )

    @property
    def defaultexpirationdate(self):
        """See IPerson."""
        days = self.defaultmembershipperiod
        if days:
            return datetime.now(pytz.timezone('UTC')) + timedelta(days)
        else:
            return None

    @property
    def defaultrenewedexpirationdate(self):
        """See IPerson."""
        days = self.defaultrenewalperiod
        if days:
            return datetime.now(pytz.timezone('UTC')) + timedelta(days)
        else:
            return None

    @property
    def touched_pofiles(self):
        results = POFile.select('''
            POSubmission.person = %s AND
            POSubmission.pomsgset = POMsgSet.id AND
            POMsgSet.pofile = POFile.id
            ''' % sqlvalues(self.id),
            orderBy=['POFile.datecreated'],
            prejoins=['language', 'potemplate'],
            clauseTables=['POMsgSet', 'POFile', 'POSubmission'],
            distinct=True)
        # XXX: Because of a template reference to
        # pofile.potemplate.displayname, it would be ideal to also
        # prejoin above:
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
        # before passing it on to avoid reissuing it; the template code
        # only hits this callsite once and iterates over all the results
        # anyway. When we have deep prejoining we can just ditch all of
        # this and either use cachedproperty or cache in the view code.
        #   -- kiko, 2006-03-17
        results = list(results)
        ids = set(pofile.potemplate.id for pofile in results)
        if ids:
            list(POTemplateSet().getByIDs(ids))
        return results

    def validateAndEnsurePreferredEmail(self, email):
        """See IPerson."""
        if not IEmailAddress.providedBy(email):
            raise TypeError, (
                "Any person's email address must provide the IEmailAddress "
                "interface. %s doesn't." % email)
        # XXX stevea 05/07/05 this is here because of an SQLobject
        # comparison oddity
        assert email.person.id == self.id, 'Wrong person! %r, %r' % (
            email.person, self)
        assert self.preferredemail != email, 'Wrong prefemail! %r, %r' % (
            self.preferredemail, email)

        if self.preferredemail is None:
            # This branch will be executed only in the first time a person
            # uses Launchpad. Either when creating a new account or when
            # resetting the password of an automatically created one.
            self.setPreferredEmail(email)
        else:
            email.status = EmailAddressStatus.VALIDATED

    def setPreferredEmail(self, email):
        """See IPerson."""
        if not IEmailAddress.providedBy(email):
            raise TypeError, (
                "Any person's email address must provide the IEmailAddress "
                "interface. %s doesn't." % email)
        assert email.person.id == self.id
        preferredemail = self.preferredemail
        if preferredemail is not None:
            preferredemail.status = EmailAddressStatus.VALIDATED
            # We need to flush updates, because we don't know what order
            # SQLObject will issue the changes and we can't set the new
            # address to PREFERRED until the old one has been set to VALIDATED
            preferredemail.syncUpdate()
        # get the non-proxied EmailAddress object, so we can call
        # syncUpdate() on it:
        email = EmailAddress.get(email.id)
        email.status = EmailAddressStatus.PREFERRED
        email.syncUpdate()
        # Now we update our cache of the preferredemail
        setattr(self, '_preferredemail_cached', email)

    @cachedproperty('_preferredemail_cached')
    def preferredemail(self):
        """See IPerson."""
        emails = self._getEmailsByStatus(EmailAddressStatus.PREFERRED)
        # There can be only one preferred email for a given person at a
        # given time, and this constraint must be ensured in the DB, but
        # it's not a problem if we ensure this constraint here as well.
        emails = shortlist(emails)
        length = len(emails)
        assert length <= 1
        if length:
            return emails[0]
        else:
            return None

    @property
    def preferredemail_sha1(self):
        """See IPerson."""
        preferredemail = self.preferredemail
        if preferredemail:
            return sha.new('mailto:' + preferredemail.email).hexdigest().upper()
        else:
            return None

    @property
    def validatedemails(self):
        """See IPerson."""
        return self._getEmailsByStatus(EmailAddressStatus.VALIDATED)

    @property
    def unvalidatedemails(self):
        """See IPerson."""
        query = ("requester=%s AND (tokentype=%s OR tokentype=%s)" 
                 % sqlvalues(self.id, LoginTokenType.VALIDATEEMAIL,
                             LoginTokenType.VALIDATETEAMEMAIL))
        return sets.Set([token.email for token in LoginToken.select(query)])

    @property
    def guessedemails(self):
        """See IPerson."""
        return self._getEmailsByStatus(EmailAddressStatus.NEW)

    @property
    def activities(self):
        """See IPerson."""
        return Karma.selectBy(personID=self.id)

    @property
    def pendinggpgkeys(self):
        """See IPerson."""
        logintokenset = getUtility(ILoginTokenSet)
        # XXX cprov 20050704
        # Use set to remove duplicated tokens, I'd appreciate something
        # SQL DISTINCT-like functionality available for sqlobject
        return sets.Set([token.fingerprint for token in
                         logintokenset.getPendingGPGKeys(requesterid=self.id)])

    @property
    def inactivegpgkeys(self):
        """See IPerson."""
        gpgkeyset = getUtility(IGPGKeySet)
        return gpgkeyset.getGPGKeys(ownerid=self.id, active=False)

    @property
    def gpgkeys(self):
        """See IPerson."""
        gpgkeyset = getUtility(IGPGKeySet)
        return gpgkeyset.getGPGKeys(ownerid=self.id)

    def latestMaintainedPackages(self):
        """See IPerson."""
        return self._latestReleaseQuery()

    def latestUploadedButNotMaintainedPackages(self):
        """See IPerson."""
        return self._latestReleaseQuery(uploader_only=True)

    def _latestReleaseQuery(self, uploader_only=False):
        # Issues a special query that returns the most recent
        # sourcepackagereleases that were maintained/uploaded to
        # distribution releases by this person.
        if uploader_only:
            extra = """sourcepackagerelease.creator = %d AND
                       sourcepackagerelease.maintainer != %d""" % (
                       self.id, self.id)
        else:
            extra = "sourcepackagerelease.maintainer = %d" % self.id
        query = """
            SourcePackageRelease.id IN (
                SELECT DISTINCT ON (uploaddistrorelease,sourcepackagename)
                       sourcepackagerelease.id
                  FROM sourcepackagerelease
                 WHERE %s
              ORDER BY uploaddistrorelease, sourcepackagename, 
                       dateuploaded DESC
              )
              """ % extra
        return SourcePackageRelease.select(
            query,
            orderBy=['-SourcePackageRelease.dateuploaded',
                     'SourcePackageRelease.id'],
            prejoins=['sourcepackagename', 'maintainer'])

    @cachedproperty
    def is_ubuntero(self):
        """See IPerson."""
        sigset = getUtility(ISignedCodeOfConductSet)
        lastdate = sigset.getLastAcceptedDate()

        query = AND(SignedCodeOfConduct.q.active==True,
                    SignedCodeOfConduct.q.ownerID==self.id,
                    SignedCodeOfConduct.q.datecreated>=lastdate)

        return bool(SignedCodeOfConduct.select(query).count())

    @property
    def activesignatures(self):
        """See IPerson."""
        sCoC_util = getUtility(ISignedCodeOfConductSet)
        return sCoC_util.searchByUser(self.id)

    @property
    def inactivesignatures(self):
        """See IPerson."""
        sCoC_util = getUtility(ISignedCodeOfConductSet)
        return sCoC_util.searchByUser(self.id, active=False)


class PersonSet:
    """The set of persons."""
    implements(IPersonSet)

    _defaultOrder = Person.sortingColumns

    def __init__(self):
        self.title = 'People registered with Launchpad'

    def topPeople(self):
        """See IPersonSet."""
        # The odd ordering here is to ensure we hit the PostgreSQL
        # indexes. It will not make any real difference outside of tests.
        query = """
            id in (
                SELECT person FROM KarmaTotalCache
                ORDER BY karma_total DESC, person DESC
                LIMIT 5
                )
            """
        top_people = shortlist(Person.select(query))
        top_people.sort(key=lambda obj: (obj.karma, obj.id), reverse=True)
        return top_people

    def newTeam(self, teamowner, name, displayname, teamdescription=None,
                subscriptionpolicy=TeamSubscriptionPolicy.MODERATED,
                defaultmembershipperiod=None, defaultrenewalperiod=None):
        """See IPersonSet."""
        assert teamowner
        team = Person(teamowner=teamowner, name=name, displayname=displayname,
                teamdescription=teamdescription,
                defaultmembershipperiod=defaultmembershipperiod,
                defaultrenewalperiod=defaultrenewalperiod,
                subscriptionpolicy=subscriptionpolicy)
        team.addMember(teamowner)
        team.setMembershipStatus(teamowner, TeamMembershipStatus.ADMIN)
        return team

    def createPersonAndEmail(self, email, name=None, displayname=None,
                             password=None, passwordEncrypted=False):
        """See IPersonSet."""
        if name is None:
            try:
                name = nickname.generate_nick(email)
            except nickname.NicknameGenerationError:
                return None, None
        else:
            if self.getByName(name, ignore_merged=False) is not None:
                return None, None

        if not passwordEncrypted and password is not None:
            password = getUtility(IPasswordEncryptor).encrypt(password)

        displayname = displayname or name.capitalize()
        person = self._newPerson(name, displayname, password=password)

        email = getUtility(IEmailAddressSet).new(email, person.id)
        return person, email

    def _newPerson(self, name, displayname, password=None):
        """Create a new Person with the given attributes.

        Also generate a wikiname for this person that's not yet used in the
        Ubuntu wiki.
        """
        assert self.getByName(name, ignore_merged=False) is None
        person = Person(name=name, displayname=displayname, password=password)
        wikinameset = getUtility(IWikiNameSet)
        wikiname = nickname.generate_wikiname(
                    person.displayname, wikinameset.exists)
        wikinameset.new(person, UBUNTU_WIKI_URL, wikiname)
        return person

    def ensurePerson(self, email, displayname):
        """See IPersonSet."""
        person = self.getByEmail(email)
        if person:
            return person
        person, dummy = self.createPersonAndEmail(
                            email, displayname=displayname)
        return person

    def getByName(self, name, default=None, ignore_merged=True):
        """See IPersonSet."""
        query = (Person.q.name == name)
        if ignore_merged:
            query = AND(query, Person.q.mergedID==None)
        person = Person.selectOne(query)
        if person is None:
            return default
        return person

    def updateStatistics(self, ztm):
        """See IPersonSet."""
        stats = getUtility(ILaunchpadStatisticSet)
        stats.update('people_count', self.getAllPersons().count())
        ztm.commit()
        stats.update('teams_count', self.getAllTeams().count())
        ztm.commit()

    def peopleCount(self):
        """See IPersonSet."""
        return getUtility(ILaunchpadStatisticSet).value('people_count')

    def getAllPersons(self, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        query = AND(Person.q.teamownerID==None, Person.q.mergedID==None)
        return Person.select(query, orderBy=orderBy)

    def getAllValidPersons(self, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        return Person.select(
            "Person.id = ValidPersonOrTeamCache.id AND teamowner IS NULL",
            clauseTables=["ValidPersonOrTeamCache"], orderBy=orderBy
            )

    def teamsCount(self):
        """See IPersonSet."""
        return getUtility(ILaunchpadStatisticSet).value('teams_count')

    def getAllTeams(self, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        return Person.select(Person.q.teamownerID!=None, orderBy=orderBy)

    def find(self, text, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        text = text.lower()
        # Teams may not have email addresses, so we need to either use a LEFT
        # OUTER JOIN or do a UNION between two queries. Using a UNION makes 
        # it a lot faster than with a LEFT OUTER JOIN.
        email_query = """
            EmailAddress.person = Person.id AND 
            lower(EmailAddress.email) LIKE %s || '%%'
            """ % quote_like(text)
        results = Person.select(email_query, clauseTables=['EmailAddress'])
        name_query = "fti @@ ftq(%s) AND merged is NULL" % quote(text)
        return results.union(Person.select(name_query), orderBy=orderBy)

    def findPerson(self, text="", orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        text = text.lower()
        base_query = ('Person.teamowner IS NULL AND Person.merged IS NULL AND '
                      'EmailAddress.person = Person.id')
        clauseTables = ['EmailAddress']
        if text:
            # We use a UNION here because this makes things *a lot* faster
            # than if we did a single SELECT with the two following clauses
            # ORed.
            email_query = ("%s AND lower(EmailAddress.email) LIKE %s || '%%'"
                           % (base_query, quote_like(text)))
            name_query = ('%s AND Person.fti @@ ftq(%s)' 
                          % (base_query, quote(text)))
            results = Person.select(email_query, clauseTables=clauseTables)
            results = results.union(
                Person.select(name_query, clauseTables=clauseTables))
        else:
            results = Person.select(base_query, clauseTables=clauseTables)

        return results.orderBy(orderBy)

    def findTeam(self, text, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        text = text.lower()
        # Teams may not have email addresses, so we need to either use a LEFT
        # OUTER JOIN or do a UNION between two queries. Using a UNION makes 
        # it a lot faster than with a LEFT OUTER JOIN.
        email_query = """
            Person.teamowner IS NOT NULL AND 
            EmailAddress.person = Person.id AND 
            lower(EmailAddress.email) LIKE %s || '%%'
            """ % quote_like(text)
        results = Person.select(email_query, clauseTables=['EmailAddress'])
        name_query = """
             Person.teamowner IS NOT NULL AND 
             Person.fti @@ ftq(%s)
            """ % quote(text)
        return results.union(Person.select(name_query), orderBy=orderBy)

    def get(self, personid, default=None):
        """See IPersonSet."""
        try:
            return Person.get(personid)
        except SQLObjectNotFound:
            return default

    def getByEmail(self, email, default=None):
        """See IPersonSet."""
        emailaddress = getUtility(IEmailAddressSet).getByEmail(email)
        if emailaddress is None:
            return default
        assert emailaddress.person is not None
        return emailaddress.person

    def getUbunteros(self, orderBy=None):
        """See IPersonSet."""
        if orderBy is None:
            orderBy = self._defaultOrder
        sigset = getUtility(ISignedCodeOfConductSet)
        lastdate = sigset.getLastAcceptedDate()

        query = AND(Person.q.id==SignedCodeOfConduct.q.ownerID,
                    SignedCodeOfConduct.q.active==True,
                    SignedCodeOfConduct.q.datecreated>=lastdate)

        return Person.select(query, distinct=True, orderBy=orderBy)

    def merge(self, from_person, to_person):
        """Merge a person into another.

        The old user (from_person) will be left as an atavism

        We are not yet game to delete the `from_person` entry from the
        database yet. We will let it roll for a while and see what cruft
        develops -- StuartBishop 20050812
        """
        # Sanity checks
        if ITeam.providedBy(from_person):
            raise TypeError('Got a team as from_person.')
        if ITeam.providedBy(to_person):
            raise TypeError('Got a team as to_person.')
        if not IPerson.providedBy(from_person):
            raise TypeError('from_person is not a person.')
        if not IPerson.providedBy(to_person):
            raise TypeError('to_person is not a person.')

        # since we are doing direct SQL manipulation, make sure all
        # changes have been flushed to the database
        flush_database_updates()

        if getUtility(IEmailAddressSet).getByPerson(from_person).count() > 0:
            raise ValueError('from_person still has email addresses.')

        # Get a database cursor.
        cur = cursor()

        references = list(postgresql.listReferences(cur, 'person', 'id'))

        # These table.columns will be skipped by the 'catch all'
        # update performed later
        skip = [
            ('teammembership', 'person'),
            ('teammembership', 'team'),
            ('teamparticipation', 'person'),
            ('teamparticipation', 'team'),
            ('personlanguage', 'person'),
            ('person', 'merged'),
            ('emailaddress', 'person'),
            ('karmacache', 'person'),
            ('karmatotalcache', 'person'),
            # We don't merge teams, so the poll table can be ignored
            ('poll', 'team'),
            # I don't think we need to worry about the votecast and vote
            # tables, because a real human should never have two accounts
            # in Launchpad that are active members of a given team and voted
            # in a given poll. -- GuilhermeSalgado 2005-07-07
            ('votecast', 'person'),
            ('vote', 'person'),
            # This table is handled entirely by triggers
            ('validpersonorteamcache', 'id'),
            ]

        # Sanity check. If we have an indirect reference, it must
        # be ON DELETE CASCADE. We only have one case of this at the moment,
        # but this code ensures we catch any new ones added incorrectly.
        for src_tab, src_col, ref_tab, ref_col, updact, delact in references:
            # If the ref_tab and ref_col is not Person.id, then we have
            # an indirect reference. Ensure the update action is 'CASCADE'
            if ref_tab != 'person' and ref_col != 'id':
                if updact != 'c':
                    raise RuntimeError(
                        '%s.%s reference to %s.%s must be ON UPDATE CASCADE'
                        % (src_tab, src_col, ref_tab, ref_col)
                        )

        # These rows are in a UNIQUE index, and we can only move them
        # to the new Person if there is not already an entry. eg. if
        # the destination and source persons are both subscribed to a bounty,
        # we cannot change the source persons subscription. We just leave them
        # as noise for the time being.

        to_id = to_person.id
        from_id = from_person.id

        # Update GPGKey. It won't conflict, but our sanity checks don't
        # know that
        cur.execute('UPDATE GPGKey SET owner=%(to_id)d WHERE owner=%(from_id)d'
                    % vars())
        skip.append(('gpgkey','owner'))

        # Update WikiName. Delete the from entry for our internal wikis
        # so it can be reused. Migrate the non-internal wikinames.
        # Note we only allow one wikiname per person for the UBUNTU_WIKI_URL
        # wiki.
        quoted_internal_wikiname = quote(UBUNTU_WIKI_URL)
        cur.execute("""
            DELETE FROM WikiName
            WHERE person=%(from_id)d AND wiki=%(quoted_internal_wikiname)s
            """ % vars()
            )
        cur.execute("""
            UPDATE WikiName SET person=%(to_id)d WHERE person=%(from_id)d
            """ % vars()
            )
        skip.append(('wikiname', 'person'))

        # Update only the BountySubscriptions that will not conflict
        # XXX: Add sampledata and test to confirm this case
        # -- StuartBishop 20050331
        cur.execute('''
            UPDATE BountySubscription
            SET person=%(to_id)d
            WHERE person=%(from_id)d AND bounty NOT IN
                (
                SELECT bounty
                FROM BountySubscription 
                WHERE person = %(to_id)d
                )
            ''' % vars())
        # and delete those left over
        cur.execute('''
            DELETE FROM BountySubscription WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('bountysubscription', 'person'))

        # Update only the SupportContacts that will not conflict
        cur.execute('''
            UPDATE SupportContact
            SET person=%(to_id)d
            WHERE person=%(from_id)d
                AND distribution IS NULL
                AND product NOT IN (
                    SELECT product
                    FROM SupportContact
                    WHERE person = %(to_id)d
                    )
            ''' % vars())
        cur.execute('''
            UPDATE SupportContact
            SET person=%(to_id)d
            WHERE person=%(from_id)d
                AND distribution IS NOT NULL
                AND (distribution, sourcepackagename) NOT IN (
                    SELECT distribution,sourcepackagename
                    FROM SupportContact
                    WHERE person = %(to_id)d
                    )
            ''' % vars())
        # and delete those left over
        cur.execute('''
            DELETE FROM SupportContact WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('supportcontact', 'person'))

        # Update only the TicketSubscriptions that will not conflict
        cur.execute('''
            UPDATE TicketSubscription
            SET person=%(to_id)d
            WHERE person=%(from_id)d AND ticket NOT IN
                (
                SELECT ticket
                FROM TicketSubscription 
                WHERE person = %(to_id)d
                )
            ''' % vars())
        # and delete those left over
        cur.execute('''
            DELETE FROM TicketSubscription WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('ticketsubscription', 'person'))

        # Update PackageBugContact entries
        cur.execute('''
            UPDATE PackageBugContact SET bugcontact=%(to_id)s
            WHERE bugcontact=%(from_id)s
            ''', vars())
        skip.append(('packagebugcontact', 'bugcontact'))

        # Update the SpecificationFeedback entries that will not conflict
        # and trash the rest.
        
        # First we handle the reviewer.
        cur.execute('''
            UPDATE SpecificationFeedback
            SET reviewer=%(to_id)d
            WHERE reviewer=%(from_id)d AND specification NOT IN
                (
                SELECT specification
                FROM SpecificationFeedback
                WHERE reviewer = %(to_id)d
                )
            ''' % vars())
        cur.execute('''
            DELETE FROM SpecificationFeedback WHERE reviewer=%(from_id)d
            ''' % vars())
        skip.append(('specificationfeedback', 'reviewer'))

        # And now we handle the requester.
        cur.execute('''
            UPDATE SpecificationFeedback
            SET requester=%(to_id)d
            WHERE requester=%(from_id)d AND specification NOT IN
                (
                SELECT specification
                FROM SpecificationFeedback
                WHERE requester = %(to_id)d
                )
            ''' % vars())
        cur.execute('''
            DELETE FROM SpecificationFeedback WHERE requester=%(from_id)d
            ''' % vars())
        skip.append(('specificationfeedback', 'requester'))

        # Update the SpecificationSubscription entries that will not conflict
        # and trash the rest
        cur.execute('''
            UPDATE SpecificationSubscription
            SET person=%(to_id)d
            WHERE person=%(from_id)d AND specification NOT IN
                (
                SELECT specification
                FROM SpecificationSubscription
                WHERE person = %(to_id)d
                )
            ''' % vars())
        cur.execute('''
            DELETE FROM SpecificationSubscription WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('specificationsubscription', 'person'))

        # Update only the SprintAttendances that will not conflict
        cur.execute('''
            UPDATE SprintAttendance
            SET attendee=%(to_id)d
            WHERE attendee=%(from_id)d AND sprint NOT IN
                (
                SELECT sprint
                FROM SprintAttendance 
                WHERE attendee = %(to_id)d
                )
            ''' % vars())
        # and delete those left over
        cur.execute('''
            DELETE FROM SprintAttendance WHERE attendee=%(from_id)d
            ''' % vars())
        skip.append(('sprintattendance', 'attendee'))

        # Update only the POSubscriptions that will not conflict
        # XXX: Add sampledata and test to confirm this case
        # -- StuartBishop 20050331
        cur.execute('''
            UPDATE POSubscription
            SET person=%(to_id)d
            WHERE person=%(from_id)d AND id NOT IN (
                SELECT a.id
                    FROM POSubscription AS a, POSubscription AS b
                    WHERE a.person = %(from_id)d AND b.person = %(to_id)d
                    AND a.language = b.language
                    AND a.potemplate = b.potemplate
                    )
            ''' % vars())
        skip.append(('posubscription', 'person'))

        # Update only the POExportRequests that will not conflict
        # and trash the rest
        cur.execute('''
            UPDATE POExportRequest
            SET person=%(to_id)d
            WHERE person=%(from_id)d AND id NOT IN (
                SELECT a.id FROM POExportRequest AS a, POExportRequest AS b
                WHERE a.person = %(from_id)d AND b.person = %(to_id)d
                AND a.potemplate = b.potemplate
                AND a.pofile = b.pofile
                )
            ''' % vars())
        cur.execute('''
            DELETE FROM POExportRequest WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('poexportrequest', 'person'))

        # Update the POSubmissions. They should not conflict since each of
        # them is independent
        cur.execute('''
            UPDATE POSubmission
            SET person=%(to_id)d
            WHERE person=%(from_id)d
            ''' % vars())
        skip.append(('posubmission', 'person'))

        # Update only the TranslationImportQueueEntry that will not conflict
        # and trash the rest
        cur.execute('''
            UPDATE TranslationImportQueueEntry
            SET importer=%(to_id)d
            WHERE importer=%(from_id)d AND id NOT IN (
                SELECT a.id
                FROM TranslationImportQueueEntry AS a,
                     TranslationImportQueueEntry AS b
                WHERE a.importer = %(from_id)d AND b.importer = %(to_id)d
                AND a.distrorelease = b.distrorelease
                AND a.sourcepackagename = b.sourcepackagename
                AND a.productseries = b.productseries
                AND a.path = b.path
                )
            ''' % vars())
        cur.execute('''
            DELETE FROM TranslationImportQueueEntry WHERE importer=%(from_id)d
            ''' % vars())
        skip.append(('translationimportqueueentry', 'importer'))

        # Sanity check. If we have a reference that participates in a
        # UNIQUE index, it must have already been handled by this point.
        # We can tell this by looking at the skip list.
        for src_tab, src_col, ref_tab, ref_col, updact, delact in references:
            uniques = postgresql.listUniques(cur, src_tab, src_col)
            if len(uniques) > 0 and (src_tab, src_col) not in skip:
                raise NotImplementedError(
                        '%s.%s reference to %s.%s is in a UNIQUE index '
                        'but has not been handled' % (
                            src_tab, src_col, ref_tab, ref_col
                            )
                        )

        # Handle all simple cases
        for src_tab, src_col, ref_tab, ref_col, updact, delact in references:
            if (src_tab, src_col) in skip:
                continue
            cur.execute('UPDATE %s SET %s=%d WHERE %s=%d' % (
                src_tab, src_col, to_person.id, src_col, from_person.id
                ))

        # Transfer active team memberships
        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        cur.execute('SELECT team, status FROM TeamMembership WHERE person = %s '
                    'AND status IN (%s,%s)' 
                    % sqlvalues(from_person.id, approved, admin))
        for team_id, status in cur.fetchall():
            cur.execute('SELECT status FROM TeamMembership WHERE person = %s '
                        'AND team = %s'
                        % sqlvalues(to_person.id, team_id))
            result = cur.fetchone()
            if result:
                current_status = result[0]
                # Now we can safely delete from_person's membership record,
                # because we know to_person has a membership entry for this
                # team, so may only need to change its status.
                cur.execute(
                    'DELETE FROM TeamMembership WHERE person = %s AND team = %s'
                    % sqlvalues(from_person.id, team_id))

                if current_status == admin.value:
                    # to_person is already an administrator of this team, no
                    # need to do anything else.
                    continue
                # to_person is either an approved or an inactive member,
                # while from_person is either admin or approved. That means we
                # can safely set from_person's membership status on
                # to_person's membership.
                assert status in (approved.value, admin.value)
                cur.execute(
                    'UPDATE TeamMembership SET status = %s WHERE person = %s '
                    'AND team = %s' % sqlvalues(status, to_person.id, team_id))
            else:
                # to_person is not a member of this team. just change
                # from_person with to_person in the membership record.
                cur.execute(
                    'UPDATE TeamMembership SET person = %s WHERE person = %s '
                    'AND team = %s'
                    % sqlvalues(to_person.id, from_person.id, team_id))

        cur.execute('SELECT team FROM TeamParticipation WHERE person = %s '
                    'AND person != team' % sqlvalues(from_person.id))
        for team_id in cur.fetchall():
            cur.execute('SELECT team FROM TeamParticipation WHERE person = %s '
                        'AND team = %s' % sqlvalues(to_person.id, team_id))
            if not cur.fetchone():
                cur.execute(
                    'UPDATE TeamParticipation SET person = %s WHERE '
                    'person = %s AND team = %s'
                    % sqlvalues(to_person.id, from_person.id, team_id))
            else:
                cur.execute(
                    'DELETE FROM TeamParticipation WHERE person = %s AND '
                    'team = %s' % sqlvalues(from_person.id, team_id))

        # Flag the account as merged
        cur.execute('''
            UPDATE Person SET merged=%(to_id)d WHERE id=%(from_id)d
            ''' % vars())

        # Append a -merged suffix to the account's name.
        name = base = "%s-merged" % from_person.name.encode('ascii')
        cur.execute("SELECT id FROM Person WHERE name = %s" % sqlvalues(name))
        i = 1
        while cur.fetchone():
            name = "%s%d" % (base, i)
            cur.execute("SELECT id FROM Person WHERE name = %s"
                        % sqlvalues(name))
            i += 1
        cur.execute("UPDATE Person SET name = %s WHERE id = %s"
                    % sqlvalues(name, from_person.id))

        # Since we've updated the database behind SQLObject's back,
        # flush its caches.
        flush_database_caches()


class EmailAddress(SQLBase):
    implements(IEmailAddress)

    _table = 'EmailAddress'
    _defaultOrder = ['email']

    email = StringCol(dbName='email', notNull=True, unique=True)
    status = EnumCol(dbName='status', schema=EmailAddressStatus, notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)

    @property
    def statusname(self):
        return self.status.title


class EmailAddressSet:
    implements(IEmailAddressSet)

    def get(self, emailid, default=None):
        """See IEmailAddressSet."""
        try:
            return EmailAddress.get(emailid)
        except SQLObjectNotFound:
            return default

    def getByPerson(self, person):
        return EmailAddress.selectBy(personID=person.id, orderBy='email')

    def getByEmail(self, email, default=None):
        result = EmailAddress.selectOne(
            "lower(email) = %s" % quote(email.strip().lower()))
        if result is None:
            return default
        return result

    def new(self, email, personID, status=EmailAddressStatus.NEW):
        email = email.strip()
        if self.getByEmail(email):
            raise EmailAddressAlreadyTaken(
                "The email address %s is already registered." % email)
        assert status in EmailAddressStatus.items
        return EmailAddress(email=email, status=status, person=personID)


class GPGKey(SQLBase):
    implements(IGPGKey)

    _table = 'GPGKey'

    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)

    keyid = StringCol(dbName='keyid', notNull=True)
    fingerprint = StringCol(dbName='fingerprint', notNull=True)

    keysize = IntCol(dbName='keysize', notNull=True)

    algorithm = EnumCol(dbName='algorithm', notNull=True,
                        schema=GPGKeyAlgorithm)

    active = BoolCol(dbName='active', notNull=True)

    can_encrypt = BoolCol(dbName='can_encrypt', notNull=False)

    @property
    def keyserverURL(self):
        return KEYSERVER_QUERY_URL + self.fingerprint

    @property
    def displayname(self):
        return '%s%s/%s' % (self.keysize, self.algorithm.title, self.keyid)


class GPGKeySet:
    implements(IGPGKeySet)

    def new(self, ownerID, keyid, fingerprint, keysize,
            algorithm, active=True, can_encrypt=False):
        """See IGPGKeySet"""
        return GPGKey(owner=ownerID, keyid=keyid,
                      fingerprint=fingerprint, keysize=keysize,
                      algorithm=algorithm, active=active,
                      can_encrypt=can_encrypt)

    def get(self, key_id, default=None):
        """See IGPGKeySet"""
        try:
            return GPGKey.get(key_id)
        except SQLObjectNotFound:
            return default

    def getByFingerprint(self, fingerprint, default=None):
        """See IGPGKeySet"""
        result = GPGKey.selectOneBy(fingerprint=fingerprint)
        if result is None:
            return default
        return result

    def deactivateGPGKey(self, key_id):
        """See IGPGKeySet"""
        try:
            key = GPGKey.get(key_id)
        except SQLObjectNotFound:
            return None
        key.active = False
        return key

    def activateGPGKey(self, key_id):
        """See IGPGKeySet"""
        try:
            key = GPGKey.get(key_id)
        except SQLObjectNotFound:
            return None
        key.active = True
        return key

    def getGPGKeys(self, ownerid=None, active=True):
        """See IGPGKeySet"""
        if active is False:
            query = ('active=false AND fingerprint NOT IN '
                     '(SELECT fingerprint from LoginToken WHERE fingerprint '
                     'IS NOT NULL AND requester = %s)' % sqlvalues(ownerid))
        else:
            query = 'active=true'

        if ownerid:
            query += ' AND owner=%s' % sqlvalues(ownerid)

        return GPGKey.select(query, orderBy='id')


class SSHKey(SQLBase):
    implements(ISSHKey)

    _table = 'SSHKey'

    person = ForeignKey(foreignKey='Person', dbName='person', notNull=True)
    keytype = EnumCol(dbName='keytype', notNull=True, schema=SSHKeyType)
    keytext = StringCol(dbName='keytext', notNull=True)
    comment = StringCol(dbName='comment', notNull=True)

    @property
    def keytypename(self):
        return self.keytype.title

    @property
    def keykind(self):
        # XXX: This seems rather odd, like it is meant for presentation
        #      of the name of a key.
        #      -- SteveAlexander, 2005-04-23
        if self.keytype == SSHKeyType.DSA:
            return 'ssh-dss'
        elif self.keytype == SSHKeyType.RSA:
            return 'ssh-rsa'
        else:
            return 'Unknown key type'


class SSHKeySet:
    implements(ISSHKeySet)

    def new(self, personID, keytype, keytext, comment):
        return SSHKey(personID=personID, keytype=keytype, keytext=keytext,
                      comment=comment)

    def get(self, id, default=None):
        try:
            return SSHKey.get(id)
        except SQLObjectNotFound:
            return default


class WikiName(SQLBase):
    implements(IWikiName)

    _table = 'WikiName'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    wiki = StringCol(dbName='wiki', notNull=True)
    wikiname = StringCol(dbName='wikiname', notNull=True)

    @property
    def url(self):
        return self.wiki + self.wikiname

class WikiNameSet:
    implements(IWikiNameSet)

    def getByWikiAndName(self, wiki, wikiname):
        """See IWikiNameSet."""
        return WikiName.selectOneBy(wiki=wiki, wikiname=wikiname)

    def getUbuntuWikiByPerson(self, person):
        """See IWikiNameSet."""
        return WikiName.selectOneBy(personID=person.id, wiki=UBUNTU_WIKI_URL)

    def getOtherWikisByPerson(self, person):
        """See IWikiNameSet."""
        return WikiName.select(AND(WikiName.q.personID==person.id,
                                   WikiName.q.wiki!=UBUNTU_WIKI_URL))

    def getAllWikisByPerson(self, person):
        """See IWikiNameSet."""
        return WikiName.selectBy(personID=person.id)

    def get(self, id, default=None):
        """See IWikiNameSet."""
        wiki = WikiName.selectOneBy(id=id)
        if wiki is None:
            return default
        return wiki

    def new(self, person, wiki, wikiname):
        """See IWikiNameSet."""
        return WikiName(personID=person.id, wiki=wiki, wikiname=wikiname)

    def exists(self, wikiname, wiki=UBUNTU_WIKI_URL):
        """See IWikiNameSet."""
        return WikiName.selectOneBy(wiki=wiki, wikiname=wikiname) is not None


class JabberID(SQLBase):
    implements(IJabberID)

    _table = 'JabberID'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    jabberid = StringCol(dbName='jabberid', notNull=True)


class JabberIDSet:
    implements(IJabberIDSet)

    def new(self, person, jabberid):
        """See IJabberIDSet"""
        return JabberID(personID=person.id, jabberid=jabberid)

    def getByJabberID(self, jabberid, default=None):
        """See IJabberIDSet"""
        jabber = JabberID.selectOneBy(jabberid=jabberid)
        if jabber is None:
            return default
        return jabber

    def getByPerson(self, person):
        """See IJabberIDSet"""
        return JabberID.selectBy(personID=person.id)


class IrcID(SQLBase):
    implements(IIrcID)

    _table = 'IrcID'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    network = StringCol(dbName='network', notNull=True)
    nickname = StringCol(dbName='nickname', notNull=True)


class IrcIDSet:
    implements(IIrcIDSet)

    def new(self, person, network, nickname):
        return IrcID(personID=person.id, network=network, nickname=nickname)

