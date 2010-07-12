# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the login helpers."""

__metaclass__ = type

import unittest

from zope.app.security.interfaces import IUnauthenticatedPrincipal
from zope.component import getUtility

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.interaction import get_current_principal
from canonical.launchpad.webapp.interfaces import IOpenLaunchBag
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.testing import (
    ANONYMOUS, is_logged_in, login, login_as, login_celebrity, login_person,
    login_team, logout)
from lp.testing import TestCaseWithFactory


class TestLoginHelpers(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def getLoggedInPerson(self):
        """Return the currently logged-in person.

        If no one is logged in, return None. If there is an anonymous user
        logged in, then return ANONYMOUS. Otherwise, return the logged-in
        `IPerson`.
        """
        # I don't really know the canonical way of asking for "the logged-in
        # person", so instead I'm using all the ways I can find and making
        # sure they match each other. -- jml
        by_launchbag = getUtility(IOpenLaunchBag).user
        principal = get_current_principal()
        if principal is None:
            return None
        elif IUnauthenticatedPrincipal.providedBy(principal):
            if by_launchbag is None:
                return ANONYMOUS
            else:
                raise ValueError(
                    "Unauthenticated principal, but launchbag thinks "
                    "%r is logged in." % (by_launchbag,))
        else:
            by_principal = principal.person
            self.assertEqual(by_launchbag, by_principal)
            return by_principal

    def assertLoggedIn(self, person):
        """Assert that 'person' is logged in."""
        self.assertEqual(person, self.getLoggedInPerson())

    def assertLoggedOut(self):
        """Assert that no one is currently logged in."""
        self.assertIs(None, get_current_principal())
        self.assertIs(None, getUtility(IOpenLaunchBag).user)

    def test_not_logged_in(self):
        # After logout has been called, we are not logged in.
        logout()
        self.assertEqual(False, is_logged_in())
        self.assertLoggedOut()

    def test_logout_twice(self):
        # Logging out twice don't harm anybody none.
        logout()
        logout()
        self.assertEqual(False, is_logged_in())
        self.assertLoggedOut()

    def test_logged_in(self):
        # After login has been called, we are logged in.
        login_person(self.factory.makePerson())
        self.assertEqual(True, is_logged_in())

    def test_login_person_actually_logs_in(self):
        # login_person changes the currently logged in person.
        person = self.factory.makePerson()
        logout()
        login_person(person)
        self.assertLoggedIn(person)

    def test_login_different_person_overrides(self):
        # Calling login_person a second time with a different person changes
        # the currently logged in user.
        a = self.factory.makePerson()
        b = self.factory.makePerson()
        logout()
        login_person(a)
        login_person(b)
        self.assertLoggedIn(b)

    def test_login_person_with_team(self):
        # Calling login_person with a team raises a nice error.
        team = self.factory.makeTeam()
        e = self.assertRaises(ValueError, login_person, team)
        self.assertEqual(str(e), "Got team, expected person: %r" % (team,))

    def test_login_with_email(self):
        # login() logs a person in by email.
        person = self.factory.makePerson()
        email = person.preferredemail.email
        logout()
        login(email)
        self.assertLoggedIn(person)

    def test_login_anonymous(self):
        # login as 'ANONYMOUS' logs in as the anonymous user.
        logout()
        login(ANONYMOUS)
        self.assertLoggedIn(ANONYMOUS)

    def test_login_team(self):
        # login_team() logs in as a member of the given team.
        team = self.factory.makeTeam()
        logout()
        login_team(team)
        person = self.getLoggedInPerson()
        self.assertTrue(person.inTeam(team))

    def test_login_team_with_person(self):
        # Calling login_team() with a person instead of a team raises a nice
        # error.
        person = self.factory.makePerson()
        logout()
        e = self.assertRaises(ValueError, login_team, person)
        self.assertEqual(str(e), "Got person, expected team: %r" % (person,))

    def test_login_team_returns_logged_in_person(self):
        # login_team returns the logged-in person.
        team = self.factory.makeTeam()
        logout()
        person = login_team(team)
        self.assertLoggedIn(person)

    def test_login_as_person(self):
        # login_as() logs in as a person if it's given a person.
        person = self.factory.makePerson()
        logout()
        login_as(person)
        self.assertLoggedIn(person)

    def test_login_as_team(self):
        # login_as() logs in as a member of a team if it's given a team.
        team = self.factory.makeTeam()
        logout()
        login_as(team)
        person = self.getLoggedInPerson()
        self.assertTrue(person.inTeam(team))

    def test_login_as_anonymous(self):
        # login_as(ANONYMOUS) logs in as the anonymous user.
        logout()
        login_as(ANONYMOUS)
        self.assertLoggedIn(ANONYMOUS)

    def test_login_as_None(self):
        # login_as(None) logs in as the anonymous user.
        logout()
        login_as(None)
        self.assertLoggedIn(ANONYMOUS)

    def test_login_celebrity(self):
        # login_celebrity logs in a celebrity.
        logout()
        login_celebrity('vcs_imports')
        vcs_imports = getUtility(ILaunchpadCelebrities).vcs_imports
        person = self.getLoggedInPerson()
        self.assertTrue(person.inTeam, vcs_imports)

    def test_login_nonexistent_celebrity(self):
        # login_celebrity raises ValueError when called with a non-existent
        # celebrity.
        logout()
        e = self.assertRaises(ValueError, login_celebrity, 'nonexistent')
        self.assertEqual(str(e), "No such celebrity: 'nonexistent'")


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
