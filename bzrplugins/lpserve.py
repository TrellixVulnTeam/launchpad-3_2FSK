# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Bazaar plugin to run the smart server on Launchpad.

Cribbed from bzrlib.builtins.cmd_serve from Bazaar 0.16.
"""

__metaclass__ = type

__all__ = ['cmd_launchpad_server']


import sys
import xmlrpclib

from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib import lockdir, urlutils, ui

from bzrlib.smart import medium, server
from bzrlib.transport import get_transport, remote

from canonical.config import config


class cmd_launchpad_server(Command):
    """Run a Bazaar server that maps Launchpad branch URLs to the internal
    file-system format.
    """

    aliases = ['lp-serve']

    takes_options = [
        Option('inet',
               help='serve on stdin/out for use from inetd or sshd'),
        Option('port',
               help='listen for connections on nominated port of the form '
                    '[hostname:]portnumber. Passing 0 as the port number will'
                    ' result in a dynamically allocated port. Default port is'
                    ' 4155.',
               type=str),
        Option('upload-directory',
               help='upload branches to this directory. Defaults to '
                    'config.codehosting.branches_root.',
               type=unicode),
        Option('mirror-directory',
               help='serve branches from this directory. Defaults to '
                    'config.supermirror.branchesdest.'),
        Option('branchfs-endpoint',
               help='the url of the internal XML-RPC server. Defaults to '
                    'config.codehosting.branchfs_endpoint.',
               type=unicode),
        ]

    takes_args = ['user_id']

    def get_lp_server(self, branchfs_client, user_id, hosted_url, mirror_url):
        """Create a Launchpad smart server.

        :param branchfs_client: An `xmlrpclib.ServerProxy` (or equivalent) for the
            branch file system end-point.
        :param user_id: A unique database ID of the user whose branches are
            being served.
        :param hosted_url: Where the branches are uploaded to.
        :param mirror_url: Where all Launchpad branches are mirrored.
        :return: A `LaunchpadTransport`.
        """
        # Importing here to avoid circular import when lpserve is loaded as a
        # bzr plugin.
        from canonical.codehosting import transport
        # XXX: JonathanLange 2007-05-29: The 'chroot' lines lack unit tests.
        hosted_transport = transport.get_chrooted_transport(hosted_url)
        mirror_transport = transport.get_chrooted_transport(mirror_url)
        lp_server = transport.LaunchpadServer(
            transport.BlockingProxy(branchfs_client), user_id, hosted_transport,
            mirror_transport)
        return lp_server

    def get_smart_server(self, transport, port, inet):
        """Construct a smart server."""
        if inet:
            smart_server = medium.SmartServerPipeStreamMedium(
                sys.stdin, sys.stdout, transport)
        else:
            host = remote.BZR_DEFAULT_INTERFACE
            if port is None:
                port = remote.BZR_DEFAULT_PORT
            else:
                if ':' in port:
                    host, port = port.split(':')
                port = int(port)
            smart_server = server.SmartTCPServer(
                transport, host=host, port=port)
            print 'listening on port: ', smart_server.port
            sys.stdout.flush()
        return smart_server

    def run_server(self, smart_server):
        """Run the given smart server."""
        # for the duration of this server, no UI output is permitted.
        # note that this may cause problems with blackbox tests. This should
        # be changed with care though, as we dont want to use bandwidth
        # sending progress over stderr to smart server clients!
        old_factory = ui.ui_factory
        try:
            ui.ui_factory = ui.SilentUIFactory()
            smart_server.serve()
        finally:
            ui.ui_factory = old_factory

    def run(self, user_id, port=None, upload_directory=None,
            mirror_directory=None, branchfs_endpoint_url=None, inet=False):
        if upload_directory is None:
            upload_directory = config.codehosting.branches_root
        if mirror_directory is None:
            mirror_directory = config.supermirror.branchesdest
        if branchfs_endpoint_url is None:
            branchfs_endpoint_url = config.codehosting.branchfs_endpoint

        upload_url = urlutils.local_path_to_url(upload_directory)
        mirror_url = urlutils.local_path_to_url(mirror_directory)
        branchfs_client = xmlrpclib.ServerProxy(branchfs_endpoint_url)

        lp_server = self.get_lp_server(
            branchfs_client, user_id, upload_url, mirror_url)
        lp_server.setUp()

        old_lockdir_timeout = lockdir._DEFAULT_TIMEOUT_SECONDS
        try:
            lp_transport = get_transport(lp_server.get_url())
            smart_server = self.get_smart_server(lp_transport, port, inet)
            lockdir._DEFAULT_TIMEOUT_SECONDS = 0
            self.run_server(smart_server)
        finally:
            lockdir._DEFAULT_TIMEOUT_SECONDS = old_lockdir_timeout
            lp_server.tearDown()


register_command(cmd_launchpad_server)
