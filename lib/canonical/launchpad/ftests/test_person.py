# Copyright 2007 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import unittest
from datetime import datetime
import pytz

from zope.component import getUtility
from sqlobject.include.validators import InvalidField

from canonical.database.sqlbase import flush_database_updates, SQLBase
from canonical.launchpad.ftests import login
from canonical.testing import LaunchpadFunctionalLayer
from canonical.launchpad.interfaces import (
    ArchivePurpose, BranchType, CreateBugParams, IArchiveSet, IBranchSet,
    IBugSet, IEmailAddressSet, IPersonSet, IProductSet,
    ISpecificationSet, PersonVisibility)
from canonical.launchpad.database import (
    AnswerContact, Bug, BugTask, BugSubscription, Person, Specification)


class TestPerson(unittest.TestCase):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login('foo.bar@canonical.com')
        self.person_set = getUtility(IPersonSet)
        self.myteam = self.person_set.getByName('myteam')
        self.otherteam = self.person_set.getByName('otherteam')
        self.guadamen = self.person_set.getByName('guadamen')
        self.product_set = getUtility(IProductSet)
        self.bzr = self.product_set.getByName('bzr')
        self.now = datetime.now(pytz.timezone('UTC'))

    def tearDown(self):
        SQLBase._connection._connection.rollback()

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
        flush_database_updates()
        self.failUnlessEqual(sample_person.name, 'name12-deactivatedaccount')
        # Now that name12 is free Foo Bar can use it.
        foo_bar = Person.byName('name16')
        foo_bar.name = 'name12'
        # If Foo Bar deactivates his account, though, we'll have to use a name
        # other than name12-deactivatedaccount because that is already in use.
        login(foo_bar.preferredemail.email)
        foo_bar.deactivateAccount("blah!")
        flush_database_updates()
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
        flush_database_updates()
        self.failUnless(warty_team in ubuntu_team.activemembers)
        self.failUnlessEqual(
            sample_person._getDirectMemberIParticipateIn(ubuntu_team),
            warty_team)

    def test_AnswerContact_person_validator(self):
        answer_contact = AnswerContact.select(limit=1)[0]
        self.assertRaises(
            InvalidField,
            setattr, answer_contact, 'person', self.myteam)

    def test_Bug_person_validator(self):
        bug = Bug.select(limit=1)[0]
        for attr_name in ['owner', 'who_made_private']:
            self.assertRaises(
                InvalidField,
                setattr, bug, attr_name, self.myteam)

    def test_BugTask_person_validator(self):
        bug_task = BugTask.select(limit=1)[0]
        for attr_name in ['assignee', 'owner']:
            self.assertRaises(
                InvalidField,
                setattr, bug_task, attr_name, self.myteam)

    def test_BugSubscription_person_validator(self):
        bug_subscription = BugSubscription.select(limit=1)[0]
        self.assertRaises(
            InvalidField,
            setattr, bug_subscription, 'person', self.myteam)

    def test_Specification_person_validator(self):
        specification = Specification.select(limit=1)[0]
        for attr_name in ['assignee', 'drafter', 'approver', 'owner',
                          'goal_proposer', 'goal_decider', 'completer',
                          'starter']:
            self.assertRaises(
                InvalidField,
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
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as an'
                ' announcement registrant.')

    def test_visibility_validator_answer_contact(self):
        answer_contact = AnswerContact(
            person=self.otherteam,
            product=self.bzr,
            distribution=None,
            sourcepackagename=None)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as an'
                ' answer contact.')

    def test_visibility_validator_archive(self):
        archive = getUtility(IArchiveSet).new(
            owner=self.otherteam,
            description='desc foo',
            purpose=ArchivePurpose.PPA)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as a'
                ' PPA owner.')

    def test_visibility_validator_branch(self):
        branch = getUtility(IBranchSet).new(
            branch_type=BranchType.HOSTED,
            name='namefoo',
            creator=self.otherteam,
            owner=self.otherteam,
            author=self.otherteam,
            product=self.bzr,
            url=None)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as a'
                ' branch author, a branch owner and a branch registrant.')

    def test_visibility_validator_bug(self):
        bug = getUtility(IBugSet).createBug(
            CreateBugParams(
                owner=self.otherteam,
                title='title foo',
                comment='comment foo',
                description='description foo',
                datecreated=self.now))
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as a'
                ' bug owner, a bug subscriber and a commenter.')

    def test_visibility_validator_specification_subscriber(self):
        email = getUtility(IEmailAddressSet).new(
            'otherteam@canonical.com', self.otherteam)
        self.otherteam.setContactAddress(email)
        specification = getUtility(ISpecificationSet).get(1)
        specification.subscribe(self.otherteam, self.otherteam, True)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as a'
                ' blueprint subscriber.')

    def test_visibility_validator_team_member(self):
        self.guadamen.addMember(self.otherteam, self.guadamen)
        try:
            self.otherteam.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        except InvalidField, info:
            self.assertEqual(
                info.msg,
                'This team cannot be made private since it is used as a'
                ' member of another team.')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

