# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Distribution."""

__metaclass__ = type

from lazr.lifecycle.snapshot import Snapshot
import soupmatchers
from testtools import ExpectedException
from testtools.matchers import (
    MatchesAny,
    Not,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.webapp import canonical_url
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.app.errors import NotFoundError
from lp.registry.errors import NoSuchDistroSeries
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.tests.test_distroseries import (
    TestDistroSeriesCurrentSourceReleases,
    )
from lp.services.propertycache import get_property_cache
from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease,
    )
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.views import create_initialized_view


class TestDistribution(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_distribution_repr_ansii(self):
        # Verify that ANSI displayname is ascii safe.
        distro = self.factory.makeDistribution(
            name="distro", displayname=u'\xdc-distro')
        ignore, displayname, name = repr(distro).rsplit(' ', 2)
        self.assertEqual("'\\xdc-distro'", displayname)
        self.assertEqual('(distro)>', name)

    def test_distribution_repr_unicode(self):
        # Verify that Unicode displayname is ascii safe.
        distro = self.factory.makeDistribution(
            name="distro", displayname=u'\u0170-distro')
        ignore, displayname, name = repr(distro).rsplit(' ', 2)
        self.assertEqual("'\\u0170-distro'", displayname)

    def test_guessPublishedSourcePackageName_no_distro_series(self):
        # Distribution without a series raises NotFoundError
        distro = self.factory.makeDistribution()
        with ExpectedException(NotFoundError, '.*has no series.*'):
            distro.guessPublishedSourcePackageName('package')

    def test_guessPublishedSourcePackageName_invalid_name(self):
        # Invalid name raises a NotFoundError
        distro = self.factory.makeDistribution()
        with ExpectedException(NotFoundError, "'Invalid package name.*"):
            distro.guessPublishedSourcePackageName('a*package')

    def test_guessPublishedSourcePackageName_nothing_published(self):
        distroseries = self.factory.makeDistroSeries()
        with ExpectedException(NotFoundError, "'Unknown package:.*"):
            distroseries.distribution.guessPublishedSourcePackageName(
                'a-package')

    def test_guessPublishedSourcePackageName_sourcepackage_name(self):
        my_package_name = self.factory.makeSourcePackageName('my-package')
        distroseries = self.factory.makeDistroSeries()
        spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=my_package_name)
        self.assertEquals(
            my_package_name,
            distroseries.distribution.guessPublishedSourcePackageName(
                'my-package'))

    def test_guessPublishedSourcePackageName_binarypackage_name(self):
        distroseries = self.factory.makeDistroSeries()
        my_package_name = self.factory.makeSourcePackageName(
            'my-package')
        spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=my_package_name)
        binary_package_name = self.factory.makeBinaryPackageName(
            'binary-package')
        binary_package_build = self.factory.makeBinaryPackageBuild(
            source_package_release=spph.sourcepackagerelease)
        binary_package_release = self.factory.makeBinaryPackageRelease(
            build=binary_package_build, binarypackagename=binary_package_name)
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=distroseries.main_archive,
            binarypackagerelease=binary_package_release)
        self.assertEquals(
            my_package_name,
            distroseries.distribution.guessPublishedSourcePackageName(
                'binary-package'))

    def test_guessPublishedSourcePackageName_exlude_ppa(self):
        # Package published in PPAs are not considered to be part of the
        # distribution.
        my_package_name = self.factory.makeSourcePackageName('my-package')
        distroseries = self.factory.makeUbuntuDistroSeries()
        ppa_archive = self.factory.makeArchive()
        spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=my_package_name,
            archive=ppa_archive)
        with ExpectedException(NotFoundError, ".*not published in.*"):
            distroseries.distribution.guessPublishedSourcePackageName(
                'my-package')

    def test_guessPublishedSourcePackageName_exlude_other_distro(self):
        # Published source package are only found in the distro
        # in which they were published.
        my_package_name = self.factory.makeSourcePackageName('my-package')
        distroseries1 = self.factory.makeDistroSeries()
        distroseries2 = self.factory.makeDistroSeries()
        spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries1, sourcepackagename=my_package_name)
        self.assertEquals(
            my_package_name,
            distroseries1.distribution.guessPublishedSourcePackageName(
                'my-package'))
        with ExpectedException(NotFoundError, ".*not published in.*"):
            distroseries2.distribution.guessPublishedSourcePackageName(
                'my-package')

    def test_guessPublishedSourcePackageName_looks_for_source_first(self):
        # If both a binary and source package name shares the same name,
        # the source package will be returned (and the one from the unrelated
        # binary).
        distroseries = self.factory.makeDistroSeries()
        my_package_name = self.factory.makeSourcePackageName(
            'my-package')
        other_name = self.factory.makeSourcePackageName(
            'other-package')
        my_spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=my_package_name)
        other_spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=other_name)
        binary_package_name = self.factory.makeBinaryPackageName(
            'my-package')
        binary_package_build = self.factory.makeBinaryPackageBuild(
            source_package_release=other_spph.sourcepackagerelease)
        binary_package_release = self.factory.makeBinaryPackageRelease(
            build=binary_package_build, binarypackagename=binary_package_name)
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=distroseries.main_archive,
            binarypackagerelease=binary_package_release)
        self.assertEquals(
            my_package_name,
            distroseries.distribution.guessPublishedSourcePackageName(
                'my-package'))

    def test_guessPublishedSourcePackageName_uses_latest(self):
        # If multiple binaries match, it will return the source of the latest
        # one published.
        distroseries = self.factory.makeDistroSeries()
        old_src_name = self.factory.makeSourcePackageName(
            'old-source-name')
        new_src_name = self.factory.makeSourcePackageName(
            'new-source-name')
        old_spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=old_src_name)
        new_spph = self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, sourcepackagename=new_src_name)
        binary_package_name = self.factory.makeBinaryPackageName(
            'my-package')
        old_package_build = self.factory.makeBinaryPackageBuild(
            source_package_release=old_spph.sourcepackagerelease)
        old_package_release = self.factory.makeBinaryPackageRelease(
            build=old_package_build, binarypackagename=binary_package_name)
        self.factory.makeBinaryPackagePublishingHistory(
            archive=distroseries.main_archive,
            binarypackagerelease=old_package_release)
        new_package_build = self.factory.makeBinaryPackageBuild(
            source_package_release=new_spph.sourcepackagerelease)
        new_package_release = self.factory.makeBinaryPackageRelease(
            build=new_package_build, binarypackagename=binary_package_name)
        self.factory.makeBinaryPackagePublishingHistory(
            archive=distroseries.main_archive,
            binarypackagerelease=new_package_release)
        self.assertEquals(
            new_src_name,
            distroseries.distribution.guessPublishedSourcePackageName(
                'my-package'))


class TestDistributionCurrentSourceReleases(
    TestDistroSeriesCurrentSourceReleases):
    """Test for Distribution.getCurrentSourceReleases().

    This works in the same way as
    DistroSeries.getCurrentSourceReleases() works, except that we look
    for the latest published source across multiple distro series.
    """

    layer = LaunchpadFunctionalLayer
    release_interface = IDistributionSourcePackageRelease

    @property
    def test_target(self):
        return self.distribution

    def test_which_distroseries_does_not_matter(self):
        # When checking for the current release, we only care about the
        # version numbers. We don't care whether the version is
        # published in a earlier or later series.
        self.current_series = self.factory.makeDistroRelease(
            self.distribution, '1.0', status=SeriesStatus.CURRENT)
        self.publisher.getPubSource(
            version='0.9', distroseries=self.current_series)
        self.publisher.getPubSource(
            version='1.0', distroseries=self.development_series)
        self.assertCurrentVersion('1.0')

        self.publisher.getPubSource(
            version='1.1', distroseries=self.current_series)
        self.assertCurrentVersion('1.1')

    def test_distribution_series_cache(self):
        distribution = removeSecurityProxy(
            self.factory.makeDistribution('foo'))

        cache = get_property_cache(distribution)

        # Not yet cached.
        self.assertNotIn("series", cache)

        # Now cached.
        series = distribution.series
        self.assertIs(series, cache.series)

        # Cache cleared.
        distribution.newSeries(
            name='bar', displayname='Bar', title='Bar', summary='',
            description='', version='1', previous_series=None,
            registrant=self.factory.makePerson())
        self.assertNotIn("series", cache)

        # New cached value.
        series = distribution.series
        self.assertEqual(1, len(series))
        self.assertIs(series, cache.series)


class SeriesByStatusTests(TestCaseWithFactory):
    """Test IDistribution.getSeriesByStatus().
    """

    layer = LaunchpadFunctionalLayer

    def test_get_none(self):
        distro = self.factory.makeDistribution()
        self.assertEquals([],
            list(distro.getSeriesByStatus(SeriesStatus.FROZEN)))

    def test_get_current(self):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro,
            status=SeriesStatus.CURRENT)
        self.assertEquals([series],
            list(distro.getSeriesByStatus(SeriesStatus.CURRENT)))


class SeriesTests(TestCaseWithFactory):
    """Test IDistribution.getSeries().
    """

    layer = LaunchpadFunctionalLayer

    def test_get_none(self):
        distro = self.factory.makeDistribution()
        self.assertRaises(NoSuchDistroSeries, distro.getSeries, "astronomy")

    def test_get_by_name(self):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro,
            name="dappere")
        self.assertEquals(series, distro.getSeries("dappere"))

    def test_get_by_version(self):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro,
            name="dappere", version="42.6")
        self.assertEquals(series, distro.getSeries("42.6"))


class SeriesTests(TestCaseWithFactory):
    """Test IDistribution.derivatives.
    """

    layer = LaunchpadFunctionalLayer

    def test_derivatives(self):
        distro1 = self.factory.makeDistribution()
        distro2 = self.factory.makeDistribution()
        previous_series = self.factory.makeDistroRelease(
            distribution=distro1)
        series = self.factory.makeDistroRelease(
            distribution=distro2,
            previous_series=previous_series)
        self.assertContentEqual(
            [series], distro1.derivatives)


class DistroSnapshotTestCase(TestCaseWithFactory):
    """A TestCase for distribution snapshots."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(DistroSnapshotTestCase, self).setUp()
        self.distribution = self.factory.makeDistribution(name="boobuntu")

    def test_snapshot(self):
        """Snapshots of products should not include marked attribues.

        Wrap an export with 'doNotSnapshot' to force the snapshot to not
        include that attribute.
        """
        snapshot = Snapshot(self.distribution, providing=IDistribution)
        omitted = [
            'archive_mirrors',
            'cdimage_mirrors',
            'series',
            'all_distro_archives',
            ]
        for attribute in omitted:
            self.assertFalse(
                hasattr(snapshot, attribute),
                "Snapshot should not include %s." % attribute)


class TestDistributionPage(TestCaseWithFactory):
    """A TestCase for the distribution page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionPage, self).setUp('foo.bar@canonical.com')
        self.distro = self.factory.makeDistribution(
            name="distro", displayname=u'distro')
        self.admin = getUtility(IPersonSet).getByEmail(
            'admin@canonical.com')
        self.simple_user = self.factory.makePerson()

    def test_distributionpage_addseries_link(self):
        """ Verify that an admin sees the +addseries link."""
        login_person(self.admin)
        view = create_initialized_view(
            self.distro, '+index', principal=self.admin)
        series_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'),
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'),
            )
        self.assertThat(view.render(), series_matches)

    def test_distributionpage_addseries_link_noadmin(self):
        """Verify that a non-admin does not see the +addseries link
        nor the series header (since there is no series yet).
        """
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, '+index', principal=self.simple_user)
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'))
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'))
        self.assertThat(
            view.render(),
            Not(MatchesAny(add_series_match, series_header_match)))

    def test_distributionpage_series_list_noadmin(self):
        """Verify that a non-admin does see the series list
        when there is a series.
        """
        self.factory.makeDistroSeries(distribution=self.distro,
            status=SeriesStatus.CURRENT)
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, '+index', principal=self.simple_user)
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'))
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'))
        self.assertThat(view.render(), series_header_match)
        self.assertThat(view.render(), Not(add_series_match))


class DistroRegistrantTestCase(TestCaseWithFactory):
    """A TestCase for registrants and owners of a distribution.

    The registrant is the creator of the distribution (read-only field).
    The owner is really the maintainer.
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(DistroRegistrantTestCase, self).setUp()
        self.owner = self.factory.makePerson()
        self.registrant = self.factory.makePerson()

    def test_distro_registrant_owner_differ(self):
        distribution = self.factory.makeDistribution(
            name="boobuntu", owner=self.owner, registrant=self.registrant)
        self.assertNotEqual(distribution.owner, distribution.registrant)
        self.assertEqual(distribution.owner, self.owner)
        self.assertEqual(distribution.registrant, self.registrant)
