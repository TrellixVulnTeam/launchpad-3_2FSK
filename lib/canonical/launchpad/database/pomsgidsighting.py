# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['POMsgIDSighting']

from zope.interface import implements

from sqlobject import DateTimeCol, ForeignKey, IntCol, BoolCol
from canonical.database.sqlbase import SQLBase

from canonical.launchpad.interfaces import IPOMsgIDSighting


class POMsgIDSighting(SQLBase):
    implements(IPOMsgIDSighting)

    _table = 'POMsgIDSighting'

    potmsgset = ForeignKey(foreignKey='POTMsgSet', dbName='potmsgset',
        notNull=True)
    pomsgid_ = ForeignKey(foreignKey='POMsgID', dbName='pomsgid',
        notNull=True)
    datefirstseen = DateTimeCol(dbName='datefirstseen', notNull=True)
    datelastseen = DateTimeCol(dbName='datelastseen', notNull=True)
    inlastrevision = BoolCol(dbName='inlastrevision', notNull=True)
    pluralform = IntCol(dbName='pluralform', notNull=True)

