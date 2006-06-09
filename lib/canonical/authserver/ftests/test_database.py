# Note: these test cases requires the Launchpad sample data.  Run
#   make launchpad_test
# in $launchpad_root/database/schema.

import unittest

import psycopg

from zope.interface.verify import verifyObject

from twisted.enterprise import adbapi

from canonical.launchpad.webapp.authentication import SSHADigestEncryptor

from canonical.authserver.interfaces import (
    IUserDetailsStorage, IBranchDetailsStorage)
from canonical.authserver.database import (
    DatabaseUserDetailsStorage, DatabaseUserDetailsStorageV2,
    DatabaseBranchDetailsStorage)
from canonical.lp import dbschema

from canonical.launchpad.ftests.harness import LaunchpadTestCase

expected_branches_to_pull = [
    (1, 'http://bazaar.example.com/mozilla@arch.ubuntu.com/mozilla--MAIN--0'),
    (2, 'http://bazaar.example.com/thunderbird@arch.ubuntu.com/'
     'thunderbird--MAIN--0'),
    (3, 'http://bazaar.example.com/twisted@arch.ubuntu.com/twisted--trunk--0'),
    (4, 'http://bazaar.example.com/bugzilla@arch.ubuntu.com/bugzila--MAIN--0'),
    (5, 'http://bazaar.example.com/arch@arch.ubuntu.com/arch--devel--1.0'),
    (6, 'http://bazaar.example.com/kiwi2@arch.ubuntu.com/kiwi2--MAIN--0'),
    (7, 'http://bazaar.example.com/plone@arch.ubuntu.com/plone--trunk--0'),
    (8, 'http://bazaar.example.com/gnome@arch.ubuntu.com/'
     'gnome--evolution--2.0'),
    (9, 'http://bazaar.example.com/iso-codes@arch.ubuntu.com/'
     'iso-codes--iso-codes--0.35'),
    (10, 'http://bazaar.example.com/mozilla@arch.ubuntu.com/'
     'mozilla--release--0.9.2'),
    (11, 'http://bazaar.example.com/mozilla@arch.ubuntu.com/'
     'mozilla--release--0.9.1'),
    (12, 'http://bazaar.example.com/mozilla@arch.ubuntu.com/'
     'mozilla--release--0.9'),
    (13, 'http://bazaar.example.com/mozilla@arch.ubuntu.com/'
     'mozilla--release--0.8'),
    (14, 'http://escudero.ubuntu.com:680/0000000e'),
    (15, 'http://example.com/gnome-terminal/main'),
    (16, 'http://example.com/gnome-terminal/2.6'),
    (17, 'http://example.com/gnome-terminal/2.4'),
    (18, 'http://trekkies.example.com/gnome-terminal/klingon'),
    (19, 'http://users.example.com/gnome-terminal/slowness'),
    (20, 'http://localhost:8000/a'),
    (21, 'http://localhost:8000/b'),
    (22, 'http://not.launchpad.server.com/a-branch'),
    (23, 'http://whynot.launchpad.server.com/another-branch'),
    (24, 'http://users.example.com/gnome-terminal/launchpad'),
    (25, '/tmp/sftp-test/branches/00/00/00/19'),
    ]


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
        self.assertEqual('MarkShuttleworth', userDict['wikiname'])
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
        # confirmed addresses.
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction(self.cursor,
                                               'stuart.bishop@canonical.com')
        self.assertEqual('Stuart Bishop', userDict['displayname'])
        self.assertEqual(['stuart.bishop@canonical.com',
                          'stuart@stuartbishop.net'],
                         userDict['emailaddresses'])

    def test_noUnconfirmedAddresses(self):
        # Unconfirmed addresses should not be returned, so if we add a NEW
        # address, it won't change the result.
        storage = DatabaseUserDetailsStorage(None)
        userDict = storage._getUserInteraction(self.cursor,
                                               'stuart.bishop@canonical.com')
        self.cursor.execute('''
            INSERT INTO EmailAddress (email, person, status)
            VALUES ('sb@example.com', %d, %d)
            ''' % (userDict['id'], dbschema.EmailAddressStatus.NEW.value))
        userDict2 = storage._getUserInteraction(self.cursor,
                                                'stuart.bishop@canonical.com')
        self.assertEqual(userDict, userDict2)
        
    def test_preferredEmailFirst(self):
        # If there's a PREFERRED address, it should be first in the
        # emailaddresses list.  Let's make stuart@stuartbishop.net PREFERRED
        # rather than stuart.bishop@canonical.com.
        storage = DatabaseUserDetailsStorage(None)
        self.cursor.execute('''
            UPDATE EmailAddress SET status = %d
            WHERE email = 'stuart.bishop@canonical.com'
            ''' % (dbschema.EmailAddressStatus.VALIDATED.value,))
        self.cursor.execute('''
            UPDATE EmailAddress SET status = %d
            WHERE email = 'stuart@stuartbishop.net'
            ''' % (dbschema.EmailAddressStatus.PREFERRED.value,))
        userDict = storage._getUserInteraction(self.cursor,
                                               'stuart.bishop@canonical.com')
        self.assertEqual(['stuart@stuartbishop.net',
                          'stuart.bishop@canonical.com'],
                         userDict['emailaddresses'])

    def test_authUserNoUser(self):
        # Authing a user that doesn't exist should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        userDict = storage._authUserInteraction(self.cursor, 'noone@fake.email',
                                                ssha)
        self.assertEqual({}, userDict)

    def test_authUserNullPassword(self):
        # Authing a user with a NULL password should always return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        # The 'admins' user in the sample data has no password, so we use that.
        userDict = storage._authUserInteraction(self.cursor, 'admins', ssha)
        self.assertEqual({}, userDict)

    def test_authUserUnconfirmedEmail(self):
        # Unconfirmed email addresses cannot be used to log in.
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        self.cursor.execute('''
            UPDATE Person SET password = '%s'
            WHERE id = (SELECT person FROM EmailAddress WHERE email =
                        'justdave@bugzilla.org')'''
            % (ssha,))
        userDict = storage._authUserInteraction(self.cursor,
                                                'justdave@bugzilla.org', ssha)
        self.assertEqual({}, userDict)

    def test_nameInV2UserDict(self):
        # V2 user dicts should have a 'name' field.
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual('sabdfl', userDict['name'])

    def test_fetchProductID(self):
        storage = DatabaseUserDetailsStorageV2(None)
        productID = storage._fetchProductIDInteraction(self.cursor, 'firefox')
        self.assertEqual(4, productID)
    
        # Invalid product names are signalled by a return value of ''
        productID = storage._fetchProductIDInteraction(self.cursor, 'xxxxx')
        self.assertEqual('', productID)

    def test_getBranchesForUser(self):
        # Although user 12 has lots of branches in the sample data, they only
        # have one push branch: a branch named "pushed" on the "gnome-terminal"
        # product.
        storage = DatabaseUserDetailsStorageV2(None)
        branches = storage._getBranchesForUserInteraction(self.cursor, 12)
        self.assertEqual(1, len(branches))
        gnomeTermProduct = branches[0]
        gnomeTermID, gnomeTermName, gnomeTermBranches = gnomeTermProduct
        self.assertEqual(6, gnomeTermID)
        self.assertEqual('gnome-terminal', gnomeTermName)
        self.assertEqual([(25, 'pushed')], gnomeTermBranches)

    def test_getBranchesForUserNullProduct(self):
        # getBranchesForUser returns branches for hosted branches with no
        # product.

        # First, insert a push branch (url is NULL) with a NULL product.
        self.cursor.execute("""
            INSERT INTO Branch 
                (owner, product, name, title, summary, author, url)
            VALUES 
                (12, NULL, 'foo-branch', NULL, NULL, 12, NULL)
            """)

        storage = DatabaseUserDetailsStorageV2(None)
        branchInfo = storage._getBranchesForUserInteraction(self.cursor, 12)
        self.assertEqual(2, len(branchInfo))

        gnomeTermProduct, junkProduct = branchInfo
        # Results could come back in either order, so swap if necessary.
        if gnomeTermProduct[0] is None:
            gnomeTermProduct, junkProduct = junkProduct, gnomeTermProduct
        
        # Check that the details and branches for the junk product are correct:
        # empty ID and name for the product, with a single branch named
        # 'foo-branch'.
        junkID, junkName, junkBranches = junkProduct
        self.assertEqual('', junkID)
        self.assertEqual('', junkName)
        self.assertEqual(1, len(junkBranches))
        fooBranchID, fooBranchName = junkBranches[0]
        self.assertEqual('foo-branch', fooBranchName)
    
    def test_createBranch(self):
        storage = DatabaseUserDetailsStorageV2(None)
        branchID = storage._createBranchInteraction(self.cursor, 12, 6, 'foo')
        # Assert branchID now appears in database.  Note that title and summary
        # should be NULL, and author should be set to the owner.
        self.cursor.execute("""
            SELECT owner, product, name, title, summary, author FROM Branch
            WHERE id = %d"""
            % branchID)
        self.assertEqual((12, 6, 'foo', None, None, 12), self.cursor.fetchone())

        # Create a branch with NULL product too:
        branchID = storage._createBranchInteraction(self.cursor, 1, None, 'foo')
        self.cursor.execute("""
            SELECT owner, product, name, title, summary, author FROM Branch
            WHERE id = %d"""
            % branchID)
        self.assertEqual((1, None, 'foo', None, None, 1), 
                         self.cursor.fetchone())
        

class ExtraUserDatabaseStorageTestCase(TestDatabaseSetup):
    # Tests that do some database writes (but makes sure to roll them back)
    def setUp(self):
        TestDatabaseSetup.setUp(self)
        # This is the salt for Mark's password in the sample data.
        self.salt = '\xf4;\x15a\xe4W\x1f'

    def test_authUser(self):
        # Authenticating a user with the right password should work
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction(self.cursor, 'mark@hbd.com',
                                                ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual(goodDict, userDict)

        # Unicode email addresses are handled too.
        self.cursor.execute(
            "INSERT INTO EmailAddress (person, email, status) "
            "VALUES ("
            "  1, "
            "  '%s', " 
            "  2)"  # 2 == Validated
            % (u'm\xe3rk@hbd.com'.encode('utf-8'),)
        )
        userDict = storage._authUserInteraction(self.cursor, u'm\xe3rk@hbd.com',
                                                ssha)
        goodDict = storage._getUserInteraction(self.cursor, u'm\xe3rk@hbd.com')
        self.assertEqual(goodDict, userDict)

    def test_authUserByNickname(self):
        # Authing a user by their nickname should work, just like an email
        # address in test_authUser.
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction(self.cursor, 'sabdfl', ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'sabdfl')
        self.assertEqual(goodDict, userDict)
        
        # And it should be the same as returned by looking them up by email
        # address.
        goodDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual(goodDict, userDict)

    def test_authUserByNicknameNoEmailAddr(self):
        # Just like test_authUserByNickname, but for a user with no email
        # address.  The result should be the same.
        self.cursor.execute(
            "DELETE FROM EmailAddress WHERE person = 1;"
        )
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        userDict = storage._authUserInteraction(self.cursor, 'sabdfl', ssha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'sabdfl')
        self.assertEqual(goodDict, userDict)

    def test_authUserBadPassword(self):
        # Authing a real user with the wrong password should return {}
        storage = DatabaseUserDetailsStorage(None)
        ssha = SSHADigestEncryptor().encrypt('wrong', self.salt)
        userDict = storage._authUserInteraction(self.cursor, 'mark@hbd.com',
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
        self.assertEqual('TestyTheTestUser', userDict['wikiname'])

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
        ssha = SSHADigestEncryptor().encrypt('test', self.salt)
        newSsha = SSHADigestEncryptor().encrypt('testing123')
        userDict = storage._changePasswordInteraction(self.cursor,
                                                      'mark@hbd.com', ssha,
                                                      newSsha)
        self.assertNotEqual({}, userDict)

        # In fact, it should return the same dict as getUser
        goodDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual(goodDict, userDict)

        # And we should be able to authenticate with the new password...
        authDict = storage._authUserInteraction(self.cursor, 'mark@hbd.com',
                                                newSsha)
        self.assertEqual(goodDict, authDict)

        # ...but not the old
        authDict = storage._authUserInteraction(self.cursor, 'mark@hbd.com',
                                                ssha)
        self.assertEqual({}, authDict)

    def test_changePasswordFailure(self):
        storage = DatabaseUserDetailsStorage(None)
        # Changing a password without giving the right current pw should fail
        # (i.e. return {})
        ssha = SSHADigestEncryptor().encrypt('WRONG', self.salt)
        newSsha = SSHADigestEncryptor().encrypt('testing123')
        userDict = storage._changePasswordInteraction(self.cursor,
                                                      'mark@hbd.com', ssha,
                                                      newSsha)
        self.assertEqual({}, userDict)

    def test_getSSHKeys(self):
        # FIXME: there should probably be some SSH keys in the sample data,
        #        so that this test wouldn't need to add some.

        # Add test SSH keys
        self.cursor.execute(
            "INSERT INTO SSHKey (person, keytype, keytext, comment) "
            "VALUES ("
            "  1, "
            "  %d,"
            "  'garbage123',"
            "  'mark@hbd.com')"
            % (dbschema.SSHKeyType.DSA.value, )
        )

        # Add test push mirror access
        self.cursor.execute(
            "INSERT INTO PushMirrorAccess (name, person) "
            "VALUES ("
            "  'marks-archive@example.com',"
            "  1) "
        )

        # Fred's SSH key should have access to freds-archive@example.com
        storage = DatabaseUserDetailsStorage(None)
        keys = storage._getSSHKeysInteraction(self.cursor,
                                              'marks-archive@example.com')
        self.assertEqual([('DSA', 'garbage123')], keys)

        # Fred's SSH key should also have access to an archive with his email
        # address
        keys = storage._getSSHKeysInteraction(self.cursor, 'mark@hbd.com')
        self.assertEqual([('DSA', 'garbage123')], keys)

        # Fred's SSH key should also have access to an archive whose name
        # starts with his email address + '--'.
        keys = storage._getSSHKeysInteraction(self.cursor,
                                              'mark@hbd.com--2005')
        self.assertEqual([('DSA', 'garbage123')], keys)

        # No-one should have access to wilma@hbd.com
        keys = storage._getSSHKeysInteraction(self.cursor, 'wilma@hbd.com')
        self.assertEqual([], keys)

        # Mark should not have access to wilma@hbd.com--2005, even if he has the
        # email address wilma@hbd.com--2005.mark.is.a.hacker.com
        self.cursor.execute(
            "INSERT INTO EmailAddress (person, email, status) "
            "VALUES ("
            "  1, "
            "  'wilma@hbd.com--2005.mark.is.a.hacker.com',"
            "  2)"  # 2 == Validated
        )
        keys = storage._getSSHKeysInteraction(
            self.cursor, 'wilma@mark@hbd.com--2005.mark.is.a.hacker.com'
        )
        self.assertEqual([], keys)
        keys = storage._getSSHKeysInteraction(
            self.cursor, 'wilma@mark@hbd.com--2005.mark.is.a.hacker.com--2005'
        )
        self.assertEqual([], keys)

        # Fred should not have access to archives named after an unvalidated
        # email address of his
        self.cursor.execute(
            "INSERT INTO EmailAddress (person, email, status) "
            "VALUES ("
            "  1, "
            "  'mark@hotmail',"
            "  1)"  # 1 == New (unvalidated)
        )
        keys = storage._getSSHKeysInteraction(self.cursor, 'mark@hotmail')
        self.assertEqual([], keys)

    def test_getUserNoWikiname(self):
        # Ensure that the authserver copes gracefully with users with:
        #    a) no wikinames at all
        #    b) no wikiname for http://www.ubuntulinux.com/wiki/
        # (even though in the long run we want to make sure these situations can
        # never happen, until then the authserver should be robust).
        
        # First, make sure that the sample user has no wikiname.
        self.cursor.execute("""
            DELETE FROM WikiName
            WHERE id = (SELECT id FROM Person
                        WHERE displayname = 'Sample Person')
            """)

        # Get the user dict for Sample Person (test@canonical.com).
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction(self.cursor, 
                                               'test@canonical.com')

        # The user dict has results, even though the wikiname is empty
        self.assertNotEqual({}, userDict)
        self.assertEqual('', userDict['wikiname'])
        self.assertEqual(12, userDict['id'])

        # Now lets add a wikiname, but for a different wiki.
        self.cursor.execute(
            "INSERT INTO WikiName (person, wiki, wikiname) "
            "VALUES (12, 'http://foowiki/', 'SamplePerson')"
        )

        # The authserver should return exactly the same results.
        userDict2 = storage._getUserInteraction(self.cursor, 
                                                'test@canonical.com')
        self.assertEqual(userDict, userDict2)
        
    def testTeamDict(self):
        # The user dict from a V2 storage should include a 'teams' element with
        # a list of team dicts, one for each team the user is in, including
        # the user.

        # Get a user dict
        storage = DatabaseUserDetailsStorageV2(None)
        userDict = storage._getUserInteraction(self.cursor, 'mark@hbd.com')

        # Sort the teams by id, they may be returned in any order.
        teams = sorted(userDict['teams'], key=lambda teamDict: teamDict['id'])

        # Mark should be in his own team, Ubuntu Team, Launchpad Administrators
        # and testing Spanish team.
        self.assertEqual(
            [{'displayname': u'Mark Shuttleworth', 'id': 1, 'name': u'sabdfl'},
             {'displayname': u'Ubuntu Team', 'id': 17, 'name': u'ubuntu-team'},
             {'displayname': u'Launchpad Administrators',
              'id': 25, 'name': u'admins'},
             {'displayname': u'testing Spanish team',
              'id': 53, 'name': u'testing-spanish-team'},
             {'displayname': u'Mirror Administrators', 
              'id': 59, 'name': u'mirror-admins'},
             {'displayname': u'Registry Administrators', 'id': 60,
              'name': u'registry'},
            ], teams)

        # The dict returned by authUser should be identical.
        userDict2 = storage._authUserInteraction(self.cursor, 
                                                 'mark@hbd.com', 'test')
        self.assertEqual(userDict, userDict2)

    def test_authUserUnconfirmedEmail(self):
        # Unconfirmed email addresses cannot be used to log in.
        storage = DatabaseUserDetailsStorageV2(None)
        ssha = SSHADigestEncryptor().encrypt('supersecret!')
        self.cursor.execute('''
            UPDATE Person SET password = '%s'
            WHERE id = (SELECT person FROM EmailAddress 
                        WHERE email = 'justdave@bugzilla.org')'''
            % (ssha,))
        userDict = storage._authUserInteraction(
            self.cursor, 'justdave@bugzilla.org', 'supersecret!')
        self.assertEqual({}, userDict)


class BranchDetailsDatabaseStorageTestCase(TestDatabaseSetup):
    def test_verifyInterface(self):
        self.failUnless(verifyObject(IBranchDetailsStorage,
                                     DatabaseBranchDetailsStorage(None)))

    def test_getBranchPullQueue(self):
        storage = DatabaseBranchDetailsStorage(None)
        results = storage._getBranchPullQueueInteraction(self.cursor)
        self.assertEqual(len(results), len(expected_branches_to_pull))
        for i, (branch_id, pull_url) in enumerate(sorted(results)):
            self.assertEqual(expected_branches_to_pull[i],
                             (branch_id, pull_url))

    def test_startMirroring(self):
        # verify that the last mirror time is None before hand.
        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertEqual(row[0], None)
        self.assertEqual(row[1], None)

        storage = DatabaseBranchDetailsStorage(None)
        success = storage._startMirroringInteraction(self.cursor, 1)
        self.assertEqual(success, True)

        # verify that last_mirror_attempt is set
        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[1], None)

    def test_startMirroring_invalid_branch(self):
        # verify that no branch exists with id == -1
        self.cursor.execute("""
            SELECT id FROM branch WHERE id = -1""")
        self.assertEqual(self.cursor.rowcount, 0)
        
        storage = DatabaseBranchDetailsStorage(None)
        success = storage._startMirroringInteraction(self.cursor, -11)
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

        storage = DatabaseBranchDetailsStorage(None)
        success = storage._startMirroringInteraction(self.cursor, 1)
        self.assertEqual(success, True)
        success = storage._mirrorFailedInteraction(self.cursor, 1, "failed")
        self.assertEqual(success, True)

        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures,
                mirror_status_message
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
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

        storage = DatabaseBranchDetailsStorage(None)
        success = storage._startMirroringInteraction(self.cursor, 1)
        self.assertEqual(success, True)
        success = storage._mirrorCompleteInteraction(self.cursor, 1)
        self.assertEqual(success, True)

        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[0], row[1])
        self.assertEqual(row[2], 0)

    def test_mirrorComplete_resets_failure_count(self):
        # this increments the failure count ...
        self.test_mirrorFailed()

        storage = DatabaseBranchDetailsStorage(None)
        success = storage._startMirroringInteraction(self.cursor, 1)
        self.assertEqual(success, True)
        success = storage._mirrorCompleteInteraction(self.cursor, 1)
        self.assertEqual(success, True)

        self.cursor.execute("""
            SELECT last_mirror_attempt, last_mirrored, mirror_failures
                FROM branch WHERE id = 1""")
        row = self.cursor.fetchone()
        self.assertNotEqual(row[0], None)
        self.assertEqual(row[0], row[1])
        self.assertEqual(row[2], 0)

    def test_always_try_mirroring_hosted_branches(self):
        # Return all hosted branches every run, regardless of
        # last_mirror_attempt.
        storage = DatabaseBranchDetailsStorage(None)
        results = storage._getBranchPullQueueInteraction(self.cursor)

        # Branch 25 is a hosted branch.
        branch_ids = [branch_id for branch_id, pull_url in results]
        self.failUnless(25 in branch_ids)
        
        # Mark 25 as recently mirrored.
        storage._startMirroringInteraction(self.cursor, 25)
        storage._mirrorCompleteInteraction(self.cursor, 25)
        
        # 25 should still be in the pull list
        results = storage._getBranchPullQueueInteraction(self.cursor)
        branch_ids = [branch_id for branch_id, pull_url in results]
        self.failUnless(25 in branch_ids,
                        "hosted branch no longer in pull list")

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

