#!/usr/bin/python
#
# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# arch-tag: f815ad2f-cd34-4399-81a1-c226a949e6b5

import unittest
import sys
from lp.archiveuploader.tests import datadir


class TestSignedFiles(unittest.TestCase):

    def testImport(self):
        """lp.archiveuploader.GPGV should be importable"""
        from lp.archiveuploader.GPGV import verify_signed_file

    def testCheckGoodSignedChanges(self):
        """lp.archiveuploader.GPGV.verify_signed_file should cope with a good
           changes file
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        s = verify_signed_file(datadir("good-signed-changes"),
                               [datadir("pubring.gpg")])
        self.assertEquals(s, "B94E5B41DAA4B3CD521BEBA03AD3DF3EF2D2C028")

    def testCheckBadSignedChangesRaises1(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           TaintedFileNameError
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import TaintedFileNameError
        self.assertRaises(TaintedFileNameError, verify_signed_file, "*", [])
        self.assertRaises(TaintedFileNameError,
                          verify_signed_file, "foo", [], "*")

    def testCheckExpiredSignedChanges(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           SignatureExpiredError
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import SignatureExpiredError
        self.assertRaises(SignatureExpiredError,
                          verify_signed_file,
                          datadir("expired-signed-changes"),
                          [datadir("pubring.gpg")])

    def testCheckRevokedSignedChanges(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           KeyRevokedError
        """
        from lp.archiveuploader.GPGV import verify_signed_file, KeyRevokedError
        self.assertRaises(KeyRevokedError,
                          verify_signed_file,
                          datadir("revoked-signed-changes"),
                          [datadir("pubring.gpg")])

    def testCheckBadSignedChanges(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           BadSignatureError
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import BadSignatureError
        self.assertRaises(BadSignatureError,
                          verify_signed_file,
                          datadir("bad-signed-changes"),
                          [datadir("pubring.gpg")])

    def testCheckNotSignedChanges(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           NoSignatureFoundError
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import NoSignatureFoundError
        self.assertRaises(NoSignatureFoundError,
                          verify_signed_file,
                          datadir("singular-stanza"),
                          [datadir("pubring.gpg")])

    def testCheckPubkeyNotFound(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           NoPublicKeyError
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import NoPublicKeyError
        self.assertRaises(NoPublicKeyError,
                          verify_signed_file,
                          datadir("good-signed-changes"),
                          [datadir("empty-file")])

    def testCheckPubkeyNotFoundDetailsKey(self):
        """lp.archiveuploader.GPGV.verify_signed_file should raise
           NoPublicKeyError with the right key id
        """
        from lp.archiveuploader.GPGV import verify_signed_file
        from lp.archiveuploader.GPGV import NoPublicKeyError
        try:
            verify_signed_file(datadir("good-signed-changes"),
                               [datadir("empty-file")])
        except NoPublicKeyError, err:
            self.assertEquals(err.key, '3AD3DF3EF2D2C028')


def test_suite():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTest(loader.loadTestsFromTestCase(TestSignedFiles))
    return suite


def main(argv):
    suite = test_suite()
    runner = unittest.TextTestRunner(verbosity=2)
    if not runner.run(suite).wasSuccessful():
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
