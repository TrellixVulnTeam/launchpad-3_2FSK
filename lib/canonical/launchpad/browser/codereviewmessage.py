__metaclass__ = type

__all__ = [
    'CodeReviewMessageAddView',
    'CodeReviewMessageView',
    ]

from zope.interface import Interface
from zope.schema import Choice, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.interfaces import CodeReviewVote, ICodeReviewMessage
from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadFormView,
    LaunchpadView)


class CodeReviewMessageView(LaunchpadView):
    """Standard view of a CodeReviewMessage"""
    __used_for__ = ICodeReviewMessage

    @property
    def reply_link(self):
        return canonical_url(self.context, view_name='+reply')


class IEditCodeReviewMessage(Interface):

    vote = Choice(
        title=_('Vote'), required=False, vocabulary=CodeReviewVote)

    subject = TextLine(
        title=_('Subject'), required=False, description=_(
        "This will be rendered as help text"))

    comment = Text(
        title=_('Comment'), required=False, description=_(
        "This will be rendered as help text"))


class CodeReviewMessageAddView(LaunchpadFormView):

    schema = IEditCodeReviewMessage

    @property
    def is_reply(self):
        return ICodeReviewMessage.providedBy(self.context)

    @property
    def branch_merge_proposal(self):
        if self.is_reply:
            return self.context.branch_merge_proposal
        else:
            return self.context

    @property
    def reply_to(self):
        if self.is_reply:
            return self.context
        else:
            return None

    @action('Add')
    def add_action(self, action, data):
        """Create the comment..."""
        message = self.branch_merge_proposal.createMessage(
            self.user, data['subject'], data['comment'], data['vote'],
            self.reply_to)
        self.next_url = canonical_url(message)
