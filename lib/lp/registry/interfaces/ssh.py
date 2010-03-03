# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""SSH key interfaces."""

__metaclass__ = type

__all__ = [
    'ISSHKey',
    'ISSHKeySet',
    'SSHKeyType',
    ]

from zope.schema import Choice, Int, TextLine
from zope.interface import Interface
from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.declarations import (
    collection_default_content, export_as_webservice_collection,
    export_as_webservice_entry, export_read_operation, exported,
    operation_parameters, operation_returns_collection_of)

from canonical.launchpad import _


class SSHKeyType(DBEnumeratedType):
    """SSH key type

    SSH (version 2) can use RSA or DSA keys for authentication. See
    OpenSSH's ssh-keygen(1) man page for details.
    """

    RSA = DBItem(1, """
        RSA

        RSA
        """)

    DSA = DBItem(2, """
        DSA

        DSA
        """)


class ISSHKey(Interface):
    """SSH public key"""

    export_as_webservice_entry('ssh_key')

    id = Int(title=_("Database ID"), required=True, readonly=True)
    person = Int(title=_("Owner"), required=True, readonly=True)
    personID = exported(Int(title=_('Owner ID'), required=True, readonly=True))
    keytype = exported(Choice(title=_("Key type"), required=True,
                     vocabulary=SSHKeyType))
    keytext = exported(TextLine(title=_("Key text"), required=True))
    comment = exported(TextLine(title=_("Comment describing this key"),
                       required=True))

    def destroySelf():
        """Remove this SSHKey from the database."""


class ISSHKeySet(Interface):
    """The set of SSHKeys."""

    def new(person, keytype, keytext, comment):
        """Create a new SSHKey pointing to the given Person."""

    def getByID(id, default=None):
        """Return the SSHKey object for the given id.

        Return the given default if there's now object with the given id.
        """

    def getByPeople(people):
        """Return SSHKey object associated to the people provided."""

