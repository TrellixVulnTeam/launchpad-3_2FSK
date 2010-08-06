# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for package-specific builds."""
__metaclass__ = type
__all__ = [
    'IPackageBuild',
    'IPackageBuildSource',
    'IPackageBuildSet',
    ]


from zope.interface import Interface, Attribute
from zope.schema import Choice, Object, TextLine
from lazr.restful.declarations import exported
from lazr.restful.fields import Reference

from canonical.launchpad import _
from canonical.launchpad.interfaces.librarian import ILibraryFileAlias
from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.archive import IArchive


class IPackageBuild(IBuildFarmJob):
    """Attributes and operations specific to package build jobs."""

    id = Attribute('The package build ID.')

    archive = exported(
        Reference(
            title=_('Archive'), schema=IArchive,
            required=True, readonly=True,
            description=_('The Archive context for this build.')))

    pocket = exported(
        Choice(
            title=_('Pocket'), required=True,
            vocabulary=PackagePublishingPocket,
            description=_('The build targeted pocket.')))

    upload_log = Object(
        schema=ILibraryFileAlias, required=False,
        title=_('The LibraryFileAlias containing the upload log for a'
                'build resulting in an upload that could not be processed '
                'successfully. Otherwise it will be None.'))

    upload_log_url = exported(
        TextLine(
            title=_("Upload Log URL"), required=False,
            description=_("A URL for failed upload logs."
                          "Will be None if there was no failure.")))

    dependencies = exported(
        TextLine(
            title=_('Dependencies'), required=False,
            description=_('Debian-like dependency line that must be satisfied'
                          ' before attempting to build this request.')))

    build_farm_job = Reference(
        title=_('Build farm job'), schema=IBuildFarmJob, required=True,
        readonly=True, description=_('The base build farm job.'))

    policy_name = TextLine(
        title=_("Policy name"), required=True,
        description=_("The upload policy to use for handling these builds."))

    current_component = Attribute(
        'Component where the source related to this build was last '
        'published.')

    distribution = exported(
        Reference(
            schema=IDistribution,
            title=_("Distribution"), required=True,
            description=_("Shortcut for its distribution.")))

    distro_series = exported(
        Reference(
            schema=IDistroSeries,
            title=_("Distribution series"), required=True,
            description=_("Shortcut for its distribution series.")))

    def getUploaderCommand(package_build, upload_leaf, uploader_logfilename):
        """Get the command to run as the uploader.

        :return: A list of command line arguments, beginning with the
            executable.
        """

    def getUploadDirLeaf(build_cookie, now=None):
        """Return the directory-leaf where files to be uploaded are stored.

        :param build_cookie: The build cookie as returned by the slave.
        :param now: The `datetime` to use when constructing the leaf
            directory name. If not provided, defaults to now.
        """

    def getUploadDir(upload_leaf):
        """Return the full directory where files to be uploaded are stored.

        :param upload_leaf: The leaf directory name where things will be
            stored.
        """

    def getLogFromSlave(build):
        """Get last buildlog from slave. """

    def getUploadLogContent(root, leaf):
        """Retrieve the upload log contents.

        :param root: Root directory for the uploads
        :param leaf: Leaf for this particular upload
        :return: Contents of log file or message saying no log file was found.
        """

    def estimateDuration():
        """Estimate the build duration."""

    def storeBuildInfo(build, librarian, slave_status):
        """Store available information for the build job.

        Derived classes can override this as needed, and call it from
        custom status handlers, but it should not be called externally.
        """

    def verifySuccessfulUpload():
        """Verify that the upload of this build completed succesfully."""

    def storeUploadLog(content):
        """Store the given content as the build upload_log.

        :param content: string containing the upload-processor log output for
            the binaries created in this build.
        """

    def notify(extra_info=None):
        """Notify current build state to related people via email.

        :param extra_info: Optional extra information that will be included
            in the notification email. If the notification is for a
            failed-to-upload error then this must be the content of the
            upload log.
        """

    def handleStatus(status, librarian, slave_status):
        """Handle a finished build status from a slave.

        :param status: Slave build status string with 'BuildStatus.' stripped.
        :param slave_status: A dict as returned by IBuilder.slaveStatus
        """

    def queueBuild(suspended=False):
        """Create a BuildQueue entry for this build.

        :param suspended: Whether the associated `Job` instance should be
            created in a suspended state.
        """


class IPackageBuildSource(Interface):
    """A utility of this interface used to create _things_."""

    def new(job_type, virtualized, archive, pocket, processor=None,
            status=BuildStatus.NEEDSBUILD, dependencies=None):
        """Create a new `IPackageBuild`.

        :param job_type: A `BuildFarmJobType` item.
        :param virtualized: A boolean indicating whether this build was
            virtualized.
        :param archive: An `IArchive`.
        :param pocket: An item of `PackagePublishingPocket`.
        :param processor: An `IProcessor` required to run this build farm
            job. Default is None (processor-independent).
        :param status: A `BuildStatus` item defaulting to NEEDSBUILD.
        :param dependencies: An optional debian-like dependency line.
        """


class IPackageBuildSet(Interface):
    """A utility representing a set of package builds."""

    def getBuildsForArchive(archive, status=None, pocket=None):
        """Return package build records targeted to a given IArchive.

        :param archive: The archive for which builds will be returned.
        :param status: If status is provided, only builders with that
            status will be returned.
        :param pocket: If pocket is provided only builds for that pocket
            will be returned.
        :return: a `ResultSet` representing the requested package builds.
        """

