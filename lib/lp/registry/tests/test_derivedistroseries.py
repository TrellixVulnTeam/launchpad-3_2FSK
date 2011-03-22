# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test initialising a distroseries using
IDistroSeries.deriveDistroSeries."""

__metaclass__ = type

from canonical.testing.layers import LaunchpadFunctionalLayer
from lp.registry.interfaces.distroseries import DerivationError
from lp.soyuz.interfaces.distributionjob import (
    IInitialiseDistroSeriesJobSource,
    )
from lp.testing import (
    login,
    logout,
    TestCaseWithFactory,
    )
from lp.testing.sampledata import ADMIN_EMAIL
from zope.component import getUtility
from zope.security.interfaces import Unauthorized


class TestDeriveDistroSeries(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestDeriveDistroSeries, self).setUp()
        self.soyuz = self.factory.makeTeam(name='soyuz-team')
        self.parent = self.factory.makeDistroSeries()
        self.child = self.factory.makeDistroSeries(
            parent_series=self.parent)

    def test_no_permission_to_call(self):
        login(ADMIN_EMAIL)
        person = self.factory.makePerson()
        logout()
        self.assertRaises(
            Unauthorized, self.parent.deriveDistroSeries, person,
            self.child.name)

    def test_no_distroseries_and_no_arguments(self):
        """Test that calling deriveDistroSeries() when the distroseries
        doesn't exist, and not enough arguments are specified that the
        function errors."""
        self.assertRaisesWithContent(
            DerivationError,
            'Display Name needs to be set when creating a distroseries.',
            self.parent.deriveDistroSeries, self.soyuz.teamowner,
            'newdistro')

    def test_parent_is_not_self(self):
        other = self.factory.makeDistroSeries()
        self.assertRaisesWithContent(
            DerivationError,
            "DistroSeries %s parent series isn't %s" % (
                self.child.name, other.name),
            other.deriveDistroSeries, self.soyuz.teamowner,
            self.child.name, self.child.distribution)

    def test_create_new_distroseries(self):
        self.parent.deriveDistroSeries(
            self.soyuz.teamowner, self.child.name, self.child.distribution)
        [job] = list(
            getUtility(IInitialiseDistroSeriesJobSource).iterReady())
        self.assertEqual(job.distroseries, self.child)

    def test_create_fully_new_distroseries(self):
        self.parent.deriveDistroSeries(
            self.soyuz.teamowner, 'deribuntu', displayname='Deribuntu',
            title='The Deribuntu', summary='Deribuntu',
            description='Deribuntu is great', version='11.11')
        [job] = list(
            getUtility(IInitialiseDistroSeriesJobSource).iterReady())
        self.assertEqual(job.distroseries.name, 'deribuntu')

    def test_create_initialises_correct_distribution(self):
        # Make two distroseries with the same name and different
        # distributions to check that the right distroseries is initialised.
        self.factory.makeDistroSeries(name='bar')
        bar = self.factory.makeDistroSeries(
            name='bar', parent_series=self.parent)
        self.parent.deriveDistroSeries(
            self.soyuz.teamowner, 'bar', distribution=bar.parent,
            displayname='Bar', title='The Bar', summary='Bar',
            description='Bar is good', version='1.0')
        [job] = list(
            getUtility(IInitialiseDistroSeriesJobSource).iterReady())
        self.assertEqual('bar', job.distroseries.name)
        self.assertEqual(bar.parent.name, job.distribution.name)
