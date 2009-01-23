# Copyright 2008 Canonical Ltd.  All rights reserved.

"""ArchiveSigningKey implementation."""

__metaclass__ = type

__all__ = [
    'ArchiveSigningKey',
    ]


import os

import gpgme

from zope.component import getUtility
from zope.interface import implements

from canonical.config import config
from canonical.launchpad.interfaces.archivesigningkey import (
    IArchiveSigningKey)
from canonical.launchpad.interfaces.gpghandler import IGPGHandler
from canonical.launchpad.interfaces.gpg import IGPGKeySet, GPGKeyAlgorithm
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities


class ArchiveSigningKey:
    """`IArchive` adapter for manipulating its GPG key."""

    implements(IArchiveSigningKey)

    def __init__(self, archive):
        self.archive = archive

    @property
    def _archive_root_path(self):
        # XXX cprov 20081104: IArchive pub configuration doesn't implement
        # any interface.
        from zope.security.proxy import removeSecurityProxy
        naked_pub_config = removeSecurityProxy(self.archive.getPubConfig())
        return naked_pub_config.archiveroot

    def getPathForSecretKey(self, key):
        """See `IArchiveSigningKey`."""
        return os.path.join(
            config.personalpackagearchive.signing_keys_root,
            "%s.gpg" % key.fingerprint)

    def exportSecretKey(self, key):
        """See `IArchiveSigningKey`."""
        assert key.secret, "Only secret keys should be exported."
        export_path = self.getPathForSecretKey(key)

        if not os.path.exists(os.path.dirname(export_path)):
            os.makedirs(os.path.dirname(export_path))

        export_file = open(export_path, 'w')
        export_file.write(key.export())
        export_file.close()

    def generateSigningKey(self):
        """See `IArchiveSigningKey`."""
        assert self.archive.signing_key is None, (
            "Cannot override signing_keys.")

        key_displayname = "Launchpad %s" % self.archive.title
        secret_key = getUtility(IGPGHandler).generateKey(key_displayname)
        self._setupSigningKey(secret_key)

    def setSigningKey(self, key_path):
        """See `IArchiveSigningKey`."""
        assert self.archive.signing_key is None, (
            "Cannot override signing_keys.")
        assert os.path.exists(key_path), (
            "%s does not exist" % key_path)

        secret_key = getUtility(IGPGHandler).importSecretKey(
            open(key_path).read())
        self._setupSigningKey(secret_key)

    def _setupSigningKey(self, secret_key):
        """Mandatory setup for signing keys.

        * Export the secret key into the protected disk location.
        * Upload public key to the keyserver.
        * Store the public GPGKey reference in the database and update
          the context archive.signing_key.
        """
        self.exportSecretKey(secret_key)

        gpghandler = getUtility(IGPGHandler)
        pub_key = gpghandler.retrieveKey(secret_key.fingerprint)
        gpghandler.uploadPublicKey(pub_key.fingerprint)

        algorithm = GPGKeyAlgorithm.items[pub_key.algorithm]
        key_owner = getUtility(ILaunchpadCelebrities).ppa_key_guard
        self.archive.signing_key = getUtility(IGPGKeySet).new(
            key_owner, pub_key.keyid, pub_key.fingerprint, pub_key.keysize,
            algorithm, active=True, can_encrypt=pub_key.can_encrypt)

    def signRepository(self, suite):
        """See `IArchiveSigningKey`."""
        assert self.archive.signing_key is not None, (
            "No signing key available for %s" % self.archive.title)

        suite_path = os.path.join(self._archive_root_path, 'dists', suite)
        release_file_path = os.path.join(suite_path, 'Release')
        assert os.path.exists(release_file_path), (
            "Release file doesn't exist in the repository: %s"
            % release_file_path)

        secret_key_export = open(
            self.getPathForSecretKey(self.archive.signing_key)).read()

        gpghandler = getUtility(IGPGHandler)
        secret_key = gpghandler.importSecretKey(secret_key_export)

        release_file_content = open(release_file_path).read()
        signature = gpghandler.signContent(
            release_file_content, secret_key.fingerprint,
            mode=gpgme.SIG_MODE_DETACH)

        release_signature_file = open(
            os.path.join(suite_path, 'Release.gpg'), 'w')
        release_signature_file.write(signature)
        release_signature_file.close()
