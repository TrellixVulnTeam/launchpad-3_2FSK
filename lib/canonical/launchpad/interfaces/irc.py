# Copyright 2004 Canonical Ltd.  All rights reserved.

"""IRC interfaces."""

__metaclass__ = type

__all__ = [
    'IIrcID',
    'IIrcIDSet',
    ]

from zope.schema import Int, TextLine
from zope.interface import Interface
from zope.i18nmessageid import MessageIDFactory

_ = MessageIDFactory('launchpad')

class IIrcID(Interface):
    """Wiki for Users"""
    id = Int(title=_("Database ID"), required=True, readonly=True)
    person = Int(title=_("Owner"), required=True, readonly=True)
    network = TextLine(title=_("IRC network"), required=True)
    nickname = TextLine(title=_("Nickname"), required=True)


class IIrcIDSet(Interface):
    """The set of IrcIDs."""

    def new(personID, network, nickname):
        """Create a new IrcID pointing to the given Person."""

