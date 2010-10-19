# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction
from canonical.testing import LaunchpadZopelessLayer
from storm.exceptions import IntegrityError
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy
from lp.soyuz.interfaces.distributionjob import (
    IInitialiseDistroSeriesJobSource,
    )
from lp.soyuz.model.initialisedistroseriesjob import (
    InitialiseDistroSeriesJob,
    )
from lp.soyuz.scripts.initialise_distroseries import InitialisationError
from lp.testing import TestCaseWithFactory


class InitialiseDistroSeriesJobTests(TestCaseWithFactory):
    """Test case for InitialiseDistroSeriesJob."""

    layer = LaunchpadZopelessLayer

    def test_getOopsVars(self):
        distroseries = self.factory.makeDistroSeries()
        job = getUtility(IInitialiseDistroSeriesJobSource).create(
            distroseries)
        vars = job.getOopsVars()
        naked_job = removeSecurityProxy(job)
        self.assertIn(
            ('distribution_id', distroseries.distribution.id), vars)
        self.assertIn(('distroseries_id', distroseries.id), vars)
        self.assertIn(('distribution_job_id', naked_job.context.id), vars)

    def _getJobs(self):
        """Return the pending InitialiseDistroSeriesJobs as a list."""
        return list(InitialiseDistroSeriesJob.iterReady())

    def _getJobCount(self):
        """Return the number of InitialiseDistroSeriesJobs in the
        queue."""
        return len(self._getJobs())

    def test_create_only_creates_one(self):
        distroseries = self.factory.makeDistroSeries()
        # If there's already a InitialiseDistroSeriesJob for a
        # DistroSeries, InitialiseDistroSeriesJob.create() won't create
        # a new one.
        job = getUtility(IInitialiseDistroSeriesJobSource).create(
            distroseries)
        transaction.commit()

        # There will now be one job in the queue.
        self.assertEqual(1, self._getJobCount())

        new_job = getUtility(IInitialiseDistroSeriesJobSource).create(
            distroseries)

        # This is less than ideal
        self.assertRaises(IntegrityError, self._getJobCount)

    def test_run(self):
        """Test that InitialiseDistroSeriesJob.run() actually
        initialises builds and copies from the parent."""
        distroseries = self.factory.makeDistroSeries()

        job = getUtility(IInitialiseDistroSeriesJobSource).create(
            distroseries)

        # Since our new distroseries doesn't have a parent set, and the first
        # thing that run() will execute is checking the distroseries, if it
        # returns an InitialisationError, then it's good.
        self.assertRaisesWithContent(
            InitialisationError, "Parent series required.", job.run)

    def test_arguments(self):
        """Test that InitialiseDistroSeriesJob specified with arguments can
        be gotten out again."""
        distroseries = self.factory.makeDistroSeries()
        arches = (u'i386', u'amd64')
        packagesets = (u'foo', u'bar', u'baz')

        job = getUtility(IInitialiseDistroSeriesJobSource).create(
            distroseries, arches, packagesets)

        naked_job = removeSecurityProxy(job)
        self.assertEqual(naked_job.distroseries, distroseries)
        self.assertEqual(naked_job.arches, arches)
        self.assertEqual(naked_job.packagesets, packagesets)
        self.assertEqual(naked_job.rebuild, False)
