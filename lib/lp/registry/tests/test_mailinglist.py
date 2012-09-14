# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = []

from textwrap import dedent

from zope.component import getUtility

from lp.registry.interfaces.mailinglist import IMailingListSet
from lp.registry.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy,
    )
from lp.registry.interfaces.person import TeamMembershipPolicy
from lp.services.messages.interfaces.message import IMessageSet
from lp.testing import (
    login_celebrity,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )


class MailingList_getSubscribers_TestCase(TestCaseWithFactory):
    """Tests for `IMailingList`.getSubscribers()."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.team, self.mailing_list = self.factory.makeTeamAndMailingList(
            'test-mailinglist', 'team-owner')

    def test_only_active_members_can_be_subscribers(self):
        former_member = self.factory.makePerson()
        pending_member = self.factory.makePerson()
        active_member = self.active_member = self.factory.makePerson()
        # Each of our members want to be subscribed to a team's mailing list
        # whenever they join the team.
        login_celebrity('admin')
        former_member.mailing_list_auto_subscribe_policy = (
            MailingListAutoSubscribePolicy.ALWAYS)
        active_member.mailing_list_auto_subscribe_policy = (
            MailingListAutoSubscribePolicy.ALWAYS)
        pending_member.mailing_list_auto_subscribe_policy = (
            MailingListAutoSubscribePolicy.ALWAYS)
        self.team.membership_policy = TeamMembershipPolicy.MODERATED
        pending_member.join(self.team)
        self.team.addMember(former_member, reviewer=self.team.teamowner)
        former_member.leave(self.team)
        self.team.addMember(active_member, reviewer=self.team.teamowner)
        # Even though our 3 members want to subscribe to the team's mailing
        # list, only the active member is considered a subscriber.
        self.assertEqual(
            [active_member], list(self.mailing_list.getSubscribers()))

    def test_getSubscribers_order(self):
        person_1 = self.factory.makePerson(name="pb1", displayname="Me")
        with person_logged_in(person_1):
            person_1.mailing_list_auto_subscribe_policy = (
                MailingListAutoSubscribePolicy.ALWAYS)
            person_1.join(self.team)
        person_2 = self.factory.makePerson(name="pa2", displayname="Me")
        with person_logged_in(person_2):
            person_2.mailing_list_auto_subscribe_policy = (
                MailingListAutoSubscribePolicy.ALWAYS)
            person_2.join(self.team)
        subscribers = self.mailing_list.getSubscribers()
        self.assertEqual(2, subscribers.count())
        self.assertEqual(
            ['pa2', 'pb1'], [person.name for person in subscribers])


class TestMailinglistSet(TestCaseWithFactory):
    """Test the mailing list set class."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestMailinglistSet, self).setUp()
        self.mailing_list_set = getUtility(IMailingListSet)
        login_celebrity('admin')

    def test_getSenderAddresses_dict_keys(self):
        # getSenderAddresses() returns a dict of teams names
        # {team_name: [(member_displayname, member_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        team2, member2 = self.factory.makeTeamWithMailingListSubscribers(
            'team2', auto_subscribe=False)
        team_names = [team1.name, team2.name]
        result = self.mailing_list_set.getSenderAddresses(team_names)
        self.assertEqual(team_names, sorted(result.keys()))

    def test_getSenderAddresses_dict_values(self):
        # getSenderAddresses() returns a dict of team namess with a list of
        # all membera display names and email addresses.
        # {team_name: [(member_displayname, member_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        result = self.mailing_list_set.getSenderAddresses([team1.name])
        list_senders = sorted([
            (m.displayname, m.preferredemail.email)
            for m in team1.allmembers])
        self.assertEqual(list_senders, sorted(result[team1.name]))

    def test_getSenderAddresses_multiple_and_lowercase_email(self):
        # getSenderAddresses() contains multiple email addresses for
        # users and they are lowercased for mailman.
        # {team_name: [(member_displayname, member_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        email = self.factory.makeEmail('me@EG.dom', member1)
        result = self.mailing_list_set.getSenderAddresses([team1.name])
        list_senders = sorted([
            (m.displayname, m.preferredemail.email)
            for m in team1.allmembers])
        list_senders.append((member1.displayname, email.email.lower()))
        self.assertContentEqual(list_senders, result[team1.name])

    def test_getSenderAddresses_participation_dict_values(self):
        # getSenderAddresses() dict values includes indirect participants.
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        result = self.mailing_list_set.getSenderAddresses([team1.name])
        list_senders = sorted([
            (m.displayname, m.preferredemail.email)
            for m in team1.allmembers if m.preferredemail])
        self.assertEqual(list_senders, sorted(result[team1.name]))

    def test_getSubscribedAddresses_dict_keys(self):
        # getSubscribedAddresses() returns a dict of team names.
        # {team_name: [(subscriber_displayname, subscriber_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1')
        team2, member2 = self.factory.makeTeamWithMailingListSubscribers(
            'team2')
        team_names = [team1.name, team2.name]
        result = self.mailing_list_set.getSubscribedAddresses(team_names)
        self.assertEqual(team_names, sorted(result.keys()))

    def test_getSubscribedAddresses_dict_values(self):
        # getSubscribedAddresses() returns a dict of teams names with a list
        # of subscriber tuples.
        # {team_name: [(subscriber_displayname, subscriber_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1')
        result = self.mailing_list_set.getSubscribedAddresses([team1.name])
        list_subscribers = [
            (member1.displayname, member1.preferredemail.email)]
        self.assertEqual(list_subscribers, result[team1.name])

    def test_getSubscribedAddresses_multiple_lowercase_email(self):
        # getSubscribedAddresses() contains email addresses for
        # users and they are lowercased for mailman. The email maybe
        # explicitly set instead of the preferred email.
        # {team_name: [(member_displayname, member_email) ...]}
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1')
        with person_logged_in(member1):
            email1 = self.factory.makeEmail('me@EG.dom', member1)
            member1.setPreferredEmail(email1)
        with person_logged_in(team1.teamowner):
            email2 = self.factory.makeEmail('you@EG.dom', team1.teamowner)
            team1.mailing_list.subscribe(team1.teamowner, email2)
        result = self.mailing_list_set.getSubscribedAddresses([team1.name])
        list_subscribers = [
            (member1.displayname, email1.email.lower()),
            (team1.teamowner.displayname, email2.email.lower())]
        self.assertContentEqual(list_subscribers, result[team1.name])

    def test_getSubscribedAddresses_participation_dict_values(self):
        # getSubscribedAddresses() dict values includes indirect participants.
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1')
        team2, member2 = self.factory.makeTeamWithMailingListSubscribers(
            'team2', super_team=team1)
        result = self.mailing_list_set.getSubscribedAddresses([team1.name])
        list_subscribers = sorted([
            (member1.displayname, member1.preferredemail.email),
            (member2.displayname, member2.preferredemail.email)])
        self.assertEqual(list_subscribers, sorted(result[team1.name]))

    def test_getSubscribedAddresses_preferredemail_dict_values(self):
        # getSubscribedAddresses() dict values include users who want email to
        # go to their preferred address.
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        team1.mailing_list.subscribe(member1)
        result = self.mailing_list_set.getSubscribedAddresses([team1.name])
        list_subscribers = [
            (member1.displayname, member1.preferredemail.email)]
        self.assertEqual(list_subscribers, result[team1.name])


class HeldMessageTestCase(TestCaseWithFactory):
    """Test the mailing list set class message rules."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(HeldMessageTestCase, self).setUp()
        self.mailing_list_set = getUtility(IMailingListSet)
        login_celebrity('admin')

    def makeMailingListAndHeldMessage(self):
        team1, member1 = self.factory.makeTeamWithMailingListSubscribers(
            'team1', auto_subscribe=False)
        owner1 = team1.teamowner
        sender = self.factory.makePerson()
        email = dedent(str("""\
            From: %s
            To: %s
            Subject: A question
            Message-ID: <first-post>
            Date: Fri, 01 Aug 2000 01:08:59 -0000\n
            I have a question about this team.
            """ % (sender.preferredemail.email, team1.mailing_list.address)))
        message = getUtility(IMessageSet).fromEmail(email)
        held_message = team1.mailing_list.holdMessage(message)
        return team1, member1, owner1, sender, held_message

    def test_mailinglistset_getSenderAddresses_approved_dict_values(self):
        # getSenderAddresses() dict values includes senders where were
        # approved in the list moderation queue.
        test_objects = self.makeMailingListAndHeldMessage()
        team1, member1, owner1, sender, held_message = test_objects
        held_message.approve(owner1)
        result = self.mailing_list_set.getSenderAddresses([team1.name])
        list_senders = sorted([
            (owner1.displayname, owner1.preferredemail.email),
            (member1.displayname, member1.preferredemail.email),
            (sender.displayname, sender.preferredemail.email)])
        self.assertEqual(list_senders, sorted(result[team1.name]))
