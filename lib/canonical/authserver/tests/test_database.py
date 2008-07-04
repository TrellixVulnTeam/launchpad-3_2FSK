# Copyright 2006-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0141

"""Tests for lib/canonical/authserver/database.py"""

__metaclass__ = type

import unittest
import datetime

import pytz
import transaction

from storm.zope.interfaces import IZStorm

from twisted.web.xmlrpc import Fault

from zope.component import getUtility
from zope.interface.verify import verifyObject
from zope.security.management import getSecurityPolicy, setSecurityPolicy
from zope.security.proxy import removeSecurityProxy

from canonical.codehosting.tests.helpers import BranchTestCase
from canonical.database.sqlbase import cursor, sqlvalues

from canonical.launchpad.ftests import ANONYMOUS, login, logout, syncUpdate
from canonical.launchpad.database.person import Person
from canonical.launchpad.interfaces.branch import (
    BranchType, BRANCH_NAME_VALIDATION_ERROR_MESSAGE, IBranchSet)
from canonical.launchpad.interfaces.emailaddress import (
    EmailAddressStatus, IEmailAddressSet)
from canonical.launchpad.interfaces.person import IPersonSet
from canonical.launchpad.interfaces.product import IProductSet
from canonical.launchpad.interfaces.wikiname import IWikiNameSet
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.launchpad.webapp.authentication import SSHADigestEncryptor
from canonical.launchpad.webapp.authorization import LaunchpadSecurityPolicy
from canonical.launchpad.webapp.interfaces import ILaunchBag

from canonical.authserver.interfaces import (
    IBranchDetailsStorage, IHostedBranchStorage, IUserDetailsStorage,
    IUserDetailsStorageV2, LAUNCHPAD_SERVICES, READ_ONLY, WRITABLE)
from canonical.authserver.database import (
    DatabaseBranchDetailsStorage, DatabaseUserDetailsStorage,
    DatabaseUserDetailsStorageV2, NOT_FOUND_FAULT_CODE,
    PERMISSION_DENIED_FAULT_CODE, run_as_requester, read_only_transaction,
    writing_transaction)
from canonical.launchpad.testing import LaunchpadObjectFactory

from canonical.testing.layers import (
    LaunchpadFunctionalLayer, LaunchpadScriptLayer, LaunchpadZopelessLayer)


UTC = pytz.timezone('UTC')


def get_logged_in_username():
    """Return the username of the logged in person.

    Used by `TestRunAsRequester`.
    """
    user = getUtility(ILaunchBag).user
    if user is None:
        return None
    return user.name


class TestRunAsRequester(TestCaseWithFactory):
    """Tests for the `run_as_requester` decorator."""

    layer = LaunchpadFunctionalLayer

    class UsesLogin:
        """Example class used for testing `run_as_requester`."""

        def _getPerson(self, login_id):
            return getUtility(IPersonSet).getByName(login_id)

        @run_as_requester
        def getLoggedInUsername(self, requester):
            return get_logged_in_username()

        @run_as_requester
        def getRequestingUser(self, requester):
            """Return the requester."""
            return requester

        @run_as_requester
        def raiseException(self, requester):
            raise RuntimeError("Deliberately raised error.")

    def setUp(self):
        super(TestRunAsRequester, self).setUp()
        self.person = self.factory.makePerson()
        transaction.commit()
        self.example = self.UsesLogin()

    def test_loginAsRequester(self):
        # run_as_requester logs in as user given as the first argument to the
        # method being decorated.
        username = self.example.getLoggedInUsername(self.person.name)
        self.assertEqual(self.person.name, username)

    def test_logoutAtEnd(self):
        # run_as_requester logs out once the decorated method is finished.
        self.example.getLoggedInUsername(self.person.name)
        self.assertEqual(None, get_logged_in_username())

    def test_logoutAfterException(self):
        # run_as_requester logs out even if the decorated method raises an
        # exception.
        try:
            self.example.raiseException(self.person.name)
        except RuntimeError:
            pass
        self.assertEqual(None, get_logged_in_username())

    def test_passesRequesterInAsPerson(self):
        # run_as_requester passes in the Launchpad Person object of the
        # requesting user.
        user = self.example.getRequestingUser(self.person.name)
        self.assertEqual(self.person.name, user.name)

    def test_cheatsForLaunchpadServices(self):
        # Various Launchpad services need to use the authserver to get
        # information about branches, unencumbered by petty restrictions of
        # ownership or privacy. `run_as_requester` detects the special
        # username `LAUNCHPAD_SERVICES` and passes that through to the
        # decorated function without logging in.
        username = self.example.getRequestingUser(LAUNCHPAD_SERVICES)
        self.assertEqual(LAUNCHPAD_SERVICES, username)
        login_id = self.example.getLoggedInUsername(LAUNCHPAD_SERVICES)
        self.assertEqual(None, login_id)


class DatabaseTest(unittest.TestCase):
    """Base class for authserver database tests.

    Runs the tests in using the web database adapter and the stricter Launchpad
    security model. Provides a `cursor` instance variable for ad-hoc queries.
    """

    layer = LaunchpadScriptLayer

    def setUp(self):
        LaunchpadScriptLayer.switchDbConfig('authserver')
        super(DatabaseTest, self).setUp()
        self._old_policy = getSecurityPolicy()
        setSecurityPolicy(LaunchpadSecurityPolicy)
        self.cursor = cursor()

    def tearDown(self):
        setSecurityPolicy(self._old_policy)
        super(DatabaseTest, self).tearDown()

    def getNextMirrorTime(self, branch_id):
        """Return the value of next_mirror_time for the branch with the given
        id.

        :param branch_id: The id of a row in the Branch table. An int.
        :return: A timestamp or None.
        """
        cur = cursor()
        cur.execute(
            "SELECT next_mirror_time FROM branch WHERE id = %s"
            % sqlvalues(branch_id))
        return cur.fetchone()[0]

    def setNextMirrorTime(self, branch_id, next_mirror_time):
        """Set next_mirror_time on the branch with the given id."""
        self.cursor.execute(
            "UPDATE Branch SET next_mirror_time = %s WHERE id = %s"
            % sqlvalues(next_mirror_time, branch_id))

    def setSeriesDateLastSynced(self, series_id, value=None, now_minus=None):
        """Helper to set the datelastsynced of a ProductSeries.

        :param series_id: Database id of the ProductSeries to update.
        :param value: SQL expression to set datelastsynced to.
        :param now_minus: shorthand to set a value before the current time.
        """
        # Exactly one of value or now_minus must be set.
        self.failUnless(
            (value is None) ^ (now_minus is None),
            "Exactly one of value or now_minus must be set")
        if now_minus is not None:
            value = ("CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - interval '%s'"
                     % now_minus)
        self.cursor.execute(
            "UPDATE ProductSeries SET datelastsynced = (%s) WHERE id = %d"
            % (value, series_id))

    def setBranchLastMirrorAttempt(self, branch_id, value=None,
                                   now_minus=None):
        """Helper to set the last_mirror_attempt of a Branch.

        :param branch_id: Database id of the Branch to update.
        :param value: SQL expression to set last_mirror_attempt to.
        :param now_minus: shorthand to set a value before the current time.
        """
        # Exactly one of value or now_minus must be set.
        self.failUnless(
            (value is None) ^ (now_minus is None),
            "Exactly one of value or now_minus must be set")
        if now_minus is not None:
            value = ("CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - interval '%s'"
                     % now_minus)
        self.cursor.execute(
            "UPDATE Branch SET last_mirror_attempt = (%s) WHERE id = %d"
            % (value, branch_id))


class UserDetailsStorageTest(DatabaseTest):

    def setUp(self):
        super(UserDetailsStorageTest, self).setUp()
        self.salt = '\xf4;\x15a\xe4W\x1f'

    def test_verifyInterface(self):
        self.failUnless(verifyObject(IUserDetailsStorage,
                                     DatabaseUserDetailsStorage(None)))
        self.failUnless(verifyObject(IUserDetailsStorageV2,
                                     DatabaseUserDetailsStorageV2(None)))
        self.failUnless(verifyObject(IHostedBranchStorage,
                                     DatabaseUserDetailsStorageV2(None)))

    def test_getUser(self):
        # Getting a user should return a valid dictionary of details
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('mark@hbd.com')
        self.assertEqual('Mark Shuttleworth', userDict['displayname'])
        self.assertEqual(['mark@hbd.com'], userDict['emailaddresses'])
        self.assertEqual('MarkShuttleworth', userDict['wikiname'])
        self.failUnless(userDict.has_key('salt'))

        # Getting by ID should give the same result as getting by email
        userDict2 = storage._getUserInteraction(userDict['id'])
        self.assertEqual(userDict, userDict2)

        # Getting by nickname should also give the same result
        userDict3 = storage._getUserInteraction('sabdfl')
        self.assertEqual(userDict, userDict3)

    def test_getUserMissing(self):
        # Getting a non-existent user should return {}
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('noone@fake.email')
        self.assertEqual({}, userDict)

        # Ditto for getting a non-existent user by id :)
        userDict = storage._getUserInteraction(9999)
        self.assertEqual({}, userDict)

    def test_getUserMultipleAddresses(self):
        # Getting a user with multiple addresses should return all the
        # confirmed addresses.
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('stuart.bishop@canonical.com')
        self.assertEqual('Stuart Bishop', userDict['displayname'])
        self.assertEqual(
            set(['stuart.bishop@canonical.com', 'stuart@stuartbishop.net']),
            set(userDict['emailaddresses']))

    def test_noUnconfirmedAddresses(self):
        # Unconfirmed addresses should not be returned, so if we add a NEW
        # address, it won't change the result.
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('stuart.bishop@canonical.com')

        transaction.begin()
        login(ANONYMOUS)
        stub = getUtility(IPersonSet).getByName('stub')
        email_set = getUtility(IEmailAddressSet)
        email = email_set.new('sb@example.com', stub, EmailAddressStatus.NEW)
        logout()
        transaction.commit()

        userDict2 = storage._getUserInteraction('stuart.bishop@canonical.com')
        self.assertEqual(userDict, userDict2)

    def test_preferredEmailFirst(self):
        # If there's a PREFERRED address, it should be first in the
        # emailaddresses list.  Let's make stuart@stuartbishop.net PREFERRED
        # rather than stuart.bishop@canonical.com.
        transaction.begin()
        email_set = getUtility(IEmailAddressSet)

        email = email_set.getByEmail('stuart.bishop@canonical.com')
        email.status = EmailAddressStatus.VALIDATED
        email.syncUpdate()

        email = email_set.getByEmail('stuart@stuartbishop.net')
        email.status = EmailAddressStatus.PREFERRED
        email.syncUpdate()
        transaction.commit()

        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('stuart.bishop@canonical.com')
        self.assertEqual(
            ['stuart@stuartbishop.net', 'stuart.bishop@canonical.com'],
            userDict['emailaddresses'])

    def test_emailAlphabeticallySorted(self):
        # Although the preferred email address is first in the emailaddresses
        # list, the rest are alphabetically sorted.
        transaction.begin()
        stub = getUtility(IPersonSet).getByName('stub')
        email_set = getUtility(IEmailAddressSet)
        # Use a silly email address that is going to appear before all others
        # in alphabetical sorting.
        email = email_set.new(
            '_stub@canonical.com', stub, EmailAddressStatus.VALIDATED)
        transaction.commit()

        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction('stub')
        self.assertEqual(
            ['stuart.bishop@canonical.com', '_stub@canonical.com',
             'stuart@stuartbishop.net'],
            userDict['emailaddresses'])

    def test_authUserNoUser(self):
        # Authing a user that doesn't exist should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        userDict = storage._authUserInteraction('noone@fake.email', ssha)
        self.assertEqual({}, userDict)

    def test_authUserNullPassword(self):
        # Authing a user with a NULL password should always return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        # The 'admins' user in the sample data has no password, so we use
        # that.
        userDict = storage._authUserInteraction('admins', ssha)
        self.assertEqual({}, userDict)

    def test_authUserUnconfirmedEmail(self):
        # Unconfirmed email addresses cannot be used to log in.
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        self.cursor.execute("""
            INSERT INTO AccountPassword (account, password)
            VALUES (
                (SELECT account FROM EmailAddress
                WHERE email='justdave@bugzilla.org'), %s
                )
            """ % sqlvalues(ssha))
        userDict = storage._authUserInteraction('justdave@bugzilla.org', ssha)
        self.assertEqual({}, userDict)

    def test_authUser(self):
        # Authenticating a user with the right password should work
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction('mark@hbd.com', ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction('mark@hbd.com')
        self.assertEqual(goodDict, userDict)

        # Unicode email addresses are handled too.
        cur = cursor()
        cur.execute(
            "INSERT INTO EmailAddress (person, email, status) "
            "VALUES (1, %s, 2)"  # 2 == Validated
            % sqlvalues(u'm\xe3rk@hbd.com'))
        transaction.commit()
        userDict = storage._authUserInteraction(u'm\xe3rk@hbd.com', ssha)
        goodDict = storage._getUserInteraction(u'm\xe3rk@hbd.com')
        self.assertEqual(goodDict, userDict)

    def test_authUserByNickname(self):
        # Authing a user by their nickname should work, just like an email
        # address in test_authUser.
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction('sabdfl', ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction('sabdfl')
        self.assertEqual(goodDict, userDict)

        # And it should be the same as returned by looking them up by email
        # address.
        goodDict = storage._getUserInteraction('mark@hbd.com')
        self.assertEqual(goodDict, userDict)

    def test_authUserByNicknameNoEmailAddr(self):
        # Just like test_authUserByNickname, but for a user with no email
        # address.  The result should be the same.

        # The authserver isn't allowed to delete email addresses.
        LaunchpadScriptLayer.switchDbConfig('launchpad')
        self.cursor = cursor()
        self.cursor.execute(
            "DELETE FROM EmailAddress WHERE person = 1;"
        )
        LaunchpadScriptLayer.switchDbConfig('authserver')

        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction('sabdfl', ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction('sabdfl')
        self.assertEqual(goodDict, userDict)

    def test_authUserBadPassword(self):
        # Authing a real user with the wrong password should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('wrong', self.salt)
        userDict = storage._authUserInteraction('mark@hbd.com', ssha)
        self.assertEqual({}, userDict)

    def test_getSSHKeys_empty(self):
        # getSSHKeys returns an empty list for users without SSH keys.
        storage = DatabaseUserDetailsStorage(None)
        keys = storage._getSSHKeysInteraction('no-priv')
        self.assertEqual([], keys)

    def test_getSSHKeys_no_such_user(self):
        storage = DatabaseUserDetailsStorage(None)
        keys = storage._getSSHKeysInteraction('no-such-user')
        self.assertEqual([], keys)

    def test_getSSHKeys(self):
        # getSSHKeys returns a list of keytype, keytext tuples for users with
        # SSH keys.

        self.cursor.execute("""
            SELECT keytext FROM SSHKey
            JOIN Person ON (SSHKey.person = Person.id)
            WHERE Person.name = 'sabdfl'
            """)
        expected_keytext = self.cursor.fetchone()[0]

        storage = DatabaseUserDetailsStorage(None)
        keytype, keytext = storage._getSSHKeysInteraction('sabdfl')[0]
        self.assertEqual('DSA', keytype)
        self.assertEqual(expected_keytext, keytext)


class XMLRPCTestHelper:
    """A mixin that defines a useful method for testing a XML-RPC interface.
    """

    def assertRaisesFault(self, code, string, callable, *args, **kw):
        """Assert that calling callable(*args, **kw) raises an xmlrpc Fault.

        The faultCode and faultString of the Fault are compared
        against 'code' and 'string'.
        """
        try:
            callable(*args, **kw)
        except Fault, e:
            self.assertEquals(e.faultCode, code)
            self.assertEquals(e.faultString, string)
        else:
            self.fail("Did not raise!")


class HostedBranchStorageTest(DatabaseTest, XMLRPCTestHelper):
    """Tests for the implementation of `IHostedBranchStorage`."""

    def setUp(self):
        super(HostedBranchStorageTest, self).setUp()
        self.factory = LaunchpadObjectFactory()
        self.arbitrary_person = self.factory.makePerson()
        transaction.commit()

    def test_verifyInterface(self):
        self.failUnless(verifyObject(IBranchDetailsStorage,
                                     DatabaseBranchDetailsStorage(None)))

    def test_createBranch(self):
        storage = DatabaseUserDetailsStorageV2(None)
        branchID = storage._createBranchInteraction(
            12, 'name12', 'firefox', 'foo')
        # Assert branchID now appears in database. Note that title and summary
        # should be NULL, and author should be set to the owner.
        cur = cursor()
        cur.execute("""
            SELECT Person.name, Product.name, Branch.name, Branch.title,
                Branch.summary, Branch.author
            FROM Branch, Person, Product
            WHERE Branch.id = %d
            AND Person.id = Branch.owner
            AND Product.id = Branch.product
            """
            % branchID)
        self.assertEqual(
            ('name12', 'firefox', 'foo', None, None, 12), cur.fetchone())

    def test_createBranch_junk(self):
        # Create a branch with NULL product too:
        storage = DatabaseUserDetailsStorageV2(None)
        branchID = storage._createBranchInteraction(
            1, 'sabdfl', '+junk', 'foo')
        cur = cursor()
        cur.execute("""
            SELECT Person.name, Branch.product, Branch.name, Branch.title,
                Branch.summary, Branch.author
            FROM Branch, Person
            WHERE Branch.id = %d
            AND Person.id = Branch.owner
            """
            % branchID)
        self.assertEqual(
            ('sabdfl', None, 'foo', None, None, 1), cur.fetchone())

    def test_createBranch_bad_product(self):
        # Test that creating a branch for a non-existant product fails.
        storage = DatabaseUserDetailsStorageV2(None)
        message = "Project 'no-such-product' does not exist."
        self.assertRaisesFault(
            NOT_FOUND_FAULT_CODE, message,
            storage._createBranchInteraction,
            1, 'sabdfl', 'no-such-product', 'foo')

    def test_createBranch_other_user(self):
        # Test that creating a branch under another user's directory fails.
        storage = DatabaseUserDetailsStorageV2(None)
        message = ("Mark Shuttleworth cannot create branches owned by "
                   "No Privileges Person")
        self.assertRaisesFault(
            PERMISSION_DENIED_FAULT_CODE, message,
            storage._createBranchInteraction,
            1, 'no-priv', 'firefox', 'foo')

    def test_createBranch_bad_name(self):
        # Test that creating a branch with an invalid name fails.
        storage = DatabaseUserDetailsStorageV2(None)
        self.assertRaisesFault(
            PERMISSION_DENIED_FAULT_CODE,
            ("Invalid branch name 'invalid name!'. %s" %
                BRANCH_NAME_VALIDATION_ERROR_MESSAGE),
            storage._createBranchInteraction,
            12, 'name12', 'firefox', 'invalid name!')

    def test_createBranch_bad_user(self):
        # Test that creating a branch under a non-existent user fails.
        storage = DatabaseUserDetailsStorageV2(None)
        message = "User/team 'no-one' does not exist."
        self.assertRaisesFault(
            NOT_FOUND_FAULT_CODE, message,
            storage._createBranchInteraction,
            12, 'no-one', 'firefox', 'branch')
        # If both the user and the product are not found, then the missing
        # user "wins" the error reporting race (as the url reads
        # ~user/product/branch).
        self.assertRaisesFault(
            NOT_FOUND_FAULT_CODE, message,
            storage._createBranchInteraction,
            12, 'no-one', 'no-such-product', 'branch')

    def test_fetchProductID(self):
        storage = DatabaseUserDetailsStorageV2(None)
        productID = storage._fetchProductIDInteraction('firefox')
        self.assertEqual(4, productID)

        # Invalid product names are signalled by a return value of ''
        productID = storage._fetchProductIDInteraction('xxxxx')
        self.assertEqual('', productID)

    def test_getBranchesForUser(self):
        # getBranchesForUser returns all of the hosted branches that a user
        # may write to. The branches are grouped by product, and are specified
        # by name and id. The name and id of the products are also included.
        transaction.begin()
        no_priv = getUtility(IPersonSet).getByName('no-priv')
        firefox = getUtility(IProductSet).getByName('firefox')
        new_branch = getUtility(IBranchSet).new(
            BranchType.HOSTED, 'branch2', no_priv, no_priv, firefox, None)
        # We only create new_branch so that we can test getBranchesForUser.
        # Zope's security is not relevant and only gets in the way, because
        # there's no logged in user.
        new_branch = removeSecurityProxy(new_branch)
        transaction.commit()

        storage = DatabaseUserDetailsStorageV2(None)
        fetched_branches = storage._getBranchesForUserInteraction(no_priv.id)

        self.assertEqual(
            [(no_priv.id,
              [((firefox.id, firefox.name),
                [(new_branch.id, new_branch.name)])])],
            fetched_branches)

    def test_getBranchesForUserNullProduct(self):
        # getBranchesForUser returns branches for hosted branches with no
        # product.
        login(ANONYMOUS)
        try:
            person = getUtility(IPersonSet).get(12)
            login_email = person.preferredemail.email
        finally:
            logout()

        transaction.begin()
        login(login_email)
        try:
            branch = getUtility(IBranchSet).new(
                BranchType.HOSTED, 'foo-branch', person, person, None, None,
                None)
        finally:
            logout()
            transaction.commit()

        storage = DatabaseUserDetailsStorageV2(None)
        branchInfo = storage._getBranchesForUserInteraction(12)

        for person_id, by_product in branchInfo:
            if person_id == 12:
                for (product_id, product_name), branches in by_product:
                    if product_id == '':
                        self.assertEqual('', product_name)
                        self.assertEqual(1, len(branches))
                        branch_id, branch_name = branches[0]
                        self.assertEqual('foo-branch', branch_name)
                        break
                else:
                    self.fail("Couldn't find +junk branch")
                break
        else:
            self.fail("Couldn't find user 12")

    def test_getBranchInformation_owned(self):
        # When we get the branch information for one of our own branches (i.e.
        # owned by us or by a team we are on), we get the database id of the
        # branch, and a flag saying that we can write to that branch.
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'name12', 'gnome-terminal', 'pushed')
        self.assertEqual(25, branch_id)
        self.assertEqual(WRITABLE, permissions)

    def test_getBranchInformation_nonexistent(self):
        # When we get the branch information for a non-existent branch, we get
        # a tuple of two empty strings (the empty string being an
        # approximation of 'None').
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'name12', 'gnome-terminal', 'doesnt-exist')
        self.assertEqual('', branch_id)
        self.assertEqual('', permissions)

    def test_getBranchInformation_unowned(self):
        # When we get the branch information for a branch that we don't own,
        # we get the database id and a flag saying that we can only read that
        # branch.
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'sabdfl', 'firefox', 'release-0.8')
        self.assertEqual(13, branch_id)
        self.assertEqual(READ_ONLY, permissions)

    def test_getBranchInformation_mirrored(self):
        # Mirrored branches cannot be written to by the smartserver or SFTP
        # server.
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'name12', 'firefox', 'main')
        self.assertEqual(1, branch_id)
        self.assertEqual(READ_ONLY, permissions)

    def test_getBranchInformation_imported(self):
        # Imported branches cannot be written to by the smartserver or SFTP
        # server.
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'vcs-imports', 'gnome-terminal', 'import')
        self.assertEqual(75, branch_id)
        self.assertEqual(READ_ONLY, permissions)

    def test_getBranchInformation_remote(self):
        # Remote branches are not accessible by the smartserver or SFTP
        # server.
        no_priv = getUtility(IPersonSet).getByName('no-priv')
        firefox = getUtility(IProductSet).getByName('firefox')
        branch = getUtility(IBranchSet).new(
            BranchType.REMOTE, 'remote', no_priv, no_priv, firefox, None)
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            12, 'no-priv', 'firefox', 'remote')
        self.assertEqual('', branch_id)
        self.assertEqual('', permissions)

    def test_getBranchInformation_private(self):
        # When we get the branch information for a private branch that is
        # hidden to us, it is an if the branch doesn't exist at all.
        store = DatabaseUserDetailsStorageV2(None)

        # salgado is a member of landscape-developers.
        person_set = getUtility(IPersonSet)
        salgado = person_set.getByName('salgado')
        landscape_dev = person_set.getByName('landscape-developers')
        self.assertTrue(
            salgado.inTeam(landscape_dev),
            "salgado should be in landscape-developers team, but isn't.")

        store._createBranchInteraction(
            'salgado', 'landscape-developers', 'landscape',
            'some-branch')
        # ddaa is not an admin, not a Landscape developer.
        branch_id, permissions = store._getBranchInformationInteraction(
            'ddaa', 'landscape-developers', 'landscape', 'some-branch')
        self.assertEqual('', branch_id)
        self.assertEqual('', permissions)

    def test_getBranchInformationAsLaunchpadServices(self):
        # The LAUNCHPAD_SERVICES special "user" has read-only access to all
        # branches.
        store = DatabaseUserDetailsStorageV2(None)
        branch_id, permissions = store._getBranchInformationInteraction(
            LAUNCHPAD_SERVICES, 'name12', 'gnome-terminal', 'pushed')
        self.assertEqual(25, branch_id)
        self.assertEqual(READ_ONLY, permissions)

    def test_getBranchInformationForPrivateAsLaunchpadServices(self):
        # The LAUNCHPAD_SERVICES special "user" has read-only access to all
        # branches, even private ones.
        store = DatabaseUserDetailsStorageV2(None)

        # salgado is a member of landscape-developers.
        person_set = getUtility(IPersonSet)
        salgado = person_set.getByName('salgado')
        landscape_dev = person_set.getByName('landscape-developers')
        self.assertTrue(
            salgado.inTeam(landscape_dev),
            "salgado should be in landscape-developers team, but isn't.")

        branch_id = store._createBranchInteraction(
            'salgado', 'landscape-developers', 'landscape',
            'some-branch')
        login(ANONYMOUS)
        try:
            branch = getUtility(IBranchSet).get(branch_id)
            self.assertTrue(
                removeSecurityProxy(branch).private,
                "%r not private" % (branch,))
        finally:
            logout()
        branch_info = store._getBranchInformationInteraction(
            LAUNCHPAD_SERVICES, 'landscape-developers', 'landscape',
            'some-branch')
        self.assertEqual((branch_id, 'r'), branch_info)

    @writing_transaction
    def _makeProductWithPrivateDevFocus(self):
        """Make a product with a private development focus.

        :return: The new Product and the new Branch.
        """
        product = self.factory.makeProduct()
        branch = self.factory.makeBranch(product=product)
        series = removeSecurityProxy(product.development_focus)
        series.user_branch = branch
        removeSecurityProxy(branch).private = True
        return product, branch

    def test_getDefaultStackedOnBranch_invisible(self):
        # When the default stacked-on branch for a product is not visible to
        # the requesting user, then we return the empty string.
        product, branch = self._makeProductWithPrivateDevFocus()
        store = DatabaseUserDetailsStorageV2(None)
        stacked_on_url = store._getDefaultStackedOnBranchInteraction(
            self.arbitrary_person.id, product.name)
        self.assertEqual('', stacked_on_url)

    def test_getDefaultStackedOnBranch_private(self):
        # When the default stacked-on branch for a product is private but
        # visible to the requesting user, we return the URL to the branch
        # relative to the host.
        product, branch = self._makeProductWithPrivateDevFocus()
        # We want to know who owns it and what its name is. We are a test and
        # should be allowed to know such things.
        branch = removeSecurityProxy(branch)
        store = DatabaseUserDetailsStorageV2(None)
        stacked_on_url = store._getDefaultStackedOnBranchInteraction(
            branch.owner.id, product.name)
        self.assertEqual('/' + branch.unique_name, stacked_on_url)

    def test_getDefaultStackedOnBranch_junk(self):
        # getDefaultStackedOnBranch returns the empty string for '+junk'.
        store = DatabaseUserDetailsStorageV2(None)
        branch = store._getDefaultStackedOnBranchInteraction(
            self.arbitrary_person.id, '+junk')
        self.assertEqual('', branch)

    def test_getDefaultStackedOnBranch_none_set(self):
        # getDefaultStackedOnBranch returns the empty string when there is no
        # branch set.
        store = DatabaseUserDetailsStorageV2(None)
        branch = store._getDefaultStackedOnBranchInteraction(
            self.arbitrary_person.id, 'firefox')
        self.assertEqual('', branch)

    def test_getDefaultStackedOnBranch_no_product(self):
        # getDefaultStackedOnBranch raises a Fault if there is no such
        # product.
        store = DatabaseUserDetailsStorageV2(None)
        product = 'no-such-product'
        self.assertRaisesFault(
            NOT_FOUND_FAULT_CODE,
            'Project %r does not exist.' % (product,),
            store._getDefaultStackedOnBranchInteraction,
            self.arbitrary_person.id, product)

    def test_getDefaultStackedOnBranch(self):
        # getDefaultStackedOnBranch returns the relative URL of the default
        # stacked-on branch for the named product.
        store = DatabaseUserDetailsStorageV2(None)
        branch = store._getDefaultStackedOnBranchInteraction(
            self.arbitrary_person.id, 'evolution')
        self.assertEqual('/~vcs-imports/evolution/main', branch)

    def test_initialMirrorRequest(self):
        # The default 'next_mirror_time' for a newly created hosted branch
        # should be None.
        storage = DatabaseUserDetailsStorageV2(None)
        branchID = storage._createBranchInteraction(
            1, 'sabdfl', '+junk', 'foo')
        self.assertEqual(self.getNextMirrorTime(branchID), None)

    def test_requestMirror(self):
        # requestMirror should set the next_mirror_time field to be the
        # current time.
        hosted_branch_id = 25
        # make sure the sample data is sane
        self.assertEqual(None, self.getNextMirrorTime(hosted_branch_id))

        cur = cursor()
        cur.execute("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")
        [current_db_time] = cur.fetchone()
        transaction.commit()

        storage = DatabaseUserDetailsStorageV2(None)
        storage._requestMirrorInteraction(1, hosted_branch_id)

        self.assertTrue(
            current_db_time < self.getNextMirrorTime(hosted_branch_id),
            "Branch next_mirror_time not updated.")

    def test_requestMirror_private(self):
        # requestMirror can be used to request the mirror of a private branch.
        store = DatabaseUserDetailsStorageV2(None)

        # salgado is a member of landscape-developers.
        person_set = getUtility(IPersonSet)
        salgado = person_set.getByName('salgado')
        landscape_dev = person_set.getByName('landscape-developers')
        self.assertTrue(
            salgado.inTeam(landscape_dev),
            "salgado should be in landscape-developers team, but isn't.")

        branch_id = store._createBranchInteraction(
            'salgado', 'landscape-developers', 'landscape',
            'some-branch')

        cur = cursor()
        cur.execute("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")
        [current_db_time] = cur.fetchone()
        transaction.commit()

        store._requestMirrorInteraction(salgado.id, branch_id)
        self.assertTrue(
            current_db_time < self.getNextMirrorTime(branch_id),
            "Branch next_mirror_time not updated.")


    def test_mirrorComplete_resets_mirror_request(self):
        # After successfully mirroring a branch, next_mirror_time should be
        # set to NULL.

        # An arbitrary hosted branch.
        hosted_branch_id = 25

        # The user id of a person who can see the hosted branch.
        user_id = 1

        # Request that 25 (a hosted branch) be mirrored. This sets
        # next_mirror_time.
        storage = DatabaseUserDetailsStorageV2(None)
        storage._requestMirrorInteraction(user_id, hosted_branch_id)

        # Simulate successfully mirroring branch 25
        storage = DatabaseBranchDetailsStorage(None)
        cur = cursor()
        storage._startMirroringInteraction(hosted_branch_id)
        storage._mirrorCompleteInteraction(hosted_branch_id, 'rev-1')

        self.assertEqual(None, self.getNextMirrorTime(hosted_branch_id))


class TestTransactionDecorators(DatabaseTest):
    """Tests for the transaction decorators used by the authserver."""

    def setUp(self):
        super(TestTransactionDecorators, self).setUp()
        self.store = getUtility(IZStorm).get('main')
        self.no_priv = self.store.find(Person, name='no-priv').one()

    def test_read_only_transaction_reset_store(self):
        """Make sure that the store is reset after the transaction."""
        @read_only_transaction
        def no_op():
            pass
        no_op()
        self.failIf(
            self.no_priv is self.store.find(Person, name='no-priv').one(),
            "Store wasn't reset properly.")

    def test_writing_transaction_reset_store(self):
        """Make sure that the store is reset after the transaction."""
        @writing_transaction
        def no_op():
            pass
        no_op()
        self.failIf(
            self.no_priv is self.store.find(Person, name='no-priv').one(),
            "Store wasn't reset properly.")


class UserDetailsStorageV2Test(DatabaseTest):
    """Test the implementation of `IUserDetailsStorageV2`."""

    def test_teamDict(self):
        # The user dict from a V2 storage should include a 'teams' element
        # with a list of team dicts, one for each team the user is in,
        # including the user.

        # Get a user dict
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction('mark@hbd.com')

        # Sort the teams by id, they may be returned in any order.
        teams = sorted(userDict['teams'], key=lambda teamDict: teamDict['id'])

        # Mark should be in his own team, Ubuntu Team, Launchpad
        # Administrators and testing Spanish team, and other teams of which
        # Launchpad Administrators is a member or owner.
        self.assertEqual(
            [{'displayname': u'Mark Shuttleworth',
              'id': 1, 'name': u'sabdfl'},
             {'displayname': u'Ubuntu Team',
              'id': 17, 'name': u'ubuntu-team'},
             {'displayname': u'Launchpad Administrators',
              'id': 25, 'name': u'admins'},
             {'displayname': u'testing Spanish team',
              'id': 53, 'name': u'testing-spanish-team'},
             {'displayname': u'Mirror Administrators',
              'id': 59, 'name': u'ubuntu-mirror-admins'},
             {'displayname': u'Registry Administrators', 'id': 60,
              'name': u'registry'},
             {'displayname': u'Mailing List Experts',
              'name': u'mailing-list-experts', 'id': 243607},
            ], teams)

        # The dict returned by authUser should be identical.
        userDict2 = storage._authUserInteraction('mark@hbd.com', 'test')
        self.assertEqual(userDict, userDict2)

    def test_authUserUnconfirmedEmail(self):
        # Unconfirmed email addresses cannot be used to log in.
        storage = DatabaseUserDetailsStorageV2(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        self.cursor.execute("""
            INSERT INTO AccountPassword (account, password)
            VALUES (
                (SELECT account FROM EmailAddress
                WHERE email = 'justdave@bugzilla.org'), %s
                )
            """, (ssha,))
        userDict = storage._authUserInteraction(
            'justdave@bugzilla.org', 'supersecret!')
        self.assertEqual({}, userDict)

    def test_nameInV2UserDict(self):
        # V2 user dicts should have a 'name' field.
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction('mark@hbd.com')
        self.assertEqual('sabdfl', userDict['name'])

    def test_getUserNoWikiname(self):
        # Ensure that the authserver copes gracefully with users with:
        #    a) no wikinames at all
        #    b) no wikiname for http://www.ubuntulinux.com/wiki/
        # (even though in the long run we want to make sure these situations
        # can never happen, until then the authserver should be robust).

        # First, make sure that the sample user has no wikiname.
        transaction.begin()
        person = getUtility(IPersonSet).getByEmail('test@canonical.com')
        wiki_names = getUtility(IWikiNameSet).getAllWikisByPerson(person)
        for wiki_name in wiki_names:
            wiki_name.destroySelf()
        transaction.commit()

        # Get the user dict for Sample Person (test@canonical.com).
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction('test@canonical.com')

        # The user dict has results, even though the wikiname is empty
        self.assertNotEqual({}, userDict)
        self.assertEqual('', userDict['wikiname'])
        self.assertEqual(12, userDict['id'])

        # Now lets add a wikiname, but for a different wiki.
        transaction.begin()
        login(ANONYMOUS)
        person = getUtility(IPersonSet).getByEmail('test@canonical.com')
        getUtility(IWikiNameSet).new(
            person, 'http://foowiki/', 'SamplePerson')
        logout()
        transaction.commit()

        # The authserver should return exactly the same results.
        userDict2 = storage._getUserInteraction('test@canonical.com')
        self.assertEqual(userDict, userDict2)


class BranchDetailsStorageTest(DatabaseTest):
    """Tests for the implementation of `IBranchDetailsStorage`."""

    def setUp(self):
        super(BranchDetailsStorageTest, self).setUp()
        self.storage = DatabaseBranchDetailsStorage(None)

    def test_startMirroring(self):
        # verify that the last mirror time is None before hand.
        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertEqual(row[0], None)
        self.assertEqual(row[1], None)

        success = self.storage._startMirroringInteraction(1)
        self.assertEqual(success, True)

        # verify that last_mirror_attempt is set
        cur = cursor()
        cur.execute("""
            SELECT last_mirror_attempt, last_mirrored
                FROM branch WHERE id = 1""")
        row = cur.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[1], None)

    def test_startMirroring_invalid_branch(self):
        # verify that no branch exists with id == -1
        self.cursor.execute("""
            SELECT id FROM branch WHERE id = -1""")
        self.assertEqual(self.cursor.rowcount, 0)

        success = self.storage._startMirroringInteraction(-11)
        self.assertEqual(success, False)

    def test_mirrorFailed(self):
        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures,
                mirror_status_message
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertEqual(row[0], None)
        self.assertEqual(row[1], None)
        self.assertEqual(row[2], 0)
        self.assertEqual(row[3], None)

        success = self.storage._startMirroringInteraction(1)
        self.assertEqual(success, True)
        success = self.storage._mirrorFailedInteraction(1, "failed")
        self.assertEqual(success, True)

        cur = cursor()
        cur.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures,
                mirror_status_message
                FROM branch WHERE id = 1""")
        row = cur.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[1], None)
        self.assertEqual(row[2], 1)
        self.assertEqual(row[3], 'failed')

    def test_mirrorComplete(self):
        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertEqual(row[0], None)
        self.assertEqual(row[1], None)
        self.assertEqual(row[2], 0)

        success = self.storage._startMirroringInteraction(1)
        self.assertEqual(success, True)
        success = self.storage._mirrorCompleteInteraction(1, 'rev-1')
        self.assertEqual(success, True)

        cur = cursor()
        cur.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures,
                   last_mirrored_id
                FROM branch WHERE id = 1""")
        row = cur.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[0], row[1])
        self.assertEqual(row[2], 0)
        self.assertEqual(row[3], 'rev-1')

    def test_mirrorComplete_resets_failure_count(self):
        # this increments the failure count ...
        self.test_mirrorFailed()

        success = self.storage._startMirroringInteraction(1)
        self.assertEqual(success, True)
        success = self.storage._mirrorCompleteInteraction(1, 'rev-1')
        self.assertEqual(success, True)

        cur = cursor()
        cur.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures
                FROM branch WHERE id = 1""")
        row = cur.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[0], row[1])
        self.assertEqual(row[2], 0)

    def test_recordSuccess(self):
        # recordSuccess must insert the given data into BranchActivity.
        started = datetime.datetime(2007, 07, 05, 19, 32, 1, tzinfo=UTC)
        completed = datetime.datetime(2007, 07, 05, 19, 34, 24, tzinfo=UTC)
        started_tuple = tuple(started.utctimetuple())
        completed_tuple = tuple(completed.utctimetuple())
        success = self.storage._recordSuccessInteraction(
            'test-recordsuccess', 'vostok', started_tuple, completed_tuple)
        self.assertEqual(success, True, '_recordSuccessInteraction failed')

        cur = cursor()
        cur.execute("""
            SELECT name, hostname, date_started, date_completed
                FROM ScriptActivity where name = 'test-recordsuccess'""")
        row = cur.fetchone()
        self.assertEqual(row[0], 'test-recordsuccess')
        self.assertEqual(row[1], 'vostok')
        self.assertEqual(row[2], started.replace(tzinfo=None))
        self.assertEqual(row[3], completed.replace(tzinfo=None))


class BranchPullQueueTest(BranchTestCase):
    """Tests for the pull queue methods of `IBranchDetailsStorage`."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        LaunchpadScriptLayer.switchDbConfig('authserver')
        super(BranchPullQueueTest, self).setUp()
        self.restrictSecurityPolicy()
        self.emptyPullQueues()
        self.storage = DatabaseBranchDetailsStorage(None)

    def assertBranchQueues(self, hosted, mirrored, imported):
        login(ANONYMOUS)
        self.assertEqual(
            map(self.storage._getBranchPullInfo, hosted),
            self.storage._getBranchPullQueueInteraction('HOSTED'))
        login(ANONYMOUS)
        self.assertEqual(
            map(self.storage._getBranchPullInfo, mirrored),
            self.storage._getBranchPullQueueInteraction('MIRRORED'))
        login(ANONYMOUS)
        self.assertEqual(
            map(self.storage._getBranchPullInfo, imported),
            self.storage._getBranchPullQueueInteraction('IMPORTED'))

    def test_pullQueuesEmpty(self):
        """getBranchPullQueue returns an empty list when there are no branches
        to pull.
        """
        self.assertBranchQueues([], [], [])

    def makeBranchAndRequestMirror(self, branch_type):
        """Make a branch of the given type and call requestMirror on it."""
        LaunchpadZopelessLayer.switchDbUser('testadmin')
        transaction.begin()
        branch = self.makeBranch(branch_type)
        branch.requestMirror()
        transaction.commit()
        LaunchpadZopelessLayer.switchDbUser('authserver')
        return branch

    def test_requestMirrorPutsBranchInQueue_hosted(self):
        branch = self.makeBranchAndRequestMirror(BranchType.HOSTED)
        self.assertBranchQueues([branch], [], [])

    def test_requestMirrorPutsBranchInQueue_mirrored(self):
        branch = self.makeBranchAndRequestMirror(BranchType.MIRRORED)
        self.assertBranchQueues([], [branch], [])

    def test_requestMirrorPutsBranchInQueue_imported(self):
        branch = self.makeBranchAndRequestMirror(BranchType.IMPORTED)
        self.assertBranchQueues([], [], [branch])


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

