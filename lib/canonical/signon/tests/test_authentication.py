# Copyright 2008 Canonical Ltd.  All rights reserved.
"""Tests authentication.py"""

__metaclass__ = type


import unittest

from zope.app.security.principalregistry import UnauthenticatedPrincipal

from canonical.config import config
from canonical.testing import DatabaseFunctionalLayer
from canonical.launchpad.ftests import login
from lp.testing import TestCaseWithFactory
from canonical.launchpad.webapp.authentication import LaunchpadPrincipal
from canonical.launchpad.webapp.login import logInPrincipal
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.signon.publisher import IdPublication, OpenIDPublication


class TestAuthenticationOfPersonlessAccounts(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.email = 'baz@example.com'
        self.request = LaunchpadTestRequest()
        self.account = self.factory.makeAccount(
            'Personless account', email=self.email)
        self.principal = LaunchpadPrincipal(
            self.account.id, self.account.displayname,
            self.account.displayname, self.account)
        login(self.email)

    def test_navigate_logged_in_on_id_dot_launchpad_dot_net(self):
        # A user with the credentials of a personless account will browse
        # login.launchpad.net logged in as that account.
        logInPrincipal(self.request, self.principal, self.email)
        self.request.response.setCookie(
            config.launchpad_session.cookie, 'xxx')

        publication = IdPublication(None)
        principal = publication.getPrincipal(self.request)
        self.failUnless(isinstance(principal, LaunchpadPrincipal),
                        "%r should be a LaunchpadPrincipal" % (principal,))
        self.failUnlessEqual(principal.id, self.account.id)

    def test_navigate_logged_in_on_login_dot_launchpad_dot_net(self):
        # A user with the credentials of a personless account will browse
        # login.launchpad.net logged in as that account.
        logInPrincipal(self.request, self.principal, self.email)
        self.request.response.setCookie(
            config.launchpad_session.cookie, 'xxx')

        publication = OpenIDPublication(None)
        principal = publication.getPrincipal(self.request)
        self.failUnless(isinstance(principal, LaunchpadPrincipal),
                        "%r should be a LaunchpadPrincipal" % (principal,))
        self.failUnlessEqual(principal.id, self.account.id)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
