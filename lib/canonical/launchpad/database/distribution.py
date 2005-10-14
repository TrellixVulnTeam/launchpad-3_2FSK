# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Distribution', 'DistributionSet', 'DistroPackageFinder']

from zope.interface import implements

from sqlobject import (
    RelatedJoin, SQLObjectNotFound, StringCol, ForeignKey, MultipleJoin)

from canonical.database.sqlbase import SQLBase, quote, sqlvalues
from canonical.launchpad.database.bug import BugSet
from canonical.launchpad.database.bugtask import BugTask, BugTaskSet
from canonical.launchpad.database.distributionbounty import DistributionBounty
from canonical.launchpad.database.distrorelease import DistroRelease
from canonical.launchpad.database.sourcepackage import SourcePackage
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.specification import Specification
from canonical.launchpad.database.ticket import Ticket
from canonical.launchpad.database.publishing import (
    SourcePackageFilePublishing, BinaryPackageFilePublishing)
from canonical.launchpad.database.librarian import LibraryFileAlias
from canonical.launchpad.database.build import Build
from canonical.lp.dbschema import (
    EnumCol, BugTaskStatus, DistributionReleaseStatus, TranslationPermission)
from canonical.launchpad.interfaces import (
    IDistribution, IDistributionSet, IDistroPackageFinder, IHasBuildRecords,
    NotFoundError)


class Distribution(SQLBase):
    """A distribution of an operating system, e.g. Debian GNU/Linux."""
    implements(IDistribution, IHasBuildRecords)

    _defaultOrder = 'name'

    name = StringCol(notNull=True, alternateID=True, unique=True)
    displayname = StringCol(notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    description = StringCol(notNull=True)
    domainname = StringCol(notNull=True)
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    members = ForeignKey(dbName='members', foreignKey='Person', notNull=True)
    translationgroup = ForeignKey(dbName='translationgroup',
        foreignKey='TranslationGroup', notNull=False, default=None)
    translationpermission = EnumCol(dbName='translationpermission',
        notNull=True, schema=TranslationPermission,
        default=TranslationPermission.OPEN)
    lucilleconfig = StringCol(notNull=False, default=None)
    releases = MultipleJoin('DistroRelease', joinColumn='distribution',
                            orderBy=['version', '-id'])
    bounties = RelatedJoin(
        'Bounty', joinColumn='distribution', otherColumn='bounty',
        intermediateTable='DistroBounty')
    bugtasks = MultipleJoin('BugTask', joinColumn='distribution')
    milestones = MultipleJoin('Milestone', joinColumn='distribution')
    specifications = MultipleJoin('Specification', joinColumn='distribution',
        orderBy=['-datecreated', 'id'])
    tickets = MultipleJoin('Ticket', joinColumn='distribution',
        orderBy=['-datecreated', 'id'])

    uploadsender = StringCol(notNull=False, default=None)
    uploadadmin = StringCol(notNull=False, default=None)

    uploaders = MultipleJoin('DistroComponentUploader',
                             joinColumn='distribution')

    def searchTasks(self, search_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        search_params.setDistribution(self)
        return BugTaskSet().search(search_params)

    def newBug(self, owner, title, description):
        """See IBugTarget."""
        return BugSet().createBug(
            distribution=self, comment=description, title=title, owner=owner)

    @property
    def open_cve_bugtasks(self):
        """See IDistribution."""
        result = BugTask.select("""
            CVE.id = BugCve.cve AND
            BugCve.bug = Bug.id AND
            BugTask.bug = Bug.id AND
            BugTask.distribution=%s AND
            BugTask.status IN (%s, %s)
            """ % sqlvalues(
                self.id,
                BugTaskStatus.NEW,
                BugTaskStatus.ACCEPTED),
            clauseTables=['Bug', 'Cve', 'BugCve'],
            orderBy=['-severity', 'datecreated'])
        return result

    @property
    def resolved_cve_bugtasks(self):
        """See IDistribution."""
        result = BugTask.select("""
            CVE.id = BugCve.cve AND
            BugCve.bug = Bug.id AND
            BugTask.bug = Bug.id AND
            BugTask.distribution=%s AND
            BugTask.status IN (%s, %s, %s)
            """ % sqlvalues(
                self.id,
                BugTaskStatus.REJECTED,
                BugTaskStatus.FIXED,
                BugTaskStatus.PENDINGUPLOAD),
            clauseTables=['Bug', 'Cve', 'BugCve'],
            orderBy=['-severity', 'datecreated'])
        return result

    @property
    def currentrelease(self):
        # if we have a frozen one, return that
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.FROZEN:
                return rel
        # if we have one in development, return that
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.DEVELOPMENT:
                return rel
        # if we have a stable one, return that
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.CURRENT:
                return rel
        # if we have ANY, return the first one
        if len(self.releases) > 0:
            return self.releases[0]
        return None

    def __getitem__(self, name):
        for release in self.releases:
            if release.name == name:
                return release
        raise NotFoundError(name)

    def __iter__(self):
        return iter(self.releases)

    def bugCounter(self):
        counts = []

        clauseTables = ["VSourcePackageInDistro"]
        severities = [
            BugTaskStatus.NEW,
            BugTaskStatus.ACCEPTED,
            BugTaskStatus.REJECTED,
            BugTaskStatus.FIXED]

        query = ("bugtask.distribution = %s AND "
                 "bugtask.bugstatus = %i")

        for severity in severities:
            query = query % (quote(self.id), severity)
            count = BugTask.select(query, clauseTables=clauseTables).count()
            counts.append(count)

        return counts
    bugCounter = property(bugCounter)

    def getRelease(self, name_or_version):
        """See IDistribution."""
        distrorelease = DistroRelease.selectOneBy(
            distributionID=self.id, name=name_or_version)
        if distrorelease is None:
            distrorelease = DistroRelease.selectOneBy(
                distributionID=self.id, version=name_or_version)
            if distrorelease is None:
                raise NotFoundError(name_or_version)
        return distrorelease

    def getDevelopmentReleases(self):
        """See IDistribution."""
        return DistroRelease.selectBy(
            distributionID = self.id,
            releasestatus = DistributionReleaseStatus.DEVELOPMENT)

    def getSourcePackage(self, name):
        """See IDistribution."""
        return SourcePackage(name, self.currentrelease)

    def getMilestone(self, name):
        """See IDistribution."""
        return Milestone.selectOne("""
            distribution = %s AND
            name = %s
            """ % sqlvalues(self.id, name))

    def getSpecification(self, name):
        """See ISpecificationTarget."""
        return Specification.selectOneBy(distributionID=self.id, name=name)

    def newTicket(self, owner, title, description):
        """See ITicketTarget."""
        return Ticket(title=title, description=description, owner=owner,
            distribution=self)

    def getTicket(self, ticket_num):
        """See ITicketTarget."""
        # first see if there is a ticket with that number
        try:
            ticket = Ticket.get(ticket_num)
        except SQLObjectNotFound:
            return None
        # now verify that that ticket is actually for this target
        if ticket.target != self:
            return None
        return ticket

    def ensureRelatedBounty(self, bounty):
        """See IDistribution."""
        for curr_bounty in self.bounties:
            if bounty.id == curr_bounty.id:
                return None
        linker = DistributionBounty(distribution=self, bounty=bounty)
        return None

    def getDistroReleaseAndPocket(self, distrorelease_name):
        """See IDistribution."""
        from canonical.archivepublisher.publishing import (
            pocketsuffix, suffixpocket)

        # Get the list of suffixes
        suffixes = [suffix for suffix, ignored in suffixpocket.items()]
        # Sort it longest string first
        suffixes.sort(key=len, reverse=True)
        
        for suffix in suffixes:
            if distrorelease_name.endswith(suffix):
                try:
                    left_size = len(distrorelease_name) - len(suffix)
                    return (self[distrorelease_name[:left_size]],
                            suffixpocket[suffix])
                except KeyError:
                    # Swallow KeyError to continue round the loop
                    pass

        raise NotFoundError(distrorelease_name)

    def getFileByName(self, filename, source=True, binary=True):
        """See IDistribution."""
        assert (source or binary), "searching in an explicitly empty " \
               "space is pointless"
        if source:
            candidate = SourcePackageFilePublishing.selectOneBy(
                distribution=self.id,
                libraryfilealiasfilename=filename)
            if candidate is not None:
                return LibraryFileAlias.get(candidate.libraryfilealias)
        if binary:
            candidate = BinaryPackageFilePublishing.selectOneBy(
                distribution=self.id,
                libraryfilealiasfilename=filename)
            if candidate is not None:
                return LibraryFileAlias.get(candidate.libraryfilealias)
        raise NotFoundError(filename)


    def getBuildRecords(self, status=None, limit=10):
        """See IHasBuildRecords"""
        # find out the distroarchreleases in question
        ids_list = []
        for release in self.releases:
            ids = ','.join(
                '%d' % arch.id for arch in release.architectures)
            # do not mess pgsql sintaxe with empty chuncks 
            if ids:
                ids_list.append(ids)
        
        arch_ids = ','.join(ids_list)

        # if not distroarchrelease was found return None
        if not arch_ids:
            return None

        # specific status or simply touched by a builder
        if status:
            status_clause = "buildstate=%s" % sqlvalues(status)
        else:
            status_clause = "builder is not NULL"

        return Build.select(
            "distroarchrelease IN (%s) AND %s" % (arch_ids, status_clause), 
            limit=limit, orderBy="-datebuilt")


class DistributionSet:
    """This class is to deal with Distribution related stuff"""

    implements(IDistributionSet)

    def __init__(self):
        self.title = "Launchpad Distributions"

    def __iter__(self):
        return iter(Distribution.select())

    def __getitem__(self, name):
        try:
            return Distribution.byName(name)
        except SQLObjectNotFound:
            raise NotFoundError(name)
        
    def get(self, distributionid):
        """See canonical.launchpad.interfaces.IDistributionSet."""
        return Distribution.get(distributionid)

    def count(self):
        return Distribution.select().count()

    def getDistros(self):
        """Returns all Distributions available on the database"""
        return Distribution.select()

    def getByName(self, name):
        """Returns a Distribution with name = name"""
        return self[name]

    def new(self, name, displayname, title, description, summary, domainname,
            members, owner):
        return Distribution(
            name=name,
            displayname=displayname,
            title=title,
            description=description,
            summary=summary,
            domainname=domainname,
            members=members,
            owner=owner)

class DistroPackageFinder:

    implements(IDistroPackageFinder)

    def __init__(self, distribution=None, processorfamily=None):
        self.distribution = distribution
        # XXX kiko: and what about processorfamily?

