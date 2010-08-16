# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'FileDownloadClient',
    'FileUploadClient',
    'get_libraryfilealias_download_path',
    'LibrarianClient',
    'RestrictedLibrarianClient',
    'url_path_quote',
    ]


import hashlib
import re
import socket
import time
import threading
import urllib
import urllib2

from select import select
from socket import SOCK_STREAM, AF_INET
from urlparse import urljoin

from storm.store import Store
from zope.interface import implements

from canonical.config import config, dbconfig
from canonical.database.sqlbase import cursor
from canonical.librarian.interfaces import (
    DownloadFailed, ILibrarianClient, IRestrictedLibrarianClient,
    LIBRARIAN_SERVER_DEFAULT_TIMEOUT, LibrarianServerError, UploadFailed)


def url_path_quote(filename):
    """Quote `filename` for use in a URL."""
    # XXX RobertCollins 2004-09-21: Perhaps filenames with / in them
    # should be disallowed?
    return urllib.quote(filename).replace('/', '%2F')


def get_libraryfilealias_download_path(aliasID, filename):
    """Download path for a given `LibraryFileAlias` id and filename."""
    return '/%d/%s' % (int(aliasID), url_path_quote(filename))


class FileUploadClient:
    """Simple blocking client for uploading to the librarian."""

    def __init__(self):
        # This class is registered as a utility, which means an instance of
        # it will be shared between threads. The easiest way of making this
        # class thread safe is by storing all state in a thread local.
        self.state = threading.local()

    def _connect(self):
        """Connect this client.

        The host and port default to what is specified in the configuration
        """
        try:
            self.state.s = socket.socket(AF_INET, SOCK_STREAM)
            self.state.s.connect((self.upload_host, self.upload_port))
            self.state.f = self.state.s.makefile('w+', 0)
        except socket.error, x:
            raise UploadFailed(
                '[%s:%s]: %s' % (self.upload_host, self.upload_port, x))

    def _close(self):
        """Close connection"""
        del self.state.s
        del self.state.f

    def _checkError(self):
        if select([self.state.s], [], [], 0)[0]:
            response = self.state.f.readline().strip()
            raise UploadFailed, 'Server said: ' + response

    def _sendLine(self, line):
        self.state.f.write(line + '\r\n')
        self._checkError()

    def _sendHeader(self, name, value):
        self._sendLine('%s: %s' % (name, value))

    def addFile(self, name, size, file, contentType, expires=None,
                debugID=None):
        """Add a file to the librarian.

        :param name: Name to store the file as
        :param size: Size of the file
        :param file: File-like object with the content in it
        :param contentType: mime-type, e.g. text/plain
        :param expires: Expiry time of file. See LibrarianGarbageCollection.
            Set to None to only expire when it is no longer referenced.
        :param debugID: Optional.  If set, causes extra logging for this
            request on the server, which will be marked with the value
            given.
        :returns: aliasID as an integer
        :raises UploadFailed: If the server rejects the upload for some
            reason, is 0.
        """
        if file is None:
            raise TypeError('Bad File Descriptor: %s' % repr(file))
        if size <= 0:
            raise UploadFailed('Invalid length: %d' % size)

        if isinstance(name, unicode):
            name = name.encode('utf-8')

        # Import in this method to avoid a circular import
        from canonical.launchpad.database import LibraryFileContent
        from canonical.launchpad.database import LibraryFileAlias

        self._connect()
        try:
            # Get the name of the database the client is using, so that
            # the server can check that the client is using the same
            # database as the server.
            cur = cursor()
            databaseName = self._getDatabaseName(cur)

            # Generate new content and alias IDs.
            # (we'll create rows with these IDs later, but not yet)
            cur.execute("SELECT nextval('libraryfilecontent_id_seq')")
            contentID = cur.fetchone()[0]
            cur.execute("SELECT nextval('libraryfilealias_id_seq')")
            aliasID = cur.fetchone()[0]

            # Send command
            self._sendLine('STORE %d %s' % (size, name))

            # Send headers
            self._sendHeader('Database-Name', databaseName)
            self._sendHeader('File-Content-ID', contentID)
            self._sendHeader('File-Alias-ID', aliasID)

            if debugID is not None:
                self._sendHeader('Debug-ID', debugID)

            # Send blank line
            self._sendLine('')

            # Prepare to the upload the file
            shaDigester = hashlib.sha1()
            md5Digester = hashlib.md5()
            bytesWritten = 0

            # Read in and upload the file 64kb at a time, by using the two-arg
            # form of iter (see
            # /usr/share/doc/python2.4/html/lib/built-in-funcs.html#l2h-42).
            for chunk in iter(lambda: file.read(1024*64), ''):
                self.state.f.write(chunk)
                bytesWritten += len(chunk)
                shaDigester.update(chunk)
                md5Digester.update(chunk)

            assert bytesWritten == size, (
                'size is %d, but %d were read from the file'
                % (size, bytesWritten))
            self.state.f.flush()

            # Read response
            response = self.state.f.readline().strip()
            if response != '200':
                raise UploadFailed, 'Server said: ' + response

            # Add rows to DB
            content = LibraryFileContent(
                id=contentID, filesize=size,
                sha1=shaDigester.hexdigest(),
                md5=md5Digester.hexdigest())
            LibraryFileAlias(
                id=aliasID, content=content, filename=name.decode('UTF-8'),
                mimetype=contentType, expires=expires,
                restricted=self.restricted)

            Store.of(content).flush()

            assert isinstance(aliasID, (int, long)), \
                    "aliasID %r not an integer" % (aliasID,)
            return aliasID
        finally:
            self._close()

    def _getDatabaseName(self, cur):
        cur.execute("SELECT current_database();")
        databaseName = cur.fetchone()[0]
        return databaseName

    def remoteAddFile(self, name, size, file, contentType, expires=None):
        """See `IFileUploadClient`."""
        if file is None:
            raise TypeError('No data')
        if size <= 0:
            raise UploadFailed('No data')
        if isinstance(name, unicode):
            name = name.encode('utf-8')
        self._connect()
        try:
            # Use dbconfig.rw_main_master directly here because it doesn't
            # make sense to try and use ro_main_master (which might be
            # returned if we use dbconfig.main_master).
            database_name = re.search(
                r"dbname=(\S*)", dbconfig.rw_main_master).group(1)
            self._sendLine('STORE %d %s' % (size, name))
            self._sendHeader('Database-Name', database_name)
            self._sendHeader('Content-Type', str(contentType))
            if expires is not None:
                epoch = time.mktime(expires.utctimetuple())
                self._sendHeader('File-Expires', str(int(epoch)))

            # Send blank line
            self._sendLine('')

            # Prepare to the upload the file
            bytesWritten = 0

            # Read in and upload the file 64kb at a time, by using the two-arg
            # form of iter (see
            # /usr/share/doc/python2.4/html/lib/built-in-funcs.html#l2h-42).
            for chunk in iter(lambda: file.read(1024*64), ''):
                self.state.f.write(chunk)
                bytesWritten += len(chunk)

            assert bytesWritten == size, (
                'size is %d, but %d were read from the file'
                % (size, bytesWritten))
            self.state.f.flush()

            # Read response
            response = self.state.f.readline().strip()
            if not response.startswith('200'):
                raise UploadFailed, 'Server said: ' + response

            status, ids = response.split()
            contentID, aliasID = ids.split('/', 1)

            path = get_libraryfilealias_download_path(aliasID, name)
            return urljoin(self.download_url, path)
        finally:
            self._close()


class _File:
    """A wrapper around a file like object that has security assertions"""

    def __init__(self, file):
        self.file = file

    def read(self, chunksize=None):
        if chunksize is None:
            return self.file.read()
        else:
            return self.file.read(chunksize)

    def close(self):
        return self.file.close()


class FileDownloadClient:
    """A simple client to download files from the librarian"""

    # If anything is using this, it should be exposed as a public method
    # in the interface. Note that there is no need to contact the Librarian
    # to do this if you have a database connection available.
    #
    # def _findByDigest(self, hexdigest):
    #     """Return a list of relative paths to aliases"""
    #     host = config.librarian.download_host
    #     port = config.librarian.download_port
    #     url = ('http://%s:%d/search?digest=%s' % (
    #         host, port, hexdigest)
    #         )
    #     results = urllib2.urlopen(url).read()
    #     lines = results.split('\n')
    #     count, paths = lines[0], lines[1:]
    #     if int(count) != len(paths):
    #         raise DownloadFailed, 'Incomplete response'
    #     return paths

    def _getPathForAlias(self, aliasID):
        """Returns the path inside the librarian to talk about the given
        alias.

        :param aliasID: A unique ID for the alias

        :returns: String path, url-escaped.  Unicode is UTF-8 encoded before
            url-escaping, as described in section 2.2.5 of RFC 2718.
            None if the file has been deleted.

        :raises: DownloadFailed if the alias is invalid
        """
        from canonical.launchpad.database import LibraryFileAlias
        from sqlobject import SQLObjectNotFound
        aliasID = int(aliasID)
        try:
            # Use SQLObjects to maximize caching benefits
            lfa = LibraryFileAlias.get(aliasID)
        except SQLObjectNotFound:
            raise DownloadFailed('Alias %d not found' % aliasID)
        if self.restricted != lfa.restricted:
            raise DownloadFailed(
                'Alias %d cannot be downloaded from this client.' % aliasID)
        if lfa.deleted:
            return None
        return get_libraryfilealias_download_path(aliasID, lfa.filename)

    def getURLForAlias(self, aliasID):
        """Returns the url for talking to the librarian about the given
        alias.

        :param aliasID: A unique ID for the alias

        :returns: String URL, or None if the file has expired and been deleted.
        """
        path = self._getPathForAlias(aliasID)
        if path is None:
            return None
        base = self.download_url
        return urljoin(base, path)

    def _getURLForDownload(self, aliasID):
        """Returns the internal librarian URL for the alias.

        :param aliasID: A unique ID for the alias

        :returns: String URL, or None if the file has expired and been deleted.
        """
        path = self._getPathForAlias(aliasID)
        if path is None:
            return None
        base = self._internal_download_url
        return urljoin(base, path)

    def getFileByAlias(
        self, aliasID, timeout=LIBRARIAN_SERVER_DEFAULT_TIMEOUT):
        """See `IFileDownloadClient`."""
        url = self._getURLForDownload(aliasID)
        if url is None:
            # File has been deleted
            return None
        try_until = time.time() + timeout
        while 1:
            try:
                return _File(urllib2.urlopen(url))
            except urllib2.URLError, error:
                # 404 errors indicate a data inconsistency: more than one
                # attempt to open the file is pointless.
                #
                # Note that URLError is a base class of HTTPError.
                if isinstance(error, urllib2.HTTPError) and error.code == 404:
                    raise LookupError, aliasID
                # HTTPErrors with a 5xx error code ("server problem")
                # are a reason to retry the access again, as well as
                # generic, non-HTTP, URLErrors like "connection refused".
                if (isinstance(error, urllib2.HTTPError)
                    and 500 <= error.code <= 599
                    or isinstance(error, urllib2.URLError) and
                        not isinstance(error, urllib2.HTTPError)):
                    if  time.time() <= try_until:
                        time.sleep(1)
                    else:
                        # There's a test (in
                        # lib/c/l/browser/tests/test_librarian.py) which 
                        # simulates a librarian server error by raising this
                        # exception, so if you change the exception raised
                        # here, make sure you update the test.
                        raise LibrarianServerError(str(error))
                else:
                    raise


class LibrarianClient(FileUploadClient, FileDownloadClient):
    """See `ILibrarianClient`."""
    implements(ILibrarianClient)

    restricted = False

    @property
    def upload_host(self):
        return config.librarian.upload_host

    @property
    def upload_port(self):
        return config.librarian.upload_port

    @property
    def download_url(self):
        return config.librarian.download_url

    @property
    def _internal_download_url(self): # used by _getURLForDownload
        return 'http://%s:%s/' % (config.librarian.download_host,
                                  config.librarian.download_port)



class RestrictedLibrarianClient(LibrarianClient):
    """See `IRestrictedLibrarianClient`."""
    implements(IRestrictedLibrarianClient)

    restricted = True

    @property
    def upload_host(self):
        return config.librarian.restricted_upload_host

    @property
    def upload_port(self):
        return config.librarian.restricted_upload_port

    @property
    def download_url(self):
        return config.librarian.restricted_download_url

    @property
    def _internal_download_url(self): # used by _getURLForDownload
        return 'http://%s:%s/' % (config.librarian.restricted_download_host,
                                  config.librarian.restricted_download_port)
