# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test DKIM-signed messages"""

__metaclass__ = type

import logging
import unittest

from StringIO import StringIO

import dkim
import dns.resolver

from zope.component import getUtility

from canonical.launchpad.mail import signed_message_from_string
from canonical.launchpad.mail.incoming import (
    authenticateEmail, )
from canonical.launchpad.interfaces.mail import IWeaklyAuthenticatedPrincipal
from lp.testing import TestCaseWithFactory
from canonical.testing.layers import DatabaseFunctionalLayer


# sample private key made with 'openssl genrsa' and public key using 'openssl
# rsa -pubout'.  Not really the key for canonical.com ;-)
sample_privkey = """\
-----BEGIN RSA PRIVATE KEY-----
MIIBOwIBAAJBANmBe10IgY+u7h3enWTukkqtUD5PR52Tb/mPfjC0QJTocVBq6Za/
PlzfV+Py92VaCak19F4WrbVTK5Gg5tW220MCAwEAAQJAYFUKsD+uMlcFu1D3YNaR
EGYGXjJ6w32jYGJ/P072M3yWOq2S1dvDthI3nRT8MFjZ1wHDAYHrSpfDNJ3v2fvZ
cQIhAPgRPmVYn+TGd59asiqG1SZqh+p+CRYHW7B8BsicG5t3AiEA4HYNOohlgWan
8tKgqLJgUdPFbaHZO1nDyBgvV8hvWZUCIQDDdCq6hYKuKeYUy8w3j7cgJq3ih922
2qNWwdJCfCWQbwIgTY0cBvQnNe0067WQIpj2pG7pkHZR6qqZ9SE+AjNTHX0CIQCI
Mgq55Y9MCq5wqzy141rnxrJxTwK9ABo3IAFMWEov3g==
-----END RSA PRIVATE KEY-----
"""

sample_pubkey = """\
-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBANmBe10IgY+u7h3enWTukkqtUD5PR52T
b/mPfjC0QJTocVBq6Za/PlzfV+Py92VaCak19F4WrbVTK5Gg5tW220MCAwEAAQ==
-----END PUBLIC KEY-----
"""

sample_dns = """\
k=rsa; \
p=MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBANmBe10IgY+u7h3enWTukkqtUD5PR52T\
b/mPfjC0QJTocVBq6Za/PlzfV+Py92VaCak19F4WrbVTK5Gg5tW220MCAwEAAQ=="""


plain_content = """\
From: Foo Bar <foo.bar@canonical.com>
Date: Fri, 1 Apr 2010 00:00:00 +1000
Subject: yet another comment
To: 1@bugs.staging.launchpad.net

  importance critical

Why isn't this fixed yet?"""


class TestDKIM(TestCaseWithFactory):
    """Messages can be strongly authenticated by DKIM."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Login with admin roles as we aren't testing access here.
        TestCaseWithFactory.setUp(self, 'admin@canonical.com')
        self._log_output = StringIO()
        handler = logging.StreamHandler(self._log_output)
        logger = logging.getLogger('mail-authenticate-dkim')
        logger.addHandler(handler)
        self.addCleanup(lambda: logger.removeHandler(handler))
        self.monkeypatch_dns()

    def fake_signing(self, plain_message, canonicalize=None):
        if canonicalize is None:
            canonicalize = (dkim.Relaxed, dkim.Relaxed) 
        dkim_line = dkim.sign(plain_message,
            selector='example', 
            domain='canonical.com',
            privkey=sample_privkey,
            debuglog=self._log_output,
            canonicalize=canonicalize
            )
        assert dkim_line[-1] == '\n'
        return dkim_line + plain_message

    def monkeypatch_dns(self):
        self._dns_responses = {}
        def my_lookup(name):
            try:
                return self._dns_responses[name]
            except KeyError:
                raise dns.resolver.NXDOMAIN()
        orig_dnstxt = dkim.dnstxt
        dkim.dnstxt = my_lookup
        def restore():
            dkim.dnstxt = orig_dnstxt
        self.addCleanup(restore)

    def get_dkim_log(self):
        return self._log_output.getvalue()
    
    def assertStronglyAuthenticated(self, principal, signed_message):
        self.assertTrue(principal.person.preferredemail.email,
            'foo.bar@canonical.com')
        if IWeaklyAuthenticatedPrincipal.providedBy(principal):
            self.fail('expected strong authentication; got weak:\n'
                + self.get_dkim_log() + '\n\n' + signed_message)

    def assertWeaklyAuthenticated(self, principal, signed_message):
        self.assertTrue(principal.person.preferredemail.email,
            'foo.bar@canonical.com')
        if not IWeaklyAuthenticatedPrincipal.providedBy(principal):
            self.fail('expected weak authentication; got strong:\n'
                + self.get_dkim_log() + '\n\n' + signed_message)

    def assertDkimLogContains(self, substring):
        l = self.get_dkim_log()
        if l.find(substring) == -1:
            self.fail("didn't find %r in log: %s" % (substring, l))

    def test_dkim_garbage_pubkey(self):
        signed_message = self.fake_signing(plain_content)
        self._dns_responses['example._domainkey.canonical.com.'] = \
            'aothuaonu'
        principal = authenticateEmail(signed_message_from_string(signed_message),
            signed_message)
        self.assertWeaklyAuthenticated(principal, signed_message)
        self.assertDkimLogContains('invalid format in _domainkey txt record')

    def test_dkim_valid_strict(self):
        signed_message = self.fake_signing(plain_content,
            canonicalize=(dkim.Simple, dkim.Simple))
        self._dns_responses['example._domainkey.canonical.com.'] = \
            sample_dns
        principal = authenticateEmail(signed_message_from_string(signed_message),
            signed_message)
        self.assertStronglyAuthenticated(principal, signed_message)

    def test_dkim_valid(self):
        signed_message = self.fake_signing(plain_content)
        self._dns_responses['example._domainkey.canonical.com.'] = \
            sample_dns
        principal = authenticateEmail(signed_message_from_string(signed_message),
            signed_message)
        self.assertStronglyAuthenticated(principal, signed_message)

    def test_dkim_nxdomain(self):
        # if there's no DNS entry for the pubkey
        # it should be handled decently
        signed_message = self.fake_signing(plain_content)
        principal = authenticateEmail(signed_message_from_string(signed_message),
            signed_message)
        self.assertWeaklyAuthenticated(principal, signed_message)

    def test_dkim_message_unsigned(self):
        # degenerate case: no signature treated as weakly authenticated
        principal = authenticateEmail(signed_message_from_string(plain_content),
            plain_content)
        self.assertWeaklyAuthenticated(principal, plain_content)
        # the library doesn't log anything if there's no header at all

    def test_dkim_body_mismatch(self):
        # The message message has a syntactically valid DKIM signature that
        # doesn't actually correspond to what was signed.  We log something about
        # this but we don't want to drop the message.
        signed_message = self.fake_signing(plain_content)
        signed_message += 'blah blah'
        self._dns_responses['example._domainkey.canonical.com.'] = \
            sample_dns
        principal = authenticateEmail(signed_message_from_string(signed_message),
            signed_message)
        self.assertWeaklyAuthenticated(principal, signed_message)
        self.assertDkimLogContains('body hash mismatch')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
