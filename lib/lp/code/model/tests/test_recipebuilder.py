# Copyright 2010-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test RecipeBuildBehaviour."""

__metaclass__ = type

import shutil
import tempfile

import transaction
from twisted.trial.unittest import TestCase as TrialTestCase
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interactor import BuilderInteractor
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.tests.mock_slaves import (
    MockBuilder,
    OkSlave,
    WaitingSlave,
    )
from lp.buildmaster.tests.test_buildfarmjobbehaviour import (
    TestGetUploadMethodsMixin,
    TestHandleStatusMixin,
    TestVerifySuccessfulBuildMixin,
    )
from lp.code.model.recipebuilder import RecipeBuildBehaviour
from lp.code.model.sourcepackagerecipebuild import SourcePackageRecipeBuild
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.log.logger import BufferLogger
from lp.soyuz.adapters.archivedependencies import (
    get_sources_list_for_building,
    )
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.interfaces.processor import IProcessorSet
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications


class TestRecipeBuilder(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def makeJob(self, recipe_registrant=None, recipe_owner=None,
                archive=None):
        """Create a sample `ISourcePackageRecipeBuild`."""
        spn = self.factory.makeSourcePackageName("apackage")
        distro = self.factory.makeDistribution(name="distro")
        distroseries = self.factory.makeDistroSeries(name="mydistro",
            distribution=distro)
        processor = getUtility(IProcessorSet).getByName('386')
        distroseries.nominatedarchindep = distroseries.newArch(
            'i386', processor, True, self.factory.makePerson())
        sourcepackage = self.factory.makeSourcePackage(spn, distroseries)
        if recipe_registrant is None:
            recipe_registrant = self.factory.makePerson(
                email="requester@ubuntu.com",
                name="joe", displayname="Joe User")
        if recipe_owner is None:
            recipe_owner = recipe_registrant
        somebranch = self.factory.makeBranch(
            owner=recipe_owner, name="pkg",
            product=self.factory.makeProduct("someapp"))
        recipe = self.factory.makeSourcePackageRecipe(
            recipe_registrant, recipe_owner, distroseries, u"recept",
            u"Recipe description", branches=[somebranch])
        spb = self.factory.makeSourcePackageRecipeBuild(
            sourcepackage=sourcepackage, archive=archive,
            recipe=recipe, requester=recipe_owner, distroseries=distroseries)
        job = IBuildFarmJobBehaviour(spb)
        return job

    def test_providesInterface(self):
        # RecipeBuildBehaviour provides IBuildFarmJobBehaviour.
        recipe_builder = RecipeBuildBehaviour(None)
        self.assertProvides(recipe_builder, IBuildFarmJobBehaviour)

    def test_adapts_ISourcePackageRecipeBuild(self):
        # IBuildFarmJobBehaviour adapts a ISourcePackageRecipeBuild
        build = self.factory.makeSourcePackageRecipeBuild()
        job = IBuildFarmJobBehaviour(build)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_verifyBuildRequest_valid(self):
        # VerifyBuildRequest won't raise any exceptions when called with a
        # valid builder set.
        job = self.makeJob()
        builder = MockBuilder("bob-de-bouwer")
        job.setBuilder(builder, OkSlave())
        logger = BufferLogger()
        job.verifyBuildRequest(logger)
        self.assertEquals("", logger.getLogBuffer())

    def test_verifyBuildRequest_non_virtual(self):
        # verifyBuildRequest will raise if a non-virtual builder is proposed.
        job = self.makeJob()
        builder = MockBuilder('non-virtual builder')
        builder.virtualized = False
        job.setBuilder(builder, OkSlave())
        logger = BufferLogger()
        e = self.assertRaises(AssertionError, job.verifyBuildRequest, logger)
        self.assertEqual(
            'Attempt to build virtual item on a non-virtual builder.', str(e))

    def test_verifyBuildRequest_bad_pocket(self):
        # verifyBuildRequest will raise if a bad pocket is proposed.
        build = self.factory.makeSourcePackageRecipeBuild(
            pocket=PackagePublishingPocket.SECURITY)
        job = IBuildFarmJobBehaviour(build)
        job.setBuilder(MockBuilder("bob-de-bouwer"), OkSlave())
        e = self.assertRaises(
            AssertionError, job.verifyBuildRequest, BufferLogger())
        self.assertIn('invalid pocket due to the series status of', str(e))

    def _setBuilderConfig(self):
        """Setup a temporary builder config."""
        self.pushConfig(
            "builddmaster",
            bzr_builder_sources_list="deb http://foo %(series)s main")

    def test_extraBuildArgs(self):
        # _extraBuildArgs will return a sane set of additional arguments
        self._setBuilderConfig()
        job = self.makeJob()
        distroarchseries = job.build.distroseries.architectures[0]
        expected_archives = get_sources_list_for_building(
            job.build, distroarchseries, None)
        expected_archives.append(
            "deb http://foo %s main" % job.build.distroseries.name)
        self.assertEqual({
           'archive_private': False,
           'arch_tag': 'i386',
           'author_email': u'requester@ubuntu.com',
           'suite': u'mydistro',
           'author_name': u'Joe User',
           'archive_purpose': 'PPA',
           'ogrecomponent': 'universe',
           'recipe_text':
               '# bzr-builder format 0.3 deb-version {debupstream}-0~{revno}\n'
               'lp://dev/~joe/someapp/pkg\n',
           'archives': expected_archives,
           'distroseries_name': job.build.distroseries.name,
            }, job._extraBuildArgs(distroarchseries))

    def test_extraBuildArgs_private_archive(self):
        # If the build archive is private, the archive_private flag is
        # True. This tells launchpad-buildd to redact credentials from
        # build logs.
        self._setBuilderConfig()
        archive = self.factory.makeArchive(private=True)
        job = self.makeJob(archive=archive)
        distroarchseries = job.build.distroseries.architectures[0]
        extra_args = job._extraBuildArgs(distroarchseries)
        self.assertEqual(
            True, extra_args['archive_private'])

    def test_extraBuildArgs_team_owner_no_email(self):
        # If the owner of the recipe is a team without a preferred email, the
        # registrant is used.
        self._setBuilderConfig()
        recipe_registrant = self.factory.makePerson(
            name='eric', displayname='Eric the Viking',
            email='eric@vikings.r.us')
        recipe_owner = self.factory.makeTeam(
            name='vikings', members=[recipe_registrant])

        job = self.makeJob(recipe_registrant, recipe_owner)
        distroarchseries = job.build.distroseries.architectures[0]
        extra_args = job._extraBuildArgs(distroarchseries)
        self.assertEqual(
            "Launchpad Package Builder", extra_args['author_name'])
        self.assertEqual("noreply@launchpad.net", extra_args['author_email'])

    def test_extraBuildArgs_team_owner_with_email(self):
        # If the owner of the recipe is a team that has an email set, we use
        # that.
        self._setBuilderConfig()
        recipe_registrant = self.factory.makePerson()
        recipe_owner = self.factory.makeTeam(
            name='vikings', email='everyone@vikings.r.us',
            members=[recipe_registrant])

        job = self.makeJob(recipe_registrant, recipe_owner)
        distroarchseries = job.build.distroseries.architectures[0]
        extra_args = job._extraBuildArgs(distroarchseries)
        self.assertEqual("Vikings", extra_args['author_name'])
        self.assertEqual("everyone@vikings.r.us", extra_args['author_email'])

    def test_extraBuildArgs_owner_deactivated(self):
        # If the owner is deactivated, they have no preferred email.
        self._setBuilderConfig()
        owner = self.factory.makePerson()
        with person_logged_in(owner):
            owner.deactivate(comment='deactivating')
        job = self.makeJob(owner)
        distroarchseries = job.build.distroseries.architectures[0]
        extra_args = job._extraBuildArgs(distroarchseries)
        self.assertEqual(
            "Launchpad Package Builder", extra_args['author_name'])
        self.assertEqual("noreply@launchpad.net", extra_args['author_email'])

    def test_extraBuildArgs_withBadConfigForBzrBuilderPPA(self):
        # Ensure _extraBuildArgs doesn't blow up with a badly formatted
        # bzr_builder_sources_list in the config.
        self.pushConfig(
            "builddmaster",
            bzr_builder_sources_list="deb http://foo %(series) main")
        # (note the missing 's' in %(series)
        job = self.makeJob()
        distroarchseries = job.build.distroseries.architectures[0]
        expected_archives = get_sources_list_for_building(
            job.build, distroarchseries, None)
        logger = BufferLogger()
        self.assertEqual({
           'archive_private': False,
           'arch_tag': 'i386',
           'author_email': u'requester@ubuntu.com',
           'suite': u'mydistro',
           'author_name': u'Joe User',
           'archive_purpose': 'PPA',
           'ogrecomponent': 'universe',
           'recipe_text':
               '# bzr-builder format 0.3 deb-version {debupstream}-0~{revno}\n'
               'lp://dev/~joe/someapp/pkg\n',
           'archives': expected_archives,
           'distroseries_name': job.build.distroseries.name,
            }, job._extraBuildArgs(distroarchseries, logger))
        self.assertIn(
            "Exception processing bzr_builder_sources_list:",
            logger.getLogBuffer())

    def test_extraBuildArgs_withNoBZrBuilderConfigSet(self):
        # Ensure _extraBuildArgs doesn't blow up when
        # bzr_builder_sources_list isn't set.
        job = self.makeJob()
        distroarchseries = job.build.distroseries.architectures[0]
        args = job._extraBuildArgs(distroarchseries)
        expected_archives = get_sources_list_for_building(
            job.build, distroarchseries, None)
        self.assertEqual(args["archives"], expected_archives)

    def test_getByID(self):
        job = self.makeJob()
        transaction.commit()
        self.assertEquals(
            job.build, SourcePackageRecipeBuild.getByID(job.build.id))

    def test_composeBuildRequest(self):
        # Ensure composeBuildRequest is correct.
        job = self.makeJob()
        test_publisher = SoyuzTestPublisher()
        test_publisher.addFakeChroots(job.build.distroseries)
        das = job.build.distroseries.nominatedarchindep
        builder = MockBuilder("bob-de-bouwer")
        builder.processor = das.processor
        job.setBuilder(builder, None)
        self.assertEqual(
            ('sourcepackagerecipe', das, {}, job._extraBuildArgs(das)),
            job.composeBuildRequest(None))


class TestBuildNotifications(TrialTestCase):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestBuildNotifications, self).setUp()
        from lp.testing.factory import LaunchpadObjectFactory
        self.factory = LaunchpadObjectFactory()

    def prepareBehaviour(self, fake_successful_upload=False):
        self.queue_record = (
            self.factory.makeSourcePackageRecipeBuild().queueBuild())
        build = self.queue_record.specific_build
        build.updateStatus(BuildStatus.FULLYBUILT)
        if fake_successful_upload:
            removeSecurityProxy(build).verifySuccessfulUpload = FakeMethod(
                result=True)
            # We overwrite the buildmaster root to use a temp directory.
            tempdir = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, tempdir)
            self.upload_root = tempdir
            tmp_builddmaster_root = """
            [builddmaster]
            root: %s
            """ % self.upload_root
            config.push('tmp_builddmaster_root', tmp_builddmaster_root)
            self.addCleanup(config.pop, 'tmp_builddmaster_root')
        self.queue_record.builder = self.factory.makeBuilder()
        slave = WaitingSlave('BuildStatus.OK')
        return BuilderInteractor.getBuildBehaviour(
            self.queue_record, self.queue_record.builder, slave)

    def assertDeferredNotifyCount(self, status, behaviour, expected_count):
        d = behaviour.handleStatus(self.queue_record, status, {'filemap': {}})

        def cb(result):
            self.assertEqual(expected_count, len(pop_notifications()))

        d.addCallback(cb)
        return d

    def test_handleStatus_PACKAGEFAIL(self):
        """Failing to build the package immediately sends a notification."""
        return self.assertDeferredNotifyCount(
            "PACKAGEFAIL", self.prepareBehaviour(), 1)

    def test_handleStatus_OK(self):
        """Building the source package does _not_ immediately send mail.

        (The archive uploader mail send one later.
        """
        return self.assertDeferredNotifyCount(
            "OK", self.prepareBehaviour(), 0)

    def test_handleStatus_OK_successful_upload(self):
        return self.assertDeferredNotifyCount(
            "OK", self.prepareBehaviour(True), 0)


class MakeSPRecipeBuildMixin:
    """Provide the common makeBuild method returning a queued build."""

    def makeBuild(self):
        build = self.factory.makeSourcePackageRecipeBuild(
            status=BuildStatus.BUILDING)
        build.queueBuild()
        return build

    def makeUnmodifiableBuild(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        build = self.factory.makeSourcePackageRecipeBuild(
            archive=archive, status=BuildStatus.BUILDING)
        build.distro_series.status = SeriesStatus.CURRENT
        build.queueBuild()
        return build


class TestGetUploadMethodsForSPRecipeBuild(
    MakeSPRecipeBuildMixin, TestGetUploadMethodsMixin, TestCaseWithFactory):
    """IPackageBuild.getUpload-related methods work with SPRecipe builds."""


class TestVerifySuccessfulBuildForSPRBuild(
    MakeSPRecipeBuildMixin, TestVerifySuccessfulBuildMixin,
    TestCaseWithFactory):
    """IBuildFarmJobBehaviour.verifySuccessfulBuild works."""


class TestHandleStatusForSPRBuild(
    MakeSPRecipeBuildMixin, TestHandleStatusMixin, TrialTestCase):
    """IPackageBuild.handleStatus works with SPRecipe builds."""
