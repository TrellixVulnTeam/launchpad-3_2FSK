# Copyright 2009 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=C0102

__metaclass__ = type

from datetime import datetime, timedelta
import pytz
import unittest

import transaction

from zope.component import getUtility
from zope.security.proxy import isinstance as zope_isinstance
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.database.translationmessage import (
    DummyTranslationMessage)
from canonical.launchpad.interfaces import (
    ILanguageSet, IPersonSet, POTMsgSetInIncompatibleTemplatesError,
    TranslationConflict, TranslationFileFormat)
from lp.testing.factory import LaunchpadObjectFactory
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
        self.assertTrue(self.potmsgset.uses_english_msgids)

        # Mozilla XPI format doesn't use English strings as msgids.
        self.devel_potemplate.source_file_format = TranslationFileFormat.XPI
        transaction.commit()
        self.assertFalse(self.potmsgset.uses_english_msgids)

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

    def test_getSharedTranslationMessage(self):
        """Test how shared and diverged current translation messages
        interact."""
        # Share a POTMsgSet in two templates, and get a Serbian POFile.
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # A shared translation matches the current one.
        shared_translation = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset)
        self.assertEquals(
            self.potmsgset.getSharedTranslationMessage(serbian),
            shared_translation)

        # Adding a diverged translation doesn't break getSharedTM.
        diverged_translation = self.factory.makeTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, force_diverged=True)
        self.assertEquals(
            self.potmsgset.getSharedTranslationMessage(serbian),
            shared_translation)

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
            set(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            set([]))

        # A shared suggestion is shown in both templates.
        shared_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, suggestion=True)
        self.assertEquals(
            set(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            set([shared_suggestion]))
        self.assertEquals(
            set(self.potmsgset.getLocalTranslationMessages(
                self.stable_potemplate, serbian)),
            set([shared_suggestion]))

        # A suggestion on another PO file is still shown in both templates.
        another_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_stable_pofile, potmsgset=self.potmsgset,
            suggestion=True)
        self.assertEquals(
            set(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            set([shared_suggestion, another_suggestion]))
        self.assertEquals(
            set(self.potmsgset.getLocalTranslationMessages(
                self.stable_potemplate, serbian)),
            set([shared_suggestion, another_suggestion]))

        # Setting one of the suggestions as current will leave make
        # them both 'reviewed' and thus hidden.
        shared_suggestion = self.factory.makeSharedTranslationMessage(
            pofile=sr_pofile, potmsgset=self.potmsgset, suggestion=False)
        self.assertEquals(
            set(self.potmsgset.getLocalTranslationMessages(
                self.devel_potemplate, serbian)),
            set([]))

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

    def test_updateTranslation_divergence(self):
        """Test that diverging translations works as expected."""
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # We can't use factory methods here because they depend on
        # updateTranslation itself.  So, a bit more boiler-plate than
        # usual.

        # Let's create a shared, current translation.
        shared_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'Shared'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC))
        self.assertEquals(shared_translation.potemplate, None)
        self.assertTrue(shared_translation.is_current)

        # And let's create a diverged translation by passing `force_diverged`
        # parameter to updateTranslation call.
        diverged_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'Diverged'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC), force_diverged=True)
        self.assertEquals(diverged_translation.potemplate,
                          self.devel_potemplate)
        # Both shared and diverged translations are marked as current,
        # since shared might be used in other templates which have no
        # divergences.
        self.assertTrue(shared_translation.is_current)
        self.assertTrue(diverged_translation.is_current)

        # But only diverged one is returned as current.
        current_translation = self.potmsgset.getCurrentTranslationMessage(
            self.devel_potemplate, serbian)
        self.assertEquals(current_translation, diverged_translation)

        # Trying to set a new, completely different translation when
        # there is a diverged translation keeps the divergence.
        new_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'New diverged'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC))
        self.assertEquals(new_translation.potemplate,
                          self.devel_potemplate)
        self.assertTrue(shared_translation.is_current)
        self.assertTrue(new_translation.is_current)

    def test_updateTranslation_convergence(self):
        """Test that converging translations works as expected."""
        sr_pofile = self.factory.makePOFile('sr', self.devel_potemplate)
        serbian = sr_pofile.language

        # Let's create a shared, current translation, and diverge from it
        # in this POTemplate.
        shared_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'Shared'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC))
        diverged_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'Diverged'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC), force_diverged=True)

        # Setting a diverged translation to exactly match shared one
        # will "converge" it back to the shared one.
        new_translation = self.potmsgset.updateTranslation(
            pofile=sr_pofile, submitter=sr_pofile.owner,
            new_translations=[u'Shared'], is_imported=False,
            lock_timestamp=datetime.now(pytz.UTC))
        self.assertEquals(new_translation, shared_translation)
        self.assertFalse(diverged_translation.is_current)
        self.assertTrue(new_translation.is_current)

        # Current translation is the shared one.
        current_translation = self.potmsgset.getCurrentTranslationMessage(
            self.devel_potemplate, serbian)
        self.assertEquals(current_translation, shared_translation)

class TestPOTMsgSetSuggestionsDismissal(unittest.TestCase):
    """Test dimissal of translation suggestions."""

    layer = LaunchpadZopelessLayer

    def _setDateCreated(self, tm):
        removeSecurityProxy(tm).date_created = self.now()

    def _setDateReviewed(self, tm):
        removeSecurityProxy(tm).date_reviewed = self.now()

    def gen_now(self):
        now = datetime.now(pytz.UTC)
        while True:
            yield now
            now += timedelta(milliseconds=1)

    def setUp(self):
        # Create a product with all the boilerplate objects to be able to
        # create TranslationMessage objects.
        factory = LaunchpadObjectFactory()
        self.factory = factory
        self.now = self.gen_now().next
        self.foo = factory.makeProduct()
        self.foo_main = factory.makeProductSeries(
            name='main', product=self.foo)
        self.foo.official_rosetta = True

        self.potemplate = factory.makePOTemplate(
            productseries=self.foo_main, name="messages")
        self.potmsgset = self.factory.makePOTMsgSet(self.potemplate,
                                                    sequence=1)
        self.pofile = self.factory.makePOFile('eo', self.potemplate)
        # Set up some translation messages with dummy timestamps that will be
        # changed in the tests.
        self.translation = self.factory.makeTranslationMessage(
            self.pofile, self.potmsgset, translations=[u'trans1'],
            reviewer=self.factory.makePerson(), date_updated=self.now())
        self.suggestion1 = self.factory.makeTranslationMessage(
            self.pofile, self.potmsgset, suggestion=True,
            translations=[u'sugg1'], date_updated=self.now())
        self.suggestion2 = self.factory.makeTranslationMessage(
            self.pofile, self.potmsgset, suggestion=True,
            translations=[u'sugg2'], date_updated=self.now())

    def test_dismiss_all(self):
        # Set order of creation and review.
        self._setDateReviewed(self.translation)
        self._setDateCreated(self.suggestion1)
        self._setDateCreated(self.suggestion2)
        # There are two local suggestions now.
        self.assertEqual(set([self.suggestion1, self.suggestion2]), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))
        # Dismiss suggestions.
        self.potmsgset.dismissAllSuggestions(
            self.pofile, self.factory.makePerson(), self.now())
        # There is no local suggestion now.
        self.assertEqual(set(), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))

    def test_dismiss_nochange(self):
        # Set order of creation and review.
        self._setDateCreated(self.suggestion1)
        self._setDateCreated(self.suggestion2)
        self._setDateReviewed(self.translation)
        # There is no local suggestion.
        self.assertEqual(set(), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)
            ))
        # Dismiss suggestions.
        self.potmsgset.dismissAllSuggestions(
            self.pofile, self.factory.makePerson(), self.now())
        # There is still no local suggestion.
        self.assertEqual(set(), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))

    def test_dismiss_conflicting_suggestion(self):
        # Set order of creation and review.
        self._setDateReviewed(self.translation)
        self._setDateCreated(self.suggestion1)
        old_now = self.now()
        self._setDateCreated(self.suggestion2)
        # There are two local suggestions now.
        self.assertEqual(set([self.suggestion1, self.suggestion2]), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))
        # Dismiss suggestions using an older timestamp only dismisses those
        # that were filed before that timestamp.
        self.potmsgset.dismissAllSuggestions(
            self.pofile, self.factory.makePerson(), old_now)
        self.assertEqual(set([self.suggestion2]), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))

    def test_dismiss_conflicting_translation(self):
        # Set order of creation and review.
        self._setDateCreated(self.suggestion1)
        old_now = self.now()
        self._setDateReviewed(self.translation)
        self._setDateCreated(self.suggestion2)
        # Only the 2nd suggestion is visible.
        self.assertEqual(set([self.suggestion2]), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))
        # Dismiss suggestions using an older timestamp fails if there is
        # a newer curent translation.
        self.assertRaises(TranslationConflict, 
            self.potmsgset.dismissAllSuggestions,
            self.pofile, self.factory.makePerson(), old_now)
        # Still only the 2nd suggestion is visible.
        self.assertEqual(set([self.suggestion2]), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))

    def test_dismiss_empty_translation(self):
        # Set order of creation and review.
        self._setDateCreated(self.suggestion1)
        self._setDateCreated(self.suggestion2)
        # Make the translation a suggestion, too.
        suggestion3 = self.translation
        suggestion3.is_current = False
        self._setDateCreated(suggestion3)
        # All suggestions are visible.
        self.assertEqual(
            set([self.suggestion1, self.suggestion2, suggestion3]),
            set(self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))
        # Dismiss suggestions, leaving the translation empty.
        self.potmsgset.dismissAllSuggestions(
            self.pofile, self.factory.makePerson(), self.now())
        current = self.potmsgset.getCurrentTranslationMessage(
            self.potemplate, self.pofile.language)
        self.assertNotEqual(None, current)
        self.assertEqual([None], current.translations)
        # All suggestions are gone.
        self.assertEqual(set(), set(
            self.potmsgset.getLocalTranslationMessages(
                self.potemplate, self.pofile.language)))


class TestPOTMsgSetTranslationMessageConstraints(unittest.TestCase):
    """Test how translation message constraints work."""

    layer = LaunchpadZopelessLayer

    def gen_now(self):
        now = datetime.now(pytz.UTC)
        while True:
            yield now
            now += timedelta(milliseconds=1)

    def setUp(self):
        """Set up context to test in."""
        # Create a product with two series and a shared POTemplate
        # in different series ('devel' and 'stable').
        factory = LaunchpadObjectFactory()
        self.factory = factory

        self.pofile = factory.makePOFile('sr')
        self.potemplate = self.pofile.potemplate
        self.uploader = getUtility(IPersonSet).getByName('carlos')
        self.now = self.gen_now().next

        # Create a single POTMsgSet that is used across all tests,
        # and add it to only one of the POTemplates.
        self.potmsgset = self.factory.makePOTMsgSet(self.potemplate,
                                                    sequence=1)

    def test_updateTranslation_SharedCurrentConstraint(self):
        # Corner case for bug #373139:
        # Adding a diverged, non-imported translation "tm1",
        # then a shared imported translation "tm2",
        # and finally, a shared imported translation "tm1" (matching original
        # diverged, non-imported translation) marks "tm2" as not current,
        # and makes "tm1" shared.
        tm1 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=False, force_diverged=True)
        tm2 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm2"], lock_timestamp=self.now(),
            is_imported=True, force_shared=True)
        self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=True)

        self.assertTrue(tm1.is_current)
        self.assertFalse(tm2.is_current)
        self.assertTrue(tm1.potemplate is None)
        self.assertTrue(tm2.potemplate is None)

    def test_updateTranslation_SharedImportedConstraint(self):
        # Corner case for bug #373139:
        # Adding a diverged imported translation "tm1",
        # then a shared imported translation "tm2",
        # and re-uploading "tm1" as just imported
        # makes "tm2" not is_imported, and both are shared.
        tm1 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=True, force_diverged=True)
        tm2 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm2"], lock_timestamp=self.now(),
            is_imported=True, force_shared=True)
        self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=True)

        self.assertTrue(tm1.is_imported)
        self.assertFalse(tm2.is_imported)
        self.assertTrue(tm1.potemplate is None)
        self.assertTrue(tm2.potemplate is None)

    def test_updateTranslation_DivergedImportedConstraint(self):
        # Corner case for bug #373139:
        # Adding a shared imported translation "tm1",
        # then a diverged imported translation "tm2",
        # and re-uploading "tm1" as imported translation
        # makes "tm2" not is_imported, and both are shared.
        tm1 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=True, force_shared=True)
        tm2 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm2"], lock_timestamp=self.now(),
            is_imported=True, force_diverged=True)
        self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=True)

        self.assertTrue(tm1.is_imported)
        self.assertFalse(tm2.is_imported)
        self.assertTrue(tm1.potemplate is None)
        self.assertTrue(tm2.potemplate is None)

    def test_updateTranslation_DivergedCurrentConstraint(self):
        # Corner case for bug #373139:
        # Adding a shared non-imported translation "tm0",
        # then a diverged non-imported translation "tm1"
        # (both are still current), then a diverged imported
        # translation (common pre-message-sharing-migration),
        # and we try to activate "tm0" as a forced diverged translation.
        # This makes "tm0" current and diverged, "tm1" non-current
        # and shared (basically, just a regular suggestion), and
        # "tm2" a diverged, non-current but imported translation.
        tm0 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm0"], lock_timestamp=self.now(),
            is_imported=False, force_shared=True)
        tm1 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm1"], lock_timestamp=self.now(),
            is_imported=False, force_diverged=True)
        tm2 = self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm2"], lock_timestamp=self.now(),
            is_imported=True, force_diverged=True)
        self.potmsgset.updateTranslation(
            self.pofile, self.uploader, [u"tm0"], lock_timestamp=self.now(),
            is_imported=False, force_diverged=True)

        self.assertTrue(tm0.is_current)
        self.assertFalse(tm1.is_current)
        self.assertFalse(tm2.is_current)
        self.assertTrue(tm2.is_imported)
        self.assertEquals(tm0.potemplate, self.potemplate)
        self.assertTrue(tm1.potemplate is None)
        self.assertEquals(tm2.potemplate, self.potemplate)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
