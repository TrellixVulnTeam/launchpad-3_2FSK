# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'GitJob',
    'GitJobType',
    'GitRefScanJob',
    'ReclaimGitRepositorySpaceJob',
    ]

from lazr.delegates import delegates
from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )
from storm.exceptions import LostObjectError
from storm.locals import (
    Int,
    JSON,
    Reference,
    SQL,
    Store,
    )
from zope.component import getUtility
from zope.interface import (
    classProvides,
    implements,
    )
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.code.interfaces.githosting import IGitHostingClient
from lp.code.interfaces.gitjob import (
    IGitJob,
    IGitRefScanJob,
    IGitRefScanJobSource,
    IReclaimGitRepositorySpaceJob,
    IReclaimGitRepositorySpaceJobSource,
    )
from lp.services.config import config
from lp.services.database.enumcol import EnumCol
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.locking import (
    AdvisoryLockHeld,
    LockType,
    try_advisory_lock,
    )
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.services.mail.sendmail import format_address_for_person
from lp.services.scripts import log


class GitJobType(DBEnumeratedType):
    """Values that `IGitJob.job_type` can take."""

    REF_SCAN = DBItem(0, """
        Ref scan

        This job scans a repository for its current list of references.
        """)

    RECLAIM_REPOSITORY_SPACE = DBItem(1, """
        Reclaim repository space

        This job removes a repository that has been deleted from the
        database from storage.
        """)


class GitJob(StormBase):
    """See `IGitJob`."""

    __storm_table__ = 'GitJob'

    implements(IGitJob)

    job_id = Int(name='job', primary=True, allow_none=False)
    job = Reference(job_id, 'Job.id')

    repository_id = Int(name='repository', allow_none=True)
    repository = Reference(repository_id, 'GitRepository.id')

    job_type = EnumCol(enum=GitJobType, notNull=True)

    metadata = JSON('json_data')

    def __init__(self, repository, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param repository: The database repository this job relates to.
        :param job_type: The `GitJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super(GitJob, self).__init__()
        self.job = Job(**job_args)
        self.repository = repository
        self.job_type = job_type
        self.metadata = metadata
        if repository is not None:
            self.metadata["repository_name"] = repository.unique_name

    def makeDerived(self):
        return GitJobDerived.makeSubclass(self)


class GitJobDerived(BaseRunnableJob):

    __metaclass__ = EnumeratedSubclass

    delegates(IGitJob)

    def __init__(self, git_job):
        self.context = git_job
        self._cached_repository_name = self.metadata["repository_name"]

    def __repr__(self):
        """Returns an informative representation of the job."""
        return "<%s for %s>" % (
            self.__class__.__name__, self._cached_repository_name)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `GitJob` with the specified id, as the current
            `GitJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        git_job = IStore(GitJob).get(GitJob, job_id)
        if git_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s" %
                (job_id, cls.class_job_type.title))
        return cls(git_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IMasterStore(GitJob).find(
            GitJob,
            GitJob.job_type == cls.class_job_type,
            GitJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super(GitJobDerived, self).getOopsVars()
        oops_vars.extend([
            ('git_job_id', self.context.job.id),
            ('git_job_type', self.context.job_type.title),
            ])
        if self.context.repository is not None:
            oops_vars.append(('git_repository_id', self.context.repository.id))
        if "repository_name" in self.metadata:
            oops_vars.append(
                ('git_repository_name', self.metadata["repository_name"]))
        return oops_vars

    def getErrorRecipients(self):
        if self.requester is None:
            return []
        return [format_address_for_person(self.requester)]


class GitRefScanJob(GitJobDerived):
    """A Job that scans a Git repository for its current list of references."""

    implements(IGitRefScanJob)

    classProvides(IGitRefScanJobSource)
    class_job_type = GitJobType.REF_SCAN

    max_retries = 5

    retry_error_types = (AdvisoryLockHeld,)

    config = config.IGitRefScanJobSource

    @classmethod
    def create(cls, repository):
        """See `IGitRefScanJobSource`."""
        git_job = GitJob(repository, cls.class_job_type, {})
        job = cls(git_job)
        job.celeryRunOnCommit()
        return job

    def run(self):
        """See `IGitRefScanJob`."""
        try:
            with try_advisory_lock(
                    LockType.GIT_REF_SCAN, self.repository.id,
                    Store.of(self.repository)):
                hosting_path = self.repository.getInternalPath()
                refs_to_upsert, refs_to_remove = (
                    self.repository.planRefChanges(hosting_path, logger=log))
                self.repository.fetchRefCommits(
                    hosting_path, refs_to_upsert, logger=log)
                self.repository.synchroniseRefs(
                    refs_to_upsert, refs_to_remove, logger=log)
                props = getUtility(IGitHostingClient).getProperties(
                    hosting_path)
                # We don't want ref canonicalisation, nor do we want to send
                # this change back to the hosting service.
                removeSecurityProxy(self.repository)._default_branch = (
                    props["default_branch"])
        except LostObjectError:
            log.info(
                "Skipping repository %s because it has been deleted." %
                self._cached_repository_name)


class ReclaimGitRepositorySpaceJob(GitJobDerived):
    """A Job that deletes a repository from storage after it has been
    deleted from the database."""

    implements(IReclaimGitRepositorySpaceJob)

    classProvides(IReclaimGitRepositorySpaceJobSource)
    class_job_type = GitJobType.RECLAIM_REPOSITORY_SPACE

    config = config.IReclaimGitRepositorySpaceJobSource

    @classmethod
    def create(cls, repository_name, repository_path):
        "See `IReclaimGitRepositorySpaceJobSource`."""
        metadata = {
            "repository_name": repository_name,
            "repository_path": repository_path,
            }
        # The GitJob has a repository of None, as there is no repository
        # left in the database to refer to.
        start = SQL("CURRENT_TIMESTAMP AT TIME ZONE 'UTC' + '7 days'")
        git_job = GitJob(
            None, cls.class_job_type, metadata, scheduled_start=start)
        job = cls(git_job)
        job.celeryRunOnCommit()
        return job

    @property
    def repository_path(self):
        return self.metadata["repository_path"]

    def run(self):
        getUtility(IGitHostingClient).delete(self.repository_path, logger=log)
