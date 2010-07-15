# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""SQLBase implementation of IQuestionBug."""

__metaclass__ = type

__all__ = ['QuestionBug']

from zope.interface import implements

from sqlobject import ForeignKey

from canonical.launchpad.interfaces import IQuestionBug

from canonical.database.sqlbase import SQLBase


class QuestionBug(SQLBase):
    """A link between a question and a bug."""

    implements(IQuestionBug)

    _table = 'QuestionBug'

    question = ForeignKey(
        dbName='question', foreignKey='Question', notNull=True)
    bug = ForeignKey(dbName='bug', foreignKey='Bug', notNull=True)

    @property
    def target(self):
        """See IBugLink."""
        return self.question

