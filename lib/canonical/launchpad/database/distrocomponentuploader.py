# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['DistroComponentUploader']

from canonical.launchpad.interfaces import IDistroComponentUploader

from canonical.database.sqlbase import SQLBase
from sqlobject import ForeignKey
from zope.interface import implements


class DistroComponentUploader(SQLBase):
    """A grant of upload rights to a person or team, applying to a
    distribution and a specific component therein.
    """
    
    implements(IDistroComponentUploader)

    distribution = ForeignKey(dbName='distribution',
        foreignKey='Distribution', notNull=True)
    component = ForeignKey(dbName='component', foreignKey='Component',
        notNull=True)
    uploader = ForeignKey(dbName='uploader', foreignKey='Person',
        notNull=True)

    def __contains__(self, person):
        """See IDistroComponentUploader."""
        return person.inTeam(self.uploader)


