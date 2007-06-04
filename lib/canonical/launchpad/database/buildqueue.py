# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'BuildQueue',
    'BuildQueueSet'
    ]

from datetime import datetime
import pytz

from zope.interface import implements

from sqlobject import (
    StringCol, ForeignKey, BoolCol, IntCol, SQLObjectNotFound)

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.interfaces import (
    IBuildQueue, IBuildQueueSet, NotFoundError)


class BuildQueue(SQLBase):
    implements(IBuildQueue)
    _table = "BuildQueue"
    _defaultOrder = "id"

    build = ForeignKey(dbName='build', foreignKey='Build', notNull=True)
    builder = ForeignKey(dbName='builder', foreignKey='Builder', default=None)
    created = UtcDateTimeCol(dbName='created', default=UTC_NOW)
    buildstart = UtcDateTimeCol(dbName='buildstart', default= None)
    logtail = StringCol(dbName='logtail', default=None)
    lastscore = IntCol(dbName='lastscore', default=0)
    manual = BoolCol(dbName='manual', default=False)

    def manualScore(self, value):
        """See IBuildQueue."""
        self.lastscore = value
        self.manual = True

    @property
    def archseries(self):
        """See IBuildQueue."""
        return self.build.distroarchseries

    @property
    def urgency(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.urgency

    @property
    def component_name(self):
        """See IBuildQueue."""
        # check currently published version
        publishings = self.build.sourcepackagerelease.publishings
        if publishings.count() > 0:
            return publishings[0].component.name
        # if not found return the original component
        return self.build.sourcepackagerelease.component.name

    @property
    def archhintlist(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.architecturehintlist

    @property
    def name(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.name

    @property
    def version(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.version

    @property
    def files(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.files

    @property
    def builddependsindep(self):
        """See IBuildQueue."""
        return self.build.sourcepackagerelease.builddependsindep

    @property
    def buildduration(self):
        """See IBuildQueue."""
        if self.buildstart:
            UTC = pytz.timezone('UTC')
            now = datetime.now(UTC)
            return now - self.buildstart
        return None

    @property
    def is_trusted(self):
        """See IBuildQueue"""
        return self.build.is_trusted


class BuildQueueSet(object):
    """See IBuildQueueSet"""
    implements(IBuildQueueSet)

    def __init__(self):
        self.title = "The Launchpad build queue"

    def __iter__(self):
        """See IBuildQueueSet."""
        return iter(BuildQueue.select())

    def __getitem__(self, job_id):
        """See IBuildQueueSet."""
        try:
            return BuildQueue.get(job_id)
        except SQLObjectNotFound:
            raise NotFoundError(job_id)

    def get(self, job_id):
        """See IBuildQueueSet."""
        return BuildQueue.get(job_id)

    def count(self):
        """See IBuildQueueSet."""
        return BuildQueue.select().count()

    def getByBuilder(self, builder):
        """See IBuildQueueSet."""
        return BuildQueue.selectOneBy(builder=builder)

    def getActiveBuildJobs(self):
        """See IBuildQueueSet."""
        return BuildQueue.select('buildstart is not null')

    def fetchByBuildIds(self, build_ids):
        """See IBuildQueueSet."""
        if len(build_ids) == 0:
            return []

        return BuildQueue.select(
            "buildqueue.build IN %s" % ','.join(sqlvalues(build_ids)),
            prejoins=['builder'])

    def calculateCandidates(self, archserieses, state):
        """See IBuildQueueSet."""
        if not archserieses:
            # return an empty SQLResult instance to make the callsites happy.
            return BuildQueue.select("1=2")

        if not isinstance(archserieses, list):
            archseries = [archserieses]
        arch_ids = [d.id for d in archserieses]

        candidates = BuildQueue.select("""
        build.distroarchrelease IN %s AND
        build.buildstate = %s AND
        buildqueue.build = build.id AND
        buildqueue.builder IS NULL
        """ % sqlvalues(arch_ids, state), clauseTables=['Build'])

        return candidates
