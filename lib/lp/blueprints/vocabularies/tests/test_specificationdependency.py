# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `SpecificationDepCandidatesVocabulary`.

There is also a doctest in specificationdepcandidates.txt.
"""

__metaclass__ = type

from zope.schema.vocabulary import getVocabularyRegistry

from canonical.testing import DatabaseFunctionalLayer

from lp.testing import TestCaseWithFactory


class TestSpecificationDepCandidatesVocabulary(TestCaseWithFactory):
    """Tests for `SpecificationDepCandidatesVocabulary`."""

    layer = DatabaseFunctionalLayer

    def getVocabularyForSpec(self, spec):
        return getVocabularyRegistry().get(
            spec, name='SpecificationDepCandidates')

    def test_getTermByToken_product(self):
        # Calling getTermByToken for a dependency vocab for a spec from a
        # product with the name of an acceptable candidate spec returns the
        # term for the candidate
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        candidate = self.factory.makeSpecification(product=product)
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(candidate.name).value)

    def test_getTermByToken_distro(self):
        # Calling getTermByToken for a dependency vocab for a spec from a
        # distribution with the name of an acceptable candidate spec returns
        # the term for the candidate
        distro = self.factory.makeDistribution()
        spec = self.factory.makeSpecification(distribution=distro)
        candidate = self.factory.makeSpecification(distribution=distro)
        vocab = self.getVocabularyForSpec(spec)
        self.assertEqual(
            candidate, vocab.getTermByToken(candidate.name).value)

    def test_getTermByToken_disallows_blocked(self):
        # getTermByToken with the name of an candidate spec that is blocked by
        # the vocab's context raises LookupError.
        product = self.factory.makeProduct()
        spec = self.factory.makeSpecification(product=product)
        candidate = self.factory.makeSpecification(product=product)
        candidate.createDependency(spec)
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, candidate.name)

    def test_getTermByToken_disallows_context(self):
        # getTermByToken with the name of the vocab's context raises
        # LookupError.
        spec = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, spec.name)

    def test_getTermByToken_disallows_spec_for_other_target(self):
        # getTermByToken with the name of a spec with a different target
        # raises LookupError.
        spec = self.factory.makeSpecification()
        candidate = self.factory.makeSpecification()
        vocab = self.getVocabularyForSpec(spec)
        self.assertRaises(LookupError, vocab.getTermByToken, candidate.name)
