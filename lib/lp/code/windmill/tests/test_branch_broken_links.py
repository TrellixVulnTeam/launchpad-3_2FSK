# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for links between branches and bugs or specs."""

__metaclass__ = type
__all__ = []

import unittest

import transaction
import windmill
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.windmill.testing import lpuser
from canonical.launchpad.windmill.testing.constants import SLEEP
from lp.code.windmill.testing import CodeWindmillLayer
from lp.testing import WindmillTestCase


ADD_COMMENT_BUTTON = (
    u'//input[@id="field.actions.save" and @class="button"]')


class TestBranchLinks(WindmillTestCase):
    """Test the rendering of broken branch links."""

    layer = CodeWindmillLayer
    suite_name = "Broken branch links"

    BUG_TEXT_TEMPLATE = u"""
    Here is the bug. Which branches are valid?
    Valid: %s
    Invalid %s
    """

    BRANCH_URL_TEMPLATE = "lp:%s"

    def make_product_and_valid_links(self):
        branch = self.factory.makeProductBranch()
        valid_branch_url = self.BRANCH_URL_TEMPLATE % branch.unique_name
        product = self.factory.makeProduct()
        product_branch = self.factory.makeProductBranch(product=product)
        naked_product = removeSecurityProxy(product)
        naked_product.development_focus.branch = product_branch
        valid_product_url = self.BRANCH_URL_TEMPLATE % product.name

        return (naked_product, [
            valid_branch_url,
            valid_product_url,
        ])

    def make_invalid_links(self):
        return [
            self.BRANCH_URL_TEMPLATE % 'foo',
            self.BRANCH_URL_TEMPLATE % 'bar',
            ]

    def test_invalid_url_rendering(self):
        """Link a bug from the branch page."""
        client = self.client

        lpuser.FOO_BAR.ensure_login(client)

        naked_product, valid_links = self.make_product_and_valid_links()
        invalid_links = self.make_invalid_links()
        bug_description = self.BUG_TEXT_TEMPLATE % (
            ', '.join(valid_links), ', '.join(invalid_links))
        bug = self.factory.makeBug(product=naked_product,
                                        title="The meaning of life is broken",
                                        description=bug_description)
        transaction.commit()

        bug_url = (
            windmill.settings['TEST_URL'] + '%s/+bug/%s'
            % (naked_product.name, bug.id))
        client.open(url=bug_url)
        client.waits.forElement(xpath=ADD_COMMENT_BUTTON)

        # Let the Ajax call run
        client.waits.sleep(milliseconds=SLEEP)

        code = """
            var good_a = windmill.testWin().document.getElementsByClassName(
                            'branch-short-link', 'a');
            var good_links = [];
            for( i=0; i<good_a.length; i++ ) {
                good_links.push(good_a[i].innerHTML);
            }

            var bad_a = windmill.testWin().document.getElementsByClassName(
                            'invalid-link', 'a');
            var bad_links = [];
            for( i=0; i<bad_a.length; i++ ) {
                bad_links.push(bad_a[i].innerHTML);
            }


            var result = {};
            result.good = good_links;
            result.bad = bad_links;
            result
        """
        raw_result = self.client.commands.execJS(js=code)
        result = raw_result['result']
        result_valid_links = result['good']
        result_invalid_links = result['bad']
        self.assertEqual(set(invalid_links), set(result_invalid_links))
        self.assertEqual(set(valid_links), set(result_valid_links))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
