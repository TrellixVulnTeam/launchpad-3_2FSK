# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Populate `DistroSeriesDifference` table.

This script creates `DistroSeriesDifference` entries for the package
version differences between a derived `DistroSeries` and its parent.

The entries will still need to be processed by the cron job that works
out the exact differences.  Any pre-existing `DistroSeriesDifference`
entries remain untouched.
"""

__metaclass__ = type
__all__ = [
    'PopulateDistroSeriesDiff',
    ]

from optparse import (
    Option,
    OptionValueError,
    )
from storm.info import ClassAlias
import transaction
from zope.component import getUtility

from canonical.database.sqlbase import (
    quote,
    quote_identifier,
    )
from canonical.launchpad.interfaces.lpstorm import IStore
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from canonical.launchpad.utilities.looptuner import TunableLoop
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.distroseriesdifference import DistroSeriesDifference
from lp.services.scripts.base import LaunchpadScript
from lp.soyuz.interfaces.publishing import active_publishing_status


def compose_sql_find_latest_source_package_releases(distroseries):
    """Produce SQL that gets the last-published `SourcePackageRelease`s.

    Within `distroseries`, looks for the `SourcePackageRelease`
    belonging to each respective `SourcePackageName`'s respective latest
    `SourcePackagePublishingHistory`.

    For each of those, it produces a tuple consisting of:
     * `SourcePackageName` id: sourcepackagename
     * `SourcePackageRelease` id: sourcepackagerelease
     * Source package version: version.

    :return: SQL query, as a string.
    """
    parameters = {
        'active_status': quote(active_publishing_status),
        'distroseries': quote(distroseries),
        'main_archive': quote(distroseries.distribution.main_archive),
        'release_pocket': quote(PackagePublishingPocket.RELEASE),
    }
    return """
        SELECT DISTINCT ON (SPR.sourcepackagename)
            SPR.sourcepackagename,
            SPR.id As sourcepackagerelease,
            SPR.version
        FROM SourcePackagePublishingHistory AS SPPH
        JOIN SourcePackageRelease AS SPR ON SPR.id = SPPH.sourcepackagerelease
        WHERE
            SPPH.distroseries = %(distroseries)s AND
            SPPH.archive = %(main_archive)s AND
            SPPH.pocket = %(release_pocket)s AND
            SPPH.status IN %(active_status)s
        ORDER BY SPR.sourcepackagename, SPPH.id DESC
        """ % parameters


def compose_sql_find_differences(derived_distroseries):
    """Produce SQL that finds differences for a `DistroSeries`.

    The query compares `derived_distroseries` and its `parent_series`
    and for each package whose latest `SourcePackageRelease`s in the
    respective series differ, produces a tuple of:
     * `SourcePackageName` id: sourcepackagename
     * Source package version in derived series: source_version
     * Source package version in parent series: parent_source_version.

    :return: SQL query, as a string.
    """
    parameters = {
        'derived_query': compose_sql_find_latest_source_package_releases(
            derived_distroseries),
        'parent_query': compose_sql_find_latest_source_package_releases(
            derived_distroseries.parent_series),
    }
    return """
        SELECT DISTINCT
            COALESCE(
                parent.sourcepackagename,
                derived.sourcepackagename) AS sourcepackagename,
            derived.version AS source_version,
            parent.version AS parent_source_version
        FROM (%(parent_query)s) AS parent
        FULL OUTER JOIN (%(derived_query)s) AS derived
        ON derived.sourcepackagename = parent.sourcepackagename
        WHERE
            derived.sourcepackagerelease IS DISTINCT FROM
                parent.sourcepackagerelease
        """ % parameters


def compose_sql_difference_type():
    """Produce SQL to compute a difference's `DistroSeriesDifferenceType`.

    Works with the parent_source_version and source_version fields as
    produced by the SQL from `compose_sql_find_differences`.

    :return: SQL query, as a string.
    """
    parameters = {
        'unique_to_derived_series': quote(
            DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES),
        'missing_from_derived_series': quote(
            DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES),
        'different_versions': quote(
            DistroSeriesDifferenceType.DIFFERENT_VERSIONS),
    }
    return """
        CASE
            WHEN parent_source_version IS NULL THEN
                %(unique_to_derived_series)s
            WHEN source_version IS NULL THEN
                %(missing_from_derived_series)s
            ELSE %(different_versions)s
        END
        """ % parameters


def compose_sql_populate_distroseriesdiff(derived_distroseries, temp_table):
    """Create `DistroSeriesDifference` rows based on found differences.

    Uses field values that describe the difference, as produced by the
    SQL from `compose_sql_find_differences`:
     * sourcepackagename
     * source_version
     * parent_source_version

    Existing `DistroSeriesDifference` rows are not affected.

    :param derived_distroseries: A derived `DistroSeries`.
    :param temp_table: The name of a table to select the input fields
        from.
    :return: SQL query, as a string.
    """
    parameters = {
        'derived_series': quote(derived_distroseries),
        'difference_type_expression': compose_sql_difference_type(),
        'needs_attention': quote(
            DistroSeriesDifferenceStatus.NEEDS_ATTENTION),
        'temp_table': quote_identifier(temp_table),
    }
    return """
        INSERT INTO DistroSeriesDifference (
            derived_series,
            source_package_name,
            status,
            difference_type,
            source_version,
            parent_source_version)
        SELECT
            %(derived_series)s,
            sourcepackagename,
            %(needs_attention)s,
            %(difference_type_expression)s,
            source_version,
            parent_source_version
        FROM %(temp_table)s
        WHERE sourcepackagename NOT IN (
            SELECT source_package_name
            FROM DistroSeriesDifference
            WHERE derived_series = %(derived_series)s)
        """ % parameters


def drop_table(store, table):
    """Drop `table`, if it exists."""
    store.execute("DROP TABLE IF EXISTS %s" % quote_identifier(table))


def populate_distroseriesdiff(logger, derived_distroseries):
    """Compare `derived_distroseries` to parent, and register differences.

    The differences are registered by creating `DistroSeriesDifference`
    records, insofar as they do not yet exist.
    """
    temp_table = "temp_potentialdistroseriesdiff"

    store = IStore(derived_distroseries)
    drop_table(store, temp_table)
    store.execute("CREATE TEMP TABLE %s AS %s" % (
        quote_identifier(temp_table),
        compose_sql_find_differences(derived_distroseries)))
    logger.info(
        "Found %d potential difference(s).",
        store.execute("SELECT count(*) FROM %s" % temp_table).get_one()[0])
    store.execute(
        compose_sql_populate_distroseriesdiff(
            derived_distroseries, temp_table))
    drop_table(store, temp_table)


def find_derived_series():
    """Find all derived `DistroSeries`.

    Derived `DistroSeries` are ones that have a `parent_series`, but
    where the `parent_series` is not in the same distribution.
    """
    Parent = ClassAlias(DistroSeries, "Parent")
    return IStore(DistroSeries).find(
        DistroSeries,
        Parent.id == DistroSeries.parent_seriesID,
        Parent.distributionID != DistroSeries.distributionID).order_by(
            (DistroSeries.parent_seriesID, DistroSeries.id))


class BaseVersionFixer(TunableLoop):
    """Fix up `DistroSeriesDifference.base_version` in the database.

    The code that creates `DistroSeriesDifference`s does not set the
    `base_version`.  In cases where there may actually be a real base
    version, this needs to be fixed up.

    Since this is likely to be much, much slower than the rest of the
    work of creating and initializing `DistroSeriesDifference`s, it is
    done in a `DBLoopTuner`.
    """

    def __init__(self, log, store, commit, ids):
        """See `TunableLoop`.

        :param log: A logger.
        :param store: Database store to work on.
        :param commit: A commit function to call after each batch.
        :param ids: Sequence of `DistroSeriesDifference` ids to fix.
        """
        super(BaseVersionFixer, self).__init__(log)
        self.minimum_chunk_size = 2
        self.maximum_chunk_size = 1000
        self.store = store
        self.commit = commit
        self.ids = sorted(ids, reverse=True)

    def isDone(self):
        """See `ITunableLoop`."""
        return len(self.ids) == 0

    def _cutChunk(self, chunk_size):
        """Cut a chunk of up to `chunk_size` items from the remaining work.

        Removes the items to be processed in this chunk from the list of
        remaining work, and returns those.
        """
        todo = self.ids[-chunk_size:]
        self.ids = self.ids[:-chunk_size]
        return todo

    def _getBatch(self, ids):
        """Retrieve a batch of `DistroSeriesDifference`s with given ids."""
        return self.store.find(
            DistroSeriesDifference, DistroSeriesDifference.id.is_in(ids))

    def __call__(self, chunk_size):
        """See `ITunableLoop`."""
        for dsd in self._getBatch(self._cutChunk(int(chunk_size))):
            dsd._updateBaseVersion()
        self.commit()


class PopulateDistroSeriesDiff(LaunchpadScript):
    """Populate `DistroSeriesDifference` for pre-existing differences."""

    def add_my_options(self):
        """Register options specific to this script."""
        self.parser.add_options([
            Option(
                '-a', '--all', dest='all', action='store_true', default=False,
                help="Populate all derived distribution series."),
            Option(
                '-d', '--distribution', dest='distribution', default=None,
                help="Derived distribution."),
            Option(
                '-l', '--list', dest='list', action='store_true',
                default=False, help="List derived distroseries, then exit."),
            Option(
                '-s', '--series', dest='series', default=None,
                help="Derived distribution series."),
            Option(
                '-x', '--dry-run', dest='dry_run', action='store_true',
                default=False, help="Pretend; don't commit changes.")])

    def getDistroSeries(self):
        """Return the `DistroSeries` that are to be processed."""
        if self.options.all:
            return list(find_derived_series())
        else:
            distro = getUtility(IDistributionSet).getByName(
                self.options.distribution)
            series = distro.getSeries(self.options.series)
            if series is None:
                raise OptionValueError(
                    "Could not find %s series %s." % (
                        self.options.distribution, self.options.series))
            if series.parent_series is None:
                raise OptionValueError(
                    "%s series %s is not derived." % (
                        self.options.distribution, self.options.series))
            return [series]

    def processDistroSeries(self, distroseries):
        """Generate `DistroSeriesDifference`s for `distroseries`."""
        self.logger.info("Looking for differences in %s.", distroseries)
        populate_distroseriesdiff(self.logger, distroseries)
        self.commit()
        self.logger.info("Updating base_versions.")
        self.fixBaseVersions(distroseries)
        self.commit()
        self.logger.info("Done with %s.", distroseries)

    def commit(self):
        """Commit (or if doing a dry run, abort instead)."""
        if self.options.dry_run:
            transaction.abort()
        else:
            transaction.commit()

    def listDerivedSeries(self):
        """Log all `DistroSeries` that the --all option would cover."""
        for series in self.getDistroSeries():
            self.logger.info("%s %s", series.distribution.name, series.name)

    def checkOptions(self):
        """Verify command-line options."""
        if self.options.list:
            return
        specified_distro = (self.options.distribution is not None)
        specified_series = (self.options.series is not None)
        if specified_distro != specified_series:
            raise OptionValueError(
                "Specify both a distribution and a series, or use --all.")
        if specified_distro == self.options.all:
            raise OptionValueError(
                "Either specify a distribution and series, or use --all.")

    def main(self):
        """Do the script's work."""
        self.checkOptions()

        if self.options.list:
            self.options.all = True
            self.listDerivedSeries()
            return

        if self.options.dry_run:
            self.logger.info("Dry run requested.  Not committing changes.")

        for series in self.getDistroSeries():
            self.processDistroSeries(series)

    def fixBaseVersions(self, distroseries):
        """Fix up `DistroSeriesDifference.base_version` where appropriate.

        The `DistroSeriesDifference` records we create don't have their
        `base_version` fields set yet.  This is a shame because it's the
        only thing we need to figure out python-side.

        Only instances where the source package is published in both the
        parent series and the derived series need to have this done.
        """
        self.logger.info(
            "Fixing up base_versions for %s.", distroseries.title)
        store = IStore(distroseries)
        dsd_ids = store.find(
            DistroSeriesDifference.id,
            DistroSeriesDifference.derived_series == distroseries,
            DistroSeriesDifference.status ==
                DistroSeriesDifferenceStatus.NEEDS_ATTENTION,
            DistroSeriesDifference.difference_type ==
                DistroSeriesDifferenceType.DIFFERENT_VERSIONS,
            DistroSeriesDifference.base_version == None)
        BaseVersionFixer(self.logger, store, self.commit, dsd_ids).run()
