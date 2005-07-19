# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Jabber interfaces."""

__metaclass__ = type

__all__ = [
    'IJabberID',
    'IJabberIDSet',
    ]

from zope.schema import Int, TextLine
from zope.interface import Interface
from zope.i18nmessageid import MessageIDFactory

_ = MessageIDFactory('launchpad')

class IJabberID(Interface):
    """Jabber specific user ID """
    id = Int(title=_("Database ID"), required=True, readonly=True)
    person = Int(title=_("Owner"), required=True)
    jabberid = TextLine(title=_("Jabber user ID"), required=True)

    def destroySelf():
        """Delete this JabberID from the database."""


class IJabberIDSet(Interface):
    """The set of JabberIDs."""

    def new(personID, jabberid):
        """Create a new JabberID pointing to the given Person."""

