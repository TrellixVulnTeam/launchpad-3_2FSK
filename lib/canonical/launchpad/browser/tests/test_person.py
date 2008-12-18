# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Test harness for person views unit tests."""

__metaclass__ = type


from textwrap import dedent
import unittest

from canonical.config import config
from canonical.testing.layers import DatabaseFunctionalLayer
from canonical.launchpad.browser.person import PersonView
from canonical.launchpad.ftests import ANONYMOUS, login, login_person, logout
from canonical.launchpad.testing.factory import LaunchpadObjectFactory
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, setUp, tearDown)
from canonical.launchpad.webapp.servers import LaunchpadTestRequest


class PersonView_openid_identity_url_TestCase(unittest.TestCase):
    """Tests for the public OpenID identifier shown on the profile page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)
        self.user = LaunchpadObjectFactory().makePerson(name='eris')
        self.request = LaunchpadTestRequest(
            SERVER_URL="http://launchpad.dev/")
        login_person(self.user, self.request)
        self.view = PersonView(self.user, self.request)
        # Marker allowing us to reset the config.
        config.push(self.id(), '')

    def tearDown(self):
        logout()
        config.pop(self.id())

    def test_should_be_profile_page_when_delegating(self):
        """The profile page is the OpenID identifier in normal situation."""
        self.assertEquals(
            'http://launchpad.dev/~eris', self.view.openid_identity_url)

    def test_should_be_production_profile_page_when_not_delegating(self):
        """When the profile page is not delegated, the OpenID identity URL
        should be the one on the main production site."""
        config.push('non-delegating', dedent('''
            [vhost.mainsite]
            openid_delegate_profile: False

            [launchpad]
            non_restricted_hostname: prod.launchpad.dev
            '''))
        self.assertEquals(
            'http://prod.launchpad.dev/~eris', self.view.openid_identity_url)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromName(__name__))
    suite.addTest(LayeredDocFileSuite(
        'person-rename-account-with-openid.txt',
        setUp=setUp, tearDown=tearDown,
        layer=DatabaseFunctionalLayer))
    return suite


if __name__ == '__main__':
    unittest.main()

