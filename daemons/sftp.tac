# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
#
# This is a Twisted application config file.  To run, use:
#     twistd -noy sftp.tac
# or similar.  Refer to the twistd(1) man page for details.

import os

from twisted.cred import portal
from twisted.conch.ssh import keys
from twisted.application import service, strports

from canonical.config import config
from canonical.authserver.client.twistedclient import TwistedAuthServer

from supermirrorsftp import sftponly

# mkdir keys; cd keys; ssh-keygen -t rsa -f ssh_host_key_rsa
keydir = config.supermirrorsftp.host_key_pair_path
hostPublicKey = keys.getPublicKeyString(
    data=open(os.path.join(keydir, 'ssh_host_key_rsa.pub'), 'rb').read()
)
hostPrivateKey = keys.getPrivateKeyObject(
    data=open(os.path.join(keydir, 'ssh_host_key_rsa'), 'rb').read()
)

# Configure the authentication
homedirs = config.branches_root
authserver = TwistedAuthServer(config.supermirrorsftp.authserver)
portal = portal.Portal(sftponly.Realm(homedirs, authserver))
portal.registerChecker(sftponly.PublicKeyFromLaunchpadChecker(authserver))
sftpfactory = sftponly.Factory(hostPublicKey, hostPrivateKey)
sftpfactory.portal = portal

# Configure it to listen on a port
application = service.Application('sftponly')
service = strports.service(config.supermirrorsftp.port, sftpfactory)
service.setServiceParent(application)

