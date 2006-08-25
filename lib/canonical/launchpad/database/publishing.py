# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['SourcePackageFilePublishing', 'BinaryPackageFilePublishing',
           'SecureSourcePackagePublishingHistory',
           'SecureBinaryPackagePublishingHistory',
           'SourcePackagePublishingHistory',
           'BinaryPackagePublishingHistory'
           ]

from zope.interface import implements

from sqlobject import ForeignKey, StringCol, BoolCol, IntCol

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW, nowUTC
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import (
    ISourcePackageFilePublishing, IBinaryPackageFilePublishing,
    ISecureSourcePackagePublishingHistory, IBinaryPackagePublishingHistory,
    ISecureBinaryPackagePublishingHistory, ISourcePackagePublishingHistory,
    IArchivePublisher, IArchiveFilePublisher, IArchiveSafePublisher,
    AlreadyInPool, NeedsSymlinkInPool, PoolFileOverwriteError)
from canonical.librarian.utils import copy_and_close
from canonical.lp.dbschema import (
    EnumCol, PackagePublishingPriority, PackagePublishingStatus,
    PackagePublishingPocket)

from warnings import warn


class ArchiveFilePublisherBase:
    """Base class to publish files in the archive."""
    def publish(self, diskpool, log):
        """See IArchiveFilePublisherBase."""
        # XXX cprov 20060612: the encode should not be needed
        # when retrieving data from DB. bug # 49510
        source = self.sourcepackagename.encode('utf-8')
        component = self.componentname.encode('utf-8')
        filename = self.libraryfilealiasfilename.encode('utf-8')
        filealias = self.libraryfilealias
        sha1 = filealias.content.sha1

        try:
            diskpool.checkBeforeAdd(component, source, filename, sha1)
        except PoolFileOverwriteError, info:
            log.error("System is trying to overwrite %s (%s), "
                      "skipping publishing record. (%s)"
                      % (diskpool.pathFor(component, source, filename),
                         self.libraryfilealias.id, info))
            raise info
        # We don't benefit in very concrete terms by having the exceptions
        # NeedsSymlinkInPool and AlreadyInPool be separate, but they
        # communicate more clearly what is the state of the archive when
        # processing this publication record, and can be used to debug or
        # log more explicitly when necessary..
        except NeedsSymlinkInPool, info:
            diskpool.makeSymlink(component, source, filename)

        except AlreadyInPool, info:
            log.debug("%s is already in pool with the same content." %
                       diskpool.pathFor(component, source, filename))

        else:
            pool_file = diskpool.openForAdd(component, source, filename)
            filealias.open()
            copy_and_close(filealias, pool_file)
            log.debug("Added %s from library" %
                       diskpool.pathFor(component, source, filename))


class SourcePackageFilePublishing(SQLBase, ArchiveFilePublisherBase):
    """Source package release files and their publishing status.

    Represents the source portion of the pool.
    """

    _idType = str
    _defaultOrder = "id"

    implements(ISourcePackageFilePublishing, IArchiveFilePublisher)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False, default=None,
                              notNull=True)

    sourcepackagepublishing = ForeignKey(dbName='sourcepackagepublishing',
         foreignKey='SecureSourcePackagePublishingHistory')

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias', notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, default=None,
                                         notNull=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              default=None, notNull=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  default=None, notNull=True)

    distroreleasename = StringCol(dbName='distroreleasename', unique=False,
                                  default=None, notNull=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               default=None, notNull=True,
                               schema=PackagePublishingStatus)

    pocket = EnumCol(dbName='pocket', unique=False,
                     default=None, notNull=True,
                     schema=PackagePublishingPocket)


class BinaryPackageFilePublishing(SQLBase, ArchiveFilePublisherBase):
    """A binary package file which is published.

    Represents the binary portion of the pool.
    """

    _idType = str
    _defaultOrder = "id"

    implements(IBinaryPackageFilePublishing, IArchiveFilePublisher)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False, default=None,
                              notNull=True, immutable=True)

    binarypackagepublishing = ForeignKey(dbName='binarypackagepublishing',
        foreignKey='SecureBinaryPackagePublishingHistory', immutable=True)

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias', notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, default=None,
                                         notNull=True, immutable=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              default=None, notNull=True, immutable=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  default=None, notNull=True, immutable=True)

    distroreleasename = StringCol(dbName='distroreleasename', unique=False,
                                  default=None, notNull=True, immutable=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               default=None, notNull=True, immutable=True,
                               schema=PackagePublishingStatus)

    architecturetag = StringCol(dbName='architecturetag', unique=False,
                                default=None, notNull=True, immutable=True)

    pocket = EnumCol(dbName='pocket', unique=False,
                     default=None, notNull=True,
                     schema=PackagePublishingPocket)


class ArchiveSafePublisherBase:
    """Base class to grant ability to publish a record in a safe manner."""

    def setPublished(self):
        """see IArchiveSafePublisher."""
        # XXX cprov 20060614:
        # Implement sanity checks before set it as published
        if self.status == PackagePublishingStatus.PENDING:
            # update the DB publishing record status if they
            # are pending, don't do anything for the ones
            # already published (usually when we use -C
            # publish-distro.py option)
            self.status = PackagePublishingStatus.PUBLISHED
            self.datepublished = nowUTC


class SecureSourcePackagePublishingHistory(SQLBase, ArchiveSafePublisherBase):
    """A source package release publishing record."""

    implements(ISecureSourcePackagePublishingHistory, IArchiveSafePublisher)

    sourcepackagerelease = ForeignKey(foreignKey='SourcePackageRelease',
                                      dbName='sourcepackagerelease')
    distrorelease = ForeignKey(foreignKey='DistroRelease',
                               dbName='distrorelease')
    component = ForeignKey(foreignKey='Component', dbName='component')
    section = ForeignKey(foreignKey='Section', dbName='section')
    status = EnumCol(schema=PackagePublishingStatus)
    scheduleddeletiondate = UtcDateTimeCol(default=None)
    datepublished = UtcDateTimeCol(default=None)
    datecreated = UtcDateTimeCol(default=None)
    datesuperseded = UtcDateTimeCol(default=None)
    supersededby = ForeignKey(foreignKey='SourcePackageRelease',
                              dbName='supersededby', default=None)
    datemadepending = UtcDateTimeCol(default=None)
    dateremoved = UtcDateTimeCol(default=None)
    pocket = EnumCol(dbName='pocket', schema=PackagePublishingPocket,
                     default=PackagePublishingPocket.RELEASE,
                     notNull=True)
    embargo = BoolCol(dbName='embargo', default=False, notNull=True)
    embargolifted = UtcDateTimeCol(default=None)

    @classmethod
    def selectBy(cls, *args, **kwargs):
        """Prevent selecting embargo packages by default"""
        if 'embargo' in kwargs:
            if kwargs['embargo']:
                warn("SecureSourcePackagePublishingHistory.selectBy called "
                     "with embargo argument set to True",
                     stacklevel=2)
        kwargs['embargo'] = False
        return super(SecureSourcePackagePublishingHistory,
                     cls).selectBy(*args, **kwargs)

    @classmethod
    def selectByWithEmbargoedEntries(cls, *args, **kwargs):
        return super(SecureSourcePackagePublishingHistory,
                     cls).selectBy(*args, **kwargs)


class SecureBinaryPackagePublishingHistory(SQLBase, ArchiveSafePublisherBase):
    """A binary package publishing record."""

    implements(ISecureBinaryPackagePublishingHistory, IArchiveSafePublisher)

    binarypackagerelease = ForeignKey(foreignKey='BinaryPackageRelease',
                                      dbName='binarypackagerelease')
    distroarchrelease = ForeignKey(foreignKey='DistroArchRelease',
                                   dbName='distroarchrelease')
    component = ForeignKey(foreignKey='Component', dbName='component')
    section = ForeignKey(foreignKey='Section', dbName='section')
    priority = EnumCol(dbName='priority', schema=PackagePublishingPriority)
    status = EnumCol(dbName='status', schema=PackagePublishingStatus)
    scheduleddeletiondate = UtcDateTimeCol(default=None)
    datepublished = UtcDateTimeCol(default=None)
    datecreated = UtcDateTimeCol(default=UTC_NOW)
    datesuperseded = UtcDateTimeCol(default=None)
    supersededby = ForeignKey(foreignKey='Build', dbName='supersededby',
                              default=None)
    datemadepending = UtcDateTimeCol(default=None)
    dateremoved = UtcDateTimeCol(default=None)
    pocket = EnumCol(dbName='pocket', schema=PackagePublishingPocket)
    embargo = BoolCol(dbName='embargo', default=False, notNull=True)
    embargolifted = UtcDateTimeCol(default=None)

    @classmethod
    def selectBy(cls, *args, **kwargs):
        """Prevent selecting embargo packages by default"""
        if 'embargo' in kwargs:
            if kwargs['embargo']:
                warn("SecureBinaryPackagePublishingHistory.selectBy called "
                     "with embargo argument set to True",
                     stacklevel=2)
        kwargs['embargo'] = False
        return super(SecureBinaryPackagePublishingHistory,
                     cls).selectBy(*args, **kwargs)

    @classmethod
    def selectByWithEmbargoedEntries(cls, *args, **kwargs):
        return super(SecureBinaryPackagePublishingHistory,
                     cls).selectBy(*args, **kwargs)


class ArchivePublisherBase:
    """Base class for ArchivePublishing task."""

    def publish(self, diskpool, log):
        """See IArchivePublisher"""
        try:
            for pub_file in self.files:
                pub_file.publish(diskpool, log)
        except PoolFileOverwriteError:
            pass
        else:
            self.secure_record.setPublished()


class SourcePackagePublishingHistory(SQLBase, ArchivePublisherBase):
    """A source package release publishing record.

       Excluding embargoed stuff
    """
    implements(ISourcePackagePublishingHistory, IArchivePublisher)

    sourcepackagerelease = ForeignKey(foreignKey='SourcePackageRelease',
        dbName='sourcepackagerelease')
    distrorelease = ForeignKey(foreignKey='DistroRelease',
        dbName='distrorelease')
    component = ForeignKey(foreignKey='Component', dbName='component')
    section = ForeignKey(foreignKey='Section', dbName='section')
    status = EnumCol(schema=PackagePublishingStatus)
    scheduleddeletiondate = UtcDateTimeCol(default=None)
    datepublished = UtcDateTimeCol(default=None)
    datecreated = UtcDateTimeCol(default=None)
    datesuperseded = UtcDateTimeCol(default=None)
    supersededby = ForeignKey(foreignKey='SourcePackageRelease',
                              dbName='supersededby', default=None)
    datemadepending = UtcDateTimeCol(default=None)
    dateremoved = UtcDateTimeCol(default=None)
    pocket = EnumCol(dbName='pocket', schema=PackagePublishingPocket)

    def publishedBinaries(self):
        """See ISourcePackagePublishingHistory."""
        clause = """
            BinaryPackagePublishingHistory.binarypackagerelease=
                BinaryPackageRelease.id AND
            BinaryPackagePublishingHistory.distroarchrelease=
                DistroArchRelease.id AND
            BinaryPackageRelease.build=Build.id AND
            BinaryPackageRelease.binarypackagename=
                BinaryPackageName.id AND
            Build.sourcepackagerelease=%s AND
            DistroArchRelease.distrorelease=%s AND
            BinaryPackagePublishingHistory.status=%s
            """ % sqlvalues(self.sourcepackagerelease.id,
                            self.distrorelease.id,
                            PackagePublishingStatus.PUBLISHED)

        orderBy = ['BinaryPackageName.name',
                   'DistroArchRelease.architecturetag']

        clauseTables = ['Build', 'BinaryPackageRelease', 'BinaryPackageName',
                        'DistroArchRelease']

        return BinaryPackagePublishingHistory.select(
            clause, orderBy=orderBy, clauseTables=clauseTables)

    @property
    def secure_record(self):
        """See IArchivePublisherBase."""
        return SecureSourcePackagePublishingHistory.get(self.id)

    @property
    def files(self):
        """See IArchivePublisherBase."""
        return SourcePackageFilePublishing.selectBy(
            sourcepackagepublishing=self)

    @property
    def meta_sourcepackage(self):
        """see ISourcePackagePublishingHistory."""
        return self.distrorelease.getSourcePackage(
            self.sourcepackagerelease.sourcepackagename
            )

    @property
    def meta_sourcepackagerelease(self):
        """see ISourcePackagePublishingHistory."""
        return self.distrorelease.distribution.getSourcePackageRelease(
            self.sourcepackagerelease
            )

    @property
    def meta_supersededby(self):
        """see ISourcePackagePublishingHistory."""
        if not self.supersededby:
            return None
        return self.distrorelease.distribution.getSourcePackageRelease(
            self.supersededby
            )

    @property
    def displayname(self):
        """See IArchiveFilePublisherBase."""
        release = self.sourcepackagerelease
        name = release.sourcepackagename.name
        return "%s %s in %s" % (name, release.version,
                                self.distrorelease.name)


class BinaryPackagePublishingHistory(SQLBase, ArchivePublisherBase):
    """A binary package publishing record. (excluding embargoed packages)"""

    implements(IBinaryPackagePublishingHistory, IArchivePublisher)

    binarypackagerelease = ForeignKey(foreignKey='BinaryPackageRelease',
                                      dbName='binarypackagerelease')
    distroarchrelease = ForeignKey(foreignKey='DistroArchRelease',
                                   dbName='distroarchrelease')
    component = ForeignKey(foreignKey='Component', dbName='component')
    section = ForeignKey(foreignKey='Section', dbName='section')
    priority = EnumCol(dbName='priority', schema=PackagePublishingPriority)
    status = EnumCol(dbName='status', schema=PackagePublishingStatus)
    scheduleddeletiondate = UtcDateTimeCol(default=None)
    datepublished = UtcDateTimeCol(default=None)
    datecreated = UtcDateTimeCol(default=None)
    datesuperseded = UtcDateTimeCol(default=None)
    supersededby = ForeignKey(foreignKey='Build', dbName='supersededby',
                              default=None)
    datemadepending = UtcDateTimeCol(default=None)
    dateremoved = UtcDateTimeCol(default=None)
    pocket = EnumCol(dbName='pocket', schema=PackagePublishingPocket)


    @property
    def distroarchreleasebinarypackagerelease(self):
        """See IBinaryPackagePublishingHistory."""
        # import here to avoid circular import
        from canonical.launchpad.database.distroarchreleasebinarypackagerelease \
            import DistroArchReleaseBinaryPackageRelease

        return DistroArchReleaseBinaryPackageRelease(
            self.distroarchrelease,
            self.binarypackagerelease)

    @property
    def secure_record(self):
        """See IArchivePublisherBase."""
        return SecureBinaryPackagePublishingHistory.get(self.id)

    @property
    def files(self):
        """See IArchivePublisherBase."""
        return BinaryPackageFilePublishing.selectBy(
            binarypackagepublishing=self)

    @property
    def hasRemovalRequested(self):
        """See ISecureBinaryPackagePublishingHistory"""
        return self.datesuperseded is not None and self.supersededby is None

    @property
    def displayname(self):
        """See IArchiveFilePublisherBase."""
        release = self.binarypackagerelease
        name = release.binarypackagename.name
        distrorelease = self.distroarchrelease.distrorelease
        return "%s %s in %s %s" % (name, release.version,
                                   distrorelease.name,
                                   self.distroarchrelease.architecturetag)
