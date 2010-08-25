# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Archive features."""

from zope.security.interfaces import Unauthorized

from canonical.testing import DatabaseFunctionalLayer
from lp.registry.interfaces.person import PersonVisibility
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )


class TestArchiveSubscriptions(TestCaseWithFactory):
    """Edge-case tests for private PPA subscribers.

    See also lib/lp/soyuz/stories/ppa/xx-private-ppa-subscription-stories.txt
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Create a test archive."""
        super(TestArchiveSubscriptions, self).setUp()
        self.private_team = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE, name="subscribertest")
        login_person(self.private_team.teamowner)
        self.archive = self.factory.makeArchive(
            private=True, owner=self.private_team)
        self.subscriber = self.factory.makePerson()

    def test_subscriber_can_access_private_team_ppa(self):
        # As per bug 597783, we need to make sure a subscriber can see
        # a private team's PPA after they have been given a subscription.
        # This is essentially allowing access for the subscriber to see
        # the private team.
        def get_name():
            return self.archive.owner.name

        # Before a subscription, accessing the team name will raise.
        login_person(self.subscriber)
        self.assertRaises(Unauthorized, get_name)

        login_person(self.private_team.teamowner)
        self.archive.newSubscription(
            self.subscriber, registrant=self.archive.owner)

        # When a subscription exists, it's fine.
        login_person(self.subscriber)
        self.assertEqual(self.archive.owner.name, "subscribertest")
