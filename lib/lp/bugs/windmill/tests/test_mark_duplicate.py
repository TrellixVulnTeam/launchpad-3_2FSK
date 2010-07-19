# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for the bug tag entry UI."""

__metaclass__ = type
__all__ = []

import unittest

from canonical.launchpad.windmill.testing import constants, lpuser
from lp.bugs.windmill.testing import BugsWindmillLayer
from lp.testing import WindmillTestCase

MAIN_FORM_ELEMENT = u'//div[@id="duplicate-form-container"]/table'
FORM_NOT_VISIBLE = (
    u'element.className.search("yui-lazr-formoverlay-hidden") != -1')
FORM_VISIBLE = (
    u'element.className.search("yui-lazr-formoverlay-hidden") == -1')
CHANGE_BUTTON = (
    u'//div[@id="duplicate-form-container"]'
    '//button[@name="field.actions.change"]')


class TestMarkDuplicate(WindmillTestCase):

    layer = BugsWindmillLayer
    suite_name = "Bug mark duplicate test"

    def test_mark_duplicate_form_overlay(self):
        """Test the mark duplicate action on bug pages.

        This test ensures that with Javascript enabled, the mark duplicate
        link on a bug page uses the formoverlay to update the duplicateof
        field via the api.
        """
        client = self.client

        # Open a bug page and wait for it to finish loading
        client.open(url=u'http://bugs.launchpad.dev:8085/bugs/15')
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        lpuser.SAMPLE_PERSON.ensure_login(client)

        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)

        # Initially the form overlay is hidden
        client.asserts.assertElemJS(
            xpath=MAIN_FORM_ELEMENT, js=FORM_NOT_VISIBLE)

        # Clicking on the mark duplicate link brings up the formoverlay.
        # Entering 1 as the duplicate ID changes the duplicate text.
        client.click(classname=u'menu-link-mark-dupe')
        client.asserts.assertElemJS(xpath=MAIN_FORM_ELEMENT, js=FORM_VISIBLE)

        # Entering the bug id '1' and changing hides the formoverlay
        # and updates the mark as duplicate:
        client.type(text=u'1', id=u'field.duplicateof')
        client.click(xpath=CHANGE_BUTTON)
        client.asserts.assertElemJS(
            xpath=MAIN_FORM_ELEMENT, js=FORM_NOT_VISIBLE)

        # The form "Add a comment" now contains a warning about adding
        # a comment for a duplicate bug.
        client.waits.forElement(
            id='warning-comment-on-duplicate', timeout=constants.FOR_ELEMENT)

        # The duplicate can be cleared:
        client.click(id=u'mark-duplicate-text')
        client.type(text=u'', id=u'field.duplicateof')
        client.click(xpath=CHANGE_BUTTON)
        client.waits.forElement(
            xpath=u"//span[@id='mark-duplicate-text']/"
                  u"a[contains(., 'Mark as duplicate')]")

        # The warning about commenting on a diplucate bug is now gone.
        client.asserts.assertNotNode(id='warning-comment-on-duplicate')

        # Entering a false bug number results in input validation errors
        client.click(id=u'mark-duplicate-text')
        client.type(text=u'123', id=u'field.duplicateof')
        client.click(xpath=CHANGE_BUTTON)
        error_xpath = (
            MAIN_FORM_ELEMENT +
            "//div[contains(@class, 'yui-lazr-formoverlay-errors')]/ul/li")
        client.waits.forElement(xpath=error_xpath)

        # Clicking change again brings back the error dialog again
        # (regression test for bug 347258)
        client.click(xpath=CHANGE_BUTTON)
        client.waits.forElement(xpath=error_xpath)

        # But entering a correct bug and submitting
        # gets us back to a normal state
        client.type(text=u'1', id=u'field.duplicateof')
        client.click(xpath=CHANGE_BUTTON)
        client.waits.forElement(
            xpath=u"//span[@id='mark-duplicate-text']"
                  u"/a[contains(., 'bug #1')]")

        # Finally, clicking on the link to the bug takes you to the master.
        client.click(link=u'bug #1')
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        client.asserts.assertText(
            xpath=u"//h1[@id='bug-title']/span[1]",
            validator=u'Firefox does not support SVG')

        # When we go back to the page for the duplicate bug...
        client.open(url=u'http://bugs.launchpad.dev:8085/bugs/15')
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)

        # ...we see the same warning about commenting on a duplicate bug
        # as the one we saw before.
        client.asserts.assertNode(id='warning-comment-on-duplicate')

        # Once we remove the duplicate mark...
        client.click(id=u'change_duplicate_bug')
        client.type(text=u'', id=u'field.duplicateof')
        client.click(xpath=CHANGE_BUTTON)
        client.waits.sleep(milliseconds=constants.SLEEP)

        # ...the warning is gone.
        client.asserts.assertNotNode(id='warning-comment-on-duplicate')

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
