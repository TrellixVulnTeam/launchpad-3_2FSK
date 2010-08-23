import unittest

from canonical.testing import DatabaseFunctionalLayer
from lp.soyuz.interfaces.archivejob import ArchiveJobType
from lp.soyuz.model.archivejob import (
    ArchiveJob,
    ArchiveJobDerived,
    )
from lp.testing import TestCaseWithFactory


class ArchiveJobTestCase(TestCaseWithFactory):
    """Test case for basic ArchiveJob gubbins."""

    layer = DatabaseFunctionalLayer

    def test_instantiate(self):
        # ArchiveJob.__init__() instantiates a ArchiveJob instance.
        archive = self.factory.makeArchive()

        metadata = ('some', 'arbitrary', 'metadata')
        archive_job = ArchiveJob(
            archive, ArchiveJobType.COPY_ARCHIVE, metadata)

        self.assertEqual(archive, archive_job.archive)
        self.assertEqual(ArchiveJobType.COPY_ARCHIVE, archive_job.job_type)

        # When we actually access the ArchiveJob's metadata it gets
        # deserialized from JSON, so the representation returned by
        # archive_job.metadata will be different from what we originally
        # passed in.
        metadata_expected = [u'some', u'arbitrary', u'metadata']
        self.assertEqual(metadata_expected, archive_job.metadata)


class ArchiveJobDerivedTestCase(TestCaseWithFactory):
    """Test case for the ArchiveJobDerived class."""

    layer = DatabaseFunctionalLayer

    def test_create_explodes(self):
        # ArchiveJobDerived.create() will blow up because it needs to be
        # subclassed to work properly.
        archive = self.factory.makeArchive()
        self.assertRaises(
            AttributeError, ArchiveJobDerived.create, archive)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
