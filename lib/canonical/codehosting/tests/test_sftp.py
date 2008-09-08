# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for the transport-backed SFTP server implementation."""

import os
import unittest
import shutil

from bzrlib.tests import TestCaseInTempDir
from bzrlib import errors as bzr_errors
from bzrlib import urlutils

from twisted.conch.ssh import filetransfer
from twisted.conch.interfaces import ISFTPServer
from twisted.internet import defer
from twisted.python import failure
from twisted.python.util import mergeFunctionMetadata
from twisted.trial.unittest import TestCase as TrialTestCase

from canonical.config import config
from canonical.codehosting.sftp import (
    FatLocalTransport, TransportSFTPServer, FileIsADirectory)
from canonical.codehosting.sshserver import LaunchpadAvatar
from canonical.codehosting.tests.helpers import FakeLaunchpad
from canonical.codehosting.transport import BlockingProxy
from canonical.launchpad.testing import LaunchpadObjectFactory
from canonical.testing.layers import TwistedLayer


class AsyncTransport:
    """Make a transport that returns Deferreds.

    While this could wrap any object and make its methods return Deferreds, we
    expect this to be wrapping FatLocalTransport (and so making a Twisted
    Transport, as defined in canonical.codehosting.sftp's docstring).
    """

    def __init__(self, transport):
        self._transport = transport

    def __getattr__(self, name):
        maybe_method = getattr(self._transport, name)
        if not callable(maybe_method):
            return maybe_method
        def defer_it(*args, **kwargs):
            return defer.maybeDeferred(maybe_method, *args, **kwargs)
        return mergeFunctionMetadata(maybe_method, defer_it)


class TestFatLocalTransport(TestCaseInTempDir):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.transport = FatLocalTransport(urlutils.local_path_to_url('.'))

    def test_writeChunk(self):
        # writeChunk writes a chunk of data to a file at a given offset.
        filename = 'foo'
        self.transport.put_bytes(filename, 'content')
        self.transport.writeChunk(filename, 1, 'razy')
        self.assertEqual('crazynt', self.transport.get_bytes(filename))

    def test_localRealPath(self):
        # localRealPath takes a URL-encoded relpath and returns a URL-encoded
        # absolute path.
        filename = '~foo'
        escaped_filename = urlutils.escape(filename)
        self.assertNotEqual(filename, escaped_filename)
        realpath = self.transport.local_realPath(escaped_filename)
        self.assertEqual(
            urlutils.escape(os.path.abspath(filename)), realpath)


class TestSFTPAdapter(TrialTestCase):

    layer = TwistedLayer

    def makeLaunchpadAvatar(self):
        fake_launchpad = FakeLaunchpad()
        user_dict = fake_launchpad.getUser(1)
        branchfs_proxy = BlockingProxy(fake_launchpad)
        return LaunchpadAvatar(user_dict, branchfs_proxy)

    def test_canAdaptToSFTPServer(self):
        server = ISFTPServer(self.makeLaunchpadAvatar())
        self.assertIsInstance(server, TransportSFTPServer)
        deferred = server.makeDirectory(
            '~testuser/firefox/baz/.bzr', {'permissions': 0777})
        self.addCleanup(shutil.rmtree, config.codehosting.branches_root)
        return deferred


class SFTPTestMixin:
    """Mixin used to check getAttrs."""

    def setUp(self):
        self._factory = LaunchpadObjectFactory()

    def checkAttrs(self, attrs, stat_value):
        """Check that an attrs dictionary matches a stat result."""
        self.assertEqual(stat_value.st_size, attrs['size'])
        self.assertEqual(os.getuid(), attrs['uid'])
        self.assertEqual(os.getgid(), attrs['gid'])
        self.assertEqual(stat_value.st_mode, attrs['permissions'])
        self.assertEqual(int(stat_value.st_mtime), attrs['mtime'])
        self.assertEqual(int(stat_value.st_atime), attrs['atime'])

    def getPathSegment(self):
        """Return a unique path segment for testing.

        This returns a path segment such that 'path != unescape(path)'. This
        exercises the interface between the sftp server and the Bazaar
        transport, which expects escaped URL segments.
        """
        return self._factory.getUniqueString('%41%42%43-')


class TestSFTPFile(TrialTestCase, TestCaseInTempDir, SFTPTestMixin):
    """Tests for `TransportSFTPServer` and `TransportSFTPFile`."""

    layer = TwistedLayer

    def setUp(self):
        TrialTestCase.setUp(self)
        TestCaseInTempDir.setUp(self)
        SFTPTestMixin.setUp(self)
        transport = AsyncTransport(
            FatLocalTransport(urlutils.local_path_to_url('.')))
        self._sftp_server = TransportSFTPServer(transport)

    def assertSFTPError(self, sftp_code, function, *args, **kwargs):
        """Assert that calling functions fails with `sftp_code`."""
        deferred = defer.maybeDeferred(function, *args, **kwargs)
        deferred = self.assertFailure(deferred, filetransfer.SFTPError)
        def check_sftp_code(exception):
            self.assertEqual(sftp_code, exception.code)
            return exception
        return deferred.addCallback(check_sftp_code)

    def openFile(self, path, flags, attrs):
        return self._sftp_server.openFile(path, flags, attrs)

    def test_openFileInNonexistingDirectory(self):
        # openFile fails with a no such file error if we try to open a file in
        # a directory that doesn't exist. The flags passed to openFile() do
        # not have any effect.
        return self.assertSFTPError(
            filetransfer.FX_NO_SUCH_FILE,
            self.openFile,
            '%s/%s' % (self.getPathSegment(), self.getPathSegment()), 0, {})

    def test_openFileInNonDirectory(self):
        # openFile fails with a no such file error if we try to open a file
        # that has another file as one of its "parents". The flags passed to
        # openFile() do not have any effect.
        nondirectory = self.getPathSegment()
        self.build_tree_contents([(nondirectory, 'content')])
        return self.assertSFTPError(
            filetransfer.FX_NO_SUCH_FILE,
            self.openFile,
            '%s/%s' % (nondirectory, self.getPathSegment()), 0, {})

    def test_createEmptyFile(self):
        # Opening a file with create flags and then closing it will create a
        # new, empty file.
        filename = self.getPathSegment()
        deferred = self.openFile(filename, filetransfer.FXF_CREAT, {})
        return deferred.addCallback(
            self._test_createEmptyFile_callback, filename)

    def _test_createEmptyFile_callback(self, handle, filename):
        deferred = handle.close()
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('', filename))

    def test_createFileWithData(self):
        # writeChunk writes data to the file.
        filename = self.getPathSegment()
        deferred = self.openFile(
            filename, filetransfer.FXF_CREAT | filetransfer.FXF_WRITE, {})
        return deferred.addCallback(
            self._test_createFileWithData_callback, filename)

    def _test_createFileWithData_callback(self, handle, filename):
        deferred = handle.writeChunk(0, 'bar')
        deferred.addCallback(lambda ignored: handle.close())
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('bar', filename))

    def test_writeChunkToFile(self):
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'contents')])
        deferred = self.openFile(filename, filetransfer.FXF_WRITE, {})
        return deferred.addCallback(
            self._test_writeChunkToFile_callback, filename)

    def _test_writeChunkToFile_callback(self, handle, filename):
        deferred = handle.writeChunk(1, 'qux')
        deferred.addCallback(lambda ignored: handle.close())
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('cquxents', filename))

    def test_writeTwoChunks(self):
        # We can write one chunk after another.
        filename = self.getPathSegment()
        deferred = self.openFile(
            filename, filetransfer.FXF_WRITE | filetransfer.FXF_TRUNC, {})
        def write_chunks(handle):
            deferred = handle.writeChunk(1, 'a')
            deferred.addCallback(lambda ignored: handle.writeChunk(2, 'a'))
            deferred.addCallback(lambda ignored: handle.close())
        deferred.addCallback(write_chunks)
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual(chr(0) + 'aa', filename))

    def test_writeChunkToNonexistentFile(self):
        # Writing a chunk of data to a non-existent file creates the file even
        # if the create flag is not set. NOTE: This behaviour is unspecified
        # in the SFTP drafts at
        # http://tools.ietf.org/wg/secsh/draft-ietf-secsh-filexfer/
        filename = self.getPathSegment()
        deferred = self.openFile(filename, filetransfer.FXF_WRITE, {})
        return deferred.addCallback(
            self._test_writeChunkToNonexistentFile_callback, filename)

    def _test_writeChunkToNonexistentFile_callback(self, handle, filename):
        deferred = handle.writeChunk(1, 'qux')
        deferred.addCallback(lambda ignored: handle.close())
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual(chr(0) + 'qux', filename))

    def test_writeToReadOpenedFile(self):
        # writeChunk raises an error if we try to write to a file that has
        # been opened only for reading.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, filetransfer.FXF_READ, {})
        return deferred.addCallback(
            self._test_writeToReadOpenedFile_callback)

    def _test_writeToReadOpenedFile_callback(self, handle):
        return self.assertSFTPError(
            filetransfer.FX_PERMISSION_DENIED,
            handle.writeChunk, 0, 'new content')

    def test_overwriteFile(self):
        # writeChunk overwrites a file if write, create and trunk flags are
        # set.
        self.build_tree_contents([('foo', 'contents')])
        deferred = self.openFile(
            'foo', filetransfer.FXF_CREAT | filetransfer.FXF_TRUNC |
            filetransfer.FXF_WRITE, {})
        return deferred.addCallback(self._test_overwriteFile_callback)

    def _test_overwriteFile_callback(self, handle):
        deferred = handle.writeChunk(0, 'bar')
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('bar', 'foo'))

    def test_writeToAppendingFileIgnoresOffset(self):
        # If a file is opened with the 'append' flag, writeChunk ignores its
        # offset parameter.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, filetransfer.FXF_APPEND, {})
        return deferred.addCallback(
            self._test_writeToAppendingFileIgnoresOffset_cb, filename)

    def _test_writeToAppendingFileIgnoresOffset_cb(self, handle, filename):
        deferred = handle.writeChunk(0, 'baz')
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('barbaz', filename))

    def test_openAndCloseExistingFileLeavesUnchanged(self):
        # If we open a file with the 'create' flag and without the 'truncate'
        # flag, the file remains unchanged.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, filetransfer.FXF_CREAT, {})
        return deferred.addCallback(
            self._test_openAndCloseExistingFileUnchanged_cb, filename)

    def _test_openAndCloseExistingFileUnchanged_cb(self, handle, filename):
        deferred = handle.close()
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('bar', filename))

    def test_openAndCloseExistingFileTruncation(self):
        # If we open a file with the 'create' flag and the 'truncate' flag,
        # the file is reset to empty.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(
            filename, filetransfer.FXF_TRUNC | filetransfer.FXF_CREAT, {})
        return deferred.addCallback(
            self._test_openAndCloseExistingFileTruncation_cb, filename)

    def _test_openAndCloseExistingFileTruncation_cb(self, handle, filename):
        deferred = handle.close()
        return deferred.addCallback(
            lambda ignored: self.assertFileEqual('', filename))

    def test_writeChunkOnDirectory(self):
        # Errors in writeChunk are translated to SFTPErrors.
        directory = self.getPathSegment()
        os.mkdir(directory)
        deferred = self.openFile(directory, filetransfer.FXF_WRITE, {})
        deferred.addCallback(lambda handle: handle.writeChunk(0, 'bar'))
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_readChunk(self):
        # readChunk reads a chunk of data from the file.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.readChunk(1, 2))
        return deferred.addCallback(self.assertEqual, 'ar')

    def test_readChunkPastEndOfFile(self):
        # readChunk returns the rest of the file if it is asked to read past
        # the end of the file.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.readChunk(2, 10))
        return deferred.addCallback(self.assertEqual, 'r')

    def test_readChunkEOF(self):
        # readChunk returns the empty string if it encounters end-of-file
        # before reading any data.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.readChunk(3, 10))
        return deferred.addCallback(self.assertEqual, '')

    def test_readChunkError(self):
        # Errors in readChunk are translated to SFTPErrors.
        filename = self.getPathSegment()
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.readChunk(1, 2))
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_setAttrs(self):
        # setAttrs on TransportSFTPFile does nothing.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.openFile(filename, 0, {})
        return deferred.addCallback(lambda handle: handle.setAttrs({}))

    def test_getAttrs(self):
        # getAttrs on TransportSFTPFile returns a dictionary consistent
        # with the results of os.stat.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        stat_value = os.stat(filename)
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.getAttrs())
        return deferred.addCallback(self.checkAttrs, stat_value)

    def test_getAttrsError(self):
        # Errors in getAttrs on TransportSFTPFile are translated into
        # SFTPErrors.
        filename = self.getPathSegment()
        deferred = self.openFile(filename, 0, {})
        deferred.addCallback(lambda handle: handle.getAttrs())
        return self.assertFailure(deferred, filetransfer.SFTPError)


class TestSFTPServer(TrialTestCase, TestCaseInTempDir, SFTPTestMixin):
    """Tests for `TransportSFTPServer` and `TransportSFTPFile`."""

    layer = TwistedLayer

    def setUp(self):
        TrialTestCase.setUp(self)
        TestCaseInTempDir.setUp(self)
        SFTPTestMixin.setUp(self)
        transport = AsyncTransport(
            FatLocalTransport(urlutils.local_path_to_url('.')))
        self.sftp_server = TransportSFTPServer(transport)

    def test_serverSetAttrs(self):
        # setAttrs on the TransportSFTPServer doesn't do anything either.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        self.sftp_server.setAttrs(filename, {})

    def test_serverGetAttrs(self):
        # getAttrs on the TransportSFTPServer also returns a dictionary
        # consistent with the results of os.stat.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        stat_value = os.stat(filename)
        deferred = self.sftp_server.getAttrs(filename, False)
        return deferred.addCallback(self.checkAttrs, stat_value)

    def test_serverGetAttrsError(self):
        # Errors in getAttrs on the TransportSFTPServer are translated into
        # SFTPErrors.
        nonexistent_file = self.getPathSegment()
        deferred = self.sftp_server.getAttrs(nonexistent_file, False)
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_removeFile(self):
        # removeFile removes the file.
        filename = self.getPathSegment()
        self.build_tree_contents([(filename, 'bar')])
        deferred = self.sftp_server.removeFile(filename)
        def assertFileRemoved(ignored):
            self.failIfExists(filename)
        return deferred.addCallback(assertFileRemoved)

    def test_removeFileError(self):
        # Errors in removeFile are translated into SFTPErrors.
        filename = self.getPathSegment()
        deferred = self.sftp_server.removeFile(filename)
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_renameFile(self):
        # renameFile renames the file.
        orig_filename = self.getPathSegment()
        new_filename = self.getPathSegment()
        self.build_tree_contents([(orig_filename, 'bar')])
        deferred = self.sftp_server.renameFile(orig_filename, new_filename)
        def assertFileRenamed(ignored):
            self.failIfExists(orig_filename)
            self.failUnlessExists(new_filename)
        return deferred.addCallback(assertFileRenamed)

    def test_renameFileError(self):
        # Errors in renameFile are translated into SFTPErrors.
        orig_filename = self.getPathSegment()
        new_filename = self.getPathSegment()
        deferred = self.sftp_server.renameFile(orig_filename, new_filename)
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_makeDirectory(self):
        # makeDirectory makes the directory.
        directory = self.getPathSegment()
        deferred = self.sftp_server.makeDirectory(
            directory, {'permissions': 0777})
        def assertDirectoryExists(ignored):
            self.assertTrue(
                os.path.isdir(directory), '%r is not a directory' % directory)
            self.assertEqual(040777, os.stat(directory).st_mode)
        return deferred.addCallback(assertDirectoryExists)

    def test_makeDirectoryError(self):
        # Errors in makeDirectory are translated into SFTPErrors.
        nonexistent = self.getPathSegment()
        nonexistent_child = '%s/%s' % (nonexistent, self.getPathSegment())
        deferred = self.sftp_server.makeDirectory(
            nonexistent_child, {'permissions': 0777})
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_removeDirectory(self):
        # removeDirectory removes the directory.
        directory = self.getPathSegment()
        os.mkdir(directory)
        deferred = self.sftp_server.removeDirectory(directory)
        def assertDirectoryRemoved(ignored):
            self.failIfExists(directory)
        return deferred.addCallback(assertDirectoryRemoved)

    def test_removeDirectoryError(self):
        # Errors in removeDirectory are translated into SFTPErrors.
        directory = self.getPathSegment()
        deferred = self.sftp_server.removeDirectory(directory)
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def test_gotVersion(self):
        # gotVersion returns an empty dictionary.
        extended = self.sftp_server.gotVersion('version', {})
        self.assertEqual({}, extended)

    def test_extendedRequest(self):
        # We don't support any extensions.
        self.assertRaises(
            NotImplementedError, self.sftp_server.extendedRequest,
            'foo', 'bar')

    def test_realPath(self):
        # realPath returns the absolute path of the file.
        src, dst = self.getPathSegment(), self.getPathSegment()
        os.symlink(src, dst)
        deferred = self.sftp_server.realPath(dst)
        return deferred.addCallback(self.assertEqual, os.path.abspath(src))

    def test_makeLink(self):
        # makeLink is not supported.
        self.assertRaises(
            NotImplementedError, self.sftp_server.makeLink,
            self.getPathSegment(), self.getPathSegment())

    def test_readLink(self):
        # readLink is not supported.
        self.assertRaises(
            NotImplementedError, self.sftp_server.readLink,
            self.getPathSegment())

    def test_openDirectory(self):
        # openDirectory returns an iterator that iterates over the contents of
        # the directory.
        parent_dir = self.getPathSegment()
        child_dir = self.getPathSegment()
        child_file = self.getPathSegment()
        self.build_tree([
            parent_dir + '/',
            '%s/%s/' % (parent_dir, child_dir),
            '%s/%s' % (parent_dir, child_file)])
        deferred = self.sftp_server.openDirectory(parent_dir)
        def check_open_directory(directory):
            self.assertEqual(
                [(child_dir, child_dir, {}), (child_file, child_file, {})],
                list(sorted((directory))))
            directory.close()
        return deferred.addCallback(check_open_directory)

    def test_openDirectoryError(self):
        # Errors in openDirectory are translated into SFTPErrors.
        nonexistent = self.getPathSegment()
        deferred = self.sftp_server.openDirectory(nonexistent)
        return self.assertFailure(deferred, filetransfer.SFTPError)

    def do_translation_test(self, exception, sftp_code, method_name=None):
        """Test that `exception` is translated into the correct SFTPError."""
        result = self.assertRaises(filetransfer.SFTPError,
            self.sftp_server.translateError,
            failure.Failure(exception), method_name)
        self.assertEqual(sftp_code, result.code)
        self.assertEqual(str(exception), result.message)

    def test_translatePermissionDenied(self):
        exception = bzr_errors.PermissionDenied(self.getPathSegment())
        self.do_translation_test(exception, filetransfer.FX_PERMISSION_DENIED)

    def test_translateTransportNotPossible(self):
        exception = bzr_errors.TransportNotPossible(self.getPathSegment())
        self.do_translation_test(exception, filetransfer.FX_PERMISSION_DENIED)

    def test_translateNoSuchFile(self):
        exception = bzr_errors.NoSuchFile(self.getPathSegment())
        self.do_translation_test(exception, filetransfer.FX_NO_SUCH_FILE)

    def test_translateFileExists(self):
        exception = bzr_errors.FileExists(self.getPathSegment())
        self.do_translation_test(
            exception, filetransfer.FX_FILE_ALREADY_EXISTS)

    def test_translateFileIsADirectory(self):
        exception = FileIsADirectory(self.getPathSegment())
        self.do_translation_test(
            exception, filetransfer.FX_FILE_IS_A_DIRECTORY)

    def test_translateDirectoryNotEmpty(self):
        exception = bzr_errors.DirectoryNotEmpty(self.getPathSegment())
        self.do_translation_test(
            exception, filetransfer.FX_FAILURE)

    def test_translateRandomError(self):
        # translateError re-raises unrecognized errors.
        exception = KeyboardInterrupt()
        result = self.assertRaises(KeyboardInterrupt,
            self.sftp_server.translateError,
            failure.Failure(exception), 'methodName')
        self.assertIs(result, exception)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
