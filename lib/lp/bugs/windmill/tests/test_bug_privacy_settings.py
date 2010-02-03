# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest

from windmill.authoring import WindmillTestClient

from canonical.launchpad.windmill.testing import lpuser, constants
from lp.bugs.windmill.testing import BugsWindmillLayer
from lp.testing import TestCaseWithFactory

BUG_URL = u'http://bugs.launchpad.dev:8085/bugs/15'
MAIN_FORM_ELEMENT = u'//div[@id="privacy-form-container"]/table'
FORM_NOT_VISIBLE = (
    u'element.className.search("yui-lazr-formoverlay-hidden") != -1')
FORM_VISIBLE = (
    u'element.className.search("yui-lazr-formoverlay-hidden") == -1')
FIELD_PRIVATE = u'field.private'
FIELD_SECURITY_RELATED = u'field.security_related'
CHANGE_BUTTON = (
    u'//div[@id="privacy-form-container"]'
    '//button[@name="field.actions.change"]')
CANCEL_BUTTON = (
    u'//div[@id="privacy-form-container"]'
    '//button[@name="field.actions.cancel"]')
PRIVACY_LINK = u'privacy-link'
PRIVACY_TEXT = u'privacy-text'
PRIVACY_TEXT_STRONG = u'//div[@id="privacy-text"]/strong'
SECURITY_MESSAGE = u'security-message'


class TestSecurityOverlay(TestCaseWithFactory):

    layer = BugsWindmillLayer

    def test_security_settings_form_overlay(self):
        """Test the change of the privacy settings on bug pages.

        This test ensures that with Javascript enabled, the link "This report
        is public[private]" on a bug page uses the formoverlay to update the
        flags "private" and "security vulnerability".
         """
        client = WindmillTestClient("Bug privacy settings test")
        lpuser.SAMPLE_PERSON.ensure_login(client)

        # Open a bug page and wait for it to finish loading.
        client.open(url=BUG_URL)
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)

        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)

        # Initially the form overlay is hidden.
        client.asserts.assertElemJS(
            xpath=MAIN_FORM_ELEMENT, js=FORM_NOT_VISIBLE)

        # Clicking on the "This report is public" link brings up
        # the formoverlay.
        client.click(id=PRIVACY_LINK)
        client.asserts.assertElemJS(xpath=MAIN_FORM_ELEMENT, js=FORM_VISIBLE)

        # The checkboxes for "privacy" and "security" are currently not
        # checked.
        client.waits.forElement(
            id=FIELD_PRIVATE, timeout=constants.FOR_ELEMENT)
        client.asserts.assertNotChecked(id=FIELD_PRIVATE)
        client.asserts.assertNotChecked(id=FIELD_SECURITY_RELATED)

        # Activating the checkbox "This bug should be private" and clicking
        # the "OK" button changes the link text to "This bug is private".
        client.click(name=FIELD_PRIVATE)
        client.click(xpath=CHANGE_BUTTON)
        client.waits.sleep(milliseconds=constants.SLEEP)
        client.asserts.assertTextIn(
            id=PRIVACY_TEXT, validator=u'This report is')
        client.asserts.assertText(
            xpath=PRIVACY_TEXT_STRONG, validator=u'private')

        # The form overlay is not longer visible.
        client.asserts.assertElemJS(
            xpath=MAIN_FORM_ELEMENT, js=FORM_NOT_VISIBLE)


        # These text changes are made via Javascript, thus avoiding a
        # complete page load. Let's reload the page, to check that
        # we get the same text in the HTML data sent by the server,
        # so that we can be sure that the security settings are correctly
        # updated.
        client.open(url=BUG_URL)
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)
        client.asserts.assertTextIn(
            id=PRIVACY_TEXT, validator=u'This report is')
        client.asserts.assertText(
            xpath=PRIVACY_TEXT_STRONG, validator=u'private')

        # The checkboxes for "privacy" and "security" reflect these
        # settings too.
        client.asserts.assertChecked(id=FIELD_PRIVATE)
        client.asserts.assertNotChecked(id=FIELD_SECURITY_RELATED)

        # We open the security settings form again, deactivate the checkbox
        # "private" and activate the checkbox "security vulnerability" and
        # save the changes.

        client.click(id=PRIVACY_LINK)
        client.click(name=FIELD_PRIVATE)
        client.click(name=FIELD_SECURITY_RELATED)
        client.click(xpath=CHANGE_BUTTON)

        # The link text indicatess now again a public bug report, and
        # we have an additional text below the link indicating that
        # this bug is a security vulnerability.
        client.waits.sleep(milliseconds=constants.SLEEP)
        client.asserts.assertTextIn(
            id=PRIVACY_TEXT, validator=u'This report is public')
        client.asserts.assertText(
            id=SECURITY_MESSAGE, validator=u'Security vulnerability')

        # The checkboxes for "privacy" and "security" reflect these
        # settings too.
        client.asserts.assertNotChecked(id=FIELD_PRIVATE)
        client.asserts.assertChecked(id=FIELD_SECURITY_RELATED)

        # When we reload the page, we get the same texts.
        client.open(url=BUG_URL)
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)
        client.asserts.assertTextIn(
            id=PRIVACY_TEXT, validator=u'This report is public')
        client.asserts.assertText(
            id=SECURITY_MESSAGE, validator=u'Security vulnerability')

        # After opening the security form overlay again, clicking the
        # "security vulnerability" chechbox and the submit button,
        # the text "Security vulnerability" is gone.
        client.click(id=PRIVACY_LINK)
        client.click(name=FIELD_SECURITY_RELATED)
        client.click(xpath=CHANGE_BUTTON)
        client.waits.sleep(milliseconds=constants.SLEEP)
        client.asserts.assertNotNode(id=SECURITY_MESSAGE)

        # When we reload the page, the <div> for the security message
        # does not exist either.
        client.open(url=BUG_URL)
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        client.waits.forElement(
            xpath=MAIN_FORM_ELEMENT, timeout=constants.FOR_ELEMENT)
        client.asserts.assertNotNode(id=SECURITY_MESSAGE)

        # The checkboxes for "privacy" and "security" reflect these
        # settings too.
        client.asserts.assertNotChecked(id=FIELD_PRIVATE)
        client.asserts.assertNotChecked(id=FIELD_SECURITY_RELATED)

        # When we open the security form overlay and then hit the
        # "cancel" button, the form is not longer visible.
        client.click(id=PRIVACY_LINK)
        client.asserts.assertElemJS(xpath=MAIN_FORM_ELEMENT, js=FORM_VISIBLE)
        client.click(xpath=CANCEL_BUTTON)
        client.asserts.assertElemJS(
            xpath=MAIN_FORM_ELEMENT, js=FORM_NOT_VISIBLE)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
