# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

from zope.interface import (
    Attribute,
    Interface,
    )


__all__ = [
    'GPGKeyExpired',
    'GPGKeyRevoked',
    'GPGKeyNotFoundError',
    'GPGUploadFailure',
    'GPGVerificationError',
    'IGPGHandler',
    'IPymeSignature',
    'IPymeKey',
    'IPymeUserId',
    'MoreThanOneGPGKeyFound',
    'SecretGPGKeyImportDetected',
    ]


class MoreThanOneGPGKeyFound(Exception):
    """More than one GPG key was found.

    And we don't know which one to import.
    """


class GPGKeyNotFoundError(Exception):
    """The given GPG key was not found in the keyserver."""

    def __init__(self, fingerprint, pubkey=None):
        self.fingerprint = fingerprint
        self.pubkey = pubkey
        super(GPGKeyNotFoundError, self).__init__(
            "No GPG key found with the given content: %s" % (fingerprint, ))


class GPGKeyRevoked(Exception):
    """The given GPG key was revoked."""

    def __init__(self, key):
        self.key = key
        super(GPGKeyRevoked, self).__init__(
            "%s has been publicly revoked" % (key.keyid, ))


class GPGKeyExpired(Exception):
    """The given GPG key has expired."""

    def __init__(self, key):
        self.key = key
        super(GPGKeyExpired, self).__init__("%s has expired" % (key.keyid, ))


class SecretGPGKeyImportDetected(Exception):
    """An attempt to import a secret GPG key."""


class GPGUploadFailure(Exception):
    """Raised when a key upload failed.

    Typically when a keyserver is not reachable.
    """


class GPGVerificationError(Exception):
    """OpenPGP verification error."""


class IGPGHandler(Interface):
    """Handler to perform OpenPGP operations."""

    def sanitizeFingerprint(fingerprint):
        """Return sanitized fingerprint if well-formed.

        If the firgerprint cannot be sanitized return None.
        """

    def verifySignature(content, signature=None):
        """See `getVerifiedSignature`.

        Suppress all exceptions and simply return None if the could not
        be verified.
        """

    def getURLForKeyInServer(fingerprint, action=None, public=False):
        """Return the URL for that fingerprint on the configured keyserver.

        If public is True, return a URL for the public keyserver; otherwise,
        references the default (internal) keyserver.
        If action is provided, will attach that to the URL.
        """

    def getVerifiedSignatureResilient(content, signature=None):
        """Wrapper for getVerifiedSignature.

        It calls the target method exactly 3 times.

        Return the result if it succeed during the cycle, otherwise
        capture the errors and emits at the end GPGVerificationError
        with the stored error information.
        """

    def getVerifiedSignature(content, signature=None):
        """Returns a PymeSignature object if content is correctly signed.

        If signature is None, we assume content is clearsigned. Otherwise
        it stores the detached signature and content should contain the
        plain text in question.

        content and signature must be 8-bit encoded str objects. It's up to
        the caller to encode or decode as appropriate.

        The only exception likely to be propogated out is GPGVerificationError

        :param content: The content to be verified as string;
        :param signature: The signature as string (or None if content is
            clearsigned)

        :raise GPGVerificationError: if the signature cannot be verified.
        :return: a `PymeSignature` object.
        """

    def importPublicKey(content):
        """Import the given public key into our local keyring.

        If the secret key's ASCII armored content is given,
        SecretGPGKeyDetected is raised.

        If no key is found, GPGKeyNotFoundError is raised.  On the other
        hand, if more than one key is found, MoreThanOneGPGKeyFound is
        raised.

        :param content: public key ASCII armored content (must be an ASCII
            string (it's up to the caller to encode or decode properly);
        :return: a `PymeKey` object referring to the public key imported.
        """

    def importSecretKey(content):
        """Import the given secret key into our local keyring.

        If no key is found, GPGKeyNotFoundError is raised.  On the other
        hand, if more than one key is found, MoreThanOneGPGKeyFound is
        raised.

        :param content: secret key ASCII armored content (must be an ASCII
            string (it's up to the caller to encode or decode properly);
        :return: a `PymeKey` object referring to the secret key imported.
        """

    def generateKey(name):
        """Generate a new GPG key with the given name.

        Currently only passwordless, signo-only 1024-bit RSA keys are
        generated.

        :param name: unicode to be included in the key paramenters, 'comment'
            and 'email' will be empty. It's content will be encoded to
            'utf-8' internally.
        :raise AssertionError: if the key generation is not exaclty what
            we expect.

        :return: a `PymeKey` object for the just-generated secret key.
        """

    def importKeyringFile(filepath):
        """Import the keyring filepath into the local key database.

        :param filepath: the path to a keyring to import.

        :returns: a list of the imported keys.
        """

    def encryptContent(content, fingerprint):
        """Encrypt the given content for the given fingerprint.

        content must be a traditional string. It's up to the caller to
        encode or decode properly. Fingerprint must be hexadecimal string.

        :param content: the Unicode content to be encrypted.
        :param fingerprint: the OpenPGP key's fingerprint.

        :return: the encrypted content or None if failed.
        """

    def signContent(content, key_fingerprint, password='', mode=None):
        """Signs content with a given GPG fingerprint.

        :param content: the content to sign.
        :param key_fingerprint: the fingerprint of the key to use when
            signing the content.
        :param password: optional password to the key identified by
            key_fingerprint, the default value is '',
        :param mode: optional he type of GPG signature to produce, the
            default mode is gpgme.SIG_MODE_CLEAR (clearsigned signatures)

        :return: The ASCII-armored signature for the content.
        """

    def retrieveKey(fingerprint):
        """Retrieve the key information from the local keyring.

        If the key with the given fingerprint is not present in the local
        keyring, first import it from the key server into the local keyring.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGKeyNotFoundError: if the key is not found neither in the
            local keyring nor in the key server.
        :return: a `PymeKey`object containing the key information.
        """

    def retrieveActiveKey(fingerprint):
        """Retrieve key information, raise errors if the key is not active.

        Exactly like `retrieveKey` except raises errors if the key is expired
        or has been revoked.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGKeyNotFoundError: if the key is not found neither in the
            local keyring nor in the key server.
        :return: a `PymeKey`object containing the key information.
        """

    def uploadPublicKey(fingerprint):
        """Upload the specified public key to a keyserver.

        Use `retrieveKey` to get the public key content and upload an
        ASCII-armored export chunk.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGUploadFailure: if the keyserver could not be reaches.
        :raise AssertionError: if the POST request doesn't succeed.
        """

    def checkTrustDb():
        """Check whether the OpenPGP trust database is up to date.

        The method automatically rebuild the trust values if necessary.

        The results will be visible in any new retrieved key objects.
        Existing key objects will not reflect the new trust value.
        """

    def localKeys(filter=None, secret=False):
        """Return an iterator of all keys locally known about.

        :param filter: optional string used to filter the results. By default
            gpgme tries to match '<name> [comment] [email]', the full
            fingerprint or the key ID (fingerprint last 8 digits);
        :param secret: optional boolean, restrict the domain to secret or
            public keys available in the keyring. Defaults to False.

        :return: a `PymeKey` generator with the matching keys.
        """

    def resetLocalState():
        """Reset the local state.

        Resets OpenPGP keyrings and trust database.
        """
        #FIXME RBC: this should be a zope test cleanup thing per SteveA.


class IPymeSignature(Interface):
    """pyME signature container."""

    fingerprint = Attribute("Signer Fingerprint.")
    plain_data = Attribute("Plain Signed Text.")
    timestamp = Attribute("The time at which the message was signed.")


class IPymeKey(Interface):
    """pyME key model."""

    fingerprint = Attribute("Key Fingerprint")
    algorithm = Attribute("Key Algorithm")
    revoked = Attribute("Key Revoked")
    expired = Attribute("Key Expired")
    secret = Attribute("Whether the key is secret of not.")
    keysize = Attribute("Key Size")
    keyid = Attribute("Pseudo Key ID, composed by last fingerprint 8 digits ")
    uids = Attribute("List of user IDs associated with this key")
    emails = Attribute(
        "List containing only well formed and non-revoked emails")
    displayname = Attribute("Key displayname: <size><type>/<keyid>")
    owner_trust = Attribute("The owner trust")

    can_encrypt = Attribute("Whether the key can be used for encrypting")
    can_sign = Attribute("Whether the key can be used for signing")
    can_certify = Attribute("Whether the key can be used for certification")
    can_authenticate = Attribute(
        "Whether the key can be used for authentication")

    def setOwnerTrust(value):
        """Set the owner_trust value for this key."""

    def export():
        """Export the context key in ASCII-armored mode.

        Both public and secret keys are supported, although secret keys are
        exported by calling `gpg` process while public ones use the native
        gpgme API.

        :return: a string containing the exported key.
        """


class IPymeUserId(Interface):
    """pyME user ID"""

    revoked = Attribute("True if the user ID has been revoked")
    invalid = Attribute("True if the user ID is invalid")
    validity = Attribute("""A measure of the validity of the user ID,
                         based on owner trust values and signatures.""")
    uid = Attribute("A string identifying this user ID")
    name = Attribute("The name portion of this user ID")
    email = Attribute("The email portion of this user ID")
    comment = Attribute("The comment portion of this user ID")
