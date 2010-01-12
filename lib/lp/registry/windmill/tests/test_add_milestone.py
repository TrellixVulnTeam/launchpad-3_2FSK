# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for translation import queue behaviour."""

__metaclass__ = type
__all__ = []

import time
import unittest

from canonical.launchpad.windmill.testing import lpuser

from windmill.authoring import WindmillTestClient

from lp.registry.windmill.testing import RegistryWindmillLayer
from lp.testing import TestCaseWithFactory


def test_inline_add_milestone(client, url, name=None, suite='milestone',
                              user=lpuser.FOO_BAR):
    """Test the form overlay for adding a milestone.

    :param name: Name of the test.
    :param url: Starting url.
    :param suite: The suite in which this test is part of.
    :param user: The user who should be logged in.
    """
    # Ensure that the milestone name doesn't conflict with previous
    # test runs, and test that it correctly lowercases the name.
    milestone_name = u'FOObar%x' % int(time.time())
    code_name = u'code-%s' % milestone_name

    user.ensure_login(client)
    client.open(url=url)
    client.waits.forPageLoad(timeout=u'20000')

    client.waits.forElement(
        id=u'field.milestone_for_release', timeout=u'8000')

    # Click the "Create milestone" link.
    client.click(id=u'create-milestone-link')

    # Submit milestone form.
    client.waits.forElement(id=u'field.name', timeout=u'8000')
    client.type(id='field.name', text=milestone_name)
    client.type(id='field.code_name', text=code_name)
    client.type(id='field.dateexpected', text=u"2004-01-05")
    client.type(id='field.summary', text=u"foo bar")
    client.click(id=u'formoverlay-add-milestone')

    # Verify that the milestone was added to the SELECT input,
    # and that it is now selected.
    client.waits.sleep(milliseconds='1000')
    client.asserts.assertSelected(id="field.milestone_for_release",
                                  validator=milestone_name.lower())

    # Verify error message when trying to create a milestone with a
    # conflicting name.
    client.click(id=u'create-milestone-link')
    client.waits.forElement(id=u'field.name', timeout=u'8000')
    client.type(id='field.name', text=milestone_name)
    client.click(id=u'formoverlay-add-milestone')
    client.waits.forElement(
        xpath="//div[contains(@class, 'yui-lazr-formoverlay-errors')]/ul/li")
    client.asserts.assertTextIn(
        classname='yui-lazr-formoverlay-errors',
        validator='The name %s is already used' % milestone_name.lower())
    client.click(classname='close-button')

    # Submit product release form.
    client.select(id='field.milestone_for_release',
                  val=milestone_name.lower())
    client.type(id='field.datereleased', text=u"2004-02-22")
    client.click(id=u'field.actions.create')
    client.waits.forPageLoad(timeout=u'20000')

    # Verify that the release was created.
    client.waits.forElement(id="version")
    client.asserts.assertText(
        xpath="//*[@id='version']/dd", validator=milestone_name.lower())
    client.asserts.assertText(
        xpath="//*[@id='code-name']/dd", validator=code_name)


class TestAddMilestone(TestCaseWithFactory):
    """Test form overlay widget for adding a milestone."""

    layer = RegistryWindmillLayer

    def setUp(self):
        self.client = WindmillTestClient('AddMilestone')

    def test_adding_milestone_on_addrelease_page(self):
        test_inline_add_milestone(
            self.client,
            url='http://launchpad.dev:8085/bzr/trunk/+addrelease',
            name='test_inline_add_milestone_for_release')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
