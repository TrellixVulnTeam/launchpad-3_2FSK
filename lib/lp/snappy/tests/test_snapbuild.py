# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test snap package build features."""

__metaclass__ = type

from datetime import timedelta

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.registry.enums import PersonVisibility
from lp.services.features.testing import FeatureFixture
from lp.snappy.interfaces.snap import (
    SNAP_FEATURE_FLAG,
    SnapFeatureDisabled,
    )
from lp.snappy.interfaces.snapbuild import (
    ISnapBuild,
    ISnapBuildSet,
    )
from lp.soyuz.enums import ArchivePurpose
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer


class TestSnapBuildFeatureFlag(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # Without a feature flag, we will not create new SnapBuilds.
        class MockSnap:
            require_virtualized = False

        self.assertRaises(
            SnapFeatureDisabled, getUtility(ISnapBuildSet).new,
            None, MockSnap(), self.factory.makeArchive(),
            self.factory.makeDistroArchSeries(), None)


class TestSnapBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestSnapBuild, self).setUp()
        self.useFixture(FeatureFixture({SNAP_FEATURE_FLAG: u"on"}))
        self.build = self.factory.makeSnapBuild()

    def test_implements_interfaces(self):
        # SnapBuild implements IPackageBuild and ISnapBuild.
        self.assertProvides(self.build, IPackageBuild)
        self.assertProvides(self.build, ISnapBuild)

    def test_queueBuild(self):
        # SnapBuild can create the queue entry for itself.
        bq = self.build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(
            self.build.build_farm_job, removeSecurityProxy(bq)._build_farm_job)
        self.assertEqual(self.build, bq.specific_build)
        self.assertEqual(self.build.virtualized, bq.virtualized)
        self.assertIsNotNone(bq.processor)
        self.assertEqual(bq, self.build.buildqueue_record)

    def test_current_component_primary(self):
        # SnapBuilds for primary archives always build in universe for the
        # time being.
        self.assertEqual(ArchivePurpose.PRIMARY, self.build.archive.purpose)
        self.assertEqual("universe", self.build.current_component.name)

    def test_current_component_ppa(self):
        # PPAs only have indices for main, so SnapBuilds for PPAs always
        # build in main.
        build = self.factory.makeSnapBuild(archive=self.factory.makeArchive())
        self.assertEqual("main", build.current_component.name)

    def test_is_private(self):
        # A SnapBuild is private iff its Snap and archive are.
        self.assertFalse(self.build.is_private)
        private_team = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE)
        with person_logged_in(private_team.teamowner):
            build = self.factory.makeSnapBuild(
                requester=private_team.teamowner, owner=private_team)
            self.assertTrue(build.is_private)
        private_archive = self.factory.makeArchive(private=True)
        with person_logged_in(private_archive.owner):
            build = self.factory.makeSnapBuild(archive=private_archive)
            self.assertTrue(build.is_private)

    def test_can_be_cancelled(self):
        # For all states that can be cancelled, can_be_cancelled returns True.
        ok_cases = [
            BuildStatus.BUILDING,
            BuildStatus.NEEDSBUILD,
            ]
        for status in BuildStatus:
            if status in ok_cases:
                self.assertTrue(self.build.can_be_cancelled)
            else:
                self.assertFalse(self.build.can_be_cancelled)

    def test_cancel_not_in_progress(self):
        # The cancel() method for a pending build leaves it in the CANCELLED
        # state.
        self.build.queueBuild()
        self.build.cancel()
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)
        self.assertIsNone(self.build.buildqueue_record)

    def test_cancel_in_progress(self):
        # The cancel() method for a building build leaves it in the
        # CANCELLING state.
        bq = self.build.queueBuild()
        bq.markAsBuilding(self.factory.makeBuilder())
        self.build.cancel()
        self.assertEqual(BuildStatus.CANCELLING, self.build.status)
        self.assertEqual(bq, self.build.buildqueue_record)

    def test_estimateDuration(self):
        # Without previous builds, the default time estimate is 30m.
        self.assertEqual(1800, self.build.estimateDuration().seconds)

    def test_estimateDuration_with_history(self):
        # Previous successful builds of the same snap package are used for
        # estimates.
        self.factory.makeSnapBuild(
            requester=self.build.requester, snap=self.build.snap,
            distroarchseries=self.build.distro_arch_series,
            status=BuildStatus.FULLYBUILT, duration=timedelta(seconds=335))
        for i in range(3):
            self.factory.makeSnapBuild(
                requester=self.build.requester, snap=self.build.snap,
                distroarchseries=self.build.distro_arch_series,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20))
        self.assertEqual(335, self.build.estimateDuration().seconds)

    def test_build_cookie(self):
        build = self.factory.makeSnapBuild()
        self.assertEqual('SNAPBUILD-%d' % build.id, build.build_cookie)

    def test_getFileByName_logs(self):
        # getFileByName returns the logs when requested by name.
        self.build.setLog(
            self.factory.makeLibraryFileAlias(filename="buildlog.txt.gz"))
        self.assertEqual(
            self.build.log, self.build.getFileByName("buildlog.txt.gz"))
        self.assertRaises(NotFoundError, self.build.getFileByName, "foo")
        self.build.storeUploadLog("uploaded")
        self.assertEqual(
            self.build.upload_log,
            self.build.getFileByName(self.build.upload_log.filename))

    def test_getFileByName_uploaded_files(self):
        # getFileByName returns uploaded files when requested by name.
        filenames = ("ubuntu.squashfs", "ubuntu.manifest")
        lfas = []
        for filename in filenames:
            lfa = self.factory.makeLibraryFileAlias(filename=filename)
            lfas.append(lfa)
            self.build.addFile(lfa)
        self.assertContentEqual(
            lfas, [row[1] for row in self.build.getFiles()])
        for filename, lfa in zip(filenames, lfas):
            self.assertEqual(lfa, self.build.getFileByName(filename))
        self.assertRaises(NotFoundError, self.build.getFileByName, "missing")

    def test_verifySuccessfulUpload(self):
        self.assertFalse(self.build.verifySuccessfulUpload())
        self.factory.makeSnapFile(snapbuild=self.build)
        self.assertTrue(self.build.verifySuccessfulUpload())

    def addFakeBuildLog(self, build):
        build.setLog(self.factory.makeLibraryFileAlias("mybuildlog.txt"))

    def test_log_url(self):
        # The log URL for a snap package build will use the archive context.
        self.addFakeBuildLog(self.build)
        self.assertEqual(
            "http://launchpad.dev/~%s/+snap/%s/+build/%d/+files/"
            "mybuildlog.txt" % (
                self.build.snap.owner.name, self.build.snap.name,
                self.build.id),
            self.build.log_url)


class TestSnapBuildSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestSnapBuildSet, self).setUp()
        self.useFixture(FeatureFixture({SNAP_FEATURE_FLAG: u"on"}))

    def test_getByBuildFarmJob_works(self):
        build = self.factory.makeSnapBuild()
        self.assertEqual(
            build,
            getUtility(ISnapBuildSet).getByBuildFarmJob(build.build_farm_job))

    def test_getByBuildFarmJob_returns_None_when_missing(self):
        bpb = self.factory.makeBinaryPackageBuild()
        self.assertIsNone(
            getUtility(ISnapBuildSet).getByBuildFarmJob(bpb.build_farm_job))

    def test_getByBuildFarmJobs_works(self):
        builds = [self.factory.makeSnapBuild() for i in range(10)]
        self.assertContentEqual(
            builds,
            getUtility(ISnapBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]))

    def test_getByBuildFarmJobs_works_empty(self):
        self.assertContentEqual(
            [], getUtility(ISnapBuildSet).getByBuildFarmJobs([]))
