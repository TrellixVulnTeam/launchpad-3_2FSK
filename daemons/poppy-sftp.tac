# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# This is a Twisted application config file.  To run, use:
#     twistd -noy sftp.tac
# or similar.  Refer to the twistd(1) man page for details.

import os

from twisted.application import service
from twisted.conch.interfaces import ISession
from twisted.conch.ssh import filetransfer
from twisted.cred.portal import IRealm, Portal
from twisted.python import components
from twisted.web.xmlrpc import Proxy

from zope.interface import implements

from canonical.config import config
from canonical.launchpad.daemons import tachandler

from lp.poppy.twistedsftp import SFTPServer
from lp.services.sshserver.auth import (
    LaunchpadAvatar, PublicKeyFromLaunchpadChecker)
from lp.services.sshserver.service import SSHService
from lp.services.sshserver.session import DoNothingSession

# XXX: Rename this file to something that doesn't mention poppy. Talk to
# bigjools.


def make_portal():
    """Create and return a `Portal` for the SSH service.

    This portal accepts SSH credentials and returns our customized SSH
    avatars (see `LaunchpadAvatar`).
    """
    authentication_proxy = Proxy(
        config.poppy.authentication_endpoint)
    portal = Portal(Realm(authentication_proxy))
    portal.registerChecker(
        PublicKeyFromLaunchpadChecker(authentication_proxy))
    return portal


class Realm:
    implements(IRealm)

    def __init__(self, authentication_proxy):
        self.authentication_proxy = authentication_proxy

    def requestAvatar(self, avatar_id, mind, *interfaces):
        # Fetch the user's details from the authserver
        deferred = mind.lookupUserDetails(
            self.authentication_proxy, avatar_id)

        # Once all those details are retrieved, we can construct the avatar.
        def got_user_dict(user_dict):
            avatar = LaunchpadAvatar(user_dict)
            return interfaces[0], avatar, avatar.logout

        return deferred.addCallback(got_user_dict)


def get_poppy_root():
    """Return the poppy root to use for this server.

    If the POPPY_ROOT environment variable is set, use that. If not, use
    config.poppy.fsroot.
    """
    poppy_root = os.environ.get('POPPY_ROOT', None)
    if poppy_root:
        return poppy_root
    return config.poppy.fsroot


def poppy_sftp_adapter(avatar):
    return SFTPServer(avatar, get_poppy_root())


components.registerAdapter(
    poppy_sftp_adapter, LaunchpadAvatar, filetransfer.ISFTPServer)

components.registerAdapter(DoNothingSession, LaunchpadAvatar, ISession)


# Construct an Application that has the Poppy SSH server.
application = service.Application('poppy-sftp')
svc = SSHService(
    portal=make_portal(),
    private_key_path=config.poppy.host_key_private,
    public_key_path=config.poppy.host_key_public,
    oops_configuration='poppy',
    main_log='poppy',
    access_log='poppy.access',
    access_log_path=config.poppy.access_log,
    strport=config.poppy.port,
    idle_timeout=config.poppy.idle_timeout,
    banner=config.poppy.banner)
svc.setServiceParent(application)

# Service that announces when the daemon is ready
tachandler.ReadyService().setServiceParent(application)
