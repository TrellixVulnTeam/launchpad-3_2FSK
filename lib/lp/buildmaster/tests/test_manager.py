# Copyright 2009-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the renovated slave scanner aka BuilddManager."""

import os
import signal
import time
import xmlrpclib

from testtools.deferredruntest import (
    assert_fails_with,
    AsynchronousDeferredRunTest,
    )
from testtools.matchers import Equals
from testtools.testcase import ExpectedException
import transaction
from twisted.internet import (
    defer,
    reactor,
    task,
    )
from twisted.internet.task import deferLater
from twisted.python.failure import Failure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuildQueueStatus,
    BuildStatus,
    )
from lp.buildmaster.interactor import (
    BuilderInteractor,
    BuilderSlave,
    extract_vitals_from_db,
    )
from lp.buildmaster.interfaces.builder import (
    BuildDaemonError,
    IBuilderSet,
    )
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.manager import (
    assessFailureCounts,
    BuilddManager,
    BuilderFactory,
    NewBuildersScanner,
    PrefetchedBuilderFactory,
    SlaveScanner,
    )
from lp.buildmaster.model.builder import Builder
from lp.buildmaster.tests.harness import BuilddManagerTestSetup
from lp.buildmaster.tests.mock_slaves import (
    BrokenSlave,
    BuildingSlave,
    LostBuildingBrokenSlave,
    make_publisher,
    MockBuilder,
    OkSlave,
    TrivialBehaviour,
    WaitingSlave,
    )
from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.config import config
from lp.services.log.logger import BufferLogger
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.model.binarypackagebuildbehaviour import (
    BinaryPackageBuildBehaviour,
    )
from lp.testing import (
    ANONYMOUS,
    login,
    StormStatementRecorder,
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.dbuser import switch_dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import (
    LaunchpadScriptLayer,
    LaunchpadZopelessLayer,
    ZopelessDatabaseLayer,
    )
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import BOB_THE_BUILDER_NAME


class TestSlaveScannerScan(TestCaseWithFactory):
    """Tests `SlaveScanner.scan` method.

    This method uses the old framework for scanning and dispatching builds.
    """
    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        """Set up BuilddSlaveTest.

        Also adjust the sampledata in a way a build can be dispatched to
        'bob' builder.
        """
        super(TestSlaveScannerScan, self).setUp()
        # Creating the required chroots needed for dispatching.
        test_publisher = make_publisher()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        test_publisher.setUpDefaultDistroSeries(hoary)
        test_publisher.addFakeChroots(db_only=True)

    def _resetBuilder(self, builder):
        """Reset the given builder and its job."""

        builder.builderok = True
        job = builder.currentjob
        if job is not None:
            job.reset()
        builder.clean_status = BuilderCleanStatus.CLEAN

        transaction.commit()

    def assertBuildingJob(self, job, builder, logtail=None):
        """Assert the given job is building on the given builder."""
        if logtail is None:
            logtail = 'Dummy sampledata entry, not processing'

        self.assertTrue(job is not None)
        self.assertEqual(job.builder, builder)
        self.assertTrue(job.date_started is not None)
        self.assertEqual(job.status, BuildQueueStatus.RUNNING)
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
        self.assertEqual(build.status, BuildStatus.BUILDING)
        self.assertEqual(job.logtail, logtail)

    def _getScanner(self, builder_name=None, clock=None, builder_factory=None):
        """Instantiate a SlaveScanner object.

        Replace its default logging handler by a testing version.
        """
        if builder_name is None:
            builder_name = BOB_THE_BUILDER_NAME
        if builder_factory is None:
            builder_factory = BuilderFactory()
        scanner = SlaveScanner(
            builder_name, builder_factory, BufferLogger(), clock=clock)
        scanner.logger.name = 'slave-scanner'

        return scanner

    @defer.inlineCallbacks
    def testScanDispatchForResetBuilder(self):
        # A job gets dispatched to the sampledata builder after it's reset.

        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        # Set this to 1 here so that _checkDispatch can make sure it's
        # reset to 0 after a successful dispatch.
        builder.failure_count = 1
        builder.clean_status = BuilderCleanStatus.CLEAN

        # Run 'scan' and check its result.
        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        yield scanner.scan()
        self.assertEqual(0, builder.failure_count)
        self.assertTrue(builder.currentjob is not None)

    def _checkNoDispatch(self, slave, builder):
        """Assert that no dispatch has occurred.

        'slave' is None, so no interations would be passed
        to the asynchonous dispatcher and the builder remained active
        and IDLE.
        """
        self.assertTrue(slave is None, "Unexpected slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)
        self.assertTrue(builder.currentjob is None)

    def _checkJobRescued(self, slave, builder, job):
        """`SlaveScanner.scan` rescued the job.

        Nothing gets dispatched,  the 'broken' builder remained disabled
        and the 'rescued' job is ready to be dispatched.
        """
        self.assertTrue(
            slave is None, "Unexpected slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertFalse(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertTrue(job.builder is None)
        self.assertTrue(job.date_started is None)
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    @defer.inlineCallbacks
    def testScanRescuesJobFromBrokenBuilder(self):
        # The job assigned to a broken builder is rescued.
        # Sampledata builder is enabled and is assigned to an active job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self.patch(
            BuilderSlave, 'makeBuilderSlave',
            FakeMethod(BuildingSlave(build_id='PACKAGEBUILD-8')))
        self.assertTrue(builder.builderok)
        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        scanner = self._getScanner()
        yield scanner.scan()
        self.assertIsNot(None, builder.currentjob)

        # Disable the sampledata builder
        builder.builderok = False
        transaction.commit()

        # Run 'scan' and check its result.
        slave = yield scanner.scan()
        self.assertIs(None, builder.currentjob)
        self._checkJobRescued(slave, builder, job)

    def _checkJobUpdated(self, slave, builder, job):
        """`SlaveScanner.scan` updates legitimate jobs.

        Job is kept assigned to the active builder and its 'logtail' is
        updated.
        """
        self.assertTrue(slave is None, "Unexpected slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertBuildingJob(job, builder, logtail='This is a build log: 0')

    def testScanUpdatesBuildingJobs(self):
        # Enable sampledata builder attached to an appropriate testing
        # slave. It will respond as if it was building the sampledata job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]

        login('foo.bar@canonical.com')
        builder.builderok = True
        self.patch(BuilderSlave, 'makeBuilderSlave',
                   FakeMethod(BuildingSlave(build_id='PACKAGEBUILD-8')))
        transaction.commit()
        login(ANONYMOUS)

        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        # Run 'scan' and check its result.
        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        d = defer.maybeDeferred(scanner.scan)
        d.addCallback(self._checkJobUpdated, builder, job)
        return d

    def test_scan_with_nothing_to_dispatch(self):
        factory = LaunchpadObjectFactory()
        builder = factory.makeBuilder()
        builder.clean_status = BuilderCleanStatus.CLEAN
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        scanner = self._getScanner(builder_name=builder.name)
        d = scanner.scan()
        return d.addCallback(self._checkNoDispatch, builder)

    def test_scan_with_manual_builder(self):
        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        builder.manual = True
        transaction.commit()
        scanner = self._getScanner()
        d = scanner.scan()
        d.addCallback(self._checkNoDispatch, builder)
        return d

    @defer.inlineCallbacks
    def test_scan_with_not_ok_builder(self):
        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        builder.builderok = False
        transaction.commit()
        scanner = self._getScanner()
        yield scanner.scan()
        # Because the builder is not ok, we can't use _checkNoDispatch.
        self.assertIsNone(builder.currentjob)

    def test_scan_of_broken_slave(self):
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(
            BuilderSlave, 'makeBuilderSlave', FakeMethod(BrokenSlave()))
        builder.failure_count = 0
        transaction.commit()
        scanner = self._getScanner(builder_name=builder.name)
        d = scanner.scan()
        return assert_fails_with(d, xmlrpclib.Fault)

    @defer.inlineCallbacks
    def test_scan_calls_builder_factory_prescanUpdate(self):
        # SlaveScanner.scan() starts by calling
        # BuilderFactory.prescanUpdate() to eg. perform necessary
        # transaction management.
        bf = BuilderFactory()
        bf.prescanUpdate = FakeMethod()
        scanner = self._getScanner(builder_factory=bf)

        # Disable the builder so we don't try to use the slave. It's not
        # relevant for this test.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.builderok = False
        transaction.commit()

        yield scanner.scan()

        self.assertEqual(1, bf.prescanUpdate.call_count)

    @defer.inlineCallbacks
    def test_scan_skipped_if_builderfactory_stale(self):
        # singleCycle does nothing if the BuilderFactory's update
        # timestamp is older than the end of the previous scan. This
        # prevents eg. a scan after a dispatch from failing to notice
        # that a build has been dispatched.
        pbf = PrefetchedBuilderFactory()
        pbf.update()
        scanner = self._getScanner(builder_factory=pbf)
        fake_scan = FakeMethod()

        def _fake_scan():
            fake_scan()
            return defer.succeed(None)
        scanner.scan = _fake_scan
        self.assertEqual(0, fake_scan.call_count)

        # An initial cycle triggers a scan.
        yield scanner.singleCycle()
        self.assertEqual(1, fake_scan.call_count)

        # But a subsequent cycle without updating BuilderFactory's data
        # is a no-op.
        yield scanner.singleCycle()
        self.assertEqual(1, fake_scan.call_count)

        # Updating the BuilderFactory causes scans to resume.
        pbf.update()
        yield scanner.singleCycle()
        self.assertEqual(2, fake_scan.call_count)

    @defer.inlineCallbacks
    def _assertFailureCounting(self, builder_count, job_count,
                               expected_builder_count, expected_job_count):
        # If scan() fails with an exception, failure_counts should be
        # incremented.  What we do with the results of the failure
        # counts is tested below separately, this test just makes sure that
        # scan() is setting the counts.
        def failing_scan():
            return defer.fail(Exception("fake exception"))
        scanner = self._getScanner()
        scanner.scan = failing_scan
        from lp.buildmaster import manager as manager_module
        self.patch(manager_module, 'assessFailureCounts', FakeMethod())
        builder = getUtility(IBuilderSet)[scanner.builder_name]

        builder.failure_count = builder_count
        naked_build = removeSecurityProxy(builder.currentjob.specific_build)
        naked_build.failure_count = job_count
        # The _scanFailed() calls abort, so make sure our existing
        # failure counts are persisted.
        transaction.commit()

        # singleCycle() calls scan() which is our fake one that throws an
        # exception.
        yield scanner.singleCycle()

        # Failure counts should be updated, and the assessment method
        # should have been called.  The actual behaviour is tested below
        # in TestFailureAssessments.
        self.assertEqual(expected_builder_count, builder.failure_count)
        self.assertEqual(
            expected_job_count,
            builder.currentjob.specific_build.failure_count)
        self.assertEqual(1, manager_module.assessFailureCounts.call_count)

    def test_scan_first_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=0, job_count=0, expected_builder_count=1,
            expected_job_count=1)

    def test_scan_second_builder_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=1, job_count=0, expected_builder_count=2,
            expected_job_count=1)

    def test_scan_second_job_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=0, job_count=1, expected_builder_count=1,
            expected_job_count=2)

    @defer.inlineCallbacks
    def test_scanFailed_handles_lack_of_a_job_on_the_builder(self):
        def failing_scan():
            return defer.fail(Exception("fake exception"))
        scanner = self._getScanner()
        scanner.scan = failing_scan
        builder = getUtility(IBuilderSet)[scanner.builder_name]
        builder.failure_count = (
            Builder.RESET_THRESHOLD * Builder.RESET_FAILURE_THRESHOLD)
        builder.currentjob.reset()
        transaction.commit()

        yield scanner.singleCycle()
        self.assertFalse(builder.builderok)

    @defer.inlineCallbacks
    def test_fail_to_resume_leaves_it_dirty(self):
        # If an attempt to resume a slave fails, its failure count is
        # incremented and it is left DIRTY.

        # Make a slave with a failing resume() method.
        slave = OkSlave()
        slave.resume = lambda: deferLater(
            reactor, 0, defer.fail, Failure(('out', 'err', 1)))

        # Reset sampledata builder.
        builder = removeSecurityProxy(
            getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME])
        self._resetBuilder(builder)
        builder.clean_status = BuilderCleanStatus.DIRTY
        builder.virtualized = True
        self.assertEqual(0, builder.failure_count)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(slave))
        builder.vm_host = "fake_vm_host"
        transaction.commit()

        # A spin of the scanner will see the DIRTY builder and reset it.
        # Our patched reset will fail.
        yield self._getScanner().singleCycle()

        # The failure_count will have been incremented on the builder,
        # and it will be left DIRTY.
        self.assertEqual(1, builder.failure_count)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

    @defer.inlineCallbacks
    def test_update_slave_version(self):
        # If the reported slave version differs from the DB's record of it,
        # then scanning the builder updates the DB.
        slave = OkSlave(version="100")
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.version = "99"
        self._resetBuilder(builder)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(slave))
        scanner = self._getScanner()
        yield scanner.scan()
        self.assertEqual("100", builder.version)

    def test_updateVersion_no_op(self):
        # If the slave version matches the DB, then updateVersion does not
        # touch the DB.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.version = "100"
        transaction.commit()
        vitals = extract_vitals_from_db(builder)
        scanner = self._getScanner()
        with StormStatementRecorder() as recorder:
            scanner.updateVersion(vitals, {"builder_version": "100"})
        self.assertThat(recorder, HasQueryCount(Equals(0)))

    @defer.inlineCallbacks
    def test_cancelling_a_build(self):
        # When scanning an in-progress build, if its state is CANCELLING
        # then the build should be aborted, and eventually stopped and moved
        # to the CANCELLED state if it does not abort by itself.

        # Set up a mock building slave.
        slave = BuildingSlave()

        # Set the sample data builder building with the slave from above.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        login('foo.bar@canonical.com')
        builder.builderok = True
        # For now, we can only cancel virtual builds.
        builder.virtualized = True
        builder.vm_host = "fake_vm_host"
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(slave))
        transaction.commit()
        login(ANONYMOUS)
        buildqueue = builder.currentjob
        behaviour = IBuildFarmJobBehaviour(buildqueue.specific_build)
        slave.build_id = behaviour.getBuildCookie()
        self.assertBuildingJob(buildqueue, builder)

        # Now set the build to CANCELLING.
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(buildqueue)
        build.cancel()

        # Run 'scan' and check its results.
        switch_dbuser(config.builddmaster.dbuser)
        clock = task.Clock()
        scanner = self._getScanner(clock=clock)
        yield scanner.scan()

        # An abort request should be sent.
        self.assertEqual(1, slave.call_log.count("abort"))
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        # Advance time a little.  Nothing much should happen.
        clock.advance(1)
        yield scanner.scan()
        self.assertEqual(1, slave.call_log.count("abort"))
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        # Advance past the timeout.  The build state should be cancelled and
        # we should have also called the resume() method on the slave that
        # resets the virtual machine.
        clock.advance(SlaveScanner.CANCEL_TIMEOUT)
        yield scanner.scan()
        self.assertEqual(1, slave.call_log.count("abort"))
        self.assertEqual(1, slave.call_log.count("resume"))
        self.assertEqual(BuildStatus.CANCELLED, build.status)

    @defer.inlineCallbacks
    def test_end_to_end(self):
        # Test that SlaveScanner.scan() successfully finds, dispatches,
        # collects and cleans a build.
        build = self.factory.makeBinaryPackageBuild()
        build.distro_arch_series.addOrUpdateChroot(
            self.factory.makeLibraryFileAlias(db_only=True))
        bq = build.queueBuild()
        bq.manualScore(9000)

        builder = self.factory.makeBuilder(
            processors=[bq.processor], manual=False, vm_host='VMHOST')
        transaction.commit()

        # Mock out the build behaviour's _handleStatus_OK so it doesn't
        # try to upload things to the librarian or queue.
        @defer.inlineCallbacks
        def handleStatus_OK(self, slave_status, logger, notify):
            build.updateStatus(
                BuildStatus.UPLOADING, builder, slave_status=slave_status)
            transaction.commit()
            yield self._slave.clean()
            bq.destroySelf()
            transaction.commit()
        self.patch(
            BinaryPackageBuildBehaviour, '_handleStatus_OK', handleStatus_OK)

        # And create a SlaveScanner with a slave and a clock that we
        # control.
        get_slave = FakeMethod(OkSlave())
        clock = task.Clock()
        scanner = SlaveScanner(
            builder.name, BuilderFactory(), BufferLogger(),
            slave_factory=get_slave, clock=clock)

        # The slave is idle and dirty, so the first scan will clean it
        # with a reset.
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)
        yield scanner.scan()
        self.assertEqual(['resume', 'echo'], get_slave.result.method_log)
        self.assertEqual(BuilderCleanStatus.CLEAN, builder.clean_status)
        self.assertIs(None, builder.currentjob)

        # The slave is idle and clean, and there's a build candidate, so
        # the next scan will dispatch the build.
        get_slave.result = OkSlave()
        yield scanner.scan()
        self.assertEqual(
            ['status', 'ensurepresent', 'build'],
            get_slave.result.method_log)
        self.assertEqual(bq, builder.currentjob)
        self.assertEqual(BuildQueueStatus.RUNNING, bq.status)
        self.assertEqual(BuildStatus.BUILDING, build.status)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

        # build() has been called, so switch in a BUILDING slave.
        # Scans will now just do a status() each, as the logtail is
        # updated.
        get_slave.result = BuildingSlave(
            IBuildFarmJobBehaviour(build).getBuildCookie())
        yield scanner.scan()
        self.assertEqual("This is a build log: 0", bq.logtail)
        yield scanner.scan()
        self.assertEqual("This is a build log: 1", bq.logtail)
        yield scanner.scan()
        self.assertEqual("This is a build log: 2", bq.logtail)
        self.assertEqual(
            ['status', 'status', 'status'], get_slave.result.method_log)

        # When the build finishes, the scanner will notice, call
        # handleStatus(), and then clean the builder.  Our fake
        # _handleStatus_OK doesn't do anything special, but there'd
        # usually be file retrievals in the middle. The builder remains
        # dirty afterward.
        get_slave.result = WaitingSlave(
            build_id=IBuildFarmJobBehaviour(build).getBuildCookie())
        yield scanner.scan()
        self.assertEqual(['status', 'clean'], get_slave.result.method_log)
        self.assertIs(None, builder.currentjob)
        self.assertEqual(BuildStatus.UPLOADING, build.status)
        self.assertEqual(builder, build.builder)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

        # We're idle and dirty, so let's flip back to an idle slave and
        # confirm that the slave gets cleaned.
        get_slave.result = OkSlave()
        yield scanner.scan()
        self.assertEqual(['resume', 'echo'], get_slave.result.method_log)
        self.assertIs(None, builder.currentjob)
        self.assertEqual(BuilderCleanStatus.CLEAN, builder.clean_status)


class TestPrefetchedBuilderFactory(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_get(self):
        # PrefetchedBuilderFactory.__getitem__ is unoptimised, just
        # querying and returning the named builder.
        builder = self.factory.makeBuilder()
        pbf = PrefetchedBuilderFactory()
        self.assertEqual(builder, pbf[builder.name])

    def test_update(self):
        # update grabs all of the Builders and their BuildQueues in a
        # single query.
        builders = [self.factory.makeBuilder() for i in range(5)]
        for i in range(3):
            bq = self.factory.makeBinaryPackageBuild().queueBuild()
            bq.markAsBuilding(builders[i])
        pbf = PrefetchedBuilderFactory()
        transaction.commit()
        pbf.update()
        with StormStatementRecorder() as recorder:
            pbf.update()
        self.assertThat(recorder, HasQueryCount(Equals(1)))

    def test_getVitals(self):
        # PrefetchedBuilderFactory.getVitals looks up the BuilderVitals
        # in a local cached map, without hitting the DB.
        builder = self.factory.makeBuilder()
        bq = self.factory.makeBinaryPackageBuild().queueBuild()
        bq.markAsBuilding(builder)
        transaction.commit()
        name = builder.name
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        def assertQuerylessVitals(comparator):
            expected_vitals = extract_vitals_from_db(builder)
            transaction.commit()
            with StormStatementRecorder() as recorder:
                got_vitals = pbf.getVitals(name)
                comparator(expected_vitals, got_vitals)
                comparator(expected_vitals.build_queue, got_vitals.build_queue)
            self.assertThat(recorder, HasQueryCount(Equals(0)))
            return got_vitals

        # We can get the vitals of a builder from the factory without
        # any DB queries.
        vitals = assertQuerylessVitals(self.assertEqual)
        self.assertIsNot(None, vitals.build_queue)

        # If we cancel the BuildQueue to unassign it, the factory
        # doesn't notice immediately.
        bq.markAsCancelled()
        vitals = assertQuerylessVitals(self.assertNotEqual)
        self.assertIsNot(None, vitals.build_queue)

        # But the vitals will show the builder as idle if we ask the
        # factory to refetch.
        pbf.update()
        vitals = assertQuerylessVitals(self.assertEqual)
        self.assertIs(None, vitals.build_queue)

    def test_iterVitals(self):
        # PrefetchedBuilderFactory.iterVitals looks up the details from
        # the local cached map, without hitting the DB.

        # Construct 5 new builders, 3 with builds. This is in addition
        # to the 2 in sampledata, 1 with a build.
        builders = [self.factory.makeBuilder() for i in range(5)]
        for i in range(3):
            bq = self.factory.makeBinaryPackageBuild().queueBuild()
            bq.markAsBuilding(builders[i])
        transaction.commit()
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        with StormStatementRecorder() as recorder:
            all_vitals = list(pbf.iterVitals())
        self.assertThat(recorder, HasQueryCount(Equals(0)))
        # Compare the counts with what we expect, and the full result
        # with the non-prefetching BuilderFactory.
        self.assertEqual(7, len(all_vitals))
        self.assertEqual(
            4, len([v for v in all_vitals if v.build_queue is not None]))
        self.assertContentEqual(BuilderFactory().iterVitals(), all_vitals)


class FakeBuildQueue:

    def __init__(self):
        self.id = 1
        self.reset = FakeMethod()
        self.status = BuildQueueStatus.RUNNING


class MockBuilderFactory:
    """A mock builder factory which uses a preset Builder and BuildQueue."""

    def __init__(self, builder, build_queue):
        self.updateTestData(builder, build_queue)
        self.get_call_count = 0
        self.getVitals_call_count = 0

    def update(self):
        return

    def prescanUpdate(self):
        return

    def updateTestData(self, builder, build_queue):
        self._builder = builder
        self._build_queue = build_queue

    def __getitem__(self, name):
        self.get_call_count += 1
        return self._builder

    def getVitals(self, name):
        self.getVitals_call_count += 1
        return extract_vitals_from_db(self._builder, self._build_queue)


class TestSlaveScannerWithoutDB(TestCase):

    run_tests_with = AsynchronousDeferredRunTest

    def getScanner(self, builder_factory=None, interactor=None, slave=None,
                   behaviour=None):
        if builder_factory is None:
            builder_factory = MockBuilderFactory(
                MockBuilder(virtualized=False), None)
        if interactor is None:
            interactor = BuilderInteractor()
            interactor.updateBuild = FakeMethod()
        if slave is None:
            slave = OkSlave()
        if behaviour is None:
            behaviour = TrivialBehaviour()
        return SlaveScanner(
            'mock', builder_factory, BufferLogger(),
            interactor_factory=FakeMethod(interactor),
            slave_factory=FakeMethod(slave),
            behaviour_factory=FakeMethod(behaviour))

    @defer.inlineCallbacks
    def test_scan_with_job(self):
        # SlaveScanner.scan calls updateBuild() when a job is building.
        slave = BuildingSlave('trivial')
        bq = FakeBuildQueue()
        scanner = self.getScanner(
            builder_factory=MockBuilderFactory(MockBuilder(), bq),
            slave=slave)

        yield scanner.scan()
        self.assertEqual(['status'], slave.call_log)
        self.assertEqual(
            1, scanner.interactor_factory.result.updateBuild.call_count)
        self.assertEqual(0, bq.reset.call_count)

    @defer.inlineCallbacks
    def test_scan_recovers_lost_slave_with_job(self):
        # SlaveScanner.scan identifies slaves that aren't building what
        # they should be, resets the jobs, and then aborts the slaves.
        slave = BuildingSlave('nontrivial')
        bq = FakeBuildQueue()
        builder = MockBuilder(virtualized=False)
        scanner = self.getScanner(
            builder_factory=MockBuilderFactory(builder, bq),
            slave=slave)

        # A single scan will call status(), notice that the slave is lost,
        # and reset() the job without calling updateBuild().
        yield scanner.scan()
        self.assertEqual(['status'], slave.call_log)
        self.assertEqual(
            0, scanner.interactor_factory.result.updateBuild.call_count)
        self.assertEqual(1, bq.reset.call_count)
        # The reset would normally have unset build_queue.
        scanner.builder_factory.updateTestData(builder, None)

        # The next scan will see a dirty idle builder with a BUILDING
        # slave, and abort() it.
        yield scanner.scan()
        self.assertEqual(['status', 'status', 'abort'], slave.call_log)

    @defer.inlineCallbacks
    def test_scan_recovers_lost_slave_when_idle(self):
        # SlaveScanner.scan identifies slaves that are building when
        # they shouldn't be and aborts them.
        slave = BuildingSlave()
        scanner = self.getScanner(slave=slave)
        yield scanner.scan()
        self.assertEqual(['status', 'abort'], slave.call_log)

    @defer.inlineCallbacks
    def test_scan_building_but_not_dirty_builder_explodes(self):
        # Builders with a build assigned must be dirty for safety
        # reasons. If we run into one that's clean, we blow up.
        slave = BuildingSlave()
        builder = MockBuilder(clean_status=BuilderCleanStatus.CLEAN)
        bq = FakeBuildQueue()
        scanner = self.getScanner(
            slave=slave, builder_factory=MockBuilderFactory(builder, bq))

        with ExpectedException(
                BuildDaemonError, "Non-dirty builder allegedly building."):
            yield scanner.scan()
        self.assertEqual([], slave.call_log)

    @defer.inlineCallbacks
    def test_scan_clean_but_not_idle_slave_explodes(self):
        # Clean builders by definition have slaves that are idle. If
        # an ostensibly clean slave isn't idle, blow up.
        slave = BuildingSlave()
        builder = MockBuilder(clean_status=BuilderCleanStatus.CLEAN)
        scanner = self.getScanner(
            slave=slave, builder_factory=MockBuilderFactory(builder, None))

        with ExpectedException(
                BuildDaemonError,
                "Allegedly clean slave not idle "
                "\('BuilderStatus.BUILDING' instead\)"):
            yield scanner.scan()
        self.assertEqual(['status'], slave.call_log)

    def test_getExpectedCookie_caches(self):
        bf = MockBuilderFactory(MockBuilder(), FakeBuildQueue())
        scanner = SlaveScanner(
            'mock', bf, BufferLogger(), interactor_factory=FakeMethod(None),
            slave_factory=FakeMethod(None),
            behaviour_factory=FakeMethod(TrivialBehaviour()))

        def assertCounts(expected):
            self.assertEqual(
                expected,
                (scanner.interactor_factory.call_count,
                 scanner.behaviour_factory.call_count,
                 scanner.builder_factory.get_call_count))

        # The first call will get a Builder and a BuildFarmJobBehaviour.
        assertCounts((0, 0, 0))
        cookie1 = scanner.getExpectedCookie(bf.getVitals('foo'))
        self.assertEqual('trivial', cookie1)
        assertCounts((0, 1, 1))

        # A second call with the same BuildQueue will not reretrieve them.
        cookie2 = scanner.getExpectedCookie(bf.getVitals('foo'))
        self.assertEqual(cookie1, cookie2)
        assertCounts((0, 1, 1))

        # But a call with a new BuildQueue will regrab.
        bf.updateTestData(bf._builder, FakeBuildQueue())
        cookie3 = scanner.getExpectedCookie(bf.getVitals('foo'))
        self.assertEqual(cookie1, cookie3)
        assertCounts((0, 2, 2))

        # And unsetting the BuildQueue returns None again.
        bf.updateTestData(bf._builder, None)
        cookie4 = scanner.getExpectedCookie(bf.getVitals('foo'))
        self.assertIs(None, cookie4)
        assertCounts((0, 2, 2))


class TestCancellationChecking(TestCaseWithFactory):
    """Unit tests for the checkCancellation method."""

    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        super(TestCancellationChecking, self).setUp()
        builder_name = BOB_THE_BUILDER_NAME
        self.builder = getUtility(IBuilderSet)[builder_name]
        self.builder.virtualized = True
        self.interactor = BuilderInteractor()

    @property
    def vitals(self):
        return extract_vitals_from_db(self.builder)

    def _getScanner(self, clock=None):
        scanner = SlaveScanner(
            None, BuilderFactory(), BufferLogger(), clock=clock)
        scanner.logger.name = 'slave-scanner'
        return scanner

    def test_ignores_nonvirtual(self):
        # If the builder is nonvirtual make sure we return False.
        self.builder.virtualized = False
        d = self._getScanner().checkCancellation(
            self.vitals, None, self.interactor)
        return d.addCallback(self.assertFalse)

    def test_ignores_no_buildqueue(self):
        # If the builder has no buildqueue associated,
        # make sure we return False.
        buildqueue = self.builder.currentjob
        buildqueue.reset()
        d = self._getScanner().checkCancellation(
            self.vitals, None, self.interactor)
        return d.addCallback(self.assertFalse)

    def test_ignores_build_not_cancelling(self):
        # If the active build is not in a CANCELLING state, ignore it.
        d = self._getScanner().checkCancellation(
            self.vitals, None, self.interactor)
        return d.addCallback(self.assertFalse)

    @defer.inlineCallbacks
    def test_cancelling_build_is_cancelled(self):
        # If a BuildQueue is CANCELLING and the cancel timeout expires,
        # make sure True is returned and the slave was resumed.
        slave = OkSlave()
        self.builder.vm_host = "fake_vm_host"
        buildqueue = self.builder.currentjob
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(buildqueue)
        build.cancel()
        clock = task.Clock()
        scanner = self._getScanner(clock=clock)

        result = yield scanner.checkCancellation(
            self.vitals, slave, self.interactor)
        self.assertNotIn("resume", slave.call_log)
        self.assertFalse(result)
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        clock.advance(SlaveScanner.CANCEL_TIMEOUT)
        result = yield scanner.checkCancellation(
            self.vitals, slave, self.interactor)
        self.assertEqual(1, slave.call_log.count("resume"))
        self.assertTrue(result)
        self.assertEqual(BuildStatus.CANCELLED, build.status)

    @defer.inlineCallbacks
    def test_lost_build_is_cancelled(self):
        # If the builder reports a fault while attempting to abort it, then
        # immediately resume the slave as if the cancel timeout had expired.
        slave = LostBuildingBrokenSlave()
        self.builder.vm_host = "fake_vm_host"
        buildqueue = self.builder.currentjob
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(buildqueue)
        build.cancel()
        result = yield self._getScanner().checkCancellation(
            self.vitals, slave, self.interactor)
        self.assertEqual(1, slave.call_log.count("resume"))
        self.assertTrue(result)
        self.assertEqual(BuildStatus.CANCELLED, build.status)


class TestBuilddManager(TestCase):

    layer = LaunchpadZopelessLayer

    def _stub_out_scheduleNextScanCycle(self):
        # stub out the code that adds a callLater, so that later tests
        # don't get surprises.
        self.patch(SlaveScanner, 'startCycle', FakeMethod())

    def test_addScanForBuilders(self):
        # Test that addScanForBuilders generates NewBuildersScanner objects.
        self._stub_out_scheduleNextScanCycle()

        manager = BuilddManager()
        builder_names = set(
            builder.name for builder in getUtility(IBuilderSet))
        scanners = manager.addScanForBuilders(builder_names)
        scanner_names = set(scanner.builder_name for scanner in scanners)
        self.assertEqual(builder_names, scanner_names)

    def test_startService_adds_NewBuildersScanner(self):
        # When startService is called, the manager will start up a
        # NewBuildersScanner object.
        self._stub_out_scheduleNextScanCycle()
        clock = task.Clock()
        manager = BuilddManager(clock=clock)

        # Replace scan() with FakeMethod so we can see if it was called.
        manager.new_builders_scanner.scan = FakeMethod()

        manager.startService()
        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, manager.new_builders_scanner.scan.call_count)


class TestFailureAssessments(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.builder = self.factory.makeBuilder()
        self.build = self.factory.makeSourcePackageRecipeBuild()
        self.buildqueue = self.build.queueBuild()
        self.buildqueue.markAsBuilding(self.builder)
        self.slave = OkSlave()

    def _assessFailureCounts(self, fail_notes, retry=True):
        # Helper for assessFailureCounts boilerplate.
        return assessFailureCounts(
            BufferLogger(), extract_vitals_from_db(self.builder), self.builder,
            self.slave, BuilderInteractor(), retry, Exception(fail_notes))

    @defer.inlineCallbacks
    def test_job_reset_threshold_with_retry(self):
        naked_build = removeSecurityProxy(self.build)
        self.builder.failure_count = Builder.JOB_RESET_THRESHOLD - 1
        naked_build.failure_count = Builder.JOB_RESET_THRESHOLD - 1

        yield self._assessFailureCounts("failnotes")
        self.assertIsNot(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.BUILDING)

        self.builder.failure_count += 1
        naked_build.failure_count += 1

        yield self._assessFailureCounts("failnotes")
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)

    @defer.inlineCallbacks
    def test_job_reset_threshold_no_retry(self):
        naked_build = removeSecurityProxy(self.build)
        self.builder.failure_count = 1
        naked_build.failure_count = 1

        yield self._assessFailureCounts("failnotes", retry=False)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)

    @defer.inlineCallbacks
    def test_job_failing_more_than_builder_fails_job(self):
        self.build.gotFailure()
        self.build.gotFailure()
        self.builder.gotFailure()

        yield self._assessFailureCounts("failnotes")
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.FAILEDTOBUILD)
        self.assertEqual(0, self.builder.failure_count)

    @defer.inlineCallbacks
    def test_virtual_builder_reset_thresholds(self):
        self.builder.virtualized = True
        self.builder.vm_host = 'foo'

        for failure_count in range(
            Builder.RESET_THRESHOLD - 1,
            Builder.RESET_THRESHOLD * Builder.RESET_FAILURE_THRESHOLD):
            self.builder.failure_count = failure_count
            yield self._assessFailureCounts("failnotes")
            self.assertIs(None, self.builder.currentjob)
            self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
            self.assertEqual(
                failure_count // Builder.RESET_THRESHOLD,
                self.slave.call_log.count('resume'))
            self.assertTrue(self.builder.builderok)

        self.builder.failure_count = (
            Builder.RESET_THRESHOLD * Builder.RESET_FAILURE_THRESHOLD)
        yield self._assessFailureCounts("failnotes")
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
        self.assertEqual(
            Builder.RESET_FAILURE_THRESHOLD - 1,
            self.slave.call_log.count('resume'))
        self.assertFalse(self.builder.builderok)
        self.assertEqual("failnotes", self.builder.failnotes)

    @defer.inlineCallbacks
    def test_non_virtual_builder_reset_thresholds(self):
        self.builder.virtualized = False
        self.builder.failure_count = Builder.RESET_THRESHOLD - 1
        yield self._assessFailureCounts("failnotes")
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
        self.assertEqual(0, self.slave.call_log.count('resume'))
        self.assertTrue(self.builder.builderok)

        self.builder.failure_count = Builder.RESET_THRESHOLD
        yield self._assessFailureCounts("failnotes")
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
        self.assertEqual(0, self.slave.call_log.count('resume'))
        self.assertFalse(self.builder.builderok)
        self.assertEqual("failnotes", self.builder.failnotes)

    @defer.inlineCallbacks
    def test_builder_failing_with_no_attached_job(self):
        self.buildqueue.reset()
        self.builder.failure_count = (
            Builder.RESET_THRESHOLD * Builder.RESET_FAILURE_THRESHOLD)

        yield self._assessFailureCounts("failnotes")
        self.assertFalse(self.builder.builderok)
        self.assertEqual("failnotes", self.builder.failnotes)


class TestNewBuilders(TestCase):
    """Test detecting of new builders."""

    layer = LaunchpadZopelessLayer

    def _getScanner(self, clock=None):
        nbs = NewBuildersScanner(
            manager=BuilddManager(builder_factory=BuilderFactory()),
            clock=clock)
        nbs.checkForNewBuilders()
        return nbs

    def test_scheduleScan(self):
        # Test that scheduleScan calls the "scan" method.
        clock = task.Clock()
        builder_scanner = self._getScanner(clock=clock)
        builder_scanner.scan = FakeMethod()
        builder_scanner.scheduleScan()

        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(
            0, builder_scanner.scan.call_count,
            "scheduleScan did not schedule anything")

    def test_checkForNewBuilders(self):
        # Test that checkForNewBuilders() detects a new builder

        # The basic case, where no builders are added.
        builder_scanner = self._getScanner()
        self.assertEqual([], builder_scanner.checkForNewBuilders())

        # Add two builders and ensure they're returned.
        new_builders = ["scooby", "lassie"]
        factory = LaunchpadObjectFactory()
        for builder_name in new_builders:
            factory.makeBuilder(name=builder_name)
        self.assertEqual(
            new_builders, builder_scanner.checkForNewBuilders())

    def test_checkForNewBuilders_detects_builder_only_once(self):
        # checkForNewBuilders() only detects a new builder once.
        builder_scanner = self._getScanner()
        self.assertEqual([], builder_scanner.checkForNewBuilders())
        LaunchpadObjectFactory().makeBuilder(name="sammy")
        self.assertEqual(["sammy"], builder_scanner.checkForNewBuilders())
        self.assertEqual([], builder_scanner.checkForNewBuilders())

    def test_scan(self):
        # See if scan detects new builders.

        def fake_checkForNewBuilders():
            return "new_builders"

        def fake_addScanForBuilders(new_builders):
            self.assertEqual("new_builders", new_builders)

        clock = task.Clock()
        builder_scanner = self._getScanner(clock=clock)
        builder_scanner.checkForNewBuilders = fake_checkForNewBuilders
        builder_scanner.manager.addScanForBuilders = fake_addScanForBuilders
        builder_scanner.scheduleScan = FakeMethod()

        builder_scanner.scan()
        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)

    def test_scan_swallows_exceptions(self):
        # scan() swallows exceptions so the LoopingCall always retries.
        clock = task.Clock()
        scanner = self._getScanner(clock=clock)
        scanner.checkForNewBuilders = FakeMethod(
            failure=Exception("CHAOS REIGNS"))
        scanner.scheduleScan()
        self.assertEqual(1, scanner.checkForNewBuilders.call_count)

        # Even though the previous checkForNewBuilders caused an
        # exception, a rescan will happen as normal.
        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertEqual(2, scanner.checkForNewBuilders.call_count)
        clock.advance(advance)
        self.assertEqual(3, scanner.checkForNewBuilders.call_count)


def is_file_growing(filepath, poll_interval=1, poll_repeat=10):
    """Poll the file size to see if it grows.

    Checks the size of the file in given intervals and returns True as soon as
    it sees the size increase between two polls. If the size does not
    increase after a given number of polls, the function returns False.
    If the file does not exist, the function silently ignores that and waits
    for it to appear on the next pall. If it has not appeared by the last
    poll, the exception is propagated.
    Program execution is blocked during polling.

    :param filepath: The path to the file to be palled.
    :param poll_interval: The number of seconds in between two polls.
    :param poll_repeat: The number times to repeat the polling, so the size is
        polled a total of poll_repeat+1 times. The default values create a
        total poll time of 11 seconds. The BuilddManager logs
        "scanning cycles" every 5 seconds so these settings should see an
        increase if the process is logging to this file.
    """
    last_size = None
    for poll in range(poll_repeat + 1):
        try:
            statinfo = os.stat(filepath)
            if last_size is None:
                last_size = statinfo.st_size
            elif statinfo.st_size > last_size:
                return True
            else:
                # The file should not be shrinking.
                assert statinfo.st_size == last_size
        except OSError:
            if poll == poll_repeat:
                # Propagate only on the last loop, i.e. give up.
                raise
        time.sleep(poll_interval)
    return False


class TestBuilddManagerScript(TestCaseWithFactory):

    layer = LaunchpadScriptLayer

    def testBuilddManagerRuns(self):
        # The `buildd-manager.tac` starts and stops correctly.
        fixture = BuilddManagerTestSetup()
        fixture.setUp()
        fixture.tearDown()
        self.layer.force_dirty_database()

    # XXX Julian 2010-08-06 bug=614275
    # These next 2 tests are in the wrong place, they should be near the
    # implementation of RotatableFileLogObserver and not depend on the
    # behaviour of the buildd-manager.  I've disabled them here because
    # they prevented me from landing this branch which reduces the
    # logging output.

    def disabled_testBuilddManagerLogging(self):
        # The twistd process logs as execpected.
        test_setup = self.useFixture(BuilddManagerTestSetup())
        logfilepath = test_setup.logfile
        # The process logs to its logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # After rotating the log, the process keeps using the old file, no
        # new file is created.
        rotated_logfilepath = logfilepath + '.1'
        os.rename(logfilepath, rotated_logfilepath)
        self.assertTrue(is_file_growing(rotated_logfilepath))
        self.assertFalse(os.access(logfilepath, os.F_OK))
        # Upon receiving the USR1 signal, the process will re-open its log
        # file at the old location.
        test_setup.sendSignal(signal.SIGUSR1)
        self.assertTrue(is_file_growing(logfilepath))
        self.assertTrue(os.access(rotated_logfilepath, os.F_OK))

    def disabled_testBuilddManagerLoggingNoRotation(self):
        # The twistd process does not perform its own rotation.
        # By default twistd will rotate log files that grow beyond
        # 1000000 bytes but this is deactivated for the buildd manager.
        test_setup = BuilddManagerTestSetup()
        logfilepath = test_setup.logfile
        rotated_logfilepath = logfilepath + '.1'
        # Prefill the log file to just under 1000000 bytes.
        test_setup.precreateLogfile(
            "2010-07-27 12:36:54+0200 [-] Starting scanning cycle.\n", 18518)
        self.useFixture(test_setup)
        # The process logs to the logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # No rotation occured.
        self.assertFalse(
            os.access(rotated_logfilepath, os.F_OK),
            "Twistd's log file was rotated by twistd.")
