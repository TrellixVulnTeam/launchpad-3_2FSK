# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from storm.exceptions import IntegrityError
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.database.sqlbase import flush_database_caches
from canonical.launchpad.scripts.tests import run_script
from canonical.testing import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.distributionjob import (
    IInitialiseDistroSeriesJobSource,
    )
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.model.initialisedistroseriesjob import InitialiseDistroSeriesJob
from lp.soyuz.scripts.initialise_distroseries import InitialisationError
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory


class InitialiseDistroSeriesJobTests(TestCaseWithFactory):
    """Test case for InitialiseDistroSeriesJob."""

    layer = DatabaseFunctionalLayer

    @property
    def job_source(self):
        return getUtility(IInitialiseDistroSeriesJobSource)

    def test_getOopsVars(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        job = self.job_source.create(distroseries, [parent.id])
        vars = job.getOopsVars()
        naked_job = removeSecurityProxy(job)
        self.assertIn(
            ('distribution_id', distroseries.distribution.id), vars)
        self.assertIn(('distroseries_id', distroseries.id), vars)
        self.assertIn(('distribution_job_id', naked_job.context.id), vars)
        self.assertIn(('parent_distroseries_ids', [parent.id]), vars)

    def _getJobs(self):
        """Return the pending InitialiseDistroSeriesJobs as a list."""
        return list(InitialiseDistroSeriesJob.iterReady())

    def _getJobCount(self):
        """Return the number of InitialiseDistroSeriesJobs in the
        queue."""
        return len(self._getJobs())

    def test_create_only_creates_one(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # If there's already a InitialiseDistroSeriesJob for a
        # DistroSeries, InitialiseDistroSeriesJob.create() won't create
        # a new one.
        self.job_source.create(distroseries, [parent.id])
        self.job_source.create(distroseries, [parent.id])
        self.assertRaises(IntegrityError, flush_database_caches)

    def test_run_with_previous_series_already_set(self):
        # InitialisationError is raised if a parent series already exists
        # for this series.
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        getUtility(IDistroSeriesParentSet).new(
            distroseries, parent, initialized=True)

        job = self.job_source.create(distroseries, [parent.id])
        expected_message = (
            "DistroSeries {child.name} has already been initialized"
            ".").format(child=distroseries)
        self.assertRaisesWithContent(
            InitialisationError, expected_message, job.run)

    def test_arguments(self):
        """Test that InitialiseDistroSeriesJob specified with arguments can
        be gotten out again."""
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        arches = (u'i386', u'amd64')
        packagesets = (u'1', u'2', u'3')
        overlays = (True, )
        overlay_pockets = ('Updates', )
        overlay_components = ('restricted', )

        job = self.job_source.create(
            distroseries, [parent.id], arches, packagesets, False, overlays,
            overlay_pockets, overlay_components)

        naked_job = removeSecurityProxy(job)
        self.assertEqual(naked_job.distroseries, distroseries)
        self.assertEqual(naked_job.arches, arches)
        self.assertEqual(naked_job.packagesets, packagesets)
        self.assertEqual(naked_job.rebuild, False)
        self.assertEqual(naked_job.parents, (parent.id, ))
        self.assertEqual(naked_job.overlays, overlays)
        self.assertEqual(naked_job.overlay_pockets, overlay_pockets)
        self.assertEqual(naked_job.overlay_components, overlay_components)

    def test_parent(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        job = self.job_source.create(distroseries, [parent.id])
        naked_job = removeSecurityProxy(job)
        self.assertEqual((parent.id, ), naked_job.parents)

    def test_getPendingJobsForDistroseries(self):
        # Pending initialisation jobs can be retrieved per distroseries.
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        another_distroseries = self.factory.makeDistroSeries()
        self.job_source.create(distroseries, [parent.id])
        self.job_source.create(another_distroseries, [parent.id])
        initialise_utility = getUtility(IInitialiseDistroSeriesJobSource)
        [job] = list(initialise_utility.getPendingJobsForDistroseries(
            distroseries))
        self.assertEqual(job.distroseries, distroseries)


class InitialiseDistroSeriesJobTestsWithPackages(TestCaseWithFactory):
    """Test case for InitialiseDistroSeriesJob."""

    layer = LaunchpadZopelessLayer

    @property
    def job_source(self):
        return getUtility(IInitialiseDistroSeriesJobSource)

    def _create_child(self):
        pf = self.factory.makeProcessorFamily()
        pf.addProcessor('x86', '', '')
        parent = self.factory.makeDistroSeries()
        parent_das = self.factory.makeDistroArchSeries(
            distroseries=parent, processorfamily=pf)
        lf = self.factory.makeLibraryFileAlias()
        # Since the LFA needs to be in the librarian, commit.
        transaction.commit()
        parent_das.addOrUpdateChroot(lf)
        parent_das.supports_virtualized = True
        parent.nominatedarchindep = parent_das
        publisher = SoyuzTestPublisher()
        publisher.prepareBreezyAutotest()
        packages = {'udev': '0.1-1', 'libc6': '2.8-1'}
        for package in packages.keys():
            publisher.getPubBinaries(
                distroseries=parent, binaryname=package,
                version=packages[package],
                status=PackagePublishingStatus.PUBLISHED)
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', parent.owner,
            distroseries=parent)
        self.test1_packageset_id = str(test1.id)
        test1.addSources('udev')
        parent.updatePackageCount()
        child = self.factory.makeDistroSeries()
        # Make sure everything hits the database, switching db users aborts.
        transaction.commit()
        return parent, child

    def test_job(self):
        parent, child = self._create_child()
        job = self.job_source.create(child, [parent.id])
        self.layer.switchDbUser('initialisedistroseries')

        job.run()
        child.updatePackageCount()
        self.assertEqual(parent.sourcecount, child.sourcecount)
        self.assertEqual(parent.binarycount, child.binarycount)

    def test_job_with_arguments(self):
        parent, child = self._create_child()
        arch = parent.nominatedarchindep.architecturetag
        job = self.job_source.create(
            child, [parent.id], packagesets=(self.test1_packageset_id,),
            arches=(arch,), rebuild=True)
        self.layer.switchDbUser('initialisedistroseries')

        job.run()
        child.updatePackageCount()
        builds = child.getBuildRecords(
            build_state=BuildStatus.NEEDSBUILD,
            pocket=PackagePublishingPocket.RELEASE)
        self.assertEqual(child.sourcecount, 1)
        self.assertEqual(child.binarycount, 0)
        self.assertEqual(builds.count(), 1)

    def test_job_with_none_arguments(self):
        parent, child = self._create_child()
        job = self.job_source.create(
            child, [parent.id], packagesets=None, arches=None,
            overlays=None, overlay_pockets=None,
            overlay_components=None, rebuild=True)
        self.layer.switchDbUser('initialisedistroseries')
        job.run()
        child.updatePackageCount()

        self.assertEqual(parent.sourcecount, child.sourcecount)

    def test_cronscript(self):
        run_script(
            'cronscripts/run_jobs.py', ['-v', 'initialisedistroseries'])
