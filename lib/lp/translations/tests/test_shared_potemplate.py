# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0102

__metaclass__ = type

import unittest

from storm.exceptions import DataError
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.testing.layers import ZopelessDatabaseLayer
from lp.testing import TestCaseWithFactory
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.app.enums import ServiceUsage


class TestTranslationSharingPOTemplate(TestCaseWithFactory):
    """Test behaviour of "sharing" PO templates."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        """Set up context to test in."""
        # Create a product with two series and sharing POTemplates
        # in different series ('devel' and 'stable').
        super(TestTranslationSharingPOTemplate, self).setUp()
        self.foo = self.factory.makeProduct(
            translations_usage=ServiceUsage.LAUNCHPAD)
        self.foo_devel = self.factory.makeProductSeries(
            name='devel', product=self.foo)
        self.foo_stable = self.factory.makeProductSeries(
            name='stable', product=self.foo)

        # POTemplate is a 'sharing' one if it has the same name ('messages').
        self.devel_potemplate = self.factory.makePOTemplate(
            productseries=self.foo_devel, name="messages")
        self.stable_potemplate = self.factory.makePOTemplate(
            self.foo_stable, name="messages")

        # Create a single POTMsgSet that is used across all tests,
        # and add it to only one of the POTemplates.
        self.potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate)
        self.potmsgset.setSequence(self.devel_potemplate, 1)

    def test_getPOTMsgSets(self):
        self.potmsgset.setSequence(self.stable_potemplate, 1)

        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        stable_potmsgsets = list(self.stable_potemplate.getPOTMsgSets())

        self.assertEquals(devel_potmsgsets, [self.potmsgset])
        self.assertEquals(devel_potmsgsets, stable_potmsgsets)

    def test_getPOTMsgSetByMsgIDText(self):
        potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate,
                                               singular="Open file",
                                               sequence=2)

        # We can retrieve the potmsgset by its ID text.
        read_potmsgset = self.devel_potemplate.getPOTMsgSetByMsgIDText(
            "Open file")
        self.assertEquals(potmsgset, read_potmsgset)

    def test_getPOTMsgSetBySequence(self):
        sequence = 2
        potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate,
                                               sequence=sequence)

        # We can retrieve the potmsgset by its sequence.
        read_potmsgset = self.devel_potemplate.getPOTMsgSetBySequence(
            sequence)
        self.assertEquals(potmsgset, read_potmsgset)

        # It's still not present in different sharing PO template.
        read_potmsgset = self.stable_potemplate.getPOTMsgSetBySequence(
            sequence)
        self.assertEquals(read_potmsgset, None)

    def test_getPOTMsgSetByID(self):
        potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate,
                                               sequence=3)
        id = potmsgset.id

        # We can retrieve the potmsgset by its ID.
        read_potmsgset = self.devel_potemplate.getPOTMsgSetByID(id)
        self.assertEquals(potmsgset, read_potmsgset)

        # Getting this one in a different template doesn't work.
        read_potmsgset = self.stable_potemplate.getPOTMsgSetByID(id)
        self.assertEquals(read_potmsgset, None)

        # Nor can you get an entry with a made up ID.
        random_id = 100000 + self.factory.getUniqueInteger()
        read_potmsgset = self.devel_potemplate.getPOTMsgSetByID(random_id)
        self.assertEquals(read_potmsgset, None)

    def test_hasMessageID(self):
        naked_potemplate = removeSecurityProxy(self.devel_potemplate)
        # Let's get details we need for a POTMsgSet that is
        # already in the POTemplate.
        present_msgid_singular = self.potmsgset.msgid_singular
        present_msgid_plural = self.potmsgset.msgid_plural
        present_context = self.potmsgset.context
        has_message_id = naked_potemplate.hasMessageID(
            present_msgid_singular, present_msgid_plural, present_context)
        self.assertEquals(has_message_id, True)

    def test_hasPluralMessage(self):
        # At the moment, a POTemplate has no plural form messages.
        self.assertEquals(self.devel_potemplate.hasPluralMessage(), False)

        # Let's add a POTMsgSet with plural forms.
        plural_potmsgset = self.factory.makePOTMsgSet(self.devel_potemplate,
                                                      singular="singular",
                                                      plural="plural")
        plural_potmsgset.setSequence(self.devel_potemplate, 4)

        # Now, template contains a plural form message.
        self.assertEquals(self.devel_potemplate.hasPluralMessage(), True)

    def test_expireAllMessages(self):
        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        self.assertEquals(len(devel_potmsgsets) > 0, True)

        # Expiring all messages brings the count back to zero.
        self.devel_potemplate.expireAllMessages()
        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        self.assertEquals(len(devel_potmsgsets), 0)

        # Expiring all messages even when all are already expired still works.
        self.devel_potemplate.expireAllMessages()
        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        self.assertEquals(len(devel_potmsgsets), 0)

    def test_createPOTMsgSetFromMsgIDs(self):
        # We need a 'naked' potemplate to make use of getOrCreatePOMsgID
        # private method.
        naked_potemplate = removeSecurityProxy(self.devel_potemplate)

        # Let's create a new POTMsgSet.
        singular_text = self.factory.getUniqueString()
        msgid_singular = naked_potemplate.getOrCreatePOMsgID(singular_text)
        potmsgset = self.devel_potemplate.createPOTMsgSetFromMsgIDs(
            msgid_singular=msgid_singular)
        self.assertEquals(potmsgset.msgid_singular, msgid_singular)

        # And let's add it to the devel_potemplate.
        potmsgset.setSequence(self.devel_potemplate, 5)
        devel_potmsgsets = list(self.devel_potemplate.getPOTMsgSets())
        self.assertEquals(len(devel_potmsgsets), 2)

        # Creating it with a different context also works.
        msgid_context = self.factory.getUniqueString()
        potmsgset_context = self.devel_potemplate.createPOTMsgSetFromMsgIDs(
            msgid_singular=msgid_singular, context=msgid_context)
        self.assertEquals(potmsgset_context.msgid_singular, msgid_singular)
        self.assertEquals(potmsgset_context.context, msgid_context)

    def test_getOrCreateSharedPOTMsgSet(self):
        # Let's create a new POTMsgSet.
        singular_text = self.factory.getUniqueString()
        potmsgset = self.devel_potemplate.getOrCreateSharedPOTMsgSet(
            singular_text, None)

        # If we try to add a POTMsgSet with identical strings,
        # we get back the existing one.
        same_potmsgset = self.devel_potemplate.getOrCreateSharedPOTMsgSet(
            singular_text, None)
        self.assertEquals(potmsgset, same_potmsgset)

        # And even if we do it in the shared template, existing
        # POTMsgSet is returned.
        shared_potmsgset = self.stable_potemplate.getOrCreateSharedPOTMsgSet(
            singular_text, None)
        self.assertEquals(potmsgset, shared_potmsgset)


class TestSharingPOTemplatesByRegex(TestCaseWithFactory):
    """Isolate tests for regular expression use in SharingSubset."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestSharingPOTemplatesByRegex, self).setUp()

    def _makeAndFind(self, names, name_pattern=None):
        product = self.factory.makeProduct()
        product.official_rosetta = True
        trunk = product.getSeries('trunk')
        for name in names:
            self.factory.makePOTemplate(productseries=trunk, name=name)
        subset = getUtility(IPOTemplateSet).getSharingSubset(product=product)
        return [
            template.name
            for template in subset.getSharingPOTemplatesByRegex(name_pattern)]

    def test_getSharingPOTemplatesByRegex_baseline(self):
        # Baseline test.
        self.assertContentEqual(
            ['foo', 'foo-bar', 'foo-two'],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two'], 'foo.*'))

    def test_getSharingPOTemplatesByRegex_not_all(self):
        # A template may not match.
        self.assertContentEqual(
            ['foo-bar', 'foo-two'],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two'], 'foo-.*'))

    def test_getSharingPOTemplatesByRegex_all(self):
        # Not passing a pattern returns all templates.
        self.assertContentEqual(
            ['foo', 'foo-bar', 'foo-two'],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two']))

    def test_getSharingPOTemplatesByRegex_no_match(self):
        # A not matching pattern returns no templates.
        self.assertContentEqual(
            [],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two'], "doo.+dle"))

    def test_getSharingPOTemplatesByRegex_robustness_single_quotes(self):
        # Single quotes do not confuse the regex match.
        self.assertContentEqual(
            [],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two'], "'"))

    def test_getSharingPOTemplatesByRegex_robustness_double_quotes(self):
        # Double quotes do not confuse the regex match.
        self.assertContentEqual(
            [],
            self._makeAndFind(['foo', 'foo-bar', 'foo-two'], '"'))

    def test_getSharingPOTemplatesByRegex_robustness_backslash(self):
        # A backslash at the end could escape enclosing quotes without
        # proper escaping, leading to a SyntaxError or even a successful
        # exploit. Instead, storm should complain about an invalid expression
        # by raising DataError.
        product = self.factory.makeProduct()
        subset = getUtility(IPOTemplateSet).getSharingSubset(product=product)
        self.assertRaises(
            DataError, list, subset.getSharingPOTemplatesByRegex("foo.*\\"))


class TestMessageSharingProductPackage(TestCaseWithFactory):
    """Test message sharing between a product and a package.

    Each test uses assertStatementCount to make sure the number of SQL
    queries does not change. This was integrated here to avoid having
    a second test case just for statement counts.
    The current implementation is good and only needs one statement.
    """

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestMessageSharingProductPackage, self).setUp()

        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.hoary = self.ubuntu['hoary']
        self.warty = self.ubuntu['warty']
        self.ubuntu.translation_focus = self.hoary
        self.packagename = self.factory.makeSourcePackageName()

        self.product = self.factory.makeProduct()
        self.trunk = self.product.getSeries('trunk')
        self.stable = self.factory.makeProductSeries(
            product=self.product)

        self.templatename = self.factory.getUniqueString()
        self.trunk_template = self.factory.makePOTemplate(
            productseries=self.trunk, name=self.templatename)
        self.hoary_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.packagename,
            name=self.templatename)

        self.owner = self.factory.makePerson()
        self.potemplateset = getUtility(IPOTemplateSet)

    def _assertStatements(self, no_of_statements, resultset):
        """Assert constant number of SQL statements when iterating result set.

        This encapsulates using the 'list' function to feed the iterator to
        the assert method. This iterates the resultset, triggering SQL
        statement execution."""
        return self.assertStatementCount(no_of_statements, list, resultset)

    def test_getSharingPOTemplates_product(self):
        # Sharing templates for a product include the same templates from
        # a linked source package.
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template], templates)

    def test_getSharingPOTemplates_package(self):
        # Sharing templates for a source package include the same templates 
        # from a linked product.
        sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        sourcepackage.setPackaging(self.trunk, self.owner)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template], templates)

    def test_getSharingPOTemplates_product_multiple_series(self):
        # Sharing templates for a product include the same templates from
        # a linked source package, even from multiple product series and
        # multiple distro series.
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name=self.templatename)
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        expected_templates = [
            self.trunk_template,
            self.hoary_template,
            stable_template,
            warty_template,
            ]
        self.assertContentEqual(expected_templates, templates)

    def test_getSharingPOTemplates_package_multiple_series(self):
        # Sharing templates for a source package include the same templates 
        # from a linked product, even with multiple product series.
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name=self.templatename)
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename)
        hoary_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        hoary_sourcepackage.setPackaging(self.trunk, self.owner)
        warty_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.warty)
        warty_sourcepackage.setPackaging(self.stable, self.owner)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        expected_templates = [
            self.trunk_template,
            self.hoary_template,
            stable_template,
            warty_template,
            ]
        self.assertContentEqual(expected_templates, templates)

    def test_getSharingPOTemplates_package_name_changed(self):
        # When the name of a package changes (but not the name of the
        # template), it will still share translations if it is linked
        # to the same product.
        changed_name = self.factory.makeSourcePackageName()
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=changed_name,
            name=self.templatename)
        hoary_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        hoary_sourcepackage.setPackaging(self.trunk, self.owner)
        warty_sourcepackage = self.factory.makeSourcePackage(
            changed_name, self.warty)
        warty_sourcepackage.setPackaging(self.stable, self.owner)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template, warty_template],
            templates)

    def test_getSharingPOTemplates_many_series(self):
        # The number of queries for a call to getSharingPOTemplates must
        # remain constant.

        all_templates = [self.trunk_template, self.hoary_template]
        hoary_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        hoary_sourcepackage.setPackaging(self.trunk, self.owner)
        # Add a greater number of series and sharing templates on either side.
        seriesnames = (
            ('0.1', 'feisty'),
            ('0.2', 'gutsy'),
            ('0.3', 'hardy'),
            ('0.4', 'intrepid'),
            ('0.5', 'jaunty'),
            ('0.6', 'karmic'),
            )
        for pseries_name, dseries_name in seriesnames:
            productseries = self.factory.makeProductSeries(
                self.product, pseries_name)
            all_templates.append(self.factory.makePOTemplate(
                productseries=productseries, name=self.templatename))
            distroseries = self.factory.makeDistroSeries(
                self.ubuntu, name=dseries_name)
            all_templates.append(self.factory.makePOTemplate(
                distroseries=distroseries, sourcepackagename=self.packagename,
                name=self.templatename))
            sourcepackage = self.factory.makeSourcePackage(
                self.packagename, distroseries)
            sourcepackage.setPackaging(productseries, self.owner)
        # Don't forget warty and stable.
        all_templates.append(self.factory.makePOTemplate(
            productseries=self.stable, name=self.templatename))
        all_templates.append(self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename))
        warty_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.warty)
        warty_sourcepackage.setPackaging(self.stable, self.owner)

        # Looking from the product side.
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))
        self.assertContentEqual(all_templates, templates)

        # Looking from the sourcepackage side.
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))
        self.assertContentEqual(all_templates, templates)

    def test_getSharingPOTemplates_product_unrelated_templates(self):
        # Sharing templates for a product must not include other templates
        # from a linked source package.
        self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.packagename,
            name=self.factory.getUniqueString())
        self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.factory.getUniqueString())
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template],
            templates)

    def test_getSharingPOTemplates_product_different_names_and_series(self):
        # A product may be packaged into differently named packages in
        # different distroseries.
        warty_packagename = self.factory.makeSourcePackageName()
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=warty_packagename,
            name=self.templatename)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=warty_packagename,
            distroseries=self.warty)
        self.trunk.setPackaging(self.warty, warty_packagename, self.owner)
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template, warty_template],
            templates)

    def test_getSharingPOTemplates_package_different_products(self):
        # A package from different distroseries can be packaging different
        # products. These products may also have templates in different
        # series which are not linked to the package but have the same name.
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename)
        warty_sourcepackage = self.factory.makeSourcePackage(
                self.packagename, self.warty)
        warty_productseries = self.factory.makeProductSeries()
        warty_productseries_template = self.factory.makePOTemplate(
            productseries=warty_productseries, name=self.templatename)
        warty_sourcepackage.setPackaging(warty_productseries, self.owner)
        
        other_productseries = self.factory.makeProductSeries(
            product=warty_productseries.product)
        other_productseries_template = self.factory.makePOTemplate(
            productseries=other_productseries, name=self.templatename)

        hoary_sourcepackage = self.factory.makeSourcePackage(
                self.packagename, self.hoary)
        hoary_sourcepackage.setPackaging(self.trunk, self.owner)

        subset = self.potemplateset.getSharingSubset(
                distribution=self.ubuntu, sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        expected_templates = [
            self.hoary_template,
            self.trunk_template,
            warty_template,
            warty_productseries_template,
            other_productseries_template,
            ]
        self.assertContentEqual(expected_templates, templates)

    def test_getSharingPOTemplates_product_different_packages(self):
        # A product can be packaged in different packages which may also have
        # sharing templates in series that are not linked to this product.
        other_sourcepackagename = self.factory.makeSourcePackageName()
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=other_sourcepackagename,
            distroseries=self.warty)
        self.stable.setPackaging(
            self.warty, other_sourcepackagename, self.owner)
        other_warty_sourcepackage_template = self.factory.makePOTemplate(
            distroseries=self.warty,
            sourcepackagename=other_sourcepackagename,
            name=self.templatename)
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name=self.templatename)
        
        other_distroseries = self.factory.makeDistroSeries(
            distribution=self.ubuntu)
        other_distroseries_template = self.factory.makePOTemplate(
            distroseries=other_distroseries,
            sourcepackagename=other_sourcepackagename,
            name=self.templatename)
        
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename, distroseries=self.hoary)
        self.trunk.setPackaging(
            self.hoary, self.packagename, self.owner)

        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        expected_templates = [
            self.hoary_template,
            self.trunk_template,
            other_warty_sourcepackage_template,
            stable_template,
            other_distroseries_template,
            ]
        self.assertContentEqual(expected_templates, templates)

    def test_getSharingPOTemplates_product_different_names_same_series(self):
        # A product may be packaged into differently named packages even in
        # the same distroseries. Must use different product series, though.
        other_packagename = self.factory.makeSourcePackageName()
        other_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=other_packagename,
            name=self.templatename)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=other_packagename,
            distroseries=self.hoary)
        self.stable.setPackaging(self.hoary, other_packagename, self.owner)
        subset = self.potemplateset.getSharingSubset(product=self.product)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template, other_template],
            templates)

    def test_getSharingPOTemplates_package_unrelated_template(self):
        # Sharing templates for a source package must not include other
        # templates from a linked product.
        self.factory.makePOTemplate(
            productseries=self.trunk, name=self.factory.getUniqueString())
        self.factory.makePOTemplate(
            productseries=self.stable, name=self.factory.getUniqueString())
        sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        sourcepackage.setPackaging(self.trunk, self.owner)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template],
            templates)

    def test_getSharingPOTemplates_package_unrelated_template_linked(self):
        # Sharing templates for a source package must not include templates
        # from sourcepackages of the same name that are linked to a different
        # product.
        # TODO: This is left in here as a sanity check. It should fail once
        # the new behavior is implemented and must then be removed.
        other_productseries = self.factory.makeProductSeries()
        other_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.warty)
        other_sourcepackage.setPackaging(other_productseries, self.owner)
        other_template = self.factory.makePOTemplate(
            productseries=other_productseries, name=self.templatename)

        sourcepackage = self.factory.makeSourcePackage(
            self.packagename, self.hoary)
        sourcepackage.setPackaging(self.trunk, self.owner)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.trunk_template, self.hoary_template], templates)

        # The behavior is controlled by the translation focus of the 
        # distribution. The series in focus will be selected.
        self.ubuntu.translation_focus = self.warty
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual([other_template], templates)

    def test_getSharingPOTemplates_package_only(self):
        # Sharing templates for a source package only, is done by the 
        # sourcepackagename.
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename)
        other_series = self.factory.makeDistroSeries(self.ubuntu)
        other_template = self.factory.makePOTemplate(
            distroseries=other_series, sourcepackagename=self.packagename,
            name=self.templatename)
        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            1, subset.getSharingPOTemplates(self.templatename))

        self.assertContentEqual(
            [self.hoary_template, other_template, warty_template], templates)

    def test_getSharingPOTemplates_package_one_linked(self):
        # Once one a sourcepackage in a distroseries that is neither the
        # translation focus nor the current series is linked to a product,
        # no sharing by name is possible anymore.
        # TODO: This is left in here as a sanity check. It should fail once
        # the new behavior is implemented and must then be removed.
        self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.packagename,
            name=self.templatename)
        other_series = self.factory.makeDistroSeries(self.ubuntu)
        self.factory.makePOTemplate(
            distroseries=other_series, sourcepackagename=self.packagename,
            name=self.templatename)
        other_sourcepackage = self.factory.makeSourcePackage(
            self.packagename, other_series)
        other_sourcepackage.setPackaging(self.trunk, self.owner)

        subset = self.potemplateset.getSharingSubset(
            distribution=self.ubuntu,
            sourcepackagename=self.packagename)
        templates = self._assertStatements(
            0, subset.getSharingPOTemplates(self.templatename))

        self.assertEqual([], templates)

    def test_getOrCreateSharedPOTMsgSet_product(self):
        # Trying to create an identical POTMsgSet in a product as exists
        # in a linked sourcepackage will return the existing POTMsgset.
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.packagename,
            distroseries=self.hoary)
        self.trunk.setPackaging(self.hoary, self.packagename, self.owner)
        hoary_potmsgset = self.factory.makePOTMsgSet(
            potemplate=self.hoary_template, sequence=1)

        trunk_potmsgset = self.trunk_template.getOrCreateSharedPOTMsgSet(
                singular_text=hoary_potmsgset.singular_text,
                plural_text=hoary_potmsgset.plural_text)
        self.assertEqual(hoary_potmsgset, trunk_potmsgset)

    def test_getOrCreateSharedPOTMsgSet_package(self):
        # Trying to create an identical POTMsgSet in a product as exists
        # in a linked sourcepackage will return the existing POTMsgset.
        sourcepackage = self.factory.makeSourcePackage(
                self.packagename, self.hoary)
        sourcepackage.setPackaging(self.trunk, self.owner)
        trunk_potmsgset = self.factory.makePOTMsgSet(
            potemplate=self.trunk_template, sequence=1)

        hoary_potmsgset = self.trunk_template.getOrCreateSharedPOTMsgSet(
                singular_text=trunk_potmsgset.singular_text,
                plural_text=trunk_potmsgset.plural_text)
        self.assertEqual(trunk_potmsgset, hoary_potmsgset)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
