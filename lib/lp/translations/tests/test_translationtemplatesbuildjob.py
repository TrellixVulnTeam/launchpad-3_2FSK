# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from unittest import TestLoader

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing import LaunchpadZopelessLayer, ZopelessDatabaseLayer

from lp.testing import TestCaseWithFactory
from lp.testing.fakemethod import FakeMethod

from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJob, ISpecificBuildFarmJobClass)
from lp.buildmaster.interfaces.buildfarmjobbehavior import (
    IBuildFarmJobBehavior)
from lp.code.interfaces.branchjob import IBranchJob, IRosettaUploadJobSource
from lp.services.job.model.job import Job
from lp.soyuz.interfaces.buildqueue import IBuildQueueSet
from lp.soyuz.model.buildqueue import BuildQueue
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode)
from lp.translations.interfaces.translationtemplatesbuildjob import (
    ITranslationTemplatesBuildJobSource)
from lp.translations.model.translationtemplatesbuildjob import (
    TranslationTemplatesBuildJob)


def get_job_id(job):
    """Peek inside a `Job` and retrieve its id."""
    return removeSecurityProxy(job).id


class TestTranslationTemplatesBuildJob(TestCaseWithFactory):
    """Test `TranslationTemplatesBuildJob`."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestTranslationTemplatesBuildJob, self).setUp()
        self.jobset = getUtility(ITranslationTemplatesBuildJobSource)
        self.branch = self.factory.makeBranch()
        self.specific_job = self.jobset.create(self.branch)

    def test_new_TranslationTemplatesBuildJob(self):
        # TranslationTemplateBuildJob implements IBuildFarmJob and
        # IBranchJob.
        verifyObject(IBranchJob, self.specific_job)
        verifyObject(IBuildFarmJob, self.specific_job)

        # The class also implements ISpecificBuildFarmJobClass.
        verifyObject(ISpecificBuildFarmJobClass, TranslationTemplatesBuildJob)

        # Each of these jobs knows the branch it will operate on.
        self.assertEqual(self.branch, self.specific_job.branch)

    def test_has_Job(self):
        # Associated with each TranslationTemplateBuildJob is a Job.
        base_job = self.specific_job.job
        self.assertIsInstance(base_job, Job)

        # From a Job, the TranslationTemplatesBuildJobSource can find the
        # TranslationTemplatesBuildJob back for us.
        specific_job_for_base_job = removeSecurityProxy(
            TranslationTemplatesBuildJob.getByJob(base_job))
        self.assertEqual(self.specific_job, specific_job_for_base_job)

    def test_has_BuildQueue(self):
        # There's also a BuildQueue item associated with the job.
        queueset = getUtility(IBuildQueueSet)
        job_id = get_job_id(self.specific_job.job)
        buildqueue = queueset.get(job_id)

        self.assertIsInstance(buildqueue, BuildQueue)
        self.assertEqual(job_id, get_job_id(buildqueue.job))

    def test_getName(self):
        # Each job gets a unique name.
        other_job = self.jobset.create(self.branch)
        self.assertNotEqual(self.specific_job.getName(), other_job.getName())

    def test_getTitle(self):
        other_job = self.jobset.create(self.branch)
        self.assertEqual(
            '%s translation templates build' % self.branch.bzr_identity,
            self.specific_job.getTitle())

    def test_getLogFileName(self):
        # Each job has a unique log file name.
        other_job = self.jobset.create(self.branch)
        self.assertNotEqual(
            self.specific_job.getLogFileName(), other_job.getLogFileName())

    def test_score(self):
        # For now, these jobs always score themselves at 1,000.  In the
        # future however the scoring system is to be revisited.
        self.assertEqual(1000, self.specific_job.score())


class FakeTranslationTemplatesJobSource(TranslationTemplatesBuildJob):
    """Ugly, ugly hack.
    """

    fake_pottery_compatibility = None

    @classmethod
    def _hasPotteryCompatibleSetup(cls, branch):
        if cls.fake_pottery_compatibility is None:
            return TranslationTemplatesBuildJob._hasPotteryCompatibleSetup(
                branch)
        else:
            return cls.fake_pottery_compatibility


class TestTranslationTemplatesBuildJobSource(TestCaseWithFactory):
    """Test `TranslationTemplatesBuildJobSource`."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestTranslationTemplatesBuildJobSource, self).setUp()
        self.jobsource = FakeTranslationTemplatesJobSource
        self.jobsource.fake_pottery_compabitility = None

    def tearDown(self):
        self._fakePotteryCompatibleSetup(compatible=None)
        super(TestTranslationTemplatesBuildJobSource, self).tearDown()

    def _makeTranslationBranch(self, fake_pottery_compatible=None):
        """Create a branch that provides translations for a productseries."""
        if fake_pottery_compatible is None:
            self.useBzrBranches()
            branch, tree = self.create_branch_and_tree()
        else:
            branch = self.factory.makeAnyBranch()
        product = removeSecurityProxy(branch.product)
        trunk = product.getSeries('trunk')
        trunk.branch = branch
        trunk.translations_autoimport_mode = (
            TranslationsBranchImportMode.IMPORT_TEMPLATES)

        self._fakePotteryCompatibleSetup(fake_pottery_compatible)

        # Validate that this produces a translations branch.
        uploadjobsource = getUtility(IRosettaUploadJobSource)
        self.assertFalse(uploadjobsource.findProductSeries(branch).is_empty())
        self.assertTrue(
            uploadjobsource.providesTranslationFiles(branch),
            "Test setup failure: did not set up a translations branch.")

        return branch

    def _fakePotteryCompatibleSetup(self, compatible=True):
        """Mock up branch compatibility check.

        :param compatible: Whether the mock check should say that
            branches have a pottery-compatible setup, or that they
            don't.
        """
        self.jobsource.fake_pottery_compatibility = compatible

    def test_baseline(self):
        utility = getUtility(ITranslationTemplatesBuildJobSource)
        verifyObject(ITranslationTemplatesBuildJobSource, utility)

    def test_generatesTemplates(self):
        # A branch "generates templates" if it is a translation branch
        # for a productseries that imports templates from it; is not
        # private; and has a pottery compatible setup.
        # For convenience we fake the pottery compatibility here.
        branch = self._makeTranslationBranch(fake_pottery_compatible=True)
        self.assertTrue(self.jobsource.generatesTemplates(branch))

    def test_not_pottery_compatible(self):
        # If pottery does not see any files it can work with in the
        # branch, generatesTemplates returns False.
        branch = self._makeTranslationBranch()
        self.assertFalse(self.jobsource.generatesTemplates(branch))
    
    def test_branch_not_used(self):
        # We don't generate templates branches not attached to series.
        branch = self._makeTranslationBranch(fake_pottery_compatible=True)

        trunk = branch.product.getSeries('trunk')
        removeSecurityProxy(trunk).branch = None

        self.assertFalse(self.jobsource.generatesTemplates(branch))

    def test_not_importing_templates(self):
        # We don't generate templates when imports are disabled.
        branch = self._makeTranslationBranch(fake_pottery_compatible=True)

        trunk = branch.product.getSeries('trunk')
        removeSecurityProxy(trunk).translations_autoimport_mode = (
            TranslationsBranchImportMode.NO_IMPORT)

        self.assertFalse(self.jobsource.generatesTemplates(branch))

    def test_private_branch(self):
        # We don't generate templates for private branches.
        branch = self._makeTranslationBranch(fake_pottery_compatible=True)
        removeSecurityProxy(branch).private = True
        self.assertFalse(self.jobsource.generatesTemplates(branch))


class TestTranslationTemplatesBuildBehavior(TestCaseWithFactory):
    """Test `TranslationTemplatesBuildBehavior`."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestTranslationTemplatesBuildBehavior, self).setUp()
        self.jobset = getUtility(ITranslationTemplatesBuildJobSource)
        self.branch = self.factory.makeBranch()
        self.specific_job = self.jobset.create(self.branch)
        self.behavior = IBuildFarmJobBehavior(self.specific_job)

    def test_getChroot(self):
        # _getChroot produces the current chroot for the current Ubuntu
        # release, on the nominated architecture for
        # architecture-independent builds.
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        current_ubuntu = ubuntu.currentseries
        distroarchseries = current_ubuntu.nominatedarchindep

        # Set an arbitrary chroot file.
        fake_chroot_file = getUtility(ILibraryFileAliasSet)[1]
        distroarchseries.addOrUpdateChroot(fake_chroot_file)

        chroot = self.behavior._getChroot()

        self.assertNotEqual(None, chroot)
        self.assertEqual(fake_chroot_file, chroot)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
