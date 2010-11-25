# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from doctest import DocTestSuite
import logging
import os
import unittest

import transaction
from zope.security.management import setSecurityPolicy

from canonical.config import config
from canonical.launchpad.ftests import import_secret_test_key
from canonical.launchpad.mail.ftests.helpers import testmails_path
from canonical.launchpad.testing.systemdocs import LayeredDocFileSuite
from canonical.launchpad.webapp.authorization import LaunchpadSecurityPolicy
from canonical.launchpad.mail import (
    authenticateEmail,
    helpers,
    )
from canonical.testing.layers import LaunchpadZopelessLayer
from lp.services.mail.incoming import (
    handleMail,
    MailErrorUtility,
    )
from lp.services.mail.sendmail import MailController
from lp.services.mail.stub import TestMailer
from lp.testing import TestCaseWithFactory
from lp.testing.factory import GPGSigningContext
from lp.testing.mail_helpers import pop_notifications


class TestIncoming(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_invalid_signature(self):
        """Invalid signature should not be handled as an OOPs.

        It should produce a message explaining to the user what went wrong.
        """
        person = self.factory.makePerson()
        transaction.commit()
        email_address = person.preferredemail.email
        invalid_body = (
            '-----BEGIN PGP SIGNED MESSAGE-----\n'
            'Hash: SHA1\n\n'
            'Body\n'
            '-----BEGIN PGP SIGNATURE-----\n'
            'Not a signature.\n'
            '-----END PGP SIGNATURE-----\n')
        ctrl = MailController(
            email_address, 'to@example.com', 'subject', invalid_body,
            bulk=False)
        ctrl.send()
        error_utility = MailErrorUtility()
        old_oops = error_utility.getLastOopsReport()
        handleMail()
        current_oops = error_utility.getLastOopsReport()
        if old_oops is None:
            self.assertIs(None, current_oops)
        else:
            self.assertEqual(old_oops.id, current_oops.id)
        [notification] = pop_notifications()
        body = notification.get_payload()[0].get_payload(decode=True)
        self.assertIn(
            "An error occurred while processing a mail you sent to "
            "Launchpad's email\ninterface.\n\n\n"
            "Error message:\n\nSignature couldn't be verified: No data",
            body)

    def test_invalid_to_addresses(self):
        """Invalid To: header should not be handled as an OOPS."""
        raw_mail = open(os.path.join(
            testmails_path, 'invalid-to-header.txt')).read()
        # Due to the way handleMail works, even if we pass a valid To header
        # to the TestMailer, as we're doing here, it falls back to parse all
        # To and CC headers from the raw_mail. Also, TestMailer is used here
        # because MailController won't send an email with a broken To: header.
        TestMailer().send("from@example.com", "to@example.com", raw_mail)
        error_utility = MailErrorUtility()
        old_oops = error_utility.getLastOopsReport()
        handleMail()
        current_oops = error_utility.getLastOopsReport()
        if old_oops is None:
            self.assertIs(None, current_oops)
        else:
            self.assertEqual(old_oops.id, current_oops.id)

    def test_bad_signature_timestamp(self):
        """If the signature is nontrivial future-dated, it's not trusted."""

        signing_context = GPGSigningContext(
            import_secret_test_key().fingerprint, password='test')
        msg = self.factory.makeSignedMessage(signing_context=signing_context)
        # It's not trivial to make a gpg signature with a bogus timestamp, so
        # let's just treat everything as invalid, and trust that the regular
        # implementation of extraction and checking of timestamps is correct,
        # or at least tested.
        def fail_all_timestamps(timestamp, context):
            raise helpers.IncomingEmailError("fail!")
        self.assertRaises(
            helpers.IncomingEmailError,
            authenticateEmail,
            msg, fail_all_timestamps)


def setUp(test):
    test._old_policy = setSecurityPolicy(LaunchpadSecurityPolicy)
    LaunchpadZopelessLayer.switchDbUser(config.processmail.dbuser)


def tearDown(test):
    setSecurityPolicy(test._old_policy)


def test_suite():
    suite = unittest.TestLoader().loadTestsFromName(__name__)
    suite.addTest(DocTestSuite('lp.services.mail.incoming'))
    suite.addTest(
        LayeredDocFileSuite(
            'incomingmail.txt',
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadZopelessLayer,
            stdout_logging_level=logging.WARNING))
    return suite
