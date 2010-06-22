from zope.interface import Attribute, Interface
from zope.schema import Int, Object

from canonical.launchpad import _

from lazr.enum import DBEnumeratedType, DBItem

from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob
from lp.soyuz.interfaces.archive import IArchive


class ArchiveJobType(DBEnumeratedType):
    """Values that IArchiveJob.job_type can take."""

    COPY_ARCHIVE = DBItem(0, """
        Create a copy archive.

        This job creates a copy archive from the current state of
        the archive.
        """)


class IArchiveJob(Interface):
    """A Job related to an Archive."""

    id = Int(
        title=_('DB ID'), required=True, readonly=True,
        description=_("The tracking number for this job."))

    archive = Object(
        title=_('The Archive this job is about.'), schema=IArchive,
        required=True)

    job = Object(
        title=_('The common Job attributes'), schema=IJob, required=True)

    metadata = Attribute('A dict of data about the job.')

    def destroySelf():
        """Destroy this object."""


class IArchiveJobSource(IJobSource):
    """An interface for acquiring IArchiveJobs."""

    def create(archive):
        """Create a new IArchiveJobs for an archive."""


class ICopyArchiveJob(IRunnableJob):
    """A Job to copy archives."""


class ICopyArchiveJobSource(IArchiveJobSource):
    """Interface for acquiring CopyArchiveJobs."""
