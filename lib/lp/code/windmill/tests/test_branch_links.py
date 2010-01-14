# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for branch links."""

__metaclass__ = type
__all__ = []

import unittest

import windmill
from windmill.authoring import WindmillTestClient

from canonical.launchpad.windmill.testing import lpuser
from lp.code.windmill.testing import CodeWindmillLayer
from lp.testing import TestCaseWithFactory


class TestBranchLinks(TestCaseWithFactory):

    layer = CodeWindmillLayer

    def link_bug_and_assert_success(self, client, bug):
        """Link a bug to the branch currently viewed by the client."""
        client.click(id=u'linkbug')
        client.waits.forElement(id=u'field.bug')
        client.type(text=bug, id=u'field.bug')
        client.click(xpath=u'//button[@name="buglink.actions.change"]')

        client.waits.forElement(id=u'buglink-' + bug, timeout=u'10000')

    def unlink_bug_and_assert_success(self, client, bug):
        """Unlink a bug to the branch currently viewed by the client."""
        client.click(id=u'delete-buglink-' + bug)
        client.waits.sleep(milliseconds=3000)
        client.asserts.assertNotNode(id=u'buglink-' + bug)

    def test_inline_branch_bug_link_unlink(self):
        """Test branch bug links."""
        client = WindmillTestClient("Branch bug links")

        lpuser.FOO_BAR.ensure_login(client)

        start_url = (
            windmill.settings['TEST_URL'] + '/~mark/firefox/release--0.9.1')
        client.open(url=start_url)
        client.waits.forElement(id=u'linkbug', timeout=u'10000')

        self.link_bug_and_assert_success(client, u'1')
        client.asserts.assertText(id=u'linkbug',
            validator=u'Link to another bug report')
        self.link_bug_and_assert_success(client, u'2')

        client.waits.forElement(id=u'buglink-2', timeout=u'10000')

        # And now to unlink.
        self.unlink_bug_and_assert_success(client, u'1')
        self.unlink_bug_and_assert_success(client, u'2')
        client.asserts.assertText(id=u'linkbug',
            validator=u'Link to a bug report')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
