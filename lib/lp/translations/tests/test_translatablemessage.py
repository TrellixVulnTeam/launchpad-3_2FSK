# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for `TranslatableMessage`."""

__metaclass__ = type

from datetime import datetime, timedelta
import pytz
import transaction
from unittest import TestLoader

from lp.testing import TestCaseWithFactory
from lp.translations.model.translatablemessage import TranslatableMessage
from canonical.testing import ZopelessDatabaseLayer


class TestTranslatableMessageBase(TestCaseWithFactory):
    """Common setup for `TranslatableMessage`."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        """Create common objects for all tests.

        Arranges for a `ProductSeries` with `POTemplate` and
        `POTMsgSet`, as well as a Esperanto translation.
        """
        super(TestTranslatableMessageBase, self).setUp()
        self.product = self.factory.makeProduct()
        self.product.official_rosetta = True
        self.trunk = self.product.getSeries('trunk')
        self.potemplate = self.factory.makePOTemplate(
            productseries=self.trunk)
        self.potmsgset = self.factory.makePOTMsgSet(
            potemplate=self.potemplate, sequence=1)
        self.pofile = self.factory.makePOFile(
            potemplate=self.potemplate, language_code='eo')

    def _createTranslation(self, translation=None, is_current_ubuntu=False,
                           is_current_upstream=False, is_diverged=False,
                           date_updated=None):
        is_suggestion = not (
            is_current_ubuntu or is_current_upstream or is_diverged)
        if translation is not None:
            translation = [translation]
        return self.factory.makeTranslationMessage(
            pofile=self.pofile, potmsgset=self.potmsgset,
            translations=translation,
            suggestion=is_suggestion,
            is_current_upstream=is_current_upstream,
            force_diverged=is_diverged,
            date_updated=date_updated)


class TestTranslatableMessage(TestTranslatableMessageBase):
    """Test of `TranslatableMessage` properties and methods."""

    def test_sequence(self):
        # After instantiation, the sequence number from the potmsgset is
        # available.
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertEqual(1, message.sequence)

    def test_is_obsolete(self):
        # A message is obsolete if the sequence number is 0.
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertFalse(message.is_obsolete)

        self.potmsgset.setSequence(self.potemplate, 0)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertTrue(message.is_obsolete)

    def test_is_untranslated(self):
        translation = self._createTranslation('', is_current_ubuntu=True)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertTrue(message.is_untranslated)

    def test_is_current_diverged(self):
        translation = self._createTranslation(is_current_ubuntu=True,
                                              is_diverged=True)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertTrue(message.is_current_diverged)

    def test_is_current_upstream(self):
        translation = self._createTranslation(is_current_ubuntu=True,
                                              is_current_upstream=True)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertTrue(message.is_current_upstream)

    def test_has_plural_forms(self):
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertFalse(message.has_plural_forms)

        self.potmsgset.updatePluralForm(u"fooplural")
        self.assertTrue(message.has_plural_forms)

    def test_number_of_plural_forms(self):
        # eo has 2 plural forms, sr has 3
        self.potmsgset.updatePluralForm(u"fooplural")
        message = TranslatableMessage(self.potmsgset, self.pofile)
        self.assertEqual(2, message.number_of_plural_forms)

        sr_pofile = self.factory.makePOFile(
            potemplate=self.potemplate, language_code='sr')
        message = TranslatableMessage(self.potmsgset, sr_pofile)
        self.assertEqual(3, message.number_of_plural_forms)

    def test_getCurrentTranslation(self):
        translation = self._createTranslation(is_current_ubuntu=True)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        current = message.getCurrentTranslation()
        self.assertEqual(translation, current)

    def test_getImportedTranslation(self):
        translation = self._createTranslation(is_current_upstream=True)

        message = TranslatableMessage(self.potmsgset, self.pofile)
        imported = message.getImportedTranslation()
        self.assertEqual(translation, imported)

    def test_getSharedTranslation(self):
        translation = self._createTranslation(is_current_ubuntu=True)
        message = TranslatableMessage(self.potmsgset, self.pofile)
        shared = message.getSharedTranslation()
        self.assertEqual(translation, shared)


class TestTranslatableMessageExternal(TestTranslatableMessageBase):
    """Test of `TranslatableMessage` methods for external translations."""

    def setUp(self):
        # Create a potmsgset with the same msg id in another product
        super(TestTranslatableMessageExternal, self).setUp()
        common_msgid = self.potmsgset.singular_text
        self.external_potemplate = self.factory.makePOTemplate()
        self.external_potemplate.productseries.product.official_rosetta = True
        self.external_potmsgset = self.factory.makePOTMsgSet(
            potemplate=self.external_potemplate,
            singular=common_msgid, sequence=1)
        self.external_pofile = self.factory.makePOFile(
            potemplate=self.external_potemplate, language_code='eo')

        self.external_suggestion = self.factory.makeTranslationMessage(
            pofile=self.external_pofile, potmsgset=self.external_potmsgset)
        self.external_current = self.factory.makeTranslationMessage(
            pofile=self.external_pofile, potmsgset=self.external_potmsgset)

        self.message = TranslatableMessage(self.potmsgset, self.pofile)

    def test_getExternalTranslations(self):
        transaction.commit()
        externals = self.message.getExternalTranslations()
        self.assertContentEqual([self.external_current], externals)

    def test_getExternalSuggestions(self):
        transaction.commit()
        externals = self.message.getExternalSuggestions()
        self.assertContentEqual([self.external_suggestion], externals)


class TestTranslatableMessageSuggestions(TestTranslatableMessageBase):
    """Test of `TranslatableMessage` methods for getting suggestions."""

    def gen_now(self):
        now = datetime.now(pytz.UTC)
        while True:
            yield now
            now += timedelta(milliseconds=1)

    def setUp(self):
        super(TestTranslatableMessageSuggestions, self).setUp()
        self.now = self.gen_now().next
        self.suggestion1 = self._createTranslation(date_updated=self.now())
        self.current =  self._createTranslation(is_current_ubuntu=True,
                                                date_updated=self.now())
        self.suggestion2 = self._createTranslation(date_updated=self.now())
        self.message = TranslatableMessage(self.potmsgset, self.pofile)

    def test_getAllSuggestions(self):
        # There are three different methods to return 
        suggestions = self.message.getAllSuggestions()
        self.assertContentEqual([self.suggestion1, self.suggestion2],
                                suggestions)

    def test_getDismissedSuggestions(self):
        # There are three different methods to return 
        suggestions = self.message.getDismissedSuggestions()
        self.assertContentEqual([self.suggestion1], suggestions)

    def test_getUnreviewedSuggestions(self):
        # There are three different methods to return 
        suggestions = self.message.getUnreviewedSuggestions()
        self.assertContentEqual([self.suggestion2], suggestions)

    def test_dismissAllSuggestions(self):
        # Add a suggestion that is newer than the current translation and
        # dismiss it. Also show that getSuggestions only returns translations
        # that are newer than the current one unless only_new is set to False.

        self.message.dismissAllSuggestions(self.potemplate.owner, self.now())
        suggestions = self.message.getUnreviewedSuggestions()
        self.assertContentEqual([], suggestions)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
