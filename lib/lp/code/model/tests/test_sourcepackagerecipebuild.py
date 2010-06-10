# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for source package builds."""

from __future__ import with_statement

__metaclass__ = type

import datetime
import unittest

from pytz import utc
import transaction
from storm.locals import Store
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.testing.layers import LaunchpadFunctionalLayer

from canonical.launchpad.interfaces.launchpad import NotFoundError
from canonical.launchpad.webapp.authorization import check_permission
from lp.buildmaster.interfaces.buildbase import BuildStatus, IBuildBase
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.tests.test_buildbase import (
    TestGetUploadMethodsMixin, TestHandleStatusMixin)
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildJob, ISourcePackageRecipeBuild,
    ISourcePackageRecipeBuildSource)
from lp.code.model.sourcepackagerecipebuild import SourcePackageRecipeBuild
from lp.soyuz.interfaces.processor import IProcessorFamilySet
from lp.soyuz.model.processor import ProcessorFamily
from lp.testing import ANONYMOUS, login, person_logged_in, TestCaseWithFactory


class TestSourcePackageRecipeBuild(TestCaseWithFactory):
    """Test the source package build object."""

    layer = LaunchpadFunctionalLayer

    def makeSourcePackageRecipeBuild(self):
        """Create a `SourcePackageRecipeBuild` for testing."""
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        distroseries_i386 = distroseries.newArch(
            'i386', ProcessorFamily.get(1), False, person,
            supports_virtualized=True)
        distroseries.nominatedarchindep = distroseries_i386

        return getUtility(ISourcePackageRecipeBuildSource).new(
            distroseries=distroseries,
            recipe=self.factory.makeSourcePackageRecipe(
                distroseries=distroseries),
            archive=self.factory.makeArchive(),
            requester=person)

    def test_providesInterfaces(self):
        # SourcePackageRecipeBuild provides IBuildBase and
        # ISourcePackageRecipeBuild.
        spb = self.makeSourcePackageRecipeBuild()
        self.assertProvides(spb, IBuildBase)
        self.assertProvides(spb, ISourcePackageRecipeBuild)

    def test_saves_record(self):
        # A source package recipe build can be stored in the database
        spb = self.makeSourcePackageRecipeBuild()
        transaction.commit()
        self.assertProvides(spb, ISourcePackageRecipeBuild)

    def test_makeJob(self):
        # A build farm job can be obtained from a SourcePackageRecipeBuild
        spb = self.makeSourcePackageRecipeBuild()
        job = spb.makeJob()
        self.assertProvides(job, ISourcePackageRecipeBuildJob)

    def test_queueBuild(self):
        spb = self.makeSourcePackageRecipeBuild()
        bq = spb.queueBuild(spb)

        self.assertProvides(bq, IBuildQueue)
        self.assertProvides(bq.specific_job, ISourcePackageRecipeBuildJob)
        self.assertEqual(True, bq.virtualized)

        # The processor for SourcePackageRecipeBuilds should not be None.
        # They do require specific environments.
        self.assertNotEqual(None, bq.processor)
        self.assertEqual(
            spb.distroseries.nominatedarchindep.default_processor,
            bq.processor)
        self.assertEqual(bq, spb.buildqueue_record)

    def test_title(self):
        # A recipe build's title currently consists of the base
        # branch's unique name.
        spb = self.makeSourcePackageRecipeBuild()
        title = "%s recipe build" % spb.recipe.base_branch.unique_name
        self.assertEqual(spb.title, title)

    def test_getTitle(self):
        # A recipe build job's title is the same as its build's title.
        spb = self.makeSourcePackageRecipeBuild()
        job = spb.makeJob()
        self.assertEqual(job.getTitle(), spb.title)

    def test_distribution(self):
        # A source package recipe build has a distribution derived from
        # its series.
        spb = self.makeSourcePackageRecipeBuild()
        self.assertEqual(spb.distroseries.distribution, spb.distribution)

    def test_is_private(self):
        # A source package recipe build is currently always public.
        spb = self.makeSourcePackageRecipeBuild()
        self.assertEqual(False, spb.is_private)

    def test_view_private_branch(self):
        """Recipebuilds with private branches are restricted."""
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(owner=owner, private=True)
        with person_logged_in(owner):
            recipe = self.factory.makeSourcePackageRecipe(branches=[branch])
            build = self.factory.makeSourcePackageRecipeBuild(recipe=recipe)
            self.assertTrue(check_permission('launchpad.View', build))
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission('launchpad.View', build))
        login(ANONYMOUS)
        self.assertFalse(check_permission('launchpad.View', build))

    def test_view_private_archive(self):
        """Recipebuilds with private branches are restricted."""
        owner = self.factory.makePerson()
        archive = self.factory.makeArchive(owner=owner, private=True)
        build = self.factory.makeSourcePackageRecipeBuild(archive=archive)
        with person_logged_in(owner):
            self.assertTrue(check_permission('launchpad.View', build))
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(check_permission('launchpad.View', build))
        login(ANONYMOUS)
        self.assertFalse(check_permission('launchpad.View', build))

    def test_estimateDuration(self):
        # If there are no successful builds, estimate 10 minutes.
        spb = self.makeSourcePackageRecipeBuild()
        self.assertEqual(
            datetime.timedelta(minutes=10), spb.estimateDuration())
        for minutes in [20, 5, 1]:
            build = removeSecurityProxy(
                self.factory.makeSourcePackageRecipeBuild(recipe=spb.recipe))
            build.buildduration = datetime.timedelta(minutes=minutes)
        self.assertEqual(
            datetime.timedelta(minutes=5), spb.estimateDuration())


    def test_datestarted(self):
        """Datestarted is taken from job if not specified in the build.

        Specifying datestarted in the build requires datebuilt and
        buildduration to be specified.
        """
        spb = self.makeSourcePackageRecipeBuild()
        self.assertIs(None, spb.datestarted)
        job = self.factory.makeSourcePackageRecipeBuildJob(
            recipe_build=spb).job
        job.start()
        self.assertEqual(job.date_started, spb.datestarted)
        now = datetime.datetime.now(utc)
        removeSecurityProxy(spb).datebuilt = now
        self.assertEqual(job.date_started, spb.datestarted)
        duration = datetime.timedelta(minutes=1)
        removeSecurityProxy(spb).buildduration = duration
        self.assertEqual(now - duration, spb.datestarted)

    def test_getFileByName(self):
        """getFileByName returns the logs when requested by name."""
        spb = self.factory.makeSourcePackageRecipeBuild()
        removeSecurityProxy(spb).buildlog = (
            self.factory.makeLibraryFileAlias(filename='buildlog.txt.gz'))
        self.assertEqual(spb.buildlog, spb.getFileByName('buildlog.txt.gz'))
        self.assertRaises(NotFoundError, spb.getFileByName, 'foo')
        removeSecurityProxy(spb).buildlog = (
            self.factory.makeLibraryFileAlias(filename='foo'))
        self.assertEqual(spb.buildlog, spb.getFileByName('foo'))
        self.assertRaises(NotFoundError, spb.getFileByName, 'buildlog.txt.gz')
        removeSecurityProxy(spb).upload_log = (
            self.factory.makeLibraryFileAlias(filename='upload.txt.gz'))
        self.assertEqual(spb.upload_log, spb.getFileByName('upload.txt.gz'))

    def test_binary_builds(self):
        """The binary_builds property should be populated automatically."""
        spb = self.factory.makeSourcePackageRecipeBuild()
        spr = self.factory.makeSourcePackageRelease(
            source_package_recipe_build=spb)
        self.assertEqual([], list(spb.binary_builds))
        binary = self.factory.makeBinaryPackageBuild(spr)
        self.factory.makeBinaryPackageBuild()
        Store.of(binary).flush()
        self.assertEqual([binary], list(spb.binary_builds))

    def test_getRecentBuilds(self):
        """Recent builds match the same person, series and receipe.

        Builds do not match if they are older than 24 hours, or have a
        different requester, series or recipe.
        """
        requester = self.factory.makePerson()
        recipe = self.factory.makeSourcePackageRecipe()
        series = self.factory.makeDistroSeries()
        now = self.factory.getUniqueDate()
        build = self.factory.makeSourcePackageRecipeBuild(recipe=recipe,
            requester=requester)
        self.factory.makeSourcePackageRecipeBuild(
            recipe=recipe, distroseries=series)
        self.factory.makeSourcePackageRecipeBuild(
            requester=requester, distroseries=series)
        def get_recent():
            Store.of(build).flush()
            return SourcePackageRecipeBuild.getRecentBuilds(
                requester, recipe, series, _now=now)
        self.assertContentEqual([], get_recent())
        yesterday = now - datetime.timedelta(days=1)
        recent_build = self.factory.makeSourcePackageRecipeBuild(
            recipe=recipe, distroseries=series, requester=requester,
            date_created=yesterday)
        self.assertContentEqual([], get_recent())
        a_second = datetime.timedelta(seconds=1)
        removeSecurityProxy(recent_build).datecreated += a_second
        self.assertContentEqual([recent_build], get_recent())

class MakeSPRecipeBuildMixin:
    """Provide the common makeBuild method returning a queued build."""

    def makeBuild(self):
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries()
        processor_fam = getUtility(IProcessorFamilySet).getByName('x86')
        distroseries_i386 = distroseries.newArch(
            'i386', processor_fam, False, person,
            supports_virtualized=True)
        distroseries.nominatedarchindep = distroseries_i386
        build = self.factory.makeSourcePackageRecipeBuild(
            distroseries=distroseries,
            status=BuildStatus.FULLYBUILT)
        build.queueBuild(build)
        return build


class TestGetUploadMethodsForSPRecipeBuild(
    MakeSPRecipeBuildMixin, TestGetUploadMethodsMixin, TestCaseWithFactory):
    """IBuildBase.getUpload-related methods work with SPRecipe builds."""


class TestHandleStatusForSPRBuild(
    MakeSPRecipeBuildMixin, TestHandleStatusMixin, TestCaseWithFactory):
    """IBuildBase.handleStatus works with SPRecipe builds."""


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
