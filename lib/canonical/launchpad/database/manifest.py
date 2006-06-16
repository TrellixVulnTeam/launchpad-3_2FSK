# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Manifest']


from zope.interface import implements

from sqlobject import SQLMultipleJoin, StringCol, SQLRelatedJoin

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.interfaces import IManifest


class Manifest(SQLBase):
    """A manifest."""

    implements(IManifest)

    _table = 'Manifest'

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    uuid = StringCol(notNull=True, alternateID=True)

    entries = SQLMultipleJoin('ManifestEntry', joinColumn='manifest',
                           orderBy='sequence')

    ancestors = SQLRelatedJoin('Manifest', joinColumn='child',
                            otherColumn='parent',
                            intermediateTable='ManifestAncestry')

    def __iter__(self):
        return self.entries

