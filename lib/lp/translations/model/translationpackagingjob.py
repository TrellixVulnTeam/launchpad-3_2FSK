# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Job for merging translations."""


__metaclass__ = type


__all__ = [
    'TranslationMergeJob',
    'TranslationSplitJob',
    ]

import logging

from lazr.lifecycle.interfaces import (
    IObjectCreatedEvent,
    IObjectDeletedEvent,
    )
import transaction
from zope.interface import (
    classProvides,
    implements,
    )

from lp.services.job.interfaces.job import (
    IRunnableJob,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.translations.interfaces.translationpackagingjob import (
    ITranslationPackagingJobSource,
    )
from lp.registry.model.packagingjob import (
    PackagingJob,
    PackagingJobDerived,
    PackagingJobType,
    )
from lp.translations.translationmerger import (
    TransactionManager,
    TranslationMerger,
    )
from lp.translations.utilities.translationsplitter import TranslationSplitter


class TranslationPackagingJob(PackagingJobDerived, BaseRunnableJob):
    """Iterate through all Translation job types."""

    classProvides(ITranslationPackagingJobSource)

    _translation_packaging_job_types = []

    @staticmethod
    def _register_subclass(cls):
        # Why not a classmethod?  See RegisteredSubclass.__init__.
        PackagingJobDerived._register_subclass(cls)
        job_type = getattr(cls, 'class_job_type', None)
        if job_type is not None:
            cls._translation_packaging_job_types.append(job_type)

    @classmethod
    def forPackaging(cls, packaging):
        """Create a TranslationPackagingJob for a Packaging.

        :param packaging: The `Packaging` to create the job for.
        :return: A `TranslationMergeJob`.
        """
        return cls.create(
            packaging.productseries, packaging.distroseries,
            packaging.sourcepackagename)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        clause = PackagingJob.job_type.is_in(
            cls._translation_packaging_job_types)
        return super(TranslationPackagingJob, cls).iterReady([clause])


class TranslationMergeJob(TranslationPackagingJob):
    """Job for merging translations between a product and sourcepackage."""

    implements(IRunnableJob)

    class_job_type = PackagingJobType.TRANSLATION_MERGE

    create_on_event = IObjectCreatedEvent

    def run(self):
        """See `IRunnableJob`."""
        logger = logging.getLogger()
        if not self.distroseries.distribution.full_functionality:
            logger.warning(
                'Skipping merge for unsupported distroseries "%s".' %
                self.distroseries.displayname)
            return
        logger.info(
            'Merging %s and %s', self.productseries.displayname,
            self.sourcepackage.displayname)
        tm = TransactionManager(transaction.manager, False)
        TranslationMerger.mergePackagingTemplates(
            self.productseries, self.sourcepackagename, self.distroseries, tm)


class TranslationSplitJob(TranslationPackagingJob):
    """Job for merging translations between a product and sourcepackage."""

    implements(IRunnableJob)

    class_job_type = PackagingJobType.TRANSLATION_SPLIT

    create_on_event = IObjectDeletedEvent

    def run(self):
        """See `IRunnableJob`."""
        logger = logging.getLogger()
        logger.info(
            'Splitting %s and %s', self.productseries.displayname,
            self.sourcepackage.displayname)
        TranslationSplitter(self.productseries, self.sourcepackage).split()
