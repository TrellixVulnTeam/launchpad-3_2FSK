# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Database class for table Archive."""

__metaclass__ = type

__all__ = ['Archive', 'ArchiveSet']

import os

from sqlobject import  (
    BoolCol, ForeignKey, IntCol, StringCol)
from sqlobject.sqlbuilder import SQLConstant
from zope.component import getUtility
from zope.interface import implements


from canonical.archivepublisher.config import Config as PubConfig
from canonical.config import config
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    cursor, quote, quote_like, sqlvalues, SQLBase)
from canonical.launchpad.database.archivedependency import (
    ArchiveDependency)
from canonical.launchpad.database.distributionsourcepackagecache import (
    DistributionSourcePackageCache)
from canonical.launchpad.database.distroseriespackagecache import (
    DistroSeriesPackageCache)
from canonical.launchpad.database.librarian import LibraryFileContent
from canonical.launchpad.database.publishing import (
    SourcePackagePublishingHistory, BinaryPackagePublishingHistory)
from canonical.launchpad.interfaces import (
    ArchiveDependencyError, ArchivePurpose, IArchive, IArchiveSet,
    IHasOwner, IHasBuildRecords, IBuildSet, ILaunchpadCelebrities,
    PackagePublishingStatus)
from canonical.launchpad.webapp.url import urlappend
from canonical.launchpad.validators.person import public_person_validator


class Archive(SQLBase):
    implements(IArchive, IHasOwner, IHasBuildRecords)
    _table = 'Archive'
    _defaultOrder = 'id'

    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        validator=public_person_validator, notNull=False)

    description = StringCol(dbName='description', notNull=False, default=None)

    distribution = ForeignKey(
        foreignKey='Distribution', dbName='distribution', notNull=False)

    purpose = EnumCol(dbName='purpose', unique=False, notNull=True,
        schema=ArchivePurpose)

    enabled = BoolCol(dbName='enabled', notNull=True, default=True)

    private = BoolCol(dbName='private', notNull=True, default=False)

    require_virtualized = BoolCol(
        dbName='require_virtualized', notNull=True, default=True)

    authorized_size = IntCol(
        dbName='authorized_size', notNull=False, default=1024)

    whiteboard = StringCol(dbName='whiteboard', notNull=False, default=None)

    sources_cached = IntCol(
        dbName='sources_cached', notNull=False, default=0)

    binaries_cached = IntCol(
        dbName='binaries_cached', notNull=False, default=0)

    package_description_cache = StringCol(
        dbName='package_description_cache', notNull=False, default=None)

    buildd_secret = StringCol(dbName='buildd_secret', default=None)

    @property
    def title(self):
        """See `IArchive`."""
        if self.purpose == ArchivePurpose.PPA:
            title = 'PPA for %s' % self.owner.displayname
            if self.private:
                title = "Private %s" % title
            return title
        return '%s for %s' % (self.purpose.title, self.distribution.title)

    @property
    def series_with_sources(self):
        """See `IArchive`."""
        cur = cursor()
        q = """SELECT DISTINCT distroseries FROM
                      SourcePackagePublishingHistory WHERE
                      SourcePackagePublishingHistory.archive = %s"""
        cur.execute(q % self.id)
        published_series_ids = [int(row[0]) for row in cur.fetchall()]
        return [s for s in self.distribution.serieses if s.id in
                published_series_ids]

    @property
    def dependencies(self):
        query = """
            ArchiveDependency.dependency = Archive.id AND
            Archive.owner = Person.id AND
            ArchiveDependency.archive = %s
        """ % sqlvalues(self)
        clauseTables = ["Archive", "Person"]
        orderBy = ['Person.displayname']
        dependencies = ArchiveDependency.select(
            query, clauseTables=clauseTables, orderBy=orderBy)
        return dependencies

    @property
    def archive_url(self):
        """See `IArchive`."""
        archive_postfixes = {
            ArchivePurpose.PRIMARY : '',
            ArchivePurpose.PARTNER : '-partner',
        }

        if self.purpose == ArchivePurpose.PPA:
            if self.private:
                url = config.personalpackagearchive.private_base_url
            else:
                url = config.personalpackagearchive.base_url
            return urlappend(
                url, self.owner.name + '/' + self.distribution.name)

        try:
            postfix = archive_postfixes[self.purpose]
        except KeyError:
            raise AssertionError("archive_url unknown for purpose: %s" %
                self.purpose)
        return urlappend(config.archivepublisher.base_url,
            self.distribution.name + postfix)

    def getPubConfig(self):
        """See `IArchive`."""
        pubconf = PubConfig(self.distribution)
        ppa_config = config.personalpackagearchive

        if self.purpose == ArchivePurpose.PRIMARY:
            pass
        elif self.purpose == ArchivePurpose.PPA:
            if self.private:
                pubconf.distroroot = ppa_config.private_root
            else:
                pubconf.distroroot = ppa_config.root
            pubconf.archiveroot = os.path.join(
                pubconf.distroroot, self.owner.name, self.distribution.name)
            pubconf.poolroot = os.path.join(pubconf.archiveroot, 'pool')
            pubconf.distsroot = os.path.join(pubconf.archiveroot, 'dists')
            pubconf.overrideroot = None
            pubconf.cacheroot = None
            pubconf.miscroot = None
        elif self.purpose == ArchivePurpose.PARTNER:
            # Reset the list of components to partner only.  This prevents
            # any publisher runs from generating components not related to
            # the partner archive.
            for distroseries in pubconf._distroserieses.keys():
                pubconf._distroserieses[
                    distroseries]['components'] = ['partner']

            pubconf.distroroot = config.archivepublisher.root
            pubconf.archiveroot = os.path.join(pubconf.distroroot,
                self.distribution.name + '-partner')
            pubconf.poolroot = os.path.join(pubconf.archiveroot, 'pool')
            pubconf.distsroot = os.path.join(pubconf.archiveroot, 'dists')
            pubconf.overrideroot = os.path.join(
                pubconf.archiveroot, 'overrides')
            pubconf.cacheroot = os.path.join(pubconf.archiveroot, 'cache')
            pubconf.miscroot = os.path.join(pubconf.archiveroot, 'misc')
        else:
            raise AssertionError(
                "Unknown archive purpose %s when getting publisher config.",
                self.purpose)

        return pubconf

    def getBuildRecords(self, build_state=None, name=None, pocket=None,
                        user=None):
        """See IHasBuildRecords"""
        # Ignore "user", since anyone already accessing this archive
        # will implicitly have permission to see it.
        return getUtility(IBuildSet).getBuildsForArchive(
            self, build_state, name, pocket)

    def getPublishedSources(self, name=None, version=None, status=None,
                            distroseries=None, pocket=None,
                            exact_match=False):
        """See `IArchive`."""
        clauses = ["""
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
            """ % sqlvalues(self)]
        clauseTables = ['SourcePackageRelease', 'SourcePackageName']
        orderBy = ['SourcePackageName.name',
                   '-SourcePackagePublishingHistory.id']

        if name is not None:
            if exact_match:
                clauses.append("""
                    SourcePackageName.name=%s
                """ % sqlvalues(name))
            else:
                clauses.append("""
                    SourcePackageName.name LIKE '%%' || %s || '%%'
                """ % quote_like(name))

        if version is not None:
            assert name is not None, (
                "'version' can be only used when name is set")
            clauses.append("""
                SourcePackageRelease.version = %s
            """ % sqlvalues(version))
        else:
            order_const = "debversion_sort_key(SourcePackageRelease.version)"
            desc_version_order = SQLConstant(order_const+" DESC")
            orderBy.insert(1, desc_version_order)

        if status is not None:
            if not isinstance(status, list):
                status = [status]
            clauses.append("""
                SourcePackagePublishingHistory.status IN %s
            """ % sqlvalues(status))

        if distroseries is not None:
            clauses.append("""
                SourcePackagePublishingHistory.distroseries = %s
            """ % sqlvalues(distroseries))

        if pocket is not None:
            clauses.append("""
                SourcePackagePublishingHistory.pocket = %s
            """ % sqlvalues(pocket))

        preJoins = ['sourcepackagerelease']

        sources = SourcePackagePublishingHistory.select(
            ' AND '.join(clauses), clauseTables=clauseTables, orderBy=orderBy,
            prejoins=preJoins)

        return sources

    def getSourcesForDeletion(self, name=None):
        """See `IArchive`."""
        clauses = ["""
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
        """ % sqlvalues(self)]

        has_published_binaries_clause = """
            EXISTS (SELECT TRUE FROM
                BinaryPackagePublishingHistory bpph,
                BinaryPackageRelease bpr, Build
            WHERE
                bpph.archive = %s AND
                bpph.status = %s AND
                bpph.binarypackagerelease = bpr.id AND
                bpr.build = Build.id AND
                Build.sourcepackagerelease = SourcePackageRelease.id)
        """ % sqlvalues(self, PackagePublishingStatus.PUBLISHED)

        clauses.append("""
           (%s OR SourcePackagePublishingHistory.status = %s)
        """ % (has_published_binaries_clause,
               quote(PackagePublishingStatus.PUBLISHED)))


        clauseTables = ['SourcePackageRelease', 'SourcePackageName']

        order_const = "debversion_sort_key(SourcePackageRelease.version)"
        desc_version_order = SQLConstant(order_const+" DESC")
        orderBy = ['SourcePackageName.name', desc_version_order,
                   '-SourcePackagePublishingHistory.id']

        if name is not None:
            clauses.append("""
                    SourcePackageName.name LIKE '%%' || %s || '%%'
                """ % quote_like(name))

        preJoins = ['sourcepackagerelease']
        sources = SourcePackagePublishingHistory.select(
            ' AND '.join(clauses), clauseTables=clauseTables, orderBy=orderBy,
            prejoins=preJoins)

        return sources

    @property
    def number_of_sources(self):
        """See `IArchive`."""
        return self.getPublishedSources(
            status=PackagePublishingStatus.PUBLISHED).count()

    @property
    def sources_size(self):
        """See `IArchive`."""
        cur = cursor()
        query = """
            SELECT SUM(filesize) FROM LibraryFileContent WHERE id IN (
               SELECT DISTINCT(lfc.id) FROM
                   LibraryFileContent lfc, LibraryFileAlias lfa,
                   SourcePackageFilePublishing spfp
               WHERE
                   lfc.id=lfa.content AND
                   lfa.id=spfp.libraryfilealias AND
                   spfp.archive=%s);
        """ % sqlvalues(self)
        cur.execute(query)
        size = cur.fetchall()[0][0]
        if size is None:
            return 0
        return int(size)

    def _getBinaryPublishingBaseClauses (
        self, name=None, version=None, status=None, distroarchseries=None,
        pocket=None, exact_match=False):
        """Base clauses and clauseTables for binary publishing queries.

        Returns a list of 'clauses' (to be joined in the callsite) and
        a list of clauseTables required according the given arguments.
        """
        clauses = ["""
            BinaryPackagePublishingHistory.archive = %s AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id
        """ % sqlvalues(self)]
        clauseTables = ['BinaryPackageRelease', 'BinaryPackageName']
        orderBy = ['BinaryPackageName.name',
                   '-BinaryPackagePublishingHistory.id']

        if name is not None:
            if exact_match:
                clauses.append("""
                    BinaryPackageName.name=%s
                """ % sqlvalues(name))
            else:
                clauses.append("""
                    BinaryPackageName.name LIKE '%%' || %s || '%%'
                """ % quote_like(name))

        if version is not None:
            assert name is not None, (
                "'version' can be only used when name is set")
            clauses.append("""
                BinaryPackageRelease.version = %s
            """ % sqlvalues(version))
        else:
            order_const = "debversion_sort_key(BinaryPackageRelease.version)"
            desc_version_order = SQLConstant(order_const+" DESC")
            orderBy.insert(1, desc_version_order)

        if status is not None:
            if not isinstance(status, list):
                status = [status]
            clauses.append("""
                BinaryPackagePublishingHistory.status IN %s
            """ % sqlvalues(status))

        if distroarchseries is not None:
            if not isinstance(distroarchseries, list):
                distroarchseries = [distroarchseries]
            # XXX cprov 20071016: there is no sqlrepr for DistroArchSeries
            # uhmm, how so ?
            das_ids = "(%s)" % ", ".join(str(d.id) for d in distroarchseries)
            clauses.append("""
                BinaryPackagePublishingHistory.distroarchseries IN %s
            """ % das_ids)

        if pocket is not None:
            clauses.append("""
                BinaryPackagePublishingHistory.pocket = %s
            """ % sqlvalues(pocket))

        return clauses, clauseTables, orderBy

    def getAllPublishedBinaries(self, name=None, version=None, status=None,
                                distroarchseries=None, pocket=None,
                                exact_match=False):
        """See `IArchive`."""
        clauses, clauseTables, orderBy = self._getBinaryPublishingBaseClauses(
            name=name, version=version, status=status, pocket=pocket,
            distroarchseries=distroarchseries, exact_match=exact_match)

        all_binaries = BinaryPackagePublishingHistory.select(
            ' AND '.join(clauses) , clauseTables=clauseTables,
            orderBy=orderBy)

        return all_binaries

    def getPublishedOnDiskBinaries(self, name=None, version=None, status=None,
                                   distroarchseries=None, pocket=None,
                                   exact_match=False):
        """See `IArchive`."""
        clauses, clauseTables, orderBy = self._getBinaryPublishingBaseClauses(
            name=name, version=version, status=status, pocket=pocket,
            distroarchseries=distroarchseries, exact_match=exact_match)

        clauses.append("""
            BinaryPackagePublishingHistory.distroarchseries =
                DistroArchSeries.id AND
            DistroArchSeries.distroseries = DistroSeries.id
        """)
        clauseTables.extend(['DistroSeries', 'DistroArchSeries'])

        # Retrieve only the binaries published for the 'nominated architecture
        # independent' (usually i386) in the distroseries in question.
        # It includes all architecture-independent binaries only once and the
        # architecture-specific built for 'nominatedarchindep'.
        nominated_arch_independent_clause = ["""
            DistroSeries.nominatedarchindep =
                BinaryPackagePublishingHistory.distroarchseries
        """]
        nominated_arch_independent_query = ' AND '.join(
            clauses + nominated_arch_independent_clause)
        nominated_arch_independents = BinaryPackagePublishingHistory.select(
            nominated_arch_independent_query, clauseTables=clauseTables)

        # Retrieve all architecture-specific binary publications except
        # 'nominatedarchindep' (already included in the previous query).
        no_nominated_arch_independent_clause = ["""
            DistroSeries.nominatedarchindep !=
                BinaryPackagePublishingHistory.distroarchseries AND
            BinaryPackageRelease.architecturespecific = true
        """]
        no_nominated_arch_independent_query = ' AND '.join(
            clauses + no_nominated_arch_independent_clause)
        no_nominated_arch_independents = (
            BinaryPackagePublishingHistory.select(
            no_nominated_arch_independent_query, clauseTables=clauseTables))

        # XXX cprov 20071016: It's not possible to use the same ordering
        # schema returned by self._getBinaryPublishingBaseClauses.
        # It results in:
        # ERROR:  missing FROM-clause entry for table "binarypackagename"
        unique_binary_publications = nominated_arch_independents.union(
            no_nominated_arch_independents)

        return unique_binary_publications

    @property
    def number_of_binaries(self):
        """See `IArchive`."""
        return self.getPublishedOnDiskBinaries(
            status=PackagePublishingStatus.PUBLISHED).count()

    @property
    def binaries_size(self):
        """See `IArchive`."""
        query = """
             LibraryFileContent.id=LibraryFileAlias.content AND
             LibraryFileAlias.id=
                 BinaryPackageFilePublishing.libraryfilealias AND
             BinaryPackageFilePublishing.archive=%s
        """ % sqlvalues(self)

        clauseTables = ['LibraryFileAlias', 'BinaryPackageFilePublishing']
        # We are careful to use DISTINCT here to eliminate files that
        # are published in more than one place.
        result = LibraryFileContent.select(query, clauseTables=clauseTables,
            distinct=True)

        # XXX 2008-01-16 Julian.  Unfortunately SQLObject has got a bug
        # where it ignores DISTINCT on a .sum() operation, so resort to
        # Python addition.  Revert to using result.sum('filesize') when
        # SQLObject gets dropped.
        size = sum([lfc.filesize for lfc in result])
        return size

    @property
    def estimated_size(self):
        """See `IArchive`."""
        size = self.sources_size + self.binaries_size
        # 'cruft' represents the increase in the size of the archive
        # indexes related to each publication. We assume it is around 1K
        # but that's over-estimated.
        cruft = (self.number_of_sources + self.number_of_binaries) * 1024
        return size + cruft

    def allowUpdatesToReleasePocket(self):
        """See `IArchive`."""
        purposeToPermissionMap = {
            ArchivePurpose.PARTNER : True,
            ArchivePurpose.PPA : True,
            ArchivePurpose.PRIMARY : False,
        }

        try:
            permission = purposeToPermissionMap[self.purpose]
        except KeyError:
            # Future proofing for when new archive types are added.
            permission = False

        return permission

    def updateArchiveCache(self):
        """See `IArchive`."""
        cache_contents = set()

        cache_contents.add(self.owner.name)
        cache_contents.add(self.owner.displayname)

        sources_cached = DistributionSourcePackageCache.selectBy(
            archive=self)

        for cache in sources_cached:
            cache_contents.add(cache.name)
            cache_contents.add(cache.binpkgnames)
            cache_contents.add(cache.binpkgsummaries)

        binaries_cached = DistroSeriesPackageCache.selectBy(
            archive=self)

        self.package_description_cache = " ".join(cache_contents)
        self.sources_cached = sources_cached.count()
        self.binaries_cached = binaries_cached.count()

    def getArchiveDependency(self, dependency):
        """See `IArchive`."""
        return ArchiveDependency.selectOneBy(
            archive=self, dependency=dependency)

    def removeArchiveDependency(self, dependency):
        """See `IArchive`."""
        dependency = self.getArchiveDependency(dependency)
        if dependency is None:
            raise AssertionError("This dependency does not exist.")
        dependency.destroySelf()

    def addArchiveDependency(self, dependency):
        """See `IArchive`."""
        if dependency == self:
            raise ArchiveDependencyError(
                "An archive should not depend on itself.")

        if dependency.purpose != ArchivePurpose.PPA:
            raise ArchiveDependencyError(
                "Archive dependencies only applies to PPAs.")

        if self.getArchiveDependency(dependency):
            raise ArchiveDependencyError(
                "This dependency is already recorded.")

        return ArchiveDependency(archive=self, dependency=dependency)


class ArchiveSet:
    implements(IArchiveSet)
    title = "Archives registered in Launchpad"

    def get(self, archive_id):
        """See `IArchiveSet`."""
        return Archive.get(archive_id)

    def getPPAByDistributionAndOwnerName(self, distribution, name):
        """See `IArchiveSet`"""
        query = """
            Archive.purpose = %s AND
            Archive.distribution = %s AND
            Person.id = Archive.owner AND
            Person.name = %s
        """ % sqlvalues(ArchivePurpose.PPA, distribution, name)

        return Archive.selectOne(query, clauseTables=['Person'])

    def getByDistroPurpose(self, distribution, purpose):
        """See `IArchiveSet`."""
        return Archive.selectOneBy(distribution=distribution, purpose=purpose)

    def new(self, distribution=None, purpose=None, owner=None,
            description=None):
        """See `IArchiveSet`."""
        if purpose == ArchivePurpose.PPA:
            assert owner, "Owner required when purpose is PPA."

        if distribution is None:
            distribution = getUtility(ILaunchpadCelebrities).ubuntu

        return Archive(owner=owner, distribution=distribution,
                       description=description, purpose=purpose)

    def ensure(self, owner, distribution, purpose, description=None):
        """See `IArchiveSet`."""
        if owner is not None:
            archive = owner.archive
            if archive is None:
                archive = self.new(distribution=distribution, purpose=purpose,
                                   owner=owner, description=description)
        else:
            archive = self.getByDistroPurpose(distribution, purpose)
            if archive is None:
                archive = self.new(distribution, purpose)
        return archive

    def __iter__(self):
        """See `IArchiveSet`."""
        return iter(Archive.select())
