# Copyright 2004-2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Builder interfaces."""

__metaclass__ = type

__all__ = [
    'BuildDaemonError',
    'BuildJobMismatch',
    'BuildSlaveFailure',
    'CannotBuild',
    'CannotResumeHost',
    'IBuilder',
    'IBuilderSet',
    'ProtocolVersionMismatch',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Choice, TextLine, Text, Bool

from canonical.launchpad import _
from canonical.launchpad.fields import Title, Description
from canonical.launchpad.interfaces.launchpad import IHasOwner
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.validators.url import builder_url_validator


class BuildDaemonError(Exception):
    """The class of errors raised by the buildd classes"""


class ProtocolVersionMismatch(BuildDaemonError):
    """The build slave had a protocol version. This is a serious error."""


class BuildJobMismatch(BuildDaemonError):
    """The build slave is working with mismatched information.

    It needs to be rescued.
    """


class CannotResumeHost(BuildDaemonError):
    """The build slave virtual machine cannot be resumed."""


# CannotBuild is intended to be the base class for a family of more specific
# errors.
class CannotBuild(BuildDaemonError):
    """The requested build cannot be done."""


class BuildSlaveFailure(BuildDaemonError):
    """The build slave has suffered an error and cannot be used."""


class IBuilder(IHasOwner):
    """Build-slave information and state.

    Builder instance represents a single builder slave machine within the
    Launchpad Auto Build System. It should specify a 'processor' on which the
    machine is based and is able to build packages for; a URL, by which the
    machine is accessed through an XML-RPC interface; name, title,
    description for entity identification and browsing purposes; an LP-like
    owner which has unrestricted access to the instance; the build slave
    machine status representation, including the field/properties:
    virtualized, builderok, status, failnotes and currentjob.
    """
    id = Attribute("Builder identifier")
    processor = Choice(
        title=_('Processor'), required=True, vocabulary='Processor',
        description=_('Build Slave Processor, used to identify '
                      'which jobs can be built by this device.'))

    owner = Choice(
        title=_('Owner'), required=True, vocabulary='ValidOwner',
        description=_('Builder owner, a Launchpad member which '
                      'will be responsible for this device.'))

    url = TextLine(
        title=_('URL'), required=True, constraint=builder_url_validator,
        description=_('The URL to the build machine, used as a unique '
                      'identifier. Includes protocol, host and port only, '
                      'e.g.: http://farm.com:8221/'))

    name = TextLine(
        title=_('Name'), required=True, constraint=name_validator,
        description=_('Builder Slave Name used for reference proposes'))

    title = Title(
        title=_('Title'), required=True,
        description=_('The builder slave title. Should be just a few words.'))

    description = Description(
        title=_('Description'), required=True,
        description=_('The builder slave description, may be several '
                      'paragraphs of text, giving the highlights and '
                      'details.'))

    virtualized = Bool(
        title=_('Virtualized'), required=True, default=False,
        description=_('Whether or not the builder is a virtual Xen '
                      'instance.'))

    manual = Bool(
        title=_('Manual Mode'), required=False, default=False,
        description=_('The auto-build system does not dispatch '
                      'jobs automatically for slaves in manual mode.'))

    builderok = Bool(
        title=_('Builder State OK'), required=True, default=True,
        description=_('Whether or not the builder is ok'))

    failnotes = Text(
        title=_('Failure Notes'), required=False,
        description=_('The reason for a builder not being ok'))

    vm_host = TextLine(
        title=_('Virtual Machine Host'), required=False,
        description=_('The machine hostname hosting the virtual '
                      'buildd-slave, e.g.: foobar-host.ppa'))

    active = Bool(
        title=_('Active'), required=True, default=True,
        description=_('Whether or not to present the builder publicly.'))

    slave = Attribute("xmlrpclib.Server instance corresponding to builder.")

    currentjob = Attribute("BuildQueue instance for job being processed.")

    status = Attribute("Generated status information")

    is_available = Bool(
        title=_("Whether or not a builder is available for building "
                "new jobs. "),
        required=False)

    def cacheFileOnSlave(logger, libraryfilealias):
        """Ask the slave to cache a librarian file to its local disk.

        This is used in preparation for a build.

        :param logger: A logger used for providing debug information.
        :param libraryfilealias: A library file alias representing the needed
            file.
        """

    def cachePrivateSourceOnSlave(logger, build_queue_item):
        """Ask the slave to download source files for a private build.

        The slave will cache the files for the source in build_queue_item
        to its local disk in preparation for a private build.  Private builds
        will always take the source files from the archive rather than the
        librarian since the archive has more granular access to each
        archive's files.

        :param logger: A logger used for providing debug information.
        :param build_queue_item: The `IBuildQueue` being built.
        """

    def checkCanBuildForDistroArchSeries(distro_arch_series):
        """Check that the slave can compile for the given distro_arch_release.

        This will query the builder to determine its actual architecture (as
        opposed to what we expect it to be).

        :param distro_arch_release: The distro_arch_release to check against.
        :raises BuildDaemonError: When the builder is down or of the wrong
            architecture.
        :raises ProtocolVersionMismatch: When the builder returns an
            unsupported protocol version.
        """

    def checkSlaveAlive():
        """Check that the buildd slave is alive.

        This pings the slave over the network via the echo method and looks
        for the sent message as the reply.

        :raises BuildDaemonError: When the slave is down.
        """

    def cleanSlave():
        """Clean any temporary files from the slave."""

    def failbuilder(reason):
        """Mark builder as failed for a given reason."""

    def requestAbort():
        """Ask that a build be aborted.

        This takes place asynchronously: Actually killing everything running
        can take some time so the slave status should be queried again to
        detect when the abort has taken effect. (Look for status ABORTED).
        """

    def resumeSlaveHost():
        """Resume the slave host to a known good condition.

        Issues 'builddmaster.vm_resume_command' specified in the configuration
        to resume the slave.

        :raises: CannotResumeHost: if builder is not virtual or if the
            configuration command has failed.

        :return: command stdout and stderr buffers as a tuple.
        """

    def setSlaveForTesting(proxy):
        """Sets the RPC proxy through which to operate the build slave."""

    def slaveStatus():
        """Get the slave status for this builder.

        * builder_status => string
        * build_id => string
        * build_status => string or None
        * logtail => string or None
        * filename => dictionary or None
        * dependencies => string or None

        :return: a tuple containing (
            builder_status, build_id, build_status, logtail, filemap,
            dependencies)
        """

    def slaveStatusSentence():
        """Get the slave status sentence for this builder.

        :return: A tuple with the first element containing the slave status,
            build_id-queue-id and then optionally more elements depending on
            the status.
        """

    def startBuild(build_queue_item, logger):
        """Start a build on this builder.

        :param build_queue_item: A BuildQueueItem to build.
        :param logger: A logger to be used to log diagnostic information.
        :raises BuildSlaveFailure: When the build slave fails.
        :raises CannotBuild: When a build cannot be started for some reason
            other than the build slave failing.
        """

    def transferSlaveFileToLibrarian(file_sha1, filename, private):
        """Transfer a file from the slave to the librarian.

        :param file_sha1: The file's sha1, which is how the file is addressed
            in the slave XMLRPC protocol. Specially, the file_sha1 'buildlog'
            will cause the build log to be retrieved and gzipped.
        :param filename: The name of the file to be given to the librarian file
            alias.
        :param private: True if the build is for a private archive.
        :return: A librarian file alias.
        """

    def findBuildCandidate():
        """Return the candidate for building.

        The pending BuildQueue item with the highest score for this builder
        ProcessorFamily or None if no candidate is available.
        """

    def dispatchBuildCandidate(candidate):
        """Dispatch the given job to this builder.

        This method can only be executed in the builddmaster machine, since
        it will actually issues the XMLRPC call to the buildd-slave.
        """

    def handleTimeout(logger, error_message):
        """Handle buildd slave communication timeout situations.

        In case of a virtualized/PPA buildd slave an attempt will be made
        to reset it first (using `resumeSlaveHost`). Only if that fails
        will it be (marked as) failed (using `failbuilder`).

        Conversely, a non-virtualized buildd slave will be (marked as)
        failed straightaway.

        :param logger: The logger object to be used for logging.
        :param error_message: The error message to be used for logging.
        """


class IBuilderSet(Interface):
    """Collections of builders.

    IBuilderSet provides access to all Builders in the system,
    and also acts as a Factory to allow the creation of new Builders.
    Methods on this interface should deal with the set of Builders:
    methods that affect a single Builder should be on IBuilder.
    """

    title = Attribute('Title')

    def __iter__():
        """Iterate over builders."""

    def __getitem__(name):
        """Retrieve a builder by name"""

    def new(processor, url, name, title, description, owner,
            active=True, virtualized=False, vm_host=None):
        """Create a new Builder entry.

        Additionally to the given arguments, builder are created with
        'builderok' and 'manual' set to True.

        It means that, once created, they will be presented as 'functional'
        in the UI but will not receive any job until an administrator move
        it to the automatic mode.
        """

    def count():
        """Return the number of builders in the system."""

    def get(builder_id):
        """Return the IBuilder with the given builderid."""

    def getBuilders():
        """Return all active configured builders."""

    def getBuildersByArch(arch):
        """Return all configured builders for a given DistroArchSeries."""

    def getBuildQueueSizeForProcessor(processor, virtualized=False):
        """Return the number of pending builds for a given processor.

        :param processor: IProcessor;
        :param virtualized: boolean, controls which queue to check,
            'virtualized' means PPA.

        :return the size of the queue, integer.
        """

    def pollBuilders(logger, txn):
        """Poll all the builders and take any immediately available actions.

        Specifically this will request a resume if needed, update log tails in
        the database, copy and process the result of builds.

        :param logger: A logger to use to provide information about the polling
            process.
        :param txn: A zopeless transaction object which is currently used by
            legacy code that we are in the process of removing. DO NOT add
            additional uses of this parameter.
        :return: A canonical.buildmaster.master.BuilddMaster instance. This is
            temporary and once the dispatchBuilds method no longer requires
            a used instance this return parameter will be dropped.
        """

    def getBuildersForQueue(processor, virtualized):
        """Return all builders for given processor/virtualization setting."""
