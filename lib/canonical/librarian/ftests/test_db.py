# Copyright 2004 Canonical Ltd.  All rights reserved.
#

import unittest

from canonical.librarian import db
from canonical.launchpad.ftests.harness import LaunchpadZopelessTestSetup

def sorted(l):
    l = list(l)
    l.sort()
    return l

class DBTestCase(LaunchpadZopelessTestSetup, unittest.TestCase):

    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName)
        LaunchpadZopelessTestSetup.__init__(self)

    def test_lookupByDigest(self):
        # Create library
        library = db.Library()

        # Initially it should be empty
        self.assertEqual([], library.lookupBySHA1('deadbeef'))

        # Add a file, check it is found by lookupBySHA1
        txn = library.makeAddTransaction()
        fileID = library.add('deadbeef', 1234, txn)
        self.assertEqual([fileID], library.lookupBySHA1('deadbeef'))

        # Add a new file with the same digest
        newFileID = library.add('deadbeef', 1234, txn)
        # Check it gets a new ID anyway
        self.assertNotEqual(fileID, newFileID)
        # Check it is found by lookupBySHA1
        self.assertEqual(sorted([fileID, newFileID]),
                sorted(library.lookupBySHA1('deadbeef', txn)))

        aliasID = library.addAlias(fileID, 'file1', 'text/unknown', txn)
        alias = library.getAlias(fileID, 'file1', txn)
        self.assertEqual('file1', alias.filename)
        self.assertEqual('text/unknown', alias.mimetype)
        txn.rollback()
        

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(DBTestCase))
    return suite
