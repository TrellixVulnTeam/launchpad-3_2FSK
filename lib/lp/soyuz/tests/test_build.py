# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Build features."""

from datetime import datetime, timedelta
import pytz
import unittest

from storm.store import Store
from zope.component import getUtility

from canonical.testing import LaunchpadZopelessLayer
from lp.services.job.model.job import Job
from lp.buildmaster.interfaces.buildbase import IBuildBase
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.build import BuildStatus, IBuild, IBuildSet
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.model.buildqueue import BuildQueue
from lp.soyuz.model.buildpackagejob import BuildPackageJob
from lp.soyuz.model.processor import ProcessorFamilySet
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory


class TestBuildInterface(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_providesInterfaces(self):
        # Build provides IBuildBase and IBuild.
        publisher = SoyuzTestPublisher()
        publisher.prepareBreezyAutotest()
        gedit_src_hist = publisher.getPubSource(
            sourcename="gedit", status=PackagePublishingStatus.PUBLISHED)
        build = gedit_src_hist.createMissingBuilds()[0]

        # The IBuild.calculated_buildstart property asserts
        # that both datebuilt and buildduration are set.
        build.datebuilt = datetime.now(pytz.UTC)
        build.buildduration = timedelta(0, 1)

        self.assertProvides(build, IBuildBase)
        self.assertProvides(build, IBuild)

class TestBuildUpdateDependencies(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def _setupSimpleDepwaitContext(self):
        """Use `SoyuzTestPublisher` to setup a simple depwait context.

        Return an `IBuild` in MANUALDEWAIT state and depending on a
        binary that exists and is reachable.
        """
        test_publisher = SoyuzTestPublisher()
        test_publisher.prepareBreezyAutotest()

        depwait_source = test_publisher.getPubSource(
            sourcename='depwait-source')

        test_publisher.getPubBinaries(
            binaryname='dep-bin',
            status=PackagePublishingStatus.PUBLISHED)

        [depwait_build] = depwait_source.createMissingBuilds()
        depwait_build.buildstate = BuildStatus.MANUALDEPWAIT
        depwait_build.dependencies = 'dep-bin'

        return depwait_build

    def testBuildqueueRemoval(self):
        """Test removing buildqueue items.

        Removing a Buildqueue row should also remove its associated
        BuildPackageJob and Job rows.
        """
        # Create a build in depwait.
        depwait_build = self._setupSimpleDepwaitContext()

        # Grab the relevant db records for later comparison.
        store = Store.of(depwait_build)
        build_package_job = store.find(
            BuildPackageJob,
            depwait_build.id == BuildPackageJob.build).one()
        build_package_job_id = build_package_job.id
        job_id = store.find(Job, Job.id == build_package_job.job.id).one().id
        build_queue_id = store.find(
            BuildQueue, BuildQueue.job == job_id).one().id

        depwait_build.buildqueue_record.destroySelf()

        # Test that the records above no longer exist in the db.
        self.assertEqual(
            store.find(
                BuildPackageJob,
                BuildPackageJob.id == build_package_job_id).count(),
            0)
        self.assertEqual(
            store.find(Job, Job.id == job_id).count(),
            0)
        self.assertEqual(
            store.find(BuildQueue, BuildQueue.id == build_queue_id).count(),
            0)

    def testUpdateDependenciesWorks(self):
        # Calling `IBuild.updateDependencies` makes the build
        # record ready for dispatch.
        depwait_build = self._setupSimpleDepwaitContext()
        depwait_build.updateDependencies()
        self.assertEquals(depwait_build.dependencies, '')

    def testInvalidDependencies(self):
        # Calling `IBuild.updateDependencies` on a build with
        # invalid 'dependencies' raises an AssertionError.
        # Anything not following '<name> [([relation] <version>)][, ...]'
        depwait_build = self._setupSimpleDepwaitContext()

        # None is not a valid dependency values.
        depwait_build.dependencies = None
        self.assertRaises(
            AssertionError, depwait_build.updateDependencies)

        # Missing 'name'.
        depwait_build.dependencies = '(>> version)'
        self.assertRaises(
            AssertionError, depwait_build.updateDependencies)

        # Missing 'version'.
        depwait_build.dependencies = 'name (>>)'
        self.assertRaises(
            AssertionError, depwait_build.updateDependencies)

        # Missing comman between dependencies.
        depwait_build.dependencies = 'name1 name2'
        self.assertRaises(
            AssertionError, depwait_build.updateDependencies)

    def testBug378828(self):
        # `IBuild.updateDependencies` copes with the scenario where
        # the corresponding source publication is not active (deleted)
        # and the source original component is not a valid ubuntu
        # component.
        depwait_build = self._setupSimpleDepwaitContext()

        depwait_build.current_source_publication.requestDeletion(
            depwait_build.sourcepackagerelease.creator)
        contrib = getUtility(IComponentSet).new('contrib')
        depwait_build.sourcepackagerelease.component = contrib

        depwait_build.updateDependencies()
        self.assertEquals(depwait_build.dependencies, '')


class BaseTestCaseWithThreeBuilds(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Publish some builds for the test archive."""
        super(BaseTestCaseWithThreeBuilds, self).setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # Create three builds for the publisher's default
        # distroseries.
        self.builds = []
        self.sources = []
        gedit_src_hist = self.publisher.getPubSource(
            sourcename="gedit", status=PackagePublishingStatus.PUBLISHED)
        self.builds += gedit_src_hist.createMissingBuilds()
        self.sources.append(gedit_src_hist)

        firefox_src_hist = self.publisher.getPubSource(
            sourcename="firefox", status=PackagePublishingStatus.PUBLISHED)
        self.builds += firefox_src_hist.createMissingBuilds()
        self.sources.append(firefox_src_hist)

        gtg_src_hist = self.publisher.getPubSource(
            sourcename="getting-things-gnome",
            status=PackagePublishingStatus.PUBLISHED)
        self.builds += gtg_src_hist.createMissingBuilds()
        self.sources.append(gtg_src_hist)


class TestBuildSetGetBuildsForArchive(BaseTestCaseWithThreeBuilds):

    def setUp(self):
        """Publish some builds for the test archive."""
        super(TestBuildSetGetBuildsForArchive, self).setUp()

        # Short-cuts for our tests.
        self.archive = self.publisher.distroseries.main_archive
        self.build_set = getUtility(IBuildSet)

    def test_getBuildsForArchive_no_params(self):
        # All builds should be returned when called without filtering
        builds = self.build_set.getBuildsForArchive(self.archive)
        self.assertContentEqual(builds, self.builds)

    def test_getBuildsForArchive_by_arch_tag(self):
        # Results can be filtered by architecture tag.
        i386_builds = self.builds[:]
        hppa_build = i386_builds.pop()
        hppa_build.distroarchseries = self.publisher.distroseries['hppa']

        builds = self.build_set.getBuildsForArchive(self.archive,
                                                    arch_tag="i386")
        self.assertContentEqual(builds, i386_builds)


class TestBuildSetGetBuildsForBuilder(BaseTestCaseWithThreeBuilds):

    def setUp(self):
        super(TestBuildSetGetBuildsForBuilder, self).setUp()

        # Short-cuts for our tests.
        self.build_set = getUtility(IBuildSet)

        # Create a 386 builder
        owner = self.factory.makePerson()
        processor_family = ProcessorFamilySet().getByProcessorName('386')
        processor = processor_family.processors[0]
        builder_set = getUtility(IBuilderSet)

        self.builder = builder_set.new(
            processor, 'http://example.com', 'Newbob', 'New Bob the Builder',
            'A new and improved bob.', owner)

        # Ensure that our builds were all built by the test builder.
        for build in self.builds:
            build.builder = self.builder

    def test_getBuildsForBuilder_no_params(self):
        # All builds should be returned when called without filtering
        builds = self.build_set.getBuildsForBuilder(self.builder.id)
        self.assertContentEqual(builds, self.builds)

    def test_getBuildsForBuilder_by_arch_tag(self):
        # Results can be filtered by architecture tag.
        i386_builds = self.builds[:]
        hppa_build = i386_builds.pop()
        hppa_build.distroarchseries = self.publisher.distroseries['hppa']

        builds = self.build_set.getBuildsForBuilder(self.builder.id,
                                                    arch_tag="i386")
        self.assertContentEqual(builds, i386_builds)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
