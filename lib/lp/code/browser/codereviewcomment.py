# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'CodeReviewCommentAddView',
    'CodeReviewCommentContextMenu',
    'CodeReviewCommentPrimaryContext',
    'CodeReviewCommentSummary',
    'CodeReviewCommentView',
    'CodeReviewDisplayComment',
    ]
from textwrap import TextWrapper

from zope.app.form.browser import TextAreaWidget, DropdownWidget
from zope.interface import Interface, implements
from zope.schema import Text

from canonical.cachedproperty import cachedproperty
from lazr.delegates import delegates
from lazr.restful.interface import copy_field

from canonical.launchpad import _
from canonical.launchpad.webapp import (
    action, canonical_url, ContextMenu, custom_widget, LaunchpadFormView,
    LaunchpadView, Link)
from canonical.launchpad.webapp.interfaces import IPrimaryContext
from lp.code.interfaces.codereviewcomment import ICodeReviewComment
from lp.code.interfaces.codereviewvote import ICodeReviewVoteReference
from lp.services.comments.interfaces.conversation import IComment


def quote_text_as_email(text, width=80):
    """Quote the text as if it is an email response.

    Uses '> ' as a line prefix, and breaks long lines.

    Trailing whitespace is stripped.
    """
    # Empty text begets empty text.
    if text is None:
        return ''
    text = text.rstrip()
    if not text:
        return ''
    prefix = '> '
    # The TextWrapper's handling of code is somewhat suspect.
    wrapper = TextWrapper(
        initial_indent=prefix,
        subsequent_indent=prefix,
        width=width,
        replace_whitespace=False)
    result = []
    # Break the string into lines, and use the TextWrapper to wrap the
    # individual lines.
    for line in text.rstrip().split('\n'):
        # TextWrapper won't do an indent of an empty string.
        if line.strip() == '':
            result.append(prefix)
        else:
            result.extend(wrapper.wrap(line))
    return '\n'.join(result)


class CodeReviewDisplayComment:
    """A code review comment or activity or both.

    The CodeReviewComment itself does not implement the IComment interface as
    this is purely a display interface, and doesn't make sense to have display
    only code in the model itself.
    """

    implements(IComment)

    delegates(ICodeReviewComment, 'comment')

    def __init__(self, comment):
        self.comment = comment
        self.has_body = bool(self.comment.message_body)
        self.has_footer = self.comment.vote is not None
        # The date attribute is used to sort the comments in the conversation.
        self.date = self.comment.message.datecreated


class CodeReviewCommentPrimaryContext:
    """The primary context is the comment is that of the source branch."""

    implements(IPrimaryContext)

    def __init__(self, comment):
        self.context = IPrimaryContext(
            comment.branch_merge_proposal).context


class CodeReviewCommentContextMenu(ContextMenu):
    """Context menu for branches."""

    usedfor = ICodeReviewComment
    links = ['reply']

    def reply(self):
        enabled = self.context.branch_merge_proposal.isMergable()
        return Link('+reply', 'Reply', icon='add', enabled=enabled)


class CodeReviewCommentView(LaunchpadView):
    """Standard view of a CodeReviewComment"""
    __used_for__ = ICodeReviewComment

    page_title = "Code review comment"

    @cachedproperty
    def comment(self):
        """The decorated code review comment."""
        return CodeReviewDisplayComment(self.context)

    @cachedproperty
    def comment_author(self):
        """The author of the comment."""
        return self.context.message.owner

    @cachedproperty
    def has_body(self):
        """Is there body text?"""
        return bool(self.body_text)

    @cachedproperty
    def body_text(self):
        """Get the body text for the message."""
        return self.context.message_body

    @cachedproperty
    def comment_date(self):
        """The date of the comment."""
        return self.context.message.datecreated

    # Should the comment be shown in full?
    full_comment = True
    # Show comment expanders?
    show_expanders = False

    @cachedproperty
    def all_attachments(self):
        return self.context.getAttachments()

    @cachedproperty
    def display_attachments(self):
        # Attachments to show.
        return self.all_attachments[0]

    @cachedproperty
    def other_attachments(self):
        # Attachments to not show.
        return self.all_attachments[1]


class CodeReviewCommentSummary(CodeReviewCommentView):
    """Summary view of a CodeReviewComment"""

    # How many lines do we show in the main view?
    SHORT_MESSAGE_LENGTH = 3

    # Show comment expanders?
    show_expanders = True

    # Should the comment be shown in full?
    @property
    def full_comment(self):
        """Show the full comment if it is short."""
        return not self.is_long_message

    @cachedproperty
    def _comment_lines(self):
        return self.context.message.text_contents.splitlines()

    @property
    def is_long_message(self):
        return len(self._comment_lines) > self.SHORT_MESSAGE_LENGTH

    @property
    def message_summary(self):
        """Return an elided message with the first X lines of the comment."""
        short_message = (
            '\n'.join(self._comment_lines[:self.SHORT_MESSAGE_LENGTH]))
        short_message += "..."
        return short_message


class IEditCodeReviewComment(Interface):
    """Interface for use as a schema for CodeReviewComment forms."""

    vote = copy_field(ICodeReviewComment['vote'], required=False)

    review_type = copy_field(ICodeReviewVoteReference['review_type'],description=u'Lowercase keywords describing the type of review you are performing.')

    comment = Text(title=_('Comment'), required=False)


class CodeReviewCommentAddView(LaunchpadFormView):
    """View for adding a CodeReviewComment."""

    class MyDropWidget(DropdownWidget):
        "Override the default no-value display name to -Select-."
        _messageNoValue = '-Select-'

    schema = IEditCodeReviewComment

    custom_widget('comment', TextAreaWidget, cssClass='codereviewcomment')
    custom_widget('vote', MyDropWidget)

    page_title = 'Reply to code review comment'

    @property
    def initial_values(self):
        """The initial values are used to populate the form fields.

        In this case, the default value of the comment should be the
        quoted comment being replied to.
        """
        if self.is_reply:
            comment = quote_text_as_email(self.reply_to.message_body)
        else:
            comment = ''
        return {'comment': comment}


    @property
    def is_reply(self):
        """True if this comment is a reply to another comment, else False."""
        return ICodeReviewComment.providedBy(self.context)

    @property
    def branch_merge_proposal(self):
        """The BranchMergeProposal being commented on."""
        if self.is_reply:
            return self.context.branch_merge_proposal
        else:
            return self.context

    @cachedproperty
    def reply_to(self):
        """The comment being replied to, or None."""
        if self.is_reply:
            return CodeReviewDisplayComment(self.context)
        else:
            return None

    @action('Save Comment', name='add')
    def add_action(self, action, data):
        """Create the comment..."""
        comment = self.branch_merge_proposal.createComment(
            self.user, subject=None, content=data['comment'],
            parent=self.reply_to, vote=data['vote'],
            review_type=data['review_type'])

    @property
    def next_url(self):
        """Always take the user back to the merge proposal itself."""
        return canonical_url(self.branch_merge_proposal)

    cancel_url = next_url
