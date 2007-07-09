# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Tests for BranchSet."""

__metaclass__ = type

from unittest import TestCase, TestLoader

from canonical.launchpad.ftests import login, logout, ANONYMOUS, syncUpdate
from canonical.launchpad.database.branch import BranchSet
from canonical.launchpad.interfaces import (
    BranchCreationForbidden, BranchCreatorNotMemberOfOwnerTeam,
    IPersonSet, IProductSet)

from canonical.lp.dbschema import (
    BranchLifecycleStatus, BranchVisibilityRule, PersonCreationRationale,
    TeamSubscriptionPolicy)

from canonical.testing import LaunchpadFunctionalLayer

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy


class TestBranchSet(TestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        login(ANONYMOUS)
        self.product = getUtility(IProductSet).getByName('firefox')
        self.branch_set = BranchSet()

    def tearDown(self):
        logout()
        TestCase.tearDown(self)

    def test_limitedByQuantity(self):
        """When getting the latest branches for a product, we can specify the
        maximum number of branches we want to know about.
        """
        quantity = 3
        latest_branches = self.branch_set.getLatestBranchesForProduct(
            self.product, quantity)
        self.assertEqual(quantity, len(list(latest_branches)))

    def test_onlyForProduct(self):
        """getLatestBranchesForProduct returns branches only from the requested
        product.
        """
        quantity = 5
        latest_branches = self.branch_set.getLatestBranchesForProduct(
            self.product, quantity)
        self.assertEqual(
            [self.product.name] * quantity,
            [branch.product.name for branch in latest_branches])

    def test_abandonedBranchesNotIncluded(self):
        """getLatestBranchesForProduct does not include branches that have been
        abandoned, because they are not relevant for those interested in recent
        activity.
        """
        original_branches = list(
            self.branch_set.getLatestBranchesForProduct(self.product, 5))
        branch = original_branches[0]
        # XXX: JonathanLange 2007-07-06, WHITEBOXING. The anonymous user cannot
        # change branch details, so we remove the security proxy and change it.
        branch = removeSecurityProxy(branch)
        branch.lifecycle_status = BranchLifecycleStatus.ABANDONED
        syncUpdate(branch)
        latest_branches = list(
            self.branch_set.getLatestBranchesForProduct(self.product, 5))
        self.assertEqual(original_branches[1:], latest_branches)

    def test_getHostedBranchesForPerson(self):
        """The hosted branches for a person are all of the branches without
        urls that are owned by that person, or a team that the person is in.
        """
        branch_owner = getUtility(IPersonSet).get(12)
        login(branch_owner.preferredemail.email)
        try:
            branch_set = getUtility(IBranchSet)
            branches = list(
                branch_set.getHostedBranchesForPerson(branch_owner))
            expected_branches = branch_set.getBranchesForOwners(
                list(branch_owner.teams_participated_in) + [branch_owner])
            expected_branches = [
                branch for branch in expected_branches if branch.url is None]
            self.assertEqual(expected_branches, branches)
        finally:
            logout()


class BranchVisibilityPolicyTestCase(TestCase):
    """Base class for tests to make testing of branch visibility easier."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        """Setup some sample people and teams.

        The team names are: "xray", "yankee", and "zulu".

        The people are:

          * "albert", who is a member of all three teams.
          * "bob", who is a member of yankee.
          * "charlie", who is a member of zulu.
          * "doug", who is a member of no teams.
        """
        TestCase.setUp(self)
        login(ANONYMOUS)
        # Our test product.
        person_set = getUtility(IPersonSet)

        self.firefox = getUtility(IProductSet).getByName('firefox')
        # Create some test people.
        self.albert, alberts_email = person_set.createPersonAndEmail(
            'albert@code.ninja.nz', PersonCreationRationale.USER_CREATED,
            name='albert', displayname='Albert Tester')
        self.albert.setPreferredEmail(alberts_email)
        self.bob, ignored  = person_set.createPersonAndEmail(
            'bob@code.ninja.nz', PersonCreationRationale.USER_CREATED,
            name='bob', displayname='Bob Tester')
        self.charlie, ignored  = person_set.createPersonAndEmail(
            'charlie@code.ninja.nz', PersonCreationRationale.USER_CREATED,
            name='charlie', displayname='Charlie Tester')
        self.doug, ignored  = person_set.createPersonAndEmail(
            'doug@code.ninja.nz', PersonCreationRationale.USER_CREATED,
            name='doug', displayname='Doug Tester')

        self.people = (self.albert, self.bob, self.charlie, self.doug)

        # And create some test teams.
        self.xray = person_set.newTeam(
            self.albert, 'xray', 'Xray Team',
            subscriptionpolicy=TeamSubscriptionPolicy.OPEN)
        self.yankee = person_set.newTeam(
            self.albert, 'yankee', 'Yankee Team',
            subscriptionpolicy=TeamSubscriptionPolicy.OPEN)
        self.zulu = person_set.newTeam(
            self.albert, 'zulu', 'Zulu Team',
            subscriptionpolicy=TeamSubscriptionPolicy.OPEN)
        self.teams = (self.xray, self.yankee, self.zulu)

        # Set the memberships of our test people to the test teams.
        self.albert.join(self.xray)
        self.albert.join(self.yankee)
        self.albert.join(self.zulu)
        self.bob.join(self.yankee)
        self.charlie.join(self.zulu)

    def defineTeamPolicies(self, team_policies):
        """Shortcut to help define team policies."""
        for team, rule in team_policies:
            self.firefox.setBranchVisibilityTeamPolicy(team, rule)

    def assertVisibilityPolicy(self, creator, owner, private, subscriber):
        """Check the visibility policy for branch creation.

        The method _checkVisibilityPolicy of the class BranchSet is called
        when a branch is being created.  The method is responsible for checking
        the visibility policy of the product.  The visibility policy is a
        collection of team policies, where a team policy is a team and a
        visiblity rule.

        This method does not create a branch, it just checks to see that the
        creator is able to create a branch in the namespace of the owner, and
        it determins whether the branch is a public branch or a private branch.
        If the branch is to be created as a private branch, then there may be
        a team that is implicitly subscribed to the branch to give that team
        the ability to see the private branch.

        :param creator: The user creating the branch.
        :param owner: The person or team that will be the owner of the branch.
        :param private: The expected private flag value.
        :param subscriber: The expected implicit subscriber to the branch.
        """
        create_private, implicit_subscription_team = (
            BranchSet()._checkVisibilityPolicy(
            creator=creator, owner=owner, product=self.firefox))
        self.assertEqual(
            create_private, private,
            "Branch privacy doesn't match. Expected %s, got %s"
            % (private, create_private))
        self.assertEqual(
            implicit_subscription_team, subscriber,
            "Implicit subscriber doesn't match. Expected %s, got %s."
            % (getattr(subscriber, 'name', None),
               getattr(implicit_subscription_team, 'name', None)))

    def assertPublic(self, creator, owner):
        """Assert that the policy check would result in a public branch.

        :param creator: The user creating the branch.
        :param owner: The person or team that will be the owner of the branch.
        """
        self.assertVisibilityPolicy(creator, owner, False, None)

    def assertPrivateSubscriber(self, creator, owner, subscriber):
        """Assert that the policy check results in a private branch.

        :param creator: The user creating the branch.
        :param owner: The person or team that will be the owner of the branch.
        :param subscriber: The expected implicit subscriber to the branch.
        """
        self.assertVisibilityPolicy(creator, owner, True, subscriber)

    def assertPolicyCheckRaises(self, error, creator, owner):
        """Assert that the policy check raises an exception.

        :param error: The exception class that should be raised.
        :param creator: The user creating the branch.
        :param owner: The person or team that will be the owner of the branch.
        """
        self.assertRaises(
            error,
            BranchSet()._checkVisibilityPolicy,
            creator=creator, owner=owner, product=self.firefox)


class TestTeamMembership(BranchVisibilityPolicyTestCase):
    """Assert the expected team memberhsip of the test users."""

    def test_team_memberships(self):
        albert, bob, charlie, doug = self.people
        xray, yankee, zulu = self.teams
        # Albert is a member of all three teams.
        self.failUnless(albert.inTeam(xray),
                        "Albert should be in team Xray team.")
        self.failUnless(albert.inTeam(yankee),
                        "Albert should be in the Yankee.")
        self.failUnless(albert.inTeam(zulu),
                        "Albert should be in Zulu team.")
        # Bob is a member of only Yankee.
        self.failIf(bob.inTeam(xray),
                    "Bob should not be in team Xray team.")
        self.failUnless(bob.inTeam(yankee),
                        "Bob should be in the Yankee team.")
        self.failIf(bob.inTeam(zulu),
                    "Bob should not be in the Zulu team.")
        # Charlie is a member of only Zulu.
        self.failIf(charlie.inTeam(xray),
                    "Charlie should not be in team Xray team.")
        self.failIf(charlie.inTeam(yankee),
                    "Charlie should not be in the Yankee team.")
        self.failUnless(charlie.inTeam(zulu),
                        "Charlie should be in the Zulu team.")
        # Doug is not a member of any
        self.failIf(doug.inTeam(xray),
                    "Doug should not be in team Xray team.")
        self.failIf(doug.inTeam(yankee),
                    "Doug should not be in the Yankee team.")
        self.failIf(doug.inTeam(zulu),
                    "Doug should not be in the Zulu team.")


class NoPolicies(BranchVisibilityPolicyTestCase):
    """Test behaviour with no team policies defined."""

    def test_creation_where_not_team_member(self):
        """If the creator isn't a member of the owner an exception is raised."""
        self.assertPolicyCheckRaises(
            BranchCreatorNotMemberOfOwnerTeam, self.doug, self.xray)
        self.assertPolicyCheckRaises(
            BranchCreatorNotMemberOfOwnerTeam, self.albert, self.bob)

    def test_public_branch_creation(self):
        """Branches where the creator is a memeber of owner will be public."""
        albert, bob, charlie, doug = self.people
        xray, yankee, zulu = self.teams

        self.assertPublic(albert, albert)
        self.assertPublic(albert, xray)
        self.assertPublic(albert, yankee)
        self.assertPublic(albert, zulu)

        self.assertPublic(bob, bob)
        self.assertPublic(bob, yankee)

        self.assertPublic(charlie, charlie)
        self.assertPublic(charlie, zulu)

        self.assertPublic(doug, doug)


class PolicySimple(BranchVisibilityPolicyTestCase):
    """Test the visiblity policy where the base visibility rule is PUBLIC with
    one team specified to have PRIVATE branches.
    """

    def setUp(self):
        BranchVisibilityPolicyTestCase.setUp(self)
        self.defineTeamPolicies((
            (None, BranchVisibilityRule.PUBLIC),
            (self.xray, BranchVisibilityRule.PRIVATE),
            ))

    def test_xray_branches_private(self):
        """Branches created in the xray namespace will be private."""
        self.assertPrivateSubscriber(self.albert, self.xray, None)

    def test_xray_member_branches_private(self):
        """Branches created by members of the Xray team in their own namespace
        will be private with the Xray team subscribed.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, self.xray)

    def test_xray_member_other_namespace_public(self):
        """Branches created by members of the Xray team in other team
        namespaces are public.
        """
        self.assertPublic(self.albert, self.yankee)
        self.assertPublic(self.albert, self.zulu)

    def test_public_branches(self):
        """Branches created by users not in team Xray are created as public
        branches.
        """
        albert, bob, charlie, doug = self.people
        xray, yankee, zulu = self.teams

        self.assertPublic(bob, bob)
        self.assertPublic(bob, yankee)

        self.assertPublic(charlie, charlie)
        self.assertPublic(charlie, zulu)

        self.assertPublic(doug, doug)


class PolicyPrivateOnly(BranchVisibilityPolicyTestCase):
    """Test the visiblity policy where the base visibility rule is PUBLIC with
    one team specified to have the PRIVATE_ONLY rule.

    PRIVATE_ONLY only stops the user from changing the branch from private to
    public and for branch creation behaves in the same maner as the PRIVATE
    policy.
    """

    def setUp(self):
        BranchVisibilityPolicyTestCase.setUp(self)
        self.defineTeamPolicies((
            (None, BranchVisibilityRule.PUBLIC),
            (self.xray, BranchVisibilityRule.PRIVATE_ONLY),
            ))

    def test_xray_branches_private(self):
        """Branches created in the xray namespace will be private."""
        self.assertPrivateSubscriber(self.albert, self.xray, None)

    def test_xray_member_branches_private(self):
        """Branches created by members of the Xray team in their own namespace
        will be private with the Xray team subscribed.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, self.xray)

    def test_xray_member_other_namespace_public(self):
        """Branches created by members of the Xray team in other team
        namespaces are public.
        """
        self.assertPublic(self.albert, self.yankee)
        self.assertPublic(self.albert, self.zulu)

    def test_public_branches(self):
        """Branches created by users not in team Xray are created as public
        branches.
        """
        albert, bob, charlie, doug = self.people
        xray, yankee, zulu = self.teams

        self.assertPublic(bob, bob)
        self.assertPublic(bob, yankee)

        self.assertPublic(charlie, charlie)
        self.assertPublic(charlie, zulu)

        self.assertPublic(doug, doug)


class PolicyForbidden(BranchVisibilityPolicyTestCase):
    """Test the visiblity policy where the base visibility rule is FORBIDDEN
    with one team specified to have the PRIVATE branches and another team
    specified to have PUBLIC branches.
    """

    def setUp(self):
        BranchVisibilityPolicyTestCase.setUp(self)
        self.defineTeamPolicies((
            (None, BranchVisibilityRule.FORBIDDEN),
            (self.xray, BranchVisibilityRule.PRIVATE),
            (self.yankee, BranchVisibilityRule.PUBLIC),
            ))

    def test_branch_creation_forbidden_non_members(self):
        """People who are not members of Xray or Yankee are not allowed to
        create branches.
        """
        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.charlie, self.charlie)
        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.charlie, self.zulu)

        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.doug, self.doug)

    def test_branch_creation_forbidden_other_namespace(self):
        """People who are members of Xray or Yankee are not allowed to
        create branches in a namespace of a team that is not a member
        of Xray or Yankee.
        """
        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.albert, self.zulu)

    def test_yankee_branches_public(self):
        """Branches in the yankee namespace are public."""
        self.assertPublic(self.bob, self.yankee)
        self.assertPublic(self.albert, self.yankee)

    def test_yankee_member_branches_public(self):
        """Branches created by a member of Yankee, who is not a member
        of Xray will be public.
        """
        self.assertPublic(self.bob, self.bob)

    def test_xray_branches_private(self):
        """Branches in the xray namespace will be private."""
        self.assertPrivateSubscriber(self.albert, self.xray, None)

    def test_xray_member_branches_private(self):
        """Branches created by Xray team members in their own namespace
        will be private, and subscribed to by the Xray team.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, self.xray)


class PolicyTeamPrivateOverlap(BranchVisibilityPolicyTestCase):
    """Test the visibility policy where a user is a member of multiple teams
    with PRIVATE branches enabled.
    """

    def setUp(self):
        BranchVisibilityPolicyTestCase.setUp(self)
        self.defineTeamPolicies((
            (self.xray, BranchVisibilityRule.PRIVATE),
            (self.zulu, BranchVisibilityRule.PRIVATE),
            ))

    def test_public_branches_for_non_members(self):
        """Branches created by people who are not members of xray or zulu
        will be public branches.
        """
        self.assertPublic(self.bob, self.bob)
        self.assertPublic(self.bob, self.yankee)
        self.assertPublic(self.doug, self.doug)

    def test_public_branches_for_members_in_other_namespace(self):
        """If a member of xray or zulu creates a branch for a team that is
        not a member of xray or zulu, then the branch will be a public branch.
        """
        self.assertPublic(self.albert, self.yankee)

    def test_team_branches_private(self):
        """Branches created in the namespace of a team that has private
        branches specified are private.
        """
        self.assertPrivateSubscriber(self.charlie, self.zulu, None)
        self.assertPrivateSubscriber(self.albert, self.zulu, None)
        self.assertPrivateSubscriber(self.albert, self.xray, None)

    def test_one_membership_private_with_subscriber(self):
        """If the creator of the branch is a member of only one team that has
        private branches set up, then that team will be subscribed to any
        branches that the creator registers in their own namespace.
        """
        self.assertPrivateSubscriber(self.charlie, self.charlie, self.zulu)

    def test_two_memberships_private_no_subscriber(self):
        """If the creator of the branch is a member of two or more teams
        that have private branches enabled, then when a branch is created
        in their own namespace, there are no implicit subscribers.

        This is done as we cannot guess which team should have access
        to the private branch.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, None)


class ComplexPolicyStructure(BranchVisibilityPolicyTestCase):
    """Test the visibility policy with a complex policy structure.

    The base visibility policy is set to FORBIDDEN, with both xray and yankee
    teams creating PRIVATE branches.  Members of zulu team create PUBLIC
    branches.

    Branch creation is forbidden to all people who are not a member of
    one of the teams: xray, yankee or zulu.  Members of zulu can create
    branches that are public.  Branches created by members of xray and
    yankee in the team namespace are private, and branches created in the
    namespace of the user are also created private.
    """

    def setUp(self):
        BranchVisibilityPolicyTestCase.setUp(self)
        self.defineTeamPolicies((
            (None, BranchVisibilityRule.FORBIDDEN),
            (self.xray, BranchVisibilityRule.PRIVATE),
            (self.yankee, BranchVisibilityRule.PRIVATE_ONLY),
            (self.zulu, BranchVisibilityRule.PUBLIC),
            ))

    def test_non_membership_cannot_create_branches(self):
        """A user who is not a member of any specified team gets the
        base policy, which is in this case FORBIDDEN.
        """
        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.doug, self.doug)

    def test_zulu_branches_public(self):
        """Branches pushed to the zulu team namespace are public branches."""
        self.assertPublic(self.albert, self.zulu)
        self.assertPublic(self.charlie, self.zulu)

    def test_zulu_members_only_public(self):
        """A user who is a member of zulu, and not a member of a team that
        specifies private branch creation have public branches when created
        in the user's own namespace.
        """
        self.assertPublic(self.charlie, self.charlie)

    def test_xray_and_yankee_branches_private(self):
        """Branches that are created in the namespace of either xray or yankee
        are private branches.
        """
        self.assertPrivateSubscriber(self.albert, self.xray, None)
        self.assertPrivateSubscriber(self.albert, self.yankee, None)
        self.assertPrivateSubscriber(self.bob, self.yankee, None)

    def test_xray_member_private_with_subscription(self):
        """Branches created by a user who is a member of only one team that
        specifies private branches will have branches in the user's namespace
        created as private branches with the team subscribed to them.
        """
        self.assertPrivateSubscriber(self.bob, self.bob, self.yankee)

    def test_multiple_memberships_private(self):
        """If the user is a member of multiple teams that specify private
        branches, then this overrides PUBLIC policy that may apply.

        Any branch created in the user's own namespace will not have any
        implicit subscribers.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, None)


class TeamsWithinTeamsPolicies(BranchVisibilityPolicyTestCase):
    """Test the visibility policy when teams within teams have different
    visibility rules.
    """

    def setUp(self):
        """Join up the teams so zulu is in yankee, and yankee is in xray."""
        BranchVisibilityPolicyTestCase.setUp(self)
        self.yankee.addMember(self.zulu, self.albert, force_team_add=True)
        self.xray.addMember(self.yankee, self.albert, force_team_add=True)
        self.defineTeamPolicies((
            (None, BranchVisibilityRule.FORBIDDEN),
            (self.xray, BranchVisibilityRule.PRIVATE),
            (self.yankee, BranchVisibilityRule.PUBLIC),
            (self.zulu, BranchVisibilityRule.PRIVATE),
            ))

    def test_team_memberships(self):
        albert, bob, charlie, doug = self.people
        xray, yankee, zulu = self.teams
        # Albert is a member of all three teams.
        self.failUnless(albert.inTeam(xray),
                        "Albert should be in team Xray team.")
        self.failUnless(albert.inTeam(yankee),
                        "Albert should be in the Yankee.")
        self.failUnless(albert.inTeam(zulu),
                        "Albert should be in Zulu team.")
        # Bob is a member of Yankee, and now Xray.
        self.failUnless(bob.inTeam(xray),
                        "Bob should now be in team Xray team.")
        self.failUnless(bob.inTeam(yankee),
                        "Bob should be in the Yankee team.")
        self.failIf(bob.inTeam(zulu),
                    "Bob should not be in the Zulu team.")
        # Charlie is a member of Zulu, and through Zulu a member
        # of Yankee, and through Yankee a member of Xray.
        self.failUnless(charlie.inTeam(xray),
                        "Charlie should now be in team Xray team.")
        self.failUnless(charlie.inTeam(yankee),
                        "Charlie should now be in the Yankee team.")
        self.failUnless(charlie.inTeam(zulu),
                        "Charlie should be in the Zulu team.")
        # Doug is not a member of any
        self.failIf(doug.inTeam(xray),
                    "Doug should not be in team Xray team.")
        self.failIf(doug.inTeam(yankee),
                    "Doug should not be in the Yankee team.")
        self.failIf(doug.inTeam(zulu),
                    "Doug should not be in the Zulu team.")

    def test_non_membership_cannot_create_branches(self):
        """A user who is not a member of any specified team gets the
        base policy, which is in this case FORBIDDEN.
        """
        self.assertPolicyCheckRaises(
            BranchCreationForbidden, self.doug, self.doug)

    def test_xray_and_zulu_branches_private_no_subscriber(self):
        """All branches created in the namespace of teams that specify
        private branches are private with no subscribers.
        """
        self.assertPrivateSubscriber(self.albert, self.xray, None)
        self.assertPrivateSubscriber(self.bob, self.xray, None)
        self.assertPrivateSubscriber(self.charlie, self.xray, None)

        self.assertPrivateSubscriber(self.albert, self.zulu, None)
        self.assertPrivateSubscriber(self.charlie, self.zulu, None)

    def test_yankee_branches_public(self):
        """All branches created in the namespace of teams that specify
        public branches are public.
        """
        self.assertPublic(self.albert, self.yankee)
        self.assertPublic(self.bob, self.yankee)
        self.assertPublic(self.charlie, self.yankee)

    def test_privacy_through_team_membership_of_private_team(self):
        """Policies that apply to team apply to people that are members
        indirectly in the same way as direct membership.
        """
        self.assertPrivateSubscriber(self.bob, self.bob, self.xray)

    def test_multiple_private_policies_through_indirect_membership(self):
        """If a person is a member of a team that specifies private branches,
        and that team is also a member either directly or indirectly of another
        team that specifies private branches, then when members of those teams
        create branches, those branches have no implicit subscribers.
        """
        self.assertPrivateSubscriber(self.albert, self.albert, None)
        self.assertPrivateSubscriber(self.charlie, self.charlie, None)


class JunkBranches(BranchVisibilityPolicyTestCase):
    """Branches are considered junk if they have no associated product.
    It is the product that has the branch visibility policy, so junk branches
    have no related visibility policy."""

    def setUp(self):
        """Override the product used for the visibility checks."""
        BranchVisibilityPolicyTestCase.setUp(self)
        # Override the product that is used in the check tests.
        self.firefox = None

    def test_junk_brances_public(self):
        """Branches created by anyone that has no product defined are created
        as public branches.
        """
        self.assertPublic(self.albert, self.albert)
        # XXX: thumper 2007-06-22
        # bug 120501 is about whether or not users are able to create junk
        # branches in the team namespace.
        self.assertPublic(self.albert, self.xray)
        self.assertPublic(self.albert, self.yankee)
        self.assertPublic(self.albert, self.zulu)

        self.assertPublic(self.doug, self.doug)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
