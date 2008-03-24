# Copyright 2008 Canonical Ltd. All rights reserved.

__metaclass__ = type

import unittest
from textwrap import dedent
from zope.component import getUtility
from zope.interface.verify import verifyObject

from canonical.database.sqlbase import commit
from canonical.launchpad.ftests import sync
from canonical.launchpad.helpers import test_diff
from canonical.launchpad.interfaces import (
    IPersonSet, IProductSet, IPOTemplateSet, ITranslationFileData,
    ITranslationFormatExporter, ITranslationImportQueue, RosettaImportStatus)
from canonical.launchpad.translationformat.xpi_po_exporter import (
    XPIPOExporter)
from canonical.testing import LaunchpadZopelessLayer
from canonical.launchpad.translationformat.tests.test_xpi_import import (
    get_en_US_xpi_file_to_import)


class XPIPOExporterTestCase(unittest.TestCase):
    """Class test for gettext's .po file exports"""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.translation_exporter = XPIPOExporter()

        # Get the importer.
        self.importer = getUtility(IPersonSet).getByName('sabdfl')

        # Get the Firefox template.
        firefox_product = getUtility(IProductSet).getByName('firefox')
        firefox_productseries = firefox_product.getSeries('trunk')
        firefox_potemplate_subset = getUtility(IPOTemplateSet).getSubset(
            productseries=firefox_productseries)
        self.firefox_template = firefox_potemplate_subset.new(
            name='firefox',
            translation_domain='firefox',
            path='en-US.xpi',
            owner=self.importer)

    def _compareExpectedAndExported(self, expected_file, exported_file):
        """Compare an export with a previous export that is correct.

        :param expected_file: buffer with the expected file content.
        :param export_file: buffer with the output file content.
        """
        expected_lines = [line for line in expected_file.split('\n')]
        # Remove time bombs in tests.
        exported_lines = [
            line for line in exported_file.split('\n')
            if (not line.startswith('"X-Launchpad-Export-Date:') and
                not line.startswith('"POT-Creation-Date:') and
                not line.startswith('"X-Generator: Launchpad'))]

        for number, expected_line in enumerate(expected_lines):
            self.assertEqual(
                expected_line, exported_lines[number],
                "Output doesn't match:\n\n %s" % test_diff(
                    expected_lines, exported_lines))

    def setUpTranslationImportQueueForTemplate(self):
        """Return an ITranslationImportQueueEntry for testing purposes."""
        # Get the file to import.
        en_US_xpi =  get_en_US_xpi_file_to_import('en-US')

        # Attach it to the import queue.
        translation_import_queue = getUtility(ITranslationImportQueue)
        published = True
        entry = translation_import_queue.addOrUpdateEntry(
            self.firefox_template.path, en_US_xpi.read(), published,
            self.importer, productseries=self.firefox_template.productseries,
            potemplate=self.firefox_template)

        # We must approve the entry to be able to import it.
        entry.status = RosettaImportStatus.APPROVED
        # The file data is stored in the Librarian, so we have to commit the
        # transaction to make sure it's stored properly.
        commit()

        # Prepare the import queue to handle a new .xpi import.
        (subject, body) = self.firefox_template.importFromQueue(entry)

        # The status is now IMPORTED:
        sync(entry)
        self.assertEquals(entry.status, RosettaImportStatus.IMPORTED)

    def test_Interface(self):
        """Check whether the object follows the interface."""
        self.failUnless(
            verifyObject(
                ITranslationFormatExporter, self.translation_exporter),
            "XPIPOExporter doesn't follow the interface")

    def test_XPITemplateExport(self):
        """Check a standard export from an XPI file."""
        # Prepare the import queue to handle a new .xpi import.
        self.setUpTranslationImportQueueForTemplate()

        exported_template = self.translation_exporter.exportTranslationFiles(
            [ITranslationFileData(self.firefox_template)])

        expected_template = dedent('''
            #, fuzzy
            msgid ""
            msgstr ""
            "Project-Id-Version: PACKAGE VERSION\\n"
            "Report-Msgid-Bugs-To: FULL NAME <EMAIL@ADDRESS>\\n"
            "PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
            "Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
            "Language-Team: LANGUAGE <LL@li.org>\\n"
            "MIME-Version: 1.0\\n"
            "Content-Type: text/plain; charset=UTF-8\\n"
            "Content-Transfer-Encoding: 8bit\\n"

            #: en-US.xpi/chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.title)
            msgid "MENU"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.accesskey)
            msgid "foozilla.menu.accesskey"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.commandkey)
            msgid "foozilla.menu.commandkey"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/subdir/test2.properties:6(foozilla_something)
            msgid "SomeZilla"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.dtd(foozilla.name)
            msgid "FooZilla!"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.dtd(foozilla.play.fire)
            msgid "Do you want to play with fire?"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.dtd(foozilla.play.ice)
            msgid "Play with ice?"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.properties:1(foozilla.title)
            msgid "FooZilla Zilla Thingy"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.properties:3(foozilla.happytitle)
            msgid "FooZillingy"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.properties:4(foozilla.nocomment)
            msgid "No Comment"
            msgstr ""

            #: en-US.xpi/chrome/en-US.jar!/test1.properties:5(foozilla.utf8)
            msgid "\xd0\x94\xd0\xb0\xd0\xbd=Day"
            msgstr ""
            ''').strip()

        self._compareExpectedAndExported(
            expected_template, exported_template.read())

def test_suite():
    return unittest.defaultTestLoader.loadTestsFromName(__name__)
