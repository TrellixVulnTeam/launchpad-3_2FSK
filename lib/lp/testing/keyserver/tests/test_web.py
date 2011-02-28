# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the web resources of the testkeyserver."""

__metaclass__ = type

import os
import shutil

from testtools.deferredruntest import AsynchronousDeferredRunTest

from twisted.internet.endpoints import serverFromString
from twisted.web.client import getPage
from twisted.web.server import Site

from lp.testing import TestCase
from lp.testing.keyserver.harness import KEYS_DIR
from lp.testing.keyserver.web import KeyServerResource
from lp.testing.matchers import DocTestMatches


class TestWebResources(TestCase):

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=2)

    def setUpKeysDirectory(self):
        path = self.makeTemporaryDirectory()
        path = os.path.join(path, 'keys')
        shutil.copytree(KEYS_DIR, path)
        return path

    def makeService(self):
        """Run a test key server on whatever port we have available."""
        from twisted.internet import reactor
        resource = KeyServerResource(self.setUpKeysDirectory())
        site = Site(resource)
        endpoint = serverFromString(reactor, 'tcp:0')
        return endpoint.listen(site)

    def fetchResource(self, listening_port, path):
        """GET the content at 'path' from the web server at 'listening_port'.
        """
        url = 'http://localhost:%s/%s' % (
            listening_port.getHost().port,
            path.lstrip('/'))
        return getPage(url)

    def getURL(self, path):
        """Start a test key server and get the content at 'path'."""
        d = self.makeService()
        def service_started(port):
            self.addCleanup(port.stopListening)
            return self.fetchResource(port, path)
        return d.addCallback(service_started)

    def assertContentMatches(self, path, content):
        """Assert that the key server content at 'path' matches 'content'."""
        d = self.getURL(path)
        return d.addCallback(self.assertThat, DocTestMatches(content))

    def test_index_lookup(self):
        # A key index lookup form via GET.
        return self.assertContentMatches(
            '/pks/lookup?op=index&search=0xDFD20543',
            '''\
<html>
...
<title>Results for Key 0xDFD20543</title>
...
pub  1024D/DFD20543 2005-04-13 Sample Person (revoked) &lt;sample.revoked@canonical.com&gt;
...
''')

    def test_content_lookup(self):
        # A key content lookup form via GET.
        return self.assertContentMatches(
            '/pks/lookup?op=get&'
            'search=0xA419AE861E88BC9E04B9C26FBA2B9389DFD20543',
            '''\
<html>
...
<title>Results for Key 0xA419AE861E88BC9E04B9C26FBA2B9389DFD20543</title>
...
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v1.4.9 (GNU/Linux)
<BLANKLINE>
mQGiBEJdmOcRBADkNJPTBuCIefBdRAhvWyD9SSVHh8GHQWS7l9sRLEsirQkKz1yB
...
''')

    def test_lookup_key_id(self):
        # We can also request a key ID instead of a fingerprint, and it will
        # glob for the fingerprint.
        return self.assertContentMatches(
            '/pks/lookup?op=get&search=0xDFD20543',
            '''\
<html>
...
<title>Results for Key 0xDFD20543</title>
...
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG v1.4.9 (GNU/Linux)
<BLANKLINE>
mQGiBEJdmOcRBADkNJPTBuCIefBdRAhvWyD9SSVHh8GHQWS7l9sRLEsirQkKz1yB
...
''')

    def test_nonexistent_key(self):
        # If we request a nonexistent key, we get a nice error.
        return self.assertContentMatches(
            '/pks/lookup?op=get&search=0xDFD20544',
            '''\
<html>
...
<title>Results for Key 0xDFD20544</title>
...
Key Not Found
...
''')

    def test_add_key(self):
        # A key submit form via POST (see doc/gpghandler.txt for more
        # information).
        return self.assertContentMatches(
            '/pks/add',
            '''\
<html>
...
<title>Submit a key</title>
...
''')
