# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0102

__metaclass__ = type

import unittest

import transaction
from zope.component import getUtility

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.testing import LaunchpadZopelessLayer
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.testing import TestCaseWithFactory
from lp.testing.factory import LaunchpadObjectFactory
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
    RosettaImportStatus,
    )


class TestCanSetStatusBase(TestCaseWithFactory):
    """Base for tests that check that canSetStatus works ."""

    layer = LaunchpadZopelessLayer
    dbuser = None
    entry = None

    def setUp(self):
        """Set up context to test in."""
        super(TestCanSetStatusBase, self).setUp()

        self.queue = getUtility(ITranslationImportQueue)
        self.rosetta_experts = (
            getUtility(ILaunchpadCelebrities).rosetta_experts)
        self.productseries = self.factory.makeProductSeries()
        self.productseries.driver = self.factory.makePerson()
        self.productseries.product.driver = self.factory.makePerson()
        self.uploaderperson = self.factory.makePerson()

    def _switch_dbuser(self):
        if self.dbuser != None:
            transaction.commit()
            self.layer.switchDbUser(self.dbuser)

    def _assertCanSetStatus(self, user, entry, expected_list):
        # Helper to check for all statuses.
        # Could iterate RosettaImportStatus.items but listing them here
        # explicitly is better to read. They are sorted alphabetically.
        possible_statuses = [
            RosettaImportStatus.APPROVED,
            RosettaImportStatus.BLOCKED,
            RosettaImportStatus.DELETED,
            RosettaImportStatus.FAILED,
            RosettaImportStatus.IMPORTED,
            RosettaImportStatus.NEEDS_INFORMATION,
            RosettaImportStatus.NEEDS_REVIEW,
        ]
        self._switch_dbuser()
        # Do *not* use assertContentEqual here, as the order matters.
        self.assertEqual(expected_list,
            [entry.canSetStatus(status, user)
                 for status in possible_statuses])

    def test_canSetStatus_non_admin(self):
        # A non-privileged users cannot set any status.
        some_user = self.factory.makePerson()
        self._assertCanSetStatus(some_user, self.entry,
            #  A      B      D      F      I     NI     NR
            [False, False, False, False, False, False, False])

    def test_canSetStatus_rosetta_expert(self):
        # Rosetta experts are all-powerful, didn't you know that?
        self._assertCanSetStatus(self.rosetta_experts, self.entry,
            #  A     B     D     F     I    NI    NR
            [True, True, True, True, True, True, True])

    def test_canSetStatus_rosetta_expert_no_target(self):
        # If the entry has no import target set, even Rosetta experts
        # cannot set it to approved or imported.
        self.entry.potemplate = None
        self.entry.pofile = None
        self._assertCanSetStatus(self.rosetta_experts, self.entry,
            #  A      B     D     F     I    NI     NR
            [False, True, True, True, False, True, True])

    def test_canSetStatus_uploader(self):
        # The uploader can set some statuses.
        self._assertCanSetStatus(self.uploaderperson, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, False, True, False, False, False, True])

    def test_canSetStatus_product_owner(self):
        # The owner (maintainer) of the product gets to set Blocked as well.
        owner = self.productseries.product.owner
        self._assertCanSetStatus(owner, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def test_canSetStatus_owner_and_uploader(self):
        # Corner case: Nothing changes if the maintainer is also the uploader.
        self.productseries.product.owner = self.uploaderperson
        self._assertCanSetStatus(self.uploaderperson, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def test_canSetStatus_driver(self):
        # The driver gets the same permissions as the maintainer.
        driver = self.productseries.driver
        self._assertCanSetStatus(driver, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def test_canSetStatus_driver_and_uploader(self):
        # Corner case: Nothing changes if the driver is also the uploader.
        self.productseries.driver = self.uploaderperson
        self._assertCanSetStatus(self.uploaderperson, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def test_canSetStatus_product_driver(self):
        # The driver of the product, too.
        driver = self.productseries.product.driver
        self._assertCanSetStatus(driver, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def test_canSetStatus_product_driver_and_uploader(self):
        # Corner case: Nothing changes if the driver is also the uploader.
        self.productseries.product.driver = self.uploaderperson
        self._assertCanSetStatus(self.uploaderperson, self.entry,
            #  A      B     D     F      I     NI     NR
            [False, True, True, False, False, False, True])

    def _setUpUbuntu(self):
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.ubuntu_group_owner = self.factory.makePerson()
        self.ubuntu.translationgroup = (
            self.factory.makeTranslationGroup(self.ubuntu_group_owner))

    def test_canSetStatus_ubuntu_translation_group(self):
        # Owners of the Ubuntu translation Groups can set entries to approved
        # that are targeted to Ubuntu.
        self._setUpUbuntu()
        ubuntu_entry = self.queue.addOrUpdateEntry(
            'demo.pot', '#demo', False, self.uploaderperson,
            distroseries=self.factory.makeDistroRelease(self.ubuntu),
            sourcepackagename=self.factory.makeSourcePackageName(),
            potemplate=self.potemplate)
        self._assertCanSetStatus(self.ubuntu_group_owner, ubuntu_entry,
            #  A     B     D     F      I     NI    NR
            [True, True, True, False, False, True, True])

    def test_canSetStatus_ubuntu_translation_group_not_ubuntu(self):
        # Outside of Ubuntu, owners of the Ubuntu translation Groups have no
        # powers.
        self._setUpUbuntu()
        self._assertCanSetStatus(self.ubuntu_group_owner, self.entry,
            #  A      B      D      F      I     NI     NR
            [False, False, False, False, False, False, False])


class TestCanSetStatusPOTemplate(TestCanSetStatusBase):
    """Test canStatus applied to an entry with a POTemplate."""

    def setUp(self):
        """Create the entry to test on."""
        super(TestCanSetStatusPOTemplate, self).setUp()

        self.potemplate = self.factory.makePOTemplate(
            productseries=self.productseries)
        self.entry = self.queue.addOrUpdateEntry(
            'demo.pot', '#demo', False, self.uploaderperson,
            productseries=self.productseries, potemplate=self.potemplate)


class TestCanSetStatusPOFile(TestCanSetStatusBase):
    """Test canStatus applied to an entry with a POFile."""

    def setUp(self):
        """Create the entry to test on."""
        super(TestCanSetStatusPOFile, self).setUp()

        self.potemplate = self.factory.makePOTemplate(
            productseries=self.productseries)
        self.pofile = self.factory.makePOFile(
            'eo', potemplate=self.potemplate)
        self.entry = self.queue.addOrUpdateEntry(
            'demo.po', '#demo', False, self.uploaderperson,
            productseries=self.productseries, pofile=self.pofile)


class TestCanSetStatusPOTemplateWithQueuedUser(TestCanSetStatusPOTemplate):
    """Test handling of the status of a queue entry with 'queued' db user.

    The archive uploader needs to set (and therefore check) the status of a
    queue entry. It connects as a different database user and therefore we
    need to make sure that setStatus stays within this user's permissions.
    This is the version for POTemplate entries.
    """

    dbuser = 'queued'


class TestCanSetStatusPOFileWithQueuedUser(TestCanSetStatusPOFile):
    """Test handling of the status of a queue entry with 'queued' db user.

    The archive uploader needs to set (and therefore check) the status of a
    queue entry. It connects as a different database user and therefore we
    need to make sure that setStatus stays within this user's permissions.
    This is the version for POFile entries.
    """

    dbuser = 'queued'


class TestGetGuessedPOFile(TestCaseWithFactory):
    """Test matching of PO files with respective templates and languages."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Set up context to test in."""
        super(TestGetGuessedPOFile, self).setUp()
        self.queue = getUtility(ITranslationImportQueue)
        self.factory = LaunchpadObjectFactory()
        self.distribution = self.factory.makeDistribution('boohoo')
        self.distroseries = self.factory.makeDistroRelease(self.distribution)
        self.uploaderperson = self.factory.makePerson()

    def createSourcePackageAndPOTemplate(self, sourcepackagename, template):
        """Create and return a source package and a POTemplate.

        Creates a source package in the self.distroseries with the passed-in
        sourcepackagename, and a template in that sourcepackage named
        template with the identical translation domain.
        """
        target_sourcepackage = self.factory.makeSourcePackage(
            distroseries=self.distroseries)
        pot = self.factory.makePOTemplate(
            sourcepackagename=target_sourcepackage.sourcepackagename,
            distroseries=target_sourcepackage.distroseries,
            name=template, translation_domain=template)
        spn = self.factory.makeSourcePackageName(sourcepackagename)
        l10n_sourcepackage = self.factory.makeSourcePackage(
            sourcepackagename=spn,
            distroseries=self.distroseries)
        return (l10n_sourcepackage, pot)

    def _getGuessedPOFile(self, source_name, template_name):
        """Return new POTemplate and matched POFile for package and template.
        """
        package, pot = self.createSourcePackageAndPOTemplate(
            source_name, template_name)
        queue_entry = self.queue.addOrUpdateEntry(
            '%s.po' % template_name, template_name, True, self.uploaderperson,
            distroseries=package.distroseries,
            sourcepackagename=package.sourcepackagename)
        pofile = queue_entry.getGuessedPOFile()
        return (pot, pofile)

    def test_KDE4_language(self):
        # PO files 'something.po' in a package named like 'kde-l10n-sr'
        # belong in the 'something' translation domain as Serbian (sr)
        # translations.
        potemplate, pofile = self._getGuessedPOFile(
            'kde-l10n-sr', 'template')
        serbian = getUtility(ILanguageSet).getLanguageByCode('sr')
        self.assertEquals(potemplate, pofile.potemplate)
        self.assertEquals(serbian, pofile.language)

    def test_KDE4_language_country(self):
        # If package name is kde-l10n-engb, it needs to be mapped
        # to British English (en_GB).
        potemplate, pofile = self._getGuessedPOFile(
            'kde-l10n-engb', 'template')
        real_english = getUtility(ILanguageSet).getLanguageByCode('en_GB')
        self.assertEquals(potemplate, pofile.potemplate)
        self.assertEquals(real_english, pofile.language)

    def test_KDE4_language_variant(self):
        # If package name is kde-l10n-ca-valencia, it needs to be mapped
        # to Valencian variant of Catalan (ca@valencia).
        catalan_valencia = self.factory.makeLanguage(
            'ca@valencia', 'Catalan Valencia')
        potemplate, pofile = self._getGuessedPOFile(
            'kde-l10n-ca-valencia', 'template')
        self.assertEquals(potemplate, pofile.potemplate)
        self.assertEquals(catalan_valencia, pofile.language)


def test_suite():
    """Add only specific test cases and leave out the base case."""
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestCanSetStatusPOTemplate))
    suite.addTest(unittest.makeSuite(TestCanSetStatusPOFile))
    suite.addTest(
        unittest.makeSuite(TestCanSetStatusPOTemplateWithQueuedUser))
    suite.addTest(unittest.makeSuite(TestCanSetStatusPOFileWithQueuedUser))
    suite.addTest(unittest.makeSuite(TestGetGuessedPOFile))
    return suite

