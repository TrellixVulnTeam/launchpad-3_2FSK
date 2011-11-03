# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from storm.store import Store
from testtools.matchers import MatchesStructure
from zope.component import getUtility

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.registry.interfaces.accesspolicy import (
    IAccessPolicy,
    IAccessPolicyArtifact,
    IAccessPolicyArtifactSource,
    IAccessPolicyGrant,
    IAccessPolicyGrantSource,
    IAccessPolicySource,
    )
from lp.testing import TestCaseWithFactory
from lp.testing.matchers import Provides


class TestAccessPolicy(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessPolicy(), Provides(IAccessPolicy))

    def test_pillar(self):
        product = self.factory.makeProduct()
        policy = self.factory.makeAccessPolicy(pillar=product)
        self.assertEqual(product, policy.pillar)


class TestAccessPolicySource(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_create_for_product(self):
        product = self.factory.makeProduct()
        name = self.factory.getUniqueUnicode()
        display_name = self.factory.getUniqueUnicode()
        policy = getUtility(IAccessPolicySource).create(
            product, name, display_name)
        self.assertThat(
            policy,
            MatchesStructure.byEquality(
                pillar=product,
                name=name,
                display_name=display_name))

    def test_getByID(self):
        # getByPillarAndName finds the right policy.
        policy = self.factory.makeAccessPolicy()
        # Flush so we get an ID.
        Store.of(policy).flush()
        self.assertEqual(
            policy, getUtility(IAccessPolicySource).getByID(policy.id))

    def test_getByID_nonexistent(self):
        # getByPillarAndName returns None if the policy doesn't exist.
        self.assertIs(
            None,
            getUtility(IAccessPolicySource).getByID(
                self.factory.getUniqueInteger()))

    def test_getByPillarAndName(self):
        # getByPillarAndName finds the right policy.
        product = self.factory.makeProduct()
        name = self.factory.getUniqueUnicode()
        # Create a policy with the desired attributes, and another
        # random one.
        policy = self.factory.makeAccessPolicy(
            pillar=product, name=name)
        self.factory.makeAccessPolicy()
        self.assertEqual(
            policy,
            getUtility(IAccessPolicySource).getByPillarAndName(product, name))

    def test_getByPillarAndName_nonexistent(self):
        # getByPillarAndName returns None if the policy doesn't exist.
        # Create policy identifiers, and an unrelated policy.
        self.factory.makeAccessPolicy()
        product = self.factory.makeProduct()
        name = self.factory.getUniqueUnicode()
        self.assertIs(
            None,
            getUtility(IAccessPolicySource).getByPillarAndName(product, name))

    def test_findByPillar(self):
        # findByPillar finds only the relevant policies.
        product = self.factory.makeProduct()
        policies = [
            self.factory.makeAccessPolicy(pillar=product) for i in range(3)]
        self.factory.makeAccessPolicy()
        self.assertContentEqual(
            policies,
            getUtility(IAccessPolicySource).findByPillar(product))


class TestAccessPolicyArtifact(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessPolicyArtifact(),
            Provides(IAccessPolicyArtifact))


class TestAccessPolicyArtifactSourceOnce(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_ensure_other_fails(self):
        # ensure() rejects unsupported objects.
        self.assertRaises(
            AssertionError,
            getUtility(IAccessPolicyArtifactSource).ensure,
            self.factory.makeProduct())


class BaseAccessPolicyArtifactTests:
    layer = DatabaseFunctionalLayer

    def getConcreteArtifact(self):
        raise NotImplementedError()

    def test_ensure(self):
        # ensure() creates an abstract artifact which maps to the
        # concrete one.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessPolicyArtifactSource).ensure(concrete)
        Store.of(abstract).flush()
        self.assertEqual(concrete, abstract.concrete_artifact)

    def test_ensure_twice(self):
        # ensure() will reuse an existing matching abstract artifact if
        # it exists.
        concrete = self.getConcreteArtifact()
        abstract = getUtility(IAccessPolicyArtifactSource).ensure(concrete)
        Store.of(abstract).flush()
        self.assertEqual(
            abstract.id,
            getUtility(IAccessPolicyArtifactSource).ensure(concrete).id)


class TestAccessPolicyArtifactBranch(BaseAccessPolicyArtifactTests,
                                     TestCaseWithFactory):

    def getConcreteArtifact(self):
        return self.factory.makeBranch()


class TestAccessPolicyArtifactBug(BaseAccessPolicyArtifactTests,
                                  TestCaseWithFactory):

    def getConcreteArtifact(self):
        return self.factory.makeBug()


class TestAccessPolicyGrant(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        self.assertThat(
            self.factory.makeAccessPolicyGrant(),
            Provides(IAccessPolicyGrant))

    def test_concrete_artifact(self):
        bug = self.factory.makeBug()
        abstract = self.factory.makeAccessPolicyArtifact(bug)
        grant = self.factory.makeAccessPolicyGrant(
            abstract_artifact=abstract)
        self.assertEqual(bug, grant.concrete_artifact)

    def test_no_concrete_artifact(self):
        grant = self.factory.makeAccessPolicyGrant(
            abstract_artifact=None)
        self.assertIs(None, grant.concrete_artifact)


class TestAccessPolicyGrantSource(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_grant_for_policy(self):
        policy = self.factory.makeAccessPolicy()
        person = self.factory.makePerson()
        grant = getUtility(IAccessPolicyGrantSource).grant(
            person, policy)
        self.assertThat(
            grant,
            MatchesStructure.byEquality(
                person=person,
                policy=policy,
                abstract_artifact=None,
                concrete_artifact=None))

    def test_grant_with_artifact(self):
        policy = self.factory.makeAccessPolicy()
        person = self.factory.makePerson()
        artifact = self.factory.makeAccessPolicyArtifact()
        grant = getUtility(IAccessPolicyGrantSource).grant(
            person, policy, artifact)
        self.assertThat(
            grant,
            MatchesStructure.byEquality(
                person=person,
                policy=policy,
                abstract_artifact=artifact,
                concrete_artifact=artifact.concrete_artifact))

    def test_getByID(self):
        # getByID finds the right grant.
        grant = self.factory.makeAccessPolicyGrant()
        # Flush so we get an ID.
        Store.of(grant).flush()
        self.assertEqual(
            grant,
            getUtility(IAccessPolicyGrantSource).getByID(grant.id))

    def test_getByID_nonexistent(self):
        # getByID returns None if the grant doesn't exist.
        self.assertIs(
            None,
            getUtility(IAccessPolicyGrantSource).getByID(
                self.factory.getUniqueInteger()))

    def test_findByPolicy(self):
        # findByPolicy finds only the relevant grants.
        policy = self.factory.makeAccessPolicy()
        grants = [
            self.factory.makeAccessPolicyGrant(policy=policy)
            for i in range(3)]
        self.factory.makeAccessPolicyGrant()
        self.assertContentEqual(
            grants,
            getUtility(IAccessPolicyGrantSource).findByPolicy(policy))
