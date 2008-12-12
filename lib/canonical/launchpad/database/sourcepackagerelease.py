# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'SourcePackageRelease',
    '_filter_ubuntu_translation_file',
    ]

import datetime
import operator
import pytz
from StringIO import StringIO
import re

from zope.interface import implements
from zope.component import getUtility

from sqlobject import StringCol, ForeignKey, SQLMultipleJoin

from canonical.cachedproperty import cachedproperty

from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, cursor, sqlvalues

from canonical.librarian.interfaces import ILibrarianClient

from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.archive import (
    ArchivePurpose, IArchiveSet, MAIN_ARCHIVE_PURPOSES)
from canonical.launchpad.interfaces.build import BuildStatus
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.packagediff import (
    PackageDiffAlreadyRequested)
from canonical.launchpad.interfaces.package import PackageUploadStatus
from canonical.launchpad.interfaces.publishing import PackagePublishingStatus
from canonical.launchpad.interfaces.sourcepackage import (
    SourcePackageFileType, SourcePackageFormat, SourcePackageUrgency)
from canonical.launchpad.interfaces.sourcepackagerelease import (
    ISourcePackageRelease)
from canonical.launchpad.interfaces.translationimportqueue import (
    ITranslationImportQueue)

from canonical.launchpad.database.build import Build
from canonical.launchpad.database.files import SourcePackageReleaseFile
from canonical.launchpad.database.packagediff import PackageDiff
from canonical.launchpad.validators.person import validate_public_person
from canonical.launchpad.database.publishing import (
    SourcePackagePublishingHistory)
from canonical.launchpad.database.queue import PackageUpload
from canonical.launchpad.scripts.queue import QueueActionError
from canonical.launchpad.webapp.interfaces import NotFoundError


def _filter_ubuntu_translation_file(filename):
    """Filter for translation filenames in tarball.
    
    Grooms filenames of translation files in tarball, returning None or
    empty string for files that should be ignored.

    Passed to `ITranslationImportQueue.addOrUpdateEntriesFromTarball`.
    """
    source_prefix = 'source/'
    if not filename.startswith(source_prefix):
        return None

    filename = filename[len(source_prefix):]

    if filename.startswith('debian/po/'):
        # Skip filenames in debian/po/*.  They're from debconf
        # translations, which are treated separately in Ubuntu.
        return None

    return filename


class SourcePackageRelease(SQLBase):
    implements(ISourcePackageRelease)
    _table = 'SourcePackageRelease'

    section = ForeignKey(foreignKey='Section', dbName='section')
    creator = ForeignKey(
        dbName='creator', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    component = ForeignKey(foreignKey='Component', dbName='component')
    sourcepackagename = ForeignKey(foreignKey='SourcePackageName',
        dbName='sourcepackagename', notNull=True)
    maintainer = ForeignKey(
        dbName='maintainer', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    dscsigningkey = ForeignKey(foreignKey='GPGKey', dbName='dscsigningkey')
    urgency = EnumCol(dbName='urgency', schema=SourcePackageUrgency,
        default=SourcePackageUrgency.LOW, notNull=True)
    dateuploaded = UtcDateTimeCol(dbName='dateuploaded', notNull=True,
        default=UTC_NOW)
    dsc = StringCol(dbName='dsc')
    copyright = StringCol(dbName='copyright', notNull=False, default=DEFAULT)
    version = StringCol(dbName='version', notNull=True)
    changelog_entry = StringCol(dbName='changelog_entry')
    builddepends = StringCol(dbName='builddepends')
    builddependsindep = StringCol(dbName='builddependsindep')
    build_conflicts = StringCol(dbName='build_conflicts')
    build_conflicts_indep = StringCol(dbName='build_conflicts_indep')
    architecturehintlist = StringCol(dbName='architecturehintlist')
    format = EnumCol(dbName='format', schema=SourcePackageFormat,
        default=SourcePackageFormat.DPKG, notNull=True)
    upload_distroseries = ForeignKey(foreignKey='DistroSeries',
        dbName='upload_distroseries')
    upload_archive = ForeignKey(
        foreignKey='Archive', dbName='upload_archive', notNull=True)

    # XXX cprov 2006-09-26: Those fields are set as notNull and required in
    # ISourcePackageRelease, however they can't be not NULL in DB since old
    # records doesn't satisfy this condition. We will sort it before using
    # 'NoMoreAptFtparchive' implementation for PRIMARY archive. For PPA
    # (primary target) we don't need to populate old records.
    dsc_maintainer_rfc822 = StringCol(dbName='dsc_maintainer_rfc822')
    dsc_standards_version = StringCol(dbName='dsc_standards_version')
    dsc_format = StringCol(dbName='dsc_format')
    dsc_binaries = StringCol(dbName='dsc_binaries')

    # MultipleJoins
    files = SQLMultipleJoin('SourcePackageReleaseFile',
        joinColumn='sourcepackagerelease', orderBy="libraryfile")
    publishings = SQLMultipleJoin('SourcePackagePublishingHistory',
        joinColumn='sourcepackagerelease', orderBy="-datecreated")
    package_diffs = SQLMultipleJoin(
        'PackageDiff', joinColumn='to_source', orderBy="-date_requested")


    @property
    def builds(self):
        """See `ISourcePackageRelease`."""
        # Excluding PPA builds may seem like a strange thing to do but
        # when copy-package works for copying packages across archives,
        # a build may well have a different archive to the corresponding
        # sourcepackagerelease.
        return Build.select("""
            sourcepackagerelease = %s AND
            archive.id = build.archive AND
            archive.purpose IN %s
            """ % sqlvalues(self.id, MAIN_ARCHIVE_PURPOSES),
            orderBy=['-datecreated', 'id'],
            clauseTables=['Archive'])

    @property
    def age(self):
        """See ISourcePackageRelease."""
        now = datetime.datetime.now(pytz.timezone('UTC'))
        return now - self.dateuploaded

    @property
    def latest_build(self):
        builds = self._cached_builds
        if len(builds) > 0:
            return builds[0]
        return None

    def failed_builds(self):
        return [build for build in self._cached_builds
                if build.buildstate == BuildStatus.FAILEDTOBUILD]

    @property
    def needs_building(self):
        for build in self._cached_builds:
            if build.buildstate in [BuildStatus.NEEDSBUILD,
                                    BuildStatus.MANUALDEPWAIT,
                                    BuildStatus.CHROOTWAIT]:
                return True
        return False

    @cachedproperty
    def _cached_builds(self):
        # The reason we have this as a cachedproperty is that all the
        # *build* methods here need access to it; better not to
        # recalculate it multiple times.
        return list(self.builds)

    @property
    def name(self):
        return self.sourcepackagename.name

    @property
    def sourcepackage(self):
        """See ISourcePackageRelease."""
        # By supplying the sourcepackagename instead of its string name,
        # we avoid doing an extra query doing getSourcepackage.
        # XXX 2008-06-16 mpt bug=241298: cprov says this property "won't be as
        # useful as it looks once we start supporting derivation ... [It] is
        # dangerous and should be renamed (or removed)".
        series = self.upload_distroseries
        return series.getSourcePackage(self.sourcepackagename)

    @property
    def distrosourcepackage(self):
        """See ISourcePackageRelease."""
        # By supplying the sourcepackagename instead of its string name,
        # we avoid doing an extra query doing getSourcepackage
        distribution = self.upload_distroseries.distribution
        return distribution.getSourcePackage(self.sourcepackagename)

    @property
    def title(self):
        return '%s - %s' % (self.sourcepackagename.name, self.version)

    @property
    def productrelease(self):
        """See ISourcePackageRelease."""
        series = None

        # Use any published source package to find the product series.
        # We can do this because if we ever find out that a source package
        # release in two product series, we've almost certainly got a data
        # problem there.
        publishings = SourcePackagePublishingHistory.select(
            """
            sourcepackagerelease = %s AND
            status = %s
            """ % sqlvalues(self, PackagePublishingStatus.PUBLISHED))

        for publishing in publishings:
            # imports us, so avoid circular import
            from canonical.launchpad.database.sourcepackage import \
                 SourcePackage
            # Only process main archives and skip PPA/copy archives.
            if publishing.archive.purpose not in MAIN_ARCHIVE_PURPOSES:
                continue
            sp = SourcePackage(self.sourcepackagename,
                               publishing.distroseries)
            sp_series = sp.productseries
            if sp_series is not None:
                if series is None:
                    series = sp_series
                elif series != sp_series:
                    # XXX: keybuk 2005-06-22: We could warn about this.
                    pass

        # No series -- no release
        if series is None:
            return None

        # XXX: keybuk 2005-06-22:
        # Find any release with the exact same version, or which
        # we begin with and after a dash.  We could be more intelligent
        # about this, but for now this will work for most.
        for release in series.releases:
            if release.version == self.version:
                return release
            elif self.version.startswith("%s-" % release.version):
                return release
        else:
            return None

    @property
    def current_publishings(self):
        """See ISourcePackageRelease."""
        from canonical.launchpad.database.distroseriessourcepackagerelease \
            import DistroSeriesSourcePackageRelease
        return [DistroSeriesSourcePackageRelease(pub.distroseries, self)
                for pub in self.publishings]

    @property
    def published_archives(self):
        """See `ISourcePacakgeRelease`."""
        archives = set()
        publishings = self.publishings.prejoin(['archive'])
        live_states = (PackagePublishingStatus.PENDING,
                       PackagePublishingStatus.PUBLISHED)
        for pub in publishings:
            if pub.status in live_states:
                archives.add(pub.archive)

        return sorted(archives, key=operator.attrgetter('id'))

    @cachedproperty
    def _cached_published_archives(self):
        """Return a cached list of published archives.

        This is intended for the security adapter as it calls
        published_archives a lot which makes private PPA index pages
        unrenderable in the timeout allowed if they have more than a
        handful of packages.

        XXX Julian 2008-09-10
        This code should be removed when security adapter caching is done.
        See bug 268612.
        """
        return self.published_archives

    def addFile(self, file):
        """See ISourcePackageRelease."""
        determined_filetype = None
        if file.filename.endswith(".dsc"):
            determined_filetype = SourcePackageFileType.DSC
        elif file.filename.endswith(".orig.tar.gz"):
            determined_filetype = SourcePackageFileType.ORIG
        elif file.filename.endswith(".diff.gz"):
            determined_filetype = SourcePackageFileType.DIFF
        elif file.filename.endswith(".tar.gz"):
            determined_filetype = SourcePackageFileType.TARBALL

        return SourcePackageReleaseFile(sourcepackagerelease=self,
                                        filetype=determined_filetype,
                                        libraryfile=file)


    def _getPackageSize(self):
        """Get the size total (in KB) of files comprising this package.
        
        Please note: empty packages (i.e. ones with no files or with
        files that are all empty) have a size of zero.
        """
        size_query = """
            SELECT
                SUM(LibraryFileContent.filesize)/1024.0
            FROM
                SourcePackagereLease
                JOIN SourcePackageReleaseFile ON
                    SourcePackageReleaseFile.sourcepackagerelease =
                    SourcePackageRelease.id
                JOIN LibraryFileAlias ON
                    SourcePackageReleaseFile.libraryfile = 
                    LibraryFileAlias.id
                JOIN LibraryFileContent ON
                    LibraryFileAlias.content = LibraryFileContent.id
            WHERE
                SourcePackageRelease.id = %s
            """ % sqlvalues(self)

        cur = cursor()
        cur.execute(size_query)
        results = cur.fetchone()

        if len(results) == 1 and results[0] is not None:
            return float(results[0])
        else:
            return 0.0

    def createBuild(self, distroarchseries, pocket, archive, processor=None,
                    status=None):
        """See ISourcePackageRelease."""
        # Guess a processor if one is not provided
        if processor is None:
            pf = distroarchseries.processorfamily
            # We guess at the first processor in the family
            processor = shortlist(pf.processors)[0]

        if status is None:
            status = BuildStatus.NEEDSBUILD

        # Force the current timestamp instead of the default
        # UTC_NOW for the transaction, avoid several row with
        # same datecreated.
        datecreated = datetime.datetime.now(pytz.timezone('UTC'))

        # Always include the primary archive when looking for
        # past build times (just in case that none can be found
        # in a PPA or copy archive).
        archives = [archive.id]
        if archive.purpose != ArchivePurpose.PRIMARY:
            archives.append(distroarchseries.main_archive.id)

        # Look for all sourcepackagerelease instances that match the name.
        matching_sprs = SourcePackageRelease.select("""
            SourcePackageName.name = %s AND
            SourcePackageRelease.sourcepackagename = SourcePackageName.id
            """ % sqlvalues(self.name),
            clauseTables=['SourcePackageName', 'SourcePackageRelease'])

        # Get the (successfully built) build records for this package.
        completed_builds = Build.select("""
            sourcepackagerelease IN %s AND
            distroarchseries = %s AND
            archive IN %s AND
            buildstate = %s
            """ % sqlvalues([spr.id for spr in matching_sprs],
                            distroarchseries, archives,
                            BuildStatus.FULLYBUILT),
            orderBy=['-datebuilt', '-id'])

        if completed_builds:
            # Historic build data exists, use the most recent value.
            most_recent_build = completed_builds[0]
            estimated_build_duration = most_recent_build.buildduration
        else:
            # Estimate the build duration based on package size if no
            # historic build data exists.

            # Get the package size in KB.
            package_size = self._getPackageSize()

            if package_size > 0:
                # Analysis of previous build data shows that a build rate
                # of 6 KB/second is realistic. Furthermore we have to add
                # another minute for generic build overhead.
                estimate = int(package_size/6.0/60 + 1)
            else:
                # No historic build times and no package size available,
                # assume a build time of 5 minutes.
                estimate = 5
            estimated_build_duration = datetime.timedelta(minutes=estimate)

        return Build(distroarchseries=distroarchseries,
                     sourcepackagerelease=self,
                     processor=processor,
                     buildstate=status,
                     datecreated=datecreated,
                     pocket=pocket,
                     estimated_build_duration=estimated_build_duration,
                     archive=archive)

    def getBuildByArch(self, distroarchseries, archive):
        """See ISourcePackageRelease."""
        # First we try to follow any binaries built from the given source
        # in a distroarchseries with the given architecturetag and published
        # in the given (distroarchseries, archive) location.
        clauseTables = [
            'BinaryPackagePublishingHistory', 'BinaryPackageRelease',
            'DistroArchSeries']

        query = """
            Build.sourcepackagerelease = %s AND
            BinaryPackageRelease.build = Build.id AND
            DistroArchSeries.id = Build.distroarchseries AND
            DistroArchSeries.architecturetag = %s AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackagePublishingHistory.distroarchseries = %s AND
            BinaryPackagePublishingHistory.archive = %s
        """ % sqlvalues(self, distroarchseries.architecturetag,
                        distroarchseries, archive)

        select_results = Build.select(
            query, clauseTables=clauseTables, distinct=True,
            orderBy='-Build.id')

        # XXX cprov 20080216: this if/elif/else block could be avoided or,
        # at least, simplified if SelectOne accepts 'distinct' argument.
        # The query above results in multiple identical builds for ..
        results = list(select_results)
        if len(results) == 1:
            # If there was any published binary we can use its original build.
            # This case covers the situations when both, source and binaries
            # got copied from another location.
            return results[0]
        elif len(results) > 1:
            # If more than one distinct build was found we have a problem.
            # A build was created when it shouldn't, possible due to bug
            # #181736. The broken build should be manually removed.
            raise AssertionError(
                    "Found more than one build candidate: %s. It possibly "
                    "means we have a serious problem in out DB model, "
                    "further investigation is required." %
                    [build.id for build in results])
        else:
            # If there was no published binary we have to try to find a
            # suitable build in all possible location across the distroseries
            # inheritance tree. See bellow.
            pass

        queries = ["Build.sourcepackagerelease = %s" % sqlvalues(self)]

        # Find out all the possible parent DistroArchSeries
        # a build could be issued (then inherited).
        parent_architectures = []
        archtag = distroarchseries.architecturetag

        if archive.purpose in MAIN_ARCHIVE_PURPOSES:
            # XXX cprov 20070720: this code belongs to IDistroSeries content
            # class as 'parent_series' property. Other parts of the system
            # can benefit of this, like SP.packagings, for instance.
            parent_series = []
            candidate = distroarchseries.distroseries
            while candidate is not None:
                parent_series.append(candidate)
                candidate = candidate.parent_series

            for series in parent_series:
                try:
                    candidate = series[archtag]
                except NotFoundError:
                    pass
                else:
                    parent_architectures.append(candidate)
            # end-of-XXX.
        else:
            parent_architectures.append(distroarchseries)

        architectures = [
            architecture.id for architecture in parent_architectures]
        queries.append(
            "Build.distroarchseries IN %s" % sqlvalues(architectures))

        # Follow archive inheritance across distribution offical archives,
        # for example:
        # guadalinex/foobar/PRIMARY was initialised from ubuntu/dapper/PRIMARY
        # guadalinex/foobar/PARTNER was initialised from ubuntu/dapper/PARTNER
        # and so on
        if archive.purpose in MAIN_ARCHIVE_PURPOSES:
            parent_archives = set()
            archive_set = getUtility(IArchiveSet)
            for series in parent_series:
                target_archive = archive_set.getByDistroPurpose(
                    series.distribution, archive.purpose)
                parent_archives.add(target_archive)
            archives = [archive.id for archive in parent_archives]
        else:
            archives = [archive.id, ]

        queries.append(
            "Build.archive IN %s" % sqlvalues(archives))

        # Query only the last build record for this sourcerelease
        # across all possible locations.
        query = " AND ".join(queries)

        return Build.selectFirst(query, orderBy=['-datecreated'])

    def override(self, component=None, section=None, urgency=None):
        """See ISourcePackageRelease."""
        if component is not None:
            self.component = component
            # See if the new component requires a new archive:
            distribution = self.upload_distroseries.distribution
            new_archive = distribution.getArchiveByComponent(component.name)
            if new_archive is not None:
                self.upload_archive = new_archive
            else:
                raise QueueActionError(
                    "New component '%s' requires a non-existent archive.")
        if section is not None:
            self.section = section
        if urgency is not None:
            self.urgency = urgency

    @property
    def upload_changesfile(self):
        """See `ISourcePackageRelease`."""
        queue_record = self.getQueueRecord()
        if not queue_record:
            return None

        return queue_record.changesfile

    def getQueueRecord(self, distroseries=None):
        """See `ISourcepackageRelease`."""
        if distroseries is None:
            distroseries = self.upload_distroseries

        clauseTables = [
            'PackageUpload',
            'PackageUploadSource',
            ]
        preJoins = ['changesfile']
        query = """
        PackageUpload.id = PackageUploadSource.packageupload AND
        PackageUpload.distroseries = %s AND
        PackageUploadSource.sourcepackagerelease = %s AND
        PackageUpload.status = %s
        """ % sqlvalues(distroseries, self, PackageUploadStatus.DONE)
        return PackageUpload.selectOne(
            query, clauseTables=clauseTables, prejoins=preJoins)

    @property
    def change_summary(self):
        """See ISourcePackageRelease"""
        # this regex is copied from apt-listchanges.py courtesy of MDZ
        new_stanza_line = re.compile(
            '^\S+ \((?P<version>.*)\) .*;.*urgency=(?P<urgency>\w+).*')
        logfile = StringIO(self.changelog_entry)
        change = ''
        top_stanza = False
        for line in logfile.readlines():
            match = new_stanza_line.match(line)
            if match:
                if top_stanza:
                    break
                top_stanza = True
            change += line

        return change

    def attachTranslationFiles(self, tarball_alias, is_published,
        importer=None):
        """See ISourcePackageRelease."""
        client = getUtility(ILibrarianClient)

        tarball_file = client.getFileByAlias(tarball_alias.id)
        tarball = tarball_file.read()

        if importer is None:
            importer = getUtility(ILaunchpadCelebrities).rosetta_experts

        queue = getUtility(ITranslationImportQueue)

        queue.addOrUpdateEntriesFromTarball(
            tarball, is_published, importer,
            sourcepackagename=self.sourcepackagename,
            distroseries=self.upload_distroseries,
            filename_filter=_filter_ubuntu_translation_file)

    def getDiffTo(self, to_sourcepackagerelease):
        """See ISourcePackageRelease."""
        return PackageDiff.selectOneBy(
            from_source=self, to_source=to_sourcepackagerelease)

    def requestDiffTo(self, requester, to_sourcepackagerelease):
        """See ISourcePackageRelease."""
        candidate = self.getDiffTo(to_sourcepackagerelease)

        if candidate is not None:
            raise PackageDiffAlreadyRequested(
                "%s was already requested by %s"
                % (candidate.title, candidate.requester.displayname))

        return PackageDiff(
            from_source=self, to_source=to_sourcepackagerelease,
            requester=requester)
