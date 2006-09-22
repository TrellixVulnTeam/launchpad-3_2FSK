# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = ['TicketReopening',
           'create_ticketreopening']

from zope.event import notify
from zope.interface import implements

from sqlobject import ForeignKey

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.event import SQLObjectCreatedEvent
from canonical.launchpad.interfaces import ITicketReopening

from canonical.lp.dbschema import EnumCol, TicketStatus


class TicketReopening(SQLBase):
    """A table recording each time a ticket is re-opened."""

    implements(ITicketReopening)

    _table = 'TicketReopening'

    ticket = ForeignKey(dbName='ticket', foreignKey='Ticket', notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    reopener = ForeignKey(dbName='reopener', foreignKey='Person',
        notNull=True)
    answerer = ForeignKey(dbName='answerer', foreignKey='Person',
        notNull=False, default=None)
    dateanswered = UtcDateTimeCol(notNull=False, default=None)
    priorstate = EnumCol(schema=TicketStatus, notNull=True)


def create_ticketreopening(ticket, event):
    """Event susbcriber that creates a TicketReopening whenever a ticket
    with an answer changes back to the OPEN state.
    """
    if ticket.status != TicketStatus.OPEN:
        return

    # Only create a TicketReopening if the ticket
    # had previsouly an answer
    old_ticket = event.object_before_modification
    if old_ticket.answerer is None:
        return
    assert ticket.answerer is None, "Open ticket shouldn't have an answerer."

    # The last message should be the cause of the reopening
    reopen_msg = ticket.messages[-1]
    assert [reopen_msg] == (
        list(set(ticket.messages).difference(old_ticket.messages))), (
            "Reopening message isn't the last one.")

    reopening = TicketReopening(
            ticket=ticket, reopener=reopen_msg.owner,
            datecreated=reopen_msg.datecreated, answerer=old_ticket.answerer,
            dateanswered=old_ticket.dateanswered,
            priorstate=old_ticket.status)
    notify(SQLObjectCreatedEvent(reopening, user=reopen_msg.owner))

