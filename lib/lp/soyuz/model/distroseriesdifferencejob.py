# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Job class to request generation or update of `DistroSeriesDifference`s."""

__metaclass__ = type
__all__ = [
    'DistroSeriesDifferenceJob',
    ]

from storm.expr import And
from zope.component import getUtility
from zope.interface import (
    classProvides,
    implements,
    )

from canonical.database.sqlbase import sqlvalues
from canonical.launchpad.interfaces.lpstorm import (
    IMasterStore,
    IStore,
    )
from lp.registry.interfaces.distroseriesdifference import (
    IDistroSeriesDifferenceSource,
    )
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.distroseriesdifference import DistroSeriesDifference
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.features import getFeatureFlag
from lp.services.job.model.job import Job
from lp.soyuz.interfaces.distributionjob import (
    DistributionJobType,
    IDistroSeriesDifferenceJob,
    IDistroSeriesDifferenceJobSource,
    )
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.model.distributionjob import (
    DistributionJob,
    DistributionJobDerived,
    )
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease


FEATURE_FLAG_ENABLE_MODULE = u"soyuz.derived_series_jobs.enabled"


def make_metadata(sourcepackagename, parent_series):
    """Return JSON metadata for a job on `sourcepackagename`."""
    return {
        'sourcepackagename': sourcepackagename.id,
        'parent_series': parent_series.id,
    }


def create_job(derived_series, sourcepackagename, parent_series):
    """Create a `DistroSeriesDifferenceJob` for a given source package.

    :param derived_series: A `DistroSeries` that is assumed to be derived
        from another one.
    :param sourcepackagename: The `SourcePackageName` whose publication
        history has changed.
    :param parent_series: A `DistroSeries` that is a parent of
        `derived_series`.  The difference is between the versions of
        `sourcepackagename` in `parent_series` and `derived_series`.
    """
    job = DistributionJob(
        distribution=derived_series.distribution, distroseries=derived_series,
        job_type=DistributionJobType.DISTROSERIESDIFFERENCE,
        metadata=make_metadata(sourcepackagename, parent_series))
    IMasterStore(DistributionJob).add(job)
    return DistroSeriesDifferenceJob(job)


def create_multiple_jobs(derived_series, parent_series):
    """Create a `DistroSeriesDifferenceJob` for all the source packages in
    archive.

    :param derived_series: A `DistroSeries` that is assumed to be derived
        from another one.
    :param parent_series: A `DistroSeries` that is a parent of
        `derived_series`.
    """
    store = IStore(SourcePackageRelease)
    source_package_releases = store.find(
        SourcePackageRelease,
        And(
            SourcePackagePublishingHistory.sourcepackagerelease ==
                SourcePackageRelease.id,
            SourcePackagePublishingHistory.distroseries == derived_series.id,
            SourcePackagePublishingHistory.status.is_in(
                active_publishing_status)))
    nb_jobs = source_package_releases.count()
    sourcepackagenames = source_package_releases.values(
        SourcePackageRelease.sourcepackagenameID)
    job_ids = Job.createMultiple(store, nb_jobs)

    def composeJobInsertionTuple(derived_series, parent_series,
                                 sourcepackagename, job_id):
        data = (
            derived_series.distribution.id, derived_series.id,
            DistributionJobType.DISTROSERIESDIFFERENCE, job_id,
            DistributionJob.serializeMetadata(
                {'sourcepackagename': sourcepackagename,
                 'parent_series': parent_series.id}))
        format_string = "(%s)" % ", ".join(["%s"] * len(data))
        return format_string % sqlvalues(*data)

    job_contents = [
        composeJobInsertionTuple(
            derived_series, parent_series, sourcepackagename, job_id)
        for job_id, sourcepackagename in
            zip(job_ids, sourcepackagenames)]

    store = IStore(DistributionJob)
    result = store.execute("""
        INSERT INTO DistributionJob (
            distribution, distroseries, job_type, job, json_data)
        VALUES %s
        RETURNING id
        """ % ", ".join(job_contents))
    return [job_id for job_id, in result]


def find_waiting_jobs(derived_series, sourcepackagename, parent_series):
    """Look for pending `DistroSeriesDifference` jobs on a package."""
    # Look for identical pending jobs.  This compares directly on
    # the metadata string.  It's fragile, but this is only an
    # optimization.  It's not actually disastrous to create
    # redundant jobs occasionally.
    json_metadata = DistributionJob.serializeMetadata(
        make_metadata(sourcepackagename, parent_series))

    # Use master store because we don't like outdated information
    # here.
    store = IMasterStore(DistributionJob)

    candidates = store.find(
        DistributionJob,
        DistributionJob.job_type ==
            DistributionJobType.DISTROSERIESDIFFERENCE,
        DistributionJob.distroseries == derived_series,
        DistributionJob._json_data == json_metadata,
        DistributionJob.job_id.is_in(Job.ready_jobs))

    return [
        job
        for job in candidates
            if job.metadata["parent_series"] == parent_series.id]


def may_require_job(derived_series, sourcepackagename, parent_series):
    """Might publishing this package require a new job?

    Use this to determine whether to create a new
    `DistroSeriesDifferenceJob`.  The answer may possibly be
    conservatively wrong: the check is really only to save the job
    runner some unnecessary work, but we don't expect a bit of
    unnecessary work to be a big problem.
    """
    if derived_series is None:
        return False
    dsp = getUtility(IDistroSeriesParentSet).getByDerivedSeries(
        derived_series)
    if dsp.count() == 0:
        return False
    for parent in dsp:
        if parent.parent_series.distribution == derived_series.distribution:
            # Differences within a distribution are not tracked.
            return False
    existing_jobs = find_waiting_jobs(
        derived_series, sourcepackagename, parent_series)
    return len(existing_jobs) == 0


def has_package(distroseries, sourcepackagename):
    """Does `distroseries` have the given source package?"""
    return not distroseries.getPublishedSources(
        sourcepackagename, include_pending=True).is_empty()


class DistroSeriesDifferenceJob(DistributionJobDerived):
    """A `Job` type for creating/updating `DistroSeriesDifference`s."""

    implements(IDistroSeriesDifferenceJob)
    classProvides(IDistroSeriesDifferenceJobSource)

    class_job_type = DistributionJobType.DISTROSERIESDIFFERENCE

    @classmethod
    def createForPackagePublication(cls, derived_series, sourcepackagename,
                                    pocket):
        """See `IDistroSeriesDifferenceJobSource`."""
        if not getFeatureFlag(FEATURE_FLAG_ENABLE_MODULE):
            return
        # -backports and -proposed are not really part of a standard
        # distribution's packages so we're ignoring them here.  They can
        # always be manually synced by the users if necessary, in the
        # rare occasions that they require them.
        if pocket in (
            PackagePublishingPocket.BACKPORTS,
            PackagePublishingPocket.PROPOSED):
            return
        jobs = []
        parent_series = derived_series.getParentSeries()
        # Create jobs for DSDs between the derived_series and its
        # parents.
        for parent in parent_series:
            if may_require_job(
                derived_series, sourcepackagename, parent):
                jobs.append(create_job(
                    derived_series, sourcepackagename, parent))
        # Create jobs for DSDs between the derived_series and its
        # children.
        for child in derived_series.getDerivedSeries():
            if may_require_job(
                child, sourcepackagename, derived_series):
                jobs.append(create_job(
                    child, sourcepackagename, derived_series))
        return jobs

    @classmethod
    def massCreateForSeries(cls, derived_series):
        """See `IDistroSeriesDifferenceJobSource`."""
        if not getFeatureFlag(FEATURE_FLAG_ENABLE_MODULE):
            return
        for parent_series in derived_series.getParentSeries():
            create_multiple_jobs(derived_series, parent_series)

    @classmethod
    def getPendingJobsForDifferences(cls, derived_series,
                                     distroseriesdifferences):
        """See `IDistroSeriesDifferenceJobSource`."""
        jobs = IStore(DistributionJob).find(
            DistributionJob,
            DistributionJob.job_type == cls.class_job_type,
            Job.id == DistributionJob.job_id,
            Job._status.is_in(Job.PENDING_STATUSES),
            DistributionJob.distroseries == derived_series)

        parent_series_ids = set(
            dsd.parent_series.id for dsd in distroseriesdifferences)
        keyed_dsds = dict(
            (dsd.source_package_name.id, dsd)
            for dsd in distroseriesdifferences)
        jobs_by_dsd = {}
        for job in jobs:
            if job.metadata["parent_series"] not in parent_series_ids:
                continue
            dsd = keyed_dsds.get(job.metadata["sourcepackagename"])
            if dsd is not None:
                jobs_by_dsd.setdefault(dsd, []).append(cls(job))
        return jobs_by_dsd

    def __repr__(self):
        """Returns an informative representation of the job."""
        parts = "%s for " % self.__class__.__name__
        name = self.sourcepackagename
        if not name:
            parts += "no package name (!)"
        else:
            parts += "package %s" % name
        parts += " from %s to %s" % (self.parent_series.name,
                                     self.derived_series.name)
        return "<%s>" % parts

    @property
    def sourcepackagename(self):
        return SourcePackageName.get(self.metadata['sourcepackagename'])

    @property
    def derived_series(self):
        return self.distroseries

    @property
    def parent_series(self):
        parent_id = self.metadata['parent_series']
        return IStore(DistroSeries).get(DistroSeries, parent_id)

    def passesPackagesetFilter(self):
        """Is this package of interest as far as packagesets are concerned?

        If the parent series has packagesets, then packages that are
        missing in the derived series are only of interest if they are
        in a packageset that the derived series also has.
        """
        derived_series = self.derived_series
        parent_series = self.parent_series

        sourcepackagename = self.sourcepackagename
        if has_package(derived_series, sourcepackagename):
            return True
        if not has_package(parent_series, sourcepackagename):
            return True
        packagesetset = getUtility(IPackagesetSet)
        if packagesetset.getBySeries(parent_series).is_empty():
            # Parent series does not have packagesets, as would be the
            # case for e.g. Debian.  In that case, don't filter.
            return True
        parent_sets = packagesetset.setsIncludingSource(
            sourcepackagename, distroseries=parent_series)
        for parent_set in parent_sets:
            for related_set in parent_set.relatedSets():
                if related_set.distroseries == derived_series:
                    return True
        return False

    def getMatchingDSD(self):
        """Find an existing `DistroSeriesDifference` for this difference."""
        spn_id = self.metadata["sourcepackagename"]
        parent_id = self.metadata["parent_series"]
        store = IMasterStore(DistroSeriesDifference)
        search = store.find(
            DistroSeriesDifference,
            DistroSeriesDifference.derived_series == self.derived_series,
            DistroSeriesDifference.parent_series_id == parent_id,
            DistroSeriesDifference.source_package_name_id == spn_id)
        return search.one()

    def run(self):
        """See `IRunnableJob`."""
        if not self.passesPackagesetFilter():
            return

        ds_diff = self.getMatchingDSD()
        if ds_diff is None:
            ds_diff = getUtility(IDistroSeriesDifferenceSource).new(
                self.distroseries, self.sourcepackagename, self.parent_series)
        else:
            ds_diff.update()
