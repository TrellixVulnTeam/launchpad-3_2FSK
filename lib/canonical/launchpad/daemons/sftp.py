# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Provides an SFTP server which Launchpad users can use to host their Bazaar
branches. For more information, see lib/canonical/codehosting/README.
"""

__metaclass__ = type
__all__ = ['SSHService']


import os

from twisted.cred.portal import Portal
from twisted.conch.ssh import keys
from twisted.application import service, strports

from canonical.config import config
from canonical.authserver.client.twistedclient import TwistedAuthServer

from canonical.codehosting import sshserver


class SSHService(service.Service):
    """A Twisted service for the supermirror SFTP server."""

    def __init__(self):
        self.service = self.makeService()

    def makeRealm(self):
        """Create and return an authentication realm for the authserver."""
        homedirs = config.codehosting.branches_root
        authserver = TwistedAuthServer(config.codehosting.authserver)
        return sshserver.Realm(homedirs, authserver)

    def makeFactory(self, hostPublicKey, hostPrivateKey):
        """Create and return an SFTP server that uses the given public and
        private keys.
        """
        homedirs = config.codehosting.branches_root
        authserver = TwistedAuthServer(config.codehosting.authserver)
        portal = Portal(self.makeRealm())
        portal.registerChecker(
            sshserver.PublicKeyFromLaunchpadChecker(authserver))
        sftpfactory = sshserver.Factory(hostPublicKey, hostPrivateKey)
        sftpfactory.portal = portal
        return sftpfactory

    def makeService(self):
        """Return a service that provides an SFTP server. This is called in the
        constructor.
        """
        hostPublicKey, hostPrivateKey = self.makeKeys()
        sftpfactory = self.makeFactory(hostPublicKey, hostPrivateKey)
        return strports.service(config.codehosting.port, sftpfactory)

    def makeKeys(self):
        """Load the public and private host keys from the configured key pair
        path. Returns both keys in a 2-tuple.

        :return: (hostPublicKey, hostPrivateKey)
        """
        keydir = config.codehosting.host_key_pair_path
        hostPublicKey = keys.getPublicKeyString(
            data=open(os.path.join(keydir,
                                   'ssh_host_key_rsa.pub'), 'rb').read())
        hostPrivateKey = keys.getPrivateKeyObject(
            data=open(os.path.join(keydir,
                                   'ssh_host_key_rsa'), 'rb').read())
        return hostPublicKey, hostPrivateKey

    def startService(self):
        """Start the SFTP service."""
        service.Service.startService(self)
        self.service.startService()

    def stopService(self):
        """Stop the SFTP service."""
        service.Service.stopService(self)
        self.service.stopService()
