# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Archive interfaces."""

__metaclass__ = type

__all__ = [
    'ArchiveDependencyError',
    'ArchivePurpose',
    'IArchive',
    'IArchiveEditDependenciesForm',
    'IArchivePackageCopyingForm',
    'IArchivePackageDeletionForm',
    'IArchiveSet',
    'IArchiveSourceSelectionForm',
    'IDistributionArchive',
    'IPPA',
    'IPPAActivateForm',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, Int, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice
from canonical.launchpad.interfaces import IHasOwner
from canonical.launchpad.validators.name import name_validator

from canonical.lazr import DBEnumeratedType, DBItem
from canonical.lazr.fields import Reference
from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, exported)


class ArchiveDependencyError(Exception):
    """Raised when an `IArchiveDependency` does not fit the context archive.

    A given dependency is considered inappropriate when:

     * It is the archive itself,
     * It is not a PPA,
     * It is already recorded.
    """


class IArchive(IHasOwner):
    """An Archive interface"""
    export_as_webservice_entry()

    id = Attribute("The archive ID.")

    owner = exported(
        PublicPersonChoice(
            title=_('Owner'), required=True, vocabulary='ValidOwner',
            description=_("""The PPA owner.""")))

    name = exported(
        TextLine(
            title=_("Name"), required=True,
            constraint=name_validator,
            description=_("The name of this archive.")))

    description = exported(
        Text(
            title=_("PPA contents description"), required=False,
            description=_("A short description of contents of this PPA.")))

    enabled = Bool(
        title=_("Enabled"), required=False,
        description=_("Whether the PPA is enabled or not."))

    private = Bool(
        title=_("Private"), required=False,
        description=_("Whether the PPA is private to the owner or not."))

    require_virtualized = Bool(
        title=_("Require Virtualized Builder"), required=False,
        description=_("Whether this archive requires its packages to be "
                      "built on a virtual builder."))

    authorized_size = Int(
        title=_("Authorized PPA size "), required=False,
        max=(20 * 1024),
        description=_("Maximum size, in MiB, allowed for this PPA."))

    whiteboard = Text(
        title=_("Whiteboard"), required=False,
        description=_("Administrator comments."))

    purpose = Int(
        title=_("Purpose of archive."), required=True, readonly=True,
        )

    buildd_secret = TextLine(
        title=_("Buildd Secret"), required=False,
        description=_("The password used by the builder to access the "
                      "archive.")
        )

    sources_cached = Int(
        title=_("Number of sources cached"), required=False,
        description=_("Number of source packages cached in this PPA."))

    binaries_cached = Int(
        title=_("Number of binaries cached"), required=False,
        description=_("Number of binary packages cached in this PPA."))

    package_description_cache = Attribute(
        "Concatenation of the source and binary packages published in this "
        "archive. Its content is used for indexed searches across archives.")

    distribution = exported(
        Reference(
            Interface, # Redefined to IDistribution later.
            title=_("The distribution that uses or is used by this "
                    "archive.")))

    dependencies = Attribute(
        "Archive dependencies recorded for this archive and ordered by owner "
        "displayname.")

    expanded_archive_dependencies = Attribute(
        "The expanded list of archive dependencies. It includes the implicit "
        "PRIMARY archive dependency for PPAs.")

    archive_url = Attribute("External archive URL.")

    is_ppa = Attribute("True if this archive is a PPA.")

    title = Attribute("Archive Title.")

    series_with_sources = Attribute(
        "DistroSeries to which this archive has published sources")
    number_of_sources = Attribute(
        'The number of sources published in the context archive.')
    number_of_binaries = Attribute(
        'The number of binaries published in the context archive.')
    sources_size = Attribute(
        'The size of sources published in the context archive.')
    binaries_size = Attribute(
        'The size of binaries published in the context archive.')
    estimated_size = Attribute('Estimated archive size.')

    total_count = Int(
        title=_("Total number of builds in archive"), required=True,
        default=0,
        description=_("The total number of builds in this archive. "
                      "This counter does not include discontinued "
                      "(superseded, cancelled, obsoleted) builds"))

    pending_count = Int(
        title=_("Number of pending builds in archive"), required=True,
        default=0,
        description=_("The number of pending builds in this archive."))

    succeeded_count = Int(
        title=_("Number of successful builds in archive"), required=True,
        default=0,
        description=_("The number of successful builds in this archive."))

    building_count = Int(
        title=_("Number of active builds in archive"), required=True,
        default=0,
        description=_("The number of active builds in this archive."))

    failed_count = Int(
        title=_("Number of failed builds in archive"), required=True,
        default=0,
        description=_("The number of failed builds in this archive."))

    date_created = Datetime(
        title=_('Date created'), required=False, readonly=True,
        description=_("The time when the archive was created."))

    def getPubConfig():
        """Return an overridden Publisher Configuration instance.

        The original publisher configuration based on the distribution is
        modified according local context, it basically fixes the archive
        paths to cope with non-primary and PPA archives publication workflow.
        """

    def getPublishedSources(name=None, version=None, status=None,
                            distroseries=None, pocket=None,
                            exact_match=False):
        """All `ISourcePackagePublishingHistory` target to this archive.

        :param: name: source name filter (exact match or SQL LIKE controlled
                      by 'exact_match' argument).
        :param: version: source version filter (always exact match).
        :param: status: `PackagePublishingStatus` filter, can be a sequence.
        :param: distroseries: `IDistroSeries` filter.
        :param: pocket: `PackagePublishingPocket` filter.
        :param: exact_match: either or not filter source names by exact
                             matching.

        :return: SelectResults containing `ISourcePackagePublishingHistory`.
        """

    def getSourcesForDeletion(name=None, status=None):
        """All `ISourcePackagePublishingHistory` available for deletion.

        :param: name: optional source name filter (SQL LIKE)
        :param: status: `PackagePublishingStatus` filter, can be a sequence.

        :return: SelectResults containing `ISourcePackagePublishingHistory`.
        """

    def getPublishedOnDiskBinaries(name=None, version=None, status=None,
                                   distroarchseries=None, exact_match=False):
        """Unique `IBinaryPackagePublishingHistory` target to this archive.

        In spite of getAllPublishedBinaries method, this method only returns
        distinct binary publications inside this Archive, i.e, it excludes
        architecture-independent publication for other architetures than the
        nominatedarchindep. In few words it represents the binary files
        published in the archive disk pool.

        :param: name: binary name filter (exact match or SQL LIKE controlled
                      by 'exact_match' argument).
        :param: version: binary version filter (always exact match).
        :param: status: `PackagePublishingStatus` filter, can be a list.
        :param: distroarchseries: `IDistroArchSeries` filter, can be a list.
        :param: pocket: `PackagePublishingPocket` filter.
        :param: exact_match: either or not filter source names by exact
                             matching.

        :return: SelectResults containing `IBinaryPackagePublishingHistory`.
        """

    def getAllPublishedBinaries(name=None, version=None, status=None,
                                distroarchseries=None, exact_match=False):
        """All `IBinaryPackagePublishingHistory` target to this archive.

        See getUniquePublishedBinaries for further information.

        :param: name: binary name filter (exact match or SQL LIKE controlled
                      by 'exact_match' argument).
        :param: version: binary version filter (always exact match).
        :param: status: `PackagePublishingStatus` filter, can be a list.
        :param: distroarchseries: `IDistroArchSeries` filter, can be a list.
        :param: pocket: `PackagePublishingPocket` filter.
        :param: exact_match: either or not filter source names by exact
                             matching.

        :return: SelectResults containing `IBinaryPackagePublishingHistory`.
        """

    def allowUpdatesToReleasePocket():
        """Return whether the archive allows publishing to the release pocket.

        If a distroseries is stable, normally release pocket publishings are
        not allowed.  However some archive types allow this.

        :return: True or False
        """

    def updateArchiveCache():
        """Concentrate cached information about the archive contents.

        Group the relevant package information (source name, binary names,
        binary summaries and distroseries with binaries) strings in the
        IArchive.package_description_cache search indexes (fti).

        Updates 'sources_cached' and 'binaries_cached' counters.

        Also include owner 'name' and 'displayname' to avoid inpecting the
        Person table indexes while searching.
        """

    def findDepCandidateByName(distroarchseries, name):
        """Return the last published binarypackage by given name.

        Return the PublishedPackage record by binarypackagename or None if
        not found.
        """

    def getArchiveDependency(dependency):
        """Return the `IArchiveDependency` object for the given dependency.

        :param dependency: is an `IArchive` object.
        :return: `IArchiveDependency` or None if a corresponding object
            could not be found.
        """

    def removeArchiveDependency(dependency):
        """Remove the `IArchiveDependency` record for the given dependency.

        :param dependency: is an `IArchive` object.
        """

    def addArchiveDependency(dependency):
        """Record an archive dependency record for the context archive.

        Raises `ArchiveDependencyError` if given 'dependency' does not fit
        the context archive.

        :param dependency: is an `IArchive` object.
        :return: a `IArchiveDependency` object targeted to the context
            `IArchive` requiring 'dependency' `IArchive`.
        """

    def canUpload(user, component_or_package=None):
        """Check to see if user is allowed to upload to component.

        :param user: An `IPerson` whom should be checked for authentication.
        :param component_or_package: The context `IComponent` or an
            `ISourcePackageName` for the check.  This parameter is
            not required if the archive is a PPA.

        :return: True if 'user' is allowed to upload to the specified
            component or package name.
        :raise TypeError: If component_or_package is not one of
            `IComponent` or `ISourcePackageName`.

        """

    def canAdministerQueue(user, component):
        """Check to see if user is allowed to administer queue items.

        :param user: An `IPerson` whom should be checked for authenticate.
        :param component: The context `IComponent` for the check.

        :return: True if 'user' is allowed to administer the package upload
        queue for items with 'component'.
        """


class IPPA(IArchive):
    """Marker interface so traversal works differently for PPAs."""


class IDistributionArchive(IArchive):
    """Marker interface so traversal works differently for distro archives."""


class IPPAActivateForm(Interface):
    """Schema used to activate PPAs."""

    description = Text(
        title=_("PPA contents description"), required=False,
        description=_(
        "A short description of this PPA. URLs are allowed and will "
        "be rendered as links."))

    accepted = Bool(
        title=_("I have read and accepted the PPA Terms of Service."),
        required=True, default=False)


# Avoid circular import.
from canonical.launchpad.interfaces.distribution import IDistribution
IArchive['distribution'].schema = IDistribution


class IArchiveSourceSelectionForm(Interface):
    """Schema used to select sources within an archive."""

    name_filter = TextLine(
        title=_("Package name"), required=False, default=None,
        description=_("Display packages only with name matching the given "
                      "filter."))


class IArchivePackageDeletionForm(IArchiveSourceSelectionForm):
    """Schema used to delete packages within an archive."""

    deletion_comment = TextLine(
        title=_("Deletion comment"), required=False,
        description=_("The reason why the package is being deleted."))


class IArchivePackageCopyingForm(IArchiveSourceSelectionForm):
    """Schema used to copy packages across archive."""



class IArchiveEditDependenciesForm(Interface):
    """Schema used to edit dependencies settings within a archive."""

    dependency_candidate = Choice(
        title=_('PPA Dependency'), required=False, vocabulary='PPA',
        description=_("Add a new PPA dependency."))


class IArchiveSet(Interface):
    """Interface for ArchiveSet"""

    title = Attribute('Title')

    number_of_ppa_sources = Attribute(
        'Number of published sources in public PPAs.')

    number_of_ppa_binaries = Attribute(
        'Number of published binaries in public PPAs.')

    def new(purpose, owner, name=None, distribution=None, description=None):
        """Create a new archive.

        :param purpose: `ArchivePurpose`;
        :param owner: `IPerson` owning the Archive;
        :param name: optional text to be used as the archive name, if not
            given it uses the names defined in
            `IArchiveSet._getDefaultArchiveNameForPurpose`;
        :param distribution: optional `IDistribution` to which the archive
            will be attached;
        :param description: optional text to be set as the archive
            description;

        :return: an `IArchive` object.
        """

    def get(archive_id):
        """Return the IArchive with the given archive_id."""

    def getPPAByDistributionAndOwnerName(distribution, name):
        """Return a single PPA the given (distribution, name) pair."""

    def getByDistroPurpose(distribution, purpose, name=None):
        """Return the IArchive with the given distribution and purpose.

        It uses the default names defined in
        `IArchiveSet._getDefaultArchiveNameForPurpose`.

        :raises AssertionError if used for with ArchivePurpose.PPA.
        """

    def __iter__():
        """Iterates over existent archives, including the main_archives."""

    def getPPAsForUser(user):
        """Return all PPAs the given user can participate.

        The result is ordered by PPA owner's displayname.
        """

    def getLatestPPASourcePublicationsForDistribution(distribution):
        """The latest 5 PPA source publications for a given distribution.

        Private PPAs are excluded from the result.
        """

    def getMostActivePPAsForDistribution(distribution):
        """Return the 5 most active PPAs.

        The activity is currently measured by number of uploaded (published)
        sources for each PPA during the last 7 days.

        Private PPAs are excluded from the result.

        :return A list with up to 5 dictionaries containing the ppa 'title'
            and the number of 'uploads' keys and corresponding values.
        """

    def getBuildCountersForArchitecture(archive, distroarchseries):
        """Return a dictionary containing the build counters per status.

        The result is restricted to the given archive and distroarchseries.

        The returned dictionary contains the follwoing keys and values:

         * 'total': total number of builds (includes SUPERSEDED);
         * 'pending': number of builds in NEEDSBUILD or BUILDING state;
         * 'failed': number of builds in FAILEDTOBUILD, MANUALDEPWAIT,
           CHROOTWAIT and FAILEDTOUPLOAD state;
         * 'succeeded': number of SUCCESSFULLYBUILT builds.

        :param archive: target `IArchive`;
        :param distroarchseries: target `IDistroArchSeries`.

        :return a dictionary with the 4 keys specified above.
        """

class ArchivePurpose(DBEnumeratedType):
    """The purpose, or type, of an archive.

    A distribution can be associated with different archives and this
    schema item enumerates the different archive types and their purpose.

    For example, Partner/ISV software in ubuntu is stored in a separate
    archive. PPAs are separate archives and contain packages that 'overlay'
    the ubuntu PRIMARY archive.
    """

    PRIMARY = DBItem(1, """
        Primary Archive

        This is the primary Ubuntu archive.
        """)

    PPA = DBItem(2, """
        PPA Archive

        This is a Personal Package Archive.
        """)

    PARTNER = DBItem(4, """
        Partner Archive

        This is the archive for partner packages.
        """)

    COPY = DBItem(6, """
        Generalized copy archive

        This kind of archive will be used for rebuilds, snapshots etc.
        """)

