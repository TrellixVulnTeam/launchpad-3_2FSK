# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.app.enums import ServiceUsage
from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.testing import TestCaseWithFactory
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.model.pofile import DummyPOFile
from lp.translations.model.potemplate import (
    get_pofiles_for,
    POTemplateSet,
    )


class TestPOTemplate(TestCaseWithFactory):
    """Test POTemplate functions not covered by doctests."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.potemplate = removeSecurityProxy(self.factory.makePOTemplate(
            translation_domain = "testdomain"))

    def test_composePOFilePath(self):
        esperanto = getUtility(ILanguageSet).getLanguageByCode('eo')
        self.potemplate.path = "testdir/messages.pot"
        expected = "testdir/testdomain-eo.po"
        result = self.potemplate._composePOFilePath(esperanto)
        self.failUnlessEqual(expected, result,
            "_composePOFilePath does not create a correct file name with "
            "directory and language code. "
            "(Expected: '%s' Got: '%s')" % (expected, result))

        self.potemplate.path = "testdir/messages.pot"
        expected = "testdir/testdomain-eo@variant.po"
        esperanto_variant = self.factory.makeLanguage(
            'eo@variant', 'Esperanto Variant')
        result = self.potemplate._composePOFilePath(esperanto_variant)
        self.failUnlessEqual(expected, result,
            "_composePOFilePath does not create a correct file name with "
            "directory, language code and variant. "
            "(Expected: '%s' Got: '%s')" % (expected, result))

        self.potemplate.path = "/messages.pot"
        expected = "/testdomain-eo.po"
        result = self.potemplate._composePOFilePath(esperanto)
        self.failUnlessEqual(expected, result,
            "_composePOFilePath does not create a correct file name with "
            "leading slash and language code. "
            "(Expected: '%s' Got: '%s')" % (expected, result))

        self.potemplate.path = "messages.pot"
        expected = "testdomain-eo.po"
        result = self.potemplate._composePOFilePath(esperanto)
        self.failUnlessEqual(expected, result,
            "_composePOFilePath does not create a correct file name with "
            "missing directory and language code. "
            "(Expected: '%s' Got: '%s')" % (expected, result))

    def test_getDummyPOFile_no_existing_pofile(self):
        # Test basic behaviour of getDummyPOFile.
        language = self.factory.makeLanguage('sr@test')
        dummy = self.potemplate.getDummyPOFile(language)
        self.assertEquals(DummyPOFile, type(dummy))

    def test_getDummyPOFile_with_existing_pofile(self):
        # Test that getDummyPOFile fails when trying to get a DummyPOFile
        # where a POFile already exists for that language.
        language = self.factory.makeLanguage('sr@test')
        pofile = self.potemplate.newPOFile(language.code)
        self.assertRaises(
            AssertionError, self.potemplate.getDummyPOFile, language)

    def test_getDummyPOFile_with_existing_pofile_no_check(self):
        # Test that getDummyPOFile succeeds when trying to get a DummyPOFile
        # where a POFile already exists for that language when
        # check_for_existing=False is passed in.
        language = self.factory.makeLanguage('sr@test')
        pofile = self.potemplate.newPOFile(language.code)
        # This is just "assertNotRaises".
        dummy = self.potemplate.getDummyPOFile(language,
                                               check_for_existing=False)
        self.assertEquals(DummyPOFile, type(dummy))

    def test_getTranslationCredits(self):
        # getTranslationCredits returns only translation credits.
        self.factory.makePOTMsgSet(self.potemplate, sequence=1)
        gnome_credits = self.factory.makePOTMsgSet(
            self.potemplate, sequence=2, singular=u"translator-credits")
        kde_credits = self.factory.makePOTMsgSet(
            self.potemplate, sequence=3,
            singular=u"Your emails", context=u"EMAIL OF TRANSLATORS")
        self.factory.makePOTMsgSet(self.potemplate, sequence=4)

        self.assertContentEqual([gnome_credits, kde_credits],
                                self.potemplate.getTranslationCredits())

    def test_awardKarma(self):
        person = self.factory.makePerson()
        template = self.factory.makePOTemplate()
        karma_listener = self.installKarmaRecorder(
            person=person, product=template.product)
        action = 'translationsuggestionadded'

        # This is not something that browser code or scripts should do,
        # so we go behind the proxy.
        removeSecurityProxy(template).awardKarma(person, action)

        karma_events = karma_listener.karma_events
        self.assertEqual(1, len(karma_events))
        self.assertEqual(action, karma_events[0].action.name)


class EquivalenceClassTestMixin:
    """Helper for POTemplate equivalence class tests."""

    def _compareResult(self, expected, actual):
        """Compare equivalence-classes set to expectations.

        This ignores the ordering of templates in an equivalence class.
        A separate test looks at ordering.
        """
        self.assertEqual(set(actual.iterkeys()), set(expected.iterkeys()))
        for key, value in actual.iteritems():
            self.assertEqual(set(value), set(expected[key]))


class TestProductTemplateEquivalenceClasses(TestCaseWithFactory,
                                            EquivalenceClassTestMixin):
    """Which templates in Products will and will not share messages."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductTemplateEquivalenceClasses, self).setUp()
        self.product = self.factory.makeProduct()
        self.trunk = self.product.getSeries('trunk')
        self.stable = self.factory.makeProductSeries(
            product=self.product)
        self.subset = getUtility(IPOTemplateSet).getSharingSubset(
            product=self.product)

    def test_ProductTemplateEquivalence(self):
        # Within a product, two identically named templates form an
        # equivalence class.
        trunk_template = self.factory.makePOTemplate(
            productseries=self.trunk, name='foo')
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name='foo')

        classes = self.subset.groupEquivalentPOTemplates()
        expected = {('foo', None): [trunk_template, stable_template]}
        self._compareResult(expected, classes)

    def test_DifferentlyNamedProductTemplatesAreNotEquivalent(self):
        # Two differently-named templates in a product do not form an
        # equivalence class.
        trunk_template = self.factory.makePOTemplate(
            productseries=self.trunk, name='foo')
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name='bar')

        classes = self.subset.groupEquivalentPOTemplates()
        expected = {
            ('foo', None): [trunk_template],
            ('bar', None): [stable_template],
        }
        self._compareResult(expected, classes)

    def test_NoEquivalenceAcrossProducts(self):
        # Two identically-named templates in different products do not
        # form an equivalence class.
        external_series = self.factory.makeProductSeries()
        template1 = self.factory.makePOTemplate(
            productseries=self.trunk, name='foo')
        template2 = self.factory.makePOTemplate(
            productseries=external_series, name='foo')

        classes = self.subset.groupEquivalentPOTemplates()
        expected = {('foo', None): [template1]}
        self._compareResult(expected, classes)

        external_subset = getUtility(IPOTemplateSet).getSharingSubset(
            product=external_series.product)
        classes = external_subset.groupEquivalentPOTemplates()
        expected = {('foo', None): [template2]}
        self._compareResult(expected, classes)

    def test_GetSharingPOTemplates(self):
        # getSharingTemplates simply returns a list of sharing templates.
        trunk_template = self.factory.makePOTemplate(
            productseries=self.trunk, name='foo')
        stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name='foo')
        other_stable_template = self.factory.makePOTemplate(
            productseries=self.stable, name='foo-other')

        templates = set(list(self.subset.getSharingPOTemplates('foo')))
        self.assertEqual(set([trunk_template, stable_template]), templates)


class TestDistroTemplateEquivalenceClasses(TestCaseWithFactory,
                                           EquivalenceClassTestMixin):
    """Which templates in Distributions will and will not share messages."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistroTemplateEquivalenceClasses, self).setUp()
        self.ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        self.hoary = self.ubuntu['hoary']
        self.warty = self.ubuntu['warty']
        self.package = self.factory.makeSourcePackageName()

    def test_PackageTemplateEquivalence(self):
        # Two identically-named templates in the same source package in
        # different releases of the same distribution form an
        # equivalence class.
        hoary_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.package,
            name='foo')
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.package,
            name='foo')

        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu, sourcepackagename=self.package)
        classes = subset.groupEquivalentPOTemplates()

        expected = {
            ('foo', self.package.name): [hoary_template, warty_template],
        }
        self._compareResult(expected, classes)

    def test_DifferentlyNamedDistroTemplatesAreNotEquivalent(self):
        # Two differently-named templates in a distribution package do
        # not form an equivalence class.
        hoary_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.package,
            name='foo')
        warty_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.package,
            name='bar')

        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu, sourcepackagename=self.package)
        classes = subset.groupEquivalentPOTemplates()

        expected = {
            ('foo', self.package.name): [hoary_template],
            ('bar', self.package.name): [warty_template],
        }
        self._compareResult(expected, classes)

    def test_NoEquivalenceAcrossPackages(self):
        # Two identically-named templates in the same distribution do
        # not form an equivalence class if they don't have the same
        # source package name.
        other_package = self.factory.makeSourcePackageName()
        our_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.package,
            name='foo')
        other_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=other_package,
            name='foo')

        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu)
        classes = subset.groupEquivalentPOTemplates()

        self.assertTrue(('foo', self.package.name) in classes)
        self.assertEqual(classes[('foo', self.package.name)], [our_template])
        self.assertTrue(('foo', other_package.name) in classes)
        self.assertEqual(
            classes[('foo', other_package.name)], [other_template])

    def test_EquivalenceByNamePattern(self):
        # We can obtain equivalence classes for a distribution by
        # template name pattern.
        unique_name = (
            'krungthepmahanakornamornrattanakosinmahintaramahadilok-etc')
        bangkok_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.package,
            name=unique_name)

        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu)
        classes = subset.groupEquivalentPOTemplates(
            name_pattern='krungthepmahanakorn.*-etc')

        expected = {
            (unique_name, self.package.name): [bangkok_template],
        }
        self._compareResult(expected, classes)

    def _test_GetSharingPOTemplates(self, template_name, not_matching_name):
        # getSharingTemplates simply returns a list of sharing templates.
        warty_template = self.factory.makePOTemplate(
            distroseries=self.hoary, sourcepackagename=self.package,
            name=template_name)
        hoary_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.package,
            name=template_name)
        other_hoary_template = self.factory.makePOTemplate(
            distroseries=self.warty, sourcepackagename=self.package,
            name=not_matching_name)
        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu, sourcepackagename=self.package)

        templates = set(list(subset.getSharingPOTemplates(template_name)))
        self.assertEqual(set([warty_template, hoary_template]), templates)

    def test_GetSharingPOTemplates(self):
        # getSharingTemplates returns all sharing templates named foo.
        self._test_GetSharingPOTemplates('foo', 'foo-other')

    def test_GetSharingPOTemplates_special_name(self):
        # Valid template names may also contain '+', '-' and '.' .
        # But they must not be interpreted as regular expressions.
        template_name = 'foo-bar.baz+'
        # This name would match if the template_name was interpreted as a
        # regular expression
        not_matching_name = 'foo-barybazz'
        self._test_GetSharingPOTemplates(template_name, not_matching_name)

    def test_GetSharingPOTemplates_NoSourcepackagename(self):
        # getSharingPOTemplates needs a sourcepackagename to be set.
        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.ubuntu)

        self.assertRaises(AssertionError, subset.getSharingPOTemplates, 'foo')


class TestTemplatePrecedence(TestCaseWithFactory):
    """Which of a set of "equivalent" `POTMsgSet`s is "representative." """
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestTemplatePrecedence, self).setUp(user='mark@example.com')
        self.product = self.factory.makeProduct(
            translations_usage=ServiceUsage.LAUNCHPAD)
        self.trunk = self.product.getSeries('trunk')
        self.one_dot_oh = self.factory.makeProductSeries(
            product=self.product, name='one')
        self.two_dot_oh = self.factory.makeProductSeries(
            product=self.product, name='two')
        self.trunk_template = self.factory.makePOTemplate(
            productseries=self.trunk, name='trunk')
        self.one_dot_oh_template = self.factory.makePOTemplate(
            productseries=self.one_dot_oh, name='one')
        self.two_dot_oh_template = self.factory.makePOTemplate(
            productseries=self.two_dot_oh, name='two')

        self.templates = [
            self.trunk_template,
            self.one_dot_oh_template,
            self.two_dot_oh_template,
            ]

        # Make sure there's another current template for every series.
        # This is to make sure that we can disable the templates we
        # care about without Product.primary_translatable ever falling
        # back on a different series and confusing our test.
        for template in self.templates:
            self.factory.makePOTemplate(productseries=template.productseries)

        self._setTranslationFocus(self.trunk)

    def _setTranslationFocus(self, focus_series):
        """Set focus_series as translation focus."""
        self.product.development_focus = focus_series
        self.assertEqual(self.product.primary_translatable, focus_series)

    def _sortTemplates(self, templates=None):
        """Order templates by precedence."""
        if templates is None:
            templates = self.templates
        return sorted(templates, cmp=POTemplateSet.compareSharingPrecedence)

    def _getPrimaryTemplate(self, templates=None):
        """Get first template in order of precedence."""
        return self._sortTemplates(templates)[0]

    def _enableTemplates(self, enable):
        """Set iscurrent flag for all templates."""
        for template in self.templates:
            template.iscurrent = enable

    def test_disabledTemplatesComeLast(self):
        # A disabled (non-current) template comes after a current one.
        candidates = [self.one_dot_oh_template, self.two_dot_oh_template]

        self.one_dot_oh_template.iscurrent = False
        self.assertEqual(
            self._getPrimaryTemplate(candidates), self.two_dot_oh_template)

        # This goes both ways, regardless of any other ordering the two
        # templates may have.
        self.one_dot_oh_template.iscurrent = True
        self.two_dot_oh_template.iscurrent = False
        self.assertEqual(
            self._getPrimaryTemplate(candidates), self.one_dot_oh_template)

    def test_focusSeriesComesFirst(self):
        # Unless disabled, a template with translation focus always
        # comes first.
        self.assertEqual(self._getPrimaryTemplate(), self.trunk_template)

        # This is the case regardless of any other ordering there
        # may be between the templates.
        self._setTranslationFocus(self.one_dot_oh)
        self.assertEqual(self._getPrimaryTemplate(), self.one_dot_oh_template)
        self._setTranslationFocus(self.two_dot_oh)
        self.assertEqual(self._getPrimaryTemplate(), self.two_dot_oh_template)

    def test_disabledTemplateComesLastDespiteFocus(self):
        # A disabled template comes after an enabled one regardless of
        # translation focus.
        self.trunk_template.iscurrent = False
        self.assertNotEqual(self._getPrimaryTemplate(), self.trunk_template)

    def test_disabledFocusBeatsOtherDisabledTemplate(self):
        # A disabled template with translation focus comes before
        # another disabled template.
        self._enableTemplates(False)
        self.assertEqual(self._getPrimaryTemplate(), self.trunk_template)

        # Both ways, regardless of any other ordering they may have.
        self._setTranslationFocus(self.one_dot_oh)
        self.assertEqual(self._getPrimaryTemplate(), self.one_dot_oh_template)

    def test_ageBreaksTie(self):
        # Of two templates that are both enabled but don't have
        # translation focus, the newest one (by id) has precedence.
        candidates = [self.one_dot_oh_template, self.two_dot_oh_template]
        self.assertEqual(
            self._getPrimaryTemplate(candidates), self.two_dot_oh_template)

    def test_ageBreaksTieWhenDisabled(self):
        # Age also acts as a tie-breaker between disabled templates.
        self._enableTemplates(False)
        self.test_ageBreaksTie()


class TestGetPOFilesFor(TestCaseWithFactory):
    """Test `get_pofiles_for`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestGetPOFilesFor, self).setUp()
        self.potemplate = self.factory.makePOTemplate()
        self.greek = getUtility(ILanguageSet).getLanguageByCode('el')

    def _makePOFile(self):
        """Produce Greek `POFile` for `self.potemplate`."""
        return self.factory.makePOFile('el', potemplate=self.potemplate)

    def test_get_pofiles_for_empty_template_list(self):
        # get_pofiles_for sensibly returns the empty list for an empty
        # template list.
        pofiles = get_pofiles_for([], self.greek)
        self.assertEqual([], pofiles)

    def test_get_pofiles_for_translated_template(self):
        # get_pofiles_for finds a POFile for a given template in a given
        # language.
        greek_pofile = self._makePOFile()
        pofiles = get_pofiles_for([self.potemplate], self.greek)
        self.assertEqual([greek_pofile], pofiles)

    def test_get_pofiles_for_untranslated_template(self):
        # If there is no POFile for a template in a language,
        # get_pofiles_for makes up a DummyPOFile.
        pofiles = get_pofiles_for([self.potemplate], self.greek)
        pofile = pofiles[0]
        self.assertTrue(isinstance(pofile, DummyPOFile))
