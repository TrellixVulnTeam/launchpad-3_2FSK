# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['BugMessage', 'BugMessageSet']

from email.Utils import make_msgid

from zope.interface import implements

from sqlobject import BoolCol, ForeignKey, StringCol
from storm.store import Store

from canonical.database.sqlbase import SQLBase, sqlvalues
from lp.bugs.interfaces.bugmessage import IBugMessage, IBugMessageSet
from canonical.launchpad.database.message import Message, MessageChunk

class BugMessage(SQLBase):
    """A table linking bugs and messages."""

    implements(IBugMessage)

    _table = 'BugMessage'

    # db field names
    bug = ForeignKey(dbName='bug', foreignKey='Bug', notNull=True)
    message = ForeignKey(dbName='message', foreignKey='Message', notNull=True)
    bugwatch = ForeignKey(dbName='bugwatch', foreignKey='BugWatch',
        notNull=False, default=None)
    remote_comment_id = StringCol(notNull=False, default=None)
    visible = BoolCol(notNull=True, default=True)


class BugMessageSet:
    """See canonical.launchpad.interfaces.IBugMessageSet."""

    implements(IBugMessageSet)

    def createMessage(self, subject, bug, owner, content=None):
        """See canonical.launchpad.interfaces.IBugMessageSet."""
        msg = Message(
            parent=bug.initial_message, owner=owner,
            rfc822msgid=make_msgid('malone'), subject=subject)
        chunk = MessageChunk(message=msg, content=content, sequence=1)
        bugmsg = BugMessage(bug=bug, message=msg)

        # XXX 2008-05-27 jamesh:
        # Ensure that BugMessages get flushed in same order as they
        # are created.
        Store.of(bugmsg).flush()
        return bugmsg

    def get(self, bugmessageid):
        """See canonical.launchpad.interfaces.IBugMessageSet."""
        return BugMessage.get(bugmessageid)

    def getByBugAndMessage(self, bug, message):
        """See canonical.launchpad.interfaces.IBugMessageSet."""
        return BugMessage.selectOneBy(bug=bug, message=message)

    def getImportedBugMessages(self, bug):
        """See IBugMessageSet."""
        return BugMessage.select("""
            BugMessage.bug = %s
            AND BugMessage.bugwatch IS NOT NULL
            """ % sqlvalues(bug), orderBy='id')
