# Copyright 2006-2007 Canonical Ltd.  All rights reserved.

"""Helper functions for testing SQLObjects."""

__all__ = ['print_date_attribute',
           'set_so_attr',
           'sync',
           'syncUpdate']

from zope.security.proxy import (
    removeSecurityProxy, isinstance as zope_isinstance)
from sqlobject import SQLObject

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import sqlvalues

def sync(object):
    """Sync the object's from the database.

    This is useful if the object's connection was commited in Zopeless mode,
    or if the database was updated outside the ORM.
    """
    if zope_isinstance(object, SQLObject):
        removeSecurityProxy(object).sync()
    else:
        raise TypeError('%r is not an SQLObject' % object)


def syncUpdate(object):
    """Write the object's changes to the database."""
    if zope_isinstance(object, SQLObject):
        removeSecurityProxy(object).syncUpdate()
    else:
        raise TypeError('%r is not an SQLObject' % object)


def set_so_attr(object, colname, value):
    """Set the underlying SQLObject's column value.

    Use this function to setup test data when the SQLObject decendant guards
    its data. Data is guarded by transitional conditions for workflows, or
    because the decendant is conjoined to another object that controls it.
    """
    if zope_isinstance(object, SQLObject):
        attr_setter = getattr(
            removeSecurityProxy(object), '_SO_set_%s' % colname)
        attr_setter(value)
    else:
        raise TypeError('%r is not an SQLObject' % object)


def print_date_attribute(object, colname):
    """Print out a date attribute of an SQLObject, possibly as 'UTC_NOW'.

    If the value of the attribute is equal to the 'UTC_NOW' time of the
    current transaction, it prints the string 'UTC_NOW' instead of the actual
    time value.  This helps write more precise doctests.
    """
    if zope_isinstance(object, SQLObject):
        cls = removeSecurityProxy(object).__class__
        syncUpdate(object)
        query_template = 'id=%%s AND %s=%%s' % colname
        found_object = cls.selectOne(
            query_template % sqlvalues(object.id, UTC_NOW))
        if found_object is None:
            print getattr(object, colname)
        else:
            print 'UTC_NOW'
    else:
        raise TypeError('%r is not an SQLObject' % object)
