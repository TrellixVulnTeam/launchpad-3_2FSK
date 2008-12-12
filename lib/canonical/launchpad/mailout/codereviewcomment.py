# Copyright 2008 Canonical Ltd.  All rights reserved.


"""Email notifications for code review comments."""


__metaclass__ = type


from canonical.launchpad.interfaces import CodeReviewNotificationLevel
from canonical.launchpad.mail import format_address
from canonical.launchpad.mailout.branchmergeproposal import BMPMailer
from canonical.launchpad.webapp import canonical_url


def send(comment, event):
    """Send a copy of the code review comments to branch subscribers."""
    CodeReviewCommentMailer.forCreation(comment).sendAll()


class CodeReviewCommentMailer(BMPMailer):
    """Send email about creation of a CodeReviewComment."""

    def __init__(self, code_review_comment, recipients):
        """Constructor."""
        self.code_review_comment = code_review_comment
        self.message = code_review_comment.message
        from_person = self.message.owner
        from_address = format_address(
            from_person.displayname, from_person.preferredemail.email)
        merge_proposal = code_review_comment.branch_merge_proposal
        BMPMailer.__init__(
            self, self.message.subject, None, recipients, merge_proposal,
            from_address)

    @classmethod
    def forCreation(klass, code_review_comment):
        """Return a mailer for CodeReviewComment creation."""
        merge_proposal = code_review_comment.branch_merge_proposal
        recipients = merge_proposal.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL)
        return klass(code_review_comment, recipients)

    def _getSubject(self, email):
        """Don't do any string template insertions on subjects."""
        return self.code_review_comment.message.subject

    def _getBody(self, email):
        """Return the complete body to use for this email.

        If there was a vote, we prefix "Review: " to the message.
        We always append information about why this message was sent.  If
        there is an existing footer, we append it to that.  Otherwise, we
        we insert a new footer.
        """
        if self.code_review_comment.vote is None:
            prefix = ''
        else:
            if self.code_review_comment.vote_tag is None:
                vote_tag = ''
            else:
                vote_tag = ' ' + self.code_review_comment.vote_tag
            prefix = 'Review: %s%s\n' % (
                self.code_review_comment.vote.title, vote_tag)
        main = self.message.text_contents
        if '\n-- \n' in main:
            footer_separator = '\n'
        else:
            footer_separator = '\n-- \n'

        # Include both the canonical_url for the proposal and the reason
        # in the footer to the email.
        reason, rationale = self._recipients.getReason(email)
        footer = "%(proposal_url)s\n%(reason)s" % {
            'proposal_url': canonical_url(self.merge_proposal),
            'reason': reason.getReason()}
        return ''.join((
            prefix, main, footer_separator, footer))

    def _getHeaders(self, email):
        """Return the mail headers to use."""
        headers = BMPMailer._getHeaders(self, email)
        headers['Message-Id'] = self.message.rfc822msgid
        if self.message.parent is not None:
            headers['In-Reply-To'] = self.message.parent.rfc822msgid
        return headers
