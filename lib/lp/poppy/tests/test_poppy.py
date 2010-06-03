# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functional tests for poppy FTP daemon."""

__metaclass__ = type

import ftplib
import os
import shutil
import socket
import StringIO
import tempfile
import time
import transaction
import unittest

from bzrlib.tests import (
    condition_id_re, exclude_tests_by_condition, multiply_tests)
from bzrlib.transport import get_transport
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.daemons.tachandler import TacTestSetup
from canonical.testing.layers import (
    ZopelessAppServerLayer, ZopelessDatabaseLayer)
from lp.registry.interfaces.ssh import ISSHKeySet, SSHKeyType
from lp.poppy.tests.helpers import PoppyTestSetup
from lp.testing import TestCaseWithFactory

class FTPServer:
    """This is an abstraction of connecting to an FTP server."""

    def __init__(self, root_dir, factory):
        self.root_dir = root_dir
        self.port = 3421

    def setUp(self):
        self.poppy = PoppyTestSetup(
            self.root_dir, port=self.port, cmd='echo CLOSED')
        self.poppy.startPoppy()

    def tearDown(self):
        self.poppy.killPoppy()

    def getTransport(self):
        return get_transport('ftp://ubuntu:@localhost:%s/' % (self.port,))

    def disconnect(self, transport):
        transport._get_connection().quit()

    def _getFTPConnection(self):
        # poppy usually takes sometime to come up, we need to wait, or insist.
        conn = ftplib.FTP()
        while True:
            try:
                conn.connect("localhost", self.port)
            except socket.error:
                if not self.poppy.alive:
                    raise
            else:
                break
        return conn

    def waitForStartUp(self):
        """Wait for the FTP server to start up."""
        conn = self._getFTPConnection()
        conn.quit()

    def waitForClose(self):
        """Wait for an FTP connection to close.

        Poppy is configured to echo 'CLOSED' to stdout when a
        connection closes, so we wait for CLOSED to appear in its
        output as a way to tell that the server has finished with the
        connection.
        """
        self.poppy.verify_output(['CLOSED'])


class SFTPServer:
    """This is an abstraction of connecting to an SFTP server."""

    def __init__(self, root_dir, factory):
        self.root_dir = root_dir
        self._factory = factory
        self.port = 5022

    def addSSHKey(self, person, public_key_path):
        f = open(public_key_path, 'r')
        try:
            public_key = f.read()
        finally:
            f.close()
        kind, key_text, comment = public_key.split(' ', 2)
        sshkeyset = getUtility(ISSHKeySet)
        # Assume it's an RSA key for now, ignoring the actual value in the
        # file.
        key = sshkeyset.new(person, SSHKeyType.RSA, key_text, comment)
        transaction.commit()
        return key

    def setUpUser(self, name):
        user = self._factory.makePerson(name=name)
        self.addSSHKey(
            user, os.path.join(os.path.dirname(__file__), 'poppy-sftp.pub'))
        # Set up a temporary home directory for Paramiko's sake
        self._home_dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self._home_dir, '.ssh'))
        os.symlink(
            os.path.join(os.path.dirname(__file__), 'poppy-sftp'),
            os.path.join(self._home_dir, '.ssh', 'id_rsa'))
        self._current_home = os.environ['HOME']
        # We'd rather not have an agent interfere
        os.environ.pop('SSH_AUTH_SOCK', None)
        os.environ['HOME'] = self._home_dir
        # XXX: Just blat over the BZR_SSH env var. Restoring env vars is a
        # little tricky, see lp.testing.TestCaseWithFactory.useTempBzrHome.
        os.environ['BZR_SSH'] = 'paramiko'

    def setUp(self):
        self.setUpUser('joe')
        self._tac = PoppyTac(self.root_dir)
        self._tac.setUp()

    def tearDown(self):
        shutil.rmtree(self._home_dir)
        os.environ['HOME'] = self._current_home
        self._tac.tearDown()

    def disconnect(self, transport):
        transport._get_connection().close()

    def waitForStartUp(self):
        pass

    def waitForClose(self):
        # XXX: Eww
        time.sleep(10)

    def getTransport(self):
        return get_transport('sftp://joe@localhost:%s/' % (self.port,))


class PoppyTac(TacTestSetup):

    def __init__(self, fs_root):
        os.environ['POPPY_ROOT'] = fs_root
        self.setUpRoot()
        super(PoppyTac, self).setUp(umask='0')

    def setUpRoot(self):
        self._root = tempfile.mkdtemp()

    def tearDownRoot(self):
        shutil.rmtree(self._root)

    @property
    def root(self):
        return self._root

    @property
    def tacfile(self):
        return os.path.abspath(
            os.path.join(config.root, 'daemons', 'poppy-sftp.tac'))

    @property
    def logfile(self):
        return os.path.join('/tmp', 'poppy-sftp.log')

    @property
    def pidfile(self):
        return os.path.join(self.root, 'poppy-sftp.pid')


class TestPoppy(TestCaseWithFactory):
    """Test if poppy.py daemon works properly."""

    def setUp(self):
        """Set up poppy in a temp dir."""
        super(TestPoppy, self).setUp()
        self.root_dir = self.makeTemporaryDirectory()
        self.server = self.server_factory(self.root_dir, self.factory)
        self.installFixture(self.server)

    def _uploadPath(self, path):
        """Return system path of specified path inside an upload.

        Only works for a single upload (poppy transaction).
        """
        contents = sorted(os.listdir(self.root_dir))
        upload_dir = contents[1]
        return os.path.join(self.root_dir, upload_dir, path)

    def test_change_directory(self):
        """Check automatic creation of directories 'cwd'ed in.

        Also ensure they are created with proper permission (g+rwxs)
        """
        self.server.waitForStartUp()

        transport = self.server.getTransport()
        transport.stat('foo/bar') # .stat will implicity chdir for us
        
        self.server.disconnect(transport)
        self.server.waitForClose()

        wanted_path = self._uploadPath('foo/bar')
        self.assertTrue(os.path.exists(wanted_path))
        self.assertEqual(os.stat(wanted_path).st_mode, 042775)

    def test_mkdir(self):
        # Creating directories on the server makes actual directories where we
        # expect them, and creates them with g+rwxs
        self.server.waitForStartUp()

        transport = self.server.getTransport()
        transport.mkdir('foo/bar', mode=None)

        self.server.disconnect(transport)
        self.server.waitForClose()

        wanted_path = self._uploadPath('foo/bar')
        self.assertTrue(os.path.exists(wanted_path))
        self.assertEqual(os.stat(wanted_path).st_mode, 042775)

    def test_rmdir(self):
        """Check recursive RMD (aka rmdir)"""
        self.server.waitForStartUp()

        transport = self.server.getTransport()
        transport.mkdir('foo/bar')
        transport.rmdir('foo/bar')
        transport.rmdir('foo')
        
        self.server.disconnect(transport)
        self.server.waitForClose()

        wanted_path = self._uploadPath('foo')
        self.assertFalse(os.path.exists(wanted_path))

    def test_single_upload(self):
        """Check if the parent directories are created during file upload.

        The uploaded file permissions are also special (g+rwxs).
        """
        self.server.waitForStartUp()

        transport = self.server.getTransport()
        fake_file = StringIO.StringIO("fake contents")

        transport.put_file('foo/bar/baz', fake_file, mode=None)

        self.server.disconnect(transport)
        self.server.waitForClose()

        wanted_path = self._uploadPath('foo/bar/baz')
        fs_content = open(os.path.join(wanted_path)).read()
        self.assertEqual(fs_content, "fake contents")
        self.assertEqual(os.stat(wanted_path).st_mode, 0102674)

    def test_full_source_upload(self):
        """Check that the connection will deal with multiple files being
        uploaded.
        """
        self.server.waitForStartUp()

        transport = self.server.getTransport()

        files = ['test-source_0.1.dsc',
                 'test-source_0.1.orig.tar.gz',
                 'test-source_0.1.diff.gz',
                 'test-source_0.1_source.changes']

        for upload in files:
            fake_file = StringIO.StringIO(upload)
            file_to_upload = "~ppa-user/ppa/ubuntu/%s" % upload
            transport.put_file(file_to_upload, fake_file, mode=None)

        self.server.disconnect(transport)
        self.server.waitForClose()

        self.assertEqual(os.stat(self._uploadPath('')).st_mode, 042770)
        for upload in files:
            wanted_path = self._uploadPath(
                "~ppa-user/ppa/ubuntu/%s" % upload)
            fs_content = open(os.path.join(wanted_path)).read()
            self.assertEqual(fs_content, upload)
            self.assertEqual(os.stat(wanted_path).st_mode, 0102674)

    def test_upload_isolation(self):
        """Check if poppy isolates the uploads properly.

        Upload should be done atomically, i.e., poppy should isolate the
        context according each connection/session.
        """
        # Perform a pair of sessions with distinct connections in time.
        self.server.waitForStartUp()

        conn_one = self.server.getTransport()
        fake_file = StringIO.StringIO("ONE")
        conn_one.put_file('test', fake_file, mode=None)
        self.server.disconnect(conn_one)
        self.server.waitForClose()

        conn_two = self.server.getTransport()
        fake_file = StringIO.StringIO("TWO")
        conn_two.put_file('test', fake_file, mode=None)
        self.server.disconnect(conn_two)
        self.server.waitForClose()

        # Perform a pair of sessions with simultaneous connections.
        conn_three = self.server.getTransport()
        conn_four = self.server.getTransport()

        fake_file = StringIO.StringIO("THREE")
        conn_three.put_file('test', fake_file, mode=None)

        fake_file = StringIO.StringIO("FOUR")
        conn_four.put_file('test', fake_file, mode=None)

        self.server.disconnect(conn_three)
        self.server.waitForClose()

        self.server.disconnect(conn_four)
        self.server.waitForClose()

        # Build a list of directories representing the 4 sessions.
        upload_dirs = [leaf for leaf in sorted(os.listdir(self.root_dir))
                       if not leaf.startswith(".") and
                       not leaf.endswith(".distro")]
        self.assertEqual(len(upload_dirs), 4)

        # Check the contents of files on each session.
        expected_contents = ['ONE', 'TWO', 'THREE', 'FOUR']
        for index in range(4):
            content = open(os.path.join(
                self.root_dir, upload_dirs[index], "test")).read()
            self.assertEqual(content, expected_contents[index])

def test_suite():
    tests = unittest.TestLoader().loadTestsFromName(__name__)
    scenarios = [
        ('ftp', {'server_factory': FTPServer,
                 # XXX: In an ideal world, this would be in the UnitTests
                 # layer. Let's get one step closer to that ideal world.
                 'layer': ZopelessDatabaseLayer}),
        ('sftp', {'server_factory': SFTPServer,
                  'layer': ZopelessAppServerLayer}),
        ]
    suite = unittest.TestSuite()
    multiply_tests(tests, scenarios, suite)
    # SFTP doesn't have the concept of the server changing directories, since
    # clients will only send absolute paths, so drop that test.
    return exclude_tests_by_condition(
        suite, condition_id_re(r'test_change_directory\(sftp\)$'))
