# Copyright 2011-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from storm.store import Store
from testtools.matchers import (
    MatchesSetwise,
    MatchesStructure,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.enums import AccessPolicyType
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
    IAccessPolicySource,
    IAccessPolicyArtifactSource,
    )
from lp.services.features.testing import FeatureFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestBugMirrorAccessTriggers(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugMirrorAccessTriggers, self).setUp()
        self.useFixture(FeatureFixture(
            {'disclosure.allow_multipillar_private_bugs.enabled': 'true'}))

    def assertMirrored(self, bug):
        """Check that a bug has been correctly mirrored to the new schema.

        :return: A tuple of
            (AccessArtifactGrant count, AccessPolicyArtifact count) for
            additional checking.
        """
        # An AccessPolicyArtifact exists.
        artifact = getUtility(IAccessArtifactSource).find([bug]).one()
        self.assertIsNot(None, artifact.concrete_artifact)

        # There is an AccessArtifactGrant for the subscriber.
        subs = bug.getDirectSubscriptions()
        grants = list(
            getUtility(IAccessArtifactGrantSource).findByArtifact(
                [artifact]))
        self.assertThat(
            grants,
            MatchesSetwise(*[
                MatchesStructure.byEquality(
                    grantee=sub.person, grantor=sub.subscribed_by,
                    date_created=sub.date_created) for sub in subs]))
        grant_count = len(grants)

        if removeSecurityProxy(bug).security_related:
            policy_type = AccessPolicyType.EMBARGOEDSECURITY
        else:
            policy_type = AccessPolicyType.USERDATA

        # Get the relevant access policies, confirming that there's one
        # for every pillar.
        pillars = set(
            task.pillar for task in removeSecurityProxy(bug).bugtasks)
        expected_policies = list(getUtility(IAccessPolicySource).find(
            [(pillar, policy_type) for pillar in pillars]))
        self.assertEqual(len(pillars), len(expected_policies))

        # There are AccessPolicyArtifacts for each relevant policy.
        policies = self.getPoliciesForArtifact(artifact)
        self.assertContentEqual(expected_policies, policies)
        policy_count = len(policies)

        # And return some counts so the test can see we looked things up
        # properly.
        return grant_count, policy_count

    def makeBugAndPolicies(self, private=False, policy_types=None):
        if policy_types is None:
            policy_types = [
                AccessPolicyType.USERDATA, AccessPolicyType.EMBARGOEDSECURITY]
        product = self.factory.makeProduct()
        for policy_type in policy_types:
            self.factory.makeAccessPolicy(pillar=product, type=policy_type)
        bug = self.factory.makeBug(private=private, product=product)
        return removeSecurityProxy(bug)

    def getPoliciesForArtifact(self, artifact):
        return set(
            apa.policy for apa in
            getUtility(IAccessPolicyArtifactSource).findByArtifact(
                [artifact]))

    def getPolicyTypesForArtifact(self, artifact):
        return set(
            policy.type for policy in self.getPoliciesForArtifact(artifact))

    def test_public_has_nothing(self):
        bug = self.factory.makeBug(private=False)
        artifact = getUtility(IAccessArtifactSource).find([bug]).one()
        self.assertIs(None, artifact)

    def test_private(self):
        bug = self.makeBugAndPolicies(private=True)
        self.assertEqual((1, 1), self.assertMirrored(bug))

    def test_add_subscriber(self):
        bug = self.makeBugAndPolicies(private=True)
        person = self.factory.makePerson()
        bug.subscribe(person, person)
        self.assertEqual((2, 1), self.assertMirrored(bug))

    def test_remove_subscriber(self):
        bug = self.makeBugAndPolicies(private=True)
        person = self.factory.makePerson()
        bug.subscribe(person, person)
        Store.of(bug).flush()
        bug.unsubscribe(person, person)
        self.assertEqual((1, 1), self.assertMirrored(bug))

    def test_add_task(self):
        # Adding a task on a new product links its policy.
        product = self.factory.makeProduct()
        self.factory.makeAccessPolicy(
            pillar=product, type=AccessPolicyType.USERDATA)

        bug = self.makeBugAndPolicies(private=True)
        bug.addTask(bug.owner, product)
        self.assertEqual((1, 2), self.assertMirrored(bug))

    def test_remove_task(self):
        # Removing a task removes its policy.
        product = self.factory.makeProduct()
        self.factory.makeAccessPolicy(
            pillar=product, type=AccessPolicyType.USERDATA)

        bug = self.makeBugAndPolicies(private=True)
        task = bug.addTask(bug.owner, product)
        Store.of(bug).flush()
        removeSecurityProxy(task).destroySelf()
        self.assertEqual((1, 1), self.assertMirrored(bug))

    def test_make_public(self):
        bug = self.makeBugAndPolicies(private=True)
        self.assertIsNot(
            None, getUtility(IAccessArtifactSource).find([bug]).one())
        bug.private = False
        self.assertIs(
            None, getUtility(IAccessArtifactSource).find([bug]).one())

    def test_make_private(self):
        bug = self.makeBugAndPolicies(private=False)
        self.assertIs(
            None, getUtility(IAccessArtifactSource).find([bug]).one())
        bug.private = True
        self.assertIsNot(
            None, getUtility(IAccessArtifactSource).find([bug]).one())
        self.assertEqual((1, 1), self.assertMirrored(bug))

    def test_security_related(self):
        # Setting the security_related flag uses EMBARGOEDSECURITY
        # policies instead of USERDATA.
        bug = self.makeBugAndPolicies(private=True)
        [artifact] = getUtility(IAccessArtifactSource).find([bug])
        self.assertEqual((1, 1), self.assertMirrored(bug))
        self.assertContentEqual(
            [AccessPolicyType.USERDATA],
            self.getPolicyTypesForArtifact(artifact))
        bug.security_related = True
        self.assertEqual((1, 1), self.assertMirrored(bug))
        self.assertContentEqual(
            [AccessPolicyType.EMBARGOEDSECURITY],
            self.getPolicyTypesForArtifact(artifact))

    def test_productseries_task(self):
        # A productseries task causes a link to its product's policy.
        productseries = self.factory.makeProductSeries()
        self.factory.makeAccessPolicy(
            pillar=productseries.product, type=AccessPolicyType.USERDATA)

        bug = self.makeBugAndPolicies(private=True)
        bug.addTask(bug.owner, productseries)
        self.assertEqual((1, 2), self.assertMirrored(bug))
        # Adding the product doesn't increase the policy count.
        bug.addTask(bug.owner, productseries.product)
        self.assertEqual((1, 2), self.assertMirrored(bug))

    def test_distribution_task(self):
        # A distribution task causes a link to its policy.
        distro = self.factory.makeDistribution()
        self.factory.makeAccessPolicy(
            pillar=distro, type=AccessPolicyType.USERDATA)

        bug = self.makeBugAndPolicies(private=True)
        bug.addTask(bug.owner, distro)
        self.assertEqual((1, 2), self.assertMirrored(bug))

    def test_distroseries_task(self):
        # A distroseries task causes a link to its distribution's
        # policy.
        distroseries = self.factory.makeDistroSeries()
        self.factory.makeAccessPolicy(
            pillar=distroseries.distribution, type=AccessPolicyType.USERDATA)

        bug = self.makeBugAndPolicies(private=True)
        bug.addTask(bug.owner, distroseries)
        self.assertEqual((1, 2), self.assertMirrored(bug))
        # Adding the distro doesn't increase the policy count.
        bug.addTask(bug.owner, distroseries.distribution)
        self.assertEqual((1, 2), self.assertMirrored(bug))
