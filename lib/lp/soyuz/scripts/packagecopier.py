# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
"""PackageCopier utilities."""

__metaclass__ = type

__all__ = [
    'CannotCopy',
    'PackageCopier',
    'UnembargoSecurityPackage',
    'check_copy',
    'do_copy',
    ]

import apt_pkg
import os
import tempfile

from zope.component import getUtility

from canonical.launchpad.interfaces.launchpad import NotFoundError
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.librarian.utils import copy_and_close
from lp.soyuz.adapters.packagelocation import (
    build_package_location)
from lp.soyuz.interfaces.archive import (
    ArchivePurpose, CannotCopy)
from lp.soyuz.interfaces.build import incomplete_building_status
from lp.soyuz.interfaces.publishing import (
    IBinaryPackagePublishingHistory, ISourcePackagePublishingHistory,
    PackagePublishingStatus, active_publishing_status)
from lp.soyuz.scripts.ftpmasterbase import (
    SoyuzScript, SoyuzScriptError)
from lp.soyuz.scripts.processaccepted import (
    close_bugs_for_sourcepublication)


def is_completely_built(source):
    """Whether or not a source publication is completely built.

    Check if all builds have quiesced before copying.
    :param source: context `ISourcePackagePublishingHistory`.

    :return: False if there is, at least, one incomplete build, True
        otherwise.
    """
    for build in source.getBuilds():
        if build.buildstate in incomplete_building_status:
            return False

    return True


def has_unpublished_binaries(source):
    """Whether or not a source publication has unpublished binaries.

    Check if there are binaries built from the source in the same
    publication context. If there are none, return False since there is
    nothing to be published.

    If there are built binaries, check if they match the ones published
    for the source in its context.

    :param source: context `ISourcePackagePublishingHistory`.

    :return: True if there are unpublished binaries, False otherwise.
    """
    # Binaries built from this source in the publishing context.
    built_binaries = set()
    for build in source.getBuilds():
        if source.pocket != build.pocket:
            continue
        for binarypackagerelease in build.binarypackages:
            built_binaries.add(binarypackagerelease)

    # No binaries built, thus none unpublished.
    if len(built_binaries) == 0:
        return False

    # Binaries have been published in the same publishing context,
    # but are some not yet published?
    candidate_binaries = set(
        pub_binary.binarypackagerelease
        for pub_binary in source.getBuiltBinaries())
    if candidate_binaries != built_binaries:
        return True

    return False


def compare_sources(source, ancestry):
    """Compare `ISourcePackagePublishingHistory` records versions.

    :param source: context `ISourcePackagePublishingHistory`;
    :param ancestry: ancestry `ISourcePackagePublishingHistory`.

    :return: `apt_pkg.VersionCompare(source_version, ancestry_version)`
        which uses the behaviour as python cmp(); 1 if source_version >
        ancestry_version, 0 if source_version == ancestry_version, -1 if
        source_version < ancestry_version.
    """
    ancestry_version = ancestry.sourcepackagerelease.version
    copy_version = source.sourcepackagerelease.version
    apt_pkg.InitSystem()
    return apt_pkg.VersionCompare(copy_version, ancestry_version)


def get_ancestry_candidate(source, archive, series, pocket):
    """Find a ancestry candidate in the give location.

    Look for the newest active source publication in the location (archive,
    series, pocket) with the same name as the given source.

    :param source: context `ISourcePackagePublishingHistory`;
    :param archive: destination `IArchive`;
    :param series: destination `IDistroSeries`;
    :param pocket: destination `PackagePublishingPocket`.

    :return: the corresponding `ISourcePackagePublishingHistory` record if
        it was found or None.
    """
    destination_series_ancestries = archive.getPublishedSources(
        name=source.sourcepackagerelease.name, exact_match=True,
        pocket=pocket, distroseries=series,
        status=active_publishing_status)

    if destination_series_ancestries.count() == 0:
        return None

    ancestry = destination_series_ancestries[0]
    return ancestry


def check_archive_conflicts(source, archive, series, include_binaries):
    """Check for possible conflicts in the destination archive.

    Check if there is a source with the same name and version published
    in the destination archive. If it exists (regardless of the series
    and pocket) and it has built or will build binaries, do not copy
    without binaries. This is because the copied source will rebuild
    binaries that conflict with existing ones. Even when the binaries
    are included, they are checked for conflict.

    :param source: context `ISourcePackagePublishingHistory`;
    :param archive: destination `IArchive`.
    :param series: destination `IDistroSeries`.
    :param include_binaries: boolean indicating whether or not binaries
        are considered in the copy.

    :raise CannotCopy: when a copy is not allowed to be performed
        containing the reason of the error.
    """
    destination_archive_conflicts = archive.getPublishedSources(
        name=source.sourcepackagerelease.name,
        version=source.sourcepackagerelease.version,
        status=active_publishing_status,
        exact_match=True)

    if destination_archive_conflicts.count() == 0:
        return

    # Cache the conflicting publication because they will be iterated
    # more than once.
    destination_archive_conflicts = list(destination_archive_conflicts)

    # Identify published binaries and incomplete builds or unpublished
    # binaries from archive conflicts. Either will deny source-only copies,
    # since a rebuild will result in binaries that cannot be published in
    # the archive because they will conflict with the existent ones.
    published_binaries = set()
    for candidate in destination_archive_conflicts:

        # If the candidate refers to a different sourcepackagerelease with
        # the same name and version there is a high chance that they have
        # conflicting files that cannot be published in the repository pool.
        # So, we deny the copy until the existing source gets deleted (and
        # removed from the archive).
        if (source.sourcepackagerelease.id !=
            candidate.sourcepackagerelease.id):
            raise CannotCopy(
                'a different source with the same version is published '
                'in the destination archive')

        # If the conflicting candidate (which we already know refer to the
        # same sourcepackagerelease) was found in the copy destination
        # series we don't have to check its building status, because it's
        # not going to change in terms of new builds and the resulting
        # binaries will match. See more details in
        # `ISourcePackageRelease.getBuildsByArch`.
        if candidate.distroseries.id == series.id:
            continue

        # Conflicting candidates building in a different series are a
        # blocker for the copy. The copied source will certainly produce
        # conflicting binaries.
        if not is_completely_built(candidate):
            raise CannotCopy(
                "same version already building in the destination archive "
                "for %s" % candidate.distroseries.displayname)

        # If the set of built binaries does not match the set of published
        # ones the copy should be denied and the user should wait for the
        # next publishing cycle to happen before copying the package.
        # The copy is only allowed when all built binaries are published,
        # this way there is no chance of a conflict.
        if has_unpublished_binaries(candidate):
            raise CannotCopy(
                "same version has unpublished binaries in the destination "
                "archive for %s, please wait for them to be published "
                "before copying" % candidate.distroseries.displayname)

        # Update published binaries inventory for the conflicting candidates.
        archive_binaries = set(
            pub_binary.binarypackagerelease.id
            for pub_binary in candidate.getPublishedBinaries())
        published_binaries.update(archive_binaries)

    if not include_binaries:
        if len(published_binaries) > 0:
            raise CannotCopy(
                "same version already has published binaries in the "
                "destination archive")
    else:
        # Since DEB files are compressed with 'ar' (encoding the creation
        # timestamp) and serially built by our infrastructure, it's correct
        # to assume that the set of BinaryPackageReleases being copied can
        # only be a superset of the set of BinaryPackageReleases published
        # in the destination archive.
        copied_binaries = set(
            pub.binarypackagerelease.id for pub in source.getBuiltBinaries())
        if not copied_binaries.issuperset(published_binaries):
            raise CannotCopy("binaries conflicting with the existing ones")


def check_privacy_mismatch(source, archive):
    """Whether or not source files match the archive privacy.

    Public source files can be copied to any archive, it does not
    represent a 'privacy mismatch'.

    On the other hand, private source files can be copied to private
    archives where builders will fetch it directly from the repository
    and not from the restricted librarian.
    """
    if archive.private:
        return False

    for source_file in source.sourcepackagerelease.files:
        if source_file.libraryfile.restricted:
            return True

    return False


def check_copy(source, archive, series, pocket, include_binaries,
               deny_privacy_mismatch=True):
    """Check if the source can be copied to the given location.

    Check possible conflicting publications in the destination archive.
    See `check_archive_conflicts()`.

    Also checks if the version of the source being copied is equal or higher
    than any version of the same source present in the destination suite
    (series + pocket).

    :param source: context `ISourcePackagePublishingHistory`;
    :param archive: destination `IArchive`;
    :param series: destination `IDistroSeries`;
    :param pocket: destination `PackagePublishingPocket`.
    :param include_binaries: boolean indicating whether or not binaries
        are considered in the copy.
    :param deny_privacy_mismatch: boolean indicating whether or not private
        sources can be copied to public archives. Defaults to True, only
        set as False in the UnembargoPackage context.

    :raise CannotCopy when a copy is not allowed to be performed
        containing the reason of the error.
    """
    if series is None:
        series = source.distroseries

    if deny_privacy_mismatch and check_privacy_mismatch(source, archive):
        raise CannotCopy("Cannot copy private source into public archives.")

    if include_binaries:
        if len(source.getBuiltBinaries()) == 0:
            raise CannotCopy("source has no binaries to be copied")

    # Check if there is already a source with the same name and version
    # published in the destination archive.
    check_archive_conflicts(source, archive, series, include_binaries)

    ancestry = get_ancestry_candidate(source, archive, series, pocket)
    if ancestry is not None and compare_sources(source, ancestry) < 0:
        raise CannotCopy(
            "version older than the %s published in %s" %
            (ancestry.displayname, ancestry.distroseries.name))


def do_copy(sources, archive, series, pocket, include_binaries=False):
    """Perform the complete copy of the given sources incrementally.

    Copy each item of the given list of `SourcePackagePublishingHistory`
    to the given destination if they are not yet available (previously
    copied).

    Also copy published binaries for each source if requested to. Again,
    only copy binaries that were not yet copied before.

    :param: sources: a list of `ISourcePackagePublishingHistory`;
    :param: archive: the target `IArchive`;
    :param: series: the target `IDistroSeries`, if None is given the same
        current source distroseries will be used as destination;
    :param: pocket: the target `PackagePublishingPocket`;
    :param: include_binaries: optional boolean, controls whether or
        not the published binaries for each given source should be also
        copied along with the source;
    :return: a list of `ISourcePackagePublishingHistory` and
        `BinaryPackagePublishingHistory` corresponding to the copied
        publications.
    """
    copies = []
    for source in sources:
        if series is None:
            destination_series = source.distroseries
        else:
            destination_series = series

        # Copy source if it's not yet copied.
        source_in_destination = archive.getPublishedSources(
            name=source.sourcepackagerelease.name, exact_match=True,
            version=source.sourcepackagerelease.version,
            status=active_publishing_status,
            distroseries=destination_series, pocket=pocket)
        if source_in_destination.count() == 0:
            source_copy = source.copyTo(destination_series, pocket, archive)
            close_bugs_for_sourcepublication(source_copy)
            copies.append(source_copy)
        else:
            source_copy = source_in_destination[0]

        if not include_binaries:
            source_copy.createMissingBuilds()
            continue

        # Copy missing suitable binaries.
        for binary in source.getBuiltBinaries():
            try:
                target_distroarchseries = destination_series[
                    binary.distroarchseries.architecturetag]
            except NotFoundError:
                # It is not an error if the destination series doesn't
                # support all the architectures originally built. We
                # simply do not copy the binary and life goes on.
                continue
            binary_in_destination = archive.getAllPublishedBinaries(
                name=binary.binarypackagerelease.name, exact_match=True,
                version=binary.binarypackagerelease.version,
                status=active_publishing_status, pocket=pocket,
                distroarchseries=target_distroarchseries)
            if binary_in_destination.count() == 0:
                binary_copy = binary.copyTo(
                        destination_series, pocket, archive)
                copies.extend(binary_copy)

        # Always ensure the needed builds exist in the copy destination
        # after copying the binaries.
        source_copy.createMissingBuilds()

    return copies


class PackageCopier(SoyuzScript):
    """SoyuzScript that copies published packages between locations.

    Possible exceptions raised are:
    * PackageLocationError: specified package or distro does not exist
    * PackageCopyError: the copy operation itself has failed
    * LaunchpadScriptFailure: only raised if entering via main(), ie this
        code is running as a genuine script.  In this case, this is
        also the _only_ exception to be raised.

    The test harness doesn't enter via main(), it calls doCopy(), so
    it only sees the first two exceptions.
    """

    usage = '%prog -s warty mozilla-firefox --to-suite hoary'
    description = 'MOVE or COPY a published package to another suite.'
    deny_privacy_mismatch = True

    def add_my_options(self):

        SoyuzScript.add_my_options(self)

        self.parser.add_option(
            "-b", "--include-binaries", dest="include_binaries",
            default=False, action="store_true",
            help='Whether to copy related binaries or not.')

        self.parser.add_option(
            '--to-distribution', dest='to_distribution',
            default='ubuntu', action='store',
            help='Destination distribution name.')

        self.parser.add_option(
            '--to-suite', dest='to_suite', default=None,
            action='store', help='Destination suite name.')

        self.parser.add_option(
            '--to-ppa', dest='to_ppa', default=None,
            action='store', help='Destination PPA owner name.')

        self.parser.add_option(
            '--to-ppa-name', dest='to_ppa_name', default='ppa',
            action='store', help='Destination PPA name.')

        self.parser.add_option(
            '--to-partner', dest='to_partner', default=False,
            action='store_true', help='Destination set to PARTNER archive.')

    def checkCopyOptions(self):
        """Check if the locations options are sane.

         * Catch Cross-PARTNER copies, they are not allowed.
         * Catch simulataneous PPA and PARTNER locations or destinations,
           results are unpredictable (in fact, the code will ignore PPA and
           operate only in PARTNER, but that's odd)
        """
        if ((self.options.partner_archive and not self.options.to_partner)
            or (self.options.to_partner and not
                self.options.partner_archive)):
            raise SoyuzScriptError(
                "Cross-PARTNER copies are not allowed.")

        if self.options.archive_owner_name and self.options.partner_archive:
            raise SoyuzScriptError(
                "Cannot operate with location PARTNER and PPA "
                "simultaneously.")

        if self.options.to_ppa and self.options.to_partner:
            raise SoyuzScriptError(
                "Cannot operate with destination PARTNER and PPA "
                "simultaneously.")

    def mainTask(self):
        """Execute package copy procedure.

        Copy source publication and optionally also copy its binaries by
        passing '-b' (include_binary) option.

        Modules using this class outside of its normal usage in the
        copy-package.py script can call this method to start the copy.

        In this case the caller can override test_args on __init__
        to set the command line arguments.

        Can raise SoyuzScriptError.
        """
        assert self.location, (
            "location is not available, call PackageCopier.setupLocation() "
            "before dealing with mainTask.")

        self.checkCopyOptions()

        sourcename = self.args[0]

        self.setupDestination()

        self.logger.info("FROM: %s" % (self.location))
        self.logger.info("TO: %s" % (self.destination))

        to_copy = []
        source_pub = self.findLatestPublishedSource(sourcename)
        to_copy.append(source_pub)
        if self.options.include_binaries:
            to_copy.extend(source_pub.getPublishedBinaries())

        self.logger.info("Copy candidates:")
        for candidate in to_copy:
            self.logger.info('\t%s' % candidate.displayname)

        try:
            check_copy(
                source_pub, self.destination.archive,
                self.destination.distroseries, self.destination.pocket,
                self.options.include_binaries, self.deny_privacy_mismatch)
        except CannotCopy, reason:
            self.logger.error(
                "%s (%s)" % (source_pub.displayname, reason))
            return []

        sources = [source_pub]
        copies = do_copy(
            sources, self.destination.archive, self.destination.distroseries,
            self.destination.pocket, self.options.include_binaries)

        if len(copies) == 1:
            self.logger.info(
                "%s package successfully copied." % len(copies))
        elif len(copies) > 1:
            self.logger.info(
                "%s packages successfully copied." % len(copies))
        else:
            self.logger.info("No packages copied.")

        # Information returned mainly for the benefit of the test harness.
        return copies

    def setupDestination(self):
        """Build PackageLocation for the destination context."""
        if self.options.to_partner:
            self.destination = build_package_location(
                self.options.to_distribution,
                self.options.to_suite,
                ArchivePurpose.PARTNER)
        elif self.options.to_ppa:
            self.destination = build_package_location(
                self.options.to_distribution,
                self.options.to_suite,
                ArchivePurpose.PPA,
                self.options.to_ppa,
                self.options.to_ppa_name)
        else:
            self.destination = build_package_location(
                self.options.to_distribution,
                self.options.to_suite)

        if self.location == self.destination:
            raise SoyuzScriptError(
                "Can not sync between the same locations: '%s' to '%s'" % (
                self.location, self.destination))


class UnembargoSecurityPackage(PackageCopier):
    """`SoyuzScript` that unembargoes security packages and their builds.

    Security builds are done in the ubuntu-security private PPA.
    When they are ready to be unembargoed, this script will copy
    them from the PPA to the Ubuntu archive and re-upload any files
    from the restricted librarian into the non-restricted one.

    This script simply wraps up PackageCopier with some nicer options,
    and implements the file re-uploading.

    An assumption is made, to reduce the number of command line options,
    that packages are always copied between the same distroseries.  The user
    can, however, select which target pocket to unembargo into.  This is
    useful to the security team when there are major version upgrades
    and they want to stage it through -proposed first for testing.
    """

    usage = ("%prog [-d <distribution>] [-s <suite>] [--ppa <private ppa>] "
             "<package(s)>")
    description = ("Unembargo packages in a private PPA by copying to the "
                   "specified location and re-uploading any files to the "
                   "unrestricted librarian.")
    deny_privacy_mismatch = False

    def add_my_options(self):
        """Add -d, -s, dry-run and confirmation options."""
        SoyuzScript.add_distro_options(self)
        SoyuzScript.add_transaction_options(self)

        self.parser.add_option(
            "-p", "--ppa", dest="archive_owner_name",
            default="ubuntu-security", action="store",
            help="Private PPA owner's name.")

        self.parser.add_option(
            "--ppa-name", dest="archive_name",
            default="ppa", action="store",
            help="Private PPA name.")

    def setUpCopierOptions(self):
        """Set up options needed by PackageCopier.

        :return: False if there is a problem with the options.
        """
        # Set up the options for PackageCopier that are needed in addition
        # to the ones that this class sets up.
        self.options.to_partner = False
        self.options.to_ppa = False
        self.options.partner_archive = None
        self.options.include_binaries = True
        self.options.to_distribution = self.options.distribution_name
        from_suite = self.options.suite.split("-")
        if len(from_suite) == 1:
            self.logger.error("Can't unembargo into the release pocket")
            return False
        else:
            # The PackageCopier parent class uses options.suite as the
            # source suite, so we need to override it to remove the
            # pocket since PPAs are pocket-less.
            self.options.to_suite = self.options.suite
            self.options.suite = from_suite[0]
        self.options.version = None
        self.options.component = None

        return True

    def mainTask(self):
        """Invoke PackageCopier to copy the package(s) and re-upload files."""
        if not self.setUpCopierOptions():
            return None

        # Generate the location for PackageCopier after overriding the
        # options.
        self.setupLocation()

        # Invoke the package copy operation.
        copies = PackageCopier.mainTask(self)

        # Do an ancestry check to override the component.
        self.overrideFromAncestry(copies)

        # Now re-upload the files associated with the package.
        for pub_record in copies:
            self.copyPublishedFiles(pub_record, False)

        # Return this for the benefit of the test suite.
        return copies

    def copyPublishedFiles(self, pub_record, to_restricted):
        """Move files for a publishing record between librarians.

        :param pub_record: One of a SourcePackagePublishingHistory or
            BinaryPackagePublishingHistory record.
        :param to_restricted: True or False depending on whether the target
            librarian to be used is the restricted one or not.
        """
        if ISourcePackagePublishingHistory.providedBy(pub_record):
            files = pub_record.sourcepackagerelease.files
            # Re-upload the changes file if necessary.
            sourcepackagerelease = pub_record.sourcepackagerelease
            queue_record = sourcepackagerelease.getQueueRecord(
                distroseries=pub_record.distroseries)
            if queue_record is not None:
                changesfile = queue_record.changesfile
            else:
                changesfile = None
            if changesfile is not None and changesfile.restricted:
                new_lfa = self.reUploadFile(changesfile, False)
                queue_record.changesfile = new_lfa
            # Re-upload the package diff files if necessary.
            diffs = sourcepackagerelease.package_diffs
            for diff in diffs:
                if diff.diff_content.restricted:
                    new_lfa = self.reUploadFile(diff.diff_content, False)
                    diff.diff_content = new_lfa
        elif IBinaryPackagePublishingHistory.providedBy(pub_record):
            files = pub_record.binarypackagerelease.files
            # Re-upload the binary changes file as necessary.
            upload = pub_record.binarypackagerelease.build.package_upload
            changesfile = upload.changesfile
            if changesfile is not None and changesfile.restricted:
                new_lfa = self.reUploadFile(changesfile, False)
                upload.changesfile = new_lfa
            # Re-upload the buildlog file as necessary.
            buildlog = pub_record.binarypackagerelease.build.buildlog
            if buildlog is not None and buildlog.restricted:
                new_lfa = self.reUploadFile(buildlog, False)
                pub_record.binarypackagerelease.build.buildlog = new_lfa
        else:
            raise AssertionError(
                "pub_record is not one of SourcePackagePublishingHistory "
                "or BinaryPackagePublishingHistory")

        for package_file in files:
            libfile = package_file.libraryfile
            # Check if the files are already in the right librarian
            # instance.
            if libfile.restricted == to_restricted:
                continue
            # Move the file to the appropriate librarian instance.
            new_lfa = self.reUploadFile(libfile, to_restricted)
            package_file.libraryfile = new_lfa

    def reUploadFile(self, libfile, to_restricted):
        """Re-upload a librarian file between librarians.

        :param libfile: A LibraryFileAlias for the file.
        :param to_restricted: True if copying to the restricted librarian.
        :return: A new LibraryFileAlias that is not restricted.
        """
        libfile.open()

        # Make a temporary file to hold the download.  It's annoying
        # having to download to a temp file but there are no guarantees
        # how large the files are, so using StringIO would be dangerous.
        fd, filepath = tempfile.mkstemp()
        temp_file = open(filepath, "w")

        # Read the old library file into the temp file.
        copy_and_close(libfile, temp_file)

        # Upload the file to the unrestricted librarian and make
        # sure the publishing record points to it.
        librarian = getUtility(ILibraryFileAliasSet)
        new_lfa = librarian.create(
            libfile.filename, libfile.content.filesize,
            open(filepath, "rb"), libfile.mimetype,
            restricted=to_restricted)

        self.logger.info(
            "Re-uploaded %s to the unrestricted librarian with ID %d" % (
                libfile.filename, new_lfa.id))

        # Junk the temporary file.
        os.remove(filepath)

        return new_lfa

    def overrideFromAncestry(self, pub_records):
        """Set the right published component from publishing ancestry.

        Start with the publishing records and fall back to the original
        uploaded package if necessary.
        """
        for pub_record in pub_records:
            archive = pub_record.archive
            if ISourcePackagePublishingHistory.providedBy(pub_record):
                is_source = True
                source_package = pub_record.sourcepackagerelease
                prev_published = archive.getPublishedSources(
                    name=source_package.sourcepackagename.name,
                    status=PackagePublishingStatus.PUBLISHED,
                    distroseries=pub_record.distroseries,
                    exact_match=True)
            elif IBinaryPackagePublishingHistory.providedBy(pub_record):
                is_source = False
                binary_package = pub_record.binarypackagerelease
                prev_published = archive.getAllPublishedBinaries(
                    name=binary_package.binarypackagename.name,
                    status=PackagePublishingStatus.PUBLISHED,
                    distroarchseries=pub_record.distroarchseries,
                    exact_match=True)
            else:
                raise AssertionError(
                    "pub_records contains something that's not one of "
                    "SourcePackagePublishingHistory or "
                    "BinaryPackagePublishingHistory")

            if prev_published.count() > 0:
                # Use the first record (the most recently published).
                component = prev_published[0].component
            else:
                # It's not been published yet, check the original package.
                if is_source:
                    component = pub_record.sourcepackagerelease.component
                else:
                    component = pub_record.binarypackagerelease.component

            # We don't want to use changeOverride here because it
            # creates a new publishing record.
            pub_record.secure_record.component = component
