# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Functional tests for XPI file format"""
__metaclass__ = type

import os.path
import tempfile
import transaction
import unittest
import zipfile

from zope.component import getUtility
import canonical.launchpad
from canonical.launchpad.interfaces import (
    IPersonSet, IProductSet, IPOTemplateNameSet, IPOTemplateSet,
    ITranslationImportQueue)
from canonical.lp.dbschema import RosettaImportStatus, TranslationFileFormat
from canonical.testing import LaunchpadZopelessLayer

def get_en_US_xpi_file_to_import():
    """Return an en-US.xpi file object ready to be imported.

    The file is generated from translationformat/tests/firefox-data/es-US.
    """
    # en-US.xpi file is a ZIP file which contains embedded JAR file (which is
    # also a ZIP file) and a couple of other files.  Embedded JAR file is
    # named 'en-US.jar' and contains translatable resources.

    # Get the root path where the data to generate .xpi file is stored.
    test_root = os.path.join(
        os.path.dirname(canonical.launchpad.__file__),
        'translationformat/tests/firefox-data/en-US')

    # First create a en-US.jar file to be included in XPI file.
    jarfile = tempfile.TemporaryFile()
    jar = zipfile.ZipFile(jarfile, 'w')
    jarlist = []
    data_dir = os.path.join(test_root, 'en-US-jar/')
    for root, dirs, files in os.walk(data_dir):
        for name in files:
            relative_dir = root[len(data_dir):].strip('/')
            jarlist.append(os.path.join(relative_dir, name))
    for file_name in jarlist:
        f = open(os.path.join(data_dir, file_name), 'r')
        jar.writestr(file_name, f.read())
    jar.close()
    jarfile.seek(0)

    # Add remaining bits and en-US.jar to en-US.xpi.

    xpifile = tempfile.TemporaryFile()
    xpi = zipfile.ZipFile(xpifile, 'w')
    xpilist = os.listdir(test_root)
    xpilist.remove('en-US-jar')
    for file_name in xpilist:
        f = open(os.path.join(test_root, file_name), 'r')
        xpi.writestr(file_name, f.read())
    xpi.writestr('chrome/en-US.jar', jarfile.read())
    xpi.close()
    xpifile.seek(0)

    return xpifile


class XpiTestCase(unittest.TestCase):
    """XPI file import into Launchpad."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        # Get the importer.
        self.importer = getUtility(IPersonSet).getByName('sabdfl')

        # Get the Firefox template.
        firefox_product = getUtility(IProductSet).getByName('firefox')
        firefox_productseries = firefox_product.getSeries('trunk')
        firefox_potemplatename = getUtility(IPOTemplateNameSet)['firefox']
        firefox_potemplate_subset = getUtility(IPOTemplateSet).getSubset(
            productseries=firefox_productseries)
        self.firefox_template = firefox_potemplate_subset.new(
            potemplatename=firefox_potemplatename,
            path='en-US.xpi',
            owner=self.importer)
        self.firefox_template = (
            firefox_potemplate_subset.getPOTemplateByName('firefox'))
        self.spanish_firefox = self.firefox_template.newPOFile('es')

    def setUpTranslationImportQueueForTemplate(self):
        """Return an ITranslationImportQueueEntry for testing purposes."""
        # Get the file to import.
        en_US_xpi =  get_en_US_xpi_file_to_import()

        # Attach it to the import queue.
        translation_import_queue = getUtility(ITranslationImportQueue)
        published = True
        entry = translation_import_queue.addOrUpdateEntry(
            self.firefox_template.path, en_US_xpi.read(), published,
            self.importer, productseries=self.firefox_template.productseries,
            potemplate=self.firefox_template)

        # We must approve the entry to be able to import it.
        entry.status = RosettaImportStatus.APPROVED

        return entry

    def setUpTranslationImportQueueForTranslation(self):
        """Return an ITranslationImportQueueEntry for testing purposes."""
        # Get the file to import. Given the way XPI file format works, we can
        # just use the same template file like a translation one.
        es_xpi =  get_en_US_xpi_file_to_import()

        # Attach it to the import queue.
        translation_import_queue = getUtility(ITranslationImportQueue)
        published = True
        entry = translation_import_queue.addOrUpdateEntry(
            'translations/es.xpi', es_xpi.read(), published,
            self.importer, productseries=self.firefox_template.productseries,
            potemplate=self.firefox_template, pofile=self.spanish_firefox)

        # We must approve the entry to be able to import it.
        entry.status = RosettaImportStatus.APPROVED

        return entry

    def _assertXpiMessageInvariant(self, message):
        """Check whether invariant part of all messages are correct."""
        # msgid and singular_text are always different except for the keyboard
        # shortcuts which are the 'accesskey' and 'commandkey' ones.
        self.failIf(
            (message.msgid == message.singular_text and
             message.msgid not in (
                u'foozilla.menu.accesskey', u'foozilla.menu.commandkey')),
            'msgid and singular_text should be different but both are %s' % (
                message.msgid))

        # Plural forms should be None as this format is not able to handle that.
        self.assertEquals(message.msgid_plural, None)
        self.assertEquals(message.plural_text, None)

        # There is no way to know whether a comment is from a
        # translator or a developer comment, so we have comenttext
        # always as None and store all comments as source comments.
        self.assertEquals(message.commenttext, None)

        # This format doesn't support any functionality like .po flags.
        self.assertEquals(message.flagscomment, u'')

    def testTemplateImport(self):
        """Test XPI template file import."""
        # Prepare the import queue to handle a new .xpi import.
        entry = self.setUpTranslationImportQueueForTemplate()
        # The file data is stored in the Librarian, so we have to commit the
        # transaction to make sure it's stored properly.
        transaction.commit()


        # Now, we tell the PO template to import from the file data it has.
        self.firefox_template.importFromQueue()

        # The status is now IMPORTED:
        self.assertEquals(entry.status, RosettaImportStatus.IMPORTED)

        # Let's validate the content of the messages.
        potmsgsets = list(self.firefox_template.getPOTMsgSets())

        messages_msgid_list = []
        for message in potmsgsets:
            messages_msgid_list.append(message.msgid)

            # Check the common values for all messages.
            self._assertXpiMessageInvariant(message)

            if message.msgid == u'foozilla.name':
                # It's a normal message that lacks any comment.

                self.assertEquals(message.singular_text, u'FooZilla!')
                self.assertEquals(
                    message.filereferences,
                    u'en-US.xpi/chrome/en-US.jar/test1.dtd(foozilla.name)')
                self.assertEquals(message.sourcecomment, None)

            elif message.msgid == u'foozilla.play.fire':
                # This one is also a normal message that has a comment.

                self.assertEquals(
                    message.singular_text, u'Do you want to play with fire?')
                self.assertEquals(
                    message.filereferences,
                    u'en-US.xpi/chrome/en-US.jar/test1.dtd' +
                        u'(foozilla.play.fire)')
                self.assertEquals(
                    message.sourcecomment,
                    u"Translators, don't play with fire!")

            elif message.msgid == u'foozilla.utf8':
                # Now, we can see that special UTF-8 chars are extracted
                # correctly.
                self.assertEquals(
                    message.singular_text, u'\u0414\u0430\u043d=Day')
                self.assertEquals(
                    message.filereferences,
                    u'en-US.xpi/chrome/en-US.jar/test1.properties:5' +
                        u'(foozilla.utf8)')
                self.assertEquals(message.sourcecomment, None)
            elif message.msgid == u'foozilla.menu.accesskey':
                # access key is a special notation that is supposed to be
                # translated with a key shortcut.
                self.assertEquals(
                    message.singular_text, u'foozilla.menu.accesskey')
                self.assertEquals(
                    message.filereferences,
                    u'en-US.xpi/chrome/en-US.jar/subdir/test2.dtd' +
                        u'(foozilla.menu.accesskey)')
                # The comment shows the key used when there is no translation,
                # which is noted as the en_US translation.
                self.assertEquals(
                    message.sourcecomment, u"Default key in en_US: 'M'")
            elif message.msgid == u'foozilla.menu.commandkey':
                # command key is a special notation that is supposed to be
                # translated with a key shortcut.
                self.assertEquals(
                    message.singular_text, u'foozilla.menu.commandkey')
                self.assertEquals(
                    message.filereferences,
                    u'en-US.xpi/chrome/en-US.jar/subdir/test2.dtd' +
                        u'(foozilla.menu.commandkey)')
                # The comment shows the key used when there is no translation,
                # which is noted as the en_US translation.
                self.assertEquals(
                    message.sourcecomment, u"Default key in en_US: 'm'")

        # Check that we got all messages.
        self.assertEquals(
            [u'foozilla.happytitle', u'foozilla.menu.accesskey',
             u'foozilla.menu.commandkey', u'foozilla.menu.title',
             u'foozilla.name', u'foozilla.nocomment', u'foozilla.play.fire',
             u'foozilla.play.ice', u'foozilla.title', u'foozilla.utf8',
             u'foozilla_something'],
            sorted(messages_msgid_list))

    def testTranslationImport(self):
        """Test XPI translation file import."""
        # Prepare the import queue to handle a new .xpi import.
        template_enstry = self.setUpTranslationImportQueueForTemplate()
        translation_entry = self.setUpTranslationImportQueueForTranslation()
        # The file data is stored in the Librarian, so we have to commit the
        # transaction to make sure it's stored properly.
        transaction.commit()

        # Now, we tell the PO template to import from the file data it has.
        self.firefox_template.importFromQueue()
        transaction.commit()
        # And the Spanish translation.
        self.spanish_firefox.importFromQueue()

        # The status is now IMPORTED:
        self.assertEquals(translation_entry.status, RosettaImportStatus.IMPORTED)

        # Let's validate the content of the messages.
        potmsgsets = list(self.firefox_template.getPOTMsgSets())

        messages = {}
        for message in potmsgsets:
            translation = self.spanish_firefox.getPOMsgSetFromPOTMsgSet(message)
            messages[message.msgid] = (message, translation)

        self.assertEquals(
            [u'foozilla.happytitle',
             u'foozilla.menu.accesskey',
             u'foozilla.menu.commandkey',
             u'foozilla.menu.title',
             u'foozilla.name',
             u'foozilla.nocomment',
             u'foozilla.play.fire',
             u'foozilla.play.ice',
             u'foozilla.title',
             u'foozilla.utf8',
             u'foozilla_something'],
            sorted(messages.keys()))

        msg, trans = messages[u'foozilla.name']
        # It's a normal message that lacks any comment.

        self.assertEquals(msg.singular_text, u'FooZilla!')
        # Translation will match singular_text because we are using
        # the same file for the template and translation.
        self.assertEquals(
            trans.published_texts,
            trans.published_texts)
        # With this first import, published and active texts must
        # match.
        self.assertEquals(
            trans.published_texts,
            trans.active_texts)

        msg, trans = messages[u'foozilla.menu.accesskey']
        # access key is a special notation that is supposed to be
        # translated with a key shortcut.
        self.assertEquals(
            msg.singular_text, u'foozilla.menu.accesskey')
        # The comment shows the key used when there is no translation,
        # which is noted as the en_US translation.
        self.assertEquals(
            msg.sourcecomment, u"Default key in en_US: 'M'")
        # But for the translation import, we get the key directly.
        self.assertEquals(
            trans.published_texts, [u'M'])

        msg, trans = messages[u'foozilla.menu.commandkey']
        # command key is a special notation that is supposed to be
        # translated with a key shortcut.
        self.assertEquals(
            msg.singular_text, u'foozilla.menu.commandkey')
        # The comment shows the key used when there is no translation,
        # which is noted as the en_US translation.
        self.assertEquals(
            msg.sourcecomment, u"Default key in en_US: 'm'")
        # But for the translation import, we get the key directly.
        self.assertEquals(
            trans.published_texts, [u'm'])


def test_suite():
    return unittest.defaultTestLoader.loadTestsFromName(__name__)
