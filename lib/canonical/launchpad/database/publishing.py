# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = ['SourcePackageFilePublishing', 'BinaryPackageFilePublishing',
           'SecureSourcePackagePublishingHistory',
           'SecureBinaryPackagePublishingHistory',
           'SourcePackagePublishingHistory',
           'BinaryPackagePublishingHistory',
           'IndexStanzaFields',
           ]

from warnings import warn
import operator
import os

from zope.interface import implements
from sqlobject import ForeignKey, StringCol, BoolCol, IntCol

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.lp.dbschema import (
    PackagePublishingPriority, PackagePublishingStatus,
    PackagePublishingPocket)
from canonical.launchpad.interfaces import (
    ISourcePackageFilePublishing, IBinaryPackageFilePublishing,
    ISecureSourcePackagePublishingHistory, IBinaryPackagePublishingHistory,
    ISecureBinaryPackagePublishingHistory, ISourcePackagePublishingHistory,
    IArchivePublisher, IArchiveFilePublisher, IArchiveSafePublisher,
    PoolFileOverwriteError)


# XXX cprov 20060818: move it away, perhaps archivepublisher/pool.py
def makePoolPath(source_name, component_name):
    """Return the pool path for a given source name and component name."""
    from canonical.archivepublisher.diskpool import poolify
    return os.path.join(
        'pool', poolify(source_name, component_name))


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
        path = diskpool.pathFor(component, source, filename)

        try:
            action = diskpool.addFile(
                component, source, filename, sha1, filealias)
            if action == diskpool.results.FILE_ADDED:
                log.debug("Added %s from library" % path)
            elif action == diskpool.results.SYMLINK_ADDED:
                log.debug("%s created as a symlink." % path)
            elif action == diskpool.results.NONE:
                log.debug(
                    "%s is already in pool with the same content." % path)
        except PoolFileOverwriteError, info:
            log.error("PoolFileOverwriteError: %s. Skipping. This indicates "
                      "some bad data, and Team Soyuz should be informed. "
                      "However, publishing of other packages is not affected."
                      % info)
            raise info


class SourcePackageFilePublishing(SQLBase, ArchiveFilePublisherBase):
    """Source package release files and their publishing status.

    Represents the source portion of the pool.
    """

    _idType = str
    _defaultOrder = "id"

    implements(ISourcePackageFilePublishing, IArchiveFilePublisher)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False,
                              notNull=True)

    sourcepackagepublishing = ForeignKey(dbName='sourcepackagepublishing',
         foreignKey='SecureSourcePackagePublishingHistory')

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias', notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, notNull=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              notNull=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  notNull=True)

    distroreleasename = StringCol(dbName='distroreleasename', unique=False,
                                  notNull=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               notNull=True, schema=PackagePublishingStatus)

    pocket = EnumCol(dbName='pocket', unique=False,
                     notNull=True, schema=PackagePublishingPocket)

    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)


class BinaryPackageFilePublishing(SQLBase, ArchiveFilePublisherBase):
    """A binary package file which is published.

    Represents the binary portion of the pool.
    """

    _idType = str
    _defaultOrder = "id"

    implements(IBinaryPackageFilePublishing, IArchiveFilePublisher)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False, notNull=True,
                              immutable=True)

    binarypackagepublishing = ForeignKey(dbName='binarypackagepublishing',
        foreignKey='SecureBinaryPackagePublishingHistory', immutable=True)

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias', notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, notNull=True,
                                         immutable=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              notNull=True, immutable=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  notNull=True, immutable=True)

    distroreleasename = StringCol(dbName='distroreleasename', unique=False,
                                  notNull=True, immutable=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               notNull=True, immutable=True,
                               schema=PackagePublishingStatus)

    architecturetag = StringCol(dbName='architecturetag', unique=False,
                                notNull=True, immutable=True)

    pocket = EnumCol(dbName='pocket', unique=False,
                     notNull=True, schema=PackagePublishingPocket)

    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)


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
            self.datepublished = UTC_NOW


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
    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

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
    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

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

    def getIndexStanza(self):
        """See IArchivePublisher"""
        fields = self.buildIndexStanzaFields()
        return fields.makeOutput()


class IndexStanzaFields:
    """Store and format ordered Index Stanza fields."""

    def __init__(self):
        self.fields = []

    def append(self, name, value):
        """Append an (field, value) tuple to the internal list.

        Then we can use the FIFO-like behaviour in makeOutput().
        """
        self.fields.append((name, value))

    def makeOutput(self):
        """Return a line-by-line aggregation of appended fields.

        Empty fields values will cause the exclusion of the field.
        The output order will preserve the insertion order, FIFO.
        """
        output_lines = []
        for name, value in self.fields:
            if not value:
                continue
            # do not add separation space for the special field 'Files'
            if name != 'Files':
                value = ' %s' % value

            output_lines.append('%s:%s' % (name, value))

        return '\n'.join(output_lines)


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
    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

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
            BinaryPackagePublishingHistory.archive=%s AND
            BinaryPackagePublishingHistory.status=%s
            """ % sqlvalues(self.sourcepackagerelease,
                            self.distrorelease,
                            self.distrorelease.main_archive,
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
    def meta_distroreleasesourcepackagerelease(self):
        """see ISourcePackagePublishingHistory."""
        return self.distrorelease.getSourcePackageRelease( 
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

    def buildIndexStanzaFields(self):
        """See IArchivePublisher"""
        # special fields preparation
        spr = self.sourcepackagerelease
        pool_path = makePoolPath(spr.name, self.component.name)
        files_subsection = ''.join(
            ['\n %s %s %s' % (spf.libraryfile.content.md5,
                              spf.libraryfile.content.filesize,
                              spf.libraryfile.filename)
             for spf in spr.files])
        # options filling
        fields = IndexStanzaFields()
        fields.append('Package', spr.name)
        fields.append('Binary', spr.dsc_binaries)
        fields.append('Version', spr.version)
        fields.append('Maintainer', spr.dsc_maintainer_rfc822)
        fields.append('Build-Depends', spr.builddepends)
        fields.append('Build-Depends-Indep', spr.builddependsindep)
        fields.append('Architecture', spr.architecturehintlist)
        fields.append('Standards-Version', spr.dsc_standards_version)
        fields.append('Format', spr.dsc_format)
        fields.append('Directory', pool_path)
        fields.append('Files', files_subsection)

        return fields


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
    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

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

    def buildIndexStanzaFields(self):
        """See IArchivePublisher"""
        bpr = self.binarypackagerelease
        spr = bpr.build.sourcepackagerelease

        # binaries have only one file, the DEB
        bin_file = bpr.files[0]
        bin_filename = bin_file.libraryfile.filename
        bin_size = bin_file.libraryfile.content.filesize
        bin_md5 = bin_file.libraryfile.content.md5
        bin_filepath = os.path.join(
            makePoolPath(spr.name, self.component.name), bin_filename)
        # description field in index is an association of summary and
        # description, as:
        #
        # Descrition: <SUMMARY>\n
        #  <DESCRIPTION L1>
        #  ...
        #  <DESCRIPTION LN>
        bin_description = (
            '%s\n %s'% (bpr.summary, '\n '.join(bpr.description.splitlines())))

        # Dealing with architecturespecific field.
        # Present 'all' in every archive index for architecture
        # independent binaries.
        if bpr.architecturespecific:
            architecture = bpr.build.distroarchrelease.architecturetag
        else:
            architecture = 'all'

        fields = IndexStanzaFields()
        fields.append('Package', bpr.name)
        fields.append('Priority', self.priority.title)
        fields.append('Section', self.section.name)
        fields.append('Installed-Size', bpr.installedsize)
        fields.append('Maintainer', spr.dsc_maintainer_rfc822)
        fields.append('Architecture', architecture)
        fields.append('Version', bpr.version)
        fields.append('Replaces', bpr.replaces)
        fields.append('Suggests', bpr.suggests)
        fields.append('Provides', bpr.provides)
        fields.append('Depends', bpr.depends)
        fields.append('Conflicts', bpr.conflicts)
        fields.append('Filename', bin_filepath)
        fields.append('Size', bin_size)
        fields.append('MD5sum', bin_md5)
        fields.append('Description', bin_description)

        # XXX cprov 20061103: the extra override fields (Bugs, Origin and
        # Task) included in the template be were not populated.
        # When we have the information this will be the place to fill them.

        return fields
