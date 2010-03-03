# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""OpenPGP key interfaces."""

__metaclass__ = type

__all__ = [
    'IGPGKey',
    'IGPGKeySet',
    'GPGKeyAlgorithm',
    'valid_keyid',
    'valid_fingerprint',
    ]


import re

from zope.schema import Bool, Int, TextLine, Choice
from zope.interface import Interface, Attribute, implementer
from zope.component import adapts

from lazr.enum import DBEnumeratedType, DBItem

from canonical.launchpad import _
from lp.registry.interfaces.role import IHasOwner
from lazr.restful.declarations import (
    collection_default_content, export_as_webservice_collection,
    export_as_webservice_entry, export_read_operation, exported,
    operation_parameters, operation_returns_collection_of)

def valid_fingerprint(fingerprint):
    """Is the fingerprint of valid form."""
    # Fingerprints of v3 keys are md5, fingerprints of v4 keys are sha1;
    # accordingly, fingerprints of v3 keys are 128 bit, those of v4 keys
    # 160. Check therefore for strings of hex characters that are 32
    # (4 * 32 == 128) or 40 characters long (4 * 40 = 160).
    if len(fingerprint) not in (32, 40):
        return False
    if re.match(r"^[\dA-F]+$", fingerprint) is None:
        return False
    return True


def valid_keyid(keyid):
    """Is the key of valid form."""
    if re.match(r"^[\dA-F]{8}$", keyid) is not None:
        return True
    else:
        return False


# XXX: cprov 2004-10-04:
# (gpg+dbschema) the data structure should be rearranged to support 4 field
# needed: keynumber(1,16,17,20), keyalias(R,g,D,G), title and description
class GPGKeyAlgorithm(DBEnumeratedType):
    """
    GPG Compliant Key Algorithms Types:

    1 : "R", # RSA
    16: "g", # ElGamal
    17: "D", # DSA
    20: "G", # ElGamal, compromised

    FIXME
    Rewrite it according the experimental API retuning also a name attribute
    tested on 'algorithmname' attribute

    """

    R = DBItem(1, """
        R

        RSA""")

    LITTLE_G = DBItem(16, """
         g

         ElGamal""")

    D = DBItem(17, """
        D

        DSA""")

    G = DBItem(20, """
        G

        ElGamal, compromised""")


class IGPGKey(IHasOwner):
    """OpenPGP support"""

    export_as_webservice_entry()

    id = Int(title=_("Database id"), required=True, readonly=True)
    keysize = Int(title=_("Keysize"), required=True)
    algorithm = Choice(title=_("Algorithm"), required=True,
            vocabulary='GpgAlgorithm')
    keyid = exported(TextLine(title=_("OpenPGP key ID"), required=True,
            constraint=valid_keyid))
    fingerprint = exported(TextLine(title=_("User Fingerprint"), required=True,
            constraint=valid_fingerprint))
    active = Bool(title=_("Active"), required=True)
    displayname = Attribute("Key Display Name")
    keyserverURL = Attribute(
        "The URL to retrieve this key from the keyserver.")
    can_encrypt = Bool(title=_("Key can be used for encryption"),
                       required=True)
    owner = Int(title=_('Person'), required=True, readonly=True)
    ownerID = Int(title=_('Owner ID'), required=True, readonly=True)


class IGPGKeySet(Interface):
    """The set of GPGKeys."""

    def new(ownerID, keyid, fingerprint, keysize,
            algorithm, active=True, can_encrypt=True):
        """Create a new GPGKey pointing to the given Person."""

    def get(key_id, default=None):
        """Return the GPGKey object for the given id.

        Return the given default if there's no object with the given id.
        """

    def getByFingerprint(fingerprint, default=None):
        """Return UNIQUE result for a given Key fingerprint including
        inactive ones.
        """

    def getGPGKeys(ownerid=None, active=True):
        """Return OpenPGP keys ordered by id.

        Optionally for a given owner and or a given status.
        """

    def getGPGKeysForPeople(self, people):
        """Return OpenPGP keys for a set of people."""


@adapts(IGPGKey)
@implementer(ICanonicalUrlData)
def get_canonical_url_data_for_gpgkey(gpg_key):
    """Return the `ICanonicalUrlData` for an `IGPGKey`."""
    return ICanonicalUrlData(gpg_key.context)
