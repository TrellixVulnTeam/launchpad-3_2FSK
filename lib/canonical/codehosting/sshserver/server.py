# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0231

__metaclass__ = type
__all__ = [
    'LaunchpadAvatar',
    'Factory',
    'PublicKeyFromLaunchpadChecker',
    'Realm',
    'SSHUserAuthServer',
    'SubsystemOnlySession',
    'UserDisplayedUnauthorizedLogin',
    ]

import binascii
import logging

from twisted.conch import avatar
from twisted.conch.error import ConchError
from twisted.conch.interfaces import ISession
from twisted.conch.ssh import channel, filetransfer, session, userauth
from twisted.conch.ssh.common import getNS, NS
from twisted.conch.checkers import SSHPublicKeyDatabase

from twisted.cred.error import UnauthorizedLogin
from twisted.cred.checkers import ICredentialsChecker
from twisted.cred.portal import IRealm

from twisted.python import components, failure

from canonical.codehosting import sftp
from canonical.codehosting.sshserver.smartserver import launch_smart_server
from canonical.config import config

from zope.interface import implements


class SubsystemOnlySession(session.SSHSession, object):
    """Session adapter that corrects a bug in Conch."""

    def closeReceived(self):
        # Without this, the client hangs when its finished transferring.
        self.loseConnection()

    def loseConnection(self):
        # XXX: JonathanLange 2008-03-31: This deliberately replaces the
        # implementation of session.SSHSession.loseConnection. The default
        # implementation will try to call loseConnection on the client
        # transport even if it's None. I don't know *why* it is None, so this
        # doesn't necessarily address the root cause.
        transport = getattr(self.client, 'transport', None)
        if transport is not None:
            transport.loseConnection()
        # This is called by session.SSHSession.loseConnection. SSHChannel is
        # the base class of SSHSession.
        channel.SSHChannel.loseConnection(self)

    def stopWriting(self):
        """See `session.SSHSession.stopWriting`.

        When the client can't keep up with us, we ask the child process to
        stop giving us data.
        """
        # XXX: MichaelHudson 2008-06-27: Being cagey about whether
        # self.client.transport is entirely paranoia inspired by the comment
        # in `loseConnection` above.  It would be good to know if and why it
        # is necessary.
        transport = getattr(self.client, 'transport', None)
        if transport is not None:
            transport.pauseProducing()

    def startWriting(self):
        """See `session.SSHSession.startWriting`.

        The client is ready for data again, so ask the child to start
        producing data again.
        """
        # XXX: MichaelHudson 2008-06-27: Being cagey about whether
        # self.client.transport is entirely paranoia inspired by the comment
        # in `loseConnection` above.  It would be good to know if and why it
        # is necessary.
        transport = getattr(self.client, 'transport', None)
        if transport is not None:
            transport.resumeProducing()


class LaunchpadAvatar(avatar.ConchUser):
    """An account on the SSH server, corresponding to a Launchpad person.

    :ivar branchfs_proxy: A Twisted XML-RPC client for the authserver. The
        server must implement `IBranchFileSystem`.
    :ivar channelLookup: See `avatar.ConchUser`.
    :ivar subsystemLookup: See `avatar.ConchUser`.
    :ivar user_id: The Launchpad database ID of the Person for this account.
    :ivar username: The Launchpad username for this account.
    """

    def __init__(self, userDict, branchfs_proxy):
        avatar.ConchUser.__init__(self)
        self.branchfs_proxy = branchfs_proxy
        self.user_id = userDict['id']
        self.username = userDict['name']
        logging.getLogger('codehosting.ssh').info(
            '%r logged in', self.username)

        # Set the only channel as a session that only allows requests for
        # subsystems...
        self.channelLookup = {'session': SubsystemOnlySession}
        # ...and set the only subsystem to be SFTP.
        self.subsystemLookup = {'sftp': filetransfer.FileTransferServer}


components.registerAdapter(launch_smart_server, LaunchpadAvatar, ISession)

components.registerAdapter(
    sftp.avatar_to_sftp_server, LaunchpadAvatar, filetransfer.ISFTPServer)


class UserDisplayedUnauthorizedLogin(UnauthorizedLogin):
    """UnauthorizedLogin which should be reported to the user."""


class Realm:
    implements(IRealm)

    avatarFactory = LaunchpadAvatar

    def __init__(self, authentication_proxy, branchfs_proxy):
        self.authentication_proxy = authentication_proxy
        self.branchfs_proxy = branchfs_proxy

    def requestAvatar(self, avatarId, mind, *interfaces):
        # Fetch the user's details from the authserver
        deferred = self.authentication_proxy.callRemote('getUser', avatarId)

        # Once all those details are retrieved, we can construct the avatar.
        def gotUserDict(userDict):
            avatar = self.avatarFactory(userDict, self.branchfs_proxy)
            return interfaces[0], avatar, lambda: None
        return deferred.addCallback(gotUserDict)


class SSHUserAuthServer(userauth.SSHUserAuthServer):

    def __init__(self, transport=None):
        self.transport = transport
        self._configured_banner_sent = False

    def sendBanner(self, text, language='en'):
        bytes = '\r\n'.join(text.encode('UTF8').splitlines() + [''])
        self.transport.sendPacket(userauth.MSG_USERAUTH_BANNER,
                                  NS(bytes) + NS(language))

    def _sendConfiguredBanner(self, passed_through):
        if (not self._configured_banner_sent
            and config.codehosting.banner is not None):
            self._configured_banner_sent = True
            self.sendBanner(config.codehosting.banner)
        return passed_through

    def ssh_USERAUTH_REQUEST(self, packet):
        # This is copied and pasted from twisted/conch/ssh/userauth.py in
        # Twisted 8.0.1. We do this so we can add _ebLogToBanner between
        # two existing errbacks.
        user, nextService, method, rest = getNS(packet, 3)
        if user != self.user or nextService != self.nextService:
            self.authenticatedWith = [] # clear auth state
        self.user = user
        self.nextService = nextService
        self.method = method
        d = self.tryAuth(method, user, rest)
        if not d:
            self._ebBadAuth(failure.Failure(ConchError('auth returned none')))
            return
        d.addCallback(self._sendConfiguredBanner)
        d.addCallbacks(self._cbFinishedAuth)
        d.addErrback(self._ebMaybeBadAuth)
        # This line does not appear in the original.
        d.addErrback(self._ebLogToBanner)
        d.addErrback(self._ebBadAuth)
        return d

    def _ebLogToBanner(self, reason):
        reason.trap(UserDisplayedUnauthorizedLogin)
        self.sendBanner(reason.getErrorMessage())
        return reason


class PublicKeyFromLaunchpadChecker(SSHPublicKeyDatabase):
    """Cred checker for getting public keys from launchpad.

    It knows how to get the public keys from the authserver.
    """
    implements(ICredentialsChecker)

    def __init__(self, authserver):
        self.authserver = authserver

    def checkKey(self, credentials):
        d = self.authserver.callRemote('getUser', credentials.username)
        return d.addCallback(self._checkUserExistence, credentials)

    def _checkUserExistence(self, userDict, credentials):
        if len(userDict) == 0:
            raise UserDisplayedUnauthorizedLogin(
                "No such Launchpad account: %s" % credentials.username)

        authorizedKeys = self.authserver.callRemote(
            'getSSHKeys', credentials.username)

        # Add callback to try find the authorized key
        authorizedKeys.addCallback(self._checkForAuthorizedKey, credentials)
        return authorizedKeys

    def _checkForAuthorizedKey(self, keys, credentials):
        if credentials.algName == 'ssh-dss':
            wantKeyType = 'DSA'
        elif credentials.algName == 'ssh-rsa':
            wantKeyType = 'RSA'
        else:
            # unknown key type
            return False

        if len(keys) == 0:
            raise UserDisplayedUnauthorizedLogin(
                "Launchpad user %r doesn't have a registered SSH key"
                % credentials.username)

        for keytype, keytext in keys:
            if keytype != wantKeyType:
                continue
            try:
                if keytext.decode('base64') == credentials.blob:
                    return True
            except binascii.Error:
                continue

        raise UnauthorizedLogin(
            "Your SSH key does not match any key registered for Launchpad "
            "user %s" % credentials.username)
