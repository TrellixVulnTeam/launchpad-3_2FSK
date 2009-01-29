# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type

__all__ = [
    'makePoolPath',
    'BinaryPackageFilePublishing',
    'BinaryPackagePublishingHistory',
    'IndexStanzaFields',
    'PublishingSet',
    'SourcePackageFilePublishing',
    'SourcePackagePublishingHistory',
    ]


from datetime import datetime
import operator
import os
import pytz
from warnings import warn

from zope.component import getUtility
from zope.interface import implements

from sqlobject import ForeignKey, StringCol, BoolCol

from storm.expr import Desc, In, LeftJoin
from storm.store import Store

from canonical.buildmaster.master import determineArchitecturesToBuild
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.launchpad.database.binarypackagename import BinaryPackageName
from canonical.launchpad.database.files import (
    BinaryPackageFile, SourcePackageReleaseFile)
from canonical.launchpad.database.librarian import (
    LibraryFileAlias, LibraryFileContent)
from canonical.launchpad.database.packagediff import PackageDiff
from canonical.launchpad.interfaces import (
    ArchivePurpose, IArchiveSafePublisher,
    IBinaryPackageFilePublishing, IBinaryPackagePublishingHistory,
    ISourcePackageFilePublishing, ISourcePackagePublishingHistory,
    PackagePublishingPriority, PackagePublishingStatus,
    PackagePublishingPocket, PackageUploadStatus,
    PoolFileOverwriteError)
from canonical.launchpad.interfaces.build import IBuildSet, BuildStatus
from canonical.launchpad.interfaces.publishing import (
    IPublishingSet, active_publishing_status)
from canonical.launchpad.scripts.changeoverride import ArchiveOverriderError
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)
from canonical.launchpad.validators.person import validate_public_person
from canonical.launchpad.webapp.interfaces import NotFoundError


# XXX cprov 2006-08-18: move it away, perhaps archivepublisher/pool.py
def makePoolPath(source_name, component_name):
    """Return the pool path for a given source name and component name."""
    from canonical.archivepublisher.diskpool import poolify
    return os.path.join(
        'pool', poolify(source_name, component_name))


class FilePublishingBase:
    """Base class to publish files in the archive."""

    def publish(self, diskpool, log):
        """See IFilePublishing."""
        # XXX cprov 2006-06-12 bug=49510: The encode should not be needed
        # when retrieving data from DB.
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

    @property
    def archive_url(self):
        """See IFilePublishing."""
        return (self.archive.archive_url + "/" +
                makePoolPath(self.sourcepackagename, self.componentname) +
                "/" +
                self.libraryfilealiasfilename)


class SourcePackageFilePublishing(FilePublishingBase, SQLBase):
    """Source package release files and their publishing status.

    Represents the source portion of the pool.
    """

    _idType = unicode
    _defaultOrder = "id"

    implements(ISourcePackageFilePublishing)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False,
                              notNull=True)

    sourcepackagepublishing = ForeignKey(
        dbName='sourcepackagepublishing',
        foreignKey='SourcePackagePublishingHistory')

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias',
        notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, notNull=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              notNull=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  notNull=True)

    distroseriesname = StringCol(dbName='distroseriesname', unique=False,
                                  notNull=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               notNull=True, schema=PackagePublishingStatus)

    pocket = EnumCol(dbName='pocket', unique=False,
                     notNull=True, schema=PackagePublishingPocket)

    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

    @property
    def publishing_record(self):
        """See `IFilePublishing`."""
        return self.sourcepackagepublishing

    @property
    def file_type_name(self):
        """See `ISourcePackagePublishingHistory`."""
        fn = self.libraryfilealiasfilename
        if ".orig.tar." in fn:
            return "orig"
        if fn.endswith(".dsc"):
            return "dsc"
        if ".diff." in fn:
            return "diff"
        if fn.endswith(".tar.gz"):
            return "tar"
        return "other"


class BinaryPackageFilePublishing(FilePublishingBase, SQLBase):
    """A binary package file which is published.

    Represents the binary portion of the pool.
    """

    _idType = unicode
    _defaultOrder = "id"

    implements(IBinaryPackageFilePublishing)

    distribution = ForeignKey(dbName='distribution',
                              foreignKey="Distribution",
                              unique=False, notNull=True,
                              immutable=True)

    binarypackagepublishing = ForeignKey(
        dbName='binarypackagepublishing',
        foreignKey='BinaryPackagePublishingHistory', immutable=True)

    libraryfilealias = ForeignKey(
        dbName='libraryfilealias', foreignKey='LibraryFileAlias',
        notNull=True)

    libraryfilealiasfilename = StringCol(dbName='libraryfilealiasfilename',
                                         unique=False, notNull=True,
                                         immutable=True)

    componentname = StringCol(dbName='componentname', unique=False,
                              notNull=True, immutable=True)

    sourcepackagename = StringCol(dbName='sourcepackagename', unique=False,
                                  notNull=True, immutable=True)

    distroseriesname = StringCol(dbName='distroseriesname', unique=False,
                                  notNull=True, immutable=True)

    publishingstatus = EnumCol(dbName='publishingstatus', unique=False,
                               notNull=True, immutable=True,
                               schema=PackagePublishingStatus)

    architecturetag = StringCol(dbName='architecturetag', unique=False,
                                notNull=True, immutable=True)

    pocket = EnumCol(dbName='pocket', unique=False,
                     notNull=True, schema=PackagePublishingPocket)

    archive = ForeignKey(dbName="archive", foreignKey="Archive", notNull=True)

    @property
    def publishing_record(self):
        """See `ArchiveFilePublisherBase`."""
        return self.binarypackagepublishing


class ArchivePublisherBase:
    """Base class for `IArchivePublisher`."""

    def setPublished(self):
        """see IArchiveSafePublisher."""
        # XXX cprov 2006-06-14:
        # Implement sanity checks before set it as published
        if self.status == PackagePublishingStatus.PENDING:
            # update the DB publishing record status if they
            # are pending, don't do anything for the ones
            # already published (usually when we use -C
            # publish-distro.py option)
            self.status = PackagePublishingStatus.PUBLISHED
            self.datepublished = UTC_NOW

    def publish(self, diskpool, log):
        """See `IPublishing`"""
        try:
            for pub_file in self.files:
                pub_file.publish(diskpool, log)
        except PoolFileOverwriteError:
            pass
        else:
            self.setPublished()

    def getIndexStanza(self):
        """See `IPublishing`."""
        fields = self.buildIndexStanzaFields()
        return fields.makeOutput()

    def supersede(self):
        """See `IPublishing`."""
        self.status = PackagePublishingStatus.SUPERSEDED
        self.datesuperseded = UTC_NOW
        return self

    def requestDeletion(self, removed_by, removal_comment=None):
        """See `IPublishing`."""
        self.status = PackagePublishingStatus.DELETED
        self.datesuperseded = UTC_NOW
        self.removed_by = removed_by
        self.removal_comment = removal_comment
        return self

    def requestObsolescence(self):
        """See `IArchivePublisher`."""
        # The tactic here is to bypass the domination step when publishing,
        # and let it go straight to death row processing.  This is because
        # domination ignores stable distroseries, and that is exactly what
        # we're most likely to be obsoleting.
        #
        # Setting scheduleddeletiondate achieves that aim.
        self.status = PackagePublishingStatus.OBSOLETE
        self.scheduleddeletiondate = UTC_NOW
        return self

    @property
    def age(self):
        """See `IArchivePublisher`."""
        return datetime.now(pytz.UTC) - self.datecreated


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
    """A source package release publishing record."""
    implements(ISourcePackagePublishingHistory)

    sourcepackagerelease = ForeignKey(foreignKey='SourcePackageRelease',
        dbName='sourcepackagerelease')
    distroseries = ForeignKey(foreignKey='DistroSeries',
        dbName='distroseries')
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
    removed_by = ForeignKey(
        dbName="removed_by", foreignKey="Person",
        storm_validator=validate_public_person, default=None)
    removal_comment = StringCol(dbName="removal_comment", default=None)

    def getPublishedBinaries(self):
        """See `ISourcePackagePublishingHistory`."""
        publishing_set = getUtility(IPublishingSet)
        result_set = publishing_set.getBinaryPublicationsForSources(self)

        return [binary_pub
                for source, binary_pub, binary, binary_name, arch
                in result_set]

    def getBuiltBinaries(self):
        """See `ISourcePackagePublishingHistory`."""
        clauses = """
            BinaryPackagePublishingHistory.binarypackagerelease=
                BinaryPackageRelease.id AND
            BinaryPackagePublishingHistory.distroarchseries=
                DistroArchSeries.id AND
            BinaryPackageRelease.build=Build.id AND
            Build.sourcepackagerelease=%s AND
            DistroArchSeries.distroseries=%s AND
            BinaryPackagePublishingHistory.archive=%s AND
            BinaryPackagePublishingHistory.pocket=%s
        """ % sqlvalues(self.sourcepackagerelease, self.distroseries,
                        self.archive, self.pocket)

        clauseTables = ['Build', 'BinaryPackageRelease', 'DistroArchSeries']
        orderBy = ['-BinaryPackagePublishingHistory.id']
        preJoins = ['binarypackagerelease']

        results = BinaryPackagePublishingHistory.select(
            clauses, orderBy=orderBy, clauseTables=clauseTables,
            prejoins=preJoins)
        binary_publications = list(results)

        unique_binary_ids = set(
            [pub.binarypackagerelease.id for pub in binary_publications])

        unique_binary_publications = []
        for pub in binary_publications:
            if pub.binarypackagerelease.id in unique_binary_ids:
                unique_binary_publications.append(pub)
                unique_binary_ids.remove(pub.binarypackagerelease.id)
                if len(unique_binary_ids) == 0:
                    break

        return unique_binary_publications

    def getBuilds(self):
        """See `ISourcePackagePublishingHistory`."""
        publishing_set = getUtility(IPublishingSet)
        result_set = publishing_set.getBuildsForSources(self)

        return [build for source, build, arch in result_set]

    def createMissingBuilds(self, architectures_available=None,
                            pas_verify=None, logger=None):
        """See `ISourcePackagePublishingHistory`."""
        if self.archive.purpose == ArchivePurpose.PPA:
            pas_verify = None

        if architectures_available is None:
            architectures_available = [
                arch for arch in self.distroseries.architectures
                if arch.getPocketChroot() is not None]

        build_architectures = determineArchitecturesToBuild(
            self, architectures_available, self.distroseries, pas_verify)

        builds = []
        for arch in build_architectures:
            build_candidate = self._createMissingBuildForArchitecture(
                arch, logger=logger)
            if build_candidate is not None:
                builds.append(build_candidate)

        return builds

    def _createMissingBuildForArchitecture(self, arch, logger=None):
        """Create a build for a given architecture if it doesn't exist yet.

        Return the just-created `IBuild` record already scored or None
        if a suitable build is already present.
        """
        build_candidate = self.sourcepackagerelease.getBuildByArch(
            arch, self.archive)

        # Check DistroArchSeries database IDs because the object belongs
        # to different transactions (architecture_available is cached).
        if (build_candidate is not None and
            (build_candidate.distroarchseries.id == arch.id or
             build_candidate.buildstate == BuildStatus.FULLYBUILT)):
            return None

        build = self.sourcepackagerelease.createBuild(
            distroarchseries=arch, archive=self.archive, pocket=self.pocket)
        build_queue = build.createBuildQueueEntry()
        build_queue.score()
        Store.of(build).flush()

        if logger is not None:
            logger.debug(
                "Created %s [%d] in %s (%d)"
                % (build.title, build.id, build.archive.title,
                   build_queue.lastscore))

        return build

    @property
    def files(self):
        """See `IPublishing`."""
        preJoins = ['libraryfilealias', 'libraryfilealias.content']

        return SourcePackageFilePublishing.selectBy(
            sourcepackagepublishing=self).prejoin(preJoins)

    def getSourceAndBinaryLibraryFiles(self):
        """See `IPublishing`."""
        publishing_set = getUtility(IPublishingSet)
        result_set = publishing_set.getFilesForSources(self)
        libraryfiles = [file for source, file, content in result_set]

        # XXX cprov 20080710: UNIONs cannot be ordered appropriately.
        # See IPublishing.getFilesForSources().
        return sorted(libraryfiles, key=operator.attrgetter('filename'))

    @property
    def meta_sourcepackage(self):
        """see `ISourcePackagePublishingHistory`."""
        return self.distroseries.getSourcePackage(
            self.sourcepackagerelease.sourcepackagename
            )

    @property
    def meta_sourcepackagerelease(self):
        """see `ISourcePackagePublishingHistory`."""
        return self.distroseries.distribution.getSourcePackageRelease(
            self.sourcepackagerelease
            )

    @property
    def meta_distroseriessourcepackagerelease(self):
        """see `ISourcePackagePublishingHistory`."""
        return self.distroseries.getSourcePackageRelease(
            self.sourcepackagerelease
            )

    @property
    def meta_supersededby(self):
        """see `ISourcePackagePublishingHistory`."""
        if not self.supersededby:
            return None
        return self.distroseries.distribution.getSourcePackageRelease(
            self.supersededby
            )

    @property
    def source_package_name(self):
        """See `ISourcePackagePublishingHistory`"""
        return self.sourcepackagerelease.name

    @property
    def source_package_version(self):
        """See `ISourcePackagePublishingHistory`"""
        return self.sourcepackagerelease.version

    @property
    def component_name(self):
        """See `ISourcePackagePublishingHistory`"""
        return self.component.name

    @property
    def section_name(self):
        """See `ISourcePackagePublishingHistory`"""
        return self.section.name

    @property
    def displayname(self):
        """See `IPublishing`."""
        release = self.sourcepackagerelease
        name = release.sourcepackagename.name
        return "%s %s in %s" % (name, release.version,
                                self.distroseries.name)

    def buildIndexStanzaFields(self):
        """See `IPublishing`."""
        # Special fields preparation.
        spr = self.sourcepackagerelease
        pool_path = makePoolPath(spr.name, self.component.name)
        files_subsection = ''.join(
            ['\n %s %s %s' % (spf.libraryfile.content.md5,
                              spf.libraryfile.content.filesize,
                              spf.libraryfile.filename)
             for spf in spr.files])
        # Filling stanza options.
        fields = IndexStanzaFields()
        fields.append('Package', spr.name)
        fields.append('Binary', spr.dsc_binaries)
        fields.append('Version', spr.version)
        fields.append('Section', self.section.name)
        fields.append('Maintainer', spr.dsc_maintainer_rfc822)
        fields.append('Build-Depends', spr.builddepends)
        fields.append('Build-Depends-Indep', spr.builddependsindep)
        fields.append('Build-Conflicts', spr.build_conflicts)
        fields.append('Build-Conflicts-Indep', spr.build_conflicts_indep)
        fields.append('Architecture', spr.architecturehintlist)
        fields.append('Standards-Version', spr.dsc_standards_version)
        fields.append('Format', spr.dsc_format)
        fields.append('Directory', pool_path)
        fields.append('Files', files_subsection)

        return fields

    def changeOverride(self, new_component=None, new_section=None):
        """See `ISourcePackagePublishingHistory`."""
        # Check we have been asked to do something
        if (new_component is None and
            new_section is None):
            raise AssertionError("changeOverride must be passed either a"
                                 " new component or new section")

        # Retrieve current publishing info
        current = self

        # Check there is a change to make
        if new_component is None:
            new_component = current.component
        if new_section is None:
            new_section = current.section

        if (new_component == current.component and
            new_section == current.section):
            return

        # See if the archive has changed by virtue of the component
        # changing:
        distribution = self.distroseries.distribution
        new_archive = distribution.getArchiveByComponent(
            new_component.name)
        if new_archive != None and new_archive != current.archive:
            raise ArchiveOverriderError(
                "Overriding component to '%s' failed because it would "
                "require a new archive." % new_component.name)

        return SourcePackagePublishingHistory(
            distroseries=current.distroseries,
            sourcepackagerelease=current.sourcepackagerelease,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            pocket=current.pocket,
            component=new_component,
            section=new_section,
            archive=current.archive)

    def copyTo(self, distroseries, pocket, archive):
        """See `ISourcePackagePublishingHistory`."""
        copy = SourcePackagePublishingHistory(
            distroseries=distroseries,
            pocket=pocket,
            archive=archive,
            sourcepackagerelease=self.sourcepackagerelease,
            component=self.component,
            section=self.section,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW)
        return copy


class BinaryPackagePublishingHistory(SQLBase, ArchivePublisherBase):
    """A binary package publishing record."""

    implements(IBinaryPackagePublishingHistory)

    binarypackagerelease = ForeignKey(foreignKey='BinaryPackageRelease',
                                      dbName='binarypackagerelease')
    distroarchseries = ForeignKey(foreignKey='DistroArchSeries',
                                   dbName='distroarchseries')
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
    removed_by = ForeignKey(
        dbName="removed_by", foreignKey="Person",
        storm_validator=validate_public_person, default=None)
    removal_comment = StringCol(dbName="removal_comment", default=None)

    @property
    def distroarchseriesbinarypackagerelease(self):
        """See `IBinaryPackagePublishingHistory`."""
        # Import here to avoid circular import.
        from canonical.launchpad.database import (
            DistroArchSeriesBinaryPackageRelease)

        return DistroArchSeriesBinaryPackageRelease(
            self.distroarchseries,
            self.binarypackagerelease)

    @property
    def files(self):
        """See `IPublishing`."""
        preJoins = ['libraryfilealias', 'libraryfilealias.content']

        return BinaryPackageFilePublishing.selectBy(
            binarypackagepublishing=self).prejoin(preJoins)

    @property
    def displayname(self):
        """See `IPublishing`."""
        release = self.binarypackagerelease
        name = release.binarypackagename.name
        distroseries = self.distroarchseries.distroseries
        return "%s %s in %s %s" % (name, release.version,
                                   distroseries.name,
                                   self.distroarchseries.architecturetag)

    def buildIndexStanzaFields(self):
        """See `IPublishing`."""
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
        descr_lines = [line.lstrip() for line in bpr.description.splitlines()]
        bin_description = (
            '%s\n %s'% (bpr.summary, '\n '.join(descr_lines)))

        # Dealing with architecturespecific field.
        # Present 'all' in every archive index for architecture
        # independent binaries.
        if bpr.architecturespecific:
            architecture = bpr.build.distroarchseries.architecturetag
        else:
            architecture = 'all'

        essential = None
        if bpr.essential:
            essential = 'yes'

        fields = IndexStanzaFields()
        fields.append('Package', bpr.name)
        fields.append('Source', spr.name)
        fields.append('Priority', self.priority.title.lower())
        fields.append('Section', self.section.name)
        fields.append('Installed-Size', bpr.installedsize)
        fields.append('Maintainer', spr.dsc_maintainer_rfc822)
        fields.append('Architecture', architecture)
        fields.append('Version', bpr.version)
        fields.append('Recommends', bpr.recommends)
        fields.append('Replaces', bpr.replaces)
        fields.append('Suggests', bpr.suggests)
        fields.append('Provides', bpr.provides)
        fields.append('Depends', bpr.depends)
        fields.append('Conflicts', bpr.conflicts)
        fields.append('Pre-Depends', bpr.pre_depends)
        fields.append('Enhances', bpr.enhances)
        fields.append('Breaks', bpr.breaks)
        fields.append('Essential', essential)
        fields.append('Filename', bin_filepath)
        fields.append('Size', bin_size)
        fields.append('MD5sum', bin_md5)
        fields.append('Description', bin_description)

        # XXX cprov 2006-11-03: the extra override fields (Bugs, Origin and
        # Task) included in the template be were not populated.
        # When we have the information this will be the place to fill them.

        return fields

    def changeOverride(self, new_component=None, new_section=None,
                       new_priority=None):
        """See `IBinaryPackagePublishingHistory`."""

        # Check we have been asked to do something
        if (new_component is None and new_section is None
            and new_priority is None):
            raise AssertionError("changeOverride must be passed a new"
                                 "component, section and/or priority.")

        # Retrieve current publishing info
        current = self

        # Check there is a change to make
        if new_component is None:
            new_component = current.component
        if new_section is None:
            new_section = current.section
        if new_priority is None:
            new_priority = current.priority

        if (new_component == current.component and
            new_section == current.section and
            new_priority == current.priority):
            return

        # See if the archive has changed by virtue of the component changing:
        distribution = self.distroarchseries.distroseries.distribution
        new_archive = distribution.getArchiveByComponent(
            new_component.name)
        if new_archive != None and new_archive != self.archive:
            raise ArchiveOverriderError(
                "Overriding component to '%s' failed because it would "
                "require a new archive." % new_component.name)

        # Append the modified package publishing entry
        return BinaryPackagePublishingHistory(
            binarypackagerelease=self.binarypackagerelease,
            distroarchseries=self.distroarchseries,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            pocket=current.pocket,
            component=new_component,
            section=new_section,
            priority=new_priority,
            archive=current.archive)

    def copyTo(self, distroseries, pocket, archive):
        """See `BinaryPackagePublishingHistory`."""
        current = self

        if current.binarypackagerelease.architecturespecific:
            try:
                target_architecture = distroseries[
                    current.distroarchseries.architecturetag]
            except NotFoundError:
                return []
            destination_architectures = [target_architecture]
        else:
            destination_architectures = distroseries.architectures

        copies = []
        for architecture in destination_architectures:
            copy = BinaryPackagePublishingHistory(
                archive=archive,
                binarypackagerelease=self.binarypackagerelease,
                distroarchseries=architecture,
                component=current.component,
                section=current.section,
                priority=current.priority,
                status=PackagePublishingStatus.PENDING,
                datecreated=UTC_NOW,
                pocket=pocket)
            copies.append(copy)

        return copies


class PublishingSet:
    """Utilities for manipulating publications in batches."""

    implements(IPublishingSet)

    def getBuildsForSourceIds(self, source_publication_ids, archive=None):
        """See `IPublishingSet`."""
        # Import Build and DistroArchSeries locally to avoid circular
        # imports, since that Build uses SourcePackagePublishingHistory
        # and DistroArchSeries uses BinaryPackagePublishingHistory.
        from canonical.launchpad.database.build import Build
        from canonical.launchpad.database.distroarchseries import (
            DistroArchSeries)

        # If an archive was passed in as a parameter, add an extra expression
        # to filter by archive:
        extra_exprs = []
        if archive is not None:
            extra_exprs.append(
                SourcePackagePublishingHistory.archive == archive)

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result_set = store.find(
            (SourcePackagePublishingHistory, Build, DistroArchSeries),
            Build.distroarchseriesID == DistroArchSeries.id,
            SourcePackagePublishingHistory.archiveID == Build.archiveID,
            SourcePackagePublishingHistory.distroseriesID ==
                DistroArchSeries.distroseriesID,
            SourcePackagePublishingHistory.sourcepackagereleaseID ==
                Build.sourcepackagereleaseID,
            In(SourcePackagePublishingHistory.id, source_publication_ids),
            *extra_exprs)

        result_set.order_by(
            SourcePackagePublishingHistory.id,
            DistroArchSeries.architecturetag)

        return result_set

    def getByIdAndArchive(self, id, archive):
        """See `IPublishingSet`."""
        return Store.of(archive).find(
            SourcePackagePublishingHistory,
            SourcePackagePublishingHistory.id == id,
            SourcePackagePublishingHistory.archive == archive.id)

    def _extractIDs(self, one_or_more_source_publications):
        """Return a list of database IDs for the given list or single object.

        :param one_or_more_source_publications: an single object or a list of
            `ISourcePackagePublishingHistory` objects.

        :return: a list of database IDs corresponding to the give set of
            objects.
        """
        try:
            source_publications = tuple(one_or_more_source_publications)
        except TypeError:
            source_publications = (one_or_more_source_publications,)

        return [source_publication.id
                for source_publication in source_publications]

    def getBuildsForSources(self, one_or_more_source_publications):
        """See `IPublishingSet`."""
        source_publication_ids = self._extractIDs(
            one_or_more_source_publications)

        return self.getBuildsForSourceIds(source_publication_ids)

    def getFilesForSources(self, one_or_more_source_publications):
        """See `IPublishingSet`."""
        # Import Build and BinaryPackageRelease locally to avoid circular
        # imports, since that Build already imports
        # SourcePackagePublishingHistory and BinaryPackageRelease imports
        # Build.
        from canonical.launchpad.database.binarypackagerelease import (
            BinaryPackageRelease)
        from canonical.launchpad.database.build import Build

        source_publication_ids = self._extractIDs(
            one_or_more_source_publications)

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        source_result = store.find(
            (SourcePackagePublishingHistory, LibraryFileAlias,
             LibraryFileContent),
            LibraryFileContent.id == LibraryFileAlias.contentID,
            LibraryFileAlias.id == SourcePackageReleaseFile.libraryfileID,
            SourcePackageReleaseFile.sourcepackagerelease ==
                SourcePackagePublishingHistory.sourcepackagereleaseID,
            In(SourcePackagePublishingHistory.id, source_publication_ids))

        binary_result = store.find(
            (SourcePackagePublishingHistory, LibraryFileAlias,
             LibraryFileContent),
            LibraryFileContent.id == LibraryFileAlias.contentID,
            LibraryFileAlias.id == BinaryPackageFile.libraryfileID,
            BinaryPackageFile.binarypackagerelease ==
                BinaryPackageRelease.id,
            BinaryPackageRelease.buildID == Build.id,
            SourcePackagePublishingHistory.sourcepackagereleaseID ==
                Build.sourcepackagereleaseID,
            BinaryPackagePublishingHistory.binarypackagereleaseID ==
                BinaryPackageRelease.id,
            BinaryPackagePublishingHistory.archiveID ==
                SourcePackagePublishingHistory.archiveID,
            In(SourcePackagePublishingHistory.id, source_publication_ids))

        result_set = source_result.union(
            binary_result.config(distinct=True))

        return result_set

    def getBinaryPublicationsForSources(
        self, one_or_more_source_publications):
        """See `IPublishingSet`."""
        # Import Build, BinaryPackageRelease and DistroArchSeries locally
        # to avoid circular imports, since Build uses
        # SourcePackagePublishingHistory, BinaryPackageRelease uses Build
        # and DistroArchSeries uses BinaryPackagePublishingHistory.
        from canonical.launchpad.database.binarypackagerelease import (
            BinaryPackageRelease)
        from canonical.launchpad.database.build import Build
        from canonical.launchpad.database.distroarchseries import (
            DistroArchSeries)

        source_publication_ids = self._extractIDs(
            one_or_more_source_publications)

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result_set = store.find(
            (SourcePackagePublishingHistory, BinaryPackagePublishingHistory,
             BinaryPackageRelease, BinaryPackageName, DistroArchSeries),
            SourcePackagePublishingHistory.sourcepackagereleaseID ==
                Build.sourcepackagereleaseID,
            BinaryPackageRelease.build == Build.id,
            BinaryPackageRelease.binarypackagenameID ==
                BinaryPackageName.id,
            SourcePackagePublishingHistory.distroseriesID ==
                DistroArchSeries.distroseriesID,
            BinaryPackagePublishingHistory.distroarchseriesID ==
                DistroArchSeries.id,
            BinaryPackagePublishingHistory.binarypackagerelease ==
                BinaryPackageRelease.id,
            BinaryPackagePublishingHistory.pocket ==
               SourcePackagePublishingHistory.pocket,
            BinaryPackagePublishingHistory.archiveID ==
               SourcePackagePublishingHistory.archiveID,
            In(BinaryPackagePublishingHistory.status,
               [enum.value for enum in active_publishing_status]),
            In(SourcePackagePublishingHistory.id, source_publication_ids))

        result_set.order_by(
            SourcePackagePublishingHistory.id,
            BinaryPackageName.name,
            DistroArchSeries.architecturetag,
            Desc(BinaryPackagePublishingHistory.id))

        return result_set

    def getPackageDiffsForSources(self, one_or_more_source_publications):
        """See `PublishingSet`."""
        source_publication_ids = self._extractIDs(
            one_or_more_source_publications)
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = (
            SourcePackagePublishingHistory,
            PackageDiff,
            LeftJoin(LibraryFileAlias,
                     LibraryFileAlias.id == PackageDiff.diff_contentID),
            LeftJoin(LibraryFileContent,
                     LibraryFileContent.id == LibraryFileAlias.contentID),
            )
        result_set = store.using(*origin).find(
            (SourcePackagePublishingHistory, PackageDiff,
             LibraryFileAlias, LibraryFileContent),
            SourcePackagePublishingHistory.sourcepackagereleaseID ==
                PackageDiff.to_sourceID,
            In(SourcePackagePublishingHistory.id, source_publication_ids))

        result_set.order_by(
            SourcePackagePublishingHistory.id,
            Desc(PackageDiff.date_requested))

        return result_set

    def getChangesFilesForSources(
        self, one_or_more_source_publications):
        """See `IPublishingSet`."""
        # Import PackageUpload and PackageUploadSource locally
        # to avoid circular imports, since PackageUpload uses
        # {Secure}SourcePackagePublishingHistory.
        from canonical.launchpad.database.sourcepackagerelease import (
            SourcePackageRelease)
        from canonical.launchpad.database.queue import (
            PackageUpload, PackageUploadSource)

        source_publication_ids = self._extractIDs(
            one_or_more_source_publications)

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result_set = store.find(
            (SourcePackagePublishingHistory, PackageUpload,
             SourcePackageRelease, LibraryFileAlias, LibraryFileContent),
            LibraryFileContent.id == LibraryFileAlias.contentID,
            LibraryFileAlias.id == PackageUpload.changesfileID,
            PackageUpload.id == PackageUploadSource.packageuploadID,
            PackageUpload.status == PackageUploadStatus.DONE,
            PackageUpload.distroseriesID ==
                SourcePackageRelease.upload_distroseriesID,
            PackageUploadSource.sourcepackagereleaseID ==
                SourcePackageRelease.id,
            SourcePackageRelease.id ==
                SourcePackagePublishingHistory.sourcepackagereleaseID,
            In(SourcePackagePublishingHistory.id, source_publication_ids))

        result_set.order_by(SourcePackagePublishingHistory.id)
        return result_set

    def getBuildStatusSummariesForSourceIdsAndArchive(self,
                                                      source_ids,
                                                      archive):
        """See `IPublishingSet`."""
        # source_ids can be None or an empty sequence.
        if not source_ids:
            return {}

        # Get the builds for all the requested sources.
        result_set = self.getBuildsForSourceIds(source_ids, archive=archive)

        # Populate the list of builds for each id in a dict.
        source_builds = {}
        for src_pub, build, distroarchseries in result_set:
            source_builds.setdefault(src_pub.id, []).append(build)

        # Gset the overall build status for each source's builds.
        build_set = getUtility(IBuildSet)
        source_build_statuses = {}
        for source_id, builds in source_builds.items():
            status_summary = build_set.getStatusSummaryForBuilds(builds)
            source_build_statuses[source_id] = status_summary

        return source_build_statuses

    def requestDeletion(self, sources, removed_by, removal_comment=None):
        """See `IPublishingSet`."""

        # The 'sources' parameter could actually be any kind of sequence
        # (e.g. even a ResultSet) and the method would still work correctly.
        # This is problematic when it comes to the type of the return value
        # however.
        # Apparently the caller anticipates that we return the sequence of
        # instances "deleted" adhering to the original type of the 'sources'
        # parameter.
        # Since this is too messy we prescribe that the type of 'sources'
        # must be a list and we return the instances manipulated as a list.
        # This may not be an ideal solution but this way we at least achieve
        # consistency.
        assert isinstance(sources, list), (
            "The 'sources' parameter must be a list.")

        if len(sources) == 0:
            return []

        # The following piece of query "boiler plate" will be used for
        # both the source and the binary package publishing history table.
        query_boilerplate = '''
            SET status = %s,
                datesuperseded = %s,
                removed_by = %s,
                removal_comment = %s
            WHERE id IN
            ''' % sqlvalues(PackagePublishingStatus.DELETED, UTC_NOW,
                            removed_by, removal_comment)

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)

        # First update the source package publishing history table.
        source_ids = [source.id for source in sources]
        if len(source_ids) > 0:
            query = 'UPDATE SourcePackagePublishingHistory '
            query += query_boilerplate
            query += ' %s' % sqlvalues(source_ids)
            store.execute(query)

        # Prepare the list of associated *binary* packages publishing
        # history records.
        binary_packages = []
        for source in sources:
            binary_packages.extend(source.getPublishedBinaries())

        if len(binary_packages) == 0:
            return sources

        # Now run the query that marks the binary packages as deleted
        # as well.
        if len(binary_packages) > 0:
            query = 'UPDATE BinaryPackagePublishingHistory '
            query += query_boilerplate
            query += ' %s' % sqlvalues(
                [binary.id for binary in binary_packages])
            store.execute(query)

        return sources + binary_packages
