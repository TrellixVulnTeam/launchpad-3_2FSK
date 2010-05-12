# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Distribution."""

__metaclass__ = type

import unittest

from zope.security.proxy import removeSecurityProxy

from lp.registry.tests.test_distroseries import (
    TestDistroSeriesCurrentSourceReleases)
from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease)
from lp.registry.interfaces.series import SeriesStatus
from lp.testing import TestCaseWithFactory
from canonical.testing.layers import (
    DatabaseFunctionalLayer, LaunchpadFunctionalLayer)


class TestDistribution(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistribution, self).setUp('foo.bar@canonical.com')

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

        # Not yet cached.
        missing = object()
        cached_series = getattr(distribution, '_cached_series', missing)
        self.assertEqual(missing, cached_series)

        # Now cached.
        series = distribution.series
        self.assertTrue(series is distribution._cached_series)

        # Cache cleared.
        distribution.newSeries(
            name='bar', displayname='Bar', title='Bar', summary='',
            description='', version='1', parent_series=None,
            owner=self.factory.makePerson())
        cached_series = getattr(distribution, '_cached_series', missing)
        self.assertEqual(missing, cached_series)

        # New cached value.
        series = distribution.series
        self.assertEqual(1, len(series))
        self.assertTrue(series is distribution._cached_series)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
