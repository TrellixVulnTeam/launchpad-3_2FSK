# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Question message interface."""

__metaclass__ = type

__all__ = [
    'IQuestionMessage',
    ]

from zope.interface import Interface
from zope.schema import (
    Bool,
    Choice,
    Int,
    )

from lazr.restful.declarations import (
    export_as_webservice_entry,
    exported,
    )
from lazr.restful.fields import Reference

from canonical.launchpad import _
from lp.services.messages.interfaces.message import IMessage
from lp.answers.enums import (
    QuestionAction,
    QuestionStatus,
    )


class IQuestionMessage(IMessage):
    """A message part of a question.

    It adds attributes to the IMessage interface.
    """
    export_as_webservice_entry(as_of='devel')

    # This is really an Object field with schema=IQuestion, but that
    # would create a circular dependency between IQuestion
    # and IQuestionMessage
    question = exported(Reference(
        title=_("The question related to this message."), schema=Interface,
        description=_("An IQuestion object."), required=True, readonly=True),
        as_of="devel")
    action = exported(Choice(
        title=_("Action operated on the question by this message."),
        required=True, readonly=True, default=QuestionAction.COMMENT,
        vocabulary=QuestionAction),
        as_of="devel")
    new_status = exported(Choice(
        title=_("Question status after message"),
        description=_("The status of the question after the transition "
        "related the action operated by this message."), required=True,
        readonly=True, default=QuestionStatus.OPEN,
        vocabulary=QuestionStatus),
        as_of="devel")
    index = exported(Int(
        title=_("Message index."),
        description=_("The messages index in the question's list of "
        "messages."),
        readonly=True))
    display_index = Int(
        title=_("Human readable Message index."),
        description=_("The message's index in the question's list of "
        "messages, meant for humans."),
        readonly=True)
    visible = exported(Bool(
        title=_("Message visibility."),
        description=_("Whether or not the message is visible."),
        readonly=True),
        as_of="devel")
