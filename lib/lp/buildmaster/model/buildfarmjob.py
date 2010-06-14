# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'BuildFarmJob',
    'BuildFarmJobDerived',
    'BuildFarmJobOld',
    'BuildFarmJobOldDerived',
    ]


import hashlib

from lazr.delegates import delegates

import pytz

from storm.locals import Bool, DateTime, Int, Reference, Storm
from storm.store import Store

from zope.component import getUtility
from zope.interface import classProvides, implements
from zope.security.proxy import removeSecurityProxy

from canonical.database.constants import UTC_NOW
from canonical.database.enumcol import DBEnum
from canonical.launchpad.interfaces.lpstorm import IMasterStore
from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR, IStoreSelector, MAIN_STORE)

from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.buildmaster.interfaces.buildfarmjob import (
    BuildFarmJobType, IBuildFarmJob, IBuildFarmJobOld,
    IBuildFarmJobSource)
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet


class BuildFarmJobOld:
    """See `IBuildFarmJobOld`."""
    implements(IBuildFarmJobOld)
    processor = None
    virtualized = None

    def score(self):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def getLogFileName(self):
        """See `IBuildFarmJobOld`."""
        return 'buildlog.txt'

    def getName(self):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def getTitle(self):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def makeJob(self):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def getByJob(self, job):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def jobStarted(self):
        """See `IBuildFarmJobOld`."""
        pass

    def jobReset(self):
        """See `IBuildFarmJobOld`."""
        pass

    def jobAborted(self):
        """See `IBuildFarmJobOld`."""
        pass

    @staticmethod
    def addCandidateSelectionCriteria(processor, virtualized):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    @staticmethod
    def postprocessCandidate(job, logger):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError

    def cleanUp(self):
        """See `IBuildFarmJob`."""
        pass

    def generateSlaveBuildCookie(self):
        """See `IBuildFarmJobOld`."""
        raise NotImplementedError


class BuildFarmJobOldDerived:
    """Setup the delegation and provide some common implementation."""
    delegates(IBuildFarmJobOld, context='build_farm_job')

    def __init__(self, *args, **kwargs):
        """Ensure the instance to which we delegate is set on creation."""
        self._set_build_farm_job()
        super(BuildFarmJobOldDerived, self).__init__(*args, **kwargs)

    def __storm_loaded__(self):
        """Set the attribute for our IBuildFarmJob delegation.

        This is needed here as __init__() is not called when a storm object
        is loaded from the database.
        """
        self._set_build_farm_job()

    def _set_build_farm_job(self):
        """Set the build farm job to which we will delegate.

        Deriving classes must set the build_farm_job attribute for the
        delegation.
        """
        raise NotImplementedError

    @classmethod
    def getByJob(cls, job):
        """See `IBuildFarmJobOld`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        return store.find(cls, cls.job == job).one()

    def generateSlaveBuildCookie(self):
        """See `IBuildFarmJobOld`."""
        buildqueue = getUtility(IBuildQueueSet).getByJob(self.job)

        if buildqueue.processor is None:
            processor = '*'
        else:
            processor = repr(buildqueue.processor.id)

        contents = ';'.join([
            repr(removeSecurityProxy(self.job).id),
            self.job.date_created.isoformat(),
            repr(buildqueue.id),
            buildqueue.job_type.name,
            processor,
            self.getName(),
            ])

        return hashlib.sha1(contents).hexdigest()

    def cleanUp(self):
        """See `IBuildFarmJob`.

        Classes that derive from BuildFarmJobOld need to clean up
        after themselves correctly.
        """
        Store.of(self).remove(self)

    @staticmethod
    def addCandidateSelectionCriteria(processor, virtualized):
        """See `IBuildFarmJobOld`."""
        return ('')

    @staticmethod
    def postprocessCandidate(job, logger):
        """See `IBuildFarmJobOld`."""
        return True


class BuildFarmJob(BuildFarmJobOld, Storm):
    """A base implementation for `IBuildFarmJob` classes."""
    __storm_table__ = 'BuildFarmJob'

    implements(IBuildFarmJob)
    classProvides(IBuildFarmJobSource)

    id = Int(primary=True)

    processor_id = Int(name='processor', allow_none=True)
    processor = Reference(processor_id, 'Processor.id')

    virtualized = Bool()

    date_created = DateTime(
        name='date_created', allow_none=False, tzinfo=pytz.UTC)

    date_started = DateTime(
        name='date_started', allow_none=True, tzinfo=pytz.UTC)

    date_finished = DateTime(
        name='date_finished', allow_none=True, tzinfo=pytz.UTC)

    date_first_dispatched = DateTime(
        name='date_first_dispatched', allow_none=True, tzinfo=pytz.UTC)

    builder_id = Int(name='builder', allow_none=True)
    builder = Reference(builder_id, 'Builder.id')

    status = DBEnum(name='status', allow_none=False, enum=BuildStatus)

    log_id = Int(name='log', allow_none=True)
    log = Reference(log_id, 'LibraryFileAlias.id')

    job_type = DBEnum(
        name='job_type', allow_none=False, enum=BuildFarmJobType)

    def __init__(self, job_type, status=BuildStatus.NEEDSBUILD,
                 processor=None, virtualized=None, date_created=None):
        super(BuildFarmJob, self).__init__()
        self.job_type, self.status, self.processor, self.virtualized = (
            job_type,
            status,
            processor,
            virtualized,
            )
        if date_created is not None:
            self.date_created = date_created

    @classmethod
    def new(cls, job_type, status=BuildStatus.NEEDSBUILD, processor=None,
            virtualized=None, date_created=None):
        """See `IBuildFarmJobSource`."""
        build_farm_job = BuildFarmJob(
            job_type, status, processor, virtualized, date_created)

        store = IMasterStore(BuildFarmJob)
        store.add(build_farm_job)
        return build_farm_job

    @property
    def title(self):
        """See `IBuildFarmJob`."""
        return self.job_type.title

    @property
    def duration(self):
        """See `IBuildFarmJob`."""
        if self.date_started is None or self.date_finished is None:
            return None
        return self.date_finished - self.date_started

    def makeJob(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError

    def jobStarted(self):
        """See `IBuildFarmJob`."""
        self.status = BuildStatus.BUILDING
        # The build started, set the start time if not set already.
        self.date_started = UTC_NOW
        if self.date_first_dispatched is None:
            self.date_first_dispatched = UTC_NOW

    def jobReset(self):
        """See `IBuildFarmJob`."""
        self.status = BuildStatus.NEEDSBUILD
        self.date_started = None

    # The implementation of aborting a job is the same as resetting
    # a job.
    jobAborted = jobReset

    @staticmethod
    def addCandidateSelectionCriteria(processor, virtualized):
        """See `IBuildFarmJob`."""
        return ('')

    @staticmethod
    def postprocessCandidate(job, logger):
        """See `IBuildFarmJob`."""
        return True

    @property
    def buildqueue_record(self):
        """See `IBuildFarmJob`."""
        return None

    @property
    def is_private(self):
        """See `IBuildFarmJob`.

        This base implementation assumes build farm jobs are public, but
        derived implementations can override as required.
        """
        return False

    @property
    def log_url(self):
        """See `IBuildFarmJob`.

        This base implementation of the property always returns None. Derived
        implementations need to override for their specific context.
        """
        return None

    def cleanUp(self):
        """See `IBuildFarmJobOld`.

        XXX 2010-05-04 michael.nelson bug=570939
        This can be removed once IBuildFarmJobOld is no longer used
        and services jobs are linked directly to IBuildFarmJob.
        """
        pass

    @property
    def was_built(self):
        """See `IBuild`"""
        return self.status not in [BuildStatus.NEEDSBUILD,
                                   BuildStatus.BUILDING,
                                   BuildStatus.SUPERSEDED]

    @property
    def specific_job(self):
        """See `IBuild`"""
        return None


class BuildFarmJobDerived:
    implements(IBuildFarmJob)
    delegates(IBuildFarmJob, context='build_farm_job')
