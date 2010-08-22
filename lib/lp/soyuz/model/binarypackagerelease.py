# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'BinaryPackageRelease',
    'BinaryPackageReleaseDownloadCount',
    'BinaryPackageReleaseSet',
    ]


import simplejson
from sqlobject import (
    BoolCol,
    ForeignKey,
    IntCol,
    SQLMultipleJoin,
    StringCol,
    )
from storm.locals import (
    Date,
    Int,
    Reference,
    Storm,
    )
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    quote,
    quote_like,
    SQLBase,
    sqlvalues,
    )
from lp.soyuz.interfaces.binarypackagerelease import (
    BinaryPackageFileType,
    BinaryPackageFormat,
    IBinaryPackageRelease,
    IBinaryPackageReleaseDownloadCount,
    IBinaryPackageReleaseSet,
    )
from lp.soyuz.interfaces.publishing import (
    PackagePublishingPriority,
    PackagePublishingStatus,
    )
from lp.soyuz.model.files import BinaryPackageFile


class BinaryPackageRelease(SQLBase):
    implements(IBinaryPackageRelease)
    _table = 'BinaryPackageRelease'
    binarypackagename = ForeignKey(dbName='binarypackagename', notNull=True,
                                   foreignKey='BinaryPackageName')
    version = StringCol(dbName='version', notNull=True)
    summary = StringCol(dbName='summary', notNull=True, default="")
    description = StringCol(dbName='description', notNull=True)
    build = ForeignKey(
        dbName='build', foreignKey='BinaryPackageBuild', notNull=True)
    binpackageformat = EnumCol(dbName='binpackageformat', notNull=True,
                               schema=BinaryPackageFormat)
    component = ForeignKey(dbName='component', foreignKey='Component',
                           notNull=True)
    section = ForeignKey(dbName='section', foreignKey='Section', notNull=True)
    priority = EnumCol(dbName='priority', notNull=True,
                       schema=PackagePublishingPriority)
    shlibdeps = StringCol(dbName='shlibdeps')
    depends = StringCol(dbName='depends')
    recommends = StringCol(dbName='recommends')
    suggests = StringCol(dbName='suggests')
    conflicts = StringCol(dbName='conflicts')
    replaces = StringCol(dbName='replaces')
    provides = StringCol(dbName='provides')
    pre_depends = StringCol(dbName='pre_depends')
    enhances = StringCol(dbName='enhances')
    breaks = StringCol(dbName='breaks')
    essential = BoolCol(dbName='essential', default=False)
    installedsize = IntCol(dbName='installedsize')
    architecturespecific = BoolCol(dbName='architecturespecific',
                                   notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    debug_package = ForeignKey(dbName='debug_package',
                              foreignKey='BinaryPackageRelease')

    files = SQLMultipleJoin('BinaryPackageFile',
        joinColumn='binarypackagerelease', orderBy="libraryfile")

    _user_defined_fields = StringCol(dbName='user_defined_fields')

    def __init__(self, *args, **kwargs):
        if 'user_defined_fields' in kwargs:
            kwargs['_user_defined_fields'] = simplejson.dumps(
                kwargs['user_defined_fields'])
            del kwargs['user_defined_fields']
        super(BinaryPackageRelease, self).__init__(*args, **kwargs)

    @property
    def user_defined_fields(self):
        """See `IBinaryPackageRelease`."""
        if self._user_defined_fields is None:
            return []
        return simplejson.loads(self._user_defined_fields)

    @property
    def title(self):
        """See `IBinaryPackageRelease`."""
        return '%s-%s' % (self.binarypackagename.name, self.version)

    @property
    def name(self):
        """See `IBinaryPackageRelease`."""
        return self.binarypackagename.name

    @property
    def distributionsourcepackagerelease(self):
        """See `IBinaryPackageRelease`."""
        # import here to avoid circular import problems
        from lp.soyuz.model.distributionsourcepackagerelease \
            import DistributionSourcePackageRelease
        return DistributionSourcePackageRelease(
            distribution=self.build.distribution,
            sourcepackagerelease=self.build.source_package_release)

    @property
    def sourcepackagename(self):
        """See `IBinaryPackageRelease`."""
        return self.build.source_package_release.sourcepackagename.name

    @property
    def is_new(self):
        """See `IBinaryPackageRelease`."""
        distroarchseries = self.build.distro_arch_series
        distroarchseries_binary_package = distroarchseries.getBinaryPackage(
            self.binarypackagename)
        return distroarchseries_binary_package.currentrelease is None

    def addFile(self, file):
        """See `IBinaryPackageRelease`."""
        determined_filetype = None
        if file.filename.endswith(".deb"):
            determined_filetype = BinaryPackageFileType.DEB
        elif file.filename.endswith(".rpm"):
            determined_filetype = BinaryPackageFileType.RPM
        elif file.filename.endswith(".udeb"):
            determined_filetype = BinaryPackageFileType.UDEB
        elif file.filename.endswith(".ddeb"):
            determined_filetype = BinaryPackageFileType.DDEB
        else:
            raise AssertionError(
                'Unsupported file type: %s' % file.filename)

        return BinaryPackageFile(binarypackagerelease=self,
                                 filetype=determined_filetype,
                                 libraryfile=file)

    def override(self, component=None, section=None, priority=None):
        """See `IBinaryPackageRelease`."""
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
            queries.append('DistroArchSeries.architecturetag=%s'
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
            status_published = PackagePublishingStatus.PUBLISHED
            queries.append('BinaryPackagePublishingHistory.status = %s'
                         % sqlvalues(status_published))

        if archtag:
            queries.append('DistroArchSeries.architecturetag = %s'
                         % sqlvalues(archtag))

        query = " AND ".join(queries)
        return BinaryPackageRelease.select(query, distinct=True,
                                           clauseTables=clauseTables,
                                           orderBy=orderBy)

    def _buildBaseQuery(self, distroseries):
        query = """
        BinaryPackagePublishingHistory.binarypackagerelease =
           BinaryPackageRelease.id AND
        BinaryPackagePublishingHistory.distroarchseries =
           DistroArchSeries.id AND
        BinaryPackagePublishingHistory.archive IN %s AND
        DistroArchSeries.distroseries = %s AND
        BinaryPackageRelease.binarypackagename =
           BinaryPackageName.id AND
        BinaryPackagePublishingHistory.dateremoved is NULL
        """ % sqlvalues([archive.id for archive in
                         distroseries.distribution.all_distro_archives],
                        distroseries)

        clauseTables = ['BinaryPackagePublishingHistory', 'DistroArchSeries',
                        'BinaryPackageRelease', 'BinaryPackageName']

        return query, clauseTables


class BinaryPackageReleaseDownloadCount(Storm):
    """See `IBinaryPackageReleaseDownloadCount`."""

    implements(IBinaryPackageReleaseDownloadCount)
    __storm_table__ = 'BinaryPackageReleaseDownloadCount'

    id = Int(primary=True)
    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')
    binary_package_release_id = Int(
        name='binary_package_release', allow_none=False)
    binary_package_release = Reference(
        binary_package_release_id, 'BinaryPackageRelease.id')
    day = Date(allow_none=False)
    country_id = Int(name='country', allow_none=True)
    country = Reference(country_id, 'Country.id')
    count = Int(allow_none=False)

    def __init__(self, archive, binary_package_release, day, country, count):
        super(BinaryPackageReleaseDownloadCount, self).__init__()
        self.archive = archive
        self.binary_package_release = binary_package_release
        self.day = day
        self.country = country
        self.count = count

    @property
    def binary_package_name(self):
        """See `IBinaryPackageReleaseDownloadCount`."""
        return self.binary_package_release.name

    @property
    def binary_package_version(self):
        """See `IBinaryPackageReleaseDownloadCount`."""
        return self.binary_package_release.version

