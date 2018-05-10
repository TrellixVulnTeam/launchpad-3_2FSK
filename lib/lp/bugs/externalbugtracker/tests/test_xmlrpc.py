# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `lp.bugs.externalbugtracker.xmlrpc`."""

__metaclass__ = type

import socket
from urllib2 import URLError
from xml.parsers.expat import ExpatError

from fixtures import MockPatch

from lp.bugs.externalbugtracker.xmlrpc import UrlLib2Transport
from lp.bugs.tests.externalbugtracker import (
    ensure_response_parser_is_expat,
    UrlLib2TransportTestHandler,
    )
from lp.testing import TestCase


class TestUrlLib2Transport(TestCase):
    """Tests for `UrlLib2Transport`."""

    def test_expat_error(self):
        # Malformed XML-RPC responses cause xmlrpclib to raise an ExpatError.
        handler = UrlLib2TransportTestHandler()
        handler.setResponse("<params><mis></match></params>")
        transport = UrlLib2Transport("http://not.real/")
        transport.opener.add_handler(handler)

        # The Launchpad production environment selects Expat at present. This
        # is quite strict compared to the other parsers that xmlrpclib can
        # possibly select.
        ensure_response_parser_is_expat(transport)

        self.assertRaises(
            ExpatError, transport.request,
            'www.example.com', 'xmlrpc', "<methodCall />")

    def test_unicode_url(self):
        # Python's httplib doesn't like Unicode URLs much. Ensure that
        # they don't cause it to crash, and we get a post-serialisation
        # connection error instead.
        self.useFixture(MockPatch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror(
                socket.EAI_NONAME, "Name or service not known")))
        transport = UrlLib2Transport(u"http://test.invalid/")
        self.assertRaisesWithContent(
            URLError, '<urlopen error [Errno -2] Name or service not known>',
            transport.request, u"test.invalid", u"xmlrpc",
            u"\N{SNOWMAN}".encode('utf-8'))
