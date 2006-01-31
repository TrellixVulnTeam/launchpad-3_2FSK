# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Build', 'BuildSet']


from zope.interface import implements

# SQLObject/SQLBase
from sqlobject import (
    StringCol, ForeignKey, IntervalCol)
from sqlobject.sqlbuilder import AND, IN

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import (
    IBuild, IBuildSet)

from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.builder import BuildQueue

from canonical.lp.dbschema import EnumCol, BuildStatus

class Build(SQLBase):
    implements(IBuild)
    _table = 'Build'

    datecreated = UtcDateTimeCol(dbName='datecreated', default=UTC_NOW)
    processor = ForeignKey(dbName='processor', foreignKey='Processor',
        notNull=True)
    distroarchrelease = ForeignKey(dbName='distroarchrelease',
        foreignKey='DistroArchRelease', notNull=True)
    buildstate = EnumCol(dbName='buildstate', notNull=True, schema=BuildStatus)
    sourcepackagerelease = ForeignKey(dbName='sourcepackagerelease',
        foreignKey='SourcePackageRelease', notNull=True)
    datebuilt = UtcDateTimeCol(dbName='datebuilt', default=None)
    buildduration = IntervalCol(dbName='buildduration', default=None)
    buildlog = ForeignKey(dbName='buildlog', foreignKey='LibraryFileAlias',
        default=None)
    builder = ForeignKey(dbName='builder', foreignKey='Builder',
        default=None)
    gpgsigningkey = ForeignKey(dbName='gpgsigningkey', foreignKey='GPGKey',
        default=None)
    changes = StringCol(dbName='changes', default=None)

    @property
    def buildqueue_record(self):
        """See IBuild"""
        # XXX cprov 20051025
        # Would be nice if we can use fresh sqlobject feature 'singlejoin'
        # instead, see bug # 3424
        return BuildQueue.selectOneBy(buildID=self.id)

    @property
    def distrorelease(self):
        """See IBuild"""
        return self.distroarchrelease.distrorelease

    @property
    def distribution(self):
        """See IBuild"""
        return self.distroarchrelease.distrorelease.distribution

    @property
    def title(self):
        """See IBuild"""
        return '%s build of %s %s in %s %s' % (
            self.distroarchrelease.architecturetag,
            self.sourcepackagerelease.name,
            self.sourcepackagerelease.version,
            self.distroarchrelease.distrorelease.distribution.name,
            self.distroarchrelease.distrorelease.name)

    @property
    def was_built(self):
        """See IBuild"""
        return self.buildstate is not BuildStatus.NEEDSBUILD

    @property
    def build_icon(self):
        """See IBuild"""

        icon_map = {
            BuildStatus.NEEDSBUILD: "",
            BuildStatus.FULLYBUILT: "/++resource++build-success",
            BuildStatus.FAILEDTOBUILD: "/++resource++build-failure",
            BuildStatus.MANUALDEPWAIT: "",
            BuildStatus.CHROOTWAIT: "",
            }
        return icon_map[self.buildstate]

    @property
    def distributionsourcepackagerelease(self):
        """See IBuild."""
        from canonical.launchpad.database.distributionsourcepackagerelease \
             import (
            DistributionSourcePackageRelease)

        return DistributionSourcePackageRelease(
            distribution=self.distroarchrelease.distrorelease.distribution,
            sourcepackagerelease=self.sourcepackagerelease)

    @property
    def binarypackages(self):
        """See IBuild."""
        bpklist = BinaryPackageRelease.selectBy(buildID=self.id,
                                                orderBy=['id'])
        return sorted(bpklist, key=lambda a: a.binarypackagename.name)

    @property
    def can_be_reset(self):
        """See IBuild."""
        return self.buildstate in [BuildStatus.FAILEDTOBUILD,
                                   BuildStatus.MANUALDEPWAIT,
                                   BuildStatus.CHROOTWAIT]

    def reset(self):
        """See IBuild."""
        self.buildstate = BuildStatus.NEEDSBUILD
        self.datebuilt = None
        self.buildduration = None
        self.builder = None
        self.gpgsigningkey = None
        self.changes = None
        self.buildlog = None

    def __getitem__(self, name):
        return self.getBinaryPackageRelease(name)

    def getBinaryPackageRelease(self, name):
        """See IBuild."""
        for binpkg in self.binarypackages:
            if binpkg.name == name:
                return binpkg
        raise IndexError, 'No binary package "%s" in build' % name

    def createBinaryPackageRelease(self, binarypackagename, version,
                                   summary, description,
                                   binpackageformat, component,
                                   section, priority, shlibdeps,
                                   depends, recommends, suggests,
                                   conflicts, replaces, provides,
                                   essential, installedsize,
                                   copyright, licence,
                                   architecturespecific):
        """See IBuild."""
        return BinaryPackageRelease(buildID=self.id,
                                    binarypackagenameID=binarypackagename,
                                    version=version,
                                    summary=summary,
                                    description=description,
                                    binpackageformat=binpackageformat,
                                    componentID=component,
                                    sectionID=section,
                                    priority=priority,
                                    shlibdeps=shlibdeps,
                                    depends=depends,
                                    recommends=recommends,
                                    suggests=suggests,
                                    conflicts=conflicts,
                                    replaces=replaces,
                                    provides=provides,
                                    essential=essential,
                                    installedsize=installedsize,
                                    copyright=copyright,
                                    licence=licence,
                                    architecturespecific=architecturespecific)

    def createBuildQueueEntry(self):
        """See IBuild"""
        return BuildQueue(build=self.id)


class BuildSet:
    implements(IBuildSet)

    def getBuildBySRAndArchtag(self, sourcepackagereleaseID, archtag):
        """See IBuildSet"""
        clauseTables = ['DistroArchRelease']
        query = ('Build.sourcepackagerelease = %s '
                 'AND Build.distroarchrelease = DistroArchRelease.id '
                 'AND DistroArchRelease.architecturetag = %s'
                 % sqlvalues(sourcepackagereleaseID, archtag)
                 )

        return Build.select(query, clauseTables=clauseTables)

    def getByBuildID(self, id):
        """See IBuildSet."""
        return Build.get(id)

    def getPendingBuildsForArchSet(self, archreleases):
        """See IBuildSet."""
        archrelease_ids = [d.id for d in archreleases]

        return Build.select(
            AND(Build.q.buildstate==BuildStatus.NEEDSBUILD,
                IN(Build.q.distroarchreleaseID, archrelease_ids))
            )

    def getBuildsForBuilder(self, builder_id, status=None):
        """See IBuildSet."""
        status_clause = ''
        if status:
            status_clause = "AND buildstate=%s" % sqlvalues(status)

        return Build.select(
            "builder=%s %s" % (builder_id, status_clause),
            orderBy="-datebuilt")

    def getBuildsByArchIds(self, arch_ids, status=None):
        """See IBuildSet."""
        # If not distroarchrelease was found return None.
        if not arch_ids:
            return None

        # format clause according single/multiple architecture(s) form
        if len(arch_ids) == 1:
            condition_clauses = [('distroarchrelease=%s'
                                  % sqlvalues(arch_ids[0]))]
        else:
            condition_clauses = [('distroarchrelease IN %s'
                                  % sqlvalues(arch_ids))]

        # exclude gina-generated builds
        # buildstate == FULLYBUILT && datebuilt == null
        condition_clauses.append(
            "NOT (Build.buildstate = %s AND Build.datebuilt is NULL)"
            % sqlvalues(BuildStatus.FULLYBUILT))

        # attempt to given status
        if status is not None:
            condition_clauses.append('buildstate=%s' % sqlvalues(status))

        return Build.select(' AND '.join(condition_clauses),
                            orderBy="-datebuilt")
