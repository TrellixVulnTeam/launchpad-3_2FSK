# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Database class for table Archive."""

__metaclass__ = type

__all__ = ['Archive', 'ArchiveSet']

from sqlobject import StringCol
from zope.interface import implements

from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import IArchive, IArchiveSet


class Archive(SQLBase):
    implements(IArchive)
    _table = 'Archive'
    _defaultOrder = 'id'

    tag = StringCol(notNull=True)


class ArchiveSet:
    implements(IArchiveSet)

    def __init__(self):
        self.title = "Archives registered in Launchpad"

    def get(self, archiveid):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        return Archive.get(archiveid)

    def new(self, tag):
        return Archive(tag=tag)
