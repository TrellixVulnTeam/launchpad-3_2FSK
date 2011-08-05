# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for adapters."""

__metaclass__ = type

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.registry.adapters import (
    distroseries_to_distribution,
    productseries_to_product,
    sourcepackage_to_distribution,
    )
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.product import IProduct
from lp.testing import TestCaseWithFactory


class TestAdapters(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_sourcepackage_to_distribution_dsp(self):
        # A distribution can be retrieved from a dsp.
        package = self.factory.makeDistributionSourcePackage()
        distribution = sourcepackage_to_distribution(package)
        self.assertTrue(IDistribution.providedBy(distribution))
        self.assertEqual(package.distribution, distribution)
        self.assertEqual(package.distribution, IDistribution(package))

    def test_sourcepackage_to_distribution_sp(self):
        # A distribution can be retrieved from a source package.
        package = self.factory.makeSourcePackage()
        distribution = sourcepackage_to_distribution(package)
        self.assertTrue(IDistribution.providedBy(distribution))
        self.assertEqual(package.distroseries.distribution, distribution)
        self.assertEqual(
            package.distroseries.distribution, IDistribution(package))

    def test_distroseries_to_distribution(self):
        # distroseries_to_distribution() returns an IDistribution given an
        # IDistroSeries.
        distro_series = self.factory.makeDistroSeries()
        distribution = distroseries_to_distribution(distro_series)
        self.assertTrue(IDistribution.providedBy(distribution))
        self.assertEqual(distro_series.distribution, distribution)
        self.assertEqual(
            distro_series.distribution, IDistribution(distro_series))

    def test_productseries_to_product(self):
        # productseries_to_product() returns an IProduct given an
        # IProductSeries.
        product_series = self.factory.makeProductSeries()
        product = productseries_to_product(product_series)
        self.assertTrue(IProduct.providedBy(product))
        self.assertEqual(product_series.product, product)
