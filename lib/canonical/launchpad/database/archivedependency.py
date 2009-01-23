# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Database class for ArchiveDependency."""

__metaclass__ = type

__all__ = ['ArchiveDependency']


from sqlobject import ForeignKey
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.components.archivedependencies import (
    component_dependencies)
from canonical.launchpad.interfaces.archivedependency import (
    IArchiveDependency)
from canonical.launchpad.interfaces.publishing import PackagePublishingPocket


class ArchiveDependency(SQLBase):
    """See `IArchiveDependency`."""

    implements(IArchiveDependency)

    _table = 'ArchiveDependency'
    _defaultOrder = 'id'

    date_created = UtcDateTimeCol(
        dbName='date_created', notNull=True, default=UTC_NOW)

    archive = ForeignKey(
        foreignKey='Archive', dbName='archive', notNull=True)

    dependency = ForeignKey(
        foreignKey='Archive', dbName='dependency', notNull=True)

    pocket = EnumCol(
        dbName='pocket', notNull=True, schema=PackagePublishingPocket)

    component = ForeignKey(
        foreignKey='Component', dbName='component')

    @property
    def title(self):
        """See `IArchiveDependency`."""
        if self.dependency.is_ppa:
            return self.dependency.title

        pocket_title = "%s - %s" % (
            self.dependency.title, self.pocket.name)

        if self.component is None:
            return pocket_title

        component_part = ", ".join(
            component_dependencies[self.component.name])

        return "%s (%s)" % (pocket_title, component_part)
