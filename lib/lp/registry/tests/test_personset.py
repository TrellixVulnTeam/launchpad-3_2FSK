# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for PersonSet."""

__metaclass__ = type

import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.code.tests.helpers import remove_all_sample_data_branches
from lp.registry.interfaces.mailinglistsubscription import (
    MailingListAutoSubscribePolicy,
    )
from lp.registry.interfaces.person import (
    IPersonSet,
    PersonCreationRationale,
    )
from lp.registry.model.person import PersonSet
from lp.services.database.sqlbase import cursor
from lp.services.identity.interfaces.account import (
    AccountStatus,
    AccountSuspendedError,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestPersonSetBranchCounts(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        remove_all_sample_data_branches()
        self.person_set = getUtility(IPersonSet)

    def test_no_branches(self):
        """Initially there should be no branches."""
        self.assertEqual(0, self.person_set.getPeopleWithBranches().count())

    def test_five_branches(self):
        branches = [self.factory.makeAnyBranch() for x in range(5)]
        # Each branch has a different product, so any individual product
        # will return one branch.
        self.assertEqual(5, self.person_set.getPeopleWithBranches().count())
        self.assertEqual(1, self.person_set.getPeopleWithBranches(
                branches[0].product).count())


class TestPersonSetEnsurePerson(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer
    email_address = 'testing.ensure.person@example.com'
    displayname = 'Testing ensurePerson'
    rationale = PersonCreationRationale.SOURCEPACKAGEUPLOAD

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.person_set = getUtility(IPersonSet)

    def test_ensurePerson_returns_existing_person(self):
        # IPerson.ensurePerson returns existing person and does not
        # override its details.
        testing_displayname = 'will not be modified'
        testing_person = self.factory.makePerson(
            email=self.email_address, displayname=testing_displayname)

        ensured_person = self.person_set.ensurePerson(
            self.email_address, self.displayname, self.rationale)
        self.assertEquals(testing_person.id, ensured_person.id)
        self.assertIsNot(
            ensured_person.displayname, self.displayname,
            'Person.displayname should not be overridden.')
        self.assertIsNot(
            ensured_person.creation_rationale, self.rationale,
            'Person.creation_rationale should not be overridden.')

    def test_ensurePerson_hides_new_person_email(self):
        # IPersonSet.ensurePerson creates new person with
        # 'hide_email_addresses' set.
        ensured_person = self.person_set.ensurePerson(
            self.email_address, self.displayname, self.rationale)
        self.assertTrue(ensured_person.hide_email_addresses)


class TestPersonSetMerge(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        # Use the unsecured PersonSet so that private methods can be tested.
        self.person_set = PersonSet()
        self.from_person = self.factory.makePerson()
        self.to_person = self.factory.makePerson()
        self.cur = cursor()

    def test__mergeMailingListSubscriptions_no_subscriptions(self):
        self.person_set._mergeMailingListSubscriptions(
            self.cur, self.from_person.id, self.to_person.id)
        self.assertEqual(0, self.cur.rowcount)

    def test__mergeMailingListSubscriptions_with_subscriptions(self):
        naked_person = removeSecurityProxy(self.from_person)
        naked_person.mailing_list_auto_subscribe_policy = (
            MailingListAutoSubscribePolicy.ALWAYS)
        self.team, self.mailing_list = self.factory.makeTeamAndMailingList(
            'test-mailinglist', 'team-owner')
        with person_logged_in(self.team.teamowner):
            self.team.addMember(
                self.from_person, reviewer=self.team.teamowner)
        transaction.commit()
        self.person_set._mergeMailingListSubscriptions(
            self.cur, self.from_person.id, self.to_person.id)
        self.assertEqual(1, self.cur.rowcount)


class TestPersonSetGetOrCreateByOpenIDIdentifier(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestPersonSetGetOrCreateByOpenIDIdentifier, self).setUp()
        self.person_set = getUtility(IPersonSet)

    def callGetOrCreate(self, identifier, email='a@b.com'):
        return self.person_set.getOrCreateByOpenIDIdentifier(
            identifier, email, "Joe Bloggs",
            PersonCreationRationale.SOFTWARE_CENTER_PURCHASE,
            "when purchasing an application via Software Center.")

    def test_existing_person(self):
        email = 'test-email@example.com'
        person = self.factory.makePerson(email=email)
        openid_ident = removeSecurityProxy(
            person.account).openid_identifiers.any().identifier

        result, db_updated = self.callGetOrCreate(openid_ident, email=email)

        self.assertEqual(person, result)
        self.assertFalse(db_updated)

    def test_existing_deactivated_account(self):
        # An existing deactivated account will be reactivated.
        person = self.factory.makePerson(
            account_status=AccountStatus.DEACTIVATED)
        openid_ident = removeSecurityProxy(
            person.account).openid_identifiers.any().identifier

        found_person, db_updated = self.callGetOrCreate(openid_ident)
        self.assertEqual(person, found_person)
        self.assertEqual(AccountStatus.ACTIVE, person.account.status)
        self.assertTrue(db_updated)
        self.assertEqual(
            "when purchasing an application via Software Center.",
            removeSecurityProxy(person.account).status_comment)

    def test_existing_suspended_account(self):
        # An existing suspended account will raise an exception.
        person = self.factory.makePerson(
            account_status=AccountStatus.SUSPENDED)
        openid_ident = removeSecurityProxy(
            person.account).openid_identifiers.any().identifier

        self.assertRaises(
            AccountSuspendedError, self.callGetOrCreate, openid_ident)

    def test_no_account_or_email(self):
        # An identifier can be used to create an account (it is assumed
        # to be already authenticated with SSO).
        person, db_updated = self.callGetOrCreate(u'openid-identifier')

        self.assertEqual(
            u"openid-identifier", removeSecurityProxy(
                person.account).openid_identifiers.any().identifier)
        self.assertTrue(db_updated)

    def test_no_matching_account_existing_email(self):
        # The openid_identity of the account matching the email will
        # updated.
        other_person = self.factory.makePerson('a@b.com')

        person, db_updated = self.callGetOrCreate(
            u'other-openid-identifier', 'a@b.com')

        self.assertEqual(other_person, person)
        self.assert_(
            u'other-openid-identifier' in [
                identifier.identifier for identifier in removeSecurityProxy(
                    person.account).openid_identifiers])
