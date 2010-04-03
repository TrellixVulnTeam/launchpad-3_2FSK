# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Build interfaces."""

__metaclass__ = type

__all__ = [
    'BuildSetStatus',
    'CannotBeRescored',
    'IBuild',
    'IBuildRescoreForm',
    'IBuildSet',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Int, Object, Text
from lazr.enum import EnumeratedType, Item

from canonical.launchpad import _
from lp.buildmaster.interfaces.buildbase import IBuildBase
from lp.soyuz.interfaces.processor import IProcessor
from lp.soyuz.interfaces.publishing import (
    ISourcePackagePublishingHistory)
from lp.soyuz.interfaces.sourcepackagerelease import (
    ISourcePackageRelease)
from lazr.restful.fields import Reference
from lazr.restful.declarations import (
    export_as_webservice_entry, exported, export_write_operation,
    operation_parameters, webservice_error)


class CannotBeRescored(Exception):
    """Raised when rescoring a build that cannot be rescored."""
    webservice_error(400) # Bad request.
    _message_prefix = "Cannot rescore build"


class IBuildView(IBuildBase):
    """A Build interface for items requiring launchpad.View."""
    id = Int(title=_('ID'), required=True, readonly=True)

    processor = Object(
        title=_("Processor"), schema=IProcessor,
        required=True, readonly=True,
        description=_("The Processor where this build should be built."))

    sourcepackagerelease = Object(
        title=_('Source'), schema=ISourcePackageRelease,
        required=True, readonly=True,
        description=_("The SourcePackageRelease requested to build."))

    distroarchseries = Object(
        title=_("Architecture"),
        # Really IDistroArchSeries
        schema=Interface,
        required=True, readonly=True,
        description=_("The DistroArchSeries context for this build."))

    # Properties
    current_source_publication = exported(
        Reference(
            title=_("Source publication"),
            schema=ISourcePackagePublishingHistory,
            required=False, readonly=True,
            description=_("The current source publication for this build.")))

    distroseries = Attribute("Direct parent needed by CanonicalURL")
    was_built = Attribute("Whether or not modified by the builddfarm.")
    arch_tag = exported(
        Text(title=_("Architecture tag"), required=False))
    distributionsourcepackagerelease = Attribute("The page showing the "
        "details for this sourcepackagerelease in this distribution.")
    binarypackages = Attribute(
        "A list of binary packages that resulted from this build, "
        "not limited and ordered by name.")
    distroarchseriesbinarypackages = Attribute(
        "A list of distroarchseriesbinarypackages that resulted from this"
        "build, ordered by name.")

    can_be_rescored = exported(
        Bool(
            title=_("Can Be Rescored"), required=False, readonly=True,
            description=_(
                "Whether or not this build record can be rescored "
                "manually.")))

    can_be_retried = exported(
        Bool(
            title=_("Can Be Retried"), required=False, readonly=True,
            description=_(
                "Whether or not this build record can be retried.")))

    calculated_buildstart = Attribute(
        "Emulates a buildstart timestamp by calculating it from "
        "datebuilt - buildduration.")

    is_virtualized = Attribute(
        "Whether or not this build requires a virtual build host or not.")

    upload_changesfile = Attribute(
        "The `LibraryFileAlias` object containing the changes file which "
        "was originally uploaded with the results of this build. It's "
        "'None' if it is build imported by Gina.")

    package_upload = Attribute(
        "The `PackageUpload` record corresponding to the original upload "
        "of the binaries resulted from this build. It's 'None' if it is "
        "a build imported by Gina.")

    def updateDependencies():
        """Update the build-dependencies line within the targeted context."""

    def __getitem__(name):
        """Mapped to getBinaryPackageRelease."""

    def getBinaryPackageRelease(name):
        """Return the binary package from this build with the given name, or
        raise NotFoundError if no such package exists.
        """

    def createBinaryPackageRelease(
        binarypackagename, version, summary, description, binpackageformat,
        component, section, priority, shlibdeps, depends, recommends,
        suggests, conflicts, replaces, provides, pre_depends, enhances,
        breaks, essential, installedsize, architecturespecific):
        """Create and return a `BinaryPackageRelease`.

        The binarypackagerelease will be attached to this specific build.
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up in the
        archive context:

         * Binary changesfile: '.changes';
         * Build logs: '.txt.gz';
         * Build upload logs: '_log.txt';

        :param filename: exactly filename to be looked up.

        :raises AssertionError if the given filename contains a unsupported
            filename and/or extension, see the list above.
        :raises NotFoundError if no file could not be found.

        :return the corresponding `ILibraryFileAlias` if the file was found.
        """


class IBuildEdit(Interface):
    """A Build interface for items requiring launchpad.Edit."""

    @export_write_operation()
    def retry():
        """Restore the build record to its initial state.

        Build record loses its history, is moved to NEEDSBUILD and a new
        non-scored BuildQueue entry is created for it.
        """


class IBuildAdmin(Interface):
    """A Build interface for items requiring launchpad.Admin."""

    @operation_parameters(score=Int(title=_("Score"), required=True))
    @export_write_operation()
    def rescore(score):
        """Change the build's score."""


class IBuild(IBuildView, IBuildEdit, IBuildAdmin):
    """A Build interface"""
    export_as_webservice_entry()


class BuildSetStatus(EnumeratedType):
    """`IBuildSet` status type

    Builds exist in the database in a number of states such as 'complete',
    'needs build' and 'dependency wait'. We sometimes provide a summary
    status of a set of builds.
    """
    # Until access to the name, title and description of exported types
    # is available through the API, set the title of these statuses
    # to match the name. This enables the result of API calls (which is
    # currently the title) to be used programatically (for example, as a
    # css class name).
    NEEDSBUILD = Item(
        title='NEEDSBUILD',# "Need building",
        description='There are some builds waiting to be built.')

    FULLYBUILT_PENDING = Item(
        title='FULLYBUILT_PENDING',
        description="All builds were built successfully but have not yet "
                    "been published.")

    FULLYBUILT = Item(title='FULLYBUILT', # "Successfully built",
                      description="All builds were built successfully.")

    FAILEDTOBUILD = Item(title='FAILEDTOBUILD', # "Failed to build",
                         description="There were build failures.")

    BUILDING = Item(title='BUILDING', # "Currently building",
                    description="There are some builds currently building.")


class IBuildSet(Interface):
    """Interface for BuildSet"""

    def getBuildBySRAndArchtag(sourcepackagereleaseID, archtag):
        """Return a build for a SourcePackageRelease and an ArchTag"""

    def getByBuildID(id):
        """Return the exact build specified.

        id is the numeric ID of the build record in the database.
        I.E. getUtility(IBuildSet).getByBuildID(foo).id == foo
        """

    def getPendingBuildsForArchSet(archseries):
        """Return all pending build records within a group of ArchSeries

        Pending means that buildstate is NEEDSBUILD.
        """

    def getBuildsForBuilder(builder_id, status=None, name=None,
                            arch_tag=None):
        """Return build records touched by a builder.

        :param builder_id: The id of the builder for which to find builds.
        :param status: If status is provided, only builds with that status
            will be returned.
        :param name: If name is provided, only builds which correspond to a
            matching sourcepackagename will be returned (SQL LIKE).
        :param arch_tag: If arch_tag is provided, only builds for that
            architecture will be returned.
        :return: a `ResultSet` representing the requested builds.
        """

    def getBuildsForArchive(archive, status=None, name=None, pocket=None,
                            arch_tag=None):
        """Return build records targeted to a given IArchive.

        :param archive: The archive for which builds will be returned.
        :param status: If status is provided, only builders with that
            status will be returned.
        :param name: If name is passed, return only build which the
            sourcepackagename matches (SQL LIKE).
        :param pocket: If pocket is provided only builds for that pocket
            will be returned.
        :param arch_tag: If arch_tag is provided, only builds for that
            architecture will be returned.
        :return: a `ResultSet` representing the requested builds.
        """

    def getBuildsByArchIds(arch_ids, status=None, name=None, pocket=None):
        """Retrieve Build Records for a given arch_ids list.

        Optionally, for a given status and/or pocket, if ommited return all
        records. If name is passed return only the builds which the
        sourcepackagename matches (SQL LIKE).
        """
    def retryDepWaiting(distroarchseries):
        """Re-process all MANUALDEPWAIT builds for a given IDistroArchSeries.

        This method will update all the dependency lines of all MANUALDEPWAIT
        records in the given architecture and those with all dependencies
        satisfied at this point will be automatically retried and re-scored.
        """

    def getBuildsBySourcePackageRelease(sourcepackagerelease_ids,
                                        buildstate=None):
        """Return all builds related with the given list of source releases.

        :param sourcepackagerelease_ids: list of `ISourcePackageRelease`s;
        :param buildstate: option build state filter.

        :return: a list of `IBuild` records not target to PPA archives.
        """

    def getStatusSummaryForBuilds(builds):
        """Return a summary of the build status for the given builds.

        The returned summary includes a status, a description of
        that status and the builds related to the status.

        :param builds: A list of build records.
        :type builds: ``list``
        :return: A dict consisting of the build status summary for the
            given builds. For example:
                {
                    'status': BuildSetStatus.FULLYBUILT,
                    'builds': [build1, build2]
                }
            or, an example where there are currently some builds building:
                {
                    'status': BuildSetStatus.BUILDING,
                    'builds':[build3]
                }
        :rtype: ``dict``.
        """

    def getByQueueEntry(queue_entry):
        """Return an IBuild instance for the given build queue entry.

        Retrieve the only one possible build record associated with the given
        build queue entry. If not found, return None.
        """

    def getQueueEntriesForBuildIDs(build_ids):
        """Return the IBuildQueue instances for the IBuild IDs at hand.

        Retrieve the build queue and related builder rows associated with the
        builds in question where they exist.
        """

    def calculateCandidates(archseries):
        """Return the BuildQueue records for the given archseries's Builds.

        Returns a selectRelease of BuildQueue items for sorted by descending
        'lastscore' for Builds within the given archseries.

        'archseries' argument should be a list of DistroArchSeries and it is
        asserted to not be None/empty.
        """


class IBuildRescoreForm(Interface):
    """Form for rescoring a build."""

    priority = Int(
        title=_("Priority"), required=True, min=-2 ** 31, max=2 ** 31,
        description=_("Build priority, the build with the highest value will "
                      "be dispatched first."))
