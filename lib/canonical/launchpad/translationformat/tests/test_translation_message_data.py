# Copyright 2009 Canonical Ltd.  All rights reserved.
"""Tests for `TranslationMessageData`."""

__metaclass__ = type

from unittest import TestCase, defaultTestLoader

from canonical.launchpad.interfaces import TranslationFormatSyntaxError
from canonical.launchpad.translationformat.translation_common_format import (
    TranslationMessageData)


class TranslationMessageDataTestCase(TestCase):
    """Test for `TranslationMessageData`."""

    def test_emptyTranslations(self):
        # TranslationMessageData starts out as an empty message.
        data = TranslationMessageData()
        self.assertEqual(data.translations, [])

    def test_addTranslation0(self):
        # Standard use case: add a form-0 translation.
        data = TranslationMessageData()
        data.addTranslation(0, 'singular')
        self.assertEqual(data.translations, ['singular'])

    def test_addTranslation1(self):
        # Unusual but possible: translate a higher form but not form 0.
        data = TranslationMessageData()
        data.addTranslation(1, 'plural')
        self.assertEqual(data.translations, [None, 'plural'])

    def test_addTranslationMulti(self):
        # Regular multi-form translation.
        data = TranslationMessageData()
        data.addTranslation(0, 'singular')
        data.addTranslation(1, 'plural')
        self.assertEqual(data.translations, ['singular', 'plural'])

    def test_addTranslationReversed(self):
        # Translate to multiple forms, but in a strange order.
        data = TranslationMessageData()
        data.addTranslation(1, 'plural')
        data.addTranslation(0, 'singular')
        self.assertEqual(data.translations, ['singular', 'plural'])

    def test_resetAllTranslations(self):
        # resetAllTranslations clears the message's translations.
        data = TranslationMessageData()
        data.addTranslation(0, 'singular')
        data.resetAllTranslations()
        self.assertEqual(data.translations, [])

    def test_duplicateTranslation(self):
        # Providing multiple translations for the same form is an error.
        data = TranslationMessageData()
        data.addTranslation(0, 'singular')
        self.assertRaises(
            TranslationFormatSyntaxError, data.addTranslation, 0, 'ralugnis')

    def test_duplicateTranslationError(self):
        # Providing multiple translations for the same form raises a
        # sensible error message.
        data = TranslationMessageData()
        data.addTranslation(0, 'singular')
        try:
            data.addTranslation(0, 'ralugnis')
        except TranslationFormatSyntaxError, error:
            self.assertEqual(
                error.render(),
                "Message has more than one translation for plural form 0.")


def test_suite():
    return defaultTestLoader.loadTestsFromName(__name__)
