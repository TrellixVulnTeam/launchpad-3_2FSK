# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for DistroSeriesParent model class."""

__metaclass__ = type

from testtools.matchers import (
    Equals,
    MatchesStructure,
    )

from zope.component import getUtility
from zope.interface.verify import verifyObject
from zope.security.interfaces import Unauthorized

from canonical.launchpad.ftests import login
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    ZopelessDatabaseLayer,
    )
from lp.registry.interfaces.distroseriesparent import (
    IDistroSeriesParent,
    IDistroSeriesParentSet,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.sampledata import LAUNCHPAD_ADMIN


class TestDistroSeriesParent(TestCaseWithFactory):
    """Test the `DistroSeriesParent` model."""
    layer = ZopelessDatabaseLayer

    def test_verify_interface(self):
        # Test the interface for the model.
        dsp = self.factory.makeDistroSeriesParent()
        verified = verifyObject(IDistroSeriesParent, dsp)
        self.assertTrue(verified)

    def test_properties(self):
        # Test the model properties.
        parent_series = self.factory.makeDistroSeries()
        derived_series = self.factory.makeDistroSeries()
        dsp = self.factory.makeDistroSeriesParent(
            derived_series=derived_series,
            parent_series=parent_series,
            initialized=True
            )

        self.assertThat(
            dsp,
            MatchesStructure(
                derived_series=Equals(derived_series),
                parent_series=Equals(parent_series),
                initialized=Equals(True)
                ))

    def test_getByDerivedSeries(self):
        parent_series = self.factory.makeDistroSeries()
        derived_series = self.factory.makeDistroSeries()
        self.factory.makeDistroSeriesParent(
            derived_series, parent_series)
        results = getUtility(IDistroSeriesParentSet).getByDerivedSeries(
            derived_series)
        self.assertEqual(1, results.count())
        self.assertEqual(parent_series, results[0].parent_series)

        # Making a second parent should add it to the results.
        self.factory.makeDistroSeriesParent(
            derived_series, self.factory.makeDistroSeries())
        results = getUtility(IDistroSeriesParentSet).getByDerivedSeries(
            derived_series)
        self.assertEqual(2, results.count())

    def test_getByParentSeries(self):
        parent_series = self.factory.makeDistroSeries()
        derived_series = self.factory.makeDistroSeries()
        dsp = self.factory.makeDistroSeriesParent(
            derived_series, parent_series)
        results = getUtility(IDistroSeriesParentSet).getByParentSeries(
            parent_series)
        self.assertEqual(1, results.count())
        self.assertEqual(derived_series, results[0].derived_series)

        # Making a second child should add it to the results.
        self.factory.makeDistroSeriesParent(
            self.factory.makeDistroSeries(), parent_series)
        results = getUtility(IDistroSeriesParentSet).getByParentSeries(
            parent_series)
        self.assertEqual(2, results.count())


class TestDistroSeriesParentSecurity(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_random_person_is_unauthorized(self):
        dsp = self.factory.makeDistroSeriesParent()
        person = self.factory.makePerson()
        with person_logged_in(person):
            self.assertRaises(
                Unauthorized,
                setattr, dsp, "derived_series", dsp.parent_series)

    def assertCanEdit(self, dsp):
        dsp.initialized = False
        self.assertEquals(False, dsp.initialized)

    def test_distroseries_drivers_can_edit(self):
        # Test that distroseries drivers can edit the data.
        dsp = self.factory.makeDistroSeriesParent()
        person = self.factory.makePerson()
        login(LAUNCHPAD_ADMIN)
        dsp.derived_series.driver = person
        with person_logged_in(person):
            self.assertCanEdit(dsp)

    def test_admins_can_edit(self):
        dsp = self.factory.makeDistroSeriesParent()
        login(LAUNCHPAD_ADMIN)
        self.assertCanEdit(dsp)

    def test_distro_owners_can_edit(self):
        dsp = self.factory.makeDistroSeriesParent()
        person = self.factory.makePerson()
        login(LAUNCHPAD_ADMIN)
        dsp.derived_series.distribution.owner = person
        with person_logged_in(person):
            self.assertCanEdit(dsp)
