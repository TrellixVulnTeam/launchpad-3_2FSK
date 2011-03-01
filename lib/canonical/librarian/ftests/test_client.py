# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from cStringIO import StringIO
import textwrap
import unittest
from urllib2 import URLError, HTTPError

import transaction

from canonical.testing.layers import DatabaseLayer, LaunchpadFunctionalLayer
from canonical.config import config
from canonical.database.sqlbase import block_implicit_flushes
from canonical.launchpad.interfaces.lpstorm import ISlaveStore
from canonical.launchpad.webapp.dbpolicy import SlaveDatabasePolicy
from canonical.librarian import client as client_module
from canonical.librarian.client import (
    LibrarianClient, LibrarianServerError, RestrictedLibrarianClient)
from canonical.librarian.interfaces import UploadFailed
from canonical.launchpad.database.librarian import LibraryFileAlias


class InstrumentedLibrarianClient(LibrarianClient):
    sentDatabaseName = False
    def _sendHeader(self, name, value):
        if name == 'Database-Name':
            self.sentDatabaseName = True
        return LibrarianClient._sendHeader(self, name, value)

    called_getURLForDownload = False
    def _getURLForDownload(self, aliasID):
        self.called_getURLForDownload = True
        return LibrarianClient._getURLForDownload(self, aliasID)


def make_mock_file(error, max_raise):
    """Return a surrogate for client._File.

    The surrogate function raises error when called for the first
    max_raise times.
    """

    file_status = {
        'error': error,
        'max_raise': max_raise,
        'num_calls': 0,
        }

    def mock_file(url_file, url):
        if file_status['num_calls'] < file_status['max_raise']:
            file_status['num_calls'] += 1
            raise file_status['error']
        return 'This is a fake file object'

    return mock_file


class LibrarianClientTestCase(unittest.TestCase):
    layer = LaunchpadFunctionalLayer

    def test_addFileSendsDatabaseName(self):
        # addFile should send the Database-Name header.
        client = InstrumentedLibrarianClient()
        id1 = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        self.failUnless(client.sentDatabaseName,
            "Database-Name header not sent by addFile")

    def test_remoteAddFileDoesntSendDatabaseName(self):
        # remoteAddFile should send the Database-Name header as well.
        client = InstrumentedLibrarianClient()
        # Because the remoteAddFile call commits to the database in a
        # different process, we need to explicitly tell the DatabaseLayer to
        # fully tear down and set up the database.
        DatabaseLayer.force_dirty_database()
        id1 = client.remoteAddFile('sample.txt', 6, StringIO('sample'),
                                   'text/plain')
        self.failUnless(client.sentDatabaseName,
            "Database-Name header not sent by remoteAddFile")

    def test_clientWrongDatabase(self):
        # If the client is using the wrong database, the server should refuse
        # the upload, causing LibrarianClient to raise UploadFailed.
        client = LibrarianClient()
        # Force the client to mis-report its database
        client._getDatabaseName = lambda cur: 'wrong_database'
        try:
            client.addFile('sample.txt', 6, StringIO('sample'), 'text/plain')
        except UploadFailed, e:
            msg = e.args[0]
            self.failUnless(
                msg.startswith('Server said: 400 Wrong database'),
                'Unexpected UploadFailed error: ' + msg)
        else:
            self.fail("UploadFailed not raised")

    def test_addFile_uses_master(self):
        # addFile is a write operation, so it should always use the
        # master store, even if the slave is the default. Close the
        # slave store and try to add a file, verifying that the master
        # is used.
        client = LibrarianClient()
        ISlaveStore(LibraryFileAlias).close()
        with SlaveDatabasePolicy():
            alias_id = client.addFile(
                'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        f = client.getFileByAlias(alias_id)
        self.assertEqual(f.read(), 'sample')

    def test__getURLForDownload(self):
        # This protected method is used by getFileByAlias. It is supposed to
        # use the internal host and port rather than the external, proxied
        # host and port. This is to provide relief for our own issues with the
        # problems reported in bug 317482.
        #
        # (Set up:)
        client = LibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        config.push(
            'test config',
            textwrap.dedent('''\
                [librarian]
                download_host: example.org
                download_port: 1234
                '''))
        try:
            # (Test:)
            # The LibrarianClient should use the download_host and
            # download_port.
            expected_host = 'http://example.org:1234/'
            download_url = client._getURLForDownload(alias_id)
            self.failUnless(download_url.startswith(expected_host),
                            'expected %s to start with %s' % (download_url,
                                                              expected_host))
            # If the alias has been deleted, _getURLForDownload returns None.
            lfa = LibraryFileAlias.get(alias_id)
            lfa.content = None
            call = block_implicit_flushes( # Prevent a ProgrammingError
                LibrarianClient._getURLForDownload)
            self.assertEqual(call(client, alias_id), None)
        finally:
            # (Tear down:)
            config.pop('test config')

    def test_restricted_getURLForDownload(self):
        # The RestrictedLibrarianClient should use the
        # restricted_download_host and restricted_download_port, but is
        # otherwise identical to the behavior of the LibrarianClient discussed
        # and demonstrated above.
        #
        # (Set up:)
        client = RestrictedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        config.push(
            'test config',
            textwrap.dedent('''\
                [librarian]
                restricted_download_host: example.com
                restricted_download_port: 5678
                '''))
        try:
            # (Test:)
            # The LibrarianClient should use the download_host and
            # download_port.
            expected_host = 'http://example.com:5678/'
            download_url = client._getURLForDownload(alias_id)
            self.failUnless(download_url.startswith(expected_host),
                            'expected %s to start with %s' % (download_url,
                                                              expected_host))
            # If the alias has been deleted, _getURLForDownload returns None.
            lfa = LibraryFileAlias.get(alias_id)
            lfa.content = None
            call = block_implicit_flushes( # Prevent a ProgrammingError
                RestrictedLibrarianClient._getURLForDownload)
            self.assertEqual(call(client, alias_id), None)
        finally:
            # (Tear down:)
            config.pop('test config')

    def test_getFileByAlias(self):
        # This method should use _getURLForDownload to download the file.
        # We use the InstrumentedLibrarianClient to show that it is consulted.
        #
        # (Set up:)
        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit() # Make sure the file is in the "remote" database
        self.failIf(client.called_getURLForDownload)
        # (Test:)
        f = client.getFileByAlias(alias_id)
        self.assertEqual(f.read(), 'sample')
        self.failUnless(client.called_getURLForDownload)

    def test_getFileByAliasLookupError(self):
        # The Librarian server can return a 404 HTTPError;
        # LibrarienClient.getFileByAlias() returns a LookupError in
        # this case.
        _File = client_module._File
        client_module._File = make_mock_file(
            HTTPError('http://fake.url/', 404, 'Forced error', None, None), 1)

        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        self.assertRaises(LookupError, client.getFileByAlias, alias_id)

        client_module._File = _File

    def test_getFileByAliasLibrarianLongServerError(self):
        # The Librarian server can return a 500 HTTPError.
        # LibrarienClient.getFileByAlias() returns a LibrarianServerError
        # if the server returns this error for a longer time than given
        # by the parameter timeout.
        _File = client_module._File

        client_module._File = make_mock_file(
            HTTPError('http://fake.url/', 500, 'Forced error', None, None), 2)
        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        self.assertRaises(
            LibrarianServerError, client.getFileByAlias, alias_id, 1)

        client_module._File = make_mock_file(
            URLError('Connection refused'), 2)
        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        self.assertRaises(
            LibrarianServerError, client.getFileByAlias, alias_id, 1)

        client_module._File = _File

    def test_getFileByAliasLibrarianShortServerError(self):
        # The Librarian server can return a 500 HTTPError;
        # LibrarienClient.getFileByAlias() returns a LibrarianServerError
        # in this case.
        _File = client_module._File

        client_module._File = make_mock_file(
            HTTPError('http://fake.url/', 500, 'Forced error', None, None), 1)
        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        self.assertEqual(
            client.getFileByAlias(alias_id), 'This is a fake file object', 3)

        client_module._File = make_mock_file(
            URLError('Connection refused'), 1)
        client = InstrumentedLibrarianClient()
        alias_id = client.addFile(
            'sample.txt', 6, StringIO('sample'), 'text/plain')
        transaction.commit()
        self.assertEqual(
            client.getFileByAlias(alias_id), 'This is a fake file object', 3)

        client_module._File = _File


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
