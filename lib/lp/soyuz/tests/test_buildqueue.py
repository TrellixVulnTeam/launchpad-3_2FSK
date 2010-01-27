# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
# pylint: disable-msg=C0324

"""Test BuildQueue features."""

from datetime import datetime, timedelta
from pytz import utc

from zope.component import getUtility
from zope.interface.verify import verifyObject

from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)
from canonical.testing import LaunchpadZopelessLayer

from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.buildfarmjob import (
    BuildFarmJobType)
from lp.buildmaster.model.builder import specific_job_classes
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.services.job.model.job import Job
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.buildqueue import IBuildQueueSet
from lp.soyuz.model.buildqueue import BuildQueue
from lp.soyuz.model.processor import ProcessorFamilySet
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.model.build import Build
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory


def find_job(test, name, processor='386'):
    """Find build and queue instance for the given source and processor."""
    for build in test.builds:
        if (build.sourcepackagerelease.name == name
            and build.processor.name == processor):
            return (build, build.buildqueue_record)
    return (None, None)


def nth_builder(test, build, n):
    """Find nth builder that can execute the given build."""
    builder = None
    builders = test.builders.get(builder_key(build), [])
    try:
        builder = builders[n-1]
    except IndexError:
        pass
    return builder


def assign_to_builder(test, job_name, builder_number, processor='386'):
    """Simulate assigning a build to a builder."""
    build, bq = find_job(test, job_name, processor)
    builder = nth_builder(test, build, builder_number)
    bq.markAsBuilding(builder)


def print_build_setup(builds):
    """Show the build set-up for a particular test."""
    def processor_name(bq):
        proc = getattr(bq, 'processor', None)
        if proc is None:
            return 'None'
        else:
            return proc.name

    for build in builds:
        bq = build.buildqueue_record
        source = None
        for attr in ('sourcepackagerelease', 'sourcepackagename'):
            source = getattr(build, attr, None)
            if source is not None:
                break
        print "%5s, %18s, p:%5s, v:%5s e:%s *** s:%5s" % (
            bq.id, source.name, processor_name(bq),
            bq.virtualized, bq.estimated_duration, bq.lastscore)


def builder_key(job):
    """Access key for builders capable of running the given job."""
    return (job.processor.id, job.is_virtualized)


def check_mintime_to_builder(
    test, bq, head_job_processor, head_job_virtualized, min_time):
    """Test the estimated time until a builder becomes available."""
    delay = bq._estimateTimeToNextBuilder(
        head_job_processor, head_job_virtualized)
    if min_time is not None:
        test.assertTrue(
            almost_equal(delay, min_time),
            "Wrong min time to next available builder (%s != %s)"
            % (delay, min_time))
    else:
        test.assertTrue(delay is None, "No delay to next builder available")


def almost_equal(a, b, deviation=1):
    """Compare the values tolerating the given deviation.

    This used to  spurious failures in time based tests.
    """
    if abs(a - b) <= deviation:
        return True
    else:
        return False


def set_remaining_time_for_running_job(bq, remainder):
    """Set remaining running time for job."""
    offset = bq.estimated_duration.seconds - remainder
    bq.setDateStarted(
        datetime.utcnow().replace(tzinfo=utc) - timedelta(seconds=offset))


def check_delay_for_job(test, the_job, delay, head_job_platform):
    # Obtain the builder statistics pertaining to this job.
    builder_data = the_job._getBuilderData()
    builders_in_total, builders_for_job, builder_stats = builder_data
    estimated_delay = the_job._estimateJobDelay(
        builders_in_total, builder_stats)
    test.assertEqual(
        estimated_delay,
        (delay, head_job_platform))


class TestBuildQueueSet(TestCaseWithFactory):
    """Test for `BuildQueueSet`."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestBuildQueueSet, self).setUp()
        self.buildqueueset = getUtility(IBuildQueueSet)

    def test_baseline(self):
        verifyObject(IBuildQueueSet, self.buildqueueset)

    def test_getByJob_none(self):
        job = Job()
        self.assertEquals(None, self.buildqueueset.getByJob(job))

    def test_getByJob(self):
        job = Job()
        buildqueue = BuildQueue(job=job.id)
        self.assertEquals(buildqueue, self.buildqueueset.getByJob(job))


class TestBuildQueueBase(TestCaseWithFactory):
    """Setup the test publisher and some builders."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestBuildQueueBase, self).setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # First make nine 'i386' builders.
        self.i1 = self.factory.makeBuilder(name='i386-v-1')
        self.i2 = self.factory.makeBuilder(name='i386-v-2')
        self.i3 = self.factory.makeBuilder(name='i386-v-3')
        self.i4 = self.factory.makeBuilder(name='i386-v-4')
        self.i5 = self.factory.makeBuilder(name='i386-v-5')
        self.i6 = self.factory.makeBuilder(name='i386-n-6', virtualized=False)
        self.i7 = self.factory.makeBuilder(name='i386-n-7', virtualized=False)
        self.i8 = self.factory.makeBuilder(name='i386-n-8', virtualized=False)
        self.i9 = self.factory.makeBuilder(name='i386-n-9', virtualized=False)

        # Next make seven 'hppa' builders.
        processor_fam = ProcessorFamilySet().getByName('hppa')
        hppa_proc = processor_fam.processors[0]
        self.h1 = self.factory.makeBuilder(
            name='hppa-v-1', processor=hppa_proc)
        self.h2 = self.factory.makeBuilder(
            name='hppa-v-2', processor=hppa_proc)
        self.h3 = self.factory.makeBuilder(
            name='hppa-v-3', processor=hppa_proc)
        self.h4 = self.factory.makeBuilder(
            name='hppa-v-4', processor=hppa_proc)
        self.h5 = self.factory.makeBuilder(
            name='hppa-n-5', processor=hppa_proc, virtualized=False)
        self.h6 = self.factory.makeBuilder(
            name='hppa-n-6', processor=hppa_proc, virtualized=False)
        self.h7 = self.factory.makeBuilder(
            name='hppa-n-7', processor=hppa_proc, virtualized=False)

        # Finally make five 'amd64' builders.
        processor_fam = ProcessorFamilySet().getByName('amd64')
        amd_proc = processor_fam.processors[0]
        self.a1 = self.factory.makeBuilder(
            name='amd64-v-1', processor=amd_proc)
        self.a2 = self.factory.makeBuilder(
            name='amd64-v-2', processor=amd_proc)
        self.a3 = self.factory.makeBuilder(
            name='amd64-v-3', processor=amd_proc)
        self.a4 = self.factory.makeBuilder(
            name='amd64-n-4', processor=amd_proc, virtualized=False)
        self.a5 = self.factory.makeBuilder(
            name='amd64-n-5', processor=amd_proc, virtualized=False)

        self.builders = dict()
        processor_fam = ProcessorFamilySet().getByName('x86')
        x86_proc = processor_fam.processors[0]
        # x86 native
        self.builders[(x86_proc.id, False)] = [
            self.i6, self.i7, self.i8, self.i9]
        # x86 virtual
        self.builders[(x86_proc.id, True)] = [
            self.i1, self.i2, self.i3, self.i4, self.i5]

        # amd64 native
        self.builders[(amd_proc.id, False)] = [self.a4, self.a5]
        # amd64 virtual
        self.builders[(amd_proc.id, True)] = [self.a1, self.a2, self.a3]

        # hppa native
        self.builders[(hppa_proc.id, False)] = [self.h5, self.h6, self.h7]
        # hppa virtual
        self.builders[(hppa_proc.id, True)] = [
            self.h1, self.h2, self.h3, self.h4]

        # Ensure all builders are operational.
        for builders in self.builders.values():
            for builder in builders:
                builder.builderok = True
                builder.manual = False

        # Disable the sample data builders.
        getUtility(IBuilderSet)['bob'].builderok = False
        getUtility(IBuilderSet)['frog'].builderok = False


class SingleArchBuildsBase(TestBuildQueueBase):
    """Set up a test environment with builds that target a single
    processor."""
    def setUp(self):
        """Set up some native x86 builds for the test archive."""
        super(SingleArchBuildsBase, self).setUp()
        # The builds will be set up as follows:
        #
        #      gedit, p:  386, v:False e:0:01:00 *** s: 1001
        #    firefox, p:  386, v:False e:0:02:00 *** s: 1002
        #        apg, p:  386, v:False e:0:03:00 *** s: 1003
        #        vim, p:  386, v:False e:0:04:00 *** s: 1004
        #        gcc, p:  386, v:False e:0:05:00 *** s: 1005
        #      bison, p:  386, v:False e:0:06:00 *** s: 1006
        #       flex, p:  386, v:False e:0:07:00 *** s: 1007
        #   postgres, p:  386, v:False e:0:08:00 *** s: 1008
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        # First mark all builds in the sample data as already built.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        sample_data = store.find(Build)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        store.flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="apg", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="vim", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gcc", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="bison", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="flex", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="postgres",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())
        # Set up the builds for test.
        score = 1000
        duration = 0
        for build in self.builds:
            score += 1
            duration += 60
            bq = build.buildqueue_record
            bq.lastscore = score
            bq.estimated_duration = timedelta(seconds=duration)
        # print_build_setup(self.builds)


class TestBuilderData(SingleArchBuildsBase):
    """Test the retrieval of builder related data. The latter is required
    for job dispatch time estimations irrespective of job processor
    architecture and virtualization setting."""
    def test_builder_data(self):
        # Make sure the builder numbers are correct. The builder data will
        # be the same for all of our builds.
        bq = self.builds[0].buildqueue_record
        builder_data = bq._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data
        self.assertEqual(
            builders_in_total, 21, "The total number of builders is wrong.")
        self.assertEqual(
            builders_for_job, 4,
            "[1] The total number of builders that can build the job in "
            "question is wrong.")
        processor_fam = ProcessorFamilySet().getByName('x86')
        x86_proc = processor_fam.processors[0]
        self.assertEqual(
            builder_stats[(x86_proc.id, False)], 4,
            "The number of native x86 builders is wrong")
        self.assertEqual(
            builder_stats[(x86_proc.id, True)], 5,
            "The number of virtual x86 builders is wrong")
        processor_fam = ProcessorFamilySet().getByName('amd64')
        amd_proc = processor_fam.processors[0]
        self.assertEqual(
            builder_stats[(amd_proc.id, False)], 2,
            "The number of native amd64 builders is wrong")
        self.assertEqual(
            builder_stats[(amd_proc.id, True)], 3,
            "The number of virtual amd64 builders is wrong")
        processor_fam = ProcessorFamilySet().getByName('hppa')
        hppa_proc = processor_fam.processors[0]
        self.assertEqual(
            builder_stats[(hppa_proc.id, False)], 3,
            "The number of native hppa builders is wrong")
        self.assertEqual(
            builder_stats[(hppa_proc.id, True)], 4,
            "The number of virtual hppa builders is wrong")
        self.assertEqual(
            builder_stats[(None, False)], 9,
            "The number of *virtual* builders across all processors is wrong")
        self.assertEqual(
            builder_stats[(None, True)], 12,
            "The number of *native* builders across all processors is wrong")
        # Disable the native x86 builders.
        for builder in self.builders[(x86_proc.id, False)]:
            builder.builderok = False
        # Get the builder statistics again.
        builder_data = bq._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data
        # Since all native x86 builders were disabled there are none left
        # to build the job.
        self.assertEqual(
            builders_for_job, 0,
            "[2] The total number of builders that can build the job in "
            "question is wrong.")
        # Re-enable one of them.
        for builder in self.builders[(x86_proc.id, False)]:
            builder.builderok = True
            break
        # Get the builder statistics again.
        builder_data = bq._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data
        # Now there should be one builder available to build the job.
        self.assertEqual(
            builders_for_job, 1,
            "[3] The total number of builders that can build the job in "
            "question is wrong.")
        # Disable the *virtual* x86 builders -- should not make any
        # difference.
        for builder in self.builders[(x86_proc.id, True)]:
            builder.builderok = False
        # Get the builder statistics again.
        builder_data = bq._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data
        # There should still be one builder available to build the job.
        self.assertEqual(
            builders_for_job, 1,
            "[4] The total number of builders that can build the job in "
            "question is wrong.")

    def test_free_builder_counts(self):
        # Make sure the builder numbers are correct. The builder data will
        # be the same for all of our builds.
        processor_fam = ProcessorFamilySet().getByName('x86')
        proc_386 = processor_fam.processors[0]
        build = self.builds[0]
        # The build in question is an x86/native one.
        self.assertEqual(build.processor.id, proc_386.id)
        self.assertEqual(build.is_virtualized, False)
        bq = build.buildqueue_record
        builder_data = bq._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data
        # We have 4 x86 native builders.
        self.assertEqual(
            builder_stats[(proc_386.id, False)], 4,
            "The number of native x86 builders is wrong")
        # Initially all 4 builders are free.
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 4)
        # Once we assign a build to one of them we should see the free
        # builders count drop by one.
        assign_to_builder(self, 'postgres', 1)
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 3)
        # When we assign another build to one of them we should see the free
        # builders count drop by one again.
        assign_to_builder(self, 'gcc', 2)
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 2)
        # Let's use up another builder.
        assign_to_builder(self, 'apg', 3)
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 1)
        # And now for the last one.
        assign_to_builder(self, 'flex', 4)
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 0)
        # If we reset the 'flex' build the builder that was assigned to it
        # will be free again.
        build, bq = find_job(self, 'flex')
        bq.reset()
        free_count = bq._freeBuildersCount(
            build.processor, build.is_virtualized)
        self.assertEqual(free_count, 1)


class TestMinTimeToNextBuilder(SingleArchBuildsBase):
    """Test estimated time-to-builder with builds targetting a single
    processor."""
    def test_min_time_to_next_builder(self):
        """When is the next builder capable of running the job at the head of
        the queue becoming available?"""
        # Test the estimation of the minimum time until a builder becomes
        # available.

        # The builds will be set up as follows:
        #
        #      gedit, p:  386, v:False e:0:01:00 *** s: 1001
        #    firefox, p:  386, v:False e:0:02:00 *** s: 1002
        #        apg, p:  386, v:False e:0:03:00 *** s: 1003
        #        vim, p:  386, v:False e:0:04:00 *** s: 1004
        #        gcc, p:  386, v:False e:0:05:00 *** s: 1005
        #      bison, p:  386, v:False e:0:06:00 *** s: 1006
        #       flex, p:  386, v:False e:0:07:00 *** s: 1007
        #   postgres, p:  386, v:False e:0:08:00 *** s: 1008
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        processor_fam = ProcessorFamilySet().getByName('x86')
        x86_proc = processor_fam.processors[0]
        # This will be the job of interest.
        apg_build, apg_job = find_job(self, 'apg')
        # One of four builders for the 'apg' build is immediately available.
        check_mintime_to_builder(self, apg_job, x86_proc, False, 0)

        # Assign the postgres job to a builder.
        assign_to_builder(self, 'postgres', 1)
        # Now one builder is gone. But there should still be a builder
        # immediately available.
        check_mintime_to_builder(self, apg_job, x86_proc, False, 0)

        assign_to_builder(self, 'flex', 2)
        check_mintime_to_builder(self, apg_job, x86_proc, False, 0)

        assign_to_builder(self, 'bison', 3)
        check_mintime_to_builder(self, apg_job, x86_proc, False, 0)

        assign_to_builder(self, 'gcc', 4)
        # Now that no builder is immediately available, the shortest
        # remaing build time (based on the estimated duration) is returned:
        #   300 seconds 
        # This is equivalent to the 'gcc' job's estimated duration.
        check_mintime_to_builder(self, apg_job, x86_proc, False, 300)

        # Now we pretend that the 'postgres' started 6 minutes ago. Its
        # remaining execution time should be 2 minutes = 120 seconds and
        # it now becomes the job whose builder becomes available next.
        build, bq = find_job(self, 'postgres')
        set_remaining_time_for_running_job(bq, 120)
        check_mintime_to_builder(self, apg_job, x86_proc, False, 120)

        # What happens when jobs overdraw the estimated duration? Let's
        # pretend the 'flex' job started 8 minutes ago.
        build, bq = find_job(self, 'flex')
        set_remaining_time_for_running_job(bq, -60)
        # In such a case we assume that the job will complete within 2
        # minutes, this is a guess that has worked well so far.
        check_mintime_to_builder(self, apg_job, x86_proc, False, 120)

        # If there's a job that will complete within a shorter time then
        # we expect to be given that time frame.
        build, bq = find_job(self, 'postgres')
        set_remaining_time_for_running_job(bq, 30)
        check_mintime_to_builder(self, apg_job, x86_proc, False, 30)

        # Disable the native x86 builders.
        for builder in self.builders[(x86_proc.id, False)]:
            builder.builderok = False

        # No builders capable of running the job at hand are available now,
        # this is indicated by a None value.
        check_mintime_to_builder(self, apg_job, x86_proc, False, None)


class MultiArchBuildsBase(TestBuildQueueBase):
    """Set up a test environment with builds and multiple processors."""
    def setUp(self):
        """Set up some native x86 builds for the test archive."""
        super(MultiArchBuildsBase, self).setUp()
        # The builds will be set up as follows:
        #
        #      gedit, p: hppa, v:False e:0:01:00 *** s: 1001
        #      gedit, p:  386, v:False e:0:02:00 *** s: 1002
        #    firefox, p: hppa, v:False e:0:03:00 *** s: 1003
        #    firefox, p:  386, v:False e:0:04:00 *** s: 1004
        #        apg, p: hppa, v:False e:0:05:00 *** s: 1005
        #        apg, p:  386, v:False e:0:06:00 *** s: 1006
        #        vim, p: hppa, v:False e:0:07:00 *** s: 1007
        #        vim, p:  386, v:False e:0:08:00 *** s: 1008
        #        gcc, p: hppa, v:False e:0:09:00 *** s: 1009
        #        gcc, p:  386, v:False e:0:10:00 *** s: 1010
        #      bison, p: hppa, v:False e:0:11:00 *** s: 1011
        #      bison, p:  386, v:False e:0:12:00 *** s: 1012
        #       flex, p: hppa, v:False e:0:13:00 *** s: 1013
        #       flex, p:  386, v:False e:0:14:00 *** s: 1014
        #   postgres, p: hppa, v:False e:0:15:00 *** s: 1015
        #   postgres, p:  386, v:False e:0:16:00 *** s: 1016
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        # First mark all builds in the sample data as already built.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        sample_data = store.find(Build)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        store.flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="apg", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="vim", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gcc", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="bison", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="flex", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="postgres",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist='any').createMissingBuilds())
        # Set up the builds for test.
        score = 1000
        duration = 0
        for build in self.builds:
            score += getattr(self, 'score_increment', 1)
            score += 1
            duration += 60
            bq = build.buildqueue_record
            bq.lastscore = score
            bq.estimated_duration = timedelta(seconds=duration)
        # print_build_setup(self.builds)


class TestMinTimeToNextBuilderMulti(MultiArchBuildsBase):
    """Test estimated time-to-builder with builds and multiple processors."""
    def test_min_time_to_next_builder(self):
        """When is the next builder capable of running the job at the head of
        the queue becoming available?"""
        processor_fam = ProcessorFamilySet().getByName('hppa')
        hppa_proc = processor_fam.processors[0]

        # One of four builders for the 'apg' build is immediately available.
        apg_build, apg_job = find_job(self, 'apg', 'hppa')
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 0)

        # Assign the postgres job to a builder.
        assign_to_builder(self, 'postgres', 1, 'hppa')
        # Now one builder is gone. But there should still be a builder
        # immediately available.
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 0)

        assign_to_builder(self, 'flex', 2, 'hppa')
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 0)

        assign_to_builder(self, 'bison', 3, 'hppa')
        # Now that no builder is immediately available, the shortest
        # remaing build time (based on the estimated duration) is returned:
        #   660 seconds 
        # This is equivalent to the 'bison' job's estimated duration.
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 660)

        # Now we pretend that the 'postgres' started 13 minutes ago. Its
        # remaining execution time should be 2 minutes = 120 seconds and
        # it now becomes the job whose builder becomes available next.
        build, bq = find_job(self, 'postgres', 'hppa')
        set_remaining_time_for_running_job(bq, 120)
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 120)

        # What happens when jobs overdraw the estimated duration? Let's
        # pretend the 'flex' job started 14 minutes ago.
        build, bq = find_job(self, 'flex', 'hppa')
        set_remaining_time_for_running_job(bq, -60)
        # In such a case we assume that the job will complete within 2
        # minutes, this is a guess that has worked well so far.
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 120)

        # If there's a job that will complete within a shorter time then
        # we expect to be given that time frame.
        build, bq = find_job(self, 'postgres', 'hppa')
        set_remaining_time_for_running_job(bq, 30)
        check_mintime_to_builder(self, apg_job, hppa_proc, False, 30)

        # Disable the native hppa builders.
        for builder in self.builders[(hppa_proc.id, False)]:
            builder.builderok = False

        # No builders capable of running the job at hand are available now,
        # this is indicated by a None value.
        check_mintime_to_builder(self, apg_job, hppa_proc, False, None)

        # Let's assume for the moment that the job at the head of the 'apg'
        # build queue is processor independent. In that case we'd ask for
        # *any* next available builder.
        self.assertTrue(
            bq._freeBuildersCount(None, None) > 0,
            "Builders are immediately available for jobs that don't care "
            "about processor architectures or virtualization")
        check_mintime_to_builder(self, apg_job, None, None, 0)

        # Let's disable all builders.
        for builders in self.builders.itervalues():
            for builder in builders:
                builder.builderok = False

        # There are no builders capable of running even the processor
        # independent jobs now and that this is indicated by a None value.
        check_mintime_to_builder(self, apg_job, None, None, None)

        # Re-enable the native hppa builders.
        for builder in self.builders[(hppa_proc.id, False)]:
            builder.builderok = True

        # The builder that's becoming available next is the one that's
        # running the 'postgres' build.
        check_mintime_to_builder(self, apg_job, None, None, 30)

        # Make sure we'll find an x86 builder as well.
        processor_fam = ProcessorFamilySet().getByName('x86')
        x86_proc = processor_fam.processors[0]
        builder = self.builders[(x86_proc.id, False)][0]
        builder.builderok = True

        # Now this builder is the one that becomes available next (29 minutes
        # remaining build time).
        assign_to_builder(self, 'gcc', 1, '386')
        build, bq = find_job(self, 'gcc', '386')
        set_remaining_time_for_running_job(bq, 29)

        check_mintime_to_builder(self, apg_job, None, None, 29)

        # Make a second, idle x86 builder available.
        builder = self.builders[(x86_proc.id, False)][1]
        builder.builderok = True

        # That builder should be available immediately since it's idle.
        check_mintime_to_builder(self, apg_job, None, None, 0)


class TestJobClasses(TestCaseWithFactory):
    """Tests covering build farm job type classes."""
    layer = LaunchpadZopelessLayer
    def setUp(self):
        """Set up a native x86 build for the test archive."""
        super(TestJobClasses, self).setUp()

        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # First mark all builds in the sample data as already built.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        sample_data = store.find(Build)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        store.flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())

    def test_BuildPackageJob(self):
        """`BuildPackageJob` is one of the job type classes."""
        from lp.soyuz.model.buildpackagejob import BuildPackageJob
        _build, bq = find_job(self, 'gedit')

        # This is a binary package build.
        self.assertEqual(
            bq.job_type, BuildFarmJobType.PACKAGEBUILD,
            "This is a binary package build")

        # The class registered for 'PACKAGEBUILD' is `BuildPackageJob`.
        self.assertEqual(
            specific_job_classes()[BuildFarmJobType.PACKAGEBUILD],
            BuildPackageJob,
            "The class registered for 'PACKAGEBUILD' is `BuildPackageJob`")

        # The 'specific_job' object associated with this `BuildQueue`
        # instance is of type `BuildPackageJob`.
        self.assertTrue(bq.specific_job is not None)
        self.assertEqual(
            bq.specific_job.__class__, BuildPackageJob,
            "The 'specific_job' object associated with this `BuildQueue` "
            "instance is of type `BuildPackageJob`")

    def test_OtherTypeClasses(self):
        """Other job type classes are picked up as well."""
        from zope import component
        from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
        class FakeBranchBuild(BuildFarmJob):
            pass

        _build, bq = find_job(self, 'gedit')
        # First make sure that we don't have a job type class registered for
        # 'BRANCHBUILD' yet.
        self.assertTrue(
            specific_job_classes().get(BuildFarmJobType.BRANCHBUILD) is None)

        # Pretend that our `FakeBranchBuild` class implements the
        # `IBuildFarmJob` interface.
        component.provideUtility(
            FakeBranchBuild, IBuildFarmJob, 'BRANCHBUILD')

        # Now we should see the `FakeBranchBuild` class "registered" in the
        # `specific_job_classes` dictionary under the 'BRANCHBUILD' key.
        self.assertEqual(
            specific_job_classes()[BuildFarmJobType.BRANCHBUILD],
            FakeBranchBuild)


class TestPlatformData(TestCaseWithFactory):
    """Tests covering the processor/virtualized properties."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Set up a native x86 build for the test archive."""
        super(TestPlatformData, self).setUp()

        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # First mark all builds in the sample data as already built.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        sample_data = store.find(Build)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        store.flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa).createMissingBuilds())

    def test_JobPlatformSettings(self):
        """The `BuildQueue` instance shares the processor/virtualized
        properties with the associated `Build`."""
        build, bq = find_job(self, 'gedit')

        # Make sure the 'processor' properties are the same.
        self.assertEqual(
            bq.processor, build.processor,
            "The 'processor' property deviates.")

        # Make sure the 'virtualized' properties are the same.
        self.assertEqual(
            bq.virtualized, build.is_virtualized,
            "The 'virtualized' property deviates.")


class TestMultiArchJobDelayEstimation(MultiArchBuildsBase):
    """Test estimated job delays with various processors."""
    score_increment = 2
    def setUp(self):
        """Set up a fake 'BRANCHBUILD' build farm job class.

        The two platform-independent jobs will have a score of 1017 and 1033
        respectively.

            3,              gedit, p: hppa, v:False e:0:01:00 *** s: 1003
            4,              gedit, p:  386, v:False e:0:02:00 *** s: 1006
            5,            firefox, p: hppa, v:False e:0:03:00 *** s: 1009
            6,            firefox, p:  386, v:False e:0:04:00 *** s: 1012
            7,                apg, p: hppa, v:False e:0:05:00 *** s: 1015
            8,                apg, p:  386, v:False e:0:06:00 *** s: 1018
            9,                vim, p: hppa, v:False e:0:07:00 *** s: 1021
           10,                vim, p:  386, v:False e:0:08:00 *** s: 1024
           11,                gcc, p: hppa, v:False e:0:09:00 *** s: 1027
           12,                gcc, p:  386, v:False e:0:10:00 *** s: 1030
           13,              bison, p: hppa, v:False e:0:11:00 *** s: 1033
           14,              bison, p:  386, v:False e:0:12:00 *** s: 1036
           15,               flex, p: hppa, v:False e:0:13:00 *** s: 1039
           16,               flex, p:  386, v:False e:0:14:00 *** s: 1042
           17,           postgres, p: hppa, v:False e:0:15:00 *** s: 1045
           18,           postgres, p:  386, v:False e:0:16:00 *** s: 1048
           19,  generic-string140, p: None, v:False e:0:00:22 *** s: 1025
           20,  generic-string206, p: None, v:False e:0:03:42 *** s: 1053

         p=processor, v=virtualized, e=estimated_duration, s=score
        """
        super(TestMultiArchJobDelayEstimation, self).setUp()

        job = self.factory.makeSourcePackageRecipeBuildJob(
            virtualized=False, estimated_duration=22)
        job.lastscore = 1025
        self.builds.append(job.specific_job.build)
        job = self.factory.makeSourcePackageRecipeBuildJob(
            virtualized=False, estimated_duration=222)
        job.lastscore = 1053
        self.builds.append(job.specific_job.build)

        # print_build_setup(self.builds)

    def test_job_delay(self):
        processor_fam = ProcessorFamilySet().getByName('hppa')
        hppa_proc = processor_fam.processors[0]

        # One of four builders for the 'flex' build is immediately available.
        flex_build, flex_job = find_job(self, 'flex', 'hppa')
        check_mintime_to_builder(self, flex_job, hppa_proc, False, 0)

        # Obtain the builder statistics pertaining to this job.
        builder_data = flex_job._getBuilderData()
        builders_in_total, builders_for_job, builder_stats = builder_data

        # The delay will be 900 (= 15*60) + 222 seconds, the head job is
        # platform-independent.
        check_delay_for_job(self, flex_job, 1122, (None, False))

        # Assign the postgres job to a builder.
        assign_to_builder(self, 'postgres', 1, 'hppa')
        # The 'postgres' job is not pending any more.  Now only the 222
        # seconds (the estimated duration of the platform-independent job)
        # should be returned.
        check_delay_for_job(self, flex_job, 222, (None, False))

        # How about some estimates for x86 builds?
        processor_fam = ProcessorFamilySet().getByName('x86')
        x86_proc = processor_fam.processors[0]

        _bison_build, bison_job = find_job(self, 'bison', '386')
        check_mintime_to_builder(self, bison_job, x86_proc, False, 0)
        check_delay_for_job(self, bison_job, 1122, (None, False))


