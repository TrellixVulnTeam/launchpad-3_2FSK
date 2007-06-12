# Copyright 2007 Canonical Ltd.  All rights reserved.
"""Gettext PO importer tests."""

__metaclass__ = type

import unittest
import transaction
from zope.component import getUtility

from canonical.launchpad.components.translationformats.gettext_po_importer import (
    GettextPoImporter
    )
from canonical.launchpad.interfaces import (
    ITranslationImportQueue, IPersonSet, IProductSet
    )
from canonical.lp.dbschema import TranslationFileFormat
from canonical.testing import LaunchpadZopelessLayer

test_template = r'''
msgid ""
msgstr ""
"PO-Revision-Date: 2005-05-03 20:41+0100\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Content-Type: text/plain; charset=UTF-8\n"

msgid "foo"
msgstr ""
'''

test_translation_file = r'''
msgid ""
msgstr ""
"PO-Revision-Date: 2005-05-03 20:41+0100\n"
"Last-Translator: Carlos Perello Marin <carlos@canonical.com>\n"
"Content-Type: text/plain; charset=UTF-8\n"

msgid "foo"
msgstr "blah"
'''


class GettextPoImporterTestCase(unittest.TestCase):
    """Class test for gettext's .po file imports"""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        # Add a new entry for testing purposes. It's a template one.
        self.translation_import_queue = getUtility(ITranslationImportQueue)
        template_path = 'po/testing.pot'
        is_published = True
        personset = getUtility(IPersonSet)
        importer = personset.getByName('carlos')
        productset = getUtility(IProductSet)
        firefox = productset.getByName('firefox')
        productseries = firefox.getSeries('trunk')
        template_entry = self.translation_import_queue.addOrUpdateEntry(
            template_path, test_template, is_published, importer,
            productseries=productseries)

        # Add another one, a translation file.
        pofile_path = 'po/es.po'
        translation_entry = self.translation_import_queue.addOrUpdateEntry(
            pofile_path, test_translation_file, is_published, importer,
            productseries=productseries)

        transaction.commit()
        self.template_importer = GettextPoImporter(template_entry)
        self.translation_importer = GettextPoImporter(translation_entry)

    def testFormat(self):
        self.failUnless(
            self.template_importer.format == TranslationFileFormat.PO,
            'GettextPoImporter format is not PO but %s' % (
                self.template_importer.format.name)
            )

    def testCanHandleFileExtension(self):
        # Gettext's file extesions are .po and .pot
        self.failUnless(
            self.template_importer.canHandleFileExtension('.po'),
            'GettextPoImporter is not handling .po files!')
        self.failUnless(
            self.template_importer.canHandleFileExtension('.pot'),
            'GettextPoImporter is not handling .pot files!')

    def testGetLastTranslator(self):
        """Tests whether we extract las translator information correctly."""
        # When it's the default one in Gettext (FULL NAME <EMAIL@ADDRESS>)
        # like it uses to be for templates, we get None values.
        name, email = self.template_importer.getLastTranslator()
        self.failUnless(name is None,
            "Didn't detect default Last Translator name")
        self.failUnless(email is None,
            "Didn't detect default Last Translator email")

        # Let's try with the translation file, it has valid Last Translator
        # information.
        name, email = self.translation_importer.getLastTranslator()
        self.failUnless(name == 'Carlos Perello Marin',
            "Didn't get the name from Last Translator field")
        self.failUnless(email == 'carlos@canonical.com',
            "Didn't get the email from Last Translator field")


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(GettextPoImporterTestCase))
    return suite

