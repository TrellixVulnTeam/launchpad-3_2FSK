# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from datetime import datetime, timedelta

# Zope interfaces
from zope.interface import implements
from zope.interface import directlyProvides, directlyProvidedBy
from zope.component import ComponentLookupError, getUtility

# SQL imports
from sqlobject import DateTimeCol, ForeignKey, IntCol, StringCol, BoolCol
from sqlobject import MultipleJoin, RelatedJoin, SQLObjectNotFound
from sqlobject.sqlbuilder import AND
from canonical.database.sqlbase import SQLBase, quote
from canonical.database.constants import UTC_NOW

# canonical imports
from canonical.launchpad.interfaces import IPerson, ITeam, IPersonSet
from canonical.launchpad.interfaces import ITeamMembership, ITeamParticipation
from canonical.launchpad.interfaces import ITeamParticipationSet
from canonical.launchpad.interfaces import IEmailAddress, IWikiName
from canonical.launchpad.interfaces import IIrcID, IArchUserID, IJabberID
from canonical.launchpad.interfaces import ISSHKey, IGPGKey, IKarma
from canonical.launchpad.interfaces import IObjectAuthorization
from canonical.launchpad.interfaces import IPasswordEncryptor
from canonical.launchpad.interfaces import ISourcePackageSet, IEmailAddressSet

from canonical.launchpad.database.translation_effort import TranslationEffort
from canonical.launchpad.database.soyuz import DistributionRole
from canonical.launchpad.database.soyuz import DistroReleaseRole
from canonical.launchpad.database.bug import Bug
from canonical.launchpad.database.pofile import POTemplate

from canonical.launchpad.webapp.interfaces import ILaunchpadPrincipal
from canonical.lp.dbschema import KarmaField
from canonical.lp.dbschema import EmailAddressStatus
from canonical.lp.dbschema import TeamSubscriptionPolicy
from canonical.lp.dbschema import TeamMembershipStatus
from canonical.lp.dbschema import GPGKeyAlgorithms
from canonical.foaf import nickname


class Person(SQLBase):
    """A Person."""

    implements(IPerson, IObjectAuthorization)

    name = StringCol(dbName='name', alternateID=True)
    password = StringCol(dbName='password', default=None)
    givenname = StringCol(dbName='givenname', default=None)
    familyname = StringCol(dbName='familyname', default=None)
    displayname = StringCol(dbName='displayname', default=None)
    teamdescription = StringCol(dbName='teamdescription', default=None)

    teamowner = ForeignKey(dbName='teamowner', foreignKey='Person', 
                           default=None)

    sshkeys = MultipleJoin('SSHKey', joinColumn='person')

    karma = IntCol(dbName='karma', default=0)
    karmatimestamp = DateTimeCol(dbName='karmatimestamp', default=UTC_NOW)

    subscriptionpolicy = IntCol(dbName='subscriptionpolicy', 
                                default=int(TeamSubscriptionPolicy.MODERATED))
    defaultrenewalperiod = IntCol(dbName='defaultrenewalperiod', default=None)
    defaultmembershipperiod = IntCol(dbName='defaultmembershipperiod',
                                     default=None)

    # RelatedJoin gives us also an addLanguage and removeLanguage for free
    languages = RelatedJoin('Language', joinColumn='person', 
                            otherColumn='language', 
                            intermediateTable='PersonLanguage')

    def get(cls, id, connection=None, selectResults=None):
        """Override the classmethod get from the base class.

        In this case when we're getting a team we mark it with ITeam.
        """
        val = super(Person, cls).get(
            id, connection=connection, selectResults=selectResults)
        if val.teamowner is not None:
            directlyProvides(val, directlyProvidedBy(val) + ITeam)
        return val
    get = classmethod(get)

    def checkPermission(self, principal, permission):
        if principal is None:
            return False

        if permission == "launchpad.Edit":
            teamowner = getattr(self.teamowner, 'id', None)
            logged = getattr(principal, 'id', None)
            if logged and logged == teamowner:
                # I'm the team owner and want to change the team
                # information.
                return True
            return self.id == principal.id

    def browsername(self):
        """Return a name suitable for display on a web page.

        1. If we have a displayname, then browsername is the displayname.

        2. If we have a familyname or givenname, then the browsername
           is "FAMILYNAME Givenname".

        3. If we have no displayname, no familyname and no givenname,
           the browsername is self.name.

        >>> class DummyPerson:
        ...     displayname = None
        ...     familyname = None
        ...     givenname = None
        ...     name = 'the_name'
        ...     # This next line is some special evil magic to allow us to
        ...     # unit test browsername() in isolation.
        ...     browsername = Person.browsername.im_func
        ...
        >>> person = DummyPerson()

        Check with just the name.

        >>> person.browsername()
        'the_name'

        Check with givenname and name.  Just givenname is used.

        >>> person.givenname = 'the_givenname'
        >>> person.browsername()
        'the_givenname'

        Check with givenname, familyname and name.  Both givenname and
        familyname are used.

        >>> person.familyname = 'the_familyname'
        >>> person.browsername()
        'THE_FAMILYNAME the_givenname'

        Check with givenname, familyname, name and displayname.
        Only displayname is used.

        >>> person.displayname = 'the_displayname'
        >>> person.browsername()
        'the_displayname'

        Remove familyname to check with givenname, name and displayname.
        Only displayname is used.

        >>> person.familyname = None
        >>> person.browsername()
        'the_displayname'

        """
        if self.displayname:
            return self.displayname
        elif self.familyname or self.givenname:
            # Make a list containing either ['FAMILYNAME'] or
            # ['FAMILYNAME', 'Givenname'] or ['Givenname'].
            # Then turn it into a space-separated string.
            L = []
            if self.familyname is not None:
                L.append(self.familyname.upper())
            if self.givenname is not None:
                L.append(self.givenname)
            return ' '.join(L)
        else:
            return self.name

    def translatedTemplates(self):
        '''
        SELECT * FROM POTemplate WHERE
            id IN (SELECT potemplate FROM pomsgset WHERE
                id IN (SELECT pomsgset FROM POTranslationSighting WHERE
                    origin = 2
                ORDER BY datefirstseen DESC))
        '''
        return POTemplate.select('''
            id IN (
                SELECT potemplate FROM potmsgset WHERE id IN (
                    SELECT potmsgset FROM pomsgset WHERE id IN (
                        SELECT pomsgset FROM POTranslationSighting WHERE origin = 2
                            ORDER BY datefirstseen DESC)))
            ''')

    def assignKarma(self, karmafield, points=None):
        if karmafield not in KarmaField.items:
            raise TypeError('"%s" is not a valid KarmaField value')
        if points is None:
            try:
                points = KARMA_POINTS[karmafield]
            except KeyError:
                # What about defining a default number of points?
                points = 0
                # Print a warning here, cause someone forgot to add the
                # karmafield to KARMA_POINTS.
        Karma(person=self, karmafield=karmafield.value, points=points)
        # XXX: salgado, 2005-01-12: I think we should recalculate the karma
        # here, but first we must define karma points and depreciation
        # methods.
        self.karma += points

    def inTeam(self, team):
        tp = TeamParticipation.selectBy(teamID=team.id, personID=self.id)
        if tp.count() > 0:
            return True
        else:
            return False

    def hasMembershipEntryFor(self, team):
        results = TeamMembership.selectBy(personID=self.id, teamID=team.id)
        return bool(results.count())

    def unjoinTeam(self, team):
        results = TeamMembership.selectBy(personID=self.id, teamID=team.id)
        assert results.count() <= 1
        if results.count() == 0:
            return False

        tm = results[0]
        if tm.status not in (int(TeamMembershipStatus.ADMIN),
                             int(TeamMembershipStatus.APPROVED)):
            return False

        tm.status = int(TeamMembershipStatus.DEACTIVATED)
        _cleanTeamParticipation(self, team)
        return True

    def joinTeam(self, team):
        if self.inTeam(team):
            return False

        if team.subscriptionpolicy == int(TeamSubscriptionPolicy.RESTRICTED):
            return False
        elif team.subscriptionpolicy == int(TeamSubscriptionPolicy.MODERATED):
            status = int(TeamMembershipStatus.PROPOSED)
        elif team.subscriptionpolicy == int(TeamSubscriptionPolicy.OPEN):
            status = int(TeamMembershipStatus.APPROVED)

        days = team.defaultmembershipperiod
        expires = None
        if days:
            expires = datetime.utcnow() + timedelta(days)

        results = TeamMembership.selectBy(personID=self.id, teamID=team.id)
        if results.count() == 1:
            tm = results[0]
            if tm.status == TeamMembershipStatus.DECLINED:
                # The user is a DECLINED member, we just have to change the
                # status according to the team's subscriptionpolicy.
                tm.status = status
                tm.dateexpires = expires
            else:
                # The user is a member and the status is not DECLINED, there's
                # nothing we can do for it.
                return False
        else:
            TeamMembership(personID=self.id, teamID=team.id, status=status,
                           dateexpires=expires)
                           
        if status == int(TeamMembershipStatus.APPROVED):
            _fillTeamParticipation(self, team)
        return True

    def getMembershipsByStatus(self, status):
        query = ("TeamMembership.team = %d AND TeamMembership.status = %d "
                 "AND Person.id = TeamMembership.team") % (self.id, status)
        return list(TeamMembership.select(query, clauseTables=['Person']))

    def _getEmailsByStatus(self, status):
        query = AND(EmailAddress.q.personID==self.id,
                    EmailAddress.q.status==int(status))
        return list(EmailAddress.select(query))

    def getMembersByStatus(self, status):
        query = ("TeamMembership.team = %d AND TeamMembership.status = %d "
                 "AND TeamMembership.person = Person.id") % (self.id, status)
        return list(Person.select(query, clauseTables=['TeamMembership']))

    #
    # Properties
    #

    def _title(self):
        return self.browsername()
    title = property(_title)

    def _deactivatedmembers(self): 
        return self.getMembersByStatus(int(TeamMembershipStatus.DEACTIVATED))
    deactivatedmembers = property(_deactivatedmembers)

    def _expiredmembers(self): 
        return self.getMembersByStatus(int(TeamMembershipStatus.EXPIRED))
    expiredmembers = property(_expiredmembers)

    def _declinedmembers(self): 
        return self.getMembersByStatus(int(TeamMembershipStatus.DECLINED))
    declinedmembers = property(_declinedmembers)

    def _proposedmembers(self):
        return self.getMembersByStatus(int(TeamMembershipStatus.PROPOSED))
    proposedmembers = property(_proposedmembers)

    def _administrators(self):
        return self.getMembersByStatus(int(TeamMembershipStatus.ADMIN))
    administrators = property(_administrators)

    def _approvedmembers(self):
        return self.getMembersByStatus(int(TeamMembershipStatus.APPROVED))
    approvedmembers = property(_approvedmembers)

    def _memberships(self):
        return list(TeamMembership.selectBy(personID=self.id))
    memberships = property(_memberships)

    def _teams(self):
        # XXX: Fix this by doing a query in Person
        memberships = TeamMembership.selectBy(personID=self.id)
        return [m.team for m in memberships]
    teams = property(_teams)

    def _superteams(self):
        # XXX: salgado, 2005-02-22: Using getUtility() here is breaking the
        # teamparticipation.txt doctest.
        #teampart = getUtility(ITeamParticipationSet)
        teampart = TeamParticipationSet()
        return teampart.getSuperTeams(self)
    superteams = property(_superteams)

    def _subteams(self):
        # XXX: salgado, 2005-02-22: Using getUtility() here is breaking the
        # teamparticipation.txt doctest.
        #teampart = getUtility(ITeamParticipationSet)
        teampart = TeamParticipationSet()
        return teampart.getSubTeams(self)
    subteams = property(_subteams)

    def _distroroles(self):
        return list(DistributionRole.selectBy(personID=self.id))
    distroroles = property(_distroroles)

    def _distroreleaseroles(self):
        return list(DistroReleaseRole.selectBy(personID=self.id))
    distroreleaseroles = property(_distroreleaseroles)

    def _setPreferredemail(self, email):
        assert email.person == self
        preferredemail = self.preferredemail
        if preferredemail is not None:
            preferredemail.status = int(EmailAddressStatus.VALIDATED)
        email.status = int(EmailAddressStatus.PREFERRED)

    def _getPreferredemail(self):
        status = EmailAddressStatus.PREFERRED
        emails = list(self._getEmailsByStatus(status))
        # There can be only one preferred email for a given person at a
        # given time, and this constraint must be ensured in the DB, but
        # it's not a problem if we ensure this constraint here as well.
        length = len(emails)
        assert length <= 1
        if length:
            return emails[0]
        return None
    preferredemail = property(_getPreferredemail, _setPreferredemail)

    def _validatedemails(self):
        status = EmailAddressStatus.VALIDATED
        return self._getEmailsByStatus(status)
    validatedemails = property(_validatedemails)

    def _notvalidatedemails(self):
        status = EmailAddressStatus.NEW
        return self._getEmailsByStatus(status)
    notvalidatedemails = property(_notvalidatedemails)

    def _bugs(self):
        return list(Bug.selectBy(ownerID=self.id))
    bugs= property(_bugs)

    def _translations(self):
        return list(TranslationEffort.selectBy(ownerID=self.id))
    translations = property(_translations)

    def _activities(self):
        return list(Karma.selectBy(personID=self.id))
    activities = property(_activities)

    def _wiki(self):
        # XXX: salgado, 2005-01-14: This method will probably be replaced
        # by a MultipleJoin since we have a good UI to add multiple Wikis. 
        wiki = WikiName.selectBy(personID=self.id)
        count = wiki.count()
        if count:
            assert count == 1
            return wiki[0]
    wiki = property(_wiki)

    def _jabber(self):
        # XXX: salgado, 2005-01-14: This method will probably be replaced
        # by a MultipleJoin since we have a good UI to add multiple
        # JabberIDs. 
        jabber = JabberID.selectBy(personID=self.id)
        if jabber.count() == 0:
            return None
        return jabber[0]
    jabber = property(_jabber)

    def _archuser(self):
        # XXX: salgado, 2005-01-14: This method will probably be replaced
        # by a MultipleJoin since we have a good UI to add multiple
        # ArchUserIDs. 
        archuser = ArchUserID.selectBy(personID=self.id)
        if archuser.count() == 0:
            return None
        return archuser[0]
    archuser = property(_archuser)

    def _irc(self):
        # XXX: salgado, 2005-01-14: This method will probably be replaced
        # by a MultipleJoin since we have a good UI to add multiple
        # IrcIDs. 
        irc = IrcID.selectBy(personID=self.id)
        if irc.count() == 0:
            return None
        return irc[0]
    irc = property(_irc)

    def _gpg(self):
        # XXX: salgado, 2005-01-14: This method will probably be replaced
        # by a MultipleJoin since we have a good UI to add multiple
        # GPGKeys. 
        gpg = GPGKey.selectBy(personID=self.id)
        if gpg.count() == 0:
            return None
        return gpg[0]
    gpg = property(_gpg)

    def _getSourcesByPerson(self):
        sputil = getUtility(ISourcePackageSet)
        return list(sputil.getByPersonID(self.id))
    packages = property(_getSourcesByPerson)


class PersonSet(object):
    """The set of persons."""
    implements(IPersonSet)

    def __init__(self):
        self.title = 'Launchpad People'

    def __iter__(self):
        return self.getall()

    def __getitem__(self, personid):
        """See IPersonSet."""
        person = self.get(personid)
        if person is None:
            raise KeyError, personid
        else:
            return person

    def newTeam(self, *args, **kw):
        """See IPersonSet."""
        ownerID = kw.get('teamownerID')
        assert ownerID
        owner = Person.get(ownerID)
        team = Person(**kw)
        _fillTeamParticipation(owner, team)
        return team

    def newPerson(self, *args, **kw):
        """See IPersonSet."""
        assert not kw.get('teamownerID')
        if kw.has_key('password'):
            # encryptor = getUtility(IPasswordEncryptor)
            # XXX: Carlos Perello Marin 22/12/2004 We cannot use getUtility
            # from initZopeless scripts and Rosetta's import_daemon.py
            # calls indirectly to this function :-(
            from canonical.launchpad.webapp.authentication \
                import SSHADigestEncryptor
            encryptor = SSHADigestEncryptor()
            kw['password'] = encryptor.encrypt(kw['password'])

        person = Person(**kw)
        # "Each Person is a member of their own Team effectively, so there is a
        #  TeamParticipation entry for each person, with themselves as the
        #  member."
        # More info: TeamParticipationUsage spec.
        _fillTeamParticipation(person, person)
        return person

    def getByName(self, name, default=None):
        """See IPersonSet."""
        results = Person.selectBy(name=name)
        if results.count() == 1:
            return results[0]
        else:
            return default

    def get(self, personid, default=None):
        """See IPersonSet."""
        try:
            return Person.get(personid)
        except SQLObjectNotFound:
            return default

    def getAll(self):
        """See IPersonSet."""
        return Person.select(orderBy='displayname')

    def getByEmail(self, email, default=None):
        """See IPersonSet."""
        results = EmailAddress.select("""lower(email) = %s
                        """ % quote(email.lower()))
        resultscount = results.count()
        if resultscount == 0:
            return default
        elif resultscount == 1:
            return results[0].person
        else:
            raise AssertionError(
                'There were %s email addresses matching %s'
                % (resultscount, email))

    def getContributorsForPOFile(self, pofile):
        """See IPersonSet."""
        return Person.select('''
            POTranslationSighting.person = Person.id AND
            POTranslationSighting.pomsgset = POMsgSet.id AND
            POMsgSet.pofile = %d''' % pofile.id,
            clauseTables=('POTranslationSighting', 'POMsgSet',),
            distinct=True, orderBy='displayname')


def createPerson(email, displayname=None, givenname=None, familyname=None,
                 password=None):
    """Create a new Person and an EmailAddress for that Person.
    
    Generate a unique nickname from the email address provided, create a
    Person with that nickname and then create the EmailAddress for the new
    Person. This function is provided mainly for nicole, debsync and POFile raw
    importer, which generally have only the email and displayname to create a
    new Person.
    """
    kw = {}
    try:
        kw['name'] = nickname.generate_nick(email)
    except NicknameGenerationError:
        return None

    kw['displayname'] = displayname
    kw['givenname'] = givenname
    kw['familyname'] = familyname
    kw['password'] = password
    person = PersonSet().newPerson(**kw)

    new = int(EmailAddressStatus.NEW)
    EmailAddress(person=person.id, email=email.lower(), status=new)

    return person


def personFromPrincipal(principal):
    """Adapt canonical.launchpad.webapp.interfaces.ILaunchpadPrincipal
       to IPerson
    """
    if ILaunchpadPrincipal.providedBy(principal):
        return Person.get(principal.id)
    else:
        # This is not actually necessary when this is used as an adapter
        # from ILaunchpadPrincipal, as we know we always have an
        # ILaunchpadPrincipal.
        #
        # When Zope3 interfaces allow returning None for "cannot adapt"
        # we can return None here.
        ##return None
        raise ComponentLookupError


class EmailAddress(SQLBase):
    implements(IEmailAddress)

    _table = 'EmailAddress'

    email = StringCol(dbName='email', notNull=True, alternateID=True)
    status = IntCol(dbName='status', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)

    def _statusname(self):
        for status in EmailAddressStatus.items:
            if status.value == self.status:
                return status.title
        return 'Unknown (%d)' %self.status
    
    statusname = property(_statusname)


class EmailAddressSet(object):
    implements(IEmailAddressSet)

    def get(self, emailid, default=None):
        """See IEmailAddressSet."""
        try:
            return EmailAddress.get(emailid)
        except SQLObjectNotFound:
            return default

    def __getitem__(self, emailid):
        """See IEmailAddressSet."""
        email = self.get(emailid)
        if email is None:
            raise KeyError, emailid
        else:
            return email

    def getByPerson(self, personid):
        return list(EmailAddress.selectBy(personID=personid))

    def getByEmail(self, email, default=None):
        try:
            return EmailAddress.byEmail(email)
        except SQLObjectNotFound:
            return default


class GPGKey(SQLBase):
    implements(IGPGKey)

    _table = 'GPGKey'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)

    keyid = StringCol(dbName='keyid', notNull=True)
    pubkey = StringCol(dbName='pubkey', notNull=True)
    fingerprint = StringCol(dbName='fingerprint', notNull=True)

    keysize = IntCol(dbName='keysize', notNull=True)
    algorithm = IntCol(dbName='algorithm', notNull=True)

    revoked = BoolCol(dbName='revoked', notNull=True)

    def _algorithmname(self):
        for algorithm in GPGKeyAlgorithms.items:
            if algorithm.value == self.algorithm:
                return algorithm.title
        return 'Unknown (%d)' %self.algorithm
    
    algorithmname = property(_algorithmname)


class SSHKey(SQLBase):
    implements(ISSHKey)

    _table = 'SSHKey'

    person = ForeignKey(foreignKey='Person', dbName='person', notNull=True)
    keytype = StringCol(dbName='keytype', notNull=True)
    keytext = StringCol(dbName='keytext', notNull=True)
    comment = StringCol(dbName='comment', notNull=True)


class ArchUserID(SQLBase):
    implements(IArchUserID)

    _table = 'ArchUserID'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    archuserid = StringCol(dbName='archuserid', notNull=True)
    

class WikiName(SQLBase):
    implements(IWikiName)

    _table = 'WikiName'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    wiki = StringCol(dbName='wiki', notNull=True)
    wikiname = StringCol(dbName='wikiname', notNull=True)


class JabberID(SQLBase):
    implements(IJabberID)

    _table = 'JabberID'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    jabberid = StringCol(dbName='jabberid', notNull=True)


class IrcID(SQLBase):
    implements(IIrcID)

    _table = 'IrcID'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    network = StringCol(dbName='network', notNull=True)
    nickname = StringCol(dbName='nickname', notNull=True)


class TeamMembership(SQLBase):
    implements(ITeamMembership)

    _table = 'TeamMembership'

    team = ForeignKey(dbName='team', foreignKey='Person', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    reviewer = ForeignKey(dbName='reviewer', foreignKey='Person', default=None)
    status = IntCol(dbName='status', notNull=True)
    datejoined = DateTimeCol(dbName='datejoined', default=datetime.utcnow(),
                             notNull=True)
    dateexpires = DateTimeCol(dbName='dateexpires', default=None)
    reviewercomment = StringCol(dbName='reviewercomment', default=None)

    def _statusname(self):
        for statusitem in TeamMembershipStatus.items:
            if statusitem.value == self.status:
                return statusitem.title
        return 'Unknown (%d)' % self.status
    statusname = property(_statusname)


class TeamParticipationSet(object):
    """ A Set for TeamParticipation objects. """

    implements(ITeamParticipationSet)

    def getAllMembers(self, team):
        return [t.person for t in TeamParticipation.selectBy(teamID=team.id)]

    def getSubTeams(self, team):
        clauseTables = ('person',)
        query = ("TeamParticipation.team = %d "
                 "AND Person.id = TeamParticipation.person "
                 "AND Person.teamowner IS NOT NULL" % team.id)
        results = TeamParticipation.select(query, clauseTables=clauseTables)
        return [t.person for t in results]

    def getSuperTeams(self, team):
        clauseTables = ('person',)
        query = ("TeamParticipation.person = %d "
                 "AND Person.id = TeamParticipation.team " % team.id)
        results = TeamParticipation.select(query, clauseTables=clauseTables)
        return [t.team for t in results]


class TeamParticipation(SQLBase):
    implements(ITeamParticipation)

    _table = 'TeamParticipation'

    team = ForeignKey(foreignKey='Person', dbName='team', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)


def _cleanTeamParticipation(person, team):
    """Remove relevant entries in TeamParticipation for given person and team.

    Remove all tuples "person, team" from TeamParticipation for the given
    person and team (together with all its superteams), unless this person is
    an indirect member of the given team. More information on how to use the 
    TeamParticipation table can be found in the TeamParticipationUsage spec.
    """
    members = [person]
    if person.teamowner is not None:
        # The given person is, in fact, a team, and in this case we must 
        # remove all of its members from the given team and from its 
        # superteams.
        # XXX: salgado, 2005-02-22: Using getUtility() here is breaking the
        # teamparticipation.txt doctest.
        #teampart = getUtility(ITeamParticipationSet)
        teampart = TeamParticipationSet()
        members.extend(teampart.getAllMembers(person))

    for member in members:
        for subteam in team.subteams:
            # This person is an indirect member of this team. We cannot remove
            # its TeamParticipation entry.
            if member.inTeam(subteam):
                break
        else:
            for t in team.superteams + [team]:
                r = TeamParticipation.selectBy(personID=member.id, teamID=t.id)
                if r.count() > 0:
                    assert r.count() == 1
                    r[0].destroySelf()


def _fillTeamParticipation(person, team):
    """Add relevant entries in TeamParticipation for given person and team.

    Add a tuple "person, team" in TeamParticipation for the given team and all
    of its superteams. More information on how to use the TeamParticipation 
    table can be found in the TeamParticipationUsage spec.
    """
    members = [person]
    if person.teamowner is not None:
        # The given person is, in fact, a team, and in this case we must 
        # add all of its members to the given team and to its superteams.
        # XXX: salgado, 2005-02-22: Using getUtility() here is breaking the
        # teamparticipation.txt doctest.
        #teampart = getUtility(ITeamParticipationSet)
        teampart = TeamParticipationSet()
        members.extend(teampart.getAllMembers(person))

    for member in members:
        for t in team.superteams + [team]:
            if not member.inTeam(t):
                TeamParticipation(personID=member.id, teamID=t.id)


class Karma(SQLBase):
    implements(IKarma)

    _table = 'Karma'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    points = IntCol(dbName='points', notNull=True, default=0)
    karmafield = IntCol(dbName='karmafield', notNull=True)
    datecreated = DateTimeCol(dbName='datecreated', notNull=True, default='NOW')

    def _karmafieldname(self):
        try:
            return KarmaField.items[self.karmafield].title
        except KeyError:
            return 'Unknown (%d)' % self.karmafield

    karmafieldname = property(_karmafieldname)


# XXX: These points are totally *CRAP*.
KARMA_POINTS = {KarmaField.BUG_REPORT: 10,
                KarmaField.BUG_FIX: 20,
                KarmaField.BUG_COMMENT: 5,
                KarmaField.WIKI_EDIT: 2,
                KarmaField.WIKI_CREATE: 3,
                KarmaField.PACKAGE_UPLOAD: 10}

