# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test harness for person views unit tests."""

__metaclass__ = type

from textwrap import dedent

from lp.registry.browser.person import PersonView
from lp.services.config import config
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class PersonView_openid_identity_url_TestCase(TestCaseWithFactory):
    """Tests for the public OpenID identifier shown on the profile page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson(name='eris')
        self.request = LaunchpadTestRequest(
            SERVER_URL="http://launchpad.dev/")
        login_person(self.user, self.request)
        self.view = PersonView(self.user, self.request)
        # Marker allowing us to reset the config.
        config.push(self.id(), '')
        self.addCleanup(config.pop, self.id())

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
