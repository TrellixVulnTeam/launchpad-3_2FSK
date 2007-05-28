# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BinaryPackageRelease', 'BinaryPackageReleaseSet']


from zope.interface import implements

from sqlobject import StringCol, ForeignKey, IntCol, SQLMultipleJoin, BoolCol

from canonical.database.sqlbase import SQLBase, quote, sqlvalues, quote_like

from canonical.launchpad.interfaces import (
    IBinaryPackageRelease, IBinaryPackageReleaseSet)

from canonical.database.enumcol import EnumCol
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.lp import dbschema

from canonical.launchpad.database.publishing import (
    SecureBinaryPackagePublishingHistory)
from canonical.launchpad.database.files import BinaryPackageFile
from canonical.launchpad.helpers import shortlist



class BinaryPackageRelease(SQLBase):
    implements(IBinaryPackageRelease)
    _table = 'BinaryPackageRelease'
    binarypackagename = ForeignKey(dbName='binarypackagename', notNull=True,
                                   foreignKey='BinaryPackageName')
    version = StringCol(dbName='version', notNull=True)
    summary = StringCol(dbName='summary', notNull=True, default="")
    description = StringCol(dbName='description', notNull=True)
    build = ForeignKey(dbName='build', foreignKey='Build', notNull=True)
    binpackageformat = EnumCol(dbName='binpackageformat', notNull=True,
                               schema=dbschema.BinaryPackageFormat)
    component = ForeignKey(dbName='component', foreignKey='Component',
                           notNull=True)
    section = ForeignKey(dbName='section', foreignKey='Section', notNull=True)
    priority = EnumCol(dbName='priority', notNull=True,
                       schema=dbschema.PackagePublishingPriority)
    shlibdeps = StringCol(dbName='shlibdeps')
    depends = StringCol(dbName='depends')
    recommends = StringCol(dbName='recommends')
    suggests = StringCol(dbName='suggests')
    conflicts = StringCol(dbName='conflicts')
    replaces = StringCol(dbName='replaces')
    provides = StringCol(dbName='provides')
    essential = BoolCol(dbName='essential', default=False)
    installedsize = IntCol(dbName='installedsize')
    copyright = StringCol(dbName='copyright')
    licence = StringCol(dbName='licence')
    architecturespecific = BoolCol(dbName='architecturespecific',
                                   notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    files = SQLMultipleJoin('BinaryPackageFile',
        joinColumn='binarypackagerelease')

    @property
    def title(self):
        """See IBinaryPackageRelease."""
        return '%s-%s' % (self.binarypackagename.name, self.version)

    @property
    def name(self):
        """See IBinaryPackageRelease."""
        return self.binarypackagename.name

    @property
    def distributionsourcepackagerelease(self):
        """See IBinaryPackageRelease."""
        # import here to avoid circular import problems
        from canonical.launchpad.database.distributionsourcepackagerelease \
            import DistributionSourcePackageRelease
        return DistributionSourcePackageRelease(
            distribution=self.build.distribution,
            sourcepackagerelease=self.build.sourcepackagerelease)

    @property
    def sourcepackagename(self):
        """See IBinaryPackageRelease."""
        return self.build.sourcepackagerelease.sourcepackagename.name

    def lastversions(self):
        """Return the SUPERSEDED BinaryPackageReleases in a DistroSeries.

        The distroseries information comes from the SourcepackageRelease
        and the publishing system.
        """
        # XXX malcc 2006-10-03: This is crack, each DistroSeries does
        # *not* compile all of its Packages. The callsite for this method
        # (binarypackagerelease-portlet-latestversions) needs reviewing,
        # to determine what it actually wants to fetch. For now, I'm just
        # modifying this to be archive-aware, which will keep the current
        # crackful behaviour.
        
        # Daniel Debonzi: To get the lastest versions of a BinaryPackage
        # Im suposing that one BinaryPackage is build for only one
        # DistroSeries (Each DistroSeries compile all its Packages). 
        # (BinaryPackage.build.distroarchseries = \
        # PackagePublishing.distroarchseries
        # where PackagePublishing.binarypackage = BinaryPackage.id)
        # When it is not true anymore, probably it should
        # be retrieved in a view class where I can use informations from
        # the launchbag.

        clauseTables = ['BinaryPackagePublishingHistory', 'BinaryPackageName']
        query = """
        BinaryPackagePublishingHistory.binarypackagerelease =
            BinaryPackageRelease.id AND
        BinaryPackageRelease.binarypackagename =
            BinaryPackageName.id AND
        BinaryPackageName.id = %s AND
        BinaryPackagePublishingHistory.distroarchrelease = %s AND
        BinaryPackagePublishingHistory.archive = %s AND
        BinaryPackagePublishingHistory.status = %s
        """ % sqlvalues(self.binarypackagename,
                        self.build.distroarchseries,
                        self.build.distroarchseries.main_archive,
                        dbschema.PackagePublishingStatus.SUPERSEDED)

        return shortlist(BinaryPackageRelease.select(
            query, clauseTables=clauseTables, distinct=True))

    def addFile(self, file):
        """See IBinaryPackageRelease."""
        determined_filetype = None
        if file.filename.endswith(".deb"):
            determined_filetype = dbschema.BinaryPackageFileType.DEB
        elif file.filename.endswith(".rpm"):
            determined_filetype = dbschema.BinaryPackageFileType.RPM
        elif file.filename.endswith(".udeb"):
            determined_filetype = dbschema.BinaryPackageFileType.UDEB

        return BinaryPackageFile(binarypackagerelease=self,
                                 filetype=determined_filetype,
                                 libraryfile=file)

    def publish(self, priority, status, pocket, embargo,
                distroarchseries=None):
        """See IBinaryPackageRelease."""
        # XXX: completely untested code
        if not distroarchseries:
            distroarchseries = self.build.distroarchseries

        return SecureBinaryPackagePublishingHistory(
            binarypackagerelease=self,
            distroarchseries=distroarchseries,
            component=self.build.sourcepackagerelease.component,
            section=self.build.sourcepackagerelease.section,
            priority=priority,
            status=status,
            pocket=pocket,
            embargo=embargo,
            archive=distroarchseries.main_archive
            )

    def override(self, component=None, section=None, priority=None):
        """See IBinaryPackageRelease."""
        if component is not None:
            self.component = component
        if section is not None:
            self.section = section
        if priority is not None:
            self.priority = priority


class BinaryPackageReleaseSet:
    """A Set of BinaryPackageReleases."""
    implements(IBinaryPackageReleaseSet)

    def findByNameInDistroSeries(self, distroseries, pattern, archtag=None,
                                  fti=False):
        """Returns a set of binarypackagereleases that matchs pattern inside a
        distroseries.
        """
        pattern = pattern.replace('%', '%%')
        query, clauseTables = self._buildBaseQuery(distroseries)
        queries = [query]

        match_query = ("BinaryPackageName.name LIKE lower('%%' || %s || '%%')"
                       % (quote_like(pattern)))
        if fti:
            match_query = ("(%s OR BinaryPackageRelease.fti @@ ftq(%s))"
                           % (match_query, quote(pattern)))
        queries.append(match_query)

        if archtag:
            queries.append('DistroArchRelease.architecturetag=%s'
                           % sqlvalues(archtag))

        query = " AND ".join(queries)

        return BinaryPackageRelease.select(query, clauseTables=clauseTables,
                                           orderBy='BinaryPackageName.name')

    def getByNameInDistroSeries(self, distroseries, name=None,
                                 version=None, archtag=None, orderBy=None):
        """Get a BinaryPackageRelease in a DistroSeries by its name."""
        query, clauseTables = self._buildBaseQuery(distroseries)
        queries = [query]

        if name:
            queries.append('BinaryPackageName.name = %s'% sqlvalues(name))

        # Look for a specific binarypackage version or if version == None
        # return the current one
        if version:
            queries.append('BinaryPackageRelease.version = %s'
                         % sqlvalues(version))
        else:
            status_published = dbschema.PackagePublishingStatus.PUBLISHED
            queries.append('BinaryPackagePublishingHistory.status = %s'
                         % sqlvalues(status_published))

        if archtag:
            queries.append('DistroArchRelease.architecturetag = %s'
                         % sqlvalues(archtag))

        query = " AND ".join(queries)
        return BinaryPackageRelease.select(query, distinct=True,
                                           clauseTables=clauseTables,
                                           orderBy=orderBy)

    def _buildBaseQuery(self, distroseries):
        query = """
        BinaryPackagePublishingHistory.binarypackagerelease =
           BinaryPackageRelease.id AND
        BinaryPackagePublishingHistory.distroarchrelease =
           DistroArchRelease.id AND
        BinaryPackagePublishingHistory.archive = %s AND
        DistroArchRelease.distrorelease = %s AND
        BinaryPackageRelease.binarypackagename =
           BinaryPackageName.id AND
        BinaryPackagePublishingHistory.status != %s
        """ % sqlvalues(distroseries.main_archive, distroseries,
                        dbschema.PackagePublishingStatus.REMOVED)

        clauseTables = ['BinaryPackagePublishingHistory', 'DistroArchRelease',
                        'BinaryPackageRelease', 'BinaryPackageName']

        return query, clauseTables

