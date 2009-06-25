# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type

__all__ = [
    'BuildQueue',
    'BuildQueueSet'
    ]

from datetime import datetime
import logging
import pytz

from zope.component import getUtility
from zope.interface import implements

from sqlobject import (
    StringCol, ForeignKey, BoolCol, IntCol, SQLObjectNotFound)
from storm.expr import In, LeftJoin

from canonical import encoding
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.registry.interfaces.sourcepackage import SourcePackageUrgency
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.buildqueue import IBuildQueue, IBuildQueueSet
from lp.soyuz.interfaces.publishing import PackagePublishingPocket
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)


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
        """See `IBuildQueue`."""
        self.lastscore = value
        self.manual = True

    @property
    def archseries(self):
        """See `IBuildQueue`."""
        return self.build.distroarchseries

    @property
    def urgency(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.urgency

    @property
    def archhintlist(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.architecturehintlist

    @property
    def name(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.name

    @property
    def version(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.version

    @property
    def files(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.files

    @property
    def builddependsindep(self):
        """See `IBuildQueue`."""
        return self.build.sourcepackagerelease.builddependsindep

    @property
    def buildduration(self):
        """See `IBuildQueue`."""
        if self.buildstart:
            UTC = pytz.timezone('UTC')
            now = datetime.now(UTC)
            return now - self.buildstart
        return None

    @property
    def is_virtualized(self):
        """See `IBuildQueue`."""
        return self.build.is_virtualized

    def score(self):
        """See `IBuildQueue`."""
        # Grab any logger instance available.
        logger = logging.getLogger()

        if self.manual:
            logger.debug(
                "%s (%d) MANUALLY RESCORED" % (self.name, self.lastscore))
            return

        # XXX Al-maisan, 2008-05-14 (bug #230330):
        # We keep touching the code here whenever a modification to the
        # scoring parameters/weights is needed. Maybe the latter can be
        # externalized?

        score_pocketname = {
            PackagePublishingPocket.BACKPORTS: 0,
            PackagePublishingPocket.RELEASE: 1500,
            PackagePublishingPocket.PROPOSED: 3000,
            PackagePublishingPocket.UPDATES: 3000,
            PackagePublishingPocket.SECURITY: 4500,
            }

        score_componentname = {
            'multiverse': 0,
            'universe': 250,
            'restricted': 750,
            'main': 1000,
            'partner' : 1250,
            }

        score_urgency = {
            SourcePackageUrgency.LOW: 5,
            SourcePackageUrgency.MEDIUM: 10,
            SourcePackageUrgency.HIGH: 15,
            SourcePackageUrgency.EMERGENCY: 20,
            }

        # Define a table we'll use to calculate the score based on the time
        # in the build queue.  The table is a sorted list of (upper time
        # limit in seconds, score) tuples.
        queue_time_scores = [
            (14400, 100),
            (7200, 50),
            (3600, 20),
            (1800, 15),
            (900, 10),
            (300, 5),
        ]

        private_archive_increment = 10000

        # For build jobs in rebuild archives a score value of -1
        # was chosen because their priority is lower than build retries
        # or language-packs. They should be built only when there is
        # nothing else to build.
        rebuild_archive_score = -10

        score = 0
        msg = "%s (%d) -> " % (self.build.title, self.lastscore)

        # Please note: the score for language packs is to be zero because
        # they unduly delay the building of packages in the main component
        # otherwise.
        if self.build.sourcepackagerelease.section.name == 'translations':
            msg += "LPack => score zero"
        elif self.build.archive.purpose == ArchivePurpose.COPY:
            score = rebuild_archive_score
            msg += "Rebuild archive => -1"
        else:
            # Calculates the urgency-related part of the score.
            urgency = score_urgency[self.urgency]
            score += urgency
            msg += "U+%d " % urgency

            # Calculates the pocket-related part of the score.
            score_pocket = score_pocketname[self.build.pocket]
            score += score_pocket
            msg += "P+%d " % score_pocket

            # Calculates the component-related part of the score.
            score_component = score_componentname[
                self.build.current_component.name]
            score += score_component
            msg += "C+%d " % score_component

            # Calculates the build queue time component of the score.
            right_now = datetime.now(pytz.timezone('UTC'))
            eta = right_now - self.created
            for limit, dep_score in queue_time_scores:
                if eta.seconds > limit:
                    score += dep_score
                    msg += "T+%d " % dep_score
                    break
            else:
                msg += "T+0 "

            # Private builds get uber score.
            if self.build.archive.private:
                score += private_archive_increment

        # Store current score value.
        self.lastscore = score

        logger.debug("%s= %d" % (msg, self.lastscore))

    def getLogFileName(self):
        """See `IBuildQueue`."""
        sourcename = self.build.sourcepackagerelease.name
        version = self.build.sourcepackagerelease.version
        # we rely on previous storage of current buildstate
        # in the state handling methods.
        state = self.build.buildstate.name

        dar = self.build.distroarchseries
        distroname = dar.distroseries.distribution.name
        distroseriesname = dar.distroseries.name
        archname = dar.architecturetag

        # logfilename format:
        # buildlog_<DISTRIBUTION>_<DISTROSeries>_<ARCHITECTURE>_\
        # <SOURCENAME>_<SOURCEVERSION>_<BUILDSTATE>.txt
        # as:
        # buildlog_ubuntu_dapper_i386_foo_1.0-ubuntu0_FULLYBUILT.txt
        # it fix request from bug # 30617
        return ('buildlog_%s-%s-%s.%s_%s_%s.txt' % (
            distroname, distroseriesname, archname, sourcename, version, state
            ))

    def markAsBuilding(self, builder):
        """See `IBuildQueue`."""
        self.builder = builder
        self.buildstart = UTC_NOW
        self.build.buildstate = BuildStatus.BUILDING
        # The build started, set the start time if not set already.
        if self.build.date_first_dispatched is None:
            self.build.date_first_dispatched = UTC_NOW

    def reset(self):
        """See `IBuildQueue`."""
        self.builder = None
        self.buildstart = None
        self.logtail = None
        self.build.buildstate = BuildStatus.NEEDSBUILD

    def updateBuild_IDLE(self, build_id, build_status, logtail,
                         filemap, dependencies, logger):
        """See `IBuildQueue`."""
        logger.warn(
            "Builder %s forgot about build %s -- resetting buildqueue record"
            % (self.builder.url, self.build.title))
        self.reset()

    def updateBuild_BUILDING(self, build_id, build_status,
                             logtail, filemap, dependencies, logger):
        """See `IBuildQueue`."""
        self.logtail = encoding.guess(str(logtail))

    def updateBuild_ABORTING(self, buildid, build_status,
                             logtail, filemap, dependencies, logger):
        """See `IBuildQueue`."""
        self.logtail = "Waiting for slave process to be terminated"

    def updateBuild_ABORTED(self, buildid, build_status,
                            logtail, filemap, dependencies, logger):
        """See `IBuildQueue`."""
        self.builder.cleanSlave()
        self.builder = None
        self.buildstart = None
        self.build.buildstate = BuildStatus.BUILDING


class BuildQueueSet(object):
    """Utility to deal with BuildQueue content class."""
    implements(IBuildQueueSet)

    def __init__(self):
        self.title = "The Launchpad build queue"

    def __iter__(self):
        """See `IBuildQueueSet`."""
        return iter(BuildQueue.select())

    def __getitem__(self, job_id):
        """See `IBuildQueueSet`."""
        try:
            return BuildQueue.get(job_id)
        except SQLObjectNotFound:
            raise NotFoundError(job_id)

    def get(self, job_id):
        """See `IBuildQueueSet`."""
        return BuildQueue.get(job_id)

    def count(self):
        """See `IBuildQueueSet`."""
        return BuildQueue.select().count()

    def getByBuilder(self, builder):
        """See `IBuildQueueSet`."""
        return BuildQueue.selectOneBy(builder=builder)

    def getActiveBuildJobs(self):
        """See `IBuildQueueSet`."""
        return BuildQueue.select('buildstart is not null')

    def calculateCandidates(self, archseries):
        """See `IBuildQueueSet`."""
        if not archseries:
            raise AssertionError("Given 'archseries' cannot be None/empty.")

        arch_ids = [d.id for d in archseries]

        query = """
           Build.distroarchseries IN %s AND
           Build.buildstate = %s AND
           BuildQueue.build = build.id AND
           BuildQueue.builder IS NULL
        """ % sqlvalues(arch_ids, BuildStatus.NEEDSBUILD)

        candidates = BuildQueue.select(
            query, clauseTables=['Build'], orderBy=['-BuildQueue.lastscore'])

        return candidates

    def getForBuilds(self, build_ids):
        """See `IBuildQueueSet`."""
        # Avoid circular import problem.
        from lp.soyuz.model.builder import Builder

        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)

        origin = (
            BuildQueue,
            LeftJoin(
                Builder,
                BuildQueue.builderID == Builder.id),
            )
        result_set = store.using(*origin).find(
            (BuildQueue, Builder),
            In(BuildQueue.buildID, build_ids))

        return result_set
