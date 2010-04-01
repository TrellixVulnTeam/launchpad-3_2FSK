# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Translation file from automtic builds auto approver tests."""

__metaclass__ = type

import transaction
from unittest import TestLoader

from zope.component import getUtility

from canonical.testing import LaunchpadZopelessLayer
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue, RosettaImportStatus)
from lp.testing import TestCaseWithFactory
from lp.translations.model.approver import TranslationBuildApprover


class TestTranslationBuildApprover(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        # We will always need the import queue and an importer.
        super(TestTranslationBuildApprover, self).setUp()
        self.queue = getUtility(ITranslationImportQueue)
        self.importer_person = self.factory.makePerson()

    def _makeApprovedEntries(self, series, approver, filenames):
        """Create a list of queue entries and approve them."""
        return [
            approver.approve(self.queue.addOrUpdateEntry(
                path, "#Dummy content.", False, self.importer_person,
                productseries=series))
            for path in filenames]

    def _assertStatus(self, entries, statuslist):
        """Compare a list of statuses to entries' statuses."""
        for index, entry in enumerate(entries):
            if index >= len(statuslist):
                # Repeat the last value
                status = statuslist[-1]
            else:
                status = statuslist[index]
            self.assertEqual(
                status, entry.status,
                "Entry %s was not '%s'." % (entry.path, status.title))

    def test_approve_all_new(self):
        # The happy approval case, all new templates.
        filenames = [
            'po-domain1/domain1.pot',
            'po-domain2/domain2.pot',
            'po-domain3/domain3.pot',
            ]
        series = self.factory.makeProductSeries()
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual('domain1', entries[0].potemplate.name)
        self.assertEqual('domain2', entries[1].potemplate.name)
        self.assertEqual('domain3', entries[2].potemplate.name)

    def test_approve_only_pots(self):
        # Only template files aill be approved.
        filenames = [
            'po/domain1.po',
            'po/eo.po',
            ]
        series = self.factory.makeProductSeries()
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.NEEDS_REVIEW])

    def test_approve_all_existing(self):
        # The happy approval case, all existing templates.
        filenames = [
            'po-domain1/domain1.pot',
            'po-domain2/domain2.pot',
            'po-domain3/domain3.pot',
            ]
        series = self.factory.makeProductSeries()
        domain1_pot = self.factory.makePOTemplate(
            productseries=series, name='domain1')
        domain2_pot = self.factory.makePOTemplate(
            productseries=series, name='domain2')
        domain3_pot = self.factory.makePOTemplate(
            productseries=series, name='domain3')
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual(domain1_pot, entries[0].potemplate)
        self.assertEqual(domain2_pot, entries[1].potemplate)
        self.assertEqual(domain3_pot, entries[2].potemplate)

    def test_approve_some_existing(self):
        # The happy approval case, some existing templates.
        filenames = [
            'po-domain1/domain1.pot',
            'po-domain2/domain2.pot',
            'po-domain3/domain3.pot',
            'po-domain4/domain4.pot',
            ]
        series = self.factory.makeProductSeries()
        domain1_pot = self.factory.makePOTemplate(
            productseries=series, name='domain1')
        domain2_pot = self.factory.makePOTemplate(
            productseries=series, name='domain2')
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual(domain1_pot, entries[0].potemplate)
        self.assertEqual(domain2_pot, entries[1].potemplate)
        self.assertEqual('domain3', entries[2].potemplate.name)
        self.assertEqual('domain4', entries[3].potemplate.name)

    def test_approve_generic_name_one_new(self):
        # Generic names are OK, if there is only one.
        filenames = [
            'po/messages.pot',
            ]
        product = self.factory.makeProduct(name='fooproduct')
        series = product.getSeries('trunk')
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual('fooproduct', entries[0].potemplate.name)

    def test_approve_generic_name_one_existing(self):
        # Generic names are OK, if there is only one.
        filenames = [
            'po/messages.pot',
            ]
        series = self.factory.makeProductSeries()
        pot = self.factory.makePOTemplate(productseries=series)
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual(pot, entries[0].potemplate)

    def test_approve_generic_name_multiple_files(self):
        # Generic names in combination with others don't get approved.
        filenames = [
            'po/messages.pot',
            'mydomain/mydomain.pot',
            ]
        series = self.factory.makeProductSeries()
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(
            entries,
            [RosettaImportStatus.NEEDS_REVIEW, RosettaImportStatus.APPROVED])
        self.assertEqual('mydomain', entries[1].potemplate.name)

    def test_approve_generic_name_multiple_templates(self):
        # Generic names don't get approved when more than one template exists.
        filenames = [
            'po/messages.pot',
            ]
        series = self.factory.makeProductSeries()
        pot1 = self.factory.makePOTemplate(productseries=series)
        pot2 = self.factory.makePOTemplate(productseries=series)
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.NEEDS_REVIEW])

    def test_approve_not_in_list(self):
        # A file that is not the list of filenames is not approved.
        filenames = [
            'po-domain1/domain1.pot',
            'po-domain2/domain2.pot',
            ]
        series = self.factory.makeProductSeries()
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(
            series, approver, filenames + ['po-domain3/domain3.pot'])

        self._assertStatus(
            entries, [
                RosettaImportStatus.APPROVED,
                RosettaImportStatus.APPROVED,
                RosettaImportStatus.NEEDS_REVIEW])

    def test_approve_by_path(self):
        # A file will be targeted to an existing template if the paths match.
        filenames = [
            'po-domain1/domain1.pot',
            'po-domain2/domain2.pot',
            ]
        series = self.factory.makeProductSeries()
        domain1_pot = self.factory.makePOTemplate(
            productseries=series, name='name1', path=filenames[0])
        domain2_pot = self.factory.makePOTemplate(
            productseries=series, name='name2', path=filenames[1])
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual(domain1_pot, entries[0].potemplate)
        self.assertEqual(domain2_pot, entries[1].potemplate)

    def test_approve_path_updated(self):
        # The path of an existing template will be updated with the path
        # from the entry..
        filenames = [
            'po-domain1/domain1.pot',
            ]
        series = self.factory.makeProductSeries()
        domain1_pot = self.factory.makePOTemplate(
            productseries=series, name='domain1', path='po/foo.pot')
        approver = TranslationBuildApprover(filenames, productseries=series)
        entries = self._makeApprovedEntries(series, approver, filenames)

        self._assertStatus(entries, [RosettaImportStatus.APPROVED])
        self.assertEqual(filenames[0], domain1_pot.path)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
