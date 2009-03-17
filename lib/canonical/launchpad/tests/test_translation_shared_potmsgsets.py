# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from datetime import datetime, timedelta
from pytz import timezone
import unittest

import transaction

from zope.component import getUtility
from zope.security.proxy import isinstance as zope_isinstance
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.database.translationmessage import (
    DummyTranslationMessage)
from canonical.launchpad.database.translationtemplateitem import (
    TranslationTemplateItem)
from canonical.launchpad.interfaces import (
    ILanguageSet, POTMsgSetInIncompatibleTemplatesError,
    TranslationFileFormat)
from canonical.launchpad.testing.factory import LaunchpadObjectFactory
from canonical.testing import LaunchpadZopelessLayer


class TestTranslationSharedPOTMsgSets(unittest.TestCase):
    """Test discovery of translation suggestions."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Set up context to test in."""
        # Create a product with two series and a shared POTemplate
        # in different series ('devel' and 'stable').
        factory = LaunchpadObjectFactory()
        self.factory = factory
        self.foo = factory.makeProduct()
        self.foo_devel = factory.makeProductSeries(
            name='devel', product=self.foo)
        self.foo_stable = factory.makeProductSeries(
            name='stable', product=self.foo)
        self.foo.official_rosetta = True

        # POTemplate is 'shared' if it has the same name ('messages').
        self.devel_potemplate = factory.makePOTemplate(
            productseries=self.foo_devel, name="messages")
        self.stable_potemplate = factory.makePOTemplate(self.foo_stable,
                                                        name="messages")

        # Create a single POTMsgSet that is used across all tests,
        # and add it to only one of the POTemplates.
        self.potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate)
        self.potmsgset.setSequence(self.devel_potemplate, 1)

    def test_TranslationTemplateItem(self):
        self.potmsgset.setSequence(self.stable_potemplate, 1)

        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        stable_potmsgsets = list(self.stable_potemplate.getPOTMsgSets())

        self.assertEquals(devel_potmsgsets, [self.potmsgset])
        self.assertEquals(devel_potmsgsets, stable_potmsgsets)

    def test_POTMsgSetInIncompatiblePOTemplates(self):
        # Make sure a POTMsgSet cannot be used in two POTemplates with
        # different incompatible source_file_format (like XPI and PO).
        self.devel_potemplate.source_file_format = TranslationFileFormat.PO
        self.stable_potemplate.source_file_format = TranslationFileFormat.XPI

        potmsgset = self.potmsgset

        self.assertRaises(POTMsgSetInIncompatibleTemplatesError,
                          potmsgset.setSequence, self.stable_potemplate, 1)

        # If the two file formats are compatible, it works.
        self.stable_potemplate.source_file_format = (
            TranslationFileFormat.KDEPO)
        potmsgset.setSequence(self.stable_potemplate, 1)

        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        stable_potmsgsets = list(self.stable_potemplate.getPOTMsgSets())
        self.assertEquals(devel_potmsgsets, stable_potmsgsets)

        # We hack the POTemplate manually to make data inconsistent
        # in database.
        self.stable_potemplate.source_file_format = TranslationFileFormat.XPI
        transaction.commit()

        # We remove the security proxy to be able to get a callable for
        # properties like `uses_english_msgids` and `singular_text`.
        naked_potmsgset = removeSecurityProxy(potmsgset)

        self.assertRaises(POTMsgSetInIncompatibleTemplatesError,
                          naked_potmsgset.__getattribute__,
                          "uses_english_msgids")

        self.assertRaises(POTMsgSetInIncompatibleTemplatesError,
                          naked_potmsgset.__getattribute__, "singular_text")


    def test_POTMsgSetUsesEnglishMsgids(self):
        """Test that `uses_english_msgids` property works correctly."""

        # Gettext PO format uses English strings as msgids.
        self.devel_potemplate.source_file_format = TranslationFileFormat.PO
        transaction.commit()
        self.assertEquals(self.potmsgset.uses_english_msgids, True)

        # Mozilla XPI format doesn't use English strings as msgids.
        self.devel_potemplate.source_file_format = TranslationFileFormat.XPI
        transaction.commit()
        self.assertEquals(self.potmsgset.uses_english_msgids, False)

    def test_POTMsgSet_singular_text(self):
        """Test that `singular_text` property works correctly."""

        BASE_STRING = u"Base string"
        ENGLISH_STRING = u"English string"
        DIVERGED_ENGLISH_STRING = u"Diverged English string"

        # We create a POTMsgSet with a base English string.
        potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate,
                                               BASE_STRING)
        potmsgset.setSequence(self.devel_potemplate, 2)

        # Gettext PO format uses English strings as msgids.
        self.devel_potemplate.source_file_format = TranslationFileFormat.PO
        transaction.commit()
        self.assertEquals(potmsgset.singular_text, BASE_STRING)

        # Mozilla XPI format doesn't use English strings as msgids,
        # unless there is no English POFile object.
        self.devel_potemplate.source_file_format = TranslationFileFormat.XPI
        transaction.commit()
        self.assertEquals(potmsgset.singular_text, BASE_STRING)

        # POTMsgSet singular_text is read from a shared English translation.
        en_pofile = self.factory.makePOFile('en', self.devel_potemplate)
        translation = self.factory.makeSharedTranslationMessage(
            pofile=en_pofile, potmsgset=potmsgset,
            translations=[ENGLISH_STRING])
        self.assertEquals(potmsgset.singular_text, ENGLISH_STRING)

        # A diverged (translation.potemplate != None) English translation
        # is not used as a singular_text.
        translation = self.factory.makeTranslationMessage(
            pofile=en_pofile, potmsgset=potmsgset,
            translations=[DIVERGED_ENGLISH_STRING])
        translation.potemplate = self.devel_potemplate
        self.assertEquals(potmsgset.singular_text, ENGLISH_STRING)

    def test_getCurrentDummyTranslationMessage(self):
        """Test that a DummyTranslationMessage is correctly returned."""

        # When there is no POFile, we get a DummyTranslationMessage inside
        # a DummyPOFile.
        serbian = getUtility(ILanguageSet).getLanguageByCode('sr')
        dummy = self.potmsgset.getCurrentDummyTranslationMessage(
            self.devel_potemplate, serbian)
        self.assertTrue(zope_isinstance(dummy, DummyTranslationMessage))

        # If a POFile exists, but there is no current translation message,
        # a dummy translation message is returned.
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        dummy = self.potmsgset.getCurrentDummyTranslationMessage(
            self.devel_potemplate, serbian)
        self.assertTrue(zope_isinstance(dummy, DummyTranslationMessage))

        # When there is a current translation message, an exception
        # is raised.
        translation = self.factory.makeTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset)
        self.assertTrue(translation.is_current)
        self.assertRaises(AssertionError,
                          self.potmsgset.getCurrentDummyTranslationMessage,
                          self.devel_potemplate, serbian)

    def test_getCurrentTranslationMessage(self):
        """Test how shared and diverged current translation messages
        interact."""
        # Share a POTMsgSet in two templates, and get a Serbian POFile.
        self.potmsgset.setSequence(self.stable_potemplate, 1)
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # A shared translation is current in both templates.
        shared_translation = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset)
        self.assertEquals(self.potmsgset.getCurrentTranslationMessage(
            self.devel_potemplate, serbian), shared_translation)
        self.assertEquals(self.potmsgset.getCurrentTranslationMessage(
            self.stable_potemplate, serbian), shared_translation)

        # Adding a diverged translation in one template makes that one
        # current in it.
        diverged_translation = self.factory.makeTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, force_diverged=True)
        self.assertEquals(self.potmsgset.getCurrentTranslationMessage(
            self.devel_potemplate, serbian), diverged_translation)
        self.assertEquals(self.potmsgset.getCurrentTranslationMessage(
            self.stable_potemplate, serbian), shared_translation)

    def test_getImportedTranslationMessage(self):
        """Test how shared and diverged current translation messages
        interact."""
        # Share a POTMsgSet in two templates, and get a Serbian POFile.
        self.potmsgset.setSequence(self.stable_potemplate, 1)
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # A shared translation is imported in both templates.
        shared_translation = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, is_imported=True)
        self.assertEquals(self.potmsgset.getImportedTranslationMessage(
            self.devel_potemplate, serbian), shared_translation)
        self.assertEquals(self.potmsgset.getImportedTranslationMessage(
            self.stable_potemplate, serbian), shared_translation)

        # Adding a diverged translation in one template makes that one
        # an imported translation there.
        diverged_translation = self.factory.makeTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, is_imported=True,
            force_diverged=True)
        self.assertEquals(self.potmsgset.getImportedTranslationMessage(
            self.devel_potemplate, serbian), diverged_translation)
        self.assertEquals(self.potmsgset.getImportedTranslationMessage(
            self.stable_potemplate, serbian), shared_translation)

    def test_getLocalTranslationMessages(self):
        """Test retrieval of local suggestions."""
        # Share a POTMsgSet in two templates, and get a Serbian POFile.
        self.potmsgset.setSequence(self.stable_potemplate, 1)
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        sr_stable_pofile = self.factory.makePOFile(
            'sr', self.stable_potemplate)
        serbian = sr_pofile.language

        # When there are no suggestions, empty list is returned.
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            [])

        # A shared suggestion is shown in both templates.
        shared_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, suggestion=True)
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            [shared_suggestion])
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.stable_potemplate, serbian)),
            [shared_suggestion])

        # A suggestion on another PO file is still shown in both templates.
        another_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_stable_pofile, potmsgset=self.potmsgset, suggestion=True)
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            [shared_suggestion, another_suggestion])
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.stable_potemplate, serbian)),
            [shared_suggestion, another_suggestion])

        # Setting one of the suggestions as current will leave make
        # them both 'reviewed' and thus hidden.
        shared_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, suggestion=False)
        self.assertEquals(
            list(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            [])

    def test_getExternallyUsedTranslationMessages(self):
        """Test retrieval of externally used translations."""

        # Create an external POTemplate with a POTMsgSet using
        # the same English string as the one in self.potmsgset.
        external_template = self.factory.makePOTemplate()
        external_template.productseries.product.official_rosetta = True
        external_potmsgset = self.factory.makePOTMsgSet(
            external_template,
            singular=self.potmsgset.singular_text)
        external_potmsgset.setSequence(external_template, 1)
        external_pofile = self.factory.makePOFile('sr', external_template)
        serbian = external_pofile.language

        # When there is no translation for the external POTMsgSet,
        # no externally used suggestions are returned.
        self.assertEquals(
            self.potmsgset.getExternallyUsedTranslationMessages(serbian),
            [])

        # If there are only suggestions on the external POTMsgSet,
        # no externally used suggestions are returned.
        external_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=True)
        self.assertEquals(
            self.potmsgset.getExternallyUsedTranslationMessages(serbian),
            [])

        # If there is an imported translation on the external POTMsgSet,
        # it is returned as the externally used suggestion.
        imported_translation = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=False, is_imported=True)
        imported_translation.is_current = False
        self.assertEquals(
            self.potmsgset.getExternallyUsedTranslationMessages(serbian),
            [imported_translation])

        # If there is a current translation on the external POTMsgSet,
        # it is returned as the externally used suggestion as well.
        current_translation = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=False, is_imported=False)
        self.assertEquals(
            self.potmsgset.getExternallyUsedTranslationMessages(serbian),
            [imported_translation, current_translation])

    def test_getExternallySuggestedTranslationMessages(self):
        """Test retrieval of externally suggested translations."""

        # Create an external POTemplate with a POTMsgSet using
        # the same English string as the one in self.potmsgset.
        external_template = self.factory.makePOTemplate()
        external_template.productseries.product.official_rosetta = True
        external_potmsgset = self.factory.makePOTMsgSet(
            external_template,
            singular=self.potmsgset.singular_text)
        external_potmsgset.setSequence(external_template, 1)
        external_pofile = self.factory.makePOFile('sr', external_template)
        serbian = external_pofile.language

        # When there is no translation for the external POTMsgSet,
        # no externally used suggestions are returned.
        self.assertEquals(
            self.potmsgset.getExternallySuggestedTranslationMessages(serbian),
            [])

        # If there is a suggestion on the external POTMsgSet,
        # it is returned.
        external_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=True)
        self.assertEquals(
            self.potmsgset.getExternallySuggestedTranslationMessages(serbian),
            [external_suggestion])

        # If there is an imported, non-current translation on the external
        # POTMsgSet, it is not returned as the external suggestion.
        imported_translation = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=False, is_imported=True)
        imported_translation.is_current = False
        self.assertEquals(
            self.potmsgset.getExternallySuggestedTranslationMessages(serbian),
            [external_suggestion])

        # A current translation on the external POTMsgSet is not
        # considered an external suggestion.
        current_translation = self.factory.makeSharedTranslationMessage(
            pofile=external_pofile, potmsgset=external_potmsgset,
            suggestion=False, is_imported=False)
        self.assertEquals(
            self.potmsgset.getExternallySuggestedTranslationMessages(serbian),
            [external_suggestion])

    def test_hasTranslationChangedInLaunchpad(self):
        """Make sure checking whether a translation is changed in LP works."""

        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # When there is no translation, it's not considered changed.
        self.assertEquals(
            self.potmsgset.hasTranslationChangedInLaunchpad(
                self.devel_potemplate, serbian),
            False)

        # If only a current, non-imported translation exists, it's not
        # changed in LP.
        current_shared = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset,
            is_imported=False)
        self.assertEquals(
            self.potmsgset.hasTranslationChangedInLaunchpad(
                self.devel_potemplate, serbian),
            False)

        # If imported translation is current, it's not changed in LP.
        current_shared.is_current = False
        imported_shared = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset,
            is_imported=True)
        self.assertEquals(
            self.potmsgset.hasTranslationChangedInLaunchpad(
                self.devel_potemplate, serbian),
            False)

        # If there's a current, diverged translation, and an imported
        # non-current one, it's changed in LP.
        imported_shared.is_current = False
        current_diverged = self.factory.makeTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset,
            is_imported=False)
        self.assertEquals(
            self.potmsgset.hasTranslationChangedInLaunchpad(
                self.devel_potemplate, serbian),
            True)

        # If imported one is shared and current, yet there is a diverged
        # current translation as well, it is changed in LP.
        imported_shared.is_current = False
        self.assertEquals(
            self.potmsgset.hasTranslationChangedInLaunchpad(
                self.devel_potemplate, serbian),
            True)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
