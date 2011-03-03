# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the populate-distroseriesdiff script."""

__metaclass__ = type

from storm.store import Store

from canonical.database.sqlbase import (
    cursor,
    quote,
    )
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    ZopelessDatabaseLayer,
    )
from lp.registry.enum import DistroSeriesDifferenceType
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.scripts.populate_distroseriesdiff import (
    compose_sql_difference_type,
    compose_sql_find_latest_source_package_releases,
    compose_sql_find_differences,
    compose_sql_populate_distroseriesdiff,
    find_derived_series,
    populate_distroseriesdiff,
    )
from lp.soyuz.interfaces.publishing import (
    active_publishing_status,
    inactive_publishing_status,
    )
from lp.soyuz.model.archive import Archive
from lp.soyuz.enums import ArchivePurpose
from lp.testing import TestCaseWithFactory


def get_archive(factory, distribution, purpose):
    archive = Store.of(distribution).find(
        Archive,
        Archive.distribution == distribution,
        Archive.purpose == purpose).any()
    if archive is not None:
        return archive
    return factory.makeArchive(distribution=distribution, purpose=purpose)


def make_spph(factory, distroseries=None, archive_purpose=None,
              pocket=PackagePublishingPocket.RELEASE, status=None,
              sourcepackagerelease=None):
    if distroseries is None:
        distroseries = factory.makeDistroSeries()

    if archive_purpose is None:
        archive = None
    else:
        archive = get_archive(
            factory, distroseries.distribution, archive_purpose)

    return factory.makeSourcePackagePublishingHistory(
        pocket=pocket, distroseries=distroseries, archive=archive,
        status=status, sourcepackagerelease=sourcepackagerelease)


class TestFindLatestSourcePackageReleases(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def makeSPPH(self, **kwargs):
        return make_spph(self.factory, **kwargs)

    def getExpectedResultFor(self, spph):
        spr = spph.sourcepackagerelease
        return (spr.sourcepackagenameID, spr.id, spr.version)

    def test_baseline(self):
        distroseries = self.factory.makeDistroSeries()
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertIsInstance(query, basestring)

    def test_finds_nothing_for_empty_distroseries(self):
        distroseries = self.factory.makeDistroSeries()
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual([], Store.of(distroseries).execute(query))

    def test_finds_published_sourcepackagerelease(self):
        spph = self.makeSPPH()
        query = compose_sql_find_latest_source_package_releases(
            spph.distroseries)
        self.assertEqual(1, Store.of(spph).execute(query).rowcount)

    def test_selects_sourcepackagename_sourcepackagerelease_version(self):
        spph = self.makeSPPH()
        spr = spph.sourcepackagerelease
        query = compose_sql_find_latest_source_package_releases(
            spph.distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(spph)], Store.of(spph).execute(query))

    def test_does_not_find_publication_from_other_series(self):
        spph = self.makeSPPH()
        query = compose_sql_find_latest_source_package_releases(
            self.factory.makeDistroSeries())
        self.assertEqual(0, Store.of(spph).execute(query).rowcount)

    def test_does_not_find_publication_outside_primary_archive(self):
        distroseries = self.factory.makeDistroSeries()
        spphs = dict(
            (purpose, self.makeSPPH(
                distroseries=distroseries, archive_purpose=purpose))
            for purpose in ArchivePurpose.items)
        primary_spr = spphs[ArchivePurpose.PRIMARY]
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(spphs[ArchivePurpose.PRIMARY])],
            Store.of(distroseries).execute(query))

    def test_does_not_find_publication_outside_release_pocket(self):
        distroseries = self.factory.makeDistroSeries()
        spphs = dict(
            (pocket, self.makeSPPH(distroseries=distroseries, pocket=pocket))
            for pocket in PackagePublishingPocket.items)
        release_spph = spphs[PackagePublishingPocket.RELEASE]
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(release_spph)],
            Store.of(distroseries).execute(query))

    def test_finds_active_publication(self):
        distroseries = self.factory.makeDistroSeries()
        spphs = dict(
            (status, self.makeSPPH(distroseries=distroseries, status=status))
            for status in active_publishing_status)
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(spph) for spph in spphs.itervalues()],
            Store.of(distroseries).execute(query))

    def test_does_not_find_inactive_publication(self):
        distroseries = self.factory.makeDistroSeries()
        spphs = dict(
            (status, self.makeSPPH(distroseries=distroseries, status=status))
            for status in inactive_publishing_status)
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual([], Store.of(distroseries).execute(query))

    def test_finds_only_latest_publication_for_release(self):
        distroseries = self.factory.makeDistroSeries()
        spr = self.factory.makeSourcePackageRelease(distroseries=distroseries)
        spphs = [
            self.makeSPPH(distroseries=distroseries, sourcepackagerelease=spr)
            for counter in xrange(5)]
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(spphs[-1])],
            Store.of(distroseries).execute(query))

    def test_finds_only_last_published_release_for_package(self):
        distroseries = self.factory.makeDistroSeries()
        spn = self.factory.makeSourcePackageName()
        sprs = [
            self.factory.makeSourcePackageRelease(
                sourcepackagename=spn, distroseries=distroseries)
            for counter in xrange(5)]
        spphs = [
            self.makeSPPH(distroseries=distroseries, sourcepackagerelease=spr)
            for spr in reversed(sprs)]
        query = compose_sql_find_latest_source_package_releases(distroseries)
        self.assertContentEqual(
            [self.getExpectedResultFor(spphs[-1])],
            Store.of(distroseries).execute(query))


class TestFindDifferences(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def makeSPPH(self, **kwargs):
        return make_spph(self.factory, **kwargs)

    def makeDerivedDistroSeries(self):
        return self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())

    def test_baseline(self):
        query = compose_sql_find_differences(self.makeDerivedDistroSeries())
        self.assertIsInstance(query, basestring)

    def test_finds_nothing_for_empty_distroseries(self):
        distroseries = self.makeDerivedDistroSeries()
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual([], Store.of(distroseries).execute(query))

    def test_does_not_find_grandparents_packages(self):
        parent = self.makeDerivedDistroSeries()
        distroseries = self.factory.makeDistroSeries(parent_series=parent)
        self.makeSPPH(distroseries=parent.parent_series)
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual([], Store.of(distroseries).execute(query))

    def test_does_not_find_identical_releases(self):
        distroseries = self.makeDerivedDistroSeries()
        spr = self.factory.makeSourcePackageRelease()
        self.makeSPPH(
            distroseries=distroseries.parent_series, sourcepackagerelease=spr)
        self.makeSPPH(
            distroseries=distroseries, sourcepackagerelease=spr)
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual([], Store.of(distroseries).execute(query))

    def test_finds_release_missing_in_derived_series(self):
        distroseries = self.makeDerivedDistroSeries()
        spph = self.makeSPPH(distroseries=distroseries.parent_series)
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual(
            [(
                spph.sourcepackagerelease.sourcepackagenameID,
                None,
                spph.sourcepackagerelease.version,
            )],
            Store.of(distroseries).execute(query))

    def test_finds_release_unique_to_derived_series(self):
        distroseries = self.makeDerivedDistroSeries()
        spph = self.makeSPPH(distroseries=distroseries)
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual(
            [(
                spph.sourcepackagerelease.sourcepackagenameID,
                spph.sourcepackagerelease.version,
                None,
            )],
            Store.of(distroseries).execute(query))

    def test_does_not_conflate_releases_of_different_packages(self):
        distroseries = self.makeDerivedDistroSeries()
        parent_spph = self.makeSPPH(distroseries=distroseries.parent_series)
        derived_spph = self.makeSPPH(distroseries=distroseries)
        query = compose_sql_find_differences(distroseries)
        self.assertEqual(2, Store.of(distroseries).execute(query).rowcount)
        self.assertContentEqual([(
                parent_spph.sourcepackagerelease.sourcepackagenameID,
                None,
                parent_spph.sourcepackagerelease.version,
            ), (
                derived_spph.sourcepackagerelease.sourcepackagenameID,
                derived_spph.sourcepackagerelease.version,
                None,
            )],
            Store.of(distroseries).execute(query))

    def test_finds_different_releases_of_same_package(self):
        distroseries = self.makeDerivedDistroSeries()
        parent_series = distroseries.parent_series
        spn = self.factory.makeSourcePackageName()
        parent_spph = self.makeSPPH(
            distroseries=parent_series,
            sourcepackagerelease=self.factory.makeSourcePackageRelease(
                distroseries=parent_series, sourcepackagename=spn))
        derived_spph = self.makeSPPH(
            distroseries=distroseries,
            sourcepackagerelease=self.factory.makeSourcePackageRelease(
                distroseries=distroseries, sourcepackagename=spn))
        query = compose_sql_find_differences(distroseries)
        self.assertContentEqual(
            [(
                parent_spph.sourcepackagerelease.sourcepackagenameID,
                derived_spph.sourcepackagerelease.version,
                parent_spph.sourcepackagerelease.version,
            )],
            Store.of(distroseries).execute(query))

    def test_finds_newer_release_even_when_same_release_also_exists(self):
        derived_series = self.makeDerivedDistroSeries()
        parent_series = derived_series.parent_series
        spn = self.factory.makeSourcePackageName()
        shared_spr = self.factory.makeSourcePackageRelease(
            distroseries=parent_series, sourcepackagename=spn)
        parent_spph = self.makeSPPH(
            distroseries=parent_series,
            sourcepackagerelease=shared_spr)
        derived_spph = self.makeSPPH(
            distroseries=derived_series,
            sourcepackagerelease=shared_spr)
        newer_spr = self.factory.makeSourcePackageRelease(
            distroseries=derived_series, sourcepackagename=spn)
        self.makeSPPH(
            distroseries=derived_series, sourcepackagerelease=newer_spr)
        query = compose_sql_find_differences(derived_series)
        self.assertContentEqual(
            [(
                parent_spph.sourcepackagerelease.sourcepackagenameID,
                newer_spr.version,
                shared_spr.version,
            )],
            Store.of(derived_series).execute(query))


class TestDifferenceTypeExpression(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def selectDifferenceType(self, parent_version=None, derived_version=None):
        query = """
            SELECT %s FROM (
                SELECT %s AS source_version, %s AS parent_source_version
            ) AS input""" % (
            compose_sql_difference_type(),
            quote(derived_version),
            quote(parent_version),
            )
        cur = cursor()
        cur.execute(query)
        return cur.fetchall()

    def test_baseline(self):
        query = compose_sql_difference_type()
        self.assertIsInstance(query, basestring)

    def test_no_parent_version_means_unique_to_derived_series(self):
        expected = DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES
        self.assertEqual(
            [(expected.value, )],
            self.selectDifferenceType(derived_version=1))

    def test_no_derived_version_means_missing_in_derived_series(self):
        expected = DistroSeriesDifferenceType.MISSING_FROM_DERIVED_SERIES
        self.assertEqual(
            [(expected.value, )],
            self.selectDifferenceType(parent_version=1))

    def test_two_versions_means_different_versions(self):
        expected = DistroSeriesDifferenceType.DIFFERENT_VERSIONS
        self.assertEqual(
            [(expected.value, )],
            self.selectDifferenceType(parent_version=1, derived_version=2))


class TestFindDerivedSeries(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_does_not_find_underived_distroseries(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertNotIn(distroseries, find_derived_series())

    def test_finds_derived_distroseries(self):
        distroseries = self.factory.makeDistroSeries(
            parent_series=self.factory.makeDistroSeries())
        self.assertIn(distroseries, find_derived_series())

    def test_ignores_parent_within_same_distro(self):
        parent_series = self.factory.makeDistroSeries()
        derived_series = self.factory.makeDistroSeries(
            distribution=parent_series.distribution,
            parent_series=parent_series)
        self.assertNotIn(derived_series, find_derived_series())


class TestComposePopulateDistroSeriesDiff(TestCaseWithFactory):

# XXX: Test!
    layer = ZopelessDatabaseLayer


class TestPopulateDistroSeriesDiff(TestCaseWithFactory):

# XXX: Test!
    layer = ZopelessDatabaseLayer


class TestPopulateDistroSeriesDiffScript(TestCaseWithFactory):

# XXX: Test!
    layer = DatabaseFunctionalLayer
