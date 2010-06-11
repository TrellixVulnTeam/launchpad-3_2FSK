# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BugJobs."""

__metaclass__ = type

import pytz
import transaction
import unittest
from datetime import datetime

from zope.component import getUtility

from canonical.launchpad.scripts.tests import run_script
from canonical.testing import LaunchpadZopelessLayer

from lp.bugs.adapters.bugchange import BugDescriptionChange
from lp.bugs.interfaces.bugjob import ICalculateBugHeatJobSource
from lp.bugs.model.bugheat import CalculateBugHeatJob
from lp.bugs.scripts.bugheat import BugHeatCalculator
from lp.testing import TestCaseWithFactory
from lp.testing.factory import LaunchpadObjectFactory


class CalculateBugHeatJobTestCase(TestCaseWithFactory):
    """Test case for CalculateBugHeatJob."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(CalculateBugHeatJobTestCase, self).setUp()
        self.bug = self.factory.makeBug()

        # NB: This looks like it should go in the teardown, however
        # creating the bug causes a job to be added for it. We clear
        # this out so that our tests are consistent.
        self._completeJobsAndAssertQueueEmpty()

    def _completeJobsAndAssertQueueEmpty(self):
        """Make sure that all the CalculateBugHeatJobs are completed."""
        for bug_job in getUtility(ICalculateBugHeatJobSource).iterReady():
            bug_job.job.start()
            bug_job.job.complete()
        self.assertEqual(0, self._getJobCount())

    def _getJobCount(self):
        """Return the number of CalculateBugHeatJobs in the queue."""
        return len(self._getJobs())

    def _getJobs(self):
        """Return the pending CalculateBugHeatJobs as a list."""
        return list(CalculateBugHeatJob.iterReady())

    def test_run(self):
        # CalculateBugHeatJob.run() sets calculates and sets the heat
        # for a bug.
        job = CalculateBugHeatJob.create(self.bug)
        bug_heat_calculator = BugHeatCalculator(self.bug)

        job.run()
        self.assertEqual(
            bug_heat_calculator.getBugHeat(), self.bug.heat)

    def test_utility(self):
        # CalculateBugHeatJobSource is a utility for acquiring
        # CalculateBugHeatJobs.
        utility = getUtility(ICalculateBugHeatJobSource)
        self.assertTrue(
            ICalculateBugHeatJobSource.providedBy(utility))

    def test_create_only_creates_one(self):
        # If there's already a CalculateBugHeatJob for a bug,
        # CalculateBugHeatJob.create() won't create a new one.
        job = CalculateBugHeatJob.create(self.bug)

        # There will now be one job in the queue.
        self.assertEqual(1, self._getJobCount())

        new_job = CalculateBugHeatJob.create(self.bug)

        # The two jobs will in fact be the same job.
        self.assertEqual(job, new_job)

        # And the queue will still have a length of 1.
        self.assertEqual(1, self._getJobCount())

    def test_cronscript_succeeds(self):
        # The calculate-bug-heat cronscript will run all pending
        # CalculateBugHeatJobs.
        CalculateBugHeatJob.create(self.bug)
        transaction.commit()

        retcode, stdout, stderr = run_script(
            'cronscripts/calculate-bug-heat.py', [],
            expect_returncode=0)
        self.assertEqual('', stdout)
        self.assertIn(
            'INFO    Ran 1 CalculateBugHeatJob jobs.\n', stderr)

    def test_getOopsVars(self):
        # BugJobDerived.getOopsVars() returns the variables to be used
        # when logging an OOPS for a bug job. We test this using
        # CalculateBugHeatJob because BugJobDerived doesn't let us
        # create() jobs.
        job = CalculateBugHeatJob.create(self.bug)
        vars = job.getOopsVars()

        # The Bug ID, BugJob ID and BugJob type will be returned by
        # getOopsVars().
        self.assertIn(('bug_id', self.bug.id), vars)
        self.assertIn(('bug_job_id', job.context.id), vars)
        self.assertIn(('bug_job_type', job.context.job_type.title), vars)


class MaxHeatByTargetBase:
    """Base class for testing a bug target's max_bug_heat attribute."""

    layer = LaunchpadZopelessLayer

    factory = LaunchpadObjectFactory()

    # The target to test.
    target = None

    # Does the target have a set method?
    delegates_setter = False

    def test_target_max_bug_heat_default(self):
        self.assertEqual(self.target.max_bug_heat, None)

    def test_set_target_max_bug_heat(self):
        if self.delegates_setter:
            self.assertRaises(
                NotImplementedError, self.target.setMaxBugHeat, 1000)
        else:
            self.target.setMaxBugHeat(1000)
            self.assertEqual(self.target.max_bug_heat, 1000)


class ProjectMaxHeatByTargetTest(MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a project has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeProduct()


class DistributionMaxHeatByTargetTest(MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a distribution has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeDistribution()


class DistributionSourcePackageMaxHeatByTargetTest(
    MaxHeatByTargetBase, unittest.TestCase):
    """Ensure distro source package has max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeDistributionSourcePackage()


class SourcePackageMaxHeatByTargetTest(
    MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a source package has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeSourcePackage()
        self.delegates_setter = True


class ProductSeriesMaxHeatByTargetTest(
    MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a product series has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeProductSeries()
        self.delegates_setter = True


class DistroSeriesMaxHeatByTargetTest(
    MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a distro series has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeDistroSeries()
        self.delegates_setter = True


class ProjectGroupMaxHeatByTargetTest(
    MaxHeatByTargetBase, unittest.TestCase):
    """Ensure a project group has a max_bug_heat value that can be set."""

    def setUp(self):
        self.target = self.factory.makeProject()

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
