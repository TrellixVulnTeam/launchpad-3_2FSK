# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation code for source package builds."""

__metaclass__ = type
__all__ = [
    'SourcePackageRecipeBuild',
    ]

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.launchpad.interfaces.lpstorm import IMasterStore

from storm.locals import Int, Reference, Storm, TimeDelta
from storm.store import Store

from zope.component import getUtility
from zope.interface import classProvides, implements

from lp.buildmaster.model.buildbase import BuildBase
from lp.services.job.model.job import Job
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildJob, ISourcePackageRecipeBuildJobSource,
    ISourcePackageRecipeBuild, ISourcePackageRecipeBuildSource)


class SourcePackageRecipeBuild(BuildBase, Storm):

    __storm_table__ = 'SourcePackageRecipeBuild'

    implements(ISourcePackageRecipeBuild)
    classProvides(ISourcePackageRecipeBuildSource)

    id = Int(primary=True)

    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

    build_duration = TimeDelta(name='build_duration', default=None)

    builder_id = Int(name='builder', allow_none=True)
    builder = Reference(builder_id, 'Builder.id')

    build_log_id = Int(name='build_log', allow_none=True)
    build_log = Reference(build_log_id, 'LibraryFileAlias.id')

    build_state = EnumCol(
        dbName='build_state', notNull=True, schema=BuildStatus)

    date_created = UtcDateTimeCol(notNull=True)
    date_built = UtcDateTimeCol(notNull=False)
    date_first_dispatched = UtcDateTimeCol(notNull=False)

    distroseries_id = Int(name='distroseries', allow_none=True)
    distroseries = Reference(distroseries_id, 'DistroSeries.id')

    sourcepackagename_id = Int(name='sourcepackagename', allow_none=True)
    sourcepackagename = Reference(
        sourcepackagename_id, 'SourcePackageName.id')

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'SourcePackageRecipe.id')

    requester_id = Int(name='requester', allow_none=False)
    requester = Reference(requester_id, 'Person.id')

    def __init__(self, distroseries, sourcepackagename, recipe, requester,
                 archive, date_created=None, date_first_dispatched=None,
                 date_built=None, builder=None,
                 build_state=BuildStatus.NEEDSBUILD, build_log=None,
                 build_duration=None):
        """Construct a SourcePackageRecipeBuild."""
        super(SourcePackageRecipeBuild, self).__init__()
        self.archive = archive
        self.build_duration = build_duration
        self.build_log = build_log
        self.builder = builder
        self.build_state = build_state
        self.date_built = date_built
        self.date_created = date_created
        self.date_first_dispatched = date_first_dispatched
        self.distroseries = distroseries
        self.recipe = recipe
        self.requester = requester
        self.sourcepackagename = sourcepackagename

    @classmethod
    def new(cls, sourcepackage, recipe, requester, archive,
            date_created=None):
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


class SourcePackageRecipeBuildJob(Storm):

    classProvides(ISourcePackageRecipeBuildJobSource)
    implements(ISourcePackageRecipeBuildJob)

    __storm_table__ = 'sourcepackagerecipebuildjob'

    id = Int(primary=True)

    job_id = Int(name='job', allow_none=False)
    job = Reference(job_id, 'Job.id')

    source_package_build_id = Int(name='build', allow_none=False)
    source_package_build = Reference(
        source_package_build_id, 'SourcePackageRecipeBuild.id')

    processor = None
    virtualized = False

    def __init__(self, build, job):
        super(SourcePackageRecipeBuildJob, self).__init__()
        self.build = build
        self.job = job

    def score(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    def getLogFileName(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    def getName(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    def jobStarted(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    def jobReset(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    def jobAborted(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError()

    @classmethod
    def new(cls, build, job):
        """See `ISourcePackageRecipeBuildJobSource`."""
        specific_job = cls(build, job)
        store = IMasterStore(SourcePackageRecipeBuildJob)
        store.add(specific_job)
        return specific_job
