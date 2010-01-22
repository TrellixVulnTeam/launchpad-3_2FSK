# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

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

from storm.locals import Int, Reference, Storm, TimeDelta, Unicode
from storm.store import Store

from zope.component import getUtility
from zope.interface import classProvides, implements

from lp.buildmaster.interfaces.buildfarmjob import BuildFarmJobType
from lp.buildmaster.model.buildbase import BuildBase
from lp.buildmaster.model.packagebuildfarmjob import PackageBuildFarmJob
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.job.model.job import Job
from lp.soyuz.adapters.archivedependencies import (
    default_component_dependency_name,)
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildJob, ISourcePackageRecipeBuildJobSource,
    ISourcePackageRecipeBuild, ISourcePackageRecipeBuildSource)
from lp.soyuz.model.buildqueue import BuildQueue


class SourcePackageRecipeBuild(BuildBase, Storm):
    __storm_table__ = 'SourcePackageRecipeBuild'

    implements(ISourcePackageRecipeBuild)
    classProvides(ISourcePackageRecipeBuildSource)

    build_farm_job_type = BuildFarmJobType.RECIPEBRANCHBUILD

    id = Int(primary=True)

    is_private = False

    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

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
    date_first_dispatched = UtcDateTimeCol(notNull=False)

    distroseries_id = Int(name='distroseries', allow_none=True)
    distroseries = Reference(distroseries_id, 'DistroSeries.id')

    sourcepackagename_id = Int(name='sourcepackagename', allow_none=True)
    sourcepackagename = Reference(
        sourcepackagename_id, 'SourcePackageName.id')

    @property
    def distribution(self):
        """See `IBuildBase`."""
        return self.distroseries.distribution

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

    def __init__(self, distroseries, sourcepackagename, recipe, requester,
                 archive, date_created=None, date_first_dispatched=None,
                 date_built=None, builder=None,
                 build_state=BuildStatus.NEEDSBUILD, build_log=None,
                 build_duration=None):
        """Construct a SourcePackageRecipeBuild."""
        super(SourcePackageRecipeBuild, self).__init__()
        self.archive = archive
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
        self.sourcepackagename = sourcepackagename

    @classmethod
    def new(
        cls, sourcepackage, recipe, requester, archive, date_created=None):
        """See `ISourcePackageRecipeBuildSource`."""
        store = IMasterStore(SourcePackageRecipeBuild)
        if date_created is None:
            date_created = UTC_NOW
        spbuild = cls(
            sourcepackage.distroseries,
            sourcepackage.sourcepackagename,
            recipe,
            requester,
            archive,
            date_created=date_created)
        store.add(spbuild)
        return spbuild

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
        # XXX: wgrant 2010-01-19 bug=507764: Need proper implementation.
        return datetime.timedelta(minutes=2)

    def notify(self, extra_info=None):
        """See `IBuildBase`."""
        # XXX: wgrant 2010-01-20 bug=509893: Implement this.
        return


class SourcePackageRecipeBuildJob(PackageBuildFarmJob, Storm):
    classProvides(ISourcePackageRecipeBuildJobSource)
    implements(ISourcePackageRecipeBuildJob)

    __storm_table__ = 'sourcepackagerecipebuildjob'

    id = Int(primary=True)

    job_id = Int(name='job', allow_none=False)
    job = Reference(job_id, 'Job.id')

    build_id = Int(name='sourcepackage_recipe_build', allow_none=False)
    build = Reference(
        build_id, 'SourcePackageRecipeBuild.id')

    processor = None
    virtualized = True

    def __init__(self, build, job):
        super(SourcePackageRecipeBuildJob, self).__init__()
        self.build = build
        self.job = job

    @classmethod
    def new(cls, build, job):
        """See `ISourcePackageRecipeBuildJobSource`."""
        specific_job = cls(build, job)
        store = IMasterStore(SourcePackageRecipeBuildJob)
        store.add(specific_job)
        return specific_job

    def getTitle(self):
        """See `IBuildFarmJob`."""
        return "%s-%s-%s-recipe-build-job" % (
            self.build.distroseries.displayname,
            self.build.sourcepackagename.name,
            self.build.archive.displayname)
