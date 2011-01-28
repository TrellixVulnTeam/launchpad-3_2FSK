# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""SQLBase implementation of IQuestionReopening."""

__metaclass__ = type

__all__ = ['QuestionReopening',
           'create_questionreopening']

from lazr.lifecycle.event import ObjectCreatedEvent
from sqlobject import ForeignKey
from zope.event import notify
from zope.interface import implements
from zope.security.proxy import ProxyFactory

from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from lp.answers.interfaces.questionenums import QuestionStatus
from lp.answers.interfaces.questionreopening import IQuestionReopening
from lp.registry.interfaces.person import validate_public_person


class QuestionReopening(SQLBase):
    """A table recording each time a question is re-opened."""

    implements(IQuestionReopening)

    _table = 'QuestionReopening'

    question = ForeignKey(
        dbName='question', foreignKey='Question', notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    reopener = ForeignKey(
        dbName='reopener', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    answerer = ForeignKey(
        dbName='answerer', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False, default=None)
    date_solved = UtcDateTimeCol(notNull=False, default=None)
    priorstate = EnumCol(schema=QuestionStatus, notNull=True)


def create_questionreopening(question):
    """Helper function to handle question reopening.

    A QuestionReopening is created when question with an answer changes back
    to the OPEN state.
    """
    # The last added message is the cause of the reopening.
    reopen_msg = question.messages[-1]

    # Make sure that the last message is really the last added one.
    assert [reopen_msg] == (
        list(set(question.messages).difference(old_question.messages))), (
            "Reopening message isn't the last one.")

    reopening = QuestionReopening(
            question=question, reopener=reopen_msg.owner,
            datecreated=reopen_msg.datecreated,
            answerer=old_question.answerer,
            date_solved=old_question.date_solved,
            priorstate=old_question.status)

    reopening = ProxyFactory(reopening)
    notify(ObjectCreatedEvent(reopening, user=reopen_msg.owner))
