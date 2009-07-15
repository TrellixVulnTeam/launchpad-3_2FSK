# Copyright 2004-2009 Canonical Ltd. All rights reserved.

__metaclass__ = type

import unittest
from zope.interface.verify import verifyObject

from lp.translations.interfaces.translationexporter import (
    ITranslationFormatExporter)
from lp.translations.utilities.gettext_po_exporter import (
    GettextPOChangedExporter)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from canonical.testing import LaunchpadZopelessLayer


class GettextPOChangedExporterTestCase(unittest.TestCase):
    """Class test for gettext's .po file exports of changed translations."""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.translation_exporter = GettextPOChangedExporter()

    def testInterface(self):
        """Check whether the object follows the interface."""
        self.failUnless(
            verifyObject(ITranslationFormatExporter,
                         self.translation_exporter),
            "GettextPOExporter doesn't follow the interface")

    def testSupportedFormats(self):
        """Check that the exporter reports the correct formats."""
        self.failUnlessEqual(
            self.translation_exporter.format,
            TranslationFileFormat.POCHANGED,
            "Expected GettextPOChangedExporter to provide POCHANGED format "
            "but got %r instead." % self.translation_exporter.format)
        self.failUnlessEqual(
            self.translation_exporter.supported_source_formats ,
            [],
            "Expected GettextPOChangedExporter to support no source formats "
            "but got %r instead." % (
                self.translation_exporter.supported_source_formats))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(GettextPOChangedExporterTestCase))
    return suite
