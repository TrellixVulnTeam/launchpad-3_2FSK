# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Build interfaces."""

__metaclass__ = type

__all__ = [
    'BuildStatus',
    'BuildSetStatus',
    'CannotBeRescored',
    'IBuild',
    'IBuildRescoreForm',
    'IBuildSet',
    'incomplete_building_status',
    ]

from zope.interface import Interface, Attribute
from zope.schema import (
    Bool, Choice, Datetime, Int, Object, TextLine, Timedelta, Text)
from lazr.enum import DBEnumeratedType, DBItem, EnumeratedType, Item

from canonical.launchpad import _
from lp.soyuz.interfaces.archive import IArchive
from lp.buildmaster.interfaces.builder import IBuilder
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.pocket import PackagePublishingPocket
from canonical.launchpad.interfaces.librarian import ILibraryFileAlias
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


class BuildStatus(DBEnumeratedType):
    """Build status type

    Builds exist in the database in a number of states such as 'complete',
    'needs build' and 'dependency wait'. We need to track these states in
    order to correctly manage the autobuilder queues in the BuildQueue table.
    """

    NEEDSBUILD = DBItem(0, """
        Needs building

        Build record is fresh and needs building. Nothing is yet known to
        block this build and it is a candidate for building on any free
        builder of the relevant architecture
        """)

    FULLYBUILT = DBItem(1, """
        Successfully built

        Build record is an historic account of the build. The build is complete
        and needs no further work to complete it. The build log etc are all
        in place if available.
        """)

    FAILEDTOBUILD = DBItem(2, """
        Failed to build

        Build record is an historic account of the build. The build failed and
        cannot be automatically retried. Either a new upload will be needed
        or the build will have to be manually reset into 'NEEDSBUILD' when
        the issue is corrected
        """)

    MANUALDEPWAIT = DBItem(3, """
        Dependency wait

        Build record represents a package whose build dependencies cannot
        currently be satisfied within the relevant DistroArchSeries. This
        build will have to be manually given back (put into 'NEEDSBUILD') when
        the dependency issue is resolved.
        """)

    CHROOTWAIT = DBItem(4, """
        Chroot problem

        Build record represents a build which needs a chroot currently known
        to be damaged or bad in some way. The buildd maintainer will have to
        reset all relevant CHROOTWAIT builds to NEEDSBUILD after the chroot
        has been fixed.
        """)

    SUPERSEDED = DBItem(5, """
        Build for superseded Source

        Build record represents a build which never got to happen because the
        source package release for the build was superseded before the job
        was scheduled to be run on a builder. Builds which reach this state
        will rarely if ever be reset to any other state.
        """)

    BUILDING = DBItem(6, """
        Currently building

        Build record represents a build which is being build by one of the
        available builders.
        """)

    FAILEDTOUPLOAD = DBItem(7, """
        Failed to upload

        Build record is an historic account of a build that could not be
        uploaded correctly. It's mainly genereated by failures in
        process-upload which quietly rejects the binary upload resulted
        by the build procedure.
        In those cases all the build historic information will be stored (
        buildlog, datebuilt, duration, builder, etc) and the buildd admins
        will be notified via process-upload about the reason of the rejection.
        """)


incomplete_building_status = (
    BuildStatus.NEEDSBUILD,
    BuildStatus.BUILDING,
    )


class IBuildView(Interface):
    """A Build interface for items requiring launchpad.View."""
    id = Int(title=_('ID'), required=True, readonly=True)

    datecreated = exported(
        Datetime(
            title=_('Date created'), required=True, readonly=True,
            description=_("The time when the build request was created.")))

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

    archive = exported(
        Reference(
            title=_("Archive"), schema=IArchive,
            required=True, readonly=True,
            description=_("The Archive context for this build.")))

    pocket = exported(
        Choice(
            title=_('Pocket'), required=True,
            vocabulary=PackagePublishingPocket,
            description=_("The build targeted pocket.")))

    buildstate = exported(
        Choice(
            title=_('State'), required=True, vocabulary=BuildStatus,
            description=_("The current build state.")))

    date_first_dispatched = exported(
        Datetime(
            title=_('Date first dispatched'), required=False,
            description=_("The actual build start time. Set when the build "
                          "is dispatched the first time and not changed in "
                          "subsequent build attempts.")))

    dependencies = exported(
        TextLine(
            title=_("Dependencies"), required=False,
            description=_("Debian-like dependency line that must be satisfied"
                          " before attempting to build this request.")))

    builder = Object(
        title=_("Builder"), schema=IBuilder, required=False,
        description=_("The Builder which address this build request."))

    datebuilt = exported(
        Datetime(
            title=_('Date built'), required=False,
            description=_("The time when the build result got collected.")))

    buildduration = Timedelta(
        title=_("Build Duration"), required=False,
        description=_("Build duration interval, calculated when the "
                      "build result gets collected."))

    # XXX: jml 2010-01-12: Rename to build_log.
    buildlog = Object(
        schema=ILibraryFileAlias, required=False,
        title=_("The LibraryFileAlias containing the entire buildlog."))

    build_log_url = exported(
        TextLine(
            title=_("Build Log URL"), required=False,
            description=_("A URL for the build log. None if there is no "
                          "log available.")))

    upload_log = Object(
        schema=ILibraryFileAlias, required=False,
        title=_("The LibraryFileAlias containing the upload log for "
                "build resulting in binaries that could not be processed "
                "successfully. Otherwise it will be None."))

    upload_log_url = exported(
        TextLine(
            title=_("Upload Log URL"), required=False,
            description=_("A URL for failed upload logs."
                          "Will be None if there was no failure.")))

    # Properties
    current_source_publication = exported(
        Reference(
            title=_("Source publication"),
            schema=ISourcePackagePublishingHistory,
            required=False, readonly=True,
            description=_("The current source publication for this build.")))

    current_component = Attribute(
        "Component where the source related to this build was last "
        "published.")
    title = exported(Text(title=_("Build Title"), required=False))
    distroseries = Attribute("Direct parent needed by CanonicalURL")
    buildqueue_record = Attribute("Corespondent BuildQueue record")
    was_built = Attribute("Whether or not modified by the builddfarm.")
    arch_tag = exported(
        Text(title=_("Architecture tag"), required=False))
    distribution = exported(
        Reference(
            schema=IDistribution,
            title=_("Distribution"), required=True,
            description=_("Shortcut for its distribution.")))
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

    def createBuildQueueEntry():
        """Create a BuildQueue entry for this build record."""

    def notify():
        """Notify current build state to related people via email.

        If config.buildmaster.build_notification is disable, simply
        return.

        If config.builddmaster.notify_owner is enabled and SPR.creator
        has preferredemail it will send an email to the creator, Bcc:
        to the config.builddmaster.default_recipient. If one of the
        conditions was not satisfied, no preferredemail found (autosync
        or untouched packages from debian) or config options disabled,
        it will only send email to the specified default recipient.

        This notification will contain useful information about
        the record in question (all states are supported), see
        doc/build-notification.txt for further information.
        """

    def getEstimatedBuildStartTime():
        """Get the estimated build start time for a pending build job.

        :return: a timestamp upon success or None on failure. None
            indicates that an estimated start time is not available.
        :raise: AssertionError when the build job is not in the
            `BuildStatus.NEEDSBUILD` state.
        """

    def storeUploadLog(content):
        """Store the given content as the build upload_log.

        The given content is stored in the librarian, restricted as necessary
        according to the targeted archive's privacy.  The content object's
        'upload_log' attribute will point to the `LibrarianFileAlias`.

        :param content: string containing the upload-processor log output for
            the binaries created in this build.
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


class IBuildRescoreForm(Interface):
    """Form for rescoring a build."""

    priority = Int(
        title=_("Priority"), required=True, min=-2 ** 31, max=2 ** 31,
        description=_("Build priority, the build with the highest value will "
                      "be dispatched first."))
