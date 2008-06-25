# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Test the user vocabularies."""

__metaclass__ = type

from unittest import TestLoader

from zope.schema.vocabulary import getVocabularyRegistry

from canonical.launchpad.interfaces.person import PersonVisibility
from canonical.launchpad.ftests import login, loginPerson
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.testing import LaunchpadFunctionalLayer


class TestUserTeamsParticipationPlusSelfVocabulary(TestCaseWithFactory):
    """Test that the UserTeamsParticipationPlusSelf behaves as expected."""

    layer = LaunchpadFunctionalLayer

    def _vocabTermValues(self):
        """Return the token values for the vocab."""
        vocabulary_registry = getVocabularyRegistry()
        vocab = vocabulary_registry.get(
            None, 'UserTeamsParticipationPlusSelf')
        return [term.value for term in vocab]

    def test_user_no_team(self):
        user = self.factory.makePerson()
        loginPerson(user)
        self.assertEqual([user], self._vocabTermValues())

    def test_user_teams(self):
        # The ordering goes user first, then alphabetical by team display
        # name.
        user = self.factory.makePerson()
        team_owner = self.factory.makePerson()
        loginPerson(team_owner)
        bravo = self.factory.makeTeam(owner=team_owner, displayname="Bravo")
        bravo.addMember(person=user, reviewer=team_owner)
        alpha = self.factory.makeTeam(owner=team_owner, displayname="Alpha")
        alpha.addMember(person=user, reviewer=team_owner)
        loginPerson(user)
        self.assertEqual([user, alpha, bravo], self._vocabTermValues())

    def test_user_no_private_teams(self):
        # Private teams are not shown in the vocabulary.
        user = self.factory.makePerson()
        team_owner = self.factory.makePerson()
        loginPerson(team_owner)
        team = self.factory.makeTeam(owner=team_owner)
        team.addMember(person=user, reviewer=team_owner)
        # Launchpad admin rights are needed to set private membership.
        login('foo.bar@canonical.com')
        team.visibility = PersonVisibility.PRIVATE_MEMBERSHIP
        loginPerson(user)
        self.assertEqual([user], self._vocabTermValues())

    def test_indirect_team_membership(self):
        # Indirect team membership is shown.
        user = self.factory.makePerson()
        team_owner = self.factory.makePerson()
        loginPerson(team_owner)
        bravo = self.factory.makeTeam(owner=team_owner, displayname="Bravo")
        bravo.addMember(person=user, reviewer=team_owner)
        alpha = self.factory.makeTeam(owner=team_owner, displayname="Alpha")
        alpha.addMember(
            person=bravo, reviewer=team_owner, force_team_add=True)
        loginPerson(user)
        self.assertEqual([user, alpha, bravo], self._vocabTermValues())


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
