# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BinaryPackageName', 'BinaryPackageNameSet',
           'BinaryAndSourcePackageName']

# Zope imports
from zope.interface import implements

# SQLObject/SQLBase
from sqlobject import (
    SQLObjectNotFound, StringCol, MultipleJoin, CONTAINSSTRING)

# launchpad imports
from canonical.database.sqlbase import SQLBase


# interfaces and database 
from canonical.launchpad.interfaces import (
    IBinaryPackageName, IBinaryPackageNameSet, NotFoundError,
    IBinaryAndSourcePackageName)


class BinaryPackageName(SQLBase):

    implements(IBinaryPackageName)
    _table = 'BinaryPackageName'
    name = StringCol(dbName='name', notNull=True, unique=True,
                     alternateID=True)

    binarypackages = MultipleJoin(
        'BinaryPackage', joinColumn='binarypackagename'
        )

    def __unicode__(self):
        return self.name


class BinaryPackageNameSet:
    implements(IBinaryPackageNameSet)

    def __getitem__(self, name):
        """See canonical.launchpad.interfaces.IBinaryPackageNameSet."""
        try:
            return BinaryPackageName.byName(name)
        except SQLObjectNotFound:
            raise NotFoundError(name)

    def __iter__(self):
        """See canonical.launchpad.interfaces.IBinaryPackageNameSet."""
        for binarypackagename in BinaryPackageName.select():
            yield binarypackagename

    def findByName(self, name):
        """Find binarypackagenames by its name or part of it."""
        return BinaryPackageName.select(
            CONTAINSSTRING(BinaryPackageName.q.name, name))

    def queryByName(self, name):
        return BinaryPackageName.selectOneBy(name=name)

    def new(self, name):
        return BinaryPackageName(name=name)

    def getOrCreateByName(self, name):
        try:
            return self[name]
        except KeyError:
            return self.new(name)

    def ensure(self, name):
        """Ensure that the given BinaryPackageName exists, creating it
        if necessary.

        Returns the BinaryPackageName
        """
        try:
            return BinaryPackageName.byName(name)
        except SQLObjectNotFound:
            return BinaryPackageName(name=name)


class BinaryAndSourcePackageName(SQLBase):
    """See IBinaryAndSourcePackageName"""

    implements(IBinaryAndSourcePackageName)

    _table = 'BinaryAndSourcePackageNameView'
    _idName = 'name'
    _idType = str
    _defaultOrder = 'name'

    name = StringCol(dbName='name', notNull=True, unique=True,
                     alternateID=True)

