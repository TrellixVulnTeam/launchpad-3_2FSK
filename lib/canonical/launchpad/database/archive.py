# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Database class for table Archive."""

__metaclass__ = type

__all__ = ['Archive', 'ArchiveSet']

import os
import re

from sqlobject import  (
    BoolCol, ForeignKey, IntCol, StringCol)
from sqlobject.sqlbuilder import SQLConstant
from zope.component import getUtility
from zope.interface import alsoProvides, implements

from canonical.archivepublisher.config import Config as PubConfig
from canonical.archiveuploader.utils import re_issource, re_isadeb
from canonical.config import config
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    cursor, quote, quote_like, sqlvalues, SQLBase)
from canonical.launchpad.database.archivedependency import (
    ArchiveDependency)
from canonical.launchpad.database.distributionsourcepackagecache import (
    DistributionSourcePackageCache)
from canonical.launchpad.database.distroseriespackagecache import (
    DistroSeriesPackageCache)
from canonical.launchpad.database.files import (
    BinaryPackageFile, SourcePackageReleaseFile)
from canonical.launchpad.database.librarian import (
    LibraryFileAlias, LibraryFileContent)
from canonical.launchpad.database.packagediff import PackageDiff
from canonical.launchpad.database.publishedpackage import PublishedPackage
from canonical.launchpad.database.publishing import (
    SourcePackagePublishingHistory, BinaryPackagePublishingHistory)
from canonical.launchpad.database.queue import (
    PackageUpload, PackageUploadSource)
from canonical.launchpad.interfaces.archive import (
    ArchiveDependencyError, ArchivePurpose, IArchive, IArchiveSet,
    IDistributionArchive, IPPA)
from canonical.launchpad.interfaces.archivepermission import (
    ArchivePermissionType, IArchivePermissionSet)
from canonical.launchpad.interfaces.build import (
    BuildStatus, IHasBuildRecords, IBuildSet)
from canonical.launchpad.interfaces.component import IComponentSet
from canonical.launchpad.interfaces.launchpad import (
    IHasOwner, ILaunchpadCelebrities, NotFoundError)
from canonical.launchpad.interfaces.package import PackageUploadStatus
from canonical.launchpad.interfaces.publishing import (
    PackagePublishingPocket, PackagePublishingStatus)
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)
from canonical.launchpad.webapp.url import urlappend
from canonical.launchpad.validators.name import valid_name
from canonical.launchpad.validators.person import validate_public_person


class Archive(SQLBase):
    implements(IArchive, IHasOwner, IHasBuildRecords)
    _table = 'Archive'
    _defaultOrder = 'id'

    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)

    def _validate_archive_name(self, attr, value):
        """Only allow renaming of COPY archives.

        Also assert the name is valid when set via an unproxied object.
        """
        if not self._SO_creating:
            assert self.purpose == ArchivePurpose.COPY, (
                "Only COPY archives can be renamed.")
        assert valid_name(value), "Invalid name given to unproxied object."
        return value

    name = StringCol(
        dbName='name', notNull=True, storm_validator=_validate_archive_name)

    description = StringCol(dbName='description', notNull=False, default=None)

    distribution = ForeignKey(
        foreignKey='Distribution', dbName='distribution', notNull=False)

    purpose = EnumCol(
        dbName='purpose', unique=False, notNull=True, schema=ArchivePurpose)

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

    total_count = IntCol(dbName='total_count', notNull=True, default=0)

    pending_count = IntCol(dbName='pending_count', notNull=True, default=0)

    succeeded_count = IntCol(
        dbName='succeeded_count', notNull=True, default=0)

    building_count = IntCol(
        dbName='building_count', notNull=True, default=0)

    failed_count = IntCol(dbName='failed_count', notNull=True, default=0)

    date_created = UtcDateTimeCol(dbName='date_created')

    signing_key = ForeignKey(
        foreignKey='GPGKey', dbName='signing_key', notNull=False)

    def _init(self, *args, **kw):
        """Provide the right interface for URL traversal."""
        SQLBase._init(self, *args, **kw)

        # Provide the additional marker interface depending on what type
        # of archive this is.  See also the browser:url declarations in
        # zcml/archive.zcml.
        if self.is_ppa:
            alsoProvides(self, IPPA)
        else:
            alsoProvides(self, IDistributionArchive)

    @property
    def is_ppa(self):
        """See `IArchive`."""
        return self.purpose == ArchivePurpose.PPA

    @property
    def title(self):
        """See `IArchive`."""
        if self.is_ppa:
            title = 'PPA for %s' % self.owner.displayname
            if self.private:
                title = "Private %s" % title
            return title
        return '%s for %s' % (self.purpose.title, self.distribution.title)

    @property
    def series_with_sources(self):
        """See `IArchive`."""
        cur = cursor()
        query = """SELECT DISTINCT distroseries FROM
                      SourcePackagePublishingHistory WHERE
                      SourcePackagePublishingHistory.archive = %s"""
        cur.execute(query % self.id)
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
    def expanded_archive_dependencies(self):
        """See `IArchive`."""
        archives = []
        if self.is_ppa:
            archives.append(self.distribution.main_archive)
        archives.append(self)
        archives.extend(
            [archive_dep.dependency for archive_dep in self.dependencies])
        return archives

    @property
    def archive_url(self):
        """See `IArchive`."""
        archive_postfixes = {
            ArchivePurpose.PRIMARY : '',
            ArchivePurpose.PARTNER : '-partner',
        }

        if self.is_ppa:
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
        elif self.is_ppa:
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
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
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

        preJoins = [
            'sourcepackagerelease.creator',
            'sourcepackagerelease.dscsigningkey',
            'distroseries',
            'section',
            ]

        sources = SourcePackagePublishingHistory.select(
            ' AND '.join(clauses), clauseTables=clauseTables, orderBy=orderBy,
            prejoins=preJoins)

        return sources

    def getSourcesForDeletion(self, name=None, status=None):
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

        source_deletable_states = (
            PackagePublishingStatus.PENDING,
            PackagePublishingStatus.PUBLISHED,
            )
        clauses.append("""
           (%s OR SourcePackagePublishingHistory.status IN %s)
        """ % (has_published_binaries_clause,
               quote(source_deletable_states)))

        if status is not None:
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
            clauses.append("""
                SourcePackagePublishingHistory.status IN %s
            """ % sqlvalues(status))

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
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result = store.find(
            (LibraryFileContent),
            SourcePackagePublishingHistory.archive == self.id,
            SourcePackagePublishingHistory.dateremoved == None,
            SourcePackagePublishingHistory.sourcepackagereleaseID ==
                SourcePackageReleaseFile.sourcepackagereleaseID,
            SourcePackageReleaseFile.libraryfileID == LibraryFileAlias.id,
            LibraryFileAlias.contentID == LibraryFileContent.id)

        # We need to select distinct `LibraryFileContent`s because that how
        # they end up published in the archive disk. Duplications may happen
        # because of the publishing records join, the same `LibraryFileAlias`
        # gets logically re-published in several locations and the fact that
        # the same `LibraryFileContent` can be shared by multiple
        # `LibraryFileAlias.` (librarian-gc).
        result = result.config(distinct=True)
        size = sum([lfc.filesize for lfc in result])
        return size

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
            desc_version_order = SQLConstant(order_const + " DESC")
            orderBy.insert(1, desc_version_order)

        if status is not None:
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
            clauses.append("""
                BinaryPackagePublishingHistory.status IN %s
            """ % sqlvalues(status))

        if distroarchseries is not None:
            try:
                distroarchseries = tuple(distroarchseries)
            except TypeError:
                distroarchseries = (distroarchseries,)
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
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result = store.find(
            (LibraryFileContent),
            BinaryPackagePublishingHistory.archive == self.id,
            BinaryPackagePublishingHistory.dateremoved == None,
            BinaryPackagePublishingHistory.binarypackagereleaseID ==
                BinaryPackageFile.binarypackagereleaseID,
            BinaryPackageFile.libraryfileID == LibraryFileAlias.id,
            LibraryFileAlias.contentID == LibraryFileContent.id)

        # See `IArchive.sources_size`.
        result = result.config(distinct=True)
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
        # Compiled regexp to remove puntication.
        clean_text = re.compile('(,|;|:|\.|\?|!)')

        # XXX cprov 20080402 bug=207969: The set() is only used because we
        # have a limitation in our FTI setup, it only indexes the first 2500
        # chars of the target columns. When such limitation
        # gets fixed we should probably change it to a normal list and
        # benefit of the FTI rank for ordering.
        cache_contents = set()
        def add_cache_content(content):
            """Sanitise and add contents to the cache."""
            content = clean_text.sub(' ', content)
            terms = [term.lower() for term in content.strip().split()]
            for term in terms:
                cache_contents.add(term)

        # Cache owner name and displayname.
        add_cache_content(self.owner.name)
        add_cache_content(self.owner.displayname)

        # Cache source package name and its binaries information, binary
        # names and summaries.
        sources_cached = DistributionSourcePackageCache.select(
            "archive = %s" % sqlvalues(self), prejoins=["distribution"])
        for cache in sources_cached:
            add_cache_content(cache.distribution.name)
            add_cache_content(cache.name)
            add_cache_content(cache.binpkgnames)
            add_cache_content(cache.binpkgsummaries)

        # Cache distroseries names with binaries.
        binaries_cached = DistroSeriesPackageCache.select(
            "archive = %s" % sqlvalues(self), prejoins=["distroseries"])
        for cache in binaries_cached:
            add_cache_content(cache.distroseries.name)

        # Collapse all relevant terms in 'package_description_cache' and
        # update the package counters.
        self.package_description_cache = " ".join(cache_contents)
        self.sources_cached = sources_cached.count()
        self.binaries_cached = binaries_cached.count()

    def findDepCandidateByName(self, distroarchseries, name):
        """See `IArchive`."""
        archives = [
            archive.id for archive in self.expanded_archive_dependencies]

        query = """
            binarypackagename = %s AND
            distroarchseries = %s AND
            archive IN %s AND
            packagepublishingstatus = %s
        """ % sqlvalues(name, distroarchseries, archives,
                        PackagePublishingStatus.PUBLISHED)

        return PublishedPackage.selectFirst(query, orderBy=['-id'])

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

    def addArchiveDependency(self, dependency, pocket, component=None):
        """See `IArchive`."""
        if dependency == self:
            raise ArchiveDependencyError(
                "An archive should not depend on itself.")

        a_dependency = self.getArchiveDependency(dependency)
        if a_dependency is not None:
            raise ArchiveDependencyError(
                "Only one dependency record per archive is supported.")

        if dependency.is_ppa:
            if pocket is not PackagePublishingPocket.RELEASE:
                raise ArchiveDependencyError(
                    "Non-primary archives only support the RELEASE pocket.")
            if (component is not None and
                component.id is not getUtility(IComponentSet)['main'].id):
                raise ArchiveDependencyError(
                    "Non-primary archives only support the 'main' component.")

        return ArchiveDependency(
            archive=self, dependency=dependency, pocket=pocket,
            component=component)

    def getPermissions(self, user, item, perm_type):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.checkAuthenticated(user, self, perm_type, item)

    def getPermissionsForPerson(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.permissionsForPerson(self, person)

    def getUploadersForPackage(self, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForPackage(self, source_package_name)

    def getUploadersForComponent(self, component_name=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForComponent(self, component_name)

    def getQueueAdminsForComponent(self, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.queueAdminsForComponent(self, component_name)

    def getComponentsForQueueAdmin(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.componentsForQueueAdmin(self, person)

    def canUpload(self, user, component_or_package=None):
        """See `IArchive`."""
        if self.is_ppa:
            return user.inTeam(self.owner)
        else:
            return self._authenticate(
                user, component_or_package, ArchivePermissionType.UPLOAD)

    def canAdministerQueue(self, user, component):
        """See `IArchive`."""
        return self._authenticate(
            user, component, ArchivePermissionType.QUEUE_ADMIN)

    def _authenticate(self, user, component, permission):
        """Private helper method to check permissions."""
        permissions = self.getPermissions(user, component, permission)
        return permissions.count() > 0

    def newPackageUploader(self, person, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newPackageUploader(
            self, person, source_package_name)

    def newComponentUploader(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newComponentUploader(
            self, person, component_name)

    def newQueueAdmin(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newQueueAdmin(self, person, component_name)

    def deletePackageUploader(self, person, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deletePackageUploader(
            self, person, source_package_name)

    def deleteComponentUploader(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deleteComponentUploader(
            self, person, component_name)

    def deleteQueueAdmin(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deleteQueueAdmin(self, person, component_name)

    def getFileByName(self, filename):
        """See `IArchive`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)

        base_clauses = (
            LibraryFileAlias.filename == filename,
            )

        if re_issource.match(filename):
            clauses = (
                SourcePackagePublishingHistory.archive == self.id,
                SourcePackagePublishingHistory.sourcepackagereleaseID ==
                    SourcePackageReleaseFile.sourcepackagereleaseID,
                SourcePackageReleaseFile.libraryfileID ==
                    LibraryFileAlias.id,
                )
        elif re_isadeb.match(filename):
            clauses = (
                BinaryPackagePublishingHistory.archive == self.id,
                BinaryPackagePublishingHistory.binarypackagereleaseID ==
                    BinaryPackageFile.binarypackagereleaseID,
                BinaryPackageFile.libraryfileID == LibraryFileAlias.id,
                )
        elif filename.endswith('_source.changes'):
            clauses = (
                SourcePackagePublishingHistory.archive == self.id,
                SourcePackagePublishingHistory.sourcepackagereleaseID ==
                    PackageUploadSource.sourcepackagereleaseID,
                PackageUploadSource.packageuploadID == PackageUpload.id,
                PackageUpload.status == PackageUploadStatus.DONE,
                PackageUpload.changesfileID == LibraryFileAlias.id,
                )
        else:
            raise NotFoundError(filename)

        def do_query():
            result = store.find((LibraryFileAlias), *(base_clauses + clauses))
            result = result.config(distinct=True)
            result.order_by(LibraryFileAlias.id)
            return result.first()

        archive_file = do_query()

        if archive_file is None:
            # If a diff.gz wasn't found in the source-files domain, try in
            # the PackageDiff domain.
            if filename.endswith('.diff.gz'):
                clauses = (
                    SourcePackagePublishingHistory.archive == self.id,
                    SourcePackagePublishingHistory.sourcepackagereleaseID ==
                        PackageDiff.to_sourceID,
                    PackageDiff.diff_contentID == LibraryFileAlias.id,
                    )
                package_diff_file = do_query()
                if package_diff_file is not None:
                    return package_diff_file

            raise NotFoundError(filename)

        return archive_file


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

    def _getDefaultArchiveNameByPurpose(self, purpose):
        """Return the default for a archive in a given purpose.

        The default names are:

         * PRIMARY: 'primary';
         * PARTNER: 'partner';
         * PPA: 'default'.

        :param purpose: queried `ArchivePurpose`.

        :raise: `AssertionError` If the given purpose is not in this list,
            i.e. doesn't have a default name.

        :return: the name text to be used as name.
        """
        name_by_purpose = {
            ArchivePurpose.PRIMARY: 'primary',
            ArchivePurpose.PPA: 'default',
            ArchivePurpose.PARTNER: 'partner',
            }

        if purpose not in name_by_purpose.keys():
            raise AssertionError(
                "'%s' purpose has no default name." % purpose.name)

        return name_by_purpose[purpose]

    def getByDistroPurpose(self, distribution, purpose, name=None):
        """See `IArchiveSet`."""
        if purpose == ArchivePurpose.PPA:
            raise AssertionError(
                "This method should not be used to lookup PPAs. "
                "Use 'getPPAByDistributionAndOwnerName' instead.")

        if name is None:
            name = self._getDefaultArchiveNameByPurpose(purpose)

        return Archive.selectOneBy(
            distribution=distribution, purpose=purpose, name=name)

    def getByDistroAndName(self, distribution, name):
        """See `IArchiveSet`."""
        return Archive.selectOne("""
            Archive.distribution = %s AND
            Archive.name = %s AND
            Archive.purpose != %s
            """ % sqlvalues(distribution, name, ArchivePurpose.PPA))

    def new(self, purpose, owner, name=None, distribution=None,
            description=None):
        """See `IArchiveSet`."""
        if distribution is None:
            distribution = getUtility(ILaunchpadCelebrities).ubuntu

        if name is None:
            name = self._getDefaultArchiveNameByPurpose(purpose)

        return Archive(
            owner=owner, distribution=distribution, name=name,
            description=description, purpose=purpose)

    def __iter__(self):
        """See `IArchiveSet`."""
        return iter(Archive.select())

    @property
    def number_of_ppa_sources(self):
        cur = cursor()
        query = """
             SELECT SUM(sources_cached) FROM Archive
             WHERE purpose = %s AND private = FALSE
        """ % sqlvalues(ArchivePurpose.PPA)
        cur.execute(query)
        size = cur.fetchall()[0][0]
        if size is None:
            return 0
        return int(size)

    @property
    def number_of_ppa_binaries(self):
        cur = cursor()
        query = """
             SELECT SUM(binaries_cached) FROM Archive
             WHERE purpose = %s AND private = FALSE
        """ % sqlvalues(ArchivePurpose.PPA)
        cur.execute(query)
        size = cur.fetchall()[0][0]
        if size is None:
            return 0
        return int(size)

    def getPPAsForUser(self, user):
        """See `IArchiveSet`."""
        query = """
            Archive.owner = Person.id AND
            TeamParticipation.team = Archive.owner AND
            TeamParticipation.person = %s AND
            Archive.purpose = %s
        """ % sqlvalues(user, ArchivePurpose.PPA)

        return Archive.select(
            query, clauseTables=['Person', 'TeamParticipation'],
            orderBy=['Person.displayname'])

    def getPPAsPendingSigningKey(self):
        """See `IArchiveSet`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        results = store.find(
            Archive,
            Archive.signing_key == None,
            Archive.purpose == ArchivePurpose.PPA,
            Archive.enabled == True)
        results.order_by(Archive.date_created)
        return results

    def getLatestPPASourcePublicationsForDistribution(self, distribution):
        """See `IArchiveSet`."""
        query = """
            SourcePackagePublishingHistory.archive = Archive.id AND
            SourcePackagePublishingHistory.distroseries =
                DistroSeries.id AND
            Archive.private = FALSE AND
            DistroSeries.distribution = %s AND
            Archive.purpose = %s
        """ % sqlvalues(distribution, ArchivePurpose.PPA)

        return SourcePackagePublishingHistory.select(
            query, limit=5, clauseTables=['Archive', 'DistroSeries'],
            orderBy=['-datecreated', '-id'])


    def getMostActivePPAsForDistribution(self, distribution):
        """See `IArchiveSet`."""
        cur = cursor()
        query = """
             SELECT a.id, count(*) as C
             FROM Archive a, SourcePackagePublishingHistory spph
             WHERE
                 spph.archive = a.id AND
                 a.private = FALSE AND
                 spph.datecreated >= now() - INTERVAL '1 week' AND
                 a.distribution = %s AND
                 a.purpose = %s
             GROUP BY a.id
             ORDER BY C DESC, a.id
             LIMIT 5
        """ % sqlvalues(distribution, ArchivePurpose.PPA)

        cur.execute(query)

        most_active = []
        for archive_id, number_of_uploads in cur.fetchall():
            archive = Archive.get(int(archive_id))
            the_dict = {'archive': archive, 'uploads': number_of_uploads}
            most_active.append(the_dict)

        return most_active

    def getBuildCountersForArchitecture(self, archive, distroarchseries):
        """See `IArchiveSet`."""
        cur = cursor()
        query = """
            SELECT buildstate, count(id) FROM Build
            WHERE archive = %s AND distroarchseries = %s
            GROUP BY buildstate ORDER BY buildstate;
        """ % sqlvalues(archive, distroarchseries)
        cur.execute(query)
        result = cur.fetchall()

        status_map = {
            'failed': (
                BuildStatus.CHROOTWAIT,
                BuildStatus.FAILEDTOBUILD,
                BuildStatus.FAILEDTOUPLOAD,
                BuildStatus.MANUALDEPWAIT,
                ),
            'pending': (
                BuildStatus.BUILDING,
                BuildStatus.NEEDSBUILD,
                ),
            'succeeded': (
                BuildStatus.FULLYBUILT,
                ),
            }

        status_and_counters = {}

        # Set 'total' counter
        status_and_counters['total'] = sum(
            [counter for status, counter in result])

        # Set each counter according 'status_map'
        for key, status in status_map.iteritems():
            status_and_counters[key] = 0
            for status_value, status_counter in result:
                status_values = [item.value for item in status]
                if status_value in status_values:
                    status_and_counters[key] += status_counter

        return status_and_counters
