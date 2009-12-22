# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest

from windmill.authoring import WindmillTestClient

from canonical.launchpad.windmill.testing import lpuser, constants
from lp.bugs.windmill.testing import BugsWindmillLayer
from lp.testing import TestCaseWithFactory


class TestFilebugExtras(TestCaseWithFactory):

    layer = BugsWindmillLayer

    def test_filebug_extra_options(self):
        """Test the extra options area on +filebug pages.

        This test ensures that, with Javascript enabled, the extra options
        expander starts closed, and contains several fields when opened.
        """
        client = WindmillTestClient("File bug extra options test")

        # Open a +filebug page and wait for it to finish loading.
        client.open(url=u'http://bugs.launchpad.dev:8085/firefox/+filebug')
        client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        lpuser.SAMPLE_PERSON.ensure_login(client)

        # Search for a possible duplicate.
        client.waits.forElement(
            id=u'field.search', timeout=constants.FOR_ELEMENT)
        client.type(text=u'Broken', id=u'field.search')
        client.waits.forElement(
            id=u'field.actions.search', timeout=constants.FOR_ELEMENT)
        client.click(id=u'field.actions.search')
        client.waits.forElement(
            id=u'filebug-form', timeout=constants.FOR_ELEMENT)

        # No duplicates were found.
        client.asserts.assertText(
            id=u'no-similar-bugs',
            validator=u'No similar bug reports were found.')

        # Check out the expander.
        _test_expander(client)


def _test_expander(client):
    extra_opts_form = u"//fieldset[@id='filebug-extra-options']/div"
    form_closed = u"%s[@class='collapsed']" % extra_opts_form
    form_opened = u"%s[@class='expanded']" % extra_opts_form

    # The collapsible area is collapsed and doesn't display.
    client.asserts.assertNode(xpath=form_closed)

    # Click to expand the extra options form.
    client.click(link=u'Extra options')

    # The collapsible area is expanded and does display.
    client.asserts.assertNode(xpath=form_opened)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
