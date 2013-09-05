# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Soyuz buildd slave manager logic."""

__metaclass__ = type

__all__ = [
    'BuilddManager',
    'BUILDD_MANAGER_LOG_NAME',
    ]

import logging

import transaction
from twisted.application import service
from twisted.internet import (
    defer,
    reactor,
    )
from twisted.internet.task import LoopingCall
from twisted.python import log
from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interactor import BuilderInteractor
from lp.buildmaster.interfaces.builder import (
    BuildDaemonError,
    BuildSlaveFailure,
    CannotBuild,
    CannotFetchFile,
    CannotResumeHost,
    )
from lp.buildmaster.model.builder import Builder
from lp.services.propertycache import get_property_cache


BUILDD_MANAGER_LOG_NAME = "slave-scanner"


def get_builder(name):
    """Helper to return the builder given the slave for this request."""
    # Avoiding circular imports.
    from lp.buildmaster.interfaces.builder import IBuilderSet
    return getUtility(IBuilderSet)[name]


@defer.inlineCallbacks
def assessFailureCounts(logger, interactor, exception):
    """View builder/job failure_count and work out which needs to die.

    :return: A Deferred that fires either immediately or after a virtual
        slave has been reset.
    """
    # builder.currentjob hides a complicated query, don't run it twice.
    # See bug 623281 (Note that currentjob is a cachedproperty).

    builder = interactor.builder
    del get_property_cache(builder).currentjob
    current_job = builder.currentjob
    if current_job is None:
        job_failure_count = 0
    else:
        job_failure_count = current_job.specific_job.build.failure_count

    if builder.failure_count == job_failure_count and current_job is not None:
        # If the failure count for the builder is the same as the
        # failure count for the job being built, then we cannot
        # tell whether the job or the builder is at fault. The  best
        # we can do is try them both again, and hope that the job
        # runs against a different builder.
        current_job.reset()
        del get_property_cache(builder).currentjob
        return

    if builder.failure_count > job_failure_count:
        # The builder has failed more than the jobs it's been
        # running.

        # Re-schedule the build if there is one.
        if current_job is not None:
            current_job.reset()

        # We are a little more tolerant with failing builders than
        # failing jobs because sometimes they get unresponsive due to
        # human error, flaky networks etc.  We expect the builder to get
        # better, whereas jobs are very unlikely to get better.
        if builder.failure_count >= (
                Builder.RESET_THRESHOLD * Builder.RESET_FAILURE_THRESHOLD):
            # We've already tried resetting it enough times, so we have
            # little choice but to give up.
            builder.failBuilder(str(exception))
        elif builder.failure_count % Builder.RESET_THRESHOLD == 0:
            # The builder is dead, but in the virtual case it might be worth
            # resetting it.
            yield interactor.resetOrFail(logger, exception)
    else:
        # The job is the culprit!  Override its status to 'failed'
        # to make sure it won't get automatically dispatched again,
        # and remove the buildqueue request.  The failure should
        # have already caused any relevant slave data to be stored
        # on the build record so don't worry about that here.
        builder.resetFailureCount()
        build_job = current_job.specific_job.build
        build_job.updateStatus(BuildStatus.FAILEDTOBUILD)
        builder.currentjob.destroySelf()

        # N.B. We could try and call _handleStatus_PACKAGEFAIL here
        # but that would cause us to query the slave for its status
        # again, and if the slave is non-responsive it holds up the
        # next buildd scan.
    del get_property_cache(builder).currentjob


class SlaveScanner:
    """A manager for a single builder."""

    # The interval between each poll cycle, in seconds.  We'd ideally
    # like this to be lower but 15 seems a reasonable compromise between
    # responsivity and load on the database server, since in each cycle
    # we can run quite a few queries.
    #
    # NB. This used to be as low as 5 but as more builders are added to
    # the farm this rapidly increases the query count, PG load and this
    # process's load.  It's backed off until we come up with a better
    # algorithm for polling.
    SCAN_INTERVAL = 15

    # The time before deciding that a cancelling builder has failed, in
    # seconds.  This should normally be a multiple of SCAN_INTERVAL, and
    # greater than abort_timeout in launchpad-buildd's slave BuildManager.
    CANCEL_TIMEOUT = 180

    def __init__(self, builder_name, logger, clock=None):
        self.builder_name = builder_name
        self.logger = logger
        # Use the clock if provided, so that tests can advance it.  Use the
        # reactor by default.
        if clock is None:
            clock = reactor
        self._clock = clock
        self.date_cancel = None

    def startCycle(self):
        """Scan the builder and dispatch to it or deal with failures."""
        self.loop = LoopingCall(self.singleCycle)
        self.loop.clock = self._clock
        self.stopping_deferred = self.loop.start(self.SCAN_INTERVAL)
        return self.stopping_deferred

    def stopCycle(self):
        """Terminate the LoopingCall."""
        self.loop.stop()

    def singleCycle(self):
        self.logger.debug("Scanning builder: %s" % self.builder_name)
        d = self.scan()

        d.addErrback(self._scanFailed)
        return d

    @defer.inlineCallbacks
    def _scanFailed(self, failure):
        """Deal with failures encountered during the scan cycle.

        1. Print the error in the log
        2. Increment and assess failure counts on the builder and job.

        :return: A Deferred that fires either immediately or after a virtual
            slave has been reset.
        """
        # Make sure that pending database updates are removed as it
        # could leave the database in an inconsistent state (e.g. The
        # job says it's running but the buildqueue has no builder set).
        transaction.abort()

        # If we don't recognise the exception include a stack trace with
        # the error.
        error_message = failure.getErrorMessage()
        if failure.check(
            BuildSlaveFailure, CannotBuild, CannotResumeHost,
            BuildDaemonError, CannotFetchFile):
            self.logger.info("Scanning %s failed with: %s" % (
                self.builder_name, error_message))
        else:
            self.logger.info("Scanning %s failed with: %s\n%s" % (
                self.builder_name, failure.getErrorMessage(),
                failure.getTraceback()))

        # Decide if we need to terminate the job or reset/fail the builder.
        builder = get_builder(self.builder_name)
        try:
            builder.handleFailure(self.logger)
            yield assessFailureCounts(
                self.logger, BuilderInteractor(builder), failure.value)
            transaction.commit()
        except Exception:
            # Catastrophic code failure! Not much we can do.
            self.logger.error(
                "Miserable failure when trying to handle failure:\n",
                exc_info=True)
            transaction.abort()

    @defer.inlineCallbacks
    def checkCancellation(self, builder):
        """See if there is a pending cancellation request.

        If the current build is in status CANCELLING then terminate it
        immediately.

        :return: A deferred whose value is True if we recovered the builder
            by resuming a slave host, so that there is no need to update its
            status.
        """
        buildqueue = self.builder.currentjob
        if not buildqueue:
            self.date_cancel = None
            defer.returnValue(False)
        build = buildqueue.specific_job.build
        if build.status != BuildStatus.CANCELLING:
            self.date_cancel = None
            defer.returnValue(False)

        try:
            if self.date_cancel is None:
                self.logger.info("Cancelling build '%s'" % build.title)
                yield self.interactor.requestAbort()
                self.date_cancel = self._clock.seconds() + self.CANCEL_TIMEOUT
                defer.returnValue(False)
            else:
                # The BuildFarmJob will normally set the build's status to
                # something other than CANCELLING once the builder responds to
                # the cancel request.  This timeout is in case it doesn't.
                if self._clock.seconds() < self.date_cancel:
                    self.logger.info(
                        "Waiting for build '%s' to cancel" % build.title)
                    defer.returnValue(False)
                else:
                    raise BuildSlaveFailure(
                        "Build '%s' cancellation timed out" % build.title)
        except Exception as e:
            self.logger.info(
                "Build '%s' on %s failed to cancel" %
                (build.title, self.builder.name))
            self.date_cancel = None
            buildqueue.cancel()
            transaction.commit()
            value = yield self.interactor.resetOrFail(self.logger, e)
            # value is not None if we resumed a slave host.
            defer.returnValue(value is not None)

    @defer.inlineCallbacks
    def scan(self, builder=None, interactor=None):
        """Probe the builder and update/dispatch/collect as appropriate.

        There are several steps to scanning:

        1. If the builder is marked as "ok" then probe it to see what state
            it's in.  This is where lost jobs are rescued if we think the
            builder is doing something that it later tells us it's not,
            and also where the multi-phase abort procedure happens.
            See IBuilder.rescueIfLost, which is called by
            IBuilder.updateStatus().
        2. If the builder is still happy, we ask it if it has an active build
            and then either update the build in Launchpad or collect the
            completed build. (builder.updateBuild)
        3. If the builder is not happy or it was marked as unavailable
            mid-build, we need to reset the job that we thought it had, so
            that the job is dispatched elsewhere.
        4. If the builder is idle and we have another build ready, dispatch
            it.

        :return: A Deferred that fires when the scan is complete, whose
            value is A `BuilderSlave` if we dispatched a job to it, or None.
        """
        # We need to re-fetch the builder object on each cycle as the
        # Storm store is invalidated over transaction boundaries.

        if self.logger:
            self.logger.debug("Scanning %s" % self.builder_name)

        self.builder = builder or get_builder(self.builder_name)
        self.interactor = interactor or BuilderInteractor(self.builder)

        if self.builder.builderok:
            cancelled = yield self.checkCancellation(self.builder)
            if cancelled:
                return
            lost = yield self.interactor.rescueIfLost(self.logger)
            if lost:
                if self.builder.currentjob is not None:
                    # The DB has a job assigned, but it and the slave
                    # disagree. rescueIfLost is already cleaning up the
                    # slave as necessary, so let's free the DB build to
                    # be dispatched elsewhere.
                    self.logger.warn(
                        "%s is lost. Resetting BuildQueue %d.",
                        self.builder.name, self.builder.currentjob.id)
                    self.builder.currentjob.reset()
                    transaction.commit()
                return
        else:
            if self.builder.currentjob is not None:
                self.logger.warn(
                    "%s was made unavailable. Resetting BuildQueue %d.",
                    self.builder.name, self.builder.currentjob.id)
                self.builder.currentjob.reset()
                transaction.commit()

        # Commit the changes done while possibly rescuing jobs, to
        # avoid holding table locks.
        transaction.commit()

        buildqueue = self.builder.currentjob
        if buildqueue is not None:
            # Scan the slave and get the logtail, or collect the build
            # if it's ready.  Yes, "updateBuild" is a bad name.
            yield self.interactor.updateBuild(buildqueue)

        # If the builder is in manual mode, don't dispatch anything.
        if self.builder.manual:
            self.logger.debug(
                '%s is in manual mode, not dispatching.' %
                self.builder.name)
            return

        # If the builder is marked unavailable, don't dispatch anything.
        # Additionaly, because builders can be removed from the pool at
        # any time, we need to see if we think there was a build running
        # on it before it was marked unavailable. In this case we reset
        # the build thusly forcing it to get re-dispatched to another
        # builder.
        available = yield self.interactor.isAvailable()
        if not available:
            return

        # See if there is a job we can dispatch to the builder slave.
        yield self.interactor.findAndStartJob()
        if self.builder.currentjob is not None:
            # After a successful dispatch we can reset the
            # failure_count.
            self.builder.resetFailureCount()
            transaction.commit()


class NewBuildersScanner:
    """If new builders appear, create a scanner for them."""

    # How often to check for new builders, in seconds.
    SCAN_INTERVAL = 300

    def __init__(self, manager, clock=None):
        self.manager = manager
        # Use the clock if provided, it's so that tests can
        # advance it.  Use the reactor by default.
        if clock is None:
            clock = reactor
        self._clock = clock
        # Avoid circular import.
        from lp.buildmaster.interfaces.builder import IBuilderSet
        self.current_builders = [
            builder.name for builder in getUtility(IBuilderSet)]

    def stop(self):
        """Terminate the LoopingCall."""
        self.loop.stop()

    def scheduleScan(self):
        """Schedule a callback SCAN_INTERVAL seconds later."""
        self.loop = LoopingCall(self.scan)
        self.loop.clock = self._clock
        self.stopping_deferred = self.loop.start(self.SCAN_INTERVAL)
        return self.stopping_deferred

    def scan(self):
        """If a new builder appears, create a SlaveScanner for it."""
        new_builders = self.checkForNewBuilders()
        self.manager.addScanForBuilders(new_builders)

    def checkForNewBuilders(self):
        """See if any new builders were added."""
        # Avoid circular import.
        from lp.buildmaster.interfaces.builder import IBuilderSet
        new_builders = set(
            builder.name for builder in getUtility(IBuilderSet))
        old_builders = set(self.current_builders)
        extra_builders = new_builders.difference(old_builders)
        self.current_builders.extend(extra_builders)
        return list(extra_builders)


class BuilddManager(service.Service):
    """Main Buildd Manager service class."""

    def __init__(self, clock=None):
        self.builder_slaves = []
        self.logger = self._setupLogger()
        self.new_builders_scanner = NewBuildersScanner(
            manager=self, clock=clock)

    def _setupLogger(self):
        """Set up a 'slave-scanner' logger that redirects to twisted.

        Make it less verbose to avoid messing too much with the old code.
        """
        level = logging.INFO
        logger = logging.getLogger(BUILDD_MANAGER_LOG_NAME)

        # Redirect the output to the twisted log module.
        channel = logging.StreamHandler(log.StdioOnnaStick())
        channel.setLevel(level)
        channel.setFormatter(logging.Formatter('%(message)s'))

        logger.addHandler(channel)
        logger.setLevel(level)
        return logger

    def startService(self):
        """Service entry point, called when the application starts."""

        # Get a list of builders and set up scanners on each one.

        # Avoiding circular imports.
        from lp.buildmaster.interfaces.builder import IBuilderSet
        builder_set = getUtility(IBuilderSet)
        builders = [builder.name for builder in builder_set]
        self.addScanForBuilders(builders)
        self.new_builders_scanner.scheduleScan()

        # Events will now fire in the SlaveScanner objects to scan each
        # builder.

    def stopService(self):
        """Callback for when we need to shut down."""
        # XXX: lacks unit tests
        # All the SlaveScanner objects need to be halted gracefully.
        deferreds = [slave.stopping_deferred for slave in self.builder_slaves]
        deferreds.append(self.new_builders_scanner.stopping_deferred)

        self.new_builders_scanner.stop()
        for slave in self.builder_slaves:
            slave.stopCycle()

        # The 'stopping_deferred's are called back when the loops are
        # stopped, so we can wait on them all at once here before
        # exiting.
        d = defer.DeferredList(deferreds, consumeErrors=True)
        return d

    def addScanForBuilders(self, builders):
        """Set up scanner objects for the builders specified."""
        for builder in builders:
            slave_scanner = SlaveScanner(builder, self.logger)
            self.builder_slaves.append(slave_scanner)
            slave_scanner.startCycle()

        # Return the slave list for the benefit of tests.
        return self.builder_slaves
