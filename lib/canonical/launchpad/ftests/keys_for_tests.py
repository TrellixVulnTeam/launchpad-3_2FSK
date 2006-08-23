# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""OpenPGP keys used for testing.

There are two GPG keys located in the 'gpgkeys' sub directory, one for
Sample Person and for Foo Bar. The passwords for the secret keys are
'test'.

Before they are used in tests they need to be imported, so that
GpgHandler knows about them.  import_public_test_keys() imports all
public keys available, while import_public_key(email_addr) only imports
the key associated with that specific email address.

Secret keys are also imported into the local key ring, they are used for
decrypt data in pagetests.
"""


__metaclass__ = type

import os
from cStringIO import StringIO

from zope.component import getUtility

import gpgme

from canonical.lp.dbschema import GPGKeyAlgorithm
from canonical.launchpad.interfaces import IGPGKeySet, IGPGHandler, IPersonSet

gpgkeysdir = os.path.join(os.path.dirname(__file__), 'gpgkeys')

def import_public_key(email_addr):
    """Imports the public key related to the given email address."""
    gpghandler = getUtility(IGPGHandler)
    personset = getUtility(IPersonSet)

    pubkey = test_pubkey_from_email(email_addr)
    key = gpghandler.importPubKey(pubkey)

    # Some of the keys shouldn't be inserted into the db.
    if email_addr.endswith('do-not-insert-into-db'):
        return

    person = personset.getByEmail(email_addr)

    # Some of the sample keys do not have corresponding Launchpad
    # users, so ignore them.
    if not person:
        return

    for gpgkey in person.gpgkeys:
        if gpgkey.fingerprint == key.fingerprint:
            # If the key's already added to the database, do nothing.
            return
        
    # Insert the key into the database.
    getUtility(IGPGKeySet).new(
        ownerID=personset.getByEmail(email_addr).id,
        keyid=key.keyid,
        fingerprint=key.fingerprint,
        keysize=key.keysize,
        algorithm=GPGKeyAlgorithm.items[key.algorithm],
        active=(not key.revoked))

def iter_test_key_emails():
    """Iterates over the email addresses for the keys in the gpgkeysdir."""
    for name in os.listdir(gpgkeysdir):
        if name.endswith('.pub'):
            yield name[:-4]

def import_public_test_keys():
    """Imports all the public keys located in gpgkeysdir into the db."""
    for email in iter_test_key_emails():
        import_public_key(email)

def import_secret_test_key():
    """Imports the secret key located in gpgkeysdir into local keyring."""
    gpghandler = getUtility(IGPGHandler)

    seckey = open(os.path.join(gpgkeysdir, 'test@canonical.com.sec')).read()
    context = gpgme.Context()
    context.armor = True
    newkey = StringIO(seckey)
    result = context.import_(newkey)

def test_pubkey_file_from_email(email_addr):
    """Get the file name for a test pubkey by email address."""
    return os.path.join(gpgkeysdir, email_addr + '.pub')

def test_pubkey_from_email(email_addr):
    """Get the on disk content for a test pubkey by email address."""
    return open(test_pubkey_file_from_email(email_addr)).read()

def test_keyrings():
    """Iterate over the filenames for test keyrings."""
    for name in os.listdir(gpgkeysdir):
        if name.endswith('.gpg'):
            yield os.path.join(gpgkeysdir, name)

def decrypt_content(content, password):
    """Return the decrypted content or None if failed

    content and password must be traditional strings. It's up to
    the caller to encode or decode properly. 

    :content: encrypted data content
    :password: unicode password to unlock the secret key in question 
    """
    if isinstance(password, unicode):
        raise TypeError('Password cannot be Unicode.')

    if isinstance(content, unicode):
        raise TypeError('Content cannot be Unicode.')

    # setup context
    ctx = gpgme.Context()
    ctx.armor = True

    # setup containers
    cipher = StringIO(content)
    plain = StringIO()

    def passphrase_cb(uid_hint, passphrase_info, prev_was_bad, fd):
        os.write(fd, '%s\n' % password)

    ctx.passphrase_cb = passphrase_cb

    # Do the deecryption.
    try:
        ctx.decrypt(cipher, plain)
    except gpgme.GpgmeError:
        return None

    return plain.getvalue()

