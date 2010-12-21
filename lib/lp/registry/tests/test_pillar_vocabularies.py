# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the pillar vocabularies."""

__metaclass__ = type

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.registry.vocabularies import (
    DistributionOrProductVocabulary,
    DistributionOrProductOrProjectGroupVocabulary,
    PillarVocabularyBase,
    )
from lp.testing import (
    celebrity_logged_in,
    TestCaseWithFactory,
    )


class TestPillarVocabularyBase(TestCaseWithFactory):
    """Test that the ProductVocabulary behaves as expected."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestPillarVocabularyBase, self).setUp()
        self.vocabulary = PillarVocabularyBase()
        self.product = self.factory.makeProduct(name='orchid-snark')
        self.distribution = self.factory.makeDistribution(name='zebra-snark')
        self.project_group = self.factory.makeProject(name='apple-snark')

    def test_toTerm(self):
        # Product terms are composed of title, name, and the object.
        term = self.vocabulary.toTerm(self.product)
        title = '%s (Product)' % self.product.title
        self.assertEqual(title, term.title)
        self.assertEqual(self.product.name, term.token)
        self.assertEqual(self.product, term.value)

    def test_getTermByToken(self):
        # Tokens are case insentive because the product name is lowercase.
        term = self.vocabulary.getTermByToken('ORCHID-SNARK')
        self.assertEqual(self.product, term.value)

    def test_getTermByToken_LookupError(self):
        # getTermByToken() raises a LookupError when no match is found.
        self.assertRaises(
            LookupError,
            self.vocabulary.getTermByToken, 'does-notexist')

    def test_order_by_name(self):
        # Results are ordered by name.
        terms = self.vocabulary.searchForTerms('snark')
        result = [term.value for term in terms]
        self.assertEqual(
            [self.project_group, self.product, self.distribution], result)


class TestDistributionOrProductVocabulary(TestCaseWithFactory):
    """Test that the ProductVocabulary behaves as expected."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionOrProductVocabulary, self).setUp()
        self.vocabulary = DistributionOrProductVocabulary()
        self.product = self.factory.makeProduct(name='orchid-snark')
        self.distribution = self.factory.makeDistribution(name='zebra-snark')

    def test_inactive_products_are_discluded(self):
        # Inactive product are not in the vocabulary.
        with celebrity_logged_in('registry_experts'):
            self.product.active = False
        terms = self.vocabulary.searchForTerms('snark')
        result = [term.value for term in terms]
        self.assertEqual([self.distribution], result)
        self.assertFalse(self.product in self.vocabulary)

    def test_project_groups_are_discluded(self):
        # Project groups are not in the vocabulary.
        project_group = self.factory.makeProject(name='apple-snark')
        terms = self.vocabulary.searchForTerms('snark')
        result = [term.value for term in terms]
        self.assertEqual([self.product, self.distribution], result)
        self.assertFalse(project_group in self.vocabulary)


class TestDistributionOrProductOrProjectGroupVocabulary(TestCaseWithFactory):
    """Test for DistributionOrProductOrProjectGroupVocabulary."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionOrProductOrProjectGroupVocabulary, self).setUp()
        self.vocabulary = DistributionOrProductOrProjectGroupVocabulary()
        self.product = self.factory.makeProduct(name='orchid-snark')
        self.distribution = self.factory.makeDistribution(name='zebra-snark')
        self.project_group = self.factory.makeProject(name='apple-snark')

    def test_contains_all_pillars_active(self):
        # All active products, project groups and distributions are included.
        self.assertTrue(self.product in self.vocabulary)
        self.assertTrue(self.distribution in self.vocabulary)
        self.assertTrue(self.project_group in self.vocabulary)

    def test_inactive_products_are_discluded(self):
        # Inactive porduct are not in the vocabulary.
        with celebrity_logged_in('registry_experts'):
            self.product.active = False
        terms = self.vocabulary.searchForTerms('snark')
        result = [term.value for term in terms]
        self.assertEqual([self.project_group, self.distribution], result)
        self.assertFalse(self.product in self.vocabulary)

    def test_inactive_product_groups_are_discluded(self):
        # Inactive porject groups are not in the vocabulary.
        with celebrity_logged_in('registry_experts'):
            self.project_group.active = False
        terms = self.vocabulary.searchForTerms('snark')
        result = [term.value for term in terms]
        self.assertEqual([self.product, self.distribution], result)
        self.assertFalse(self.project_group in self.vocabulary)
