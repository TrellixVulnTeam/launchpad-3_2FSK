# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=F0401,E1002

"""Implementation code for source package builds."""

__metaclass__ = type
__all__ = [
    'SourcePackageRecipeBuild',
    ]

import datetime

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import DBEnum
from canonical.launchpad.interfaces.lpstorm import IMasterStore
from canonical.launchpad.interfaces.launchpad import NotFoundError

from storm.locals import Int, Reference, Storm, TimeDelta, Unicode
from storm.store import Store

from zope.component import getUtility
from zope.interface import classProvides, implements

from lp.buildmaster.interfaces.buildbase import BuildStatus, IBuildBase
from lp.buildmaster.interfaces.buildfarmjob import BuildFarmJobType
from lp.buildmaster.model.buildbase import BuildBase
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.model.buildfarmjob import BuildFarmJobOldDerived
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildJob, ISourcePackageRecipeBuildJobSource,
    ISourcePackageRecipeBuild, ISourcePackageRecipeBuildSource)
from lp.code.mail.sourcepackagerecipebuild import (
    SourcePackageRecipeBuildMailer)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.job.model.job import Job
from lp.soyuz.adapters.archivedependencies import (
    default_component_dependency_name,)
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.buildfarmbuildjob import BuildFarmBuildJob
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease


class SourcePackageRecipeBuild(BuildBase, Storm):
    __storm_table__ = 'SourcePackageRecipeBuild'

    policy_name = 'recipe'

    implements(IBuildBase, ISourcePackageRecipeBuild)
    classProvides(ISourcePackageRecipeBuildSource)

    build_farm_job_type = BuildFarmJobType.RECIPEBRANCHBUILD

    id = Int(primary=True)

    is_private = False

    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

    @property
    def binary_builds(self):
        """See `ISourcePackageRecipeBuild`."""
        return Store.of(self).find(BinaryPackageBuild,
            BinaryPackageBuild.source_package_release==
            SourcePackageRelease.id,
            SourcePackageRelease.source_package_recipe_build==self.id)

    buildduration = TimeDelta(name='build_duration', default=None)

    builder_id = Int(name='builder', allow_none=True)
    builder = Reference(builder_id, 'Builder.id')

    buildlog_id = Int(name='build_log', allow_none=True)
    buildlog = Reference(buildlog_id, 'LibraryFileAlias.id')

    buildstate = DBEnum(enum=BuildStatus, name='build_state')
    dependencies = Unicode(allow_none=True)

    upload_log_id = Int(name='upload_log', allow_none=True)
    upload_log = Reference(upload_log_id, 'LibraryFileAlias.id')

    @property
    def current_component(self):
        return getUtility(IComponentSet)[default_component_dependency_name]

    datecreated = UtcDateTimeCol(notNull=True, dbName='date_created')
    datebuilt = UtcDateTimeCol(notNull=False, dbName='date_built')

    # See `IBuildBase` - the following attributes are aliased
    # to allow a shared implementation of the handleStatus methods
    # until IBuildBase is removed.
    status = buildstate
    date_finished = datebuilt
    log = buildlog

    @property
    def datestarted(self):
        """See `IBuild`."""
        # datestarted is not stored on Build.  It can be calculated from
        # self.datebuilt and self.buildduration, if both are set.  This does
        # not happen until the build is complete.
        #
        # Before the build is complete, there will be a buildqueue_record.
        # If buildqueue_record is set, buildqueue_record.job.date_started can
        # be used.  Otherwise, None is returned.
        if None not in (self.datebuilt, self.buildduration):
            return self.datebuilt - self.buildduration
        queue_record = self.buildqueue_record
        if queue_record is None:
            return None
        return queue_record.job.date_started

    date_first_dispatched = UtcDateTimeCol(notNull=False)

    distroseries_id = Int(name='distroseries', allow_none=True)
    distroseries = Reference(distroseries_id, 'DistroSeries.id')
    distro_series = distroseries

    @property
    def distribution(self):
        """See `IBuildBase`."""
        return self.distroseries.distribution

    is_virtualized = True

    pocket = DBEnum(enum=PackagePublishingPocket)

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'SourcePackageRecipe.id')

    requester_id = Int(name='requester', allow_none=False)
    requester = Reference(requester_id, 'Person.id')

    @property
    def buildqueue_record(self):
        """See `IBuildBase`."""
        store = Store.of(self)
        results = store.find(
            BuildQueue,
            SourcePackageRecipeBuildJob.job == BuildQueue.jobID,
            SourcePackageRecipeBuildJob.build == self.id)
        return results.one()

    @property
    def source_package_release(self):
        """See `ISourcePackageRecipeBuild`."""
        return Store.of(self).find(
            SourcePackageRelease, source_package_recipe_build=self).one()

    @property
    def title(self):
        return '%s recipe build' % self.recipe.base_branch.unique_name

    def __init__(self, distroseries, recipe, requester,
                 archive, pocket, date_created=None,
                 date_first_dispatched=None, date_built=None, builder=None,
                 build_state=BuildStatus.NEEDSBUILD, build_log=None,
                 build_duration=None):
        """Construct a SourcePackageRecipeBuild."""
        super(SourcePackageRecipeBuild, self).__init__()
        self.archive = archive
        self.pocket = pocket
        self.buildduration = build_duration
        self.buildlog = build_log
        self.builder = builder
        self.buildstate = build_state
        self.datebuilt = date_built
        self.datecreated = date_created
        self.date_first_dispatched = date_first_dispatched
        self.distroseries = distroseries
        self.recipe = recipe
        self.requester = requester

    @classmethod
    def new(cls, distroseries, recipe, requester, archive, pocket=None,
            date_created=None):
        """See `ISourcePackageRecipeBuildSource`."""
        store = IMasterStore(SourcePackageRecipeBuild)
        if pocket is None:
            pocket = PackagePublishingPocket.RELEASE
        if date_created is None:
            date_created = UTC_NOW
        spbuild = cls(
            distroseries,
            recipe,
            requester,
            archive,
            pocket,
            date_created=date_created)
        store.add(spbuild)
        return spbuild

    def destroySelf(self):
        store = Store.of(self)
        job = self.buildqueue_record.job
        store.remove(self.buildqueue_record)
        store.find(
            SourcePackageRecipeBuildJob,
            SourcePackageRecipeBuildJob.build == self.id).remove()
        store.remove(job)
        store.remove(self)

    @classmethod
    def getById(cls, build_id):
        """See `ISourcePackageRecipeBuildSource`."""
        store = IMasterStore(SourcePackageRecipeBuild)
        return store.find(cls, cls.id == build_id).one()

    def makeJob(self):
        """See `ISourcePackageRecipeBuildJob`."""
        store = Store.of(self)
        job = Job()
        store.add(job)
        specific_job = getUtility(
            ISourcePackageRecipeBuildJobSource).new(self, job)
        return specific_job

    def estimateDuration(self):
        """See `IBuildBase`."""
        median = self.recipe.getMedianBuildDuration()
        if median is not None:
            return median
        return datetime.timedelta(minutes=10)

    def verifySuccessfulUpload(self):
        return self.source_package_release is not None

    def notify(self, extra_info=None):
        """See `IBuildBase`."""
        mailer = SourcePackageRecipeBuildMailer.forStatus(self)
        mailer.sendAll()

    def getFileByName(self, filename):
        """See `ISourcePackageRecipeBuild`."""
        files = dict((lfa.filename, lfa)
                     for lfa in [self.buildlog, self.upload_log]
                     if lfa is not None)
        try:
            return files[filename]
        except KeyError:
            raise NotFoundError(filename)

    @staticmethod
    def _handleStatus_OK(build, librarian, slave_status, logger):
        """See `IBuildBase`."""
        BuildBase._handleStatus_OK(build, librarian, slave_status, logger)
        # base implementation doesn't notify on success.
        if build.status == BuildStatus.FULLYBUILT:
            build.notify()

class SourcePackageRecipeBuildJob(BuildFarmJobOldDerived, Storm):
    classProvides(ISourcePackageRecipeBuildJobSource)
    implements(ISourcePackageRecipeBuildJob)

    __storm_table__ = 'sourcepackagerecipebuildjob'

    id = Int(primary=True)

    job_id = Int(name='job', allow_none=False)
    job = Reference(job_id, 'Job.id')

    build_id = Int(name='sourcepackage_recipe_build', allow_none=False)
    build = Reference(
        build_id, 'SourcePackageRecipeBuild.id')

    @property
    def processor(self):
        return self.build.distroseries.nominatedarchindep.default_processor

    @property
    def virtualized(self):
        """See `IBuildFarmJob`."""
        return self.build.is_virtualized

    def __init__(self, build, job):
        self.build = build
        self.job = job
        super(SourcePackageRecipeBuildJob, self).__init__()

    def _set_build_farm_job(self):
        """Setup the IBuildFarmJob delegate.

        We override this to provide a delegate specific to package builds."""
        self.build_farm_job = BuildFarmBuildJob(self.build)

    @classmethod
    def new(cls, build, job):
        """See `ISourcePackageRecipeBuildJobSource`."""
        specific_job = cls(build, job)
        store = IMasterStore(cls)
        store.add(specific_job)
        return specific_job

    def getName(self):
        return "%s-%s" % (self.id, self.build_id)
