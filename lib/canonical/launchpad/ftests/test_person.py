# Copyright 2007 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import unittest
from datetime import datetime
import pytz

from zope.component import getUtility

from canonical.database.sqlbase import cursor
from canonical.launchpad.ftests import ANONYMOUS, login
from canonical.testing import LaunchpadFunctionalLayer
from canonical.launchpad.interfaces import (
    ArchivePurpose, BranchType, CreateBugParams, EmailAddressAlreadyTaken,
    IArchiveSet, IBranchSet, IBugSet, IEmailAddressSet, IProductSet,
    ISpecificationSet, InvalidEmailAddress, InvalidName)
from canonical.launchpad.interfaces.mailinglist import IMailingListSet
from canonical.launchpad.interfaces.person import (
    IPersonSet, ImmutableVisibilityError, NameAlreadyTaken,
    PersonCreationRationale, PersonVisibility)
from canonical.launchpad.database import (
    AnswerContact, Bug, BugTask, BugSubscription, Person, Specification)
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.launchpad.testing.systemdocs import create_initialized_view
from canonical.launchpad.validators.person import PrivatePersonLinkageError


class TestPerson(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, 'foo.bar@canonical.com')
        self.person_set = getUtility(IPersonSet)
        self.myteam = self.person_set.getByName('myteam')
        self.otherteam = self.person_set.getByName('otherteam')
        self.guadamen = self.person_set.getByName('guadamen')
        self.product_set = getUtility(IProductSet)
        self.bzr = self.product_set.getByName('bzr')
        self.now = datetime.now(pytz.timezone('UTC'))

    def test_getBranch_looks_up_products_by_aliases(self):
        """When looking up a person's branch using IPerson.getBranch() it's
        possible to use either the product's name or any of its aliases.
        """
        foobar = self.person_set.getByName('name16')
        branch = self.factory.makeBranch(owner=foobar, product=self.bzr)
        self.assertEquals(
            foobar.getBranch(self.bzr.name, branch.name), branch)
        self.bzr.setAliases(['bazaar-ng'])
        self.assertEquals(
            foobar.getBranch('bazaar-ng', branch.name), branch)

    def test_getBranch_returns_None_if_pillar_is_not_product(self):
        foobar = self.person_set.getByName('name16')
        self.failUnless(foobar.getBranch('ubuntu', 'some-branch') is None)
        self.failUnless(foobar.getBranch('mozilla', 'some-branch') is None)

    def test_deactivateAccount_copes_with_names_already_in_use(self):
        """When a user deactivates his account, its name is changed.

        We do that so that other users can use that name, which the original
        user doesn't seem to want anymore.

        It may happen that we attempt to rename an account to something that
        is already in use. If this happens, we'll simply append an integer to
        that name until we can find one that is free.
        """
        sample_person = Person.byName('name12')
        login(sample_person.preferredemail.email)
        sample_person.deactivateAccount("blah!")
        self.failUnlessEqual(sample_person.name, 'name12-deactivatedaccount')
        # Now that name12 is free Foo Bar can use it.
        foo_bar = Person.byName('name16')
        foo_bar.name = 'name12'
        # If Foo Bar deactivates his account, though, we'll have to use a name
        # other than name12-deactivatedaccount because that is already in use.
        login(foo_bar.preferredemail.email)
        foo_bar.deactivateAccount("blah!")
        self.failUnlessEqual(foo_bar.name, 'name12-deactivatedaccount1')

    def test_getDirectMemberIParticipateIn(self):
        sample_person = Person.byName('name12')
        warty_team = Person.byName('name20')
        ubuntu_team = Person.byName('ubuntu-team')
        # Sample Person is an active member of Warty Security Team which in
        # turn is a proposed member of Ubuntu Team. That means
        # sample_person._getDirectMemberIParticipateIn(ubuntu_team) will fail
        # with an AssertionError.
        self.failUnless(sample_person in warty_team.activemembers)
        self.failUnless(warty_team in ubuntu_team.invited_members)
        self.failUnlessRaises(
            AssertionError, sample_person._getDirectMemberIParticipateIn,
            ubuntu_team)

        # If we make warty_team an active member of Ubuntu team, then the
        # _getDirectMemberIParticipateIn() call will actually return
        # warty_team.
        login(warty_team.teamowner.preferredemail.email)
        warty_team.acceptInvitationToBeMemberOf(ubuntu_team, comment="foo")
        self.failUnless(warty_team in ubuntu_team.activemembers)
        self.failUnlessEqual(
            sample_person._getDirectMemberIParticipateIn(ubuntu_team),
            warty_team)

    def test_AnswerContact_person_validator(self):
        answer_contact = AnswerContact.select(limit=1)[0]
        self.assertRaises(
            PrivatePersonLinkageError,
            setattr, answer_contact, 'person', self.myteam)

    def test_Bug_person_validator(self):
        bug = Bug.select(limit=1)[0]
        for attr_name in ['owner', 'who_made_private']:
            self.assertRaises(
                PrivatePersonLinkageError,
                setattr, bug, attr_name, self.myteam)

    def test_BugTask_person_validator(self):
        bug_task = BugTask.select(limit=1)[0]
        for attr_name in ['assignee', 'owner']:
            self.assertRaises(
                PrivatePersonLinkageError,
                setattr, bug_task, attr_name, self.myteam)

    def test_BugSubscription_person_validator(self):
        bug_subscription = BugSubscription.select(limit=1)[0]
        self.assertRaises(
            PrivatePersonLinkageError,
            setattr, bug_subscription, 'person', self.myteam)

    def test_Specification_person_validator(self):
        specification = Specification.select(limit=1)[0]
        for attr_name in ['assignee', 'drafter', 'approver', 'owner',
                          'goal_proposer', 'goal_decider', 'completer',
                          'starter']:
            self.assertRaises(
                PrivatePersonLinkageError,
                setattr, specification, attr_name, self.myteam)

    def test_visibility_validator_announcement(self):
        announcement = self.bzr.announce(
            user = self.otherteam,
            title = 'title foo',
            summary = 'summary foo',
            url = 'http://foo.com',
            publication_date = self.now
            )
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by'
                ' an announcement.')

    def test_visibility_validator_answer_contact(self):
        answer_contact = AnswerContact(
            person=self.otherteam,
            product=self.bzr,
            distribution=None,
            sourcepackagename=None)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by'
                ' an answercontact.')

    def test_visibility_validator_archive(self):
        archive = getUtility(IArchiveSet).new(
            owner=self.otherteam,
            description='desc foo',
            purpose=ArchivePurpose.PPA)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by'
                ' an archive.')

    def test_visibility_validator_branch(self):
        branch = getUtility(IBranchSet).new(
            branch_type=BranchType.HOSTED,
            name='namefoo',
            registrant=self.otherteam,
            owner=self.otherteam,
            author=self.otherteam,
            product=self.bzr,
            url=None)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by a'
                ' branch and a branchsubscription.')

    def test_visibility_validator_bug(self):
        bug_params = CreateBugParams(
            owner=self.otherteam,
            title='title foo',
            comment='comment foo',
            description='description foo',
            datecreated=self.now)
        bug_params.setBugTarget(product=self.bzr)
        bug = getUtility(IBugSet).createBug(bug_params)
        bug.bugtasks[0].transitionToAssignee(self.otherteam)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by a'
                ' bug, a bugsubscription, a bugtask and a message.')

    def test_visibility_validator_product_subscription(self):
        self.bzr.addSubscription(self.otherteam, self.guadamen)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by'
                ' a project subscriber.')

    def test_visibility_validator_specification_subscriber(self):
        email = getUtility(IEmailAddressSet).new(
            'otherteam@canonical.com', self.otherteam)
        self.otherteam.setContactAddress(email)
        specification = getUtility(ISpecificationSet).get(1)
        specification.subscribe(self.otherteam, self.otherteam, True)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by a'
                ' specificationsubscription.')

    def test_visibility_validator_team_member(self):
        self.guadamen.addMember(self.otherteam, self.guadamen)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it is referenced by a'
                ' teammembership.')

    def test_visibility_validator_team_mailinglist_public(self):
        self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        try:
            self.otherteam.visibility = PersonVisibility.PUBLIC
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made public since it has a mailing list')

    def test_visibility_validator_team_mailinglist_public_view(self):
        self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        # The view should add an error notification.
        view = create_initialized_view(self.otherteam, '+edit', {
            'field.name': 'otherteam',
            'field.displayname': 'Other Team',
            'field.subscriptionpolicy': 'RESTRICTED',
            'field.renewal_policy': 'NONE',
            'field.visibility': 'PUBLIC',
            'field.actions.save': 'Save',
            })
        self.assertEqual(len(view.request.notifications), 1)
        self.assertEqual(
            view.request.notifications[0].message,
            'This team cannot be made public since it has a mailing list')

    def test_visibility_validator_team_mailinglist_public_purged(self):
        self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        mailinglist.purge()
        self.otherteam.visibility = PersonVisibility.PUBLIC
        self.assertEqual(self.otherteam.visibility, PersonVisibility.PUBLIC)

    def test_visibility_validator_team_mailinglist_private(self):
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except ImmutableVisibilityError, exc:
            self.assertEqual(
                str(exc),
                'This team cannot be made private since it '
                'is referenced by a mailing list.')

    def test_visibility_validator_team_mailinglist_private_view(self):
        # The view should add a field error.
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        view = create_initialized_view(self.otherteam, '+edit', {
            'field.name': 'otherteam',
            'field.displayname': 'Other Team',
            'field.subscriptionpolicy': 'RESTRICTED',
            'field.renewal_policy': 'NONE',
            'field.visibility': 'PRIVATE_MEMBERSHIP',
            'field.actions.save': 'Save',
            })
        self.assertEqual(len(view.errors), 1)
        self.assertEqual(view.errors[0],
                         'This team cannot be made private since it '
                         'is referenced by a mailing list.')

    def test_visibility_validator_team_mailinglist_private_purged(self):
        mailinglist = getUtility(IMailingListSet).new(self.otherteam)
        mailinglist.purge()
        self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        self.assertEqual(self.otherteam.visibility,
                         PersonVisibility.PRIVATE_MEMBERSHIP)


class TestPersonSet(unittest.TestCase):
    """Test `IPersonSet`."""
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)
        self.person_set = getUtility(IPersonSet)

    def test_isNameBlacklisted(self):
        cursor().execute(
            "INSERT INTO NameBlacklist(id, regexp) VALUES (-100, 'foo')")
        self.failUnless(self.person_set.isNameBlacklisted('foo'))
        self.failIf(self.person_set.isNameBlacklisted('bar'))


class TestCreatePersonAndEmail(unittest.TestCase):
    """Test `IPersonSet`.createPersonAndEmail()."""
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)
        self.person_set = getUtility(IPersonSet)

    def test_duplicated_name_not_accepted(self):
        self.person_set.createPersonAndEmail(
            'testing@example.com', PersonCreationRationale.UNKNOWN,
            name='zzzz')
        self.assertRaises(
            NameAlreadyTaken, self.person_set.createPersonAndEmail,
            'testing2@example.com', PersonCreationRationale.UNKNOWN,
            name='zzzz')

    def test_duplicated_email_not_accepted(self):
        self.person_set.createPersonAndEmail(
            'testing@example.com', PersonCreationRationale.UNKNOWN)
        self.assertRaises(
            EmailAddressAlreadyTaken, self.person_set.createPersonAndEmail,
            'testing@example.com', PersonCreationRationale.UNKNOWN)

    def test_invalid_email_not_accepted(self):
        self.assertRaises(
            InvalidEmailAddress, self.person_set.createPersonAndEmail,
            'testing@.com', PersonCreationRationale.UNKNOWN)

    def test_invalid_name_not_accepted(self):
        self.assertRaises(
            InvalidName, self.person_set.createPersonAndEmail,
            'testing@example.com', PersonCreationRationale.UNKNOWN,
            name='/john')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
