# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `SpecificationDepCandidatesVocabulary`.

There is also a doctest in specificationdepcandidates.txt.
"""

__metaclass__ = type

from zope.schema.vocabulary import getVocabularyRegistry

from canonical.launchpad.webapp import canonical_url
from canonical.testing import DatabaseFunctionalLayer

from lp.testing import TestCaseWithFactory


class TestSpecificationDepCandidatesVocabulary(TestCaseWithFactory):
    """Tests for `SpecificationDepCandidatesVocabulary`."""

    layer = DatabaseFunctionalLayer

    def getVocabularyForSpec(self, spec):
        return getVocabularyRegistry().get(
            spec, name='SpecificationDepCandidates')

    def test_getTermByToken_by_name_for_product(self):
        # Calling getTermByToken for a dependency vocab for a spec from a
        # product with the name of an acceptable candidate spec returns the
        # term for the candidate
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        candidate = self.factory.makeSpecification(product=product)
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(candidate.name).value)

    def test_getTermByToken_by_name_for_distro(self):
        # Calling getTermByToken for a dependency vocab for a spec from a
        # distribution with the name of an acceptable candidate spec returns
        # the term for the candidate
        distro = self.factory.makeDistribution()
        spec = self.factory.makeSpecification(distribution=distro)
        candidate = self.factory.makeSpecification(distribution=distro)
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(candidate.name).value)

    def test_getTermByToken_by_url_for_product(self):
        # Calling getTermByToken with the full URL for a spec on a product
        # returns that spec, irrespective of the context's target.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification(
            product=self.factory.makeProduct())
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(canonical_url(candidate)).value)

    def test_getTermByToken_by_url_for_distro(self):
        # Calling getTermByToken with the full URL for a spec on a
        # distribution returns that spec, irrespective of the context's
        # target.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification(
            distribution=self.factory.makeDistribution())
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(canonical_url(candidate)).value)

    def test_getTermByToken_lookup_error_on_nonsense(self):
        # getTermByToken with the a string that does not name a spec raises
        # LookupError.
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(
            LookupError, vocab.getTermByToken, self.factory.getUniqueString())

    def test_getTermByToken_lookup_error_on_url_with_invalid_pillar(self):
        # getTermByToken with the a string that looks like a blueprint URL but
        # has an invalid pillar name raises LookupError.
        spec = self.factory.makeSpecification()
        url = canonical_url(spec).replace(
            spec.target.name, self.factory.getUniqueString())
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, url)

    def test_getTermByToken_lookup_error_on_url_with_invalid_spec_name(self):
        # getTermByToken with the a string that looks like a blueprint URL but
        # has an invalid spec name raises LookupError.
        spec = self.factory.makeSpecification()
        url = canonical_url(spec).replace(
            spec.name, self.factory.getUniqueString())
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, url)

    def test_getTermByToken_by_name_disallows_blocked(self):
        # getTermByToken with the name of an candidate spec that is blocked by
        # the vocab's context raises LookupError.
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        candidate = self.factory.makeSpecification(product=product)
        candidate.createDependency(spec)
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, candidate.name)

    def test_getTermByToken_by_url_disallows_blocked(self):
        # getTermByToken with the URL of an candidate spec that is blocked by
        # the vocab's context raises LookupError.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        candidate.createDependency(spec)
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(
            LookupError, vocab.getTermByToken, canonical_url(candidate))

    def test_getTermByToken_by_name_disallows_context(self):
        # getTermByToken with the name of the vocab's context raises
        # LookupError.
        spec = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, spec.name)

    def test_getTermByToken_by_url_disallows_context(self):
        # getTermByToken with the URL of the vocab's context raises
        # LookupError.
        spec = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(
            LookupError, vocab.getTermByToken, canonical_url(spec))

    def test_getTermByToken_by_name_disallows_spec_for_other_target(self):
        # getTermByToken with the name of a spec with a different target
        # raises LookupError.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, candidate.name)

    def test_searchForTerms_by_url(self):
        # Calling searchForTerms with the URL of a valid candidate spec
        # returns just that spec.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        results = vocab.searchForTerms(canonical_url(candidate))
        self.assertEqual(1, len(results))
        self.assertEqual(candidate, list(results)[0].value)

    def test_searchForTerms_by_url_rejects_invalid(self):
        # Calling searchForTerms with the URL of a invalid candidate spec
        # returns an empty iterator.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        candidate.createDependency(spec)
        vocab = self.getVocabularyForSpec(spec)
        results = vocab.searchForTerms(canonical_url(candidate))
        self.assertEqual(0, len(results))

    def test_token_for_same_target_dep_is_name(self):
        # The 'token' part of the term for a dependency candidate that has the
        # same target is just the name of the candidate.
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        candidate = self.factory.makeSpecification(product=product)
        vocab = self.getVocabularyForSpec(spec)
        term = vocab.getTermByToken(candidate.name)
        self.assertEqual(term.token, candidate.name)

    def test_token_for_different_target_dep_is_url(self):
        # The 'token' part of the term for a dependency candidate that has a
        # different target is the canonical url of the candidate.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        term = vocab.getTermByToken(canonical_url(candidate))
        self.assertEqual(term.token, canonical_url(candidate))
