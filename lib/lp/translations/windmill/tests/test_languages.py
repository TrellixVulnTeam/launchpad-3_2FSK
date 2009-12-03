# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for languages listing and filtering behaviour."""

__metaclass__ = type
__all__ = []

import transaction

from windmill.authoring import WindmillTestClient
from zope.component import getUtility

from canonical.launchpad.windmill.testing.constants import (
    FOR_ELEMENT, PAGE_LOAD, SLEEP)
from lp.translations.windmill.testing import TranslationsWindmillLayer
from lp.testing import TestCaseWithFactory

INPUT_FIELD=(u"//div[contains(@class,'searchform')]"+
             u"//input[contains(@class,'find')]")
FILTER_BUTTON=(u"//div[contains(@class,'searchform')]"+
               u"//input[@value='Filter languages']")
LANGUAGE=u"//a[contains(@class, 'language') and text()='%s']/parent::li"
UNSEEN_VALIDATOR='className|unseen'


class LanguagesFilterTest(TestCaseWithFactory):
    """Test that filtering on the +languages page works."""

    layer = TranslationsWindmillLayer

    def _enter_filter_string(self, filterstring):
        self.client.type(xpath=INPUT_FIELD, text=filterstring)
        self.client.click(xpath=FILTER_BUTTON)
        self.client.waits.sleep(milliseconds=SLEEP)

    def _assert_languages_visible(self, languages):
        for language, visibility in languages.items():
            xpath = LANGUAGE % language
            if visibility:
                self.client.asserts.assertNotProperty(
                    xpath=xpath, validator=UNSEEN_VALIDATOR)
            else:
                self.client.asserts.assertProperty(
                    xpath=xpath, validator=UNSEEN_VALIDATOR)

    def test_filter_languages(self):
        """Test that filtering on the +languages page works.

        The test cannot fully cover all languages on the page and so just
        tests three with a search string of 'de':
        German, because it's language code is 'de' but the names does not,
        Mende, because it contains a 'de' but the language code does not,
        French, because neither its name nor language code contain 'de'.
        """
        self.client = WindmillTestClient('Languages filter')
        start_url = 'http://translations.launchpad.dev:8085/+languages'
        # Go to the languages page
        self.client.open(url=start_url)
        self.client.waits.forPageLoad(timeout=PAGE_LOAD)

        # "Not-matching" message is hidden and languages are visible.
        self.client.asserts.assertProperty(
            id=u'no_filter_matches',
            validator='className|unseen')
        self._assert_languages_visible({
            u'German': True,
            u'Mende': True,
            u'French': True,
            })

        # Enter search string, search and wait.
        self._enter_filter_string(u"de")
        # "Not-matching" message and French are hidden now.
        self.client.asserts.assertProperty(
            id=u'no_filter_matches',
            validator='className|unseen')
        self._assert_languages_visible({
            u'German': True,
            u'Mende': True,
            u'French': False,
            })

        # Enter not matching search string, search and wait.
        self._enter_filter_string(u"xxxxxx")
        # "Not-matching" message is shown, all languages are hidden.
        self.client.asserts.assertNotProperty(
            id=u'no_filter_matches',
            validator='className|unseen')
        self._assert_languages_visible({
            u'German': False,
            u'Mende': False,
            u'French': False,
            })

        # Enter empty search string, search and wait.
        self._enter_filter_string(u"")
        # "Not-matching" message is hidden, all languages are visible again.
        self.client.asserts.assertProperty(
             id=u'no_filter_matches',
             validator='className|unseen')
        self._assert_languages_visible({
            u'German': True,
            u'Mende': True,
            u'French': True,
            })

