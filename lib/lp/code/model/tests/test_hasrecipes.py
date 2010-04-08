# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for classes that implement IHasRecipes."""

__metaclass__ = type

import unittest

from canonical.testing import DatabaseFunctionalLayer
from lp.code.interfaces.hasrecipes import IHasRecipes
from lp.testing import TestCaseWithFactory


class TestIHasRecipes(TestCaseWithFactory):
    """Test that the correct objects implement the interface."""

    layer = DatabaseFunctionalLayer

    def test_branch_implements_hasrecipes(self):
        # Branches should implement IHasRecipes.
        branch = self.factory.makeBranch()
        self.assertProvides(branch, IHasRecipes)

    def test_branch_getRecipes(self):
        # IBranch.recipes should provide all the SourcePackageRecipes attached
        # to that branch.
        base_branch = self.factory.makeBranch()
        recipe1 = self.factory.makeSourcePackageRecipe(
            None, None, None, None, None, None, base_branch)
        recipe2 = self.factory.makeSourcePackageRecipe(
            None, None, None, None, None, None, base_branch)
        recipe_ignored = self.factory.makeSourcePackageRecipe()
        self.assertEqual(2, base_branch.getRecipes().count())

    def test_person_implements_hasrecipes(self):
        # Person should implement IHasRecipes.
        person = self.factory.makeBranch()
        self.assertProvides(person, IHasRecipes)

    def test_person_getRecipes(self):
        # IPerson.getRecipes should provide all the SourcePackageRecipes
        # owned by that person.
        person = self.factory.makePerson()
        recipe1 = self.factory.makeSourcePackageRecipe(owner=person)
        recipe2 = self.factory.makeSourcePackageRecipe(owner=person)
        recipe_ignored = self.factory.makeSourcePackageRecipe()
        self.assertEqual(2, person.getRecipes().count())

    def test_product_implements_hasrecipes(self):
        # Product should implement IHasRecipes.
        product = self.factory.makeProduct()
        self.assertProvides(product, IHasRecipes)

    def test_product_getRecipes(self):
        # IProduct.recipes should provide all the SourcePackageRecipes attached
        # to that branch.
        product = self.factory.makeProduct()
        branch = self.factory.makeBranch(product=product)
        recipe1 = self.factory.makeSourcePackageRecipe(
            None, None, None, None, None, None, branch)
        recipe2 = self.factory.makeSourcePackageRecipe(
            None, None, None, None, None, None, branch)
        recipe_ignored = self.factory.makeSourcePackageRecipe()
        self.assertEqual(2, product.getRecipes().count())


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
