# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""SSH key interfaces."""

__metaclass__ = type

__all__ = [
    'ISSHKey',
    'ISSHKeySet',
    ]

from zope.schema import Int, TextLine
from zope.interface import Interface
from canonical.launchpad import _


class ISSHKey(Interface):
    """SSH public key"""
    id = Int(title=_("Database ID"), required=True, readonly=True)
    person = Int(title=_("Owner"), required=True, readonly=True)
    keytype = TextLine(title=_("Key type"), required=True)
    keytext = TextLine(title=_("Key text"), required=True)
    comment = TextLine(title=_("Comment describing this key"), required=True)

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

