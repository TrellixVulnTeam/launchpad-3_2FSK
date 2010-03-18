# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

from __future__ import with_statement

"""Common build base classes."""

__metaclass__ = type

__all__ = ['BuildBase']

import datetime
import logging
import os
import pytz
from cStringIO import StringIO

from storm.store import Store
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import ZopelessTransactionManager
from canonical.launchpad.helpers import filenameToContentType
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.scripts.logger import BufferLogger
from canonical.librarian.utils import copy_and_close
from lp.archiveuploader.uploadpolicy import findPolicyByOptions
from lp.archiveuploader.uploadprocessor import UploadProcessor
from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.interfaces.buildbase import BUILDD_MANAGER_LOG_NAME
from lp.registry.interfaces.pocket import pocketsuffix


UPLOAD_LOG_FILENAME = 'uploader.log'


class BuildBase:
    """A mixin class providing functionality for farm jobs that build a
    package.

    Note: this class does not implement IBuildBase as we currently duplicate
    the properties defined on IBuildBase on the inheriting class tables. 
    BuildBase cannot therefore implement IBuildBase itself, as storm requires
    that the corresponding __storm_table__ be defined for the class. Instead,
    the classes using the BuildBase mixin must ensure that they implement IBuildBase.
    """
    policy_name = 'buildd'

    def getUploadLeaf(self, build_id, now=None):
        """Return a directory name to store build things in.

        :param build_id: The id as returned by the slave, normally
            $BUILD_ID-$BUILDQUEUE_ID
        :param now: The `datetime` to use. If not provided, defaults to now.
        """
        # UPLOAD_LEAF: <TIMESTAMP>-<BUILD_ID>-<BUILDQUEUE_ID>
        if now is None:
            now = datetime.datetime.now()
        return '%s-%s' % (now.strftime("%Y%m%d-%H%M%S"), build_id)

    def getUploadDir(self, upload_leaf):
        """Return the directory that things will be stored in."""
        return os.path.join(config.builddmaster.root, 'incoming', upload_leaf)

    def _getProxiedFileURL(self, library_file):
        """Return the 'http_url' of a `ProxiedLibraryFileAlias`."""
        # Avoiding circular imports.
        from canonical.launchpad.browser.librarian import (
            ProxiedLibraryFileAlias)

        proxied_file = ProxiedLibraryFileAlias(library_file, self)
        return proxied_file.http_url

    @property
    def build_log_url(self):
        """See `IBuildBase`."""
        if self.buildlog is None:
            return None
        return self._getProxiedFileURL(self.buildlog)

    @property
    def upload_log_url(self):
        """See `IBuildBase`."""
        if self.upload_log is None:
            return None
        return self._getProxiedFileURL(self.upload_log)

    def handleStatus(self, status, librarian, slave_status):
        """See `IBuildBase`."""
        logger = logging.getLogger(BUILDD_MANAGER_LOG_NAME)

        method = getattr(self, '_handleStatus_' + status, None)

        if method is None:
            logger.critical("Unknown BuildStatus '%s' for builder '%s'"
                            % (status, self.buildqueue_record.builder.url))
            return

        method(librarian, slave_status, logger)

    def processUpload(self, leaf, root, logger):
        """Process an upload.
        
        :param leaf: Leaf for this particular upload
        :param root: Root directory for the uploads
        :param logger: A logger object
        """
        class ProcessUploadOptions(object):

            def __init__(self, policy_name, distribution, distroseries, pocket,
                         buildid):
                self.context = policy_name
                self.distro = distribution.name
                self.distroseries = distroseries.name + pocketsuffix[pocket]
                self.buildid = buildid
                self.announce = []

        options = ProcessUploadOptions(self.policy_name, self.distribution,
            self.distroseries, self.pocket, self.id)
        # XXX JRV 20100317: This should not create a mock options 
        # object and derive the policy from that but rather create a
        # policy object in a more sensible way.
        policy = findPolicyByOptions(options)
        processor = UploadProcessor(root, dry_run=False, no_mails=True,
            keep=False, policy_for_distro=lambda distro: policy,
            ztm=ZopelessTransactionManager, log=logger)
        processor.processUploadQueue(leaf)

    def _handleStatus_OK(self, librarian, slave_status, logger):
        """Handle a package that built successfully.

        Once built successfully, we pull the files, store them in a
        directory, store build information and push them through the
        uploader.
        """
        # XXX cprov 2007-07-11 bug=129487: untested code path.
        buildid = slave_status['build_id']
        filemap = slave_status['filemap']

        logger.info("Processing successful build %s from builder %s" % (
            buildid, self.buildqueue_record.builder.name))
        # Explode before collect a binary that is denied in this
        # distroseries/pocket
        if not self.archive.allowUpdatesToReleasePocket():
            assert self.distroseries.canUploadToPocket(self.pocket), (
                "%s (%s) can not be built for pocket %s: illegal status"
                % (self.title, self.id, self.pocket.name))

        # ensure we have the correct build root as:
        # <BUILDMASTER_ROOT>/incoming/<UPLOAD_LEAF>/<TARGET_PATH>/[FILES]
        root = os.path.abspath(config.builddmaster.root)

        # create a single directory to store build result files
        upload_leaf = self.getUploadLeaf(buildid)
        upload_dir = self.getUploadDir(upload_leaf)
        logger.debug("Storing build result at '%s'" % upload_dir)

        # Build the right UPLOAD_PATH so the distribution and archive
        # can be correctly found during the upload:
        #       <archive_id>/distribution_name
        # for all destination archive types.
        upload_path = os.path.join(upload_dir, str(self.archive.id),
                                   self.distribution.name)
        os.makedirs(upload_path)

        slave = removeSecurityProxy(self.buildqueue_record.builder.slave)
        for filename in filemap:
            logger.info("Grabbing file: %s" % filename)
            slave_file = slave.getFile(filemap[filename])
            out_file_name = os.path.join(upload_path, filename)
            out_file = open(out_file_name, "wb")
            copy_and_close(slave_file, out_file)

        uploader_logfilename = os.path.join(upload_dir, UPLOAD_LOG_FILENAME)
        logger.debug("Saving uploader log at '%s'" % uploader_logfilename)

        logger.info("Invoking uploader on %s for %s" % (root, upload_leaf))
        upload_logger = BufferLogger()
        upload_log = self.processUpload(upload_leaf, root, upload_logger)
        uploader_log_content = upload_logger.getvalue()

        # Quick and dirty hack to carry on on process-upload failures
        if os.path.exists(upload_dir):
            logger.warning("The upload directory did not get moved.")
            failed_dir = os.path.join(root, "failed-to-move")
            if not os.path.exists(failed_dir):
                os.mkdir(failed_dir)
            os.rename(upload_dir, os.path.join(failed_dir, upload_leaf))

        original_slave = self.buildqueue_record.builder.slave

        # Store build information, build record was already updated during
        # the binary upload.
        self.storeBuildInfo(librarian, slave_status)

        # Retrive the up-to-date build record and perform consistency
        # checks. The build record should be updated during the binary
        # upload processing, if it wasn't something is broken and needs
        # admins attention. Even when we have a FULLYBUILT build record,
        # if it is not related with at least one binary, there is also
        # a problem.
        # For both situations we will mark the builder as FAILEDTOUPLOAD
        # and the and update the build details (datebuilt, duration,
        # buildlog, builder) in LP. A build-failure-notification will be
        # sent to the lp-build-admin celebrity and to the sourcepackagerelease
        # uploader about this occurrence. The failure notification will
        # also contain the information required to manually reprocess the
        # binary upload when it was the case.
        if (self.buildstate != BuildStatus.FULLYBUILT or
            not self.verifySuccessfulUpload()):
            logger.warning("Build %s upload failed." % self.id)
            self.buildstate = BuildStatus.FAILEDTOUPLOAD
            # Store the upload_log_contents in librarian so it can be
            # accessed by anyone with permission to see the build.
            self.storeUploadLog(uploader_log_content)
            # Notify the build failure.
            self.notify(extra_info=uploader_log_content)
        else:
            logger.info(
                "Gathered %s %d completely" % (
                self.__class__.__name__, self.id))

        # Release the builder for another job.
        self.buildqueue_record.builder.cleanSlave()
        # Remove BuildQueue record.
        self.buildqueue_record.destroySelf()

    def _handleStatus_PACKAGEFAIL(self, librarian, slave_status, logger):
        """Handle a package that had failed to build.

        Build has failed when trying the work with the target package,
        set the job status as FAILEDTOBUILD, store available info and
        remove Buildqueue entry.
        """
        self.buildstate = BuildStatus.FAILEDTOBUILD
        self.storeBuildInfo(librarian, slave_status)
        self.buildqueue_record.builder.cleanSlave()
        self.notify()
        self.buildqueue_record.destroySelf()

    def _handleStatus_DEPFAIL(self, librarian, slave_status, logger):
        """Handle a package that had missing dependencies.

        Build has failed by missing dependencies, set the job status as
        MANUALDEPWAIT, store available information, remove BuildQueue
        entry and release builder slave for another job.
        """
        self.buildstate = BuildStatus.MANUALDEPWAIT
        self.storeBuildInfo(librarian, slave_status)
        logger.critical("***** %s is MANUALDEPWAIT *****"
                        % self.buildqueue_record.builder.name)
        self.buildqueue_record.builder.cleanSlave()
        self.buildqueue_record.destroySelf()

    def _handleStatus_CHROOTFAIL(self, librarian, slave_status,
                                 logger):
        """Handle a package that had failed when unpacking the CHROOT.

        Build has failed when installing the current CHROOT, mark the
        job as CHROOTFAIL, store available information, remove BuildQueue
        and release the builder.
        """
        self.buildstate = BuildStatus.CHROOTWAIT
        self.storeBuildInfo(librarian, slave_status)
        logger.critical("***** %s is CHROOTWAIT *****" %
                        self.buildqueue_record.builder.name)
        self.buildqueue_record.builder.cleanSlave()
        self.notify()
        self.buildqueue_record.destroySelf()

    def _handleStatus_BUILDERFAIL(self, librarian, slave_status, logger):
        """Handle builder failures.

        Build has been failed when trying to build the target package,
        The environment is working well, so mark the job as NEEDSBUILD again
        and 'clean' the builder to do another jobs.
        """
        logger.warning("***** %s has failed *****"
                       % self.buildqueue_record.builder.name)
        self.buildqueue_record.builder.failBuilder(
            "Builder returned BUILDERFAIL when asked for its status")
        # simply reset job
        self.storeBuildInfo(librarian, slave_status)
        self.buildqueue_record.reset()

    def _handleStatus_GIVENBACK(self, librarian, slave_status, logger):
        """Handle automatic retry requested by builder.

        GIVENBACK pseudo-state represents a request for automatic retry
        later, the build records is delayed by reducing the lastscore to
        ZERO.
        """
        logger.warning("***** %s is GIVENBACK by %s *****"
                       % (slave_status['build_id'],
                          self.buildqueue_record.builder.name))
        self.storeBuildInfo(librarian, slave_status)
        # XXX cprov 2006-05-30: Currently this information is not
        # properly presented in the Web UI. We will discuss it in
        # the next Paris Summit, infinity has some ideas about how
        # to use this content. For now we just ensure it's stored.
        self.buildqueue_record.builder.cleanSlave()
        self.buildqueue_record.reset()

    def getLogFromSlave(self):
        """See `IBuildBase`."""
        return self.buildqueue_record.builder.transferSlaveFileToLibrarian(
            'buildlog', self.buildqueue_record.getLogFileName(),
            self.is_private)

    def storeBuildInfo(self, librarian, slave_status):
        """See `IBuildBase`."""
        self.buildlog = self.getLogFromSlave()
        self.builder = self.buildqueue_record.builder
        # XXX cprov 20060615 bug=120584: Currently buildduration includes
        # the scanner latency, it should really be asking the slave for
        # the duration spent building locally.
        self.datebuilt = UTC_NOW
        # We need dynamic datetime.now() instance to be able to perform
        # the time operations for duration.
        RIGHT_NOW = datetime.datetime.now(pytz.timezone('UTC'))
        self.buildduration = RIGHT_NOW - self.buildqueue_record.date_started
        if slave_status.get('dependencies') is not None:
            self.dependencies = unicode(slave_status.get('dependencies'))
        else:
            self.dependencies = None

    def storeUploadLog(self, content):
        """See `IBuildBase`."""
        # The given content is stored in the librarian, restricted as
        # necessary according to the targeted archive's privacy.  The content
        # object's 'upload_log' attribute will point to the
        # `LibrarianFileAlias`.

        assert self.upload_log is None, (
            "Upload log information already exists and cannot be overridden.")

        filename = 'upload_%s_log.txt' % self.id
        contentType = filenameToContentType(filename)
        file_size = len(content)
        file_content = StringIO(content)
        restricted = self.is_private

        library_file = getUtility(ILibraryFileAliasSet).create(
            filename, file_size, file_content, contentType=contentType,
            restricted=restricted)
        self.upload_log = library_file

    def queueBuild(self, suspended=False):
        """See `IBuildBase`"""
        specific_job = self.makeJob()

        # This build queue job is to be created in a suspended state.
        if suspended:
            specific_job.job.suspend()

        duration_estimate = self.estimateDuration()
        queue_entry = BuildQueue(
            estimated_duration=duration_estimate,
            job_type=self.build_farm_job_type,
            job=specific_job.job, processor=specific_job.processor,
            virtualized=specific_job.virtualized)
        Store.of(self).add(queue_entry)
        return queue_entry

