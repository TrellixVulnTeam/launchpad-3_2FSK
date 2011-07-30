# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for merging translations."""

__metaclass__ = type


import transaction
from zope.component import getUtility

from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing.layers import (
    LaunchpadZopelessLayer,
    )
from lp.registry.interfaces.packaging import IPackagingUtil
from lp.registry.model.packagingjob import (
    TranslationTemplateJob,
    TranslationTemplateJobDerived,
    )
from lp.services.job.interfaces.job import (
    IRunnableJob,
    JobStatus,
    )
from lp.testing import (
    EventRecorder,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.translations.interfaces.side import TranslationSide
from lp.translations.interfaces.translationpackagingjob import (
    ITranslationPackagingJobSource,
    )
from lp.translations.model.potemplate import POTemplateSubset
from lp.translations.model.translationpackagingjob import (
    TranslationMergeJob,
    TranslationPackagingJob,
    TranslationSplitJob,
    )
from lp.translations.tests.test_translationsplitter import (
    make_shared_potmsgset,
    )


def make_translation_merge_job(factory, not_ubuntu=False):
    singular = factory.getUniqueString()
    upstream_pofile = factory.makePOFile(side=TranslationSide.UPSTREAM)
    upstream_potmsgset = factory.makePOTMsgSet(
        upstream_pofile.potemplate, singular)
    upstream = factory.makeCurrentTranslationMessage(
        pofile=upstream_pofile, potmsgset=upstream_potmsgset)
    if not_ubuntu:
        distroseries = factory.makeDistroSeries()
    else:
        distroseries = factory.makeUbuntuDistroSeries()
    package_potemplate = factory.makePOTemplate(
        distroseries=distroseries, name=upstream_pofile.potemplate.name)
    package_pofile = factory.makePOFile(
        potemplate=package_potemplate, language=upstream_pofile.language)
    package_potmsgset = factory.makePOTMsgSet(
        package_pofile.potemplate, singular)
    package = factory.makeCurrentTranslationMessage(
        pofile=package_pofile, potmsgset=package_potmsgset,
        translations=upstream.translations)
    productseries = upstream_pofile.potemplate.productseries
    distroseries = package_pofile.potemplate.distroseries
    sourcepackagename = package_pofile.potemplate.sourcepackagename
    return TranslationMergeJob.create(
        productseries=productseries, distroseries=distroseries,
        sourcepackagename=sourcepackagename)


def get_msg_sets(productseries=None, distroseries=None,
               sourcepackagename=None):
    msg_sets = []
    for template in POTemplateSubset(
        productseries=productseries, distroseries=distroseries,
        sourcepackagename=sourcepackagename):
        msg_sets.extend(template.getPOTMsgSets())
    return msg_sets


def get_translations(productseries=None, distroseries=None,
                    sourcepackagename=None):
    msg_sets = get_msg_sets(
        productseries=productseries, distroseries=distroseries,
        sourcepackagename=sourcepackagename)
    translations = set()
    for msg_set in msg_sets:
        translations.update(msg_set.getAllTranslationMessages())
    return translations


def count_translations(job):
    tm = get_translations(productseries=job.productseries)
    tm.update(get_translations(
        sourcepackagename=job.sourcepackagename,
        distroseries=job.distroseries))
    return len(tm)


class JobFinder:

    def __init__(self, productseries, sourcepackage, job_class):
        self.productseries = productseries
        self.sourcepackagename = sourcepackage.sourcepackagename
        self.distroseries = sourcepackage.distroseries
        self.job_type = job_class.class_job_type

    def find(self):
        return list(TranslationTemplateJobDerived.iterReady([
            TranslationTemplateJob.productseries_id == self.productseries.id,
            (TranslationTemplateJob.sourcepackagename_id ==
             self.sourcepackagename.id),
            TranslationTemplateJob.distroseries_id == self.distroseries.id,
            TranslationTemplateJob.job_type == self.job_type,
            ]))


class TestTranslationPackagingJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_interface(self):
        """Should implement ITranslationPackagingJobSource."""
        verifyObject(ITranslationPackagingJobSource, TranslationPackagingJob)


class TestTranslationMergeJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_interface(self):
        """TranslationMergeJob must implement IRunnableJob."""
        job = make_translation_merge_job(self.factory)
        verifyObject(IRunnableJob, job)

    def test_run_merges_msgset(self):
        """Run should merge msgsets."""
        job = make_translation_merge_job(self.factory)
        self.becomeDbUser('rosettaadmin')
        product_msg = get_msg_sets(productseries=job.productseries)
        package_msg = get_msg_sets(
            sourcepackagename=job.sourcepackagename,
            distroseries=job.distroseries)
        self.assertNotEqual(package_msg, product_msg)
        job.run()
        product_msg = get_msg_sets(productseries=job.productseries)
        package_msg = get_msg_sets(
            sourcepackagename=job.sourcepackagename,
            distroseries=job.distroseries)
        self.assertEqual(package_msg, product_msg)

    def test_run_merges_translations(self):
        """Run should merge translations."""
        job = make_translation_merge_job(self.factory)
        self.becomeDbUser('rosettaadmin')
        self.assertEqual(2, count_translations(job))
        job.run()
        self.assertEqual(1, count_translations(job))

    def test_skips_non_ubuntu_distros(self):
        """Run should ignore non-Ubuntu distributions."""
        job = make_translation_merge_job(self.factory, not_ubuntu=True)
        self.becomeDbUser('rosettaadmin')
        self.assertEqual(2, count_translations(job))
        job.run()
        self.assertEqual(2, count_translations(job))

    def test_create_packaging_makes_job(self):
        """Creating a Packaging should make a TranslationMergeJob."""
        productseries = self.factory.makeProductSeries()
        sourcepackage = self.factory.makeSourcePackage()
        finder = JobFinder(productseries, sourcepackage, TranslationMergeJob)
        self.assertEqual([], finder.find())
        sourcepackage.setPackaging(productseries, productseries.owner)
        self.assertNotEqual([], finder.find())
        # Ensure no constraints were violated.
        transaction.commit()

    def test_getNextJobStatus(self):
        """Should find next packaging job."""
        #suppress job creation.
        with EventRecorder() as recorder:
            packaging = self.factory.makePackagingLink()
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))
        TranslationMergeJob.forPackaging(packaging)
        self.assertEqual(
            JobStatus.WAITING,
            TranslationMergeJob.getNextJobStatus(packaging))

    def test_getNextJobStatus_wrong_packaging(self):
        """Jobs on wrong packaging should be ignored."""
        #suppress job creation.
        with EventRecorder() as recorder:
            packaging = self.factory.makePackagingLink()
        self.factory.makePackagingLink(
            productseries=packaging.productseries)
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))
        self.factory.makePackagingLink()
        other_packaging = self.factory.makePackagingLink(
            distroseries=packaging.distroseries)
        other_packaging = self.factory.makePackagingLink(
            distroseries=packaging.distroseries)
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))
        TranslationMergeJob.create(
            sourcepackagename=packaging.sourcepackagename,
            distroseries=packaging.distroseries,
            productseries=self.factory.makeProductSeries())
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))

    def test_getNextJobStatus_wrong_type(self):
        """Only TranslationMergeJobs should result."""
        #suppress job creation.
        with EventRecorder() as recorder:
            packaging = self.factory.makePackagingLink()
        job = TranslationSplitJob.forPackaging(packaging)
        self.assertIs(
            None, TranslationMergeJob.getNextJobStatus(packaging))

    def test_getNextJobStatus_status(self):
        """Only RUNNING and WAITING jobs should influence status."""
        #suppress job creation.
        with EventRecorder() as recorder:
            packaging = self.factory.makePackagingLink()
        job = TranslationMergeJob.forPackaging(packaging)
        job.start()
        self.assertEqual(JobStatus.RUNNING,
            TranslationMergeJob.getNextJobStatus(packaging))
        job.fail()
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))
        job2 = TranslationMergeJob.forPackaging(packaging)
        job2.start()
        job2.complete()
        job3 = TranslationMergeJob.forPackaging(packaging)
        job3.suspend()
        self.assertIs(None, TranslationMergeJob.getNextJobStatus(packaging))

    def test_getNextJobStatus_order(self):
        """Status should order by id."""
        with EventRecorder() as recorder:
            packaging = self.factory.makePackagingLink()
        job = TranslationMergeJob.forPackaging(packaging)
        job.start()
        job2 = TranslationMergeJob.forPackaging(packaging)
        self.assertEqual(JobStatus.RUNNING,
            TranslationMergeJob.getNextJobStatus(packaging))


class TestTranslationSplitJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_run_splits_translations(self):
        upstream_item, ubuntu_item = make_shared_potmsgset(self.factory)
        job = TranslationSplitJob.create(
            upstream_item.potemplate.productseries,
            ubuntu_item.potemplate.distroseries,
            ubuntu_item.potemplate.sourcepackagename,
        )
        self.assertEqual(upstream_item.potmsgset, ubuntu_item.potmsgset)
        job.run()
        self.assertNotEqual(upstream_item.potmsgset, ubuntu_item.potmsgset)

    def test_deletePackaging_makes_job(self):
        """Creating a Packaging should make a TranslationMergeJob."""
        packaging = self.factory.makePackagingLink()
        finder = JobFinder(
            packaging.productseries, packaging.sourcepackage,
            TranslationSplitJob)
        self.assertEqual([], finder.find())
        with person_logged_in(packaging.owner):
            getUtility(IPackagingUtil).deletePackaging(
                packaging.productseries, packaging.sourcepackagename,
                packaging.distroseries)
        (job,) = finder.find()
        self.assertIsInstance(job, TranslationSplitJob)
