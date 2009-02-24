# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
"""Soyuz buildd slave manager logic."""

__metaclass__ = type

__all__ = [
    'BaseDispatchResult',
    'BuilddManager'
    'FailDispatchResult',
    'RecordingSlave',
    'ResetDispatchResult',
    'buildd_success_result_map',
    ]

import logging
import os

from twisted.application import service
from twisted.internet import reactor, utils, defer
from twisted.internet.threads import deferToThread
from twisted.protocols.policies import TimeoutMixin
from twisted.web.xmlrpc import Proxy, _QueryFactory, QueryProtocol

from zope.component import getUtility
from zope.security.management import endInteraction, newInteraction

from canonical.config import config
from canonical.launchpad.interfaces.build import BuildStatus
from canonical.launchpad.interfaces.builder import IBuilderSet
from canonical.launchpad.webapp import urlappend
from canonical.librarian.db import write_transaction


buildd_success_result_map = {
    'ensurepresent': True,
    'build': 'BuilderStatus.BUILDING',
    }


class FakeZTM:
    """Fake transaction manager."""
    def commit(self):
        pass
    def abort(self):
        pass


class QueryWithTimeoutProtocol(QueryProtocol, TimeoutMixin):
    """XMLRPC query protocol with a configurable timeout."""

    def connectionMade(self):
        QueryProtocol.connectionMade(self)
        self.setTimeout(config.builddmaster.socket_timeout)


class QueryFactoryWithTimeout(_QueryFactory):
    """XMLRPC client facory with timeout support."""
    protocol = QueryWithTimeoutProtocol


class RecordingSlave:
    """An RPC proxy for buildd slaves that records instructions to the latter.

    The idea here is to merely record the instructions that the slave-scanner
    issues to the buildd slaves and "replay" them a bit later in asynchronous
    and parallel fashion.

    By dealing with a number of buildd slaves in parallel we remove *the*
    major slave-scanner throughput issue while avoiding large-scale changes to
    its code base.
    """
    def __init__(self, name, url, vm_host):
        self.name = name
        self.url = url
        self.vm_host = vm_host

        self.resume_requested = False
        self.calls = []

    def __repr__(self):
        return '<%s:%s>' % (self.name, self.url)

    def ensurepresent(self, *args):
        """Download files needed for the build."""
        self.calls.append(('ensurepresent', args))
        result = buildd_success_result_map.get('ensurepresent')
        return (result, 'Download')

    def build(self, *args):
        """Perform the build."""
        self.calls.append(('build', args))
        result = buildd_success_result_map.get('build')
        return (result, args[0])

    def resume(self):
        """Record the request to resume the builder..

        Always succeed.

        :return: a (stdout, stderr, subprocess exitcode) triple
        """
        self.resume_requested = True
        return ('', '', 0)

    def resumeSlave(self):
        """Resume the builder in a asynchronous fashion.

        Used the configuration command-line in the same way
        `BuilddSlave.resume` does.

        :return: a Deferred
        """
        resume_command = config.builddmaster.vm_resume_command % {
            'vm_host': self.vm_host}
        # Twisted API require string and the configuration provides unicode.
        resume_argv = [str(term) for term in resume_command.split()]
        d = utils.getProcessOutputAndValue(resume_argv[0], resume_argv[1:])
        return d


class BaseDispatchResult:
    """Base class for *DispatchResult variations.


    It will be extended to represent dispatching results and allow
    homogeneous processing.
    """

    def __init__(self, slave, info=None):
        self.slave = slave
        self.info = info

    def _cleanJob(self, job):
        """Clean up in case of builder reset or dispatch failure."""
        if job is not None:
            job.build.buildstate = BuildStatus.NEEDSBUILD
            job.builder = None
            job.buildstart = None
            job.logtail = None

    def ___call__(self):
        raise NotImplementedError(
            "Call sites must define an evaluation method.")


class FailDispatchResult(BaseDispatchResult):
    """Represents a communication failure while dispatching a build job..

    When evaluated this object mark the corresponding `IBuilder` as
    'NOK' with the given text as 'failnotes'. It also cleanup the running
    job (`IBuildQueue`).
    """

    def __repr__(self):
        return  '%r failure (%s)' % (self.slave, self.info)

    @write_transaction
    def __call__(self):
        builder = getUtility(IBuilderSet)[self.slave.name]
        builder.failbuilder(self.info)
        self._cleanJob(builder.currentjob)


class ResetDispatchResult(BaseDispatchResult):
    """Represents a failure to reset a builder.

    When evaluated this object simply cleanup the running job
    (`IBuildQueue`).
    """

    def __repr__(self):
        return  '%r reset' % self.slave

    @write_transaction
    def __call__(self):
        builder = getUtility(IBuilderSet)[self.slave.name]
        self._cleanJob(builder.currentjob)


class BuilddManager(service.Service):
    """Build slave manager."""

    # Dispatch result factories, used to build objects of type
    # BaseDispatchResult representing the result of a dispatching chain.
    reset_result = ResetDispatchResult
    fail_result = FailDispatchResult

    def __init__(self):
        # Store for running chains.
        self._deferreds = []

        # Keep track of build slaves that need handling in a scan/dispatch
        # cycle.
        self.remaining_slaves = []

        # Logger setup
        level = logging.INFO
        logger = logging.getLogger('slave-scanner')
        logger.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        logger.addHandler(ch)
        self.logger = logger

    def startService(self):
        """Service entry point, run at the start of a scan/dispatch cycle."""
        self.logger.info('Starting scanning cycle.')
        d = deferToThread(self.scan)
        d.addCallback(self.resumeAndDispatch)
        d.addErrback(self.scanFailed)

    def scanFailed(self, error):
        """Deal with scanning failures."""
        self.logger.info(
            'Scanning failed with: %s' % error.getErrorMessage())
        self.finishCycle()

    def nextCycle(self):
        """Schedule the next scanning cycle."""
        self.logger.debug('Next cycle in 5 seconds.')
        reactor.callLater(5, self.startService)

    def slaveDone(self, slave):
        """Mark slave as done for this cycle."""
        self.logger.info('%r marked as done.' % slave)
        self.remaining_slaves.remove(slave)
        if len(self.remaining_slaves) == 0:
            self.finishCycle()

    def finishCycle(self, r=None):
        """Finishes a slave-scanning cycle.

        Once all the active events were executed:

         * Evaluate pending builder update results;
         * Clean the list of active events (_deferreds);
         * Call `nextCycle`.
        """
        def done(deferred_results):
            self.logger.info('Scanning cycle finished.')
            # We are only interested in returned objects of type
            # BaseDispatchResults, those are the ones that needs evaluation.
            dispatch_results = [
                result for status, result in deferred_results
                if isinstance(result, BaseDispatchResult)]

            # Evaluate then, which will synchronize the database information.
            for result in dispatch_results:
                self.logger.info('%r' % result)
                result()

            # Clean the events stored for this cycle and schedule the
            # next one.
            self._deferreds = []
            self.nextCycle()

            # Return the evaluated events for testing purpose.
            return deferred_results

        self.logger.info('Finishing scanning cycle.')
        dl = defer.DeferredList(self._deferreds, consumeErrors=True)
        dl.addBoth(done)
        return dl

    @write_transaction
    def scan(self):
        """Scan all builders and dispatch build jobs to the idle ones.

        All builders are polled for status and any required post-processing
        actions are performed.

        Subsequently, build job candidates are selected and assigned to the
        idle builders. The necessary build job assignment actions are not
        carried out directly though but merely memorized by the recording
        build slaves.

        In a second stage (see resumeAndDispatch()) each of the latter will be
        handled in an asynchronous and parallel fashion.
        """
        recording_slaves = []

        newInteraction()

        builder_set = getUtility(IBuilderSet)
        # Use FakeZTM to avoid partial commits.
        builder_set.pollBuilders(self.logger, FakeZTM())

        for builder in builder_set:
            self.logger.debug("Considering %s" % builder.name)

            if builder.manual:
                self.logger.debug('Builder is in manual state, ignored.')
                continue

            if not builder.is_available:
                self.logger.debug('Builder is not available, ignored.')
                continue

            candidate = builder.findBuildCandidate()
            if candidate is None:
                self.logger.debug(
                    "No build candidates available for builder.")
                continue

            slave = RecordingSlave(builder.name, builder.url, builder.vm_host)
            builder.setSlaveForTesting(slave)

            builder.dispatchBuildCandidate(candidate)
            recording_slaves.append(slave)

        endInteraction()
        return recording_slaves

    def checkResume(self, response, slave):
        """Verify the results of a slave resume procedure.

        If it failed, it returns a corresponding `ResetDispatchResult`
        dispatch result.
        """
        out, err, code = response
        if code == os.EX_OK:
            return None

        self.slaveDone(slave)
        return self.reset_result(slave)

    def checkDispatch(self, response, method, slave):
        """Verify the results of a slave xmlrpc call.

        If it failed returns a corresponding `FailDispatchResult`.
        Otherwise dispatch the next call if there are any and return None.
        """
        assert method in buildd_success_result_map.keys(), (
            'Unknown slave method %s' % method)
        result = buildd_success_result_map.get(method)

        status, info = response
        if status == result:
            self._mayDispatch(slave)
            return None

        self.slaveDone(slave)
        return self.fail_result(slave, info)

    def resumeAndDispatch(self, recording_slaves):
        """Dispatch existing resume procedure calls and chain dispatching.

        See `RecordingSlave.resumeSlaveHost` for more details.
        """
        self.logger.info('Resuming slaves: %s' % recording_slaves)
        self.remaining_slaves = recording_slaves
        if len(self.remaining_slaves) == 0:
            self.finishCycle()

        for slave in recording_slaves:
            if slave.resume_requested:
                # The buildd slave needs to be reset before we can dispatch
                # builds to it.
                d = slave.resumeSlave()
                d.addCallback(self.checkResume, slave)
            else:
                # Buildd slave is clean, we can dispatch a build to it
                # straightaway.
                d = defer.succeed(None)
            d.addCallback(self.dispatchBuild, slave)
            # Store the active deferred.
            self._deferreds.append(d)

    def dispatchBuild(self, resume_result, slave):
        """Start dispatching a build to a slave.

        If the previous task in chain (slave resuming) has failed it will
        receive a `ResetBuilderRequest` instance as 'resume_result' and
        will immediately return that so the subsequent callback can collect
        it.

        If the slave resuming succeed, it starts the XMLRPC dialog. See
        `_mayDispatch` for more information.
        """
        self.logger.info('Dispatching: %s' % slave)
        if resume_result is not None:
            self.slaveDone(slave)
            return resume_result
        self._mayDispatch(slave)

    def _getProxyForSlave(self, slave):
        """Return a twisted.web.xmlrpc.Proxy for the buildd slave.

        Uses a protocol with timeout support, See QueryFactoryWithTimeout.
        """
        proxy = Proxy(str(urlappend(slave.url, 'rpc')))
        proxy.queryFactory = QueryFactoryWithTimeout
        return proxy

    def _mayDispatch(self, slave):
        """Dispatch the next XMLRPC for the given slave.

        If there are no messages to dispatch return None and mark the slave
        as done for this cycle. Otherwise it will fetch a new XMLRPC proxy,
        dispatch the call and set `checkDispatch` as callback.
        """
        if len(slave.calls) == 0:
            self.slaveDone(slave)
            return

        # Get an XMPRPC proxy for the buildd slave.
        proxy = self._getProxyForSlave(slave)
        method, args = slave.calls.pop(0)
        d = proxy.callRemote(method, *args)
        d.addCallback(self.checkDispatch, method, slave)

        # Store another active event.
        self._deferreds.append(d)
        self.logger.info('%s -> %s(%s)' % (slave, method, args))
