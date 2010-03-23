# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for pofile translate pages."""

__metaclass__ = type
__all__ = []

from canonical.launchpad.windmill.testing import constants, lpuser
from lp.translations.windmill.testing import TranslationsWindmillLayer
from lp.testing import WindmillTestCase


class POFileNewTranslationFieldKeybindings(WindmillTestCase):
    """Tests for keybinding actions associated to the translation field."""

    layer = TranslationsWindmillLayer
    suite_name = 'POFile Translate'

    def test_pofile_new_translation_autoselect(self):
        """Test for automatically selecting new translation on text input.

        When new text is typed into the new translation text fields, the
        associated radio button should be automatically selected.
        """
        client = self.client
        start_url = ('http://translations.launchpad.dev:8085/'
                        'evolution/trunk/+pots/evolution-2.2/es/+translate')
        user = lpuser.TRANSLATIONS_ADMIN
        new_translation_id = u'msgset_1_es_translation_0_new'
        radiobutton_id = u'msgset_1_es_translation_0_new_select'

        # Go to the translation page.
        self.client.open(url=start_url)
        self.client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        user.ensure_login(self.client)

        # Wait for the new translation field and it's associated radio button.
        client.waits.forElement(
            id=new_translation_id, timeout=constants.FOR_ELEMENT)
        client.waits.forElement(
            id=radiobutton_id, timeout=constants.FOR_ELEMENT)

        # Check that the associated radio button is not selected.
        client.asserts.assertNotChecked(id=radiobutton_id)

        # Type a new translation.
        client.type(
            id=new_translation_id, text=u'New translation')

        # Check that the associated radio button is selected.
        client.asserts.assertChecked(id=radiobutton_id)

    def _check_reset_translation_select(
        self, client, checkbox, singular_select, singular_current,
        plural_select=None):
        """Checks that the new translation select radio buttons are checked
        when ticking 'Someone should review this translation' checkbox.
        """

        client.waits.forElement(
            id=checkbox, timeout=constants.FOR_ELEMENT)
        client.waits.forElement(
            id=singular_select, timeout=constants.FOR_ELEMENT)
        if plural_select is not None:
            client.waits.forElement(
                id=plural_select, timeout=constants.FOR_ELEMENT)        

        # Check that initialy the checkbox is not checked and
        # that the radio buttons are not selected.
        client.asserts.assertNotChecked(id=checkbox)
        client.asserts.assertNotChecked(id=singular_select)
        client.asserts.assertChecked(id=singular_current)
        if plural_select is not None:
            client.asserts.assertNotChecked(id=plural_select)

        # Check the checkbox
        client.click(id=checkbox)
        
        # Check that the checkbox and the new translation radio buttons are
        # selected.
        client.asserts.assertChecked(id=checkbox)
        client.asserts.assertChecked(id=singular_select)
        client.asserts.assertNotChecked(id=singular_current)
        if plural_select is not None:
            client.asserts.assertChecked(id=plural_select)

        # We select the current translation for the singular form.
        client.click(id=singular_current)        

        # Then then we uncheck the 'Someone needs to review this translation'
        # checkbox.
        client.click(id=checkbox)

        # Unchecking the 'Someone needs to review this translation' checkbox
        # will not change the state of the radio buttons.
        client.asserts.assertNotChecked(id=checkbox)
        client.asserts.assertNotChecked(id=singular_select)
        client.asserts.assertChecked(id=singular_current)
        if plural_select is not None:
            client.asserts.assertChecked(id=plural_select)

    def test_pofile_reset_translation_select(self):
        """Test for automatically selecting new translation when
        'Someone needs to review this translations' is checked.
        """
        client = self.client
        user = lpuser.TRANSLATIONS_ADMIN

        # Go to the zoom in page for a translation with plural forms.
        self.client.open(
            url='http://translations.launchpad.dev:8085/'
                'ubuntu/hoary/+source/evolution/+pots/'
                'evolution-2.2/es/15/+translate')
        self.client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        user.ensure_login(self.client)

        checkbox = u'msgset_144_force_suggestion'
        singular_select = u'msgset_144_es_translation_0_new_select'
        singular_current = u'msgset_144_es_translation_0_radiobutton'
        plural_select = u'msgset_144_es_translation_1_new_select'
        self._check_reset_translation_select(
            client,
            checkbox=checkbox,
            singular_select=singular_select,
            singular_current=singular_current,
            plural_select=plural_select)
        
        # Go to the zoom in page for a translation without plural forms.
        self.client.open(
            url='http://translations.launchpad.dev:8085/'
                'ubuntu/hoary/+source/evolution/+pots/'
                'evolution-2.2/es/19/+translate')
        self.client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        user.ensure_login(self.client)

        checkbox = u'msgset_148_force_suggestion'
        singular_select = u'msgset_148_es_translation_0_new_select'
        singular_current = u'msgset_148_es_translation_0_radiobutton'
        self._check_reset_translation_select(
            client,
            checkbox=checkbox,
            singular_select=singular_select,
            singular_current=singular_current)

        # Go to the zoom out page for some translations.
        self.client.open(
            url='http://translations.launchpad.dev:8085/'
                'ubuntu/hoary/+source/evolution/+pots/'
                'evolution-2.2/es/+translate')
        self.client.waits.forPageLoad(timeout=constants.PAGE_LOAD)
        user.ensure_login(self.client)

        checkbox = u'msgset_130_force_suggestion'
        singular_select = u'msgset_130_es_translation_0_new_select'
        singular_current = u'msgset_130_es_translation_0_radiobutton'
        self._check_reset_translation_select(
            client,
            checkbox=checkbox,
            singular_select=singular_select,
            singular_current=singular_current)
        
        # Ensure that the other radio buttons are not changed
        client.asserts.assertNotChecked(
            id=u'msgset_131_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_132_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_133_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_134_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_135_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_136_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_137_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_138_es_translation_0_new_select')
        client.asserts.assertNotChecked(
            id=u'msgset_139_es_translation_0_new_select')
