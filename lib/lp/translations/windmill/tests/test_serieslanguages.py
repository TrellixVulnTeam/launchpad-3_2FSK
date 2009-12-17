# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for series languages."""

__metaclass__ = type
__all__ = []

import transaction

from windmill.authoring import WindmillTestClient
from zope.component import getUtility

from canonical.launchpad.windmill.testing.constants import (
    FOR_ELEMENT, PAGE_LOAD, SLEEP)
from canonical.launchpad.windmill.testing import lpuser
from canonical.launchpad.windmill.testing.lpuser import login_person
from lp.translations.windmill.testing import TranslationsWindmillLayer
from lp.testing import TestCaseWithFactory

LANGUAGE=(u"//table[@id='languagestats']/descendant::a[text()='%s']"
         u"/parent::td/parent::tr")
UNSEEN_VALIDATOR='className|unseen'


class LanguagesSeriesTest(TestCaseWithFactory):
    """Test for filtering preferred languages in serieslanguages table."""

    layer = TranslationsWindmillLayer

    def _toggle_languages_visiblity(self):
        self.client.click(id="toggle-languages-visibility")
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

    def test_serieslanguages_table(self):
        """Test that filtering on the +languages page works.

        The test cannot fully cover all languages on the page and so just
        tests three with a search string of 'de':
        German, because it's language code is 'de' but the names does not,
        Mende, because it contains a 'de' but the language code does not,
        French, because neither its name nor language code contain 'de'.
        """
        self.client = WindmillTestClient('SeriesLanguages Tables')
        start_url = 'http://translations.launchpad.dev:8085/ubuntu'
        user = lpuser.TRANSLATIONS_ADMIN
        # Go to the distribution languages page
        self.client.open(url=start_url)
        self.client.waits.forPageLoad(timeout=PAGE_LOAD)
        user.ensure_login(self.client)

        # A link will be displayed for viewing all languages
        # and only user preferred langauges are displayed
        self.client.asserts.assertProperty(
            id=u'toggle-languages-visibility',
            validator='text|View All Languages')
        self._assert_languages_visible({
            u'Catalan': True,
            u'Spanish': True,
            u'French': False,
            u'Croatian': False,
            })

        # Toggle language visibility by clicking the toggle link.
        self._toggle_languages_visiblity()
        self.client.asserts.assertProperty(
            id=u'toggle-languages-visibility',
            validator='text|View Only Preferred Languages')
        # All languages should be visible now
        self._assert_languages_visible({
            u'Catalan': True,
            u'Spanish': True,
            u'French': True,
            u'Croatian': True,
            })

