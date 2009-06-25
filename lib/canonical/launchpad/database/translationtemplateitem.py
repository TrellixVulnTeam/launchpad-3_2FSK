# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'TranslationTemplateItem',
    ]

from zope.interface import implements
from sqlobject import ForeignKey, IntCol

from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import ITranslationTemplateItem


class TranslationTemplateItem(SQLBase):
    """See `ITranslationTemplateItem`."""
    implements(ITranslationTemplateItem)

    _table = 'TranslationTemplateItem'

    potemplate = ForeignKey(
        foreignKey='POTemplate', dbName='potemplate', notNull=True)
    sequence = IntCol(dbName='sequence', notNull=True)
    potmsgset = ForeignKey(
        foreignKey='POTMsgSet', dbName='potmsgset', notNull=True)
