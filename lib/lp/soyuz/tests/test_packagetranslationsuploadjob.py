# Copyright 2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import transaction
from testtools.content import text_content
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.tests import block_on_job
from lp.services.mail.sendmail import format_address_for_person
from lp.services.tarfile_helpers import LaunchpadWriteTarFile
from lp.soyuz.interfaces.packagetranslationsuploadjob import (
    IPackageTranslationsUploadJob,
    IPackageTranslationsUploadJobSource,
    )
from lp.soyuz.model.packagetranslationsuploadjob import (
    PackageTranslationsUploadJob,
    )
from lp.testing import (
    person_logged_in,
    run_script,
    TestCaseWithFactory,
    verifyObject,
    )
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import (
    CeleryJobLayer,
    LaunchpadZopelessLayer,
    )
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
    )


class LocalTestHelper(TestCaseWithFactory):

    def makeJob(self, has_sharing_translation_templates=False,
                sourcepackagerelease=None, tar_content=None):
        requester = self.factory.makePerson()
        if sourcepackagerelease is None:
            distroseries = self.factory.makeDistroSeries()
            sourcepackagename = self.factory.getOrMakeSourcePackageName(
                "foobar")
            self.factory.makeSourcePackage(sourcepackagename=sourcepackagename,
                distroseries=distroseries, publish=True)
            spr = self.factory.makeSourcePackageRelease(
                sourcepackagename=sourcepackagename,
                distroseries=distroseries)
        else:
            spr = sourcepackagerelease
            distroseries = spr.upload_distroseries
            sourcepackagename = spr.sourcepackagename

        libraryfilealias = self.makeTranslationsLFA(tar_content)

        return (spr, getUtility(IPackageTranslationsUploadJobSource).create(
                    distroseries, libraryfilealias,
                    has_sharing_translation_templates, sourcepackagename,
                    requester))

    def makeTranslationsLFA(self, tar_content=None):
        """Create an LibraryFileAlias containing dummy translation data."""
        if tar_content is None:
            tar_content = {
                'source/po/foo.pot': 'Foo template',
                'source/po/eo.po': 'Foo translation',
                }
        tarfile_content = LaunchpadWriteTarFile.files_to_string(
            tar_content)
        return self.factory.makeLibraryFileAlias(content=tarfile_content)


class TestPackageTranslationsUploadJob(LocalTestHelper):

    layer = LaunchpadZopelessLayer

    def test_job_implements_IPackageTranslationsUploadJob(self):
        _, job = self.makeJob()
        self.assertTrue(verifyObject(IPackageTranslationsUploadJob, job))

    def test_job_source_implements_IPackageTranslationsUploadJobSource(self):
        job_source = getUtility(IPackageTranslationsUploadJobSource)
        self.assertTrue(verifyObject(IPackageTranslationsUploadJobSource,
                                     job_source))

    def test_iterReady(self):
        _, job1 = self.makeJob()
        removeSecurityProxy(job1).job._status = JobStatus.COMPLETED
        _, job2 = self.makeJob()
        jobs = list(PackageTranslationsUploadJob.iterReady())
        self.assertEqual(1, len(jobs))

    def test_getErrorRecipients_requester(self):
        _, job = self.makeJob()
        email = format_address_for_person(job.requester)
        self.assertEquals([email], job.getErrorRecipients())
        removeSecurityProxy(job).requester = None
        self.assertEquals([], job.getErrorRecipients())

    def test_run(self):
        _, job = self.makeJob()
        method = FakeMethod()
        removeSecurityProxy(job).attachTranslationFiles = method
        transaction.commit()
        _, job.run()
        self.assertEqual(method.call_count, 1)

    def test_smoke(self):
        tar_content = {
            'source/po/foobar.pot': 'FooBar template',
        }
        spr, job = self.makeJob(tar_content=tar_content)
        transaction.commit()
        out, err, exit_code = run_script(
            "LP_DEBUG_SQL=1 cronscripts/process-job-source.py -vv %s" % (
                IPackageTranslationsUploadJobSource.getName()))

        self.addDetail("stdout", text_content(out))
        self.addDetail("stderr", text_content(err))

        self.assertEqual(0, exit_code)
        translation_import_queue = getUtility(ITranslationImportQueue)
        entries_in_queue = translation_import_queue.getAllEntries(
            target=spr.sourcepackage)

        self.assertEqual(1, entries_in_queue.count())
        # Check if the file in tar_content is queued:
        self.assertTrue("po/foobar.pot", entries_in_queue[0].path)


class TestViaCelery(LocalTestHelper):
    """PackageTranslationsUploadJob runs under Celery."""

    layer = CeleryJobLayer

    def test_run(self):
        self.useFixture(FeatureFixture({
            'jobs.celery.enabled_classes': 'PackageTranslationsUploadJob',
        }))

        spr, job = self.makeJob()
        with block_on_job(self):
            transaction.commit()
        translation_import_queue = getUtility(ITranslationImportQueue)
        entries_in_queue = translation_import_queue.getAllEntries(
            target=spr.sourcepackage).count()
        self.assertEqual(2, entries_in_queue)


class TestAttachTranslationFiles(LocalTestHelper):
    """Tests for attachTranslationFiles."""

    layer = LaunchpadZopelessLayer

    def test_attachTranslationFiles__no_translation_sharing(self):
        # If translation sharing is disabled, attachTranslationFiles() creates
        # a job in the translation import queue.

        spr, job = self.makeJob()

        self.assertFalse(
            removeSecurityProxy(job).has_sharing_translation_templates)

        transaction.commit()
        with dbuser('upload_package_translations_job'):
            job.attachTranslationFiles(True)
        translation_import_queue = getUtility(ITranslationImportQueue)
        entries_in_queue = translation_import_queue.getAllEntries(
            target=spr.sourcepackage).count()
        self.assertEqual(2, entries_in_queue)

    def test_attachTranslationFiles__translation_sharing(self):
        # If translation sharing is enabled, attachTranslationFiles() only
        # attaches templates.

        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.getOrMakeSourcePackageName(
            "foobar")
        self.factory.makeSourcePackage(sourcepackagename=sourcepackagename,
            distroseries=distroseries, publish=True)
        spr = self.factory.makeSourcePackageRelease(
            sourcepackagename=sourcepackagename,
            distroseries=distroseries)

        productseries = self.factory.makeProductSeries()
        sourcepackage = spr.sourcepackage

        self.factory.makePOTemplate(productseries=productseries)
        with person_logged_in(sourcepackage.distroseries.owner):
            sourcepackage.setPackaging(
                productseries, sourcepackage.distroseries.owner)

        spr, job = self.makeJob(has_sharing_translation_templates=True,
                sourcepackagerelease=spr)

        transaction.commit()
        with dbuser('upload_package_translations_job'):
            job.attachTranslationFiles(True)
        translation_import_queue = getUtility(ITranslationImportQueue)
        entries = translation_import_queue.getAllEntries(target=sourcepackage)
        self.assertEqual(1, entries.count())
        self.assertTrue(entries[0].path.endswith('.pot'))
