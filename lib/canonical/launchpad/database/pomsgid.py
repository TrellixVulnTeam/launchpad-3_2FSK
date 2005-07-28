# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['POMsgID']

from zope.interface import implements

from sqlobject import StringCol, SQLObjectNotFound

from canonical.database.sqlbase import SQLBase, quote

from canonical.launchpad.interfaces import IPOMsgID


class POMsgID(SQLBase):
    implements(IPOMsgID)

    _table = 'POMsgID'

    # alternateID is technically true, but we don't use it because this
    # column is too large to be indexed.
    msgid = StringCol(dbName='msgid', notNull=True, unique=True,
        alternateID=False)

    def byMsgid(cls, key):
        """Return a POMsgID object for the given msgid."""

        # We can't search directly on msgid, because this database column
        # contains values too large to index. Instead we search on its
        # hash, which *is* indexed
        r = POMsgID.selectOne('sha1(msgid) = sha1(%s)' % quote(key))
        if r is None:
            # To be 100% compatible with the alternateID behaviour, we should
            # raise SQLObjectNotFound instead of KeyError
            raise SQLObjectNotFound(key)
        return r
    byMsgid = classmethod(byMsgid)

