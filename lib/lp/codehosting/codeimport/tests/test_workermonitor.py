# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the CodeImportWorkerMonitor and related classes."""

__metaclass__ = type
__all__ = [
    'nuke_codeimport_sample_data']


import os
import shutil
import StringIO
import tempfile
import unittest

from bzrlib.branch import Branch
from bzrlib.tests import TestCase as BzrTestCase

from twisted.internet import defer, error, protocol, reactor
from twisted.trial.unittest import TestCase as TrialTestCase

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.testing.layers import (
    TwistedLayer, TwistedLaunchpadZopelessLayer)
from canonical.twistedsupport.tests.test_processmonitor import (
    makeFailure, ProcessTestsMixin)
from lp.code.enums import CodeImportResultStatus, CodeImportReviewStatus
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.codeimportjob import (
    ICodeImportJobSet, ICodeImportJobWorkflow)
from lp.code.model.codeimport import CodeImport
from lp.code.model.codeimportjob import CodeImportJob
from lp.codehosting import load_optional_plugin
from lp.codehosting.codeimport.worker import (
    CodeImportSourceDetails, get_default_bazaar_branch_store)
from lp.codehosting.codeimport.workermonitor import (
    CodeImportWorkerMonitor, CodeImportWorkerMonitorProtocol, ExitQuietly,
    read_only_transaction)
from lp.codehosting.codeimport.tests.servers import (
    CVSServer, GitServer, SubversionServer, _make_silent_logger)
from lp.codehosting.codeimport.tests.test_worker import (
    clean_up_default_stores_for_import)
from lp.testing import login, logout
from lp.testing.factory import LaunchpadObjectFactory


class TestWorkerMonitorProtocol(ProcessTestsMixin, TrialTestCase):

    layer = TwistedLayer

    class StubWorkerMonitor:

        def __init__(self):
            self.calls = []

        def updateHeartbeat(self, tail):
            self.calls.append(('updateHeartbeat', tail))

    def setUp(self):
        self.worker_monitor = self.StubWorkerMonitor()
        self.log_file = StringIO.StringIO()
        ProcessTestsMixin.setUp(self)

    def makeProtocol(self):
        """See `ProcessTestsMixin.makeProtocol`."""
        return CodeImportWorkerMonitorProtocol(
            self.termination_deferred, self.worker_monitor, self.log_file,
            self.clock)

    def test_callsUpdateHeartbeatInConnectionMade(self):
        # The protocol calls updateHeartbeat() as it is connected to the
        # process.
        # connectionMade() is called during setUp().
        self.assertEqual(
            self.worker_monitor.calls,
            [('updateHeartbeat', '')])

    def test_callsUpdateHeartbeatRegularly(self):
        # The protocol calls 'updateHeartbeat' on the worker_monitor every
        # config.codeimportworker.heartbeat_update_interval seconds.
        # Forget the call in connectionMade()
        self.worker_monitor.calls = []
        # Advance the simulated time a little to avoid fencepost errors.
        self.clock.advance(0.1)
        # And check that updateHeartbeat is called at the frequency we expect:
        for i in range(4):
            self.protocol.resetTimeout()
            self.assertEqual(
                self.worker_monitor.calls,
                [('updateHeartbeat', '')]*i)
            self.clock.advance(
                config.codeimportworker.heartbeat_update_interval)

    def test_updateHeartbeatStopsOnProcessExit(self):
        # updateHeartbeat is not called after the process has exited.
        # Forget the call in connectionMade()
        self.worker_monitor.calls = []
        self.simulateProcessExit()
        # Advance the simulated time past the time the next update is due.
        self.clock.advance(
            config.codeimportworker.heartbeat_update_interval + 1)
        # Check that updateHeartbeat was not called.
        self.assertEqual(self.worker_monitor.calls, [])

    def test_outReceivedWritesToLogFile(self):
        # outReceived writes the data it is passed into the log file.
        output = ['some data\n', 'some more data\n']
        self.protocol.outReceived(output[0])
        self.assertEqual(self.log_file.getvalue(), output[0])
        self.protocol.outReceived(output[1])
        self.assertEqual(self.log_file.getvalue(), output[0] + output[1])

    def test_outReceivedUpdatesTail(self):
        # outReceived updates the tail of the log, currently and arbitrarily
        # defined to be the last 5 lines of the log.
        lines = ['line %d' % number for number in range(1, 7)]
        self.protocol.outReceived('\n'.join(lines[:3]) + '\n')
        self.assertEqual(
            self.protocol._tail, 'line 1\nline 2\nline 3\n')
        self.protocol.outReceived('\n'.join(lines[3:]) + '\n')
        self.assertEqual(
            self.protocol._tail, 'line 3\nline 4\nline 5\nline 6\n')


class TestWorkerMonitorUnit(TrialTestCase):
    """Unit tests for most of the `CodeImportWorkerMonitor` class.

    We have to pay attention to the fact that several of the methods of the
    `CodeImportWorkerMonitor` class are wrapped in decorators that create and
    commit a transaction, and have to start our own transactions to check what
    they did.
    """

    layer = TwistedLaunchpadZopelessLayer

    class WorkerMonitor(CodeImportWorkerMonitor):
        """A subclass of CodeImportWorkerMonitor that stubs logging OOPSes."""

        def _logOopsFromFailure(self, failure):
            self._failures.append(failure)

    def getResultsForOurCodeImport(self):
        """Return the `CodeImportResult`s for the `CodeImport` we created.
        """
        code_import = getUtility(ICodeImportSet).get(self.code_import_id)
        return code_import.results

    def getOneResultForOurCodeImport(self):
        """Return the only `CodeImportResult` for the `CodeImport` we created.

        This method fails the test if there is more than one
        `CodeImportResult` for this `CodeImport`.
        """
        results = list(self.getResultsForOurCodeImport())
        self.failUnlessEqual(len(results), 1)
        return results[0]

    def assertOopsesLogged(self, exc_types):
        self.assertEqual(len(exc_types), len(self.worker_monitor._failures))
        for failure, exc_type in zip(self.worker_monitor._failures,
                                     exc_types):
            self.assert_(failure.check(exc_type))

    def setUp(self):
        login('no-priv@canonical.com')
        self.factory = LaunchpadObjectFactory()
        job = self.factory.makeCodeImportJob()
        self.code_import_id = job.code_import.id
        getUtility(ICodeImportJobWorkflow).startJob(
            job, self.factory.makeCodeImportMachine(set_online=True))
        self.job_id = job.id
        self.worker_monitor = self.WorkerMonitor(
            job.id, _make_silent_logger())
        self.worker_monitor._failures = []
        self.layer.txn.commit()
        self.layer.switchDbUser('codeimportworker')

    def tearDown(self):
        logout()

    def test_getJob(self):
        # getJob() returns the job whose id we passed to the constructor.
        return self.assertEqual(
            self.worker_monitor.getJob().id, self.job_id)

    def test_getJobWhenJobDeleted(self):
        # If the job has been deleted, getJob sets _call_finish_job to False
        # and raises ExitQuietly.
        job = self.worker_monitor.getJob()
        removeSecurityProxy(job).destroySelf()
        self.assertRaises(ExitQuietly, self.worker_monitor.getJob)
        self.assertNot(self.worker_monitor._call_finish_job)

    def test_getSourceDetails(self):
        # getSourceDetails extracts the details from the CodeImport database
        # object.
        @read_only_transaction
        def check_source_details(details):
            job = self.worker_monitor.getJob()
            self.assertEqual(
                details.svn_branch_url, job.code_import.svn_branch_url)
            self.assertEqual(
                details.cvs_root, job.code_import.cvs_root)
            self.assertEqual(
                details.cvs_module, job.code_import.cvs_module)
        return self.worker_monitor.getSourceDetails().addCallback(
            check_source_details)

    def test_updateHeartbeat(self):
        # The worker monitor's updateHeartbeat method calls the
        # updateHeartbeat job workflow method.
        @read_only_transaction
        def check_updated_details(result):
            job = self.worker_monitor.getJob()
            self.assertEqual(job.logtail, 'log tail')
        return self.worker_monitor.updateHeartbeat('log tail').addCallback(
            check_updated_details)

    def test_finishJobCallsFinishJob(self):
        # The worker monitor's finishJob method calls the
        # finishJob job workflow method.
        @read_only_transaction
        def check_finishJob_called(result):
            # We take as indication that finishJob was called that a
            # CodeImportResult was created.
            self.assertEqual(
                len(list(self.getResultsForOurCodeImport())), 1)
        return self.worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_finishJob_called)

    def test_finishJobDoesntUploadEmptyFileToLibrarian(self):
        # The worker monitor's finishJob method does not try to upload an
        # empty log file to the librarian.
        self.assertEqual(self.worker_monitor._log_file.tell(), 0)
        @read_only_transaction
        def check_no_file_uploaded(result):
            result = self.getOneResultForOurCodeImport()
            self.assertIdentical(result.log_file, None)
        return self.worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_no_file_uploaded)

    def test_finishJobUploadsNonEmptyFileToLibrarian(self):
        # The worker monitor's finishJob method uploads the log file to the
        # librarian.
        self.worker_monitor._log_file.write('some text')
        @read_only_transaction
        def check_file_uploaded(result):
            result = self.getOneResultForOurCodeImport()
            self.assertNotIdentical(result.log_file, None)
            self.assertEqual(result.log_file.read(), 'some text')
        return self.worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_file_uploaded)

    def test_finishJobStillCreatesResultWhenLibrarianUploadFails(self):
        # If the upload to the librarian fails for any reason, the
        # worker monitor still calls the finishJob workflow method,
        # but an OOPS is logged to indicate there was a problem.
        # Write some text so that we try to upload the log.
        self.worker_monitor._log_file.write('some text')
        # Make _createLibrarianFileAlias fail in a distinctive way.
        self.worker_monitor._createLibrarianFileAlias = lambda *args: 1/0
        def check_oops_logged_and_result_created(ignored):
            self.assertOopsesLogged([ZeroDivisionError])
            self.assertEqual(
                len(list(self.getResultsForOurCodeImport())), 1)
        return self.worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_oops_logged_and_result_created)

    def patchOutFinishJob(self):
        calls = []
        def finishJob(status):
            calls.append(status)
            return defer.succeed(None)
        self.worker_monitor.finishJob = finishJob
        return calls

    def test_callFinishJobCallsFinishJobSuccess(self):
        # callFinishJob calls finishJob with CodeImportResultStatus.SUCCESS if
        # its argument is not a Failure.
        calls = self.patchOutFinishJob()
        self.worker_monitor.callFinishJob(None)
        self.assertEqual(calls, [CodeImportResultStatus.SUCCESS])

    def test_callFinishJobCallsFinishJobFailure(self):
        # callFinishJob calls finishJob with CodeImportResultStatus.FAILURE
        # and swallows the failure if its argument is a Failure.
        calls = self.patchOutFinishJob()
        ret = self.worker_monitor.callFinishJob(makeFailure(RuntimeError))
        self.assertEqual(calls, [CodeImportResultStatus.FAILURE])
        self.assertOopsesLogged([RuntimeError])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobLogsTracebackOnFailure(self):
        # When callFinishJob is called with a failure, it dumps the traceback
        # of the failure into the log file.
        ret = self.worker_monitor.callFinishJob(makeFailure(RuntimeError))
        def check_log_file(ignored):
            self.worker_monitor._log_file.seek(0)
            log_text = self.worker_monitor._log_file.read()
            self.assertIn('RuntimeError', log_text)
        return ret.addCallback(check_log_file)

    def test_callFinishJobRespects_call_finish_job(self):
        # callFinishJob does not call finishJob if _call_finish_job is False.
        # This is to support exiting without fuss when the job we are working
        # on is deleted in the web UI.
        calls = self.patchOutFinishJob()
        self.worker_monitor._call_finish_job = False
        self.worker_monitor.callFinishJob(None)
        self.assertEqual(calls, [])


class TestWorkerMonitorRunNoProcess(TrialTestCase, BzrTestCase):
    """Tests for `CodeImportWorkerMonitor.run` that don't launch a subprocess.
    """

    class WorkerMonitor(CodeImportWorkerMonitor):
        """See `CodeImportWorkerMonitor`.

        Override _launchProcess to return a deferred that we can
        callback/errback as we choose.
        """

        def _launchProcess(self, source_details):
            return self.process_deferred

        def finishJob(self, status):
            assert self.result_status is None, "finishJob called twice!"
            self.result_status = status
            return defer.succeed(None)

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        self.factory = LaunchpadObjectFactory()
        login('no-priv@canonical.com')
        job = self.factory.makeCodeImportJob()
        self.code_import_id = job.code_import.id
        getUtility(ICodeImportJobWorkflow).startJob(
            job, self.factory.makeCodeImportMachine(set_online=True))
        self.job_id = job.id
        self.worker_monitor = self.WorkerMonitor(
            job.id, _make_silent_logger())
        self.worker_monitor.result_status = None
        self.layer.txn.commit()
        self.layer.switchDbUser('codeimportworker')

    def tearDown(self):
        logout()

    @read_only_transaction
    def assertFinishJobCalledWithStatus(self, ignored, status):
        """Assert that finishJob was called with the given status."""
        self.assertEqual(self.worker_monitor.result_status, status)

    def test_success(self):
        # In the successful case, finishJob is called with
        # CodeImportResultStatus.SUCCESS.
        self.worker_monitor.process_deferred = defer.succeed(None)
        return self.worker_monitor.run().addCallback(
            self.assertFinishJobCalledWithStatus,
            CodeImportResultStatus.SUCCESS)

    def test_failure(self):
        # If the process deferred is fired with a failure, finishJob is called
        # with CodeImportResultStatus.FAILURE, but the call to run() still
        # succeeds.
        self.worker_monitor.process_deferred = defer.fail(RuntimeError())
        return self.worker_monitor.run().addCallback(
            self.assertFinishJobCalledWithStatus,
            CodeImportResultStatus.FAILURE)

    def test_quiet_exit(self):
        # If the process deferred fails with ExitQuietly, the call to run()
        # succeeds.
        self.worker_monitor.process_deferred = defer.fail(ExitQuietly())
        return self.worker_monitor.run()

    def test_quiet_exit_from_finishJob(self):
        # If finishJob fails with ExitQuietly, the call to run() still
        # succeeds.
        self.worker_monitor.process_deferred = defer.succeed(None)
        def finishJob(reason):
            raise ExitQuietly
        self.worker_monitor.finishJob = finishJob
        return self.worker_monitor.run()


def nuke_codeimport_sample_data():
    """Delete all the sample data that might interfere with tests."""
    for job in CodeImportJob.select():
        job.destroySelf()
    for code_import in CodeImport.select():
        code_import.destroySelf()


class CIWorkerMonitorProtocolForTesting(CodeImportWorkerMonitorProtocol):
    """A `CodeImportWorkerMonitorProtocol` that counts `resetTimeout` calls.
    """

    def __init__(self, deferred, worker_monitor, log_file, clock=None):
        """See `CodeImportWorkerMonitorProtocol.__init__`."""
        CodeImportWorkerMonitorProtocol.__init__(
            self, deferred, worker_monitor, log_file, clock)
        self.reset_calls = 0

    def resetTimeout(self):
        """See `ProcessMonitorProtocolWithTimeout.resetTimeout`."""
        CodeImportWorkerMonitorProtocol.resetTimeout(self)
        self.reset_calls += 1


class CIWorkerMonitorForTesting(CodeImportWorkerMonitor):
    """A `CodeImportWorkerMonitor` that hangs on to the process protocol."""

    def _makeProcessProtocol(self, deferred):
        """See `CodeImportWorkerMonitor._makeProcessProtocol`.

        We hang on to the constructed object for later inspection -- see
        `TestWorkerMonitorIntegration.assertImported`.
        """
        protocol = CIWorkerMonitorProtocolForTesting(
            deferred, self, self._log_file)
        self._protocol = protocol
        return protocol


class TestWorkerMonitorIntegration(TrialTestCase, BzrTestCase):

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        BzrTestCase.setUp(self)
        login('no-priv@canonical.com')
        self.factory = LaunchpadObjectFactory()
        nuke_codeimport_sample_data()
        self.repo_path = tempfile.mkdtemp()
        self.disable_directory_isolation()
        self.addCleanup(shutil.rmtree, self.repo_path)
        self.foreign_commit_count = 0

    def tearDown(self):
        BzrTestCase.tearDown(self)
        logout()

    def makeCVSCodeImport(self):
        """Make a `CodeImport` that points to a real CVS repository."""
        cvs_server = CVSServer(self.repo_path)
        cvs_server.setUp()
        self.addCleanup(cvs_server.tearDown)

        cvs_server.makeModule('trunk', [('README', 'original\n')])
        self.foreign_commit_count = 2

        return self.factory.makeCodeImport(
            cvs_root=cvs_server.getRoot(), cvs_module='trunk')

    def makeSVNCodeImport(self):
        """Make a `CodeImport` that points to a real Subversion repository."""
        self.subversion_server = SubversionServer(self.repo_path)
        self.subversion_server.setUp()
        self.addCleanup(self.subversion_server.tearDown)
        svn_branch_url = self.subversion_server.makeBranch(
            'trunk', [('README', 'contents')])
        self.foreign_commit_count = 2

        return self.factory.makeCodeImport(
            svn_branch_url=svn_branch_url)

    def makeGitCodeImport(self):
        """Make a `CodeImport` that points to a real Git repository."""
        load_optional_plugin('git')
        self.git_server = GitServer(self.repo_path)
        self.git_server.setUp()
        self.addCleanup(self.git_server.tearDown)

        self.git_server.makeRepo([('README', 'contents')])
        self.foreign_commit_count = 1

        return self.factory.makeCodeImport(git_repo_url=self.repo_path)

    def getStartedJobForImport(self, code_import):
        """Get a started `CodeImportJob` for `code_import`.

        This method approves the import, creates a job, marks it started and
        returns the job.  It also makes sure there are no branches or foreign
        trees in the default stores to interfere with processing this job.
        """
        source_details = CodeImportSourceDetails.fromCodeImport(code_import)
        clean_up_default_stores_for_import(source_details)
        self.addCleanup(clean_up_default_stores_for_import, source_details)
        if code_import.review_status != CodeImportReviewStatus.REVIEWED:
            code_import.updateFromData(
                {'review_status': CodeImportReviewStatus.REVIEWED},
                self.factory.makePerson())
        job = getUtility(ICodeImportJobSet).getJobForMachine('machine')
        self.assertEqual(code_import, job.code_import)
        return job

    def assertCodeImportResultCreated(self, code_import):
        """Assert that a `CodeImportResult` was created for `code_import`."""
        self.assertEqual(len(list(code_import.results)), 1)
        result = list(code_import.results)[0]
        self.assertEqual(result.status, CodeImportResultStatus.SUCCESS)

    def assertBranchImportedOKForCodeImport(self, code_import):
        """Assert that a branch was pushed into the default branch store."""
        url = get_default_bazaar_branch_store()._getMirrorURL(
            code_import.branch.id)
        branch = Branch.open(url)
        self.assertEqual(
            self.foreign_commit_count, len(branch.revision_history()))

    @read_only_transaction
    def assertImported(self, ignored, code_import_id):
        """Assert that the `CodeImport` of the given id was imported."""
        # In the in-memory tests, check that resetTimeout on the
        # CodeImportWorkerMonitorProtocol was called at least once.
        if self._protocol is not None:
            self.assertPositive(self._protocol.reset_calls)
        code_import = getUtility(ICodeImportSet).get(code_import_id)
        self.assertCodeImportResultCreated(code_import)
        self.assertBranchImportedOKForCodeImport(code_import)

    def performImport(self, job_id):
        """Perform the import job with ID job_id.

        Return a Deferred that fires when it the job is done.

        This implementation does it in-process.
        """
        self.layer.switchDbUser('codeimportworker')
        monitor = CIWorkerMonitorForTesting(job_id, _make_silent_logger())
        deferred = monitor.run()
        def save_protocol_object(result):
            """Save the process protocol object.

            We do this in an addBoth so that it's called after the process
            protocol is actually constructed but before we drop the last
            reference to the monitor object.
            """
            self._protocol = monitor._protocol
            return result
        return deferred.addBoth(save_protocol_object)

    def DISABLEDtest_import_cvs(self):
        # Create a CVS CodeImport and import it.
        job = self.getStartedJobForImport(self.makeCVSCodeImport())
        code_import_id = job.code_import.id
        job_id = job.id
        self.layer.txn.commit()
        result = self.performImport(job_id)
        return result.addCallback(self.assertImported, code_import_id)

    def DISABLEDtest_import_subversion(self):
        # Create a Subversion CodeImport and import it.
        job = self.getStartedJobForImport(self.makeSVNCodeImport())
        code_import_id = job.code_import.id
        job_id = job.id
        self.layer.txn.commit()
        result = self.performImport(job_id)
        return result.addCallback(self.assertImported, code_import_id)

    def test_import_git(self):
        # Create a Git CodeImport and import it.
        job = self.getStartedJobForImport(self.makeGitCodeImport())
        code_import_id = job.code_import.id
        job_id = job.id
        self.layer.txn.commit()
        result = self.performImport(job_id)
        return result.addCallback(self.assertImported, code_import_id)


class DeferredOnExit(protocol.ProcessProtocol):

    def __init__(self, deferred):
        self._deferred = deferred

    def processEnded(self, reason):
        if reason.check(error.ProcessDone):
            self._deferred.callback(None)
        else:
            self._deferred.errback(reason)

class TestWorkerMonitorIntegrationScript(TestWorkerMonitorIntegration):
    """Tests for CodeImportWorkerMonitor that execute a child process."""

    def setUp(self):
        TestWorkerMonitorIntegration.setUp(self)
        self._protocol = None

    def performImport(self, job_id):
        """Perform the import job with ID job_id.

        Return a Deferred that fires when it the job is done.

        This implementation does it in a child process.
        """
        script_path = os.path.join(
            config.root, 'scripts', 'code-import-worker-db.py')
        process_end_deferred = defer.Deferred()
        # The "childFDs={0:0, 1:1, 2:2}" means that any output from the script
        # goes to the test runner's console rather than to pipes that noone is
        # listening too.
        interpreter = '%s/bin/py' % config.root
        reactor.spawnProcess(
            DeferredOnExit(process_end_deferred), interpreter,
            [interpreter, script_path, str(job_id), '-q'],
            childFDs={0:0, 1:1, 2:2}, env=os.environ)
        return process_end_deferred


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
