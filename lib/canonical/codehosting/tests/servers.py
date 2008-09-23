# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Servers used in codehosting tests."""

__metaclass__ = type

__all__ = [
    'CodeHostingServer',
    'SSHCodeHostingServer',
    'make_bzr_ssh_server',
    'make_launchpad_server',
    'make_sftp_server',
    ]


import gc
import os
import shutil
import tempfile
import threading

from zope.component import getUtility

from bzrlib.transport import get_transport, ssh, Server
from bzrlib.transport.memory import MemoryServer, MemoryTransport

from twisted.conch.ssh import filetransfer
from twisted.internet import defer
from twisted.internet.protocol import connectionDone
from twisted.python.util import sibpath

from canonical.config import config
from canonical.database.sqlbase import commit
from canonical.launchpad.daemons.sftp import SSHService
from canonical.launchpad.interfaces import (
    IPersonSet, ISSHKeySet, SSHKeyType, TeamSubscriptionPolicy)

from canonical.codehosting.branchfs import LaunchpadServer
from canonical.codehosting.branchfsclient import BlockingProxy
from canonical.codehosting.sshserver import LaunchpadAvatar

from canonical.codehosting.tests.helpers import FakeLaunchpad


def make_launchpad_server():
    user_id = 1
    return FakeLaunchpadServer(user_id)


def make_sftp_server():
    branches_root = config.codehosting.branches_root
    mirror_root = config.supermirror.branchesdest
    return SFTPCodeHostingServer(branches_root, mirror_root)


def make_bzr_ssh_server():
    branches_root = config.codehosting.branches_root
    mirror_root = config.supermirror.branchesdest
    return BazaarSSHCodeHostingServer(branches_root, mirror_root)


class ConnectionTrackingParamikoVendor(ssh.ParamikoVendor):
    """Wrapper for ParamikoVendor that tracks connections.

    Used by the test suite to make sure that all connections are closed in a
    timely fashion.
    """

    def __init__(self):
        ssh.ParamikoVendor.__init__(self)
        self._ssh_transports = []
        self._ssh_channels = []
        self._sftp_clients = []

    def _connect(self, username, password, host, port):
        transport = ssh.ParamikoVendor._connect(
            self, username, password, host, port)
        self._ssh_transports.append(transport)
        return transport

    def connect_sftp(self, username, password, host, port):
        client = ssh.ParamikoVendor.connect_sftp(
            self, username, password, host, port)
        self._sftp_clients.append(client)
        return client

    def _closeAllTransports(self):
        if self._sftp_clients:
            while self._sftp_clients:
                client = self._sftp_clients.pop()
                client.close()
            gc.collect()
        while self._ssh_transports:
            connection = self._ssh_transports.pop()
            connection.close()


def set_up_host_keys_for_testing():
    """Put ssh host keys into a directory where the server will find them."""
    key_pair_path = config.codehosting.host_key_pair_path
    if os.path.isdir(key_pair_path):
        shutil.rmtree(key_pair_path)
    parent = os.path.dirname(key_pair_path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    shutil.copytree(
        sibpath(__file__, 'keys'), os.path.join(key_pair_path))


def set_up_test_user(test_user, test_team):
    """Configure a user called 'test_user' with SSH keys.

    Also make sure that 'test_user' belongs to 'test_team'.
    """
    person_set = getUtility(IPersonSet)
    testUser = person_set.getByName('no-priv')
    testUser.name = test_user
    testTeam = person_set.newTeam(
        testUser, test_team, test_team,
        subscriptionpolicy=TeamSubscriptionPolicy.OPEN)
    testUser.join(testTeam)
    ssh_key_set = getUtility(ISSHKeySet)
    ssh_key_set.new(
        testUser, SSHKeyType.DSA,
        'AAAAB3NzaC1kc3MAAABBAL5VoWG5sy3CnLYeOw47L8m9A15hA/PzdX2u0B7c2Z1k'
        'tFPcEaEuKbLqKVSkXpYm7YwKj9y88A9Qm61CdvI0c50AAAAVAKGY0YON9dEFH3Dz'
        'eVYHVEBGFGfVAAAAQCoe0RhBcefm4YiyQVwMAxwTlgySTk7FSk6GZ95EZ5Q8/OTd'
        'ViTaalvGXaRIsBdaQamHEBB+Vek/VpnF1UGGm8YAAABAaCXDl0r1k93JhnMdF0ap'
        '4UJQ2/NnqCyoE8Xd5KdUWWwqwGdMzqB1NOeKN6ladIAXRggLc2E00UsnUXh3GE3R'
        'gw==', 'testuser')
    commit()


class FakeLaunchpadServer(LaunchpadServer):

    def __init__(self, user_id):
        authserver = FakeLaunchpad()
        server = MemoryServer()
        server.setUp()
        # The backing transport is supplied during FakeLaunchpadServer.setUp.
        mirror_transport = get_transport(server.get_url())
        LaunchpadServer.__init__(
            self, BlockingProxy(authserver), user_id, MemoryTransport(),
            mirror_transport)
        self._schema = 'lp'

    def getTransport(self, path=None):
        if path is None:
            path = ''
        transport = get_transport(self.get_url()).clone(path)
        return transport

    def setUp(self):
        LaunchpadServer.setUp(self)

    def tearDown(self):
        LaunchpadServer.tearDown(self)
        return defer.succeed(None)

    def runAndWaitForDisconnect(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class CodeHostingServer(Server):

    def __init__(self, branches_root, mirror_root):
        Server.__init__(self)
        self._branches_root = branches_root
        self._mirror_root = mirror_root

    def setUp(self):
        if os.path.isdir(self._branches_root):
            shutil.rmtree(self._branches_root)
        os.makedirs(self._branches_root, 0700)
        if os.path.isdir(self._mirror_root):
            shutil.rmtree(self._mirror_root)
        os.makedirs(self._mirror_root, 0700)
        set_up_host_keys_for_testing()
        set_up_test_user('testuser', 'testteam')

    def tearDown(self):
        shutil.rmtree(self._branches_root)
        return defer.succeed(None)

    def getTransport(self, relpath=None):
        """Return a new transport for 'relpath', adding necessary cleanup."""
        raise NotImplementedError()


class SSHCodeHostingServer(CodeHostingServer):

    def __init__(self, schema, branches_root, mirror_root):
        self._schema = schema
        CodeHostingServer.__init__(
            self, branches_root, mirror_root)

    def setUpFakeHome(self):
        user_home = os.path.abspath(tempfile.mkdtemp())
        os.makedirs(os.path.join(user_home, '.ssh'))
        shutil.copyfile(
            sibpath(__file__, 'id_dsa'),
            os.path.join(user_home, '.ssh', 'id_dsa'))
        shutil.copyfile(
            sibpath(__file__, 'id_dsa.pub'),
            os.path.join(user_home, '.ssh', 'id_dsa.pub'))
        os.chmod(os.path.join(user_home, '.ssh', 'id_dsa'), 0600)
        real_home, os.environ['HOME'] = os.environ['HOME'], user_home
        return real_home, user_home

    def forceParamiko(self):
        _old_vendor_manager = ssh._ssh_vendor_manager._cached_ssh_vendor
        vendor = ConnectionTrackingParamikoVendor()
        ssh._ssh_vendor_manager._cached_ssh_vendor = vendor
        return _old_vendor_manager

    def getTransport(self, path=None):
        if path is None:
            path = ''
        transport = get_transport(self.get_url()).clone(path)
        return transport

    def closeAllConnections(self):
        ssh._ssh_vendor_manager._cached_ssh_vendor._closeAllTransports()

    def setUp(self):
        self._real_home, self._fake_home = self.setUpFakeHome()
        self._old_vendor_manager = self.forceParamiko()
        CodeHostingServer.setUp(self)
        self.server = _TestSSHService()
        self.server.startService()

    def tearDown(self):
        self.closeAllConnections()
        deferred1 = self.server.stopService()
        os.environ['HOME'] = self._real_home
        deferred2 = CodeHostingServer.tearDown(self)
        shutil.rmtree(self._fake_home)
        ssh._ssh_vendor_manager._cached_ssh_vendor = self._old_vendor_manager
        return defer.gatherResults([deferred1, deferred2])

    def get_url(self, user=None):
        if user is None:
            user = 'testuser'
        return '%s://%s@localhost:22222/' % (self._schema, user)


class SFTPCodeHostingServer(SSHCodeHostingServer):

    def __init__(self, branches_root, mirror_root):
        SSHCodeHostingServer.__init__(
            self, 'sftp', branches_root, mirror_root)

    def runAndWaitForDisconnect(self, func, *args, **kwargs):
        """Run the given function, close all SFTP connections, and wait for
        the server to acknowledge the end of the session.
        """
        ever_connected = threading.Event()
        done = threading.Event()
        self.server.setConnectionMadeEvent(ever_connected)
        self.server.setConnectionLostEvent(done)
        try:
            return func(*args, **kwargs)
        finally:
            self.closeAllConnections()
            # done.wait() can block forever if func() never actually
            # connects, so only wait if we are sure that the client
            # connected.
            if ever_connected.isSet():
                done.wait()


class BazaarSSHCodeHostingServer(SSHCodeHostingServer):

    def __init__(self, branches_root, mirror_root):
        SSHCodeHostingServer.__init__(
            self, 'bzr+ssh', branches_root, mirror_root)

    def runAndWaitForDisconnect(self, func, *args, **kwargs):
        """Run the given function, close all connections, and wait for the
        server to acknowledge the end of the session.
        """
        try:
            return func(*args, **kwargs)
        finally:
            self.closeAllConnections()


class _TestSSHService(SSHService):
    """SSH service that uses the the _TestLaunchpadAvatar and installs the
    test keys in a place that the SSH server can find them.

    This class, _TestLaunchpadAvatar and _TestBazaarFileTransferServer work
    together to provide a threading event which is set when the first
    connecting SSH client closes its connection to the SSH server.
    """

    _connection_lost_event = None
    _connection_made_event = None
    avatar = None

    def getConnectionLostEvent(self):
        return self._connection_lost_event

    def getConnectionMadeEvent(self):
        return self._connection_made_event

    def setConnectionLostEvent(self, event):
        self._connection_lost_event = event

    def setConnectionMadeEvent(self, event):
        self._connection_made_event = event

    def makeRealm(self):
        realm = SSHService.makeRealm(self)
        realm.avatarFactory = self.makeAvatar
        return realm

    def makeAvatar(self, userDict, launchpad):
        self.avatar = _TestLaunchpadAvatar(self, userDict, launchpad)
        return self.avatar


class _TestLaunchpadAvatar(LaunchpadAvatar):
    """SSH avatar that uses the _TestBazaarFileTransferServer."""

    def __init__(self, service, userDict, launchpad):
        LaunchpadAvatar.__init__(self, userDict, launchpad)
        self.service = service
        self.subsystemLookup = {'sftp': self.makeFileTransferServer}

    def getConnectionLostEvent(self):
        return self.service.getConnectionLostEvent()

    def getConnectionMadeEvent(self):
        return self.service.getConnectionMadeEvent()

    def makeFileTransferServer(self, data=None, avatar=None):
        return _TestBazaarFileTransferServer(data, avatar)


class _TestBazaarFileTransferServer(filetransfer.FileTransferServer):
    """BazaarFileTransferServer that sets a threading event when it loses its
    first connection.
    """
    def __init__(self, data=None, avatar=None):
        filetransfer.FileTransferServer.__init__(
            self, data=data, avatar=avatar)
        self.avatar = avatar

    def getConnectionLostEvent(self):
        return self.avatar.getConnectionLostEvent()

    def getConnectionMadeEvent(self):
        return self.avatar.getConnectionMadeEvent()

    def connectionMade(self):
        event = self.getConnectionMadeEvent()
        if event is not None:
            event.set()

    def connectionLost(self, reason=connectionDone):
        event = self.getConnectionLostEvent()
        if event is not None:
            event.set()
