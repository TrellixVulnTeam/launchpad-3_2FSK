# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""An interface for objects that are linked to messages."""

__metaclass__ = type

__all__ = [
    'IMessageTarget',
    ]

from zope.interface import Interface, Attribute

from canonical.launchpad import _
from canonical.launchpad.interfaces.message import IMessage

from canonical.lazr.rest.declarations import exported
from canonical.lazr.fields import CollectionField, Reference


class IMessageTarget(Interface):
    """An object that an be linked to a message."""

    messages = CollectionField(
            title=_("The messages related to this object, in reverse "
                    "order of creation (so newest first)."),
            readonly=True,
            value_type=Reference(schema=IMessage))

    indexed_messages = exported(
        CollectionField(
            title=_("The messages related to this object, in reverse "
                    "order of creation (so newest first)."),
            readonly=True,
            value_type=Reference(schema=IMessage)),
        exported_as='messages')

    followup_subject = Attribute("The likely subject of the next message.")

    def newMessage(owner, subject, content):
        """Create a new message, and link it to this object."""

    def linkMessage(message):
        """Link the given message to this object."""
