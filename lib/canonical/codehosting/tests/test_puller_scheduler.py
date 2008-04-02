# Copyright 2007-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0702,W0222

__metaclass__ = type

from datetime import datetime
import logging
import os
import textwrap
import unittest

import pytz

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.urlutils import local_path_to_url

from twisted.internet import defer, error, task
from twisted.protocols.basic import NetstringParseError
from twisted.python import failure
from twisted.trial.unittest import TestCase as TrialTestCase

from canonical.codehosting.puller import get_lock_id_for_branch_id, scheduler
from canonical.codehosting.puller.worker import (
    get_canonical_url_for_branch_name)
from canonical.codehosting.tests.helpers import BranchTestCase
from canonical.config import config
from canonical.launchpad.interfaces import BranchType
from canonical.testing import (
    reset_logging, TwistedLayer, TwistedLaunchpadZopelessLayer)
from canonical.launchpad.webapp import errorlog


class FakeBranchStatusClient:

    def __init__(self, branch_queues=None):
        self.branch_queues = branch_queues
        self.calls = []

    def getBranchPullQueue(self, branch_type):
        return defer.succeed(self.branch_queues[branch_type])

    def startMirroring(self, branch_id):
        self.calls.append(('startMirroring', branch_id))
        return defer.succeed(None)

    def mirrorComplete(self, branch_id, revision_id):
        self.calls.append(('mirrorComplete', branch_id, revision_id))
        return defer.succeed(None)

    def mirrorFailed(self, branch_id, revision_id):
        self.calls.append(('mirrorFailed', branch_id, revision_id))
        return defer.succeed(None)


def makeFailure(exception_factory, *args, **kwargs):
    """Make a Failure object from the given exception factory.

    Any other arguments are passed straight on to the factory.
    """
    try:
        raise exception_factory(*args, **kwargs)
    except:
        return failure.Failure()


class TestJobScheduler(unittest.TestCase):

    def setUp(self):
        self.masterlock = 'master.lock'
        # We set the log level to CRITICAL so that the log messages
        # are suppressed.
        logging.basicConfig(level=logging.CRITICAL)

    def tearDown(self):
        reset_logging()

    def makeFakeClient(self, hosted, mirrored, imported):
        return FakeBranchStatusClient(
            {'HOSTED': hosted, 'MIRRORED': mirrored, 'IMPORTED': imported})

    def makeJobScheduler(self, branch_type, branch_tuples):
        if branch_type == BranchType.HOSTED:
            client = self.makeFakeClient(branch_tuples, [], [])
        elif branch_type == BranchType.MIRRORED:
            client = self.makeFakeClient([], branch_tuples, [])
        elif branch_type == BranchType.IMPORTED:
            client = self.makeFakeClient([], [], branch_tuples)
        else:
            self.fail("Unknown branch type: %r" % (branch_type,))
        return scheduler.JobScheduler(
            client, logging.getLogger(), branch_type)

    def testManagerCreatesLocks(self):
        try:
            manager = self.makeJobScheduler(BranchType.HOSTED, [])
            manager.lockfilename = self.masterlock
            manager.lock()
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def testManagerEnforcesLocks(self):
        try:
            manager = self.makeJobScheduler(BranchType.HOSTED, [])
            manager.lockfilename = self.masterlock
            manager.lock()
            anothermanager = self.makeJobScheduler(BranchType.HOSTED, [])
            anothermanager.lockfilename = self.masterlock
            self.assertRaises(scheduler.LockError, anothermanager.lock)
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def _removeLockFile(self):
        if os.path.exists(self.masterlock):
            os.unlink(self.masterlock)


class TestPullerMasterProtocol(TrialTestCase):
    """Tests for the process protocol used by the job manager."""

    layer = TwistedLayer

    class StubPullerListener:
        """Stub listener object that records calls."""

        def __init__(self):
            self.calls = []

        def startMirroring(self):
            self.calls.append('startMirroring')

        def mirrorSucceeded(self, last_revision):
            self.calls.append(('mirrorSucceeded', last_revision))

        def mirrorFailed(self, message, oops):
            self.calls.append(('mirrorFailed', message, oops))


    class StubTransport:
        """Stub transport that implements the minimum for a ProcessProtocol.

        We're manually feeding data to the protocol, so we don't need a real
        transport.
        """

        only_sigkill_kills = False

        def __init__(self, protocol, clock):
            self.protocol = protocol
            self.clock = clock
            self.calls = []

        def loseConnection(self):
            self.calls.append('loseConnection')

        def signalProcess(self, signal_name):
            self.calls.append(('signalProcess', signal_name))
            if not self.only_sigkill_kills or signal_name == 'KILL':
                reason = failure.Failure(error.ProcessTerminated())
                self.clock.callLater(0, self.protocol.processEnded, reason)


    def setUp(self):
        self.arbitrary_branch_id = 1
        self.listener = self.StubPullerListener()
        self.termination_deferred = defer.Deferred()
        self.clock = task.Clock()
        self.protocol = scheduler.PullerMasterProtocol(
            self.termination_deferred, self.listener, self.clock)
        self.protocol.transport = self.StubTransport(
            self.protocol, self.clock)
        self.protocol.connectionMade()

    def assertProtocolSuccess(self):
        """Assert that the protocol saw no unexpected errors."""
        self.assertEqual(None, self.protocol._termination_failure)

    def convertToNetstring(self, string):
        return '%d:%s,' % (len(string), string)

    def sendToProtocol(self, *arguments):
        for argument in arguments:
            self.protocol.outReceived(self.convertToNetstring(str(argument)))

    def test_startMirroring(self):
        """Receiving a startMirroring message notifies the listener."""
        self.sendToProtocol('startMirroring', 0)
        self.assertEqual(['startMirroring'], self.listener.calls)
        self.assertProtocolSuccess()

    def test_mirrorSucceeded(self):
        """Receiving a mirrorSucceeded message notifies the listener."""
        self.sendToProtocol('startMirroring', 0)
        self.listener.calls = []
        self.sendToProtocol('mirrorSucceeded', 1, 1234)
        self.assertEqual([('mirrorSucceeded', '1234')], self.listener.calls)
        self.assertProtocolSuccess()

    def test_mirrorFailed(self):
        """Receiving a mirrorFailed message notifies the listener."""
        self.sendToProtocol('startMirroring', 0)
        self.listener.calls = []
        self.sendToProtocol('mirrorFailed', 2, 'Error Message', 'OOPS')
        self.assertEqual(
            [('mirrorFailed', 'Error Message', 'OOPS')], self.listener.calls)
        self.assertProtocolSuccess()

    def test_timeoutWithoutProgress(self):
        """If we don't receive any messages after the configured timeout
        period, then we kill the child process.
        """
        self.protocol.connectionMade()
        self.clock.advance(config.supermirror.worker_timeout + 1)
        return self.assertFailure(
            self.termination_deferred, scheduler.TimeoutError)

    def assertMessageResetsTimeout(self, *message):
        """Assert that sending the message resets the protocol timeout."""
        self.assertTrue(2 < config.supermirror.worker_timeout)
        self.clock.advance(config.supermirror.worker_timeout - 1)
        self.sendToProtocol(*message)
        self.clock.advance(2)
        self.assertProtocolSuccess()

    def test_progressMadeResetsTimeout(self):
        """Receiving 'progressMade' resets the timeout."""
        self.assertMessageResetsTimeout('progressMade', 0)

    def test_startMirroringResetsTimeout(self):
        """Receiving 'startMirroring' resets the timeout."""
        self.assertMessageResetsTimeout('startMirroring', 0)

    def test_mirrorSucceededDoesNotResetTimeout(self):
        """Receiving 'mirrorSucceeded' doesn't reset the timeout.

        It's possible that in pathological cases, the worker process might
        hang around even after it has said that it's finished. When that
        happens, we want to kill it quickly so that we can continue mirroring
        other branches.
        """
        self.sendToProtocol('startMirroring', 0)
        self.clock.advance(config.supermirror.worker_timeout - 1)
        self.sendToProtocol('mirrorSucceeded', 1, 'rev1')
        self.clock.advance(2)
        return self.assertFailure(
            self.termination_deferred, scheduler.TimeoutError)

    def test_mirrorFailedDoesNotResetTimeout(self):
        """Receiving 'mirrorFailed' doesn't reset the timeout.

        mirrorFailed doesn't reset the timeout for the same reasons as
        mirrorSucceeded.
        """
        self.sendToProtocol('startMirroring', 0)
        self.clock.advance(config.supermirror.worker_timeout - 1)
        self.sendToProtocol('mirrorFailed', 2, 'error message', 'OOPS')
        self.clock.advance(2)
        return self.assertFailure(
            self.termination_deferred, scheduler.TimeoutError)

    def test_processTermination(self):
        """The protocol fires a Deferred when it is terminated."""
        self.protocol.processEnded(failure.Failure(error.ProcessDone(None)))
        return self.termination_deferred

    def test_processTerminationCancelsTimeout(self):
        """When the process ends (for any reason) cancel the timeout."""
        self.protocol._processTerminated(
            failure.Failure(error.ConnectionDone()))
        self.clock.advance(config.supermirror.worker_timeout * 2)
        self.assertProtocolSuccess()

    def test_terminatesWithError(self):
        """When the child process terminates with an unexpected error, raise
        an error that includes the contents of stderr and the exit condition.
        """

        def check_failure(failure):
            self.assertEqual('error message', failure.error)
            return failure

        self.termination_deferred.addErrback(check_failure)

        self.protocol.errReceived('error ')
        self.protocol.errReceived('message')
        self.protocol.processEnded(
            failure.Failure(error.ProcessTerminated(exitCode=1)))

        return self.assertFailure(
            self.termination_deferred, error.ProcessTerminated)

    def test_stderrFailsProcess(self):
        """If the process prints to stderr, then the Deferred fires an
        errback, even if it terminated successfully.
        """

        def check_failure(failure):
            self.assertEqual('error message', failure.error)
            return failure

        self.termination_deferred.addErrback(check_failure)

        self.protocol.errReceived('error ')
        self.protocol.errReceived('message')
        self.protocol.processEnded(failure.Failure(error.ProcessDone(None)))

        return self.termination_deferred

    def test_unrecognizedMessage(self):
        """The protocol notifies the listener when it receives an unrecognized
        message.
        """
        self.protocol.outReceived(self.convertToNetstring('foo'))

        # Give the process time to die.
        self.clock.advance(1)

        def check_failure(exception):
            self.assertEqual(
                [('signalProcess', 'INT')], self.protocol.transport.calls)
            self.assertTrue('foo' in str(exception))

        deferred = self.assertFailure(
            self.termination_deferred, scheduler.BadMessage)

        return deferred.addCallback(check_failure)

    def test_invalidNetstring(self):
        """The protocol terminates the session if it receives an unparsable
        netstring.
        """
        self.protocol.outReceived('foo')

        # Give the process time to die.
        self.clock.advance(1)

        def check_failure(exception):
            self.assertEqual(
                ['loseConnection', ('signalProcess', 'INT')],
                self.protocol.transport.calls)
            self.assertTrue('foo' in str(exception))

        deferred = self.assertFailure(
            self.termination_deferred, NetstringParseError)

        return deferred.addCallback(check_failure)

    def test_interruptThenKill(self):
        """If SIGINT doesn't kill the process, we SIGKILL after 5 seconds."""
        fail = makeFailure(RuntimeError, 'error message')
        self.protocol.transport.only_sigkill_kills = True

        # When the error happens, we SIGINT the process.
        self.protocol.unexpectedError(fail)
        self.assertEqual(
            [('signalProcess', 'INT')],
            self.protocol.transport.calls)

        # After 5 seconds, we send SIGKILL.
        self.clock.advance(6)
        self.assertEqual(
            [('signalProcess', 'INT'), ('signalProcess', 'KILL')],
            self.protocol.transport.calls)

        # SIGKILL is assumed to kill the process.  We check that the
        # failure passed to the termination_deferred is the failure we
        # created above, not the ProcessTerminated that results from
        # the process dying.

        def check_failure(exception):
            self.assertEqual('error message', str(exception))

        deferred = self.assertFailure(
            self.termination_deferred, RuntimeError)

        return deferred.addCallback(check_failure)


class TestPullerMaster(TrialTestCase):

    layer = TwistedLayer

    def setUp(self):
        self.status_client = FakeBranchStatusClient()
        self.arbitrary_branch_id = 1
        self.eventHandler = scheduler.PullerMaster(
            self.arbitrary_branch_id, 'arbitrary-source', 'arbitrary-dest',
            BranchType.HOSTED, logging.getLogger(), self.status_client,
            set(['oops-prefix']))

    def test_unexpectedError(self):
        """The puller master logs an OOPS when it receives an unexpected
        error.
        """
        now = datetime.now(pytz.timezone('UTC'))
        fail = makeFailure(RuntimeError, 'error message')
        self.eventHandler.unexpectedError(fail, now)
        oops = errorlog.globalErrorUtility.getOopsReport(now)
        self.assertEqual(fail.getTraceback(), oops.tb_text)
        self.assertEqual('error message', oops.value)
        self.assertEqual('RuntimeError', oops.type)
        self.assertEqual(
            get_canonical_url_for_branch_name(
                self.eventHandler.unique_name), oops.url)

    def test_startMirroring(self):
        deferred = self.eventHandler.startMirroring()

        def checkMirrorStarted(ignored):
            self.assertEqual(
                [('startMirroring', self.arbitrary_branch_id)],
                self.status_client.calls)

        return deferred.addCallback(checkMirrorStarted)

    def test_mirrorComplete(self):
        arbitrary_revision_id = 'rev1'
        deferred = self.eventHandler.startMirroring()

        def mirrorSucceeded(ignored):
            self.status_client.calls = []
            return self.eventHandler.mirrorSucceeded(arbitrary_revision_id)
        deferred.addCallback(mirrorSucceeded)

        def checkMirrorCompleted(ignored):
            self.assertEqual(
                [('mirrorComplete', self.arbitrary_branch_id,
                  arbitrary_revision_id)],
                self.status_client.calls)
        return deferred.addCallback(checkMirrorCompleted)

    def test_mirrorFailed(self):
        arbitrary_error_message = 'failed'

        deferred = self.eventHandler.startMirroring()

        def mirrorFailed(ignored):
            self.status_client.calls = []
            return self.eventHandler.mirrorFailed(
                arbitrary_error_message, 'oops')
        deferred.addCallback(mirrorFailed)

        def checkMirrorFailed(ignored):
            self.assertEqual(
                [('mirrorFailed', self.arbitrary_branch_id,
                  arbitrary_error_message)],
                self.status_client.calls)
        return deferred.addCallback(checkMirrorFailed)


class TestPullerMasterSpawning(TrialTestCase):

    layer = TwistedLayer

    def setUp(self):
        from twisted.internet import reactor
        self.status_client = FakeBranchStatusClient()
        self.arbitrary_branch_id = 1
        self.available_oops_prefixes = set(['foo'])
        self.eventHandler = scheduler.PullerMaster(
            self.arbitrary_branch_id, 'arbitrary-source', 'arbitrary-dest',
            BranchType.HOSTED, logging.getLogger(), self.status_client,
            self.available_oops_prefixes)
        self._realSpawnProcess = reactor.spawnProcess
        reactor.spawnProcess = self.spawnProcess
        self.oops_prefixes = []

    def tearDown(self):
        from twisted.internet import reactor
        reactor.spawnProcess = self._realSpawnProcess

    def spawnProcess(self, protocol, executable, arguments, env):
        self.oops_prefixes.append(arguments[-1])

    def test_getsOopsPrefixFromSet(self):
        # Different workers should have different OOPS prefixes. They get
        # those prefixes from a limited set of possible prefixes.
        self.eventHandler.run()
        self.assertEqual(self.available_oops_prefixes, set())
        self.assertEqual(self.oops_prefixes, ['foo'])

    def test_restoresOopsPrefixToSetOnSuccess(self):
        # When a worker finishes running, they restore the OOPS prefix to the
        # set of available prefixes.
        deferred = self.eventHandler.run()
        # Fake a successful run.
        deferred.callback(None)
        def check_available_prefixes(ignored):
            self.assertEqual(self.available_oops_prefixes, set(['foo']))
        return deferred.addCallback(check_available_prefixes)

    def test_restoresOopsPrefixToSetOnFailure(self):
        # When a worker finishes running, they restore the OOPS prefix to the
        # set of available prefixes, even if the worker failed.
        deferred = self.eventHandler.run()
        # Fake a failed run.
        try:
            raise RuntimeError("Spurious error")
        except RuntimeError:
            fail = failure.Failure()
        deferred.errback(fail)
        def check_available_prefixes(ignored):
            self.assertEqual(self.available_oops_prefixes, set(['foo']))
        return deferred.addErrback(check_available_prefixes)

    def test_logOopsWhenNoAvailablePrefix(self):
        # If there are no available prefixes then we log an OOPS and re-raise
        # the error, aborting the rest of the run.

        # Empty the set of available OOPS prefixes
        self.available_oops_prefixes.clear()

        unexpected_errors = []
        def unexpectedError(failure, now=None):
            unexpected_errors.append(failure)
        self.eventHandler.unexpectedError = unexpectedError
        self.assertRaises(KeyError, self.eventHandler.run)
        self.assertEqual(unexpected_errors[0].type, KeyError)


# The common parts of all the worker scripts.  See
# TestPullerMasterIntegration.makePullerMaster for more.
script_header = """\
from optparse import OptionParser
from canonical.codehosting.puller.worker import PullerWorkerProtocol
import sys, time
parser = OptionParser()
(options, arguments) = parser.parse_args()
(source_url, destination_url, branch_id, unique_name,
 branch_type_name, oops_prefix) = arguments
from bzrlib import branch
branch = branch.Branch.open(destination_url)
protocol = PullerWorkerProtocol(sys.stdout)
"""


class TestPullerMasterIntegration(BranchTestCase, TrialTestCase):
    """Tests for the puller master that launch sub-processes."""

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        BranchTestCase.setUp(self)
        self.db_branch = self.makeBranch(BranchType.HOSTED)
        self.bzr_tree = self.createTemporaryBazaarBranchAndTree('src-branch')
        self.client = FakeBranchStatusClient()

    def run(self, result):
        # We want to use Trial's run() method so we can return Deferreds.
        return TrialTestCase.run(self, result)

    def _dumpError(self, failure):
        # XXX: JonathanLange 2007-10-17: It would be nice if we didn't have to
        # do this manually, and instead the test automatically gave us the
        # full error.
        error = getattr(failure, 'error', 'No stderr stored.')
        print error
        return failure

    def makePullerMaster(self, cls=scheduler.PullerMaster, script_text=None):
        """Construct a PullerMaster suited to the test environment.

        :param cls: The class of the PullerMaster to construct, defaulting to
            the base PullerMaster.
        :param script_text: If passed, set up the master to run a custom
            script instead of 'scripts/mirror-branch.py'.  The passed text
            will be passed through textwrap.dedent() and appended to
            `script_header` (see above) which means the text can refer to the
            worker command line arguments, the destination branch and an
            instance of PullerWorkerProtocol.
        """
        puller_master = cls(
            self.db_branch.id, local_path_to_url('src-branch'),
            self.db_branch.unique_name, self.db_branch.branch_type,
            logging.getLogger(), self.client,
            set([config.error_reports.oops_prefix]))
        puller_master.destination_url = os.path.abspath('dest-branch')
        if script_text is not None:
            script = open('script.py', 'w')
            script.write(script_header + textwrap.dedent(script_text))
            script.close()
            puller_master.path_to_script = os.path.abspath('script.py')
        return puller_master

    def doDefaultMirroring(self):
        """Run the subprocess to do the mirroring and check that it succeeded.
        """
        revision_id = self.bzr_tree.branch.last_revision()

        puller_master = self.makePullerMaster()
        deferred = puller_master.mirror()

        def check_authserver_called(ignored):
            self.assertEqual(
                [('startMirroring', self.db_branch.id),
                 ('mirrorComplete', self.db_branch.id, revision_id)],
                self.client.calls)
            return ignored
        deferred.addCallback(check_authserver_called)

        def check_branch_mirrored(ignored):
            self.assertEqual(
                revision_id,
                Branch.open(puller_master.destination_url).last_revision())
            return ignored
        deferred.addCallback(check_branch_mirrored)

        return deferred

    def test_mirror(self):
        # Actually mirror a branch using a worker sub-process.
        #
        # This test actually launches a worker process and makes sure that it
        # runs successfully and that we report the successful run.
        return self.doDefaultMirroring().addErrback(self._dumpError)

    def test_lock_with_magic_id(self):
        # When the subprocess locks a branch, it is locked with the right ID.
        class PullerMasterProtocolWithLockID(scheduler.PullerMasterProtocol):
            """Subclass of PullerMasterProtocol that defines a lock_id method.

            This protocol defines a method that records on the listener the
            lock id reported by the subprocess.
            """

            def do_lock_id(self, id):
                """Record the lock id on the listener."""
                self.listener.lock_ids.append(id)


        class PullerMasterWithLockID(scheduler.PullerMaster):
            """A subclass of PullerMaster that allows recording of lock ids.
            """

            master_protocol_class = PullerMasterProtocolWithLockID

        check_lock_id_script = """
        branch.lock_write()
        protocol.sendEvent(
            'lock_id', branch.control_files._lock.peek()['user'])
        sys.stdout.flush()
        branch.unlock()
        """

        puller_master = self.makePullerMaster(
            PullerMasterWithLockID, check_lock_id_script)
        puller_master.lock_ids = []

        # We need to create a branch at the destination_url, so that the
        # subprocess can actually create a lock.
        destination_branch = BzrDir.create_branch_convenience(
            puller_master.destination_url)

        deferred = puller_master.mirror().addErrback(self._dumpError)

        def checkID(ignored):
            self.assertEqual(
                puller_master.lock_ids,
                [get_lock_id_for_branch_id(puller_master.branch_id)])

        return deferred.addCallback(checkID)

    def _run_with_destination_locked(self, func, lock_id_delta=0):
        """Run the function `func` with the destination branch locked.

        :param func: The function that is to be run with the destination
            branch locked.  It will be called no arguments and is expected to
            return a deferred.
        :param lock_id_delta: By default, the destination branch will be
            locked as if by another worker process for the same branch.  If
            lock_id_delta != 0, the lock id will be different, so the worker
            should not break it.
        """

        # Lots of moving parts :/

        # We launch two subprocesses, one that locks the branch, tells us that
        # its done so and waits to be killed (we need to do the locking in a
        # subprocess to get the lock id to be right, see the above test).

        # When the first process tells us that it has locked the branch, we
        # run the provided function.  When the deferred this returns is called
        # or erred back, we keep hold of the result and send a signal to kill
        # the first process and wait for it to die.

        class LockingPullerMasterProtocol(scheduler.PullerMasterProtocol):
            """Extend PullerMasterProtocol with a 'branchLocked' method."""

            def do_branchLocked(self):
                """Notify the listener that the branch is now locked."""
                self.listener.branchLocked()

            def connectionMade(self):
                """Record the protocol instance on the listener.

                Normally the PullerMaster doesn't need to find the protocol
                again, but we need to to be able to kill the subprocess after
                the test has completed.
                """
                self.listener.protocol = self

        class LockingPullerMaster(scheduler.PullerMaster):
            """Extend PullerMaster for the purposes of the test."""

            master_protocol_class = LockingPullerMasterProtocol

            # This is where the result of the deferred returned by 'func' will
            # be stored.  We need to store seen_final_result and final_result
            # separately because we don't have any control over what
            # final_result may be (in the successful case at the time of
            # writing it is None).
            seen_final_result = False
            final_result = None

            def branchLocked(self):
                """Called when the subprocess has locked the branch.

                When this has happened, we can proceed with the main part of
                the test.
                """
                branch_locked_deferred.callback(None)

        lock_and_wait_script = """
        branch.lock_write()
        protocol.sendEvent('branchLocked')
        sys.stdout.flush()
        time.sleep(3600)
        """

        # branch_locked_deferred will be called back when the subprocess locks
        # the branch.
        branch_locked_deferred = defer.Deferred()

        # So we add the function passed in as a callback to
        # branch_locked_deferred.
        def wrapper(ignore):
            return func()
        branch_locked_deferred.addCallback(wrapper)

        # When it is done, successfully or not, we store the result on the
        # puller master and kill the locking subprocess.
        def cleanup(result):
            locking_puller_master.seen_final_result = True
            locking_puller_master.final_result = result
            try:
                locking_puller_master.protocol.transport.signalProcess('INT')
            except error.ProcessExitedAlready:
                # We can only get here if the locking subprocess somehow
                # manages to crash between locking the branch and being killed
                # by us.  In that case, locking_process_errback below will
                # cause the test to fail, so just do nothing here.
                pass
        branch_locked_deferred.addBoth(cleanup)

        locking_puller_master = self.makePullerMaster(
            LockingPullerMaster, lock_and_wait_script)
        locking_puller_master.branch_id += lock_id_delta

        # We need to create a branch at the destination_url, so that the
        # subprocess can actually create a lock.
        destination_branch = BzrDir.create_branch_convenience(
            locking_puller_master.destination_url)

        # Because when the deferred returned by 'func' is done we kill the
        # locking subprocess, we know that when the subprocess is done, the
        # test is done (note that this also applies if the locking script
        # fails to start up properly for some reason).
        locking_process_deferred = locking_puller_master.mirror()

        def locking_process_callback(ignored):
            # There's no way the process should have exited normally!
            self.fail("Subprocess exited normally!?")

        def locking_process_errback(failure):
            # Exiting abnormally is expected, but there are two sub-cases:
            if not locking_puller_master.seen_final_result:
                # If the locking subprocess exits abnormally before we send
                # the signal to kill it, that's bad.
                return failure
            else:
                # Afterwards, though that's the whole point :)
                # Return the result of the function passed in.
                return locking_puller_master.final_result

        return locking_process_deferred.addCallbacks(
            locking_process_callback, locking_process_errback)

    def test_mirror_with_destination_self_locked(self):
        # If the destination branch was locked by another worker, the worker
        # should break the lock and mirror the branch regardless.
        deferred = self._run_with_destination_locked(self.doDefaultMirroring)
        return deferred.addErrback(self._dumpError)

    def test_mirror_with_destination_locked_by_another(self):
        # When the destination branch is locked with a different lock it, the
        # worker should *not* break the lock and instead fail.

        # We have to use a custom worker script to lower the time we wait for
        # the lock for (the default is five minutes, too long for a test!)
        lower_timeout_script = """
        from bzrlib import lockdir
        lockdir._DEFAULT_TIMEOUT_SECONDS = 2.0
        from canonical.launchpad.interfaces import BranchType
        from canonical.codehosting.puller.worker import (
            PullerWorker, install_worker_ui_factory)
        branch_type = BranchType.items[branch_type_name]
        install_worker_ui_factory(protocol)
        PullerWorker(
            source_url, destination_url, int(branch_id), unique_name,
            branch_type, protocol).mirror()
        """

        def mirror_fails_to_unlock():
            puller_master = self.makePullerMaster(
                script_text=lower_timeout_script)
            deferred = puller_master.mirror()
            def check_mirror_failed(ignored):
                self.assertEqual(len(self.client.calls), 2)
                start_mirroring_call, mirror_failed_call = self.client.calls
                self.assertEqual(
                    start_mirroring_call,
                    ('startMirroring', self.db_branch.id))
                self.assertEqual(
                    mirror_failed_call[:2],
                    ('mirrorFailed', self.db_branch.id))
                self.assertTrue(
                    "Could not acquire lock" in mirror_failed_call[2])
                return ignored
            deferred.addCallback(check_mirror_failed)
            return deferred

        deferred = self._run_with_destination_locked(
            mirror_fails_to_unlock, 1)

        return deferred.addErrback(self._dumpError)

    def mirror_with_unexpected_failure(self):
        """Attempt to mirror using a script that fails with a NameError.

        The script will fail with a distinctive NameError before reporting
        success or failure, and this function will return a deferred that
        calls back with the ProcessTerminated exception that results.
        """
        unexpected_error_script = """
        OOGA_BOOGA
        """

        puller_master = self.makePullerMaster(
            script_text=unexpected_error_script)

        destination_branch = BzrDir.create_branch_convenience(
            puller_master.destination_url)

        # "Mirroring" the branch will fail.
        return self.assertFailure(
            puller_master.mirror(), error.ProcessTerminated)

    def test_mirror_with_unexpected_failure(self):
        # If the puller worker script fails before recording success or
        # failure, the branch is considered to have failed.

        # We run a "mirror" that will fail with a distinctive
        # NameError:
        deferred = self.mirror_with_unexpected_failure()

        # And check that the process monitoring machinery will call
        # "mirrorFailed" for the branch.
        def check_mirror_failed(ignored):
            self.assertEqual(len(self.client.calls), 1)
            mirror_failed_call, = self.client.calls
            self.assertEqual(
                mirror_failed_call[:2],
                ('mirrorFailed', self.db_branch.id))
            self.assertTrue(
                "OOGA_BOOGA" in mirror_failed_call[2])
            return ignored
        deferred.addCallback(check_mirror_failed)

        return deferred.addErrback(self._dumpError)

    def test_mirror_with_unexpected_failure_and_failing_authserver(self):
        # If the puller worker script fails before recording success
        # or failure _and_ the call to the authserver to record this
        # failure fails, there's not much we can do, but we should
        # exit cleanly and not hang.

        class FailingFakeBranchStatusClient(FakeBranchStatusClient):
            def mirrorFailed(self, branch_id, revision_id):
                return defer.fail(Exception())
        self.client = FailingFakeBranchStatusClient()

        deferred = self.mirror_with_unexpected_failure()

        return deferred.addErrback(self._dumpError)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
