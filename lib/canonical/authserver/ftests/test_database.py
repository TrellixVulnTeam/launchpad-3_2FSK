# Note: these test cases requires the Launchpad sample data.  Run
#   make launchpad_test
# in $launchpad_root/database/schema.

import unittest

import psycopg

from zope.interface.verify import verifyObject

from twisted.enterprise import adbapi

from canonical.launchpad.webapp.authentication import SSHADigestEncryptor

from canonical.authserver.database import DatabaseUserDetailsStorage
from canonical.authserver.database import IUserDetailsStorage
from canonical.lp import dbschema

from canonical.launchpad.ftests.harness import LaunchpadTestCase

class TestDatabaseSetup(LaunchpadTestCase):
    def setUp(self):
        super(TestDatabaseSetup, self).setUp()
        self.connection = self.connect()
        self.cursor = self.connection.cursor()

    def tearDown(self):
        self.cursor.close()
        self.connection.close()
        super(TestDatabaseSetup, self).tearDown()

class DatabaseStorageTestCase(TestDatabaseSetup):
    def test_verifyInterface(self):
        self.failUnless(verifyObject(IUserDetailsStorage,
                                     DatabaseUserDetailsStorage(None)))

    def test_getUser(self):
        # Getting a user should return a valid dictionary of details

        # Note: we access _getUserInteraction directly to avoid mucking around
        # with setting up a ConnectionPool
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual('Mark Shuttleworth', userDict['displayname'])
        self.assertEqual(['mark@hbd.com'], userDict['emailaddresses'])
        self.failUnless(userDict.has_key('salt'))

        # Getting by ID should give the same result as getting by email
        userDict2 = storage._getUserInteraction(self.cursor, userDict['id'])
        self.assertEqual(userDict, userDict2)

        # Getting by nickname should also give the same result
        userDict3 = storage._getUserInteraction(self.cursor, 'sabdfl')
        self.assertEqual(userDict, userDict3)

    def test_getUserMissing(self):
        # Getting a non-existent user should return {}
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction(self.cursor, 'noone@fake.email')
        self.assertEqual({}, userDict)

        # Ditto for getting a non-existent user by id :)
        userDict = storage._getUserInteraction(self.cursor, 9999)
        self.assertEqual({}, userDict)

    def test_getUserMultipleAddresses(self):
        # Getting a user with multiple addresses should return all the
        # addresses
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction(self.cursor, 'justdave@bugzilla.org')
        self.assertEqual('Dave Miller', userDict['displayname'])
        self.assertEqual(['dave.miller@ubuntulinux.com',
                          'justdave@bugzilla.org'],
                         userDict['emailaddresses'])

    def test_authUserNoUser(self):
        # Authing a user that doesn't exist should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        userDict = storage._authUserInteraction(self.cursor, 'noone@fake.email',
                                                ssha)
        self.assertEqual({}, userDict)

class ExtraUserDatabaseStorageTestCase(TestDatabaseSetup):
    # Tests that do some database writes (but makes sure to roll them back)
    def setUp(self):
        TestDatabaseSetup.setUp(self)
        # Add some extra sample data to DB -- none of the standard sample data
        # has passwords.
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        self.fredsalt = ssha.decode('base64')[20:]
        self.cursor.execute(
            "INSERT INTO Person (name, displayname, password) "
            "VALUES ('fflintst', 'Fred Flintstone', '%s')"
            % ssha
        )
        self.cursor.execute(
            "INSERT INTO EmailAddress (person, email, status) "
            "VALUES ("
            "  (SELECT id FROM Person WHERE displayname = 'Fred Flintstone'), "
            "  'fred@bedrock',"
            "  1)"
        )

    def test_authUser(self):
        # Authenticating a user with the right password should work
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!', self.fredsalt)
        userDict = storage._authUserInteraction(self.cursor, 'fred@bedrock',
                                                ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'fred@bedrock')
        self.assertEqual(goodDict, userDict)

    def test_authUserBadPassword(self):
        # Authing a real user with the wrong password should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('wrong', self.fredsalt)
        userDict = storage._authUserInteraction(self.cursor, 'fred@bedrock',
                                                ssha)
        self.assertEqual({}, userDict)

    def test_createUser(self):
        # Creating a user should return a user dict with that user's details
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        displayname = 'Testy the Test User'
        emailaddresses = ['test1@test.test', 'test2@test.test']
        # This test needs a real Transaction, because it calls rollback
        trans = adbapi.Transaction(None, self.connection)
        userDict = storage._createUserInteraction(
            trans, ssha, displayname, emailaddresses
        )
        self.assertNotEqual({}, userDict)
        self.assertEqual(displayname, userDict['displayname'])
        self.assertEqual(emailaddresses, userDict['emailaddresses'])

    def test_createUserUnicode(self):
        # Creating a user should return a user dict with that user's details
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        # Name with an e acute, and an apostrophe too.
        displayname = u'Test\xc3\xa9 the Test\' User'
        emailaddresses = ['test1@test.test', 'test2@test.test']
        # This test needs a real Transaction, because it calls rollback
        trans = adbapi.Transaction(None, self.connection)
        userDict = storage._createUserInteraction(
            trans, ssha, displayname, emailaddresses
        )
        self.assertNotEqual({}, userDict)
        self.assertEqual(displayname, userDict['displayname'])
        self.assertEqual(emailaddresses, userDict['emailaddresses'])

        # Check that the nickname was correctly generated (and that getUser
        # returns the same values that createUser returned)
        userDict2 = storage._getUserInteraction(self.cursor, 'test1')
        self.assertEqual(userDict, userDict2)

    # FIXME: behaviour of this case isn't defined yet
    ##def test_createUserFailure(self):
    ##    # Creating a user with a loginID that already exists should fail

    def test_changePassword(self):
        storage = DatabaseUserDetailsStorage(None)
        # Changing a password should return a user dict with that user's details
        ssha = SSHADigestEncryptor().encrypt('supersecret!', self.fredsalt)
        newSsha = SSHADigestEncryptor().encrypt('testing123')
        userDict = storage._changePasswordInteraction(self.cursor,
                                                      'fred@bedrock', ssha,
                                                      newSsha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'fred@bedrock')
        self.assertEqual(goodDict, userDict)

        # And we should be able to authenticate with the new password...
        authDict = storage._authUserInteraction(self.cursor, 'fred@bedrock',
                                                newSsha)
        self.assertEqual(goodDict, authDict)

        # ...but not the old
        authDict = storage._authUserInteraction(self.cursor, 'fred@bedrock',
                                                ssha)
        self.assertEqual({}, authDict)

    def test_changePasswordFailure(self):
        storage = DatabaseUserDetailsStorage(None)
        # Changing a password without giving the right current pw should fail
        # (i.e. return {})
        ssha = SSHADigestEncryptor().encrypt('WRONG', self.fredsalt)
        newSsha = SSHADigestEncryptor().encrypt('testing123')
        userDict = storage._changePasswordInteraction(self.cursor,
                                                      'fred@bedrock', ssha,
                                                      newSsha)
        self.assertEqual({}, userDict)

    def test_getSSHKeys(self):
        # FIXME: there should probably be some SSH keys in the sample data,
        #        so that this test wouldn't need to add some.

        # Add test SSH keys
        self.cursor.execute(
            "INSERT INTO SSHKey (person, keytype, keytext, comment) "
            "VALUES ("
            "  (SELECT id FROM Person WHERE displayname = 'Fred Flintstone'), "
            "  %d,"
            "  'garbage123',"
            "  'fred@bedrock')"
            % (dbschema.SSHKeyType.DSA,)
        )
        
        storage = DatabaseUserDetailsStorage(None)
        keys = storage._getSSHKeysInteraction(self.cursor, 'fred@bedrock')
        self.assertEqual([(dbschema.SSHKeyType.DSA, 'garbage123')], keys)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(DatabaseStorageTestCase))
    suite.addTest(unittest.makeSuite(ExtraUserDatabaseStorageTestCase))
    return suite

