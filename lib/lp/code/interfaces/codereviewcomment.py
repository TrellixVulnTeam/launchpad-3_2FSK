# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211

"""CodeReviewComment interfaces."""

__metaclass__ = type
__all__ = [
    'ICodeReviewComment',
    'ICodeReviewCommentDeletion',
    ]

from zope.interface import Interface
from zope.schema import Choice, Object, Int, TextLine

from canonical.launchpad import _
from lp.code.enums import CodeReviewVote
from lp.code.interfaces.branchmergeproposal import (
    IBranchMergeProposal)
from canonical.launchpad.interfaces.message import IMessage
from lazr.restful.fields import Reference
from lazr.restful.declarations import (
    export_as_webservice_entry, exported)


class ICodeReviewComment(Interface):
    """A link between a merge proposal and a message."""
    export_as_webservice_entry()

    id = exported(
        Int(
            title=_('DB ID'), required=True, readonly=True,
            description=_("The tracking number for this comment.")))

    branch_merge_proposal = exported(
        Reference(
            title=_('The branch merge proposal'), schema=IBranchMergeProposal,
            required=True, readonly=True))

    message = Object(schema=IMessage, title=_('The message.'))

    vote = exported(
        Choice(
            title=_('Review'), required=False,
            vocabulary=CodeReviewVote))

    vote_tag = exported(
        TextLine(
            title=_('Vote tag'), required=False))

    title = exported(
        TextLine(
            title=_('The title of the comment')))

    message_body = exported(
        TextLine(
            title=_('The body of the code review message.'),
            readonly=True))

    def getAttachments():
        """Get the attachments from the original message.

        :return: two lists, the first being attachments that we would display
            (being plain text or diffs), and a second list being any other
            attachments.
        """

    as_quoted_email = exported(
        TextLine(
            title=_('The message as quoted in email.'),
            readonly=True))


class ICodeReviewCommentDeletion(Interface):
    """This interface provides deletion of CodeReviewComments.

    This is the only mutation of CodeReviewCommentss that is permitted.
    """

    def destroySelf():
        """Delete this message."""
