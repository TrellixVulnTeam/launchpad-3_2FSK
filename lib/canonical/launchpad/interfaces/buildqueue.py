# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""Build interfaces."""

__metaclass__ = type

__all__ = [
    'IBuildQueue',
    'IBuildQueueSet',
    ]

from zope.interface import Interface, Attribute

from canonical.launchpad import _

class IBuildQueue(Interface):
    """A Launchpad Auto Build queue entry.

    This table contains work-in-progress in Buildd environment, as well as
    incoming jobs.

    It relates a pending Builds with an heuristic index (last_score) which
    is used to order build jobs in a proper way.

    When building (job dispatched) it also includes the responsible Builder
    (builder), the time it has started (buildstarted) and up to 2 Kbytes
    of the current processing log (logtail).
    """

    id = Attribute("Job identifier")
    build = Attribute("The IBuild record that originated this job")
    builder = Attribute("The IBuilder instance processing this job")
    created = Attribute("The datetime that the queue entry was created")
    buildstart = Attribute("The datetime of the last build attempt")
    logtail = Attribute("The current tail of the log of the build")
    lastscore = Attribute("Last score to be computed for this job")
    manual = Attribute("Whether or not the job was manually scored")

    # properties inherited from related Content classes.
    archseries = Attribute(
        "DistroArchSeries target of the IBuild releated to this job.")
    name = Attribute(
        "Name of the ISourcePackageRelease releated to this job.")
    version = Attribute(
        "Version of the ISourcePackageRelease releated to this job.")
    files = Attribute(
        "Collection of files related to the ISourcePackageRelease "
        "releated to this job.")
    component_name = Attribute(
        "Component name where the ISourcePackageRelease releated to "
        "this job got published in.")
    urgency = Attribute(
        "Urgency of the ISourcePackageRelease releated to this job.")
    archhintlist = Attribute(
        "architecturehintlist of the ISourcePackageRelease releated "
        "to this job.")
    builddependsindep = Attribute(
        "builddependsindep of the ISourcePackageRelease releated to "
        "this job.")
    buildduration = Attribute(
        "Durarion of the job, calculated on-the-fly based on buildstart.")
    is_trusted = Attribute("See IBuild.is_trusted.")

    def manualScore(value):
        """Manually set a score value to a queue item and lock it."""

    def destroySelf():
        """Delete this entry from the database."""

    def getLogFileName():
        """Get the preferred filename for the buildlog of this build."""

    def updateBuild_IDLE(slave, build_id, build_status, logtail,
                         filemap, dependencies, logger):
        """Somehow the builder forgot about the build job.

        Log this and reset the record.
        """

    def updateBuild_BUILDING(slave, build_id, build_status,
                             logtail, filemap, dependencies, logger):
        """Build still building, Simple collects the logtail"""

    def updateBuild_ABORTING(slave, buildid, build_status,
                             logtail, filemap, dependencies, logger):
        """Build was ABORTED.

        Master-side should wait until the slave finish the process correctly.
        """

    def updateBuild_ABORTED(slave, buildid, build_status,
                            logtail, filemap, dependencies, logger):
        """ABORTING process has successfully terminated.

        Clean the builder for another jobs.
        """


class IBuildQueueSet(Interface):
    """Launchpad Auto Build queue set handler and auxiliary methods."""

    title = Attribute('Title')

    def __iter__():
        """Iterate over current build jobs."""

    def __getitem__(job_id):
        """Retrieve a build job by id."""

    def count():
        """Return the number of build jobs in the queue."""

    def get(job_id):
        """Return the IBuildQueue with the given job_id."""

    def getByBuilder(builder):
        """Return an IBuildQueue instance for a builder.

        Retrieve the only one possible entry being processed for a given
        builder. If not found, return None.
        """

    def getActiveBuildJobs():
        """Return All active Build Jobs."""

    def fetchByBuildIds(build_ids):
        """Used to pre-populate the cache with reversed referred keys.

        When dealing with a group of Build records we can't use pre-join
        facility to also fetch BuildQueue records in a single query,
        because Build and BuildQueue are related with reversed keys

        Build.id = BuildQueue.build

        So this method receives a list of Build IDs and fetches the
        correspondent BuildQueue with prejoined builder information.

        It return the SelectResults or empty list if the passed builds
        is empty, but the result isn't might to be used in call site.
        """

    def calculateCandidates(archserieses, state):
        """Return the candidates for building

        The result is a unsorted list of BuildQueue items in a given state
        within a given DistroArchSeries group.
        """

