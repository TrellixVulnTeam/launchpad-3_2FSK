# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for the main branch merge proposal page."""

__metaclass__ = type
__all__ = []

import transaction
import unittest

from windmill.authoring import WindmillTestClient

from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.windmill.testing.constants import (
    FOR_ELEMENT, PAGE_LOAD, SLEEP)
from canonical.launchpad.windmill.testing.lpuser import login_person
from lp.code.windmill.testing import CodeWindmillLayer
from lp.testing import TestCaseWithFactory


EDIT_COMMIT_LINK = u'//a[contains(@href, "+edit-commit-message")]'
# There seem to be two textareas rendered for the yui-ieditor-input for some
# reason.
EDIT_COMMENT_TEXTBOX = (
    u'//div[@id="edit-commit-message"]//textarea[@class="yui-ieditor-input"][1]')
EDIT_COMMENT_SUBMIT = (
    u'//div[@id="edit-commit-message"]//'
    'button[contains(@class, "yui-ieditor-submit_button")]')
COMMIT_MESSAGE_TEXT = (
    u'//div[@id="edit-commit-message"]//div[@class="yui-editable_text-text"]')


class TestCommitMessage(TestCaseWithFactory):

    layer = CodeWindmillLayer

    def test_set_commit_message(self):
        """Test the commit message multiline editor."""
        eric = self.factory.makePerson(
            name="eric", displayname="Eric the Viking", password="test",
            email="eric@example.com")
        bmp = self.factory.makeBranchMergeProposal(registrant=eric)
        transaction.commit()

        client = WindmillTestClient("Commit message editing.")

        login_person(eric, "test", client)

        client.open(url=canonical_url(bmp))
        client.waits.forPageLoad(timeout=PAGE_LOAD)

        # Click on the element containing the branch status.
        client.click(xpath=EDIT_COMMIT_LINK)
        client.waits.forElement(xpath=EDIT_COMMENT_TEXTBOX)

        # Edit the commit message.
        message = u"This is the commit message."
        client.type(text=message, xpath=EDIT_COMMENT_TEXTBOX)
        client.click(xpath=EDIT_COMMENT_SUBMIT)

        client.waits.forElement(xpath=COMMIT_MESSAGE_TEXT)
        client.asserts.assertText(
            xpath=COMMIT_MESSAGE_TEXT, validator=message)

        # Confirm that the change was saved.
        client.open(url=canonical_url(bmp))
        client.waits.forPageLoad(timeout=PAGE_LOAD)
        client.asserts.assertText(
            xpath=COMMIT_MESSAGE_TEXT, validator=message)


class TestQueueStatus(TestCaseWithFactory):

    layer = CodeWindmillLayer

    def test_inline_queue_status_setting(self):
        """Test setting the queue_status with the ChoiceWidget."""
        mike = self.factory.makePerson(
            name="mike", displayname="Mike Tyson", password="test",
            email="mike@example.com")
        branch = self.factory.makeBranch(owner=mike)
        second_branch = self.factory.makeBranch(product=branch.product)
        merge_proposal = second_branch.addLandingTarget(mike, branch)
        transaction.commit()

        client = WindmillTestClient("Queue status setting")

        merge_url = canonical_url(merge_proposal)
        client.open(url=merge_url)
        client.waits.forPageLoad(timeout=PAGE_LOAD)
        login_person(mike, "test", client)

        # Click on the element containing the branch status.
        client.waits.forElement(
            id=u'branchmergeproposal-status-value', timeout=PAGE_LOAD)
        client.click(id=u'branchmergeproposal-status-value')
        client.waits.forElement(
            xpath=u'//div[contains(@class, "yui-ichoicelist-content")]')

        # Change the status to experimental.
        client.click(link=u'Rejected')
        client.waits.sleep(milliseconds=SLEEP)

        client.asserts.assertText(
            xpath=u'//td[@id="branchmergeproposal-status-value"]/span',
            validator=u'Rejected')

        # Reload the page and make sure the change sticks.
        client.open(url=merge_url)
        client.waits.forPageLoad(timeout=PAGE_LOAD)
        client.waits.forElement(
            xpath=u'//td[@id="branchmergeproposal-status-value"]/span',
            timeout=FOR_ELEMENT)
        client.asserts.assertText(
            xpath=u'//td[@id="branchmergeproposal-status-value"]/span',
            validator=u'Rejected')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
