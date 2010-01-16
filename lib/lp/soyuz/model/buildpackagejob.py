# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = ['BuildPackageJob']


from datetime import datetime
import pytz

from storm.locals import Int, Reference, Storm

from zope.interface import classProvides, implements
from zope.component import getUtility

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import sqlvalues

from lp.buildmaster.interfaces.buildfarmjob import (
    BuildFarmJobType, IBuildFarmJobDispatchEstimation)
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.registry.interfaces.sourcepackage import SourcePackageUrgency
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.job.interfaces.job import JobStatus
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.build import BuildStatus, IBuildSet
from lp.soyuz.interfaces.buildpackagejob import IBuildPackageJob
from lp.soyuz.interfaces.publishing import PackagePublishingStatus


class BuildPackageJob(Storm, BuildFarmJob):
    """See `IBuildPackageJob`."""
    implements(IBuildPackageJob)
    classProvides(IBuildFarmJobDispatchEstimation)

    __storm_table__ = 'buildpackagejob'
    id = Int(primary=True)

    job_id = Int(name='job', allow_none=False)
    job = Reference(job_id, 'Job.id')

    build_id = Int(name='build', allow_none=False)
    build = Reference(build_id, 'Build.id')

    def score(self):
        """See `IBuildPackageJob`."""
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
            'partner': 1250,
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

        # Please note: the score for language packs is to be zero because
        # they unduly delay the building of packages in the main component
        # otherwise.
        if self.build.sourcepackagerelease.section.name == 'translations':
            pass
        elif self.build.archive.purpose == ArchivePurpose.COPY:
            score = rebuild_archive_score
        else:
            # Calculates the urgency-related part of the score.
            urgency = score_urgency[self.build.sourcepackagerelease.urgency]
            score += urgency

            # Calculates the pocket-related part of the score.
            score_pocket = score_pocketname[self.build.pocket]
            score += score_pocket

            # Calculates the component-related part of the score.
            score_component = score_componentname[
                self.build.current_component.name]
            score += score_component

            # Calculates the build queue time component of the score.
            right_now = datetime.now(pytz.timezone('UTC'))
            eta = right_now - self.job.date_created
            for limit, dep_score in queue_time_scores:
                if eta.seconds > limit:
                    score += dep_score
                    break

            # Private builds get uber score.
            if self.build.archive.private:
                score += private_archive_increment

            # Lastly, apply the archive score delta.  This is to boost
            # or retard build scores for any build in a particular
            # archive.
            score += self.build.archive.relative_build_score

        return score

    def getLogFileName(self):
        """See `IBuildPackageJob`."""
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
            distroname, distroseriesname, archname, sourcename, version,
            state))

    def getName(self):
        """See `IBuildPackageJob`."""
        return self.build.sourcepackagerelease.name

    def getTitle(self):
        """See `IBuildPackageJob`."""
        return self.build.title

    def jobStarted(self):
        """See `IBuildPackageJob`."""
        self.build.buildstate = BuildStatus.BUILDING
        # The build started, set the start time if not set already.
        if self.build.date_first_dispatched is None:
            self.build.date_first_dispatched = UTC_NOW

    def jobReset(self):
        """See `IBuildPackageJob`."""
        self.build.buildstate = BuildStatus.NEEDSBUILD

    def jobAborted(self):
        """See `IBuildPackageJob`."""
        # XXX, al-maisan, Thu, 12 Nov 2009 16:38:52 +0100
        # The setting below was "inherited" from the previous code. We
        # need to investigate whether and why this is really needed and
        # fix it.
        self.build.buildstate = BuildStatus.BUILDING

    @staticmethod
    def composePendingJobsQuery(min_score, processor, virtualized):
        """See `IBuildFarmJob`."""
        return """
            SELECT
                BuildQueue.job,
                BuildQueue.lastscore,
                BuildQueue.estimated_duration,
                Build.processor AS processor,
                Archive.require_virtualized AS virtualized
            FROM
                BuildQueue, Build, BuildPackageJob, Archive, Job
            WHERE
                BuildQueue.job_type = %s
                AND BuildPackageJob.job = BuildQueue.job
                AND BuildPackageJob.job = Job.id
                AND Job.status = %s
                AND BuildPackageJob.build = Build.id
                AND Build.buildstate = %s
                AND Build.archive = Archive.id
                AND Archive.enabled = TRUE
                AND BuildQueue.lastscore >= %s
                AND Build.processor = %s
                AND Archive.require_virtualized = %s
        """ % sqlvalues(
            BuildFarmJobType.PACKAGEBUILD, JobStatus.WAITING,
            BuildStatus.NEEDSBUILD, min_score, processor, virtualized)

    @property
    def processor(self):
        """See `IBuildFarmJob`."""
        return self.build.processor

    @property
    def virtualized(self):
        """See `IBuildFarmJob`."""
        return self.build.is_virtualized

    @staticmethod
    def addCandidateSelectionCriteria(processor, virtualized):
        """See `IBuildFarmCandidateJobSelection`."""
        # Avoiding circular import.
        from lp.buildmaster.model.builder import Builder

        private_statuses = (
            PackagePublishingStatus.PUBLISHED,
            PackagePublishingStatus.SUPERSEDED,
            PackagePublishingStatus.DELETED,
            )
        extra_tables = [
            'Archive', 'Build', 'BuildPackageJob', 'DistroArchSeries']
        extra_clauses = """
            BuildPackageJob.job = Job.id AND 
            BuildPackageJob.build = Build.id AND 
            Build.distroarchseries = DistroArchSeries.id AND
            Build.archive = Archive.id AND
            ((Archive.private IS TRUE AND
              EXISTS (
                  SELECT SourcePackagePublishingHistory.id
                  FROM SourcePackagePublishingHistory
                  WHERE
                      SourcePackagePublishingHistory.distroseries =
                         DistroArchSeries.distroseries AND
                      SourcePackagePublishingHistory.sourcepackagerelease =
                         Build.sourcepackagerelease AND
                      SourcePackagePublishingHistory.archive = Archive.id AND
                      SourcePackagePublishingHistory.status IN %s))
              OR
              archive.private IS FALSE) AND
            build.buildstate = %s
        """ % sqlvalues(private_statuses, BuildStatus.NEEDSBUILD)

        # Ensure that if BUILDING builds exist for the same
        # public ppa archive and architecture and another would not
        # leave at least 20% of them free, then we don't consider
        # another as a candidate.
        #
        # This clause selects the count of currently building builds on
        # the arch in question, then adds one to that total before
        # deriving a percentage of the total available builders on that
        # arch.  It then makes sure that percentage is under 80.
        #
        # The extra clause is only used if the number of available
        # builders is greater than one, or nothing would get dispatched
        # at all.
        num_arch_builders = Builder.selectBy(
            processor=processor, manual=False, builderok=True).count()
        if num_arch_builders > 1:
            extra_clauses += """
                AND EXISTS (SELECT true
                WHERE ((
                    SELECT COUNT(build2.id)
                    FROM Build build2, DistroArchSeries distroarchseries2
                    WHERE
                        build2.archive = build.archive AND
                        archive.purpose = %s AND
                        archive.private IS FALSE AND
                        build2.distroarchseries = distroarchseries2.id AND
                        distroarchseries2.processorfamily = %s AND
                        build2.buildstate = %s) + 1::numeric)
                    *100 / %s
                    < 80)
            """ % sqlvalues(
                ArchivePurpose.PPA, processor.family,
                BuildStatus.BUILDING, num_arch_builders)

        return(extra_tables, extra_clauses)

    @staticmethod
    def postprocessCandidate(job, logger):
        """See `IBuildFarmCandidateJobSelection`."""
        # Mark build records targeted to old source versions as SUPERSEDED
        # and build records target to SECURITY pocket as FAILEDTOBUILD.
        # Builds in those situation should not be built because they will
        # be wasting build-time, the former case already has a newer source
        # and the latter could not be built in DAK.
        build_set = getUtility(IBuildSet)

        build = build_set.getByQueueEntry(job)
        if build.pocket == PackagePublishingPocket.SECURITY:
            # We never build anything in the security pocket.
            logger.debug(
                "Build %s FAILEDTOBUILD, queue item %s REMOVED"
                % (build.id, job.id))
            build.buildstate = BuildStatus.FAILEDTOBUILD
            job.destroySelf()
            return False

        publication = build.current_source_publication
        if publication is None:
            # The build should be superseded if it no longer has a
            # current publishing record.
            logger.debug(
                "Build %s SUPERSEDED, queue item %s REMOVED"
                % (build.id, job.id))
            build.buildstate = BuildStatus.SUPERSEDED
            job.destroySelf()
            return False

        return True
