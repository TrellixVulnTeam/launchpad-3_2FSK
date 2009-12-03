# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type

__all__ = [
    'Builder',
    'BuilderSet',
    ]

import httplib
import gzip
import logging
import os
import socket
import subprocess
import tempfile
import urllib2
import xmlrpclib

from lazr.delegates import delegates

from zope.interface import implements
from zope.component import getUtility

from sqlobject import (
    StringCol, ForeignKey, BoolCol, IntCol, SQLObjectNotFound)

from storm.store import Store

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.buildd.slave import BuilderStatus
from lp.buildmaster.interfaces.buildfarmjobbehavior import (
    BuildBehaviorMismatch, IBuildFarmJobBehavior)
from lp.buildmaster.master import BuilddMaster
from lp.buildmaster.model.buildfarmjobbehavior import IdleBuildBehavior
from canonical.database.sqlbase import SQLBase, sqlvalues
from lp.soyuz.model.buildqueue import BuildQueue
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.pocket import PackagePublishingPocket
from canonical.launchpad.helpers import filenameToContentType
from canonical.launchpad.interfaces._schema_circular_imports import (
    IHasBuildRecords)
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeriesSet
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.build import BuildStatus, IBuildSet
from lp.soyuz.interfaces.builder import (
    BuildDaemonError, BuildSlaveFailure, CannotBuild, CannotResumeHost,
    IBuilder, IBuilderSet, ProtocolVersionMismatch)
from lp.soyuz.interfaces.buildqueue import IBuildQueueSet
from lp.soyuz.interfaces.publishing import (
    PackagePublishingStatus)
from lp.soyuz.model.buildpackagejob import BuildPackageJob
from canonical.launchpad.webapp import urlappend
from canonical.lazr.utils import safe_hasattr
from canonical.librarian.utils import copy_and_close


class TimeoutHTTPConnection(httplib.HTTPConnection):
    def connect(self):
        """Override the standard connect() methods to set a timeout"""
        ret = httplib.HTTPConnection.connect(self)
        self.sock.settimeout(config.builddmaster.socket_timeout)
        return ret


class TimeoutHTTP(httplib.HTTP):
    _connection_class = TimeoutHTTPConnection


class TimeoutTransport(xmlrpclib.Transport):
    """XMLRPC Transport to setup a socket with defined timeout"""
    def make_connection(self, host):
        host, extra_headers, x509 = self.get_host_info(host)
        return TimeoutHTTP(host)


class BuilderSlave(xmlrpclib.Server):
    """Add in a few useful methods for the XMLRPC slave."""

    def __init__(self, urlbase, vm_host):
        """Initialise a Server with specific parameter to our buildfarm."""
        self.vm_host = vm_host
        self.urlbase = urlbase
        rpc_url = urlappend(urlbase, "rpc")
        xmlrpclib.Server.__init__(self, rpc_url,
                                  transport=TimeoutTransport(),
                                  allow_none=True)

    def getFile(self, sha_sum):
        """Construct a file-like object to return the named file."""
        filelocation = "filecache/%s" % sha_sum
        fileurl = urlappend(self.urlbase, filelocation)
        return urllib2.urlopen(fileurl)

    def resume(self):
        """Resume a virtual builder.

        It uses the configuration command-line (replacing 'vm_host') and
        return its output.

        :return: a (stdout, stderr, subprocess exitcode) triple
        """
        resume_command = config.builddmaster.vm_resume_command % {
            'vm_host': self.vm_host}
        resume_argv = resume_command.split()
        resume_process = subprocess.Popen(
            resume_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = resume_process.communicate()

        return (stdout, stderr, resume_process.returncode)


class Builder(SQLBase):

    implements(IBuilder, IHasBuildRecords)
    delegates(IBuildFarmJobBehavior, context="current_build_behavior")
    _table = 'Builder'

    _defaultOrder = ['id']

    processor = ForeignKey(dbName='processor', foreignKey='Processor',
                           notNull=True)
    url = StringCol(dbName='url', notNull=True)
    name = StringCol(dbName='name', notNull=True)
    title = StringCol(dbName='title', notNull=True)
    description = StringCol(dbName='description', notNull=True)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    builderok = BoolCol(dbName='builderok', notNull=True)
    failnotes = StringCol(dbName='failnotes')
    virtualized = BoolCol(dbName='virtualized', default=True, notNull=True)
    speedindex = IntCol(dbName='speedindex')
    manual = BoolCol(dbName='manual', default=False)
    vm_host = StringCol(dbName='vm_host')
    active = BoolCol(dbName='active', notNull=True, default=True)

    def _getCurrentBuildBehavior(self):
        """Return the current build behavior."""
        if not safe_hasattr(self, '_current_build_behavior'):
            self._current_build_behavior = None

        if (self._current_build_behavior is None or
            isinstance(self._current_build_behavior, IdleBuildBehavior)):
            # If we don't currently have a current build behavior set,
            # or we are currently idle, then...
            currentjob = self.currentjob
            if currentjob is not None:
                # ...we'll set it based on our current job.
                self._current_build_behavior = (
                    currentjob.required_build_behavior)
                self._current_build_behavior.setBuilder(self)
                return self._current_build_behavior
            elif self._current_build_behavior is None:
                # If we don't have a current job or an idle behavior
                # already set, then we just set the idle behavior
                # before returning.
                self._current_build_behavior = IdleBuildBehavior()
            return self._current_build_behavior

        else:
            # We did have a current non-idle build behavior set, so
            # we just return it.
            return self._current_build_behavior


    def _setCurrentBuildBehavior(self, new_behavior):
        """Set the current build behavior."""
        self._current_build_behavior = new_behavior
        self._current_build_behavior.setBuilder(self)

    current_build_behavior = property(
        _getCurrentBuildBehavior, _setCurrentBuildBehavior)

    def cacheFileOnSlave(self, logger, libraryfilealias):
        """See `IBuilder`."""
        url = libraryfilealias.http_url
        logger.debug("Asking builder on %s to ensure it has file %s "
                     "(%s, %s)" % (self.url, libraryfilealias.filename,
                                   url, libraryfilealias.content.sha1))
        self._sendFileToSlave(url, libraryfilealias.content.sha1)

    def _sendFileToSlave(self, url, sha1, username="", password=""):
        """Helper to send the file at 'url' with 'sha1' to this builder."""
        if not self.builderok:
            raise BuildDaemonError("Attempted to give a file to a known-bad"
                                   " builder")
        present, info = self.slave.ensurepresent(
            sha1, url, username, password)
        if not present:
            message = """Slave '%s' (%s) was unable to fetch file.
            ****** URL ********
            %s
            ****** INFO *******
            %s
            *******************
            """ % (self.name, self.url, url, info)
            raise BuildDaemonError(message)

    def checkCanBuildForDistroArchSeries(self, distro_arch_series):
        """See IBuilder."""
        # XXX cprov 2007-06-15:
        # This function currently depends on the operating system specific
        # details of the build slave to return a processor-family-name (the
        # architecturetag) which matches the distro_arch_series. In reality,
        # we should be checking the processor itself (e.g. amd64) as that is
        # what the distro policy is set from, the architecture tag is both
        # distro specific and potentially different for radically different
        # distributions - its not the right thing to be comparing.

        # query the slave for its active details.
        # XXX cprov 2007-06-15: Why is 'mechanisms' ignored?
        builder_vers, builder_arch, mechanisms = self.slave.info()
        # we can only understand one version of slave today:
        if builder_vers != '1.0':
            raise ProtocolVersionMismatch("Protocol version mismatch")
        # check the slave arch-tag against the distro_arch_series.
        if builder_arch != distro_arch_series.architecturetag:
            raise BuildDaemonError(
                "Architecture tag mismatch: %s != %s"
                % (builder_arch, distro_arch_series.architecturetag))

    def checkSlaveAlive(self):
        """See IBuilder."""
        if self.slave.echo("Test")[0] != "Test":
            raise BuildDaemonError("Failed to echo OK")

    def cleanSlave(self):
        """See IBuilder."""
        return self.slave.clean()

    @property
    def currentjob(self):
        """See IBuilder"""
        return getUtility(IBuildQueueSet).getByBuilder(self)

    def requestAbort(self):
        """See IBuilder."""
        return self.slave.abort()

    def resumeSlaveHost(self):
        """See IBuilder."""
        if not self.virtualized:
            raise CannotResumeHost('Builder is not virtualized.')

        if not self.vm_host:
            raise CannotResumeHost('Undefined vm_host.')

        logger = self._getSlaveScannerLogger()
        logger.debug("Resuming %s (%s)" % (self.name, self.url))

        stdout, stderr, returncode = self.slave.resume()
        if returncode != 0:
            raise CannotResumeHost(
                "Resuming failed:\nOUT:\n%s\nERR:\n%s\n" % (stdout, stderr))

        return stdout, stderr

    @cachedproperty
    def slave(self):
        """See IBuilder."""
        # A cached attribute is used to allow tests to replace
        # the slave object, which is usually an XMLRPC client, with a
        # stub object that removes the need to actually create a buildd
        # slave in various states - which can be hard to create.
        return BuilderSlave(self.url, self.vm_host)

    def setSlaveForTesting(self, proxy):
        """See IBuilder."""
        self.slave = proxy

    def startBuild(self, build_queue_item, logger):
        """See IBuilder."""
        # Set the build behavior depending on the provided build queue item.
        self.current_build_behavior = build_queue_item.required_build_behavior
        self.logStartBuild(build_queue_item, logger)

        # Make sure the request is valid; an exception is raised if it's not.
        self.verifyBuildRequest(build_queue_item, logger)

        # If we are building a virtual build, resume the virtual machine.
        if self.virtualized:
            self.resumeSlaveHost()

        # Do it.
        build_queue_item.markAsBuilding(self)
        self.dispatchBuildToSlave(build_queue_item, logger)

    # XXX cprov 2009-06-24: This code does not belong to the content
    # class domain. Here we cannot make sensible decisions about what
    # we are allowed to present according to the request user. Then
    # bad things happens, see bug #391721.
    @property
    def status(self):
        """See IBuilder"""
        if not self.builderok:
            if self.failnotes is not None:
                return self.failnotes
            return 'Disabled'

        # If the builder is OK then we delegate the status
        # to our current behavior.
        return self.current_build_behavior.status

    def failbuilder(self, reason):
        """See IBuilder"""
        self.builderok = False
        self.failnotes = reason

    # XXX Michael Nelson 20091202 bug=491330. The current UI assumes
    # that the builder history will display binary build records, as
    # returned by getBuildRecords() below. See the bug for a discussion
    # of the options.
    def getBuildRecords(self, build_state=None, name=None, arch_tag=None,
                        user=None):
        """See IHasBuildRecords."""
        return getUtility(IBuildSet).getBuildsForBuilder(
            self.id, build_state, name, arch_tag, user)

    def slaveStatus(self):
        """See IBuilder."""
        builder_version, builder_arch, mechanisms = self.slave.info()
        status_sentence = self.slave.status()

        status = {'builder_status': status_sentence[0]}
        status.update(
            self.current_build_behavior.slaveStatus(status_sentence))
        return status

    def slaveStatusSentence(self):
        """See IBuilder."""
        return self.slave.status()

    def transferSlaveFileToLibrarian(self, file_sha1, filename, private):
        """See IBuilder."""
        out_file_fd, out_file_name = tempfile.mkstemp(suffix=".buildlog")
        out_file = os.fdopen(out_file_fd, "r+")
        try:
            slave_file = self.slave.getFile(file_sha1)
            copy_and_close(slave_file, out_file)
            # If the requested file is the 'buildlog' compress it using gzip
            # before storing in Librarian.
            if file_sha1 == 'buildlog':
                out_file = open(out_file_name)
                filename += '.gz'
                out_file_name += '.gz'
                gz_file = gzip.GzipFile(out_file_name, mode='wb')
                copy_and_close(out_file, gz_file)
                os.remove(out_file_name.replace('.gz', ''))

            # Reopen the file, seek to its end position, count and seek
            # to beginning, ready for adding to the Librarian.
            out_file = open(out_file_name)
            out_file.seek(0, 2)
            bytes_written = out_file.tell()
            out_file.seek(0)

            library_file = getUtility(ILibraryFileAliasSet).create(
                filename, bytes_written, out_file,
                contentType=filenameToContentType(filename),
                restricted=private)
        finally:
            # Finally, remove the temporary file
            out_file.close()
            os.remove(out_file_name)

        return library_file.id

    @property
    def is_available(self):
        """See `IBuilder`."""
        if not self.builderok:
            return False
        try:
            slavestatus = self.slaveStatusSentence()
        except (xmlrpclib.Fault, socket.error), info:
            return False
        if slavestatus[0] != BuilderStatus.IDLE:
            return False
        return True

    # XXX cprov 20071116: It should become part of the public
    # findBuildCandidate once we start to detect superseded builds
    # at build creation time.
    def _findBuildCandidate(self):
        """Return the highest priority build candidate for this builder.

        Returns a pending IBuildQueue record queued for this builder
        processorfamily with the highest lastscore or None if there
        is no one available.
        """
        # If a private build does not yet have its source published then
        # we temporarily skip it because we want to wait for the publisher
        # to place the source in the archive, which is where builders
        # download the source from in the case of private builds (because
        # it's a secure location).
        private_statuses = (
            PackagePublishingStatus.PUBLISHED,
            PackagePublishingStatus.SUPERSEDED,
            PackagePublishingStatus.DELETED,
            )
        clauses = ["""
            ((archive.private IS TRUE AND
              EXISTS (
                  SELECT SourcePackagePublishingHistory.id
                  FROM SourcePackagePublishingHistory
                  WHERE
                      SourcePackagePublishingHistory.distroseries =
                         DistroArchSeries.distroseries AND
                      SourcePackagePublishingHistory.sourcepackagerelease =
                         Build.sourcepackagerelease AND
                      SourcePackagePublishingHistory.archive = Archive.id AND
                      SourcePackagePublishingHistory.status IN %s))
              OR
              archive.private IS FALSE) AND
            buildqueue.job = buildpackagejob.job AND
            buildpackagejob.build = build.id AND
            build.distroarchseries = distroarchseries.id AND
            build.archive = archive.id AND
            archive.enabled = TRUE AND
            build.buildstate = %s AND
            distroarchseries.processorfamily = %s AND
            buildqueue.builder IS NULL
        """ % sqlvalues(
            private_statuses, BuildStatus.NEEDSBUILD, self.processor.family)]

        clauseTables = [
            'Build', 'BuildPackageJob', 'DistroArchSeries', 'Archive']

        clauses.append("""
            archive.require_virtualized = %s
        """ % sqlvalues(self.virtualized))

        # Ensure that if BUILDING builds exist for the same
        # public ppa archive and architecture and another would not
        # leave at least 20% of them free, then we don't consider
        # another as a candidate.
        #
        # This clause selects the count of currently building builds on
        # the arch in question, then adds one to that total before
        # deriving a percentage of the total available builders on that
        # arch.  It then makes sure that percentage is under 80.
        #
        # The extra clause is only used if the number of available
        # builders is greater than one, or nothing would get dispatched
        # at all.
        num_arch_builders = Builder.selectBy(
            processor=self.processor, manual=False, builderok=True).count()
        if num_arch_builders > 1:
            clauses.append("""
                EXISTS (SELECT true
                WHERE ((
                    SELECT COUNT(build2.id)
                    FROM Build build2, DistroArchSeries distroarchseries2
                    WHERE
                        build2.archive = build.archive AND
                        archive.purpose = %s AND
                        archive.private IS FALSE AND
                        build2.distroarchseries = distroarchseries2.id AND
                        distroarchseries2.processorfamily = %s AND
                        build2.buildstate = %s) + 1::numeric)
                    *100 / %s
                    < 80)
            """ % sqlvalues(
                ArchivePurpose.PPA, self.processor.family,
                BuildStatus.BUILDING, num_arch_builders))

        query = " AND ".join(clauses)
        candidate = BuildQueue.selectFirst(
            query, clauseTables=clauseTables,
            orderBy=['-buildqueue.lastscore', 'build.id'])

        return candidate

    def _getSlaveScannerLogger(self):
        """Return the logger instance from buildd-slave-scanner.py."""
        # XXX cprov 20071120: Ideally the Launchpad logging system
        # should be able to configure the root-logger instead of creating
        # a new object, then the logger lookups won't require the specific
        # name argument anymore. See bug 164203.
        logger = logging.getLogger('slave-scanner')
        return logger

    def findBuildCandidate(self):
        """See `IBuilder`."""
        logger = self._getSlaveScannerLogger()
        candidate = self._findBuildCandidate()

        # Mark build records targeted to old source versions as SUPERSEDED
        # and build records target to SECURITY pocket as FAILEDTOBUILD.
        # Builds in those situation should not be built because they will
        # be wasting build-time, the former case already has a newer source
        # and the latter could not be built in DAK.
        build_set = getUtility(IBuildSet)
        while candidate is not None:
            build = build_set.getByQueueEntry(candidate)
            if build.pocket == PackagePublishingPocket.SECURITY:
                # We never build anything in the security pocket.
                logger.debug(
                    "Build %s FAILEDTOBUILD, queue item %s REMOVED"
                    % (build.id, candidate.id))
                build.buildstate = BuildStatus.FAILEDTOBUILD
                candidate.destroySelf()
                candidate = self._findBuildCandidate()
                continue

            publication = build.current_source_publication

            if publication is None:
                # The build should be superseded if it no longer has a
                # current publishing record.
                logger.debug(
                    "Build %s SUPERSEDED, queue item %s REMOVED"
                    % (build.id, candidate.id))
                build.buildstate = BuildStatus.SUPERSEDED
                candidate.destroySelf()
                candidate = self._findBuildCandidate()
                continue

            return candidate

        # No candidate was found.
        return None

    def dispatchBuildCandidate(self, candidate):
        """See `IBuilder`."""
        logger = self._getSlaveScannerLogger()
        try:
            self.startBuild(candidate, logger)
        except (BuildSlaveFailure, CannotBuild, BuildBehaviorMismatch), err:
            logger.warn('Could not build: %s' % err)

    def handleTimeout(self, logger, error_message):
        """See IBuilder."""
        builder_should_be_failed = True

        if self.virtualized:
            # Virtualized/PPA builder: attempt a reset.
            logger.warn(
                "Resetting builder: %s -- %s" % (self.url, error_message),
                exc_info=True)
            try:
                self.resumeSlaveHost()
            except CannotResumeHost, err:
                # Failed to reset builder.
                logger.warn(
                    "Failed to reset builder: %s -- %s" %
                    (self.url, str(err)), exc_info=True)
            else:
                # Builder was reset, do *not* mark it as failed.
                builder_should_be_failed = False

        if builder_should_be_failed:
            # Mark builder as 'failed'.
            logger.warn(
                "Disabling builder: %s -- %s" % (self.url, error_message),
                exc_info=True)
            self.failbuilder(error_message)


class BuilderSet(object):
    """See IBuilderSet"""
    implements(IBuilderSet)

    def __init__(self):
        self.title = "The Launchpad build farm"

    def __iter__(self):
        return iter(Builder.select())

    def __getitem__(self, name):
        try:
            return Builder.selectOneBy(name=name)
        except SQLObjectNotFound:
            raise NotFoundError(name)

    def new(self, processor, url, name, title, description, owner,
            active=True, virtualized=False, vm_host=None):
        """See IBuilderSet."""
        return Builder(processor=processor, url=url, name=name, title=title,
                       description=description, owner=owner, active=active,
                       virtualized=virtualized, vm_host=vm_host,
                       builderok=True, manual=True)

    def get(self, builder_id):
        """See IBuilderSet."""
        return Builder.get(builder_id)

    def count(self):
        """See IBuilderSet."""
        return Builder.select().count()

    def getBuilders(self):
        """See IBuilderSet."""
        return Builder.selectBy(
            active=True, orderBy=['virtualized', 'processor', 'name'])

    def getBuildersByArch(self, arch):
        """See IBuilderSet."""
        return Builder.select('builder.processor = processor.id '
                              'AND processor.family = %d'
                              % arch.processorfamily.id,
                              clauseTables=("Processor",))

    def getBuildQueueSizeForProcessor(self, processor, virtualized=False):
        """See `IBuilderSet`."""
        # Avoiding circular imports.
        from lp.soyuz.model.archive import Archive
        from lp.soyuz.model.build import Build
        from lp.soyuz.model.distroarchseries import (
            DistroArchSeries)
        from lp.soyuz.model.processor import Processor

        store = Store.of(processor)
        origin = (
            Archive,
            Build,
            BuildPackageJob,
            BuildQueue,
            DistroArchSeries,
            Processor,
            )
        queue = store.using(*origin).find(
            BuildQueue,
            BuildPackageJob.job == BuildQueue.jobID,
            BuildPackageJob.build == Build.id,
            Build.distroarchseries == DistroArchSeries.id,
            Build.archive == Archive.id,
            DistroArchSeries.processorfamilyID == Processor.familyID,
            Build.buildstate == BuildStatus.NEEDSBUILD,
            Archive.enabled == True,
            Processor.id == processor.id,
            Archive.require_virtualized == virtualized,
            )

        return (queue.count(), queue.sum(BuildQueue.estimated_duration))

    def pollBuilders(self, logger, txn):
        """See IBuilderSet."""
        logger.info("Slave Scan Process Initiated.")

        buildMaster = BuilddMaster(logger, txn)

        logger.info("Setting Builders.")
        # Put every distroarchseries we can find into the build master.
        for archseries in getUtility(IDistroArchSeriesSet):
            buildMaster.addDistroArchSeries(archseries)
            buildMaster.setupBuilders(archseries)

        logger.info("Scanning Builders.")
        # Scan all the pending builds, update logtails and retrieve
        # builds where they are completed
        buildMaster.scanActiveBuilders()
        return buildMaster

    def getBuildersForQueue(self, processor, virtualized):
        """See `IBuilderSet`."""
        return Builder.selectBy(builderok=True, processor=processor,
                                virtualized=virtualized)
