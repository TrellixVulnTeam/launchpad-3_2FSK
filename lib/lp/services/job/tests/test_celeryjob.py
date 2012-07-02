# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.code.model.branchjob import BranchScanJob
from lp.scripts.helpers import TransactionFreeOperation
from lp.services.features.testing import FeatureFixture
from lp.services.job.tests import (
    drain_celery_queues,
    monitor_celery,
    )
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import ZopelessAppServerLayer


class TestRunMissingJobs(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def setUp(self):
        super(TestRunMissingJobs, self).setUp()
        from lp.services.job.celeryjob import (
            find_missing_ready,
            run_missing_ready,
        )
        self.find_missing_ready = find_missing_ready
        self.run_missing_ready = run_missing_ready

    def createMissingJob(self):
        job = BranchScanJob.create(self.factory.makeBranch())
        self.addCleanup(drain_celery_queues)
        return job

    # XXX wgrant 2012-06-27 bug=1018235: Disabled due to intermittent
    # failure on buildbot.
    def disabled_test_find_missing_ready(self):
        """A job which is ready but not queued is "missing"."""
        job = self.createMissingJob()
        self.assertEqual([job], self.find_missing_ready(BranchScanJob))
        job.runViaCelery()
        self.assertEqual([], self.find_missing_ready(BranchScanJob))
        drain_celery_queues()
        self.assertEqual([job], self.find_missing_ready(BranchScanJob))

    def test_run_missing_ready_not_enabled(self):
        """run_missing_ready does nothing if the class isn't enabled."""
        self.createMissingJob()
        with monitor_celery() as responses:
            with dbuser('run_missing_ready'):
                with TransactionFreeOperation.require():
                    self.run_missing_ready(_no_init=True)
        self.assertEqual([], responses)

    def test_run_missing_ready(self):
        """run_missing_ready requests the job to run if not scheduled."""
        self.createMissingJob()
        self.useFixture(
            FeatureFixture({'jobs.celery.enabled_classes': 'BranchScanJob'}))
        with monitor_celery() as responses:
            with dbuser('run_missing_ready'):
                with TransactionFreeOperation.require():
                    self.run_missing_ready(_no_init=True)
        self.assertEqual(1, len(responses))
