# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal codehosting API."""

__metaclass__ = type

from pymacaroons import Macaroon
from storm.sqlobject import SQLObjectNotFound
from testtools.matchers import Is
from zope.component import getUtility
from zope.interface import implementer
from zope.publisher.xmlrpc import TestRequest

from lp.services.authserver.xmlrpc import AuthServerAPIView
from lp.services.config import config
from lp.services.librarian.interfaces import (
    ILibraryFileAlias,
    ILibraryFileAliasSet,
    )
from lp.services.macaroons.interfaces import IMacaroonIssuer
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.testing import (
    person_logged_in,
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    ZopelessDatabaseLayer,
    )
from lp.xmlrpc import faults
from lp.xmlrpc.interfaces import IPrivateApplication


class GetUserAndSSHKeysTests(TestCaseWithFactory):
    """Tests for the implementation of `IAuthServer.getUserAndSSHKeys`.
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        private_root = getUtility(IPrivateApplication)
        self.authserver = AuthServerAPIView(
            private_root.authserver, TestRequest())

    def test_user_not_found(self):
        # getUserAndSSHKeys returns the NoSuchPersonWithName fault if there is
        # no Person of the given name.
        self.assertEqual(
            faults.NoSuchPersonWithName('no-one'),
            self.authserver.getUserAndSSHKeys('no-one'))

    def test_user_no_keys(self):
        # getUserAndSSHKeys returns a dict with keys ['id', 'name', 'keys'].
        # 'keys' refers to a list of SSH public keys in LP, which is empty for
        # a freshly created user.
        new_person = self.factory.makePerson()
        self.assertEqual(
            dict(id=new_person.id, name=new_person.name, keys=[]),
            self.authserver.getUserAndSSHKeys(new_person.name))

    def test_user_with_keys(self):
        # For a user with registered SSH keys, getUserAndSSHKeys returns the
        # name of the key type (RSA or DSA) and the text of the keys under
        # 'keys' in the dict.
        new_person = self.factory.makePerson()
        with person_logged_in(new_person):
            key = self.factory.makeSSHKey(person=new_person)
            self.assertEqual(
                dict(id=new_person.id, name=new_person.name,
                     keys=[(key.keytype.title, key.keytext)]),
                self.authserver.getUserAndSSHKeys(new_person.name))


@implementer(IMacaroonIssuer)
class DummyMacaroonIssuer(MacaroonIssuerBase):

    identifier = 'test'
    _root_secret = 'test'

    def checkIssuingContext(self, context):
        """See `MacaroonIssuerBase`."""
        if not ILibraryFileAlias.providedBy(context):
            raise ValueError("Cannot handle context %r." % context)
        return context.id

    def checkVerificationContext(self, context):
        """See `IMacaroonIssuerBase`."""
        if not ILibraryFileAlias.providedBy(context):
            raise ValueError("Cannot handle context %r." % context)
        return context

    def verifyPrimaryCaveat(self, caveat_value, context):
        """See `MacaroonIssuerBase`."""
        return caveat_value == str(context.id)


class VerifyMacaroonTests(TestCase):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(VerifyMacaroonTests, self).setUp()
        self.issuer = DummyMacaroonIssuer()
        self.useFixture(ZopeUtilityFixture(
            self.issuer, IMacaroonIssuer, name='test'))
        private_root = getUtility(IPrivateApplication)
        self.authserver = AuthServerAPIView(
            private_root.authserver, TestRequest())

    def test_nonsense_macaroon(self):
        self.assertEqual(
            faults.Unauthorized(),
            self.authserver.verifyMacaroon('nonsense', 'LibraryFileAlias', 1))

    def test_unknown_issuer(self):
        macaroon = Macaroon(
            location=config.vhost.mainsite.hostname,
            identifier='unknown-issuer', key='test')
        self.assertEqual(
            faults.Unauthorized(),
            self.authserver.verifyMacaroon(
                macaroon.serialize(), 'LibraryFileAlias', 1))

    def test_wrong_context_type(self):
        lfa = getUtility(ILibraryFileAliasSet)[1]
        macaroon = self.issuer.issueMacaroon(lfa)
        self.assertEqual(
            faults.Unauthorized(),
            self.authserver.verifyMacaroon(
                macaroon.serialize(), 'nonsense', lfa.id))

    def test_wrong_context(self):
        lfa = getUtility(ILibraryFileAliasSet)[1]
        macaroon = self.issuer.issueMacaroon(lfa)
        self.assertEqual(
            faults.Unauthorized(),
            self.authserver.verifyMacaroon(
                macaroon.serialize(), 'LibraryFileAlias', 2))

    def test_nonexistent_lfa(self):
        macaroon = self.issuer.issueMacaroon(
            getUtility(ILibraryFileAliasSet)[1])
        # Pick a large ID that doesn't exist in sampledata.
        lfa_id = 1000000
        self.assertRaises(
            SQLObjectNotFound, getUtility(ILibraryFileAliasSet).__getitem__,
            lfa_id)
        self.assertEqual(
            faults.Unauthorized(),
            self.authserver.verifyMacaroon(
                macaroon.serialize(), 'LibraryFileAlias', lfa_id))

    def test_success(self):
        lfa = getUtility(ILibraryFileAliasSet)[1]
        macaroon = self.issuer.issueMacaroon(lfa)
        self.assertThat(
            self.authserver.verifyMacaroon(
                macaroon.serialize(), 'LibraryFileAlias', lfa.id),
            Is(True))
