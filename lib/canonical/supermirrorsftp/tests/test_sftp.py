# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""Tests for Supermirror SFTP server's bzr support.
"""

__metaclass__ = type

import os
import unittest
import stat
import struct
import sys
import traceback

from zope.interface import implements

from bzrlib.errors import NoSuchFile, PermissionDenied
from bzrlib.transport import get_transport

from twisted.cred.error import UnauthorizedLogin
from twisted.cred.portal import IRealm, Portal

from twisted.conch.checkers import SSHPublicKeyDatabase
from twisted.conch.ssh.transport import SSHServerTransport
from twisted.conch.ssh import keys, userauth
from twisted.conch.ssh.common import getNS, NS

from twisted.python import failure

from twisted.trial.unittest import TestCase as TrialTestCase

from canonical.config import config
from canonical.supermirrorsftp import sftponly
from canonical.supermirrorsftp.tests.test_acceptance import (
    SFTPTestCase, deferToThread, TestSFTPService)
from canonical.testing import TwistedLayer


class SFTPTests(SFTPTestCase):
    layer = TwistedLayer

    @deferToThread
    def _test_rmdir_branch(self):
        # Make some directories under ~testuser/+junk (i.e. create some empty
        # branches)
        transport = get_transport(self.server_base + '~testuser/+junk')
        transport.mkdir('foo')
        transport.mkdir('bar')
        self.failUnless(stat.S_ISDIR(transport.stat('foo').st_mode))
        self.failUnless(stat.S_ISDIR(transport.stat('bar').st_mode))

        # Try to remove a branch directory, which is not allowed.
        e = self.assertRaises(PermissionDenied, transport.rmdir, 'foo')
        self.failUnless(
            "removing branch directory 'foo' is not allowed." in str(e), str(e))

        # The 'foo' directory is still listed.
        self.failUnlessEqual(['bar', 'foo'], sorted(transport.list_dir('.')))

    def test_rmdir_branch(self):
        return self._test_rmdir_branch()

    @deferToThread
    def _test_mkdir_toplevel_error(self):
        # You cannot create a top-level directory.
        transport = get_transport(self.server_base)
        e = self.assertRaises(PermissionDenied, transport.mkdir, 'foo')
        self.failUnless(
            "Branches must be inside a person or team directory." in str(e),
            str(e))

    def test_mkdir_toplevel_error(self):
        return self._test_mkdir_toplevel_error()

    @deferToThread
    def _test_mkdir_invalid_product_error(self):
        # Make some directories under ~testuser/+junk (i.e. create some empty
        # branches)
        transport = get_transport(self.server_base + '~testuser')

        # You cannot create a product directory unless the product name is
        # registered in Launchpad.
        e = self.assertRaises(PermissionDenied,
                transport.mkdir, 'no-such-product')
        self.failUnless(
            "Directories directly under a user directory must be named after a "
            "product name registered in Launchpad" in str(e),
            str(e))

    def test_mkdir_invalid_product_error(self):
        return self._test_mkdir_invalid_product_error()

    @deferToThread
    def _test_mkdir_not_team_member_error(self):
        # You can't mkdir in a team directory unless you're a member of that
        # team (in fact, you can't even see the directory).
        transport = get_transport(self.server_base)
        e = self.assertRaises(NoSuchFile,
                transport.mkdir, '~not-my-team/mozilla-firefox')
        self.failUnless("~not-my-team" in str(e))

    def test_mkdir_not_team_member_error(self):
        return self._test_mkdir_not_team_member_error()

    @deferToThread
    def _test_mkdir_team_member(self):
        # You can mkdir in a team directory that you're a member of (so long as
        # it's a real product), though.
        transport = get_transport(self.server_base)
        transport.mkdir('~testteam/firefox')

        # Confirm the mkdir worked by using list_dir.
        self.failUnless('firefox' in transport.list_dir('~testteam'))

        # You can of course mkdir a branch, too
        transport.mkdir('~testteam/firefox/shiny-new-thing')
        self.failUnless(
            'shiny-new-thing' in transport.list_dir('~testteam/firefox'))
        transport.mkdir('~testteam/firefox/shiny-new-thing/.bzr')

    def test_mkdir_team_member(self):
        return self._test_mkdir_team_member()


class MockRealm:
    implements(IRealm)

    def requestAvatar(self, avatar, mind, *interfaces):
        raise NotImplementedError("This should not be called")


class MockSSHTransport(SSHServerTransport):
    def __init__(self, portal):
        self.packets = []
        class Factory:
            pass
        self.factory = Factory()
        self.factory.portal = portal

    def sendPacket(self, messageType, payload):
        self.packets.append((messageType, payload))


class UserAuthServerMixin:
    def setUp(self):
        self.portal = Portal(MockRealm())
        self.transport = MockSSHTransport(self.portal)
        self.user_auth = sftponly.SSHUserAuthServer(self.transport)


class TestUserAuthServer(UserAuthServerMixin, unittest.TestCase):

    def test_sendBanner(self):
        # sendBanner should send an SSH 'packet' with type MSG_USERAUTH_BANNER
        # and two fields. The first field is the message itself, and the second
        # is the language tag.
        #
        # sendBanner automatically adds a trailing newline, because openssh and
        # Twisted don't add one when displaying the banner.
        #
        # See RFC 4252, Section 5.4.
        message = u"test message"
        self.user_auth.sendBanner(message, language='en-US')
        [(messageType, payload)] = self.transport.packets
        self.assertEqual(messageType, userauth.MSG_USERAUTH_BANNER)
        bytes, language, empty = getNS(payload, 2)
        self.assertEqual(bytes.decode('UTF8'), message + '\r\n')
        self.assertEqual('en-US', language)
        self.assertEqual('', empty)

    def test_sendBannerUsesCRLF(self):
        # sendBanner should make sure that any line breaks in the message are
        # sent as CR LF pairs.
        #
        # See RFC 4252, Section 5.4.
        self.user_auth.sendBanner(u"test\nmessage")
        [(messageType, payload)] = self.transport.packets
        bytes, language, empty = getNS(payload, 2)
        self.assertEqual(bytes.decode('UTF8'), u"test\r\nmessage\r\n")


class MockChecker(SSHPublicKeyDatabase):
    error_message = u'error message'

    def requestAvatarId(self, credentials):
        return failure.Failure(UnauthorizedLogin('error message'))


class TestAuthenticationErrors(UserAuthServerMixin, TrialTestCase):
    layer = TwistedLayer

    def setUp(self):
        UserAuthServerMixin.setUp(self)
        self.portal.registerChecker(MockChecker())
        self.user_auth.serviceStarted()
        self.key_data = self._makeKey()

    def _makeKey(self):
        keydir = config.supermirrorsftp.host_key_pair_path
        public_key = keys.getPublicKeyString(
            data=open(os.path.join(keydir,
                                   'ssh_host_key_rsa.pub'), 'rb').read())
        return chr(0) + NS('rsa') + NS(public_key)

    def test_loggedToBanner(self):
        # When there's an authentication failure, we display an informative
        # error message through the SSH authentication protocol 'banner'.
        d = self.user_auth.ssh_USERAUTH_REQUEST(
            NS('jml') + NS('') + NS('publickey') + self.key_data)

        def check(ignored):
            # Check that we received a BANNER, then a FAILURE.
            self.assertEqual(
                list(zip(*self.transport.packets)[0]),
                [userauth.MSG_USERAUTH_BANNER, userauth.MSG_USERAUTH_FAILURE])
            # Check that the banner message is informative.
            bytes, language, empty = getNS(self.transport.packets[0][1], 2)
            self.assertEqual(bytes.decode('UTF8'),
                             MockChecker.error_message + u'\r\n')
        return d.addCallback(check)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
