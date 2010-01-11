# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

from zope.interface.verify import verifyObject
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.launchpad import (
    ILaunchpadCelebrities, IPersonRoles)
from lp.registry.interfaces.person import IPerson

from lp.testing import TestCaseWithFactory
from canonical.testing import ZopelessDatabaseLayer


class TestPersonRoles(TestCaseWithFactory):
    """Test IPersonRoles adapter.
     """

    layer = ZopelessDatabaseLayer

    prefix = 'in_'

    def setUp(self):
        super(TestPersonRoles, self).setUp()
        self.person = self.factory.makePerson()
        self.celebs = getUtility(ILaunchpadCelebrities)

    def test_interface(self):
        roles = IPersonRoles(self.person)
        verifyObject(IPersonRoles, roles)

    def test_person(self):
        # The person is available through the person attribute.
        roles = IPersonRoles(self.person)
        self.assertIs(self.person, roles.person)

    def _get_person_celebrities(self, is_team):
        for name in ILaunchpadCelebrities.names():
            attr = getattr(self.celebs, name)
            if IPerson.providedBy(attr) and attr.isTeam() == is_team:
                yield (name, attr)

    def test_in_teams(self):
        # Test all celebrity teams are available.
        for name, team in self._get_person_celebrities(is_team=True):
            roles_attribute = self.prefix + name
            roles = IPersonRoles(self.person)
            self.assertFalse(
                getattr(roles, roles_attribute),
                "%s should be False" % roles_attribute)

            team.addMember(self.person, team.teamowner)
            roles = IPersonRoles(self.person)
            self.assertTrue(
                getattr(roles, roles_attribute),
                "%s should be True" % roles_attribute)
            self.person.leave(team)

    def test_is_person(self):
        # All celebrity persons are available.
        for name, celeb in self._get_person_celebrities(is_team=False):
            roles_attribute = self.prefix + name
            roles = IPersonRoles(celeb)
            self.assertTrue(
                getattr(roles, roles_attribute),
                "%s should be True" % roles_attribute)

    def test_in_AttributeError(self):
        # Do not check for non-existent attributes, even if it has the
        # right prefix.
        roles = IPersonRoles(self.person)
        fake_attr = self.factory.getUniqueString()
        self.assertRaises(AttributeError, getattr, roles, fake_attr)
        fake_attr = self.factory.getUniqueString(self.prefix)
        self.assertRaises(AttributeError, getattr, roles, fake_attr)

    def test_inTeam(self):
        # The method person.inTeam is available as the inTeam attribute.
        roles = IPersonRoles(self.person)
        self.assertEquals(self.person.inTeam, roles.inTeam)

    def test_inTeam_works(self):
        # Make sure it actually works.
        team = self.factory.makeTeam(self.person)
        roles = IPersonRoles(self.person)
        self.assertTrue(roles.inTeam(team))

    def test_isOwner(self):
        # The person can be the owner of something, e.g. a product.
        product = self.factory.makeProduct(owner=self.person)
        roles = IPersonRoles(self.person)
        self.assertTrue(roles.isOwner(product))

    def test_isDriver(self):
        # The person can be the driver of something, e.g. a sprint.
        sprint = self.factory.makeSprint()
        sprint.driver = self.person
        roles = IPersonRoles(self.person)
        self.assertTrue(roles.isDriver(sprint))

    def test_isDriver_multiple_drivers(self):
        # The person can be one of multiple drivers of if a product and its
        # series each has a driver.
        productseries = self.factory.makeProductSeries()
        productseries.product.driver = self.person
        productseries.driver = self.factory.makePerson()
        roles = IPersonRoles(self.person)
        self.assertTrue(roles.isDriver(productseries))

    def test_isOneOf(self):
        # Objects may have multiple roles that a person can fulfill.
        # Specifications are such a case.
        spec = removeSecurityProxy(self.factory.makeSpecification())
        spec.owner = self.factory.makePerson()
        spec.drafter = self.factory.makePerson()
        spec.assignee = self.factory.makePerson()
        spec.approver = self.person

        roles = IPersonRoles(self.person)
        self.assertTrue(roles.isOneOf(
            spec, ['owner', 'drafter', 'assignee', 'approver']))

    def test_isOneOf_None(self):
        # Objects may have multiple roles that a person can fulfill.
        # Specifications are such a case. Some roles may be None.
        spec = removeSecurityProxy(self.factory.makeSpecification())
        spec.owner = self.factory.makePerson()
        spec.drafter = None
        spec.assignee = None
        spec.approver = self.person

        roles = IPersonRoles(self.person)
        self.assertTrue(roles.isOneOf(
            spec, ['owner', 'drafter', 'assignee', 'approver']))

    def test_isOneOf_AttributeError(self):
        # Do not try to check for none-existent attributes.
        obj = self.factory.makeProduct()
        fake_attr = self.factory.getUniqueString()
        roles = IPersonRoles(self.person)
        self.assertRaises(AttributeError, roles.isOneOf, obj, [fake_attr])


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

