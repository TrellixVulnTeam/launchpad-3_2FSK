# Copyright 2009 Canonical Ltd.  All rights reserved.

from datetime import datetime
import unittest

from zope.component import getUtility
from zope.event import notify
from zope.session.interfaces import ISession

from canonical.config import config

from canonical.launchpad.ftests import login
from canonical.launchpad.interfaces import (
    AccountCreationRationale, IAccountSet)
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.launchpad.webapp.authentication import LaunchpadPrincipal
from canonical.launchpad.webapp.interfaces import (
    CookieAuthLoggedInEvent, IPlacelessAuthUtility)
from canonical.launchpad.webapp.login import logInPerson, logoutPerson
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import DatabaseFunctionalLayer


class TestLoginAndLogout(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.request = LaunchpadTestRequest()
        # We create an account without a Person here just to make sure the
        # person and account created later don't end up with the same IDs,
        # which could happen since they're both sequential.
        # We need them to be different for one of our tests here.
        dummy_account = getUtility(IAccountSet).new(
            AccountCreationRationale.UNKNOWN, 'Dummy name')
        person = self.factory.makePerson('foo.bar@example.com')
        self.failIfEqual(person.id, person.account.id)
        self.principal = LaunchpadPrincipal(
            person.account.id, person.browsername,
            person.displayname, person)

    def test_logging_in_and_logging_out(self):
        # A test showing that we can authenticate the request after
        # logInPerson() is called, and after logoutPerson() we can no longer
        # authenticate it.

        # This is to setup an interaction so that we can call logInPerson
        # below.
        login('foo.bar@example.com')

        logInPerson(self.request, self.principal, 'foo.bar@example.com')
        session = ISession(self.request)
        # logInPerson() stores the account ID in a variable named 'accountid'.
        self.failUnlessEqual(
            session['launchpad.authenticateduser']['accountid'],
            self.principal.id)

        # This is so that the authenticate() call below uses cookie auth.
        self.request.response.setCookie(
            config.launchpad_session.cookie, 'xxx')

        principal = getUtility(IPlacelessAuthUtility).authenticate(
            self.request)
        self.failUnlessEqual(self.principal.id, principal.id)

        logoutPerson(self.request)

        principal = getUtility(IPlacelessAuthUtility).authenticate(
            self.request)
        self.failUnless(principal is None)

    def test_logging_in_and_logging_out_the_old_way(self):
        # A test showing that we can authenticate a request that had the
        # person/account ID stored in the 'personid' session variable instead
        # of 'accountid' -- where it's stored by logInPerson(). Also shows
        # that after logoutPerson() we can no longer authenticate it.
        # This is just for backwards compatibility.

        # This is to setup an interaction so that we can call logInPerson
        # below.
        login('foo.bar@example.com')

        session = ISession(self.request)
        authdata = session['launchpad.authenticateduser']
        self.request.setPrincipal(self.principal)
        authdata['personid'] = self.principal.person.id
        authdata['logintime'] = datetime.utcnow()
        authdata['login'] = 'foo.bar@example.com'
        notify(CookieAuthLoggedInEvent(self.request, 'foo.bar@example.com'))

        # This is so that the authenticate() call below uses cookie auth.
        self.request.response.setCookie(
            config.launchpad_session.cookie, 'xxx')

        principal = getUtility(IPlacelessAuthUtility).authenticate(
            self.request)
        self.failUnlessEqual(self.principal.id, principal.id)
        self.failUnlessEqual(self.principal.person, principal.person)

        logoutPerson(self.request)

        principal = getUtility(IPlacelessAuthUtility).authenticate(
            self.request)
        self.failUnless(principal is None)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
