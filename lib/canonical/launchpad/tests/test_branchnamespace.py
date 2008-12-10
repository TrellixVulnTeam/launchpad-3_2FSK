# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for `IBranchNamespace` implementations."""

__metaclass__ = type

import unittest

from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.database.branchnamespace import (
    PackageNamespace, PersonalNamespace, ProductNamespace)
from canonical.launchpad.interfaces.branch import (
    BranchLifecycleStatus, BranchType)
from canonical.launchpad.interfaces.branchnamespace import (
    get_branch_namespace, lookup_branch_namespace, IBranchNamespace)
from canonical.launchpad.interfaces.distribution import NoSuchDistribution
from canonical.launchpad.interfaces.distroseries import NoSuchDistroSeries
from canonical.launchpad.interfaces.person import NoSuchPerson
from canonical.launchpad.interfaces.product import NoSuchProduct
from canonical.launchpad.interfaces.sourcepackagename import (
    NoSuchSourcePackageName)
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.testing import DatabaseFunctionalLayer


class NamespaceMixin:
    """Tests common to all namespace implementations.

    You might even call these 'interface tests'.
    """

    def test_provides_interface(self):
        # All branch namespaces provide IBranchNamespace.
        self.assertProvides(self.getNamespace(), IBranchNamespace)

    def test_getBranchName(self):
        # getBranchName returns the thing that would be the
        # IBranch.unique_name of a branch with that name in the namespace.
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        self.assertEqual(
            '%s/%s' % (namespace.name, branch_name),
            namespace.getBranchName(branch_name))

    def test_createBranch_right_namespace(self):
        # createBranch creates a branch in that namespace.
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        expected_unique_name = namespace.getBranchName(branch_name)
        registrant = namespace.owner
        branch = namespace.createBranch(
            BranchType.HOSTED, branch_name, registrant)
        self.assertEqual(
            expected_unique_name, branch.unique_name)

    def test_createBranch_passes_through(self):
        # createBranch takes all the arguments that IBranchSet.new takes,
        # except for the ones that define the namespace.
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        registrant = namespace.owner
        title = self.factory.getUniqueString()
        summary = self.factory.getUniqueString()
        whiteboard = self.factory.getUniqueString()
        branch = namespace.createBranch(
            BranchType.HOSTED, branch_name, registrant, url=None,
            title=title, lifecycle_status=BranchLifecycleStatus.EXPERIMENTAL,
            summary=summary, whiteboard=whiteboard)
        self.assertEqual(BranchType.HOSTED, branch.branch_type)
        self.assertEqual(branch_name, branch.name)
        self.assertEqual(registrant, branch.registrant)
        self.assertIs(None, branch.url)
        self.assertEqual(title, branch.title)
        self.assertEqual(
            BranchLifecycleStatus.EXPERIMENTAL, branch.lifecycle_status)
        self.assertEqual(summary, branch.summary)
        self.assertEqual(whiteboard, branch.whiteboard)

    def test_getBranches_no_branches(self):
        # getBranches on an IBranchNamespace returns a result set of branches
        # in that namespace. If there are no branches, the result set is
        # empty.
        namespace = self.getNamespace()
        self.assertEqual([], list(namespace.getBranches()))

    def test_getBranches_some_branches(self):
        # getBranches on an IBranchNamespace returns a result set of branches
        # in that namespace.
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        branch = namespace.createBranch(
            BranchType.HOSTED, branch_name, namespace.owner)
        self.assertEqual([branch], list(namespace.getBranches()))

    def test_getByName_default(self):
        # getByName returns the given default if there is no branch in the
        # namespace with that name.
        namespace = self.getNamespace()
        default = object()
        match = namespace.getByName(self.factory.getUniqueString(), default)
        self.assertIs(default, match)

    def test_getByName_default_is_none(self):
        # The default 'default' return value is None.
        namespace = self.getNamespace()
        match = namespace.getByName(self.factory.getUniqueString())
        self.assertIs(None, match)

    def test_getByName_matches(self):
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        branch = namespace.createBranch(
            BranchType.HOSTED, branch_name, namespace.owner)
        match = namespace.getByName(branch_name)
        self.assertEqual(branch, match)

    def test_isNameUsed_not(self):
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        self.assertEqual(False, namespace.isNameUsed(name))

    def test_isNameUsed_yes(self):
        namespace = self.getNamespace()
        branch_name = self.factory.getUniqueString()
        branch = namespace.createBranch(
            BranchType.HOSTED, branch_name, namespace.owner)
        self.assertEqual(True, namespace.isNameUsed(branch_name))

    def test_findUnusedName_unused(self):
        # findUnusedName returns the given name if that name is not used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        unused_name = namespace.findUnusedName(name)
        self.assertEqual(name, unused_name)

    def test_findUnusedName_used(self):
        # findUnusedName returns the given name with a numeric suffix if its
        # already used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        namespace.createBranch(BranchType.HOSTED, name, namespace.owner)
        unused_name = namespace.findUnusedName(name)
        self.assertEqual('%s-1' % name, unused_name)

    def test_findUnusedName_used_twice(self):
        # findUnusedName returns the given name with a numeric suffix if its
        # already used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        namespace.createBranch(BranchType.HOSTED, name, namespace.owner)
        namespace.createBranch(
            BranchType.HOSTED, name + '-1', namespace.owner)
        unused_name = namespace.findUnusedName(name)
        self.assertEqual('%s-2' % name, unused_name)

    def test_createBranchWithPrefix_unused(self):
        # createBranch with prefix creates a branch with the same name as the
        # given prefix if there's no branch with that name already.
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        branch = namespace.createBranchWithPrefix(
            BranchType.HOSTED, name, namespace.owner)
        self.assertEqual(name, branch.name)

    def test_createBranchWithPrefix_used(self):
        # createBranch with prefix creates a branch with the same name as the
        # given prefix if there's no branch with that name already.
        namespace = self.getNamespace()
        name = self.factory.getUniqueString()
        namespace.createBranch(BranchType.HOSTED, name, namespace.owner)
        branch = namespace.createBranchWithPrefix(
            BranchType.HOSTED, name, namespace.owner)
        self.assertEqual(name + '-1', branch.name)


class TestPersonalNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `PersonalNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self):
        return get_branch_namespace(person=self.factory.makePerson())

    def test_name(self):
        # A personal namespace has branches with names starting with
        # ~foo/+junk.
        person = self.factory.makePerson()
        namespace = PersonalNamespace(person)
        self.assertEqual('~%s/+junk' % person.name, namespace.name)

    def test_owner(self):
        # The person passed to a personal namespace is the owner.
        person = self.factory.makePerson()
        namespace = PersonalNamespace(person)
        self.assertEqual(person, namespace.owner)


class TestProductNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `ProductNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self):
        return get_branch_namespace(
            person=self.factory.makePerson(),
            product=self.factory.makeProduct())

    def test_name(self):
        # A product namespace has branches with names starting with ~foo/bar.
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = ProductNamespace(person, product)
        self.assertEqual(
            '~%s/%s' % (person.name, product.name), namespace.name)

    def test_owner(self):
        # The person passed to a product namespace is the owner.
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = ProductNamespace(person, product)
        self.assertEqual(person, namespace.owner)


class TestPackageNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `PackageNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self):
        return get_branch_namespace(
            person=self.factory.makePerson(),
            distroseries=self.factory.makeDistroRelease(),
            sourcepackagename=self.factory.makeSourcePackageName())

    def test_name(self):
        # A package namespace has branches that start with
        # ~foo/ubuntu/spicy/packagename.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = PackageNamespace(person, distroseries, sourcepackagename)
        self.assertEqual(
            '~%s/%s/%s/%s' % (
                person.name, distroseries.distribution.name,
                distroseries.name, sourcepackagename.name),
            namespace.name)

    def test_owner(self):
        # The person passed to a package namespace is the owner.
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = PackageNamespace(person, distroseries, sourcepackagename)
        self.assertEqual(person, namespace.owner)


class TestGetNamespace(TestCaseWithFactory):
    """Tests for `get_namespace`."""

    layer = DatabaseFunctionalLayer

    def test_get_personal(self):
        person = self.factory.makePerson()
        namespace = get_branch_namespace(person=person)
        self.assertIsInstance(namespace, PersonalNamespace)

    def test_get_product(self):
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = get_branch_namespace(person=person, product=product)
        self.assertIsInstance(namespace, ProductNamespace)

    def test_get_package(self):
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = get_branch_namespace(
            person=person, distroseries=distroseries,
            sourcepackagename=sourcepackagename)
        self.assertIsInstance(namespace, PackageNamespace)

    def test_lookup_personal(self):
        # lookup_branch_namespace returns a personal namespace if given a junk
        # path.
        person = self.factory.makePerson()
        namespace = lookup_branch_namespace('~%s/+junk' % person.name)
        self.assertIsInstance(namespace, PersonalNamespace)
        self.assertEqual(person, namespace.owner)

    def test_lookup_personal_not_found(self):
        # lookup_branch_namespace raises NoSuchPerson error if the given
        # person doesn't exist.
        self.assertRaises(
            NoSuchPerson, lookup_branch_namespace, '~no-such-person/+junk')

    def test_lookup_product(self):
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        namespace = lookup_branch_namespace(
            '~%s/%s' % (person.name, product.name))
        self.assertIsInstance(namespace, ProductNamespace)
        self.assertEqual(person, namespace.owner)
        self.assertEqual(product, removeSecurityProxy(namespace).product)

    def test_lookup_product_not_found(self):
        person = self.factory.makePerson()
        self.assertRaises(
            NoSuchProduct, lookup_branch_namespace,
            '~%s/no-such-product' % person.name)

    def test_lookup_package(self):
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        namespace = lookup_branch_namespace(
            '~%s/%s/%s/%s' % (
                person.name, distroseries.distribution.name,
                distroseries.name, sourcepackagename.name))
        self.assertIsInstance(namespace, PackageNamespace)
        self.assertEqual(person, namespace.owner)
        namespace = removeSecurityProxy(namespace)
        self.assertEqual(distroseries, namespace.distroseries)
        self.assertEqual(sourcepackagename, namespace.sourcepackagename)

    def test_lookup_package_no_distribution(self):
        person = self.factory.makePerson()
        self.assertRaises(
            NoSuchDistribution, lookup_branch_namespace,
            '~%s/no-such-distro/whocares/whocares' % person.name)

    def test_lookup_package_no_distroseries(self):
        person = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        self.assertRaises(
            NoSuchDistroSeries, lookup_branch_namespace,
            '~%s/%s/no-such-series/whocares/whocares'
            % (person.name, distribution.name))

    def test_lookup_package_no_source_package(self):
        person = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        self.assertRaises(
            NoSuchSourcePackageName, lookup_branch_namespace,
            '~%s/%s/%s/no-such-spn' % (
                person.name, distroseries.distribution.name,
                distroseries.name))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

