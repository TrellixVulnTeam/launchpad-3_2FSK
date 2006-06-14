# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Distribution', 'DistributionSet']

from zope.interface import implements
from zope.component import getUtility

from sqlobject import (
    BoolCol, ForeignKey, SQLMultipleJoin, SQLRelatedJoin, StringCol,
    SQLObjectNotFound)
from sqlobject.sqlbuilder import AND, OR

from canonical.cachedproperty import cachedproperty

from canonical.database.sqlbase import SQLBase, quote, sqlvalues, quote_like

from canonical.launchpad.components.bugtarget import BugTargetBase

from canonical.launchpad.database.bug import BugSet
from canonical.launchpad.database.bugtask import BugTask, BugTaskSet
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.specification import Specification
from canonical.launchpad.database.ticket import Ticket, TicketSet
from canonical.launchpad.database.distrorelease import DistroRelease
from canonical.launchpad.database.publishedpackage import PublishedPackage
from canonical.launchpad.database.librarian import LibraryFileAlias
from canonical.launchpad.database.binarypackagename import (
    BinaryPackageName)
from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.distributionbounty import DistributionBounty
from canonical.launchpad.database.distributionmirror import DistributionMirror
from canonical.launchpad.database.distributionsourcepackage import (
    DistributionSourcePackage)
from canonical.launchpad.database.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease)
from canonical.launchpad.database.distributionsourcepackagecache import (
    DistributionSourcePackageCache)
from canonical.launchpad.database.sourcepackagename import (
    SourcePackageName)
from canonical.launchpad.database.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.database.supportcontact import SupportContact
from canonical.launchpad.database.publishing import (
    SourcePackageFilePublishing, BinaryPackageFilePublishing,
    SourcePackagePublishing)
from canonical.launchpad.helpers import shortlist

from canonical.lp.dbschema import (
    EnumCol, BugTaskStatus, DistributionReleaseStatus, MirrorContent,
    TranslationPermission, SpecificationSort, SpecificationFilter,
    MirrorPulseType)

from canonical.launchpad.interfaces import (
    IDistribution, IDistributionSet, NotFoundError,
    IHasBuildRecords, ISourcePackageName, IBuildSet,
    UNRESOLVED_BUGTASK_STATUSES, RESOLVED_BUGTASK_STATUSES)

from sourcerer.deb.version import Version

from canonical.launchpad.validators.name import valid_name


class Distribution(SQLBase, BugTargetBase):
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
    bugcontact = ForeignKey(
        dbName='bugcontact', foreignKey='Person', notNull=False, default=None)
    security_contact = ForeignKey(
        dbName='security_contact', foreignKey='Person', notNull=False,
        default=None)
    driver = ForeignKey(
        foreignKey="Person", dbName="driver", notNull=False, default=None)
    members = ForeignKey(dbName='members', foreignKey='Person', notNull=True)
    translationgroup = ForeignKey(dbName='translationgroup',
        foreignKey='TranslationGroup', notNull=False, default=None)
    translationpermission = EnumCol(dbName='translationpermission',
        notNull=True, schema=TranslationPermission,
        default=TranslationPermission.OPEN)
    lucilleconfig = StringCol(notNull=False, default=None)
    uploadsender = StringCol(notNull=False, default=None)
    uploadadmin = StringCol(notNull=False, default=None)
    archiveadmin = ForeignKey(dbName='archiveadmin', foreignKey='Person',
                              default=None, notNull=False)
    bounties = SQLRelatedJoin(
        'Bounty', joinColumn='distribution', otherColumn='bounty',
        intermediateTable='DistributionBounty')
    milestones = SQLMultipleJoin('Milestone', joinColumn='distribution',
        orderBy=['dateexpected', 'name'])
    uploaders = SQLMultipleJoin('DistroComponentUploader',
        joinColumn='distribution')
    official_malone = BoolCol(dbName='official_malone', notNull=True,
        default=False)
    official_rosetta = BoolCol(dbName='official_rosetta', notNull=True,
        default=False)
    translation_focus = ForeignKey(dbName='translation_focus',
        foreignKey='DistroRelease', notNull=False, default=None)

    @property
    def source_package_caches(self):
        # XXX: should be moved back to SQLMultipleJoin when it supports
        # prejoin
        cache = DistributionSourcePackageCache.selectBy(distributionID=self.id,
                    orderBy="DistributionSourcePackageCache.name")
        return cache.prejoin(['sourcepackagename'])

    @property
    def archive_mirrors(self):
        """See canonical.launchpad.interfaces.IDistribution."""
        return DistributionMirror.selectBy(
            distributionID=self.id, content=MirrorContent.ARCHIVE,
            official_approved=True, official_candidate=True, enabled=True)

    @property
    def release_mirrors(self):
        """See canonical.launchpad.interfaces.IDistribution."""
        return DistributionMirror.selectBy(
            distributionID=self.id, content=MirrorContent.RELEASE,
            official_approved=True, official_candidate=True, enabled=True)

    @property
    def disabled_mirrors(self):
        """See canonical.launchpad.interfaces.IDistribution."""
        return DistributionMirror.selectBy(
            distributionID=self.id, enabled=False)

    @property
    def unofficial_mirrors(self):
        """See canonical.launchpad.interfaces.IDistribution."""
        query = OR(DistributionMirror.q.official_candidate==False,
                   DistributionMirror.q.official_approved==False) 
        return DistributionMirror.select(
            AND(DistributionMirror.q.distributionID==self.id, query))

    @property
    def full_functionality(self):
        """See IDistribution."""
        if self.name == 'ubuntu':
            return True
        return False

    @cachedproperty
    def releases(self):
        # This is used in a number of places and given it's already
        # listified, why not spare the trouble of regenerating?
        ret = DistroRelease.selectBy(distributionID=self.id)
        return sorted(ret, key=lambda a: Version(a.version), reverse=True)

    def searchTasks(self, search_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        search_params.setDistribution(self)
        return BugTaskSet().search(search_params)

    def getMirrorByName(self, name):
        """See IDistribution."""
        return DistributionMirror.selectOneBy(distributionID=self.id, name=name)

    def newMirror(self, owner, name, speed, country, content,
                  pulse_type=MirrorPulseType.PUSH, displayname=None,
                  description=None, http_base_url=None, ftp_base_url=None,
                  rsync_base_url=None, file_list=None, official_candidate=False,
                  enabled=False, pulse_source=None):
        """See IDistribution."""

        # NB this functionality is only available to distributions that have
        # the full functionality of Launchpad enabled. This is Ubuntu and
        # commercial derivatives that have been specifically given this
        # ability
        if not self.full_functionality:
            return None

        return DistributionMirror(
            distribution=self, owner=owner, name=name, speed=speed,
            country=country, content=content, pulse_type=pulse_type,
            displayname=displayname, description=description,
            http_base_url=http_base_url, ftp_base_url=ftp_base_url,
            rsync_base_url=rsync_base_url, file_list=file_list,
            official_candidate=official_candidate, enabled=enabled,
            pulse_source=pulse_source)

    def createBug(self, owner, title, comment, security_related=False,
                  private=False):
        """See canonical.launchpad.interfaces.IBugTarget."""
        return BugSet().createBug(
            distribution=self, comment=comment, title=title, owner=owner,
            security_related=security_related, private=private)

    @property
    def open_cve_bugtasks(self):
        """See IDistribution."""
        open_bugtask_status_sql_values = "(%s)" % (
            ', '.join(sqlvalues(*UNRESOLVED_BUGTASK_STATUSES)))

        result = BugTask.select("""
            CVE.id = BugCve.cve AND
            BugCve.bug = Bug.id AND
            BugTask.bug = Bug.id AND
            BugTask.distribution=%d AND
            BugTask.status IN %s
            """ % (self.id, open_bugtask_status_sql_values),
            clauseTables=['Bug', 'Cve', 'BugCve'],
            orderBy=['-importance', 'datecreated'])

        return result

    @property
    def resolved_cve_bugtasks(self):
        """See IDistribution."""
        resolved_bugtask_status_sql_values = "(%s)" % (
            ', '.join(sqlvalues(*RESOLVED_BUGTASK_STATUSES)))

        result = BugTask.select("""
            CVE.id = BugCve.cve AND
            BugCve.bug = Bug.id AND
            BugTask.bug = Bug.id AND
            BugTask.distribution=%d AND
            BugTask.status IN %s
            """ % (self.id, resolved_bugtask_status_sql_values),
            clauseTables=['Bug', 'Cve', 'BugCve'],
            orderBy=['-importance', 'datecreated'])
        return result

    @property
    def currentrelease(self):
        # XXX: this should be just a selectFirst with a case in its
        # order by clause -- kiko, 2006-03-18

        # If we have a frozen one, return that.
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.FROZEN:
                return rel
        # If we have one in development, return that.
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.DEVELOPMENT:
                return rel
        # If we have a stable one, return that.
        for rel in self.releases:
            if rel.releasestatus == DistributionReleaseStatus.CURRENT:
                return rel
        # If we have ANY, return the first one.
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

        severities = [BugTaskStatus.NEW,
                      BugTaskStatus.ACCEPTED,
                      BugTaskStatus.REJECTED,
                      BugTaskStatus.FIXED]

        query = ("BugTask.distribution = %s AND "
                 "BugTask.bugstatus = %i")

        for severity in severities:
            query = query % (quote(self.id), severity)
            count = BugTask.select(query).count()
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

    def getMilestone(self, name):
        """See IDistribution."""
        return Milestone.selectOne("""
            distribution = %s AND
            name = %s
            """ % sqlvalues(self.id, name))

    def getSourcePackage(self, name):
        """See IDistribution."""
        if ISourcePackageName.providedBy(name):
            sourcepackagename = name
        else:
            try:
                sourcepackagename = SourcePackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return DistributionSourcePackage(self, sourcepackagename)

    def getSourcePackageRelease(self, sourcepackagerelease):
        """See IDistribution."""
        return DistributionSourcePackageRelease(self, sourcepackagerelease)

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None):
        """See IHasSpecifications.
        
        In the case of distributions, there are two kinds of filtering,
        based on:
        
          - completeness: we want to show INCOMPLETE if nothing is said
          - informationalness: we will show ANY if nothing is said
        
        """

        # eliminate mutables in the case where nothing or an empty filter
        # was sent
        if not filter:
            # it could be None or it could be []
            filter = [SpecificationFilter.INCOMPLETE]

        # now look at the filter and fill in the unsaid bits

        # defaults for completeness: if nothing is said about completeness
        # then we want to show INCOMPLETE
        completeness = False
        for option in [
            SpecificationFilter.COMPLETE,
            SpecificationFilter.INCOMPLETE]:
            if option in filter:
                completeness = True
        if completeness is False:
            filter.append(SpecificationFilter.INCOMPLETE)
        
        # defaults for acceptance: in this case we have nothing to do
        # because specs are not accepted/declined against a distro

        # defaults for informationalness: we don't have to do anything
        # because the default if nothing is said is ANY

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = ['-priority', 'Specification.status', 'Specification.name']
        elif sort == SpecificationSort.DATE:
            order = ['-Specification.datecreated', 'Specification.id']

        # figure out what set of specifications we are interested in. for
        # distributions, we need to be able to filter on the basis of:
        #
        #  - completeness. by default, only incomplete specs shown
        #  - informational.
        #
        base = 'Specification.distribution = %s' % self.id
        query = base
        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += ' AND Specification.informational IS TRUE'

        # filter based on completion. see the implementation of
        # Specification.is_complete() for more details
        completeness =  Specification.completeness_clause

        if SpecificationFilter.COMPLETE in filter:
            query += ' AND ( %s ) ' % completeness
        elif SpecificationFilter.INCOMPLETE in filter:
            query += ' AND NOT ( %s ) ' % completeness

        # ALL is the trump card
        if SpecificationFilter.ALL in filter:
            query = base

        # now do the query, and remember to prejoin to people
        results = Specification.select(query, orderBy=order, limit=quantity)
        return results.prejoin(['assignee', 'approver', 'drafter'])

    def getSpecification(self, name):
        """See ISpecificationTarget."""
        return Specification.selectOneBy(distributionID=self.id, name=name)

    def tickets(self, quantity=None):
        """See ITicketTarget."""
        return Ticket.select("""
            Ticket.distribution = %s
            """ % sqlvalues(self.id),
            orderBy='-Ticket.datecreated',
            prejoins=['distribution', 'owner', 'sourcepackagename'],
            limit=quantity)

    def newTicket(self, owner, title, description):
        """See ITicketTarget."""
        return TicketSet().new(
            title=title, description=description, owner=owner,
            distribution=self)

    def getTicket(self, ticket_num):
        """See ITicketTarget."""
        # First see if there is a ticket with that number.
        try:
            ticket = Ticket.get(ticket_num)
        except SQLObjectNotFound:
            return None
        # Now verify that that ticket is actually for this target.
        if ticket.target != self:
            return None
        return ticket

    def addSupportContact(self, person):
        """See ITicketTarget."""
        if person in self.support_contacts:
            return False
        SupportContact(
            product=None, person=person.id,
            sourcepackagename=None, distribution=self)
        return True

    def removeSupportContact(self, person):
        """See ITicketTarget."""
        if person not in self.support_contacts:
            return False
        support_contact_entry = SupportContact.selectOne(
            "distribution = %d AND person = %d"
            " AND sourcepackagename IS NULL" % (self.id, person.id))
        support_contact_entry.destroySelf()
        return True

    @property
    def support_contacts(self):
        """See ITicketTarget."""
        support_contacts = SupportContact.select(
            """distribution = %d AND sourcepackagename IS NULL""" % self.id)

        return shortlist([
            support_contact.person for support_contact in support_contacts
            ],
            longest_expected=100)

    def ensureRelatedBounty(self, bounty):
        """See IDistribution."""
        for curr_bounty in self.bounties:
            if bounty.id == curr_bounty.id:
                return None
        DistributionBounty(distribution=self, bounty=bounty)

    def getDistroReleaseAndPocket(self, distrorelease_name):
        """See IDistribution."""
        from canonical.archivepublisher.publishing import suffixpocket

        # Get the list of suffixes.
        suffixes = [suffix for suffix, ignored in suffixpocket.items()]
        # Sort it longest string first.
        suffixes.sort(key=len, reverse=True)

        for suffix in suffixes:
            if distrorelease_name.endswith(suffix):
                try:
                    left_size = len(distrorelease_name) - len(suffix)
                    return (self[distrorelease_name[:left_size]],
                            suffixpocket[suffix])
                except KeyError:
                    # Swallow KeyError to continue round the loop.
                    pass

        raise NotFoundError(distrorelease_name)

    def getFileByName(self, filename, source=True, binary=True):
        """See IDistribution."""
        assert (source or binary), "searching in an explicitly empty " \
               "space is pointless"
        if source:
            candidate = SourcePackageFilePublishing.selectFirstBy(
                distribution=self.id, libraryfilealiasfilename=filename,
                orderBy=['id'])

        if binary:
            candidate = BinaryPackageFilePublishing.selectFirstBy(
                distribution=self.id,
                libraryfilealiasfilename=filename,
                orderBy=["-id"])

        if candidate is not None:
            return candidate.libraryfilealias

        raise NotFoundError(filename)


    def getBuildRecords(self, status=None, name=None, pocket=None):
        """See IHasBuildRecords"""
        # Find out the distroarchreleases in question.
        arch_ids = []
        # concatenate architectures list since they are distinct.
        for release in self.releases:
            arch_ids += [arch.id for arch in release.architectures]

        # use facility provided by IBuildSet to retrieve the records
        return getUtility(IBuildSet).getBuildsByArchIds(
            arch_ids, status, name, pocket)

    def removeOldCacheItems(self):
        """See IDistribution."""

        # Get the set of source package names to deal with.
        spns = set(SourcePackageName.select("""
            SourcePackagePublishing.distrorelease =
                DistroRelease.id AND
            DistroRelease.distribution = %s AND
            SourcePackagePublishing.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
            """ % sqlvalues(self.id),
            distinct=True,
            clauseTables=['SourcePackagePublishing', 'DistroRelease',
                'SourcePackageRelease']))

        # Remove the cache entries for packages we no longer publish.
        for cache in self.source_package_caches:
            if cache.sourcepackagename not in spns:
                cache.destroySelf()

    def updateCompleteSourcePackageCache(self, ztm=None):
        """See IDistribution."""

        # Get the set of source package names to deal with.
        spns = list(SourcePackageName.select("""
            SourcePackagePublishing.distrorelease =
                DistroRelease.id AND
            DistroRelease.distribution = %s AND
            SourcePackagePublishing.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
            """ % sqlvalues(self.id),
            distinct=True,
            clauseTables=['SourcePackagePublishing', 'DistroRelease',
                'SourcePackageRelease']))

        # Now update, committing every 50 packages.
        counter = 0
        for spn in spns:
            self.updateSourcePackageCache(spn)
            counter += 1
            if counter > 49:
                counter = 0
                if ztm is not None:
                    ztm.commit()

    def updateSourcePackageCache(self, sourcepackagename):
        """See IDistribution."""

        # Get the set of published sourcepackage releases.
        sprs = list(SourcePackageRelease.select("""
            SourcePackageRelease.sourcepackagename = %s AND
            SourcePackageRelease.id =
                SourcePackagePublishing.sourcepackagerelease AND
            SourcePackagePublishing.distrorelease =
                DistroRelease.id AND
            DistroRelease.distribution = %s
            """ % sqlvalues(sourcepackagename.id, self.id),
            orderBy='id',
            clauseTables=['SourcePackagePublishing', 'DistroRelease'],
            distinct=True))
        if len(sprs) == 0:
            return

        # Find or create the cache entry.
        cache = DistributionSourcePackageCache.selectOne("""
            distribution = %s AND
            sourcepackagename = %s
            """ % sqlvalues(self.id, sourcepackagename.id))
        if cache is None:
            cache = DistributionSourcePackageCache(
                distribution=self,
                sourcepackagename=sourcepackagename)

        # Make sure the name is correct.
        cache.name = sourcepackagename.name

        # Get the sets of binary package names, summaries, descriptions.
        binpkgnames = set()
        binpkgsummaries = set()
        binpkgdescriptions = set()
        for spr in sprs:
            binpkgs = BinaryPackageRelease.select("""
                BinaryPackageRelease.build = Build.id AND
                Build.sourcepackagerelease = %s
                """ % sqlvalues(spr.id),
                clauseTables=['Build'])
            for binpkg in binpkgs:
                binpkgnames.add(binpkg.name)
                binpkgsummaries.add(binpkg.summary)
                binpkgdescriptions.add(binpkg.description)

        # Update the caches.
        cache.binpkgnames = ' '.join(sorted(binpkgnames))
        cache.binpkgsummaries = ' '.join(sorted(binpkgsummaries))
        cache.binpkgdescriptions = ' '.join(sorted(binpkgdescriptions))

    def searchSourcePackages(self, text):
        """See IDistribution."""
        # The query below tries exact matching on the source package
        # name as well; this is because source package names are
        # notoriously bad for fti matching -- they can contain dots, or
        # be short like "at", both things which users do search for.
        dspcaches = DistributionSourcePackageCache.select("""
            distribution = %s AND
            (fti @@ ftq(%s) OR
             DistributionSourcePackageCache.name ILIKE '%%' || %s || '%%')
            """ % (quote(self.id), quote(text), quote_like(text)),
            selectAlso='rank(fti, ftq(%s)) AS rank' % sqlvalues(text),
            orderBy=['-rank'],
            prejoins=["sourcepackagename"],
            distinct=True)
        return [dspc.distributionsourcepackage for dspc in dspcaches]

    def getPackageNames(self, pkgname):
        """See IDistribution"""
        # We should only ever get a pkgname as a string.
        assert isinstance(pkgname, str), "Only ever call this with a string"

        # Clean it up and make sure it's a valid package name.
        pkgname = pkgname.strip().lower()
        if not valid_name(pkgname):
            raise NotFoundError('Invalid package name: %s' % pkgname)

        if self.currentrelease is None:
            # This distribution has no releases; there can't be anything
            # published in it.
            raise NotFoundError('Distribution has no releases; %r was never '
                                'published in it' % pkgname)

        # First, we try assuming it's a binary package. let's try and find
        # a binarypackagename for it.
        binarypackagename = BinaryPackageName.selectOneBy(name=pkgname)
        if binarypackagename is None:
            # Is it a sourcepackagename?
            sourcepackagename = SourcePackageName.selectOneBy(name=pkgname)
            if sourcepackagename is None:
                # It's neither a sourcepackage, nor a binary package name.
                raise NotFoundError('Unknown package: %s' % pkgname)

            # It's definitely only a sourcepackagename. Let's make sure it
            # is published in the current distro release.
            publishing = SourcePackagePublishing.select('''
                SourcePackagePublishing.distrorelease = %s AND
                SourcePackagePublishing.sourcepackagerelease =
                    SourcePackageRelease.id AND
                SourcePackageRelease.sourcepackagename = %s
                ''' % sqlvalues(self.currentrelease.id, sourcepackagename.id),
                clauseTables=['SourcePackageRelease'], distinct=True)
            if publishing.count() == 0:
                # Yes, it's a sourcepackage, but we don't know about it in
                # this distro.
                raise NotFoundError('Unpublished source package: %s' % pkgname)
            return (sourcepackagename, None)

        # Ok, so we have a binarypackage with that name. let's see if it's
        # published, and what its sourcepackagename is.
        publishings = PublishedPackage.selectBy(
            binarypackagename=binarypackagename.name,
            distrorelease=self.currentrelease.id,
            orderBy=['id'])
        if publishings.count() == 0:
            # Ok, we have a binary package name, but it's not published in the
            # target distro release. let's see if it's published anywhere.
            publishings = PublishedPackage.selectBy(
                binarypackagename=binarypackagename.name,
                orderBy=['id'])
            if publishings.count() == 0:
                # There are no publishing records anywhere for this beast,
                # sadly.
                raise NotFoundError('Unpublished binary package: %s' % pkgname)

        # PublishedPackageView uses the actual text names.
        for p in publishings:
            sourcepackagenametxt = p.sourcepackagename
            break
        sourcepackagename = SourcePackageName.byName(sourcepackagenametxt)
        return (sourcepackagename, binarypackagename)


class DistributionSet:
    """This class is to deal with Distribution related stuff"""

    implements(IDistributionSet)

    def __init__(self):
        self.title = "Distributions registered in Launchpad"

    def __iter__(self):
        return iter(Distribution.select())

    def __getitem__(self, name):
        """See canonical.launchpad.interfaces.IDistributionSet."""
        distribution = self.getByName(name)
        if distribution is None:
            raise NotFoundError(name)
        return distribution

    def get(self, distributionid):
        """See canonical.launchpad.interfaces.IDistributionSet."""
        return Distribution.get(distributionid)

    def count(self):
        return Distribution.select().count()

    def getDistros(self):
        """Returns all Distributions available on the database"""
        return Distribution.select()

    def getByName(self, distroname):
        """See canonical.launchpad.interfaces.IDistributionSet."""
        try:
            return Distribution.byName(distroname)
        except SQLObjectNotFound:
            return None

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


