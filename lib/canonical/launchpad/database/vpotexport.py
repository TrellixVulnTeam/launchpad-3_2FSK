# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Database class for Rosetta POT export view."""

__metaclass__ = type

__all__ = ['VPOTExportSet', 'VPOTExport']

from zope.interface import implements

from canonical.database.sqlbase import sqlvalues, cursor

from canonical.launchpad.database.potemplate import POTemplate
from canonical.launchpad.database.potmsgset import POTMsgSet
from canonical.launchpad.interfaces import IVPOTExportSet, IVPOTExport

class VPOTExportSet:
    """Retrieve collections of VPOTExport objects."""

    implements(IVPOTExportSet)

    column_names = [
        'potemplate',
        'sequence',
        'header',
        'pluralform',
        'context',
        'msgid',
        'commenttext',
        'sourcecomment',
        'filereferences',
        'flagscomment',
        'potmsgset',
    ]
    columns = ', '.join(['POTExport.' + name for name in column_names])

    sort_column_names = [
        'potemplate',
        'sequence',
        'potmsgset',
        'pluralform',
    ]
    sort_columns = ', '.join(
        ['POTExport.' + name for name in sort_column_names])

    def _select(self, join=None, where=None):
        query = 'SELECT %s FROM POTExport' % self.columns

        if join is not None:
            query += ''.join([' JOIN ' + s for s in join])

        if where is not None:
            query += ' WHERE %s' % where

        query += ' ORDER BY %s' % self.sort_columns

        cur = cursor()
        cur.execute(query)

        while True:
            row = cur.fetchone()

            if row is not None:
                yield VPOTExport(*row)
            else:
                break

    def get_potemplate_rows(self, potemplate):
        """See IVPOTExportSet."""
        where = 'potemplate = %s' % sqlvalues(potemplate.id)

        return self._select(where=where)


class VPOTExport:
    """Present Rosetta POT files in a form suitable for exporting them
    efficiently.
    """

    implements(IVPOTExport)

    def __init__(self, *args):
        (potemplate,
         self.sequence,
         self.header,
         self.pluralform,
         self.context,
         self.msgid,
         self.commenttext,
         self.sourcecomment,
         self.filereferences,
         self.flagscomment,
         potmsgset) = args

        self.potemplate = POTemplate.get(potemplate)
        self.potmsgset = POTMsgSet.get(potmsgset)

