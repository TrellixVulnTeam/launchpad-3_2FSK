# Copyright 2004 Canonical Ltd.  All rights reserved.
#

import unittest

from storm.zope.interfaces import IZStorm
import transaction
from zope.component import getUtility

from canonical.launchpad.database.librarian import LibraryFileContent
from canonical.librarian import db
from canonical.testing import LaunchpadZopelessLayer


class DBTestCase(unittest.TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.layer.switchDbUser('librarian')

    def test_lookupByDigest(self):
        # Create library
        library = db.Library()

        # Initially it should be empty
        self.assertEqual([], library.lookupBySHA1('deadbeef'))

        # Add a file, check it is found by lookupBySHA1
        fileID = library.add('deadbeef', 1234, 'abababab')
        self.assertEqual([fileID], library.lookupBySHA1('deadbeef'))

        # Add a new file with the same digest
        newFileID = library.add('deadbeef', 1234, 'abababab')
        # Check it gets a new ID anyway
        self.assertNotEqual(fileID, newFileID)
        # Check it is found by lookupBySHA1
        self.assertEqual(sorted([fileID, newFileID]),
                         sorted(library.lookupBySHA1('deadbeef')))

        aliasID = library.addAlias(fileID, 'file1', 'text/unknown')
        alias = library.getAlias(aliasID)
        self.assertEqual('file1', alias.filename)
        self.assertEqual('text/unknown', alias.mimetype)


class TestTransactionDecorators(unittest.TestCase):
    """Tests for the transaction decorators used by the librarian."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.layer.switchDbUser('librarian')
        self.store = getUtility(IZStorm).get('main')
        self.content_id = db.Library().add('deadbeef', 1234, 'abababab')
        self.file_content = self._getTestFileContent()
        transaction.commit()

    def _getTestFileContent(self):
        """Return the file content object that created."""
        return self.store.find(LibraryFileContent, id=self.content_id).one()

    def test_read_transaction_reset_store(self):
        """Make sure that the store is reset after the transaction."""
        @db.read_transaction
        def no_op():
            pass
        no_op()
        self.failIf(
            self.file_content is self._getTestFileContent(),
            "Store wasn't reset properly.")

    def test_write_transaction_reset_store(self):
        """Make sure that the store is reset after the transaction."""
        @db.write_transaction
        def no_op():
            pass
        no_op()
        self.failIf(
            self.file_content is self._getTestFileContent(),
            "Store wasn't reset properly.")

    def test_write_transaction_reset_store_with_raise(self):
        """Make sure that the store is reset after the transaction."""
        @db.write_transaction
        def no_op():
            raise RuntimeError('an error occured')
        self.assertRaises(RuntimeError, no_op)
        self.failIf(
            self.file_content is self._getTestFileContent(),
            "Store wasn't reset properly.")

    def test_writing_transaction_reset_store_on_commit_failure(self):
        """The store should be reset even if committing the transaction fails.
        """
        class TransactionAborter:
            """Make the next commit() fails."""
            def newTransaction(self, txn):
                pass

            def beforeCompletion(self, txn):
                raise RuntimeError('the commit will fail')
        aborter = TransactionAborter()
        transaction.manager.registerSynch(aborter)
        try:
            @db.write_transaction
            def no_op():
                pass
            self.assertRaises(RuntimeError, no_op)
            self.failIf(
                self.file_content is self._getTestFileContent(),
                "Store wasn't reset properly.")
        finally:
            transaction.manager.unregisterSynch(aborter)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
