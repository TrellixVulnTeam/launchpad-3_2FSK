# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from datetime import datetime
from pytz import timezone
import unittest

from zope.component import getUtility

from canonical.launchpad.interfaces import ILanguageSet
from lp.testing.factory import LaunchpadObjectFactory
from canonical.testing import LaunchpadZopelessLayer


class TestTranslationEmptyMessages(unittest.TestCase):
    """Test behaviour of empty translation messages."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Set up context to test in."""
        # Pretend we have a product being translated to Serbian.
        # This is where we are going to be importing translations to.
        factory = LaunchpadObjectFactory()
        self.factory = factory
        self.productseries = factory.makeProductSeries()
        self.productseries.product.official_rosetta = True
        self.potemplate = factory.makePOTemplate(self.productseries)
        self.serbian = getUtility(ILanguageSet).getLanguageByCode('sr')
        self.pofile_sr = factory.makePOFile('sr', potemplate=self.potemplate)
        self.now = datetime.now(timezone('UTC'))

    def test_NoEmptyImporedTranslation(self):
        # When an empty translation comes from import, it is
        # ignored when there's NO previous is_imported translation.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate)
        translation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, [""],
            is_imported=True, lock_timestamp=None)

        # Importing an empty translation should not create a new record
        # in the database.
        self.assertEquals(translation, None)

    def test_DeactivatingCurrentTranslation(self):
        # Deactivating replace existing is_current translation,
        # stores an empty translation in the database.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate)
        translation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, ["active translation"],
            is_imported=False, lock_timestamp=None)
        deactivation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, [u""],
            is_imported=False, lock_timestamp=self.now)
        current_message = potmsgset.getCurrentTranslationMessage(
            self.potemplate, self.serbian)

        # Storing empty translation should deactivate current
        # translation message.
        self.assertEquals(deactivation, current_message)

    def test_DeactivatingImportedTranslation(self):
        # When an empty translation comes from import, it is
        # ignored when there IS a previous is_imported translation,
        # and previous translation is marked as not being is_imported anymore.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate)
        translation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, ["imported translation"],
            is_imported=True, lock_timestamp=None)
        deactivation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, [""],
            is_imported=True, lock_timestamp=self.now)
        imported_message = potmsgset.getImportedTranslationMessage(
            self.potemplate, self.serbian)
        current_message = potmsgset.getCurrentTranslationMessage(
            self.potemplate, self.serbian)

        # Empty is_imported message should not be imported.
        self.assertEquals(deactivation, None)
        # Existing is_imported message should be unset.
        self.assertEquals(imported_message, None)
        # Old is_imported message is not is_current either.
        self.assertEquals(current_message, None)

    def test_DeactivatingImportedNotCurrentTranslation(self):
        # When an empty translation comes from import, and there is a
        # previous is_imported translation and another is_current translation,
        # only is_imported translation is unset.
        potmsgset = self.factory.makePOTMsgSet(self.potemplate)
        imported_message = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, ["imported translation"],
            is_imported=True, lock_timestamp=None)
        launchpad_message = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, ["launchpad translation"],
            is_imported=False, lock_timestamp=self.now)
        deactivation = potmsgset.updateTranslation(
            self.pofile_sr, self.pofile_sr.owner, [""],
            is_imported=True, lock_timestamp=self.now)
        new_imported_message = potmsgset.getImportedTranslationMessage(
            self.potemplate, self.serbian)
        current_message = potmsgset.getCurrentTranslationMessage(
            self.potemplate, self.serbian)

        # Current message should not be changed.
        self.assertEquals(launchpad_message, current_message)
        # Existing is_imported message should be unset.
        self.assertEquals(new_imported_message, None)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
