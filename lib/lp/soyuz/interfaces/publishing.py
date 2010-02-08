# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Publishing interfaces."""

__metaclass__ = type

__all__ = [
    'IArchiveSafePublisher',
    'IBinaryPackageFilePublishing',
    'IBinaryPackagePublishingHistory',
    'ICanPublishPackages',
    'IFilePublishing',
    'IPublishingEdit',
    'IPublishingSet',
    'ISourcePackageFilePublishing',
    'ISourcePackagePublishingHistory',
    'MissingSymlinkInPool',
    'NotInPool',
    'PackagePublishingPriority',
    'PackagePublishingStatus',
    'PoolFileOverwriteError',
    'active_publishing_status',
    'inactive_publishing_status',
    'name_priority_map',
    ]

from zope.schema import Bool, Choice, Datetime, Int, TextLine, Text
from zope.interface import Interface, Attribute
from lazr.enum import DBEnumeratedType, DBItem

from canonical.launchpad import _
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pocket import PackagePublishingPocket

from lazr.restful.fields import Reference
from lazr.restful.declarations import (
    REQUEST_USER, call_with, export_as_webservice_entry,
    export_read_operation, export_write_operation, exported,
    operation_parameters, operation_returns_collection_of)

#
# Exceptions
#


class NotInPool(Exception):
    """Raised when an attempt is made to remove a non-existent file."""


class PoolFileOverwriteError(Exception):
    """Raised when an attempt is made to overwrite a file in the pool.

    The proposed file has different content as the one in pool.
    This exception is unexpected and when it happens we keep the original
    file in pool and print a warning in the publisher log. It probably
    requires manual intervention in the archive.
    """

class MissingSymlinkInPool(Exception):
    """Raised when there is a missing symlink in pool.

    This condition is ignored, similarly to what we do for `NotInPool`,
    since the pool entry requested to be removed is not there anymore.

    The corresponding record is marked as removed and the process
    continues.
    """

class PackagePublishingStatus(DBEnumeratedType):
    """Package Publishing Status

     A package has various levels of being published within a DistroSeries.
     This is important because of how new source uploads dominate binary
     uploads bit-by-bit. Packages (source or binary) enter the publishing
     tables as 'Pending', progress through to 'Published' eventually become
     'Superseded' and then become 'PendingRemoval'. Once removed from the
     DistroSeries the publishing record is also removed.
     """

    PENDING = DBItem(1, """
        Pending

        This [source] package has been accepted into the DistroSeries and
        is now pending the addition of the files to the published disk area.
        In due course, this source package will be published.
        """)

    PUBLISHED = DBItem(2, """
        Published

        This package is currently published as part of the archive for that
        distroseries. In general there will only ever be one version of any
        source/binary package published at any one time. Once a newer
        version becomes published the older version is marked as superseded.
        """)

    SUPERSEDED = DBItem(3, """
        Superseded

        When a newer version of a [source] package is published the existing
        one is marked as "superseded".  """)

    DELETED = DBItem(4, """
        Deleted

        When a publication was "deleted" from the archive by user request.
        Records in this state contain a reference to the Launchpad user
        responsible for the deletion and a text comment with the removal
        reason.
        """)

    OBSOLETE = DBItem(5, """
        Obsolete

        When a distroseries becomes obsolete, its published packages
        are no longer required in the archive.  The publications for
        those packages are marked as "obsolete" and are subsequently
        removed during domination and death row processing.
        """)


class PackagePublishingPriority(DBEnumeratedType):
    """Package Publishing Priority

    Binary packages have a priority which is related to how important
    it is to have that package installed in a system. Common priorities
    range from required to optional and various others are available.
    """

    REQUIRED = DBItem(50, """
        Required

        This priority indicates that the package is required. This priority
        is likely to be hard-coded into various package tools. Without all
        the packages at this priority it may become impossible to use dpkg.
        """)

    IMPORTANT = DBItem(40, """
        Important

        If foo is in a package; and "What is going on?! Where on earth is
        foo?!?!" would be the reaction of an experienced UNIX hacker were
        the package not installed, then the package is important.
        """)

    STANDARD = DBItem(30, """
        Standard

        Packages at this priority are standard ones you can rely on to be in
        a distribution. They will be installed by default and provide a
        basic character-interface userland.
        """)

    OPTIONAL = DBItem(20, """
        Optional

        This is the software you might reasonably want to install if you did
        not know what it was or what your requiredments were. Systems such
        as X or TeX will live here.
        """)

    EXTRA = DBItem(10, """
        Extra

        This contains all the packages which conflict with those at the
        other priority levels; or packages which are only useful to people
        who have very specialised needs.
        """)


name_priority_map = {
    'required': PackagePublishingPriority.REQUIRED,
    'important': PackagePublishingPriority.IMPORTANT,
    'standard': PackagePublishingPriority.STANDARD,
    'optional': PackagePublishingPriority.OPTIONAL,
    'extra': PackagePublishingPriority.EXTRA,
    '': None,
    }


#
# Base Interfaces
#


class ICanPublishPackages(Interface):
    """Denotes the ability to publish associated publishing records."""

    def getPendingPublications(archive, pocket, is_careful):
        """Return the specific group of records to be published.

        IDistroSeries -> ISourcePackagePublishing
        IDistroArchSeries -> IBinaryPackagePublishing

        'pocket' & 'archive' are mandatory arguments, they  restrict the
        results to the given value.

        If the distroseries is already released, it automatically refuses
        to publish records to RELEASE pocket.
        """

    def publish(diskpool, log, archive, pocket, careful=False):
        """Publish associated publishing records targeted for a given pocket.

        Require an initialised diskpool instance and a logger instance.
        Require an 'archive' which will restrict the publications.
        'careful' argument would cause the 'republication' of all published
        records if True (system will DTRT checking hash of all
        published files.)

        Consider records returned by the local implementation of
        getPendingPublications.
        """


class IArchiveSafePublisher(Interface):
    """Safe Publication methods"""

    def setPublished():
        """Set a publishing record to published.

        Basically set records to PUBLISHED status only when they
        are PENDING and do not update datepublished value of already
        published field when they were checked via 'careful'
        publishing.
        """


class IPublishingView(Interface):
    """Base interface for all Publishing classes"""

    files = Attribute("Files included in this publication.")
    displayname = exported(
        TextLine(
            title=_("Display Name"),
            description=_("Text representation of the current record.")),
        exported_as="display_name")
    age = Attribute("Age of the publishing record.")

    component_name = exported(
        TextLine(
            title=_("Component Name"),
            required=False, readonly=True))
    section_name = exported(
        TextLine(
            title=_("Section Name"),
            required=False, readonly=True))

    def publish(diskpool, log):
        """Publish or ensure contents of this publish record

        Skip records which attempt to overwrite the archive (same file paths
        with different content) and do not update the database.

        If all the files get published correctly update its status properly.
        """

    def getIndexStanza():
        """Return archive index stanza contents

        It's based on the locally provided buildIndexStanzaTemplate method,
        which differs for binary and source instances.
        """

    def buildIndexStanzaFields():
        """Build a map of fields and values to be in the Index file.

        The fields and values ae mapped into a dictionary, where the key is
        the field name and value is the value string.
        """

    def supersede():
        """Supersede this publication.

        :return: The superseded publishing records, either a
            `ISourcePackagePublishingHistory` or
            `IBinaryPackagePublishingHistory`.
        """

    def requestObsolescence():
        """Make this publication obsolete.

        :return: The obsoleted publishing record, either:
            `ISourcePackagePublishingHistory` or
            `IBinaryPackagePublishingHistory`.
        """

    def getAncestry(archive=None, distroseries=None, pocket=None,
                    status=None):
        """Return the most recent publication of the same source or binary.

        If a suitable ancestry could not be found, None is returned.

        It optionally accepts parameters for adjusting the publishing
        context, if not given they default to the current context.

        :param archive: optional `IArchive`, defaults to the context archive.
        :param distroseries: optional `IDistroSeries`, defaults to the
            context distroseries.
        :param pocket: optional `PackagePublishingPocket`, defaults to any
            pocket.
        :param status: optional `PackagePublishingStatus` or a collection of
            them, defaults to `PackagePublishingStatus.PUBLISHED`
        """

    def overrideFromAncestry():
        """Set the right published component from publishing ancestry.

        Start with the publishing records and fall back to the original
        uploaded package if necessary.

        :raise: AssertionError if the context publishing record is not in
            PENDING status.
        """


class IPublishingEdit(Interface):
    """Base interface for writeable Publishing classes."""
    export_as_webservice_entry()

    @call_with(removed_by=REQUEST_USER)
    @operation_parameters(
        removal_comment=TextLine(title=_("Removal comment"), required=False))
    @export_write_operation()
    def requestDeletion(removed_by, removal_comment=None):
        """Delete this publication.

        :param removed_by: `IPerson` responsible for the removal.
        :param removal_comment: optional text describing the removal reason.
        """


class IFilePublishing(Interface):
    """Base interface for *FilePublishing classes"""

    distribution = Int(
            title=_('Distribution ID'), required=True, readonly=True,
            )
    distroseriesname = TextLine(
            title=_('Series name'), required=True, readonly=True,
            )
    componentname = TextLine(
            title=_('Component name'), required=True, readonly=True,
            )
    publishingstatus = Int(
            title=_('Package publishing status'), required=True,
            readonly=True,
            )
    pocket = Int(
            title=_('Package publishing pocket'), required=True,
            readonly=True,
            )
    archive = Int(
            title=_('Archive ID'), required=True, readonly=True,
            )
    libraryfilealias = Int(
            title=_('Binarypackage file alias'), required=True,
            readonly=True,
            )
    libraryfilealiasfilename = TextLine(
            title=_('File name'), required=True, readonly=True,
            )
    archive_url = Attribute('The on-archive URL for the published file.')

    publishing_record = Attribute(
        "Return the Source or Binary publishing record "
        "(in the form of I{Source,Binary}PackagePublishingHistory).")

    def publish(diskpool, log):
        """Publish or ensure contents of this file in the archive.

        Create symbolic link to files already present in different component
        or add file from librarian if it's not present. Update the database
        to represent the current archive state.
        """

#
# Source package publishing
#


class ISourcePackageFilePublishing(IFilePublishing):
    """Source package release files and their publishing status"""
    file_type_name = Attribute(
        "The uploaded file's type; one of 'orig', 'dsc', 'diff' or 'other'")
    sourcepackagename = TextLine(
            title=_('Binary package name'), required=True, readonly=True,
            )
    sourcepackagepublishing = Int(
            title=_('Sourcepackage publishing record id'), required=True,
            readonly=True,
            )


class ISourcePackagePublishingHistory(IPublishingView):
    """A source package publishing history record."""
    export_as_webservice_entry()

    id = Int(
            title=_('ID'), required=True, readonly=True,
            )
    sourcepackagerelease = Int(
            title=_('The source package release being published'),
            required=False, readonly=False,
            )
    status = exported(
        Choice(
            title=_('Package Publishing Status'),
            description=_('The status of this publishing record'),
            vocabulary=PackagePublishingStatus,
            required=False, readonly=False,
            ))
    distroseries = exported(
        Reference(
            IDistroSeries,
            title=_('The distro series being published into'),
            required=False, readonly=False,
            ),
        exported_as="distro_series")
    component = Int(
            title=_('The component being published into'),
            required=False, readonly=False,
            )
    section = Int(
            title=_('The section being published into'),
            required=False, readonly=False,
            )
    datepublished = exported(
        Datetime(
            title=_('The date on which this record was published'),
            required=False, readonly=False,
            ),
        exported_as="date_published")
    scheduleddeletiondate = exported(
        Datetime(
            title=_('The date on which this record is scheduled for '
                    'deletion'),
            required=False, readonly=False,
            ),
        exported_as="scheduled_deletion_date")
    pocket = exported(
        Choice(
            title=_('Pocket'),
            description=_('The pocket into which this entry is published'),
            vocabulary=PackagePublishingPocket,
            required=True, readonly=True,
            ))
    archive = exported(
        Reference(
            Interface, # Really IArchive, see below.
            title=_('Archive ID'), required=True, readonly=True,
            ))
    supersededby = Int(
            title=_('The sourcepackagerelease which superseded this one'),
            required=False, readonly=False,
            )
    datesuperseded = exported(
        Datetime(
            title=_('The date on which this record was marked superseded'),
            required=False, readonly=False,
            ),
        exported_as="date_superseded")
    datecreated = exported(
        Datetime(
            title=_('The date on which this record was created'),
            required=True, readonly=False,
            ),
        exported_as="date_created")
    datemadepending = exported(
        Datetime(
            title=_('The date on which this record was set as pending '
                    'removal'),
            required=False, readonly=False,
            ),
        exported_as="date_made_pending")
    dateremoved = exported(
        Datetime(
            title=_('The date on which this record was removed from the '
                    'published set'),
            required=False, readonly=False,
            ),
        exported_as="date_removed")
    removed_by = exported(
        Reference(
            IPerson,
            title=_('The IPerson responsible for the removal'),
            required=False, readonly=False,
            ))
    removal_comment = exported(
        Text(
            title=_('Reason why this publication is going to be removed.'),
            required=False, readonly=False,
        ))

    meta_sourcepackage = Attribute(
        "Return an ISourcePackage meta object correspondent to the "
        "sourcepackagerelease attribute inside a specific distroseries")
    meta_sourcepackagerelease = Attribute(
        "Return an IDistributionSourcePackageRelease meta object "
        "correspondent to the sourcepackagerelease attribute")
    meta_supersededby = Attribute(
        "Return an IDistributionSourcePackageRelease meta object "
        "correspondent to the supersededby attribute. if supersededby "
        "is None return None.")
    meta_distroseriessourcepackagerelease = Attribute(
        "Return an IDistroSeriesSourcePackageRelease meta object "
        "correspondent to the sourcepackagerelease attribute inside "
        "a specific distroseries")

    source_package_name = exported(
        TextLine(
            title=_("Source Package Name"),
            required=False, readonly=True))
    source_package_version = exported(
        TextLine(
            title=_("Source Package Version"),
            required=False, readonly=True))

    package_creator = exported(
        Reference(
            IPerson,
            title=_('Package Creator'),
            description=_('The IPerson who created the source package.'),
            required=False, readonly=True,
        ))
    package_maintainer = exported(
        Reference(
            IPerson,
            title=_('Package Maintainer'),
            description=_('The IPerson who maintains the source package.'),
            required=False, readonly=True,
        ))
    package_signer = exported(
        Reference(
            IPerson,
            title=_('Package Signer'),
            description=_('The IPerson who signed the source package.'),
            required=False, readonly=True,
        ))

    newer_distroseries_version = Attribute(
        "An `IDistroSeriosSourcePackageRelease` with a newer version of this "
        "package that has been published in the main distribution series, "
        "if one exists, or None.")

    # Really IBinaryPackagePublishingHistory, see below.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    def getPublishedBinaries():
        """Return all resulted `IBinaryPackagePublishingHistory`.

        Follow the build record and return every PUBLISHED or PENDING
        binary publishing record for any `DistroArchSeries` in this
        `DistroSeries` and in the same `IArchive` and Pocket, ordered
        by architecture tag.

        :return: a list with all corresponding publishing records.
        """

    def getBuiltBinaries():
        """Return all unique binary publications built by this source.

        Follow the build record and return every unique binary publishing
        record in the context `DistroSeries` and in the same `IArchive`
        and Pocket.

        There will be only one entry for architecture independent binary
        publications.

        :return: a list containing all unique
            `IBinaryPackagePublishingHistory`.
        """

    @operation_returns_collection_of(Interface) # Really IBuild, see below.
    @export_read_operation()
    def getBuilds():
        """Return a list of `IBuild` objects in this publishing context.

        The builds are ordered by `DistroArchSeries.architecturetag`.

        :return: a list of `IBuilds`.
        """

    @export_read_operation()
    def changesFileUrl():
        """The .changes file URL for this source publication.

        :return: the .changes file URL for this source (a string).
        """

    def getUnpublishedBuilds(build_states=None):
        """Return a resultset of `IBuild` objects in this context that are
        not published.

        :param build_states: list of build states to which the result should
            be limited. Defaults to BuildStatus.FULLYBUILT if none are
            specified.
        :return: a result set of `IBuilds`.
        """

    def createMissingBuilds(architectures_available=None, pas_verify=None,
                            logger=None):
        """Create missing Build records for a published source.

        P-a-s should be used when accepting sources to the PRIMARY archive
        (in drescher). It explicitly ignores given P-a-s for sources
        targeted to PPAs.

        :param architectures_available: options list of `DistroArchSeries`
            that should be considered for build creation; if not given
            it will be calculated in place, all architectures for the
            context distroseries with available chroot.
        :param pas_verify: optional Package-architecture-specific (P-a-s)
            object, to be used, when convinient, for creating builds;
        :param logger: optional context Logger object (used on DEBUG level).

        :return: a list of `Builds` created for this source publication.
        """

    def getSourceAndBinaryLibraryFiles():
        """Return a list of `LibraryFileAlias` for all source and binaries.

        All the source files and all binary files ever published to the
        same archive context are returned as a list of LibraryFileAlias
        records.

        :return: a list of `ILibraryFileAlias`.
        """

    def changeOverride(new_component=None, new_section=None):
        """Change the component and/or section of this publication

        It is changed only if the argument is not None.

        Return the overridden publishing record, either a
        `ISourcePackagePublishingHistory` or `IBinaryPackagePublishingHistory`.
        """

    def copyTo(distroseries, pocket, archive):
        """Copy this publication to another location.

        :return: a `ISourcePackagePublishingHistory` record representing the
            source in the destination location.
        """

    def getStatusSummaryForBuilds():
        """Return a summary of the build status for the related builds.

        This method augments IBuildSet.getBuildStatusSummaryForBuilds() by
        additionally checking to see if all the builds have been published
        before returning the fully-built status.

        :return: A dict consisting of the build status summary for the
            related builds. For example:
                {
                    'status': PackagePublishingStatus.PENDING,
                    'builds': [build1, build2]
                }
        """

    @export_read_operation()
    def sourceFileUrls():
        """URLs for this source publication's uploaded source files.

        :return: A collection of URLs for this source.
        """

    @export_read_operation()
    def binaryFileUrls():
        """URLs for this source publication's binary files.

        :return: A collection of URLs for this source.
        """


#
# Binary package publishing
#


class IBinaryPackageFilePublishing(IFilePublishing):
    """Binary package files and their publishing status"""
    # Note that it is really /source/ package name below, and not a
    # thinko; at least, that's what Celso tells me the code uses
    #   -- kiko, 2006-03-22
    sourcepackagename = TextLine(
            title=_('Source package name'), required=True, readonly=True,
            )
    binarypackagepublishing = Int(
            title=_('Binary Package publishing record id'), required=True,
            readonly=True,
            )
    architecturetag = TextLine(
            title=_("Architecture tag. As per dpkg's use"), required=True,
            readonly=True,
            )


class IBinaryPackagePublishingHistory(IPublishingView):
    """A binary package publishing record."""
    export_as_webservice_entry()

    id = Int(
            title=_('ID'), required=True, readonly=True,
            )
    binarypackagerelease = Int(
            title=_('The binary package being published'), required=False,
            readonly=False,
            )
    distroarchseries = exported(
        Reference(
            Interface, #Really IDistroArchSeries, circular import fixed below.
            title=_("Distro Arch Series"),
            description=_('The distroarchseries being published into'),
            required=False, readonly=False,
            ),
        exported_as="distro_arch_series")
    component = Int(
            title=_('The component being published into'),
            required=False, readonly=False,
            )
    section = Int(
            title=_('The section being published into'),
            required=False, readonly=False,
            )
    priority = Int(
            title=_('The priority being published into'),
            required=False, readonly=False,
            )
    datepublished = exported(
        Datetime(
            title=_("Date Published"),
            description=_('The date on which this record was published'),
            required=False, readonly=False,
            ),
        exported_as="date_published")
    scheduleddeletiondate = exported(
        Datetime(
            title=_("Scheduled Deletion Date"),
            description=_('The date on which this record is scheduled for '
                    'deletion'),
            required=False, readonly=False,
            ),
        exported_as="scheduled_deletion_date")
    status = exported(
        Choice(
            title=_('Status'),
            description=_('The status of this publishing record'),
            vocabulary=PackagePublishingStatus,
            required=False, readonly=False,
            ))
    pocket = exported(
        Choice(
            title=_('Pocket'),
            description=_('The pocket into which this entry is published'),
            vocabulary=PackagePublishingPocket,
            required=True, readonly=True,
            ))
    supersededby = Int(
            title=_('The build which superseded this one'),
            required=False, readonly=False,
            )
    datecreated = exported(
        Datetime(
            title=_('Date Created'),
            description=_('The date on which this record was created'),
            required=True, readonly=False,
            ),
        exported_as="date_created")
    datesuperseded = exported(
        Datetime(
            title=_("Date Superseded"),
            description=_(
                'The date on which this record was marked superseded'),
            required=False, readonly=False,
            ),
        exported_as="date_superseded")
    datemadepending = exported(
        Datetime(
            title=_("Date Made Pending"),
            description=_(
                'The date on which this record was set as pending removal'),
            required=False, readonly=False,
            ),
        exported_as="date_made_pending")
    dateremoved = exported(
        Datetime(
            title=_("Date Removed"),
            description=_(
                'The date on which this record was removed from the '
                'published set'),
            required=False, readonly=False,
            ),
        exported_as="date_removed")
    archive = exported(
        Reference(
            Interface, # Really IArchive, see below.
            title=_('Archive'),
            description=_("The context archive for this publication."),
            required=True, readonly=True,
            ))
    removed_by = exported(
        Reference(
            IPerson,
            title=_("Removed By"),
            description=_('The Person responsible for the removal'),
            required=False, readonly=False,
        ))
    removal_comment = exported(
        Text(
            title=_("Removal Comment"),
            description=_(
                'Reason why this publication is going to be removed.'),
            required=False, readonly=False))

    distroarchseriesbinarypackagerelease = Attribute("The object that "
        "represents this binarypackagerelease in this distroarchseries.")

    binary_package_name = exported(
        TextLine(
            title=_("Binary Package Name"),
            required=False, readonly=True))
    binary_package_version = exported(
        TextLine(
            title=_("Binary Package Version"),
            required=False, readonly=True))
    priority_name = exported(
        TextLine(
            title=_("Priority Name"),
            required=False, readonly=True))

    def changeOverride(new_component=None, new_section=None,
                       new_priority=None):
        """Change the component, section and/or priority of this publication.

        It is changed only if the argument is not None.

        Return the overridden publishing record, either a
        `ISourcePackagePublishingHistory` or `IBinaryPackagePublishingHistory`.
        """

    def copyTo(distroseries, pocket, archive):
        """Copy this publication to another location.

        Architecture independent binary publications are copied to all
        supported architectures in the destination distroseries.

        :return: a list of `IBinaryPackagePublishingHistory` records
            representing the binaries copied to the destination location.
        """


class IPublishingSet(Interface):
    """Auxiliary methods for dealing with sets of publications."""

    def copyBinariesTo(binaries, distroseries, pocket, archive):
        """Copy multiple binaries to a given destination.

        Processing multiple binaries in a batch allows certain
        performance optimisations such as looking up the main
        component once only, and getting all the BPPH records
        with one query.

        :param binaries: A list of binaries to copy.
        :param distroseries: The target distroseries.
        :param pocket: The target pocket.
        :param archive: The target archive.

        :return: A result set of the created binary package
            publishing histories.
        """

    def newBinaryPublication(archive, binarypackagerelease, distroarchseries,
                             component, section, priority, pocket):
        """Create a new `BinaryPackagePublishingHistory`.

        :param archive: An `IArchive`
        :param binarypackagerelease: An `IBinaryPackageRelease`
        :param distroarchseries: An `IDistroArchSeries`
        :param component: An `IComponent`
        :param section: An `ISection`
        :param priority: A `PackagePublishingPriority`
        :param pocket: A `PackagePublishingPocket`

        datecreated will be UTC_NOW.
        status will be PackagePublishingStatus.PENDING
        """

    def newSourcePublication(archive, sourcepackagerelease, distroseries,
                             component, section, pocket):
        """Create a new `SourcePackagePublishingHistory`.

        :param archive: An `IArchive`
        :param sourcepackagerelease: An `ISourcePackageRelease`
        :param distroseries: An `IDistroSeries`
        :param component: An `IComponent`
        :param section: An `ISection`
        :param pocket: A `PackagePublishingPocket`

        datecreated will be UTC_NOW.
        status will be PackagePublishingStatus.PENDING
        """

    def getByIdAndArchive(id, archive, source=True):
        """Return the publication matching id AND archive.

        :param archive: The context `IArchive`.
        :param source: If true look for source publications, otherwise
            binary publications.
        """

    def getBuildsForSourceIds(source_ids, archive=None, build_states=None):
        """Return all builds related with each given source publication.

        The returned ResultSet contains entries with the wanted `Build`s
        associated with the corresponding source publication and its
        targeted `DistroArchSeries` in a 3-element tuple. This way the extra
        information will be cached and the callsites can group builds in
        any convenient form.

        The optional archive parameter, if provided, will ensure that only
        builds corresponding to the archive will be included in the results.

        The result is ordered by:

         1. Ascending `SourcePackagePublishingHistory.id`,
         2. Ascending `DistroArchSeries.architecturetag`.

        :param source_ids: list of or a single
            `SourcePackagePublishingHistory` object.
        :type source_ids: ``list`` or `SourcePackagePublishingHistory`
        :param archive: An optional archive with which to filter the source
                        ids.
        :type archive: `IArchive`
        :param build_states: optional list of build states to which the
            result will be limited. Defaults to all states if ommitted.
        :type build_states: ``list`` or None
        :return: a storm ResultSet containing tuples as
            (`SourcePackagePublishingHistory`, `Build`, `DistroArchSeries`)
        :rtype: `storm.store.ResultSet`.
        """

    def getBuildsForSources(one_or_more_source_publications):
        """Return all builds related with each given source publication.

        Extracts the source ids from one_or_more_source_publications and
        calls getBuildsForSourceIds.
        """

    def getUnpublishedBuildsForSources(one_or_more_source_publications,
                                       build_states=None):
        """Return all the unpublished builds for each source.

        :param one_or_more_source_publications: list of, or a single
            `SourcePackagePublishingHistory` object.
        :param build_states: list of build states to which the result should
            be limited. Defaults to BuildStatus.FULLYBUILT if none are
            specified.
        :return: a storm ResultSet containing tuples of
            (`SourcePackagePublishingHistory`, `Build`)
        """

    def getBinaryFilesForSources(one_or_more_source_publication):
        """Return binary files related to each given source publication.

        The returned ResultSet contains entries with the wanted
        `LibraryFileAlias`s (binaries only) associated with the
        corresponding source publication and its `LibraryFileContent`
        in a 3-element tuple. This way the extra information will be
        cached and the callsites can group files in any convenient form.

        :param one_or_more_source_publication: list of or a single
            `SourcePackagePublishingHistory` object.

        :return: a storm ResultSet containing triples as follows:
            (`SourcePackagePublishingHistory`, `LibraryFileAlias`,
             `LibraryFileContent`)
        """

    def getFilesForSources(one_or_more_source_publication):
        """Return all files related to each given source publication.

        The returned ResultSet contains entries with the wanted
        `LibraryFileAlias`s (source and binaries) associated with the
        corresponding source publication and its `LibraryFileContent`
        in a 3-element tuple. This way the extra information will be
        cached and the callsites can group files in any convenient form.

        Callsites should order this result after grouping by source,
        because SQL UNION can't be correctly ordered in SQL level.

        :param one_or_more_source_publication: list of or a single
            `SourcePackagePublishingHistory` object.

        :return: an *unordered* storm ResultSet containing tuples as
            (`SourcePackagePublishingHistory`, `LibraryFileAlias`,
             `LibraryFileContent`)
        """

    def getBinaryPublicationsForSources(one_or_more_source_publications):
        """Return all binary publication for the given source publications.

        The returned ResultSet contains entries with the wanted
        `BinaryPackagePublishingHistory`s associated with the corresponding
        source publication and its targeted `DistroArchSeries`,
        `BinaryPackageRelease` and `BinaryPackageName` in a 5-element tuple.
        This way the extra information will be cached and the callsites can
        group binary publications in any convenient form.

        The result is ordered by:

         1. Ascending `SourcePackagePublishingHistory.id`,
         2. Ascending `BinaryPackageName.name`,
         3. Ascending `DistroArchSeries.architecturetag`.
         4. Descending `BinaryPackagePublishingHistory.id`.

        :param one_or_more_source_publication: list of or a single
            `SourcePackagePublishingHistory` object.

        :return: a storm ResultSet containing tuples as
            (`SourcePackagePublishingHistory`,
             `BinaryPackagePublishingHistory`,
             `BinaryPackageRelease`, `BinaryPackageName`, `DistroArchSeries`)
        """

    def getPackageDiffsForSources(one_or_more_source_publications):
        """Return all `PackageDiff`s for each given source publication.

        The returned ResultSet contains entries with the wanted `PackageDiff`s
        associated with the corresponding source publication and its resulting
        `LibraryFileAlias` and `LibraryFileContent` in a 4-element tuple. This
        way the extra information will be cached and the callsites can group
        package-diffs in any convenient form.

        `LibraryFileAlias` and `LibraryFileContent` elements might be None in
        case the `PackageDiff` is not completed yet.

        The result is ordered by:

         1. Ascending `SourcePackagePublishingHistory.id`,
         2. Descending `PackageDiff.date_requested`.

        :param one_or_more_source_publication: list of or a single
            `SourcePackagePublishingHistory` object.

        :return: a storm ResultSet containing tuples as
            (`SourcePackagePublishingHistory`, `PackageDiff`,
             `LibraryFileAlias`, `LibraryFileContent`)
        """

    def getChangesFilesForSources(one_or_more_source_publications):
        """Return all changesfiles for each given source publication.

        The returned ResultSet contains entries with the wanted changesfiles
        as `LibraryFileAlias`es associated with the corresponding source
        publication and its corresponding `LibraryFileContent`,
        `PackageUpload` and `SourcePackageRelease` in a 5-element tuple.
        This way the extra information will be cached and the call sites can
        group changesfiles in any convenient form.

        The result is ordered by ascending `SourcePackagePublishingHistory.id`

        :param one_or_more_source_publication: list of or a single
            `SourcePackagePublishingHistory` object.

        :return: a storm ResultSet containing tuples as
            (`SourcePackagePublishingHistory`, `PackageUpload`,
             `SourcePackageRelease`, `LibraryFileAlias`, `LibraryFileContent`)
        """

    def getChangesFileLFA(spr):
        """The changes file for the given `SourcePackageRelease`.

        :param spr: the `SourcePackageRelease` for which to return the
            changes file `LibraryFileAlias`.

        :return: a `LibraryFileAlias` instance or None
        """

    def requestDeletion(sources, removed_by, removal_comment=None):
        """Delete the source and binary publications specified.

        This method deletes the source publications passed via the first
        parameter as well as their associated binary publications.

        :param sources: list of `SourcePackagePublishingHistory` objects.
        :param removed_by: `IPerson` responsible for the removal.
        :param removal_comment: optional text describing the removal reason.

        :return: The deleted publishing record, either:
            `ISourcePackagePublishingHistory` or
            `IBinaryPackagePublishingHistory`.
        """

    def getBuildStatusSummariesForSourceIdsAndArchive(source_ids, archive):
        """Return a summary of the build statuses for source publishing ids.

        This method collects all the builds for the provided source package
        publishing history ids, and returns the build status summary for
        the builds associated with each source package.

        See the `getStatusSummaryForBuilds()` method of `IBuildSet`.for
        details of the summary.

        :param source_ids: A list of source publishing history record ids.
        :type source_ids: ``list``
        :param archive: The archive which will be used to filter the source
                        ids.
        :type archive: `IArchive`
        :return: A dict consisting of the overall status summaries for the
            given ids that belong in the archive. For example:
                {
                    18: {'status': 'succeeded'},
                    25: {'status': 'building', 'builds':[building_builds]},
                    35: {'status': 'failed', 'builds': [failed_builds]}
                }
        :rtype: ``dict``.
        """

    def getBuildStatusSummaryForSourcePublication(source_publication):
        """Return a summary of the build statuses for this source
        publication.

        See `ISourcePackagePublishingHistory`.getStatusSummaryForBuilds()
        for details. The call is just proxied here so that it can also be
        used with an ArchiveSourcePublication passed in as
        the source_package_pub, allowing the use of the cached results.
        """

    def getNearestAncestor(
        package_name, archive, distroseries, pocket=None, status=None,
        binary=False):
        """Return the ancestor of the given parkage in a particular archive.

        :param package_name: The package name for which we are checking for
            an ancestor.
        :type package_name: ``string``
        :param archive: The archive in which we are looking for an ancestor.
        :type archive: `IArchive`
        :param distroseries: The particular series in which we are looking for
            an ancestor.
        :type distroseries: `IDistroSeries`
        :param pocket: An optional pocket to restrict the search.
        :type pocket: `PackagePublishingPocket`.
        :param status: An optional status defaulting to PUBLISHED if not
            provided.
        :type status: `PackagePublishingStatus`
        :param binary: An optional argument to look for a binary ancestor
            instead of the default source.
        :type binary: ``Boolean``

        :return: The most recent publishing history for the given
            arguments.
        :rtype: `ISourcePackagePublishingHistory` or
            `IBinaryPackagePublishingHistory` or None.
        """

active_publishing_status = (
    PackagePublishingStatus.PENDING,
    PackagePublishingStatus.PUBLISHED,
    )


inactive_publishing_status = (
    PackagePublishingStatus.SUPERSEDED,
    PackagePublishingStatus.DELETED,
    PackagePublishingStatus.OBSOLETE,
    )


# Circular import problems fixed in _schema_circular_imports.py
