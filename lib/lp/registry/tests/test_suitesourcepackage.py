# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Tests for ISuiteSourcePackage."""

__metaclass__ = type

import unittest

from canonical.launchpad.interfaces.publishing import PackagePublishingPocket
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.testing.layers import DatabaseFunctionalLayer

from lp.registry.model.suitesourcepackage import SuiteSourcePackage


class TestSuiteSourcePackage(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def makeSuiteSourcePackage(self):
        distroseries = self.factory.makeDistroRelease()
        pocket = PackagePublishingPocket.RELEASE
        sourcepackagename = self.factory.makeSourcePackageName()
        return SuiteSourcePackage(distroseries, pocket, sourcepackagename)

    def test_construction(self):
        # A SuiteSourcePackage is constructed from an `IDistroSeries`, a
        # `PackagePublishingPocket` enum and an `ISourcePackageName`. These
        # are all provided as attributes.
        distroseries = self.factory.makeDistroRelease()
        pocket = PackagePublishingPocket.RELEASE
        sourcepackagename = self.factory.makeSourcePackageName()
        ssp = SuiteSourcePackage(distroseries, pocket, sourcepackagename)
        self.assertEqual(distroseries, ssp.distroseries)
        self.assertEqual(pocket, ssp.pocket)
        self.assertEqual(sourcepackagename, ssp.sourcepackagename)

    def test_sourcepackage(self):
        # A SuiteSourcePackage has a `sourcepackage` property, which is an
        # ISourcePackage that represents the sourcepackagename, distroseries
        # pair.
        ssp = self.makeSuiteSourcePackage()
        package = ssp.distroseries.getSourcePackage(ssp.sourcepackagename)
        self.assertEqual(package, ssp.sourcepackage)

    def test_suite(self):
        # The `suite` property of a `SuiteSourcePackage` is a string of the
        # distro series name followed by the pocket suffix.
        ssp = self.makeSuiteSourcePackage()
        self.assertEqual(ssp.distroseries.getSuite(ssp.pocket), ssp.suite)

    def test_distribution(self):
        # The `distribution` property of a `SuiteSourcePackage` is the
        # distribution that the object's distroseries is associated with.
        ssp = self.makeSuiteSourcePackage()
        self.assertEqual(ssp.distroseries.distribution, ssp.distribution)

    def test_path(self):
        # The `path` property of a `SuiteSourcePackage` is a string that has
        # the distribution name followed by the suite followed by the source
        # package name, separated by slashes.
        ssp = self.makeSuiteSourcePackage()
        self.assertEqual(
            '%s/%s/%s' % (
                ssp.distribution.name, ssp.suite, ssp.sourcepackagename.name),
            ssp.path)

    def test_repr(self):
        # The repr of a `SuiteSourcePackage` includes the path and clearly
        # refers to the type of the object.
        ssp = self.makeSuiteSourcePackage()
        self.assertEqual('<SuiteSourcePackage %s>' % ssp.path, repr(ssp))

    def test_equality(self):
        ssp1 = self.makeSuiteSourcePackage()
        ssp2 = SuiteSourcePackage(
            ssp1.distroseries, ssp1.pocket, ssp1.sourcepackagename)
        self.assertEqual(ssp1, ssp2)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
