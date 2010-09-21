# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

from canonical.testing import DatabaseFunctionalLayer

from lp.app.enums import ServiceUsage
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )


class UsageEnumsMixin(object):
    """Base class for testing the UsageEnums on their pillars."""

    def setUp(self):
        self.target = None

    def test_answers_usage_no_data(self):
        # By default, we don't know anything about a target
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.target.answers_usage)

    def test_answers_usage_using_bool(self):
        # If the old bool says they use Launchpad, return LAUNCHPAD
        # if the ServiceUsage is unknown.
        login_person(self.target.owner)
        self.target.official_answers = True
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            self.target.answers_usage)

    def test_answers_usage_with_enum_data(self):
        # If the enum has something other than UNKNOWN as its status,
        # use that.
        login_person(self.target.owner)
        self.target.answers_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            ServiceUsage.EXTERNAL,
            self.target.answers_usage)

    def test_answers_setter(self):
        login_person(self.target.owner)
        self.target.official_answers = True
        self.target.answers_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            False,
            self.target.official_answers)
        self.target.answers_usage = ServiceUsage.LAUNCHPAD
        self.assertEqual(
            True,
            self.target.official_answers)

    def test_codehosting_usage(self):
        # Only test get for codehosting; this has no setter because the
        # state is derived from other data.
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.target.codehosting_usage)

    def test_translations_usage_no_data(self):
        # By default, we don't know anything about a target
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.target.translations_usage)

    def test_translations_usage_using_bool(self):
        # If the old bool says they use Launchpad, return LAUNCHPAD
        # if the ServiceUsage is unknown.
        login_person(self.target.owner)
        self.target.official_rosetta = True
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            self.target.translations_usage)

    def test_translations_usage_with_enum_data(self):
        # If the enum has something other than UNKNOWN as its status,
        # use that.
        login_person(self.target.owner)
        self.target.translations_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            ServiceUsage.EXTERNAL,
            self.target.translations_usage)

    def test_translations_setter(self):
        login_person(self.target.owner)
        self.target.official_rosetta = True
        self.target.translations_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            False,
            self.target.official_rosetta)
        self.target.translations_usage = ServiceUsage.LAUNCHPAD
        self.assertEqual(
            True,
            self.target.official_rosetta)

    def test_bug_tracking_usage(self):
        # Only test get for bug_tracking; this has no setter because the
        # state is derived from other data.
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.target.bug_tracking_usage)

    def test_blueprints_usage_no_data(self):
        # By default, we don't know anything about a target
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.target.blueprints_usage)

    def test_blueprints_usage_using_bool(self):
        # If the old bool says they use Launchpad, return LAUNCHPAD
        # if the ServiceUsage is unknown.
        login_person(self.target.owner)
        self.target.official_blueprints = True
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            self.target.blueprints_usage)

    def test_blueprints_usage_with_enum_data(self):
        # If the enum has something other than UNKNOWN as its status,
        # use that.
        login_person(self.target.owner)
        self.target.blueprints_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            ServiceUsage.EXTERNAL,
            self.target.blueprints_usage)

    def test_blueprints_setter(self):
        login_person(self.target.owner)
        self.target.official_blueprints = True
        self.target.blueprints_usage = ServiceUsage.EXTERNAL
        self.assertEqual(
            False,
            self.target.official_blueprints)
        self.target.blueprints_usage = ServiceUsage.LAUNCHPAD
        self.assertEqual(
            True,
            self.target.official_blueprints)

class SeriesUsageEnumsMixin(object):
    
    def setUp(self):
        self.series = None
        self.series_pillar = None

    def _addCurrentPOTemplate(self):
        raise NotImplementedError("Child class must provide _addPOTTemplate.")

    def test_translations_usage_pillar(self):
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.series_pillar.translations_usage)
        self.assertEqual(
            ServiceUsage.UNKNOWN,
            self.series.translations_usage)

        self._addCurrentPOTemplate()
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            self.series.translations_usage)

class TestDistributionUsageEnums(TestCaseWithFactory, UsageEnumsMixin):
    """Tests the usage enums for the distribution."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionUsageEnums, self).setUp()
        self.target = self.factory.makeDistribution()

    def test_codehosting_usage(self):
        # This method must be changed for Distribution, because its
        # enum defaults to different data.
        self.assertEqual(
            ServiceUsage.NOT_APPLICABLE,
            self.target.codehosting_usage)


class TestProductUsageEnums(TestCaseWithFactory, UsageEnumsMixin):
    """Tests the usage enums for the product."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductUsageEnums, self).setUp()
        self.target = self.factory.makeProduct()

class TestProductSeriesUsageEnums(
    TestCaseWithFactory,
    SeriesUsageEnumsMixin):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductSeriesUsageEnums, self).setUp()
        self.series_pillar = self.factory.makeProduct()
        self.series = self.factory.makeProductSeries(
            product=self.series_pillar)
        login_person(self.series_pillar.owner)

    def _addCurrentPOTemplate(self):
        self.factory.makePOTemplate(productseries=self.series)
        # XXX j.c.sackett 2010-09-21 bug=605924: Right now for it to
        # be current, the series pillar must be marked as using
        # using translations.
        self.series_pillar.translations_usage = ServiceUsage.LAUNCHPAD
        

class TestDistroSeriesUsageEnums(
    TestCaseWithFactory,
    SeriesUsageEnumsMixin):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistroSeriesUsageEnums, self).setUp()
        self.series_pillar = self.factory.makeDistribution()
        self.series = self.factory.makeDistroSeries(
            distribution=self.series_pillar)
        login_person(self.series_pillar.owner)

    def _addCurrentPOTemplate(self):
        sp_name = self.factory.makeSourcePackageName()
        self.factory.makeSourcePackage(
            sourcepackagename=sp_name,
            distroseries=self.series)
        self.factory.makePOTemplate(
            distroseries=self.series,
            sourcepackagename=sp_name)

        # XXX j.c.sackett 2010-09-21 bug=605924: Right now for it to
        # be current, the series pillar must be marked as using
        # using translations.
        self.series_pillar.translations_usage = ServiceUsage.LAUNCHPAD

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
