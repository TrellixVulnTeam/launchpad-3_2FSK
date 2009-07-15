# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Implementation of `ICanHasLinkedBranch`."""

__metaclass__ = type
# Don't export anything -- anything you need from this module you can get by
# adapting another object.
__all__ = []

from zope.component import adapts
from zope.interface import implements

from lp.code.interfaces.linkedbranch import ICanHasLinkedBranch
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage)
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.suitesourcepackage import ISuiteSourcePackage
from lp.soyuz.interfaces.publishing import PackagePublishingPocket


class ProductSeriesLinkedBranch:
    """Implement a linked branch for a product series."""

    adapts(IProductSeries)
    implements(ICanHasLinkedBranch)

    def __init__(self, product_series):
        self.product_series = product_series

    @property
    def branch(self):
        """See `ICanHasLinkedBranch`."""
        return self.product_series.branch


class ProductLinkedBranch:
    """Implement a linked branch for a product."""

    adapts(IProduct)
    implements(ICanHasLinkedBranch)

    def __init__(self, product):
        self.product = product

    @property
    def branch(self):
        """See `ICanHasLinkedBranch`."""
        return ICanHasLinkedBranch(self.product.development_focus).branch


class PackageLinkedBranch:
    """Implement a linked branch for a source package pocket."""

    adapts(ISuiteSourcePackage)
    implements(ICanHasLinkedBranch)

    def __init__(self, suite_sourcepackage):
        self.suite_sourcepackage = suite_sourcepackage

    @property
    def branch(self):
        """See `ICanHasLinkedBranch`."""
        package = self.suite_sourcepackage.sourcepackage
        pocket = self.suite_sourcepackage.pocket
        return package.getBranch(pocket)


class DistributionPackageLinkedBranch:
    """Implement a linked branch for an `IDistributionSourcePackage`."""

    adapts(IDistributionSourcePackage)
    implements(ICanHasLinkedBranch)

    def __init__(self, distribution_sourcepackage):
        self._distribution_sourcepackage = distribution_sourcepackage

    @property
    def branch(self):
        """See `ICanHasLinkedBranch`."""
        development_package = (
            self._distribution_sourcepackage.development_version)
        suite_sourcepackage = development_package.getSuiteSourcePackage(
            PackagePublishingPocket.RELEASE)
        return ICanHasLinkedBranch(suite_sourcepackage).branch
