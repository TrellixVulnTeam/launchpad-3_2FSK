# Copyright 2008 Canonical Ltd.  All rights reserved.


"""Base class for sending out emails."""


__metaclass__ = type



__all__ = ['BaseMailer']


from canonical.launchpad.helpers import get_email_template
from canonical.launchpad.mail import simple_sendmail, format_address
from canonical.launchpad.mailout import text_delta
from canonical.launchpad.mailout.notificationrecipientset import (
    NotificationRecipientSet)


class BaseMailer:
    """Base class for notification mailers.

    Subclasses must provide getReason (or reimplement _getTemplateParameters
    or generateEmail).

    It is expected that subclasses may override _getHeaders,
    _getTemplateParams, and perhaps _getBody.
    """

    def __init__(self, subject, template_name, recipients, from_address,
                 delta=None):
        """Constructor.

        :param subject: A Python dict-replacement template for the subject
            line of the email.
        :param template: Name of the template to use for the message body.
        :param recipients: A dict of recipient to Subscription.
        :param from_address: The from_address to use on emails.
        :param delta: A Delta object with members "delta_values", "interface"
            and "new_values", such as BranchMergeProposalDelta.
        """
        self._subject_template = subject
        self._template_name = template_name
        self._recipients = NotificationRecipientSet()
        for recipient, reason in recipients.iteritems():
            self._recipients.add(recipient, reason, reason.mail_header)
        self.from_address = from_address
        self.delta = delta

    def generateEmail(self, email):
        """Generate the email for this recipient.

        :return: (headers, subject, body) of the email.
        """
        headers = self._getHeaders(email)
        subject = self._getSubject(email)
        return (headers, subject, self._getBody(email))

    def _getSubject(self, email):
        """The subject template expanded with the template params."""
        return self._subject_template % self._getTemplateParams(email)

    def _getReplyToAddress(self):
        """Return the address to use for the reply-to header."""
        return None

    def _getHeaders(self, email):
        """Return the mail headers to use."""
        reason, rationale = self._recipients.getReason(email)
        headers = {'X-Launchpad-Message-Rationale': reason.mail_header}
        reply_to = self._getReplyToAddress()
        if reply_to is not None:
            headers['Reply-To'] = reply_to
        return headers

    def _getTemplateParams(self, email):
        """Return a dict of values to use in the body and subject."""
        reason, rationale = self._recipients.getReason(email)
        params = {'reason': reason.getReason()}
        if self.delta is not None:
            params['delta'] = self.textDelta()
        return params

    def textDelta(self):
        """Return a textual version of the class delta."""
        return text_delta(self.delta, self.delta.delta_values,
            self.delta.new_values, self.delta.interface)

    def _getBody(self, email):
        """Return the complete body to use for this email."""
        template = get_email_template(self._template_name)
        return template % self._getTemplateParams(email)

    def iterRecipients(self, recipient_people=None):
        if recipient_people is None:
            iterator = self._recipients.getRecipientPersons()
        else:
            iterator = ((r.preferredemail.email, r) for r in recipient_people)
        for email, recipient in iterator:
            to_address = format_address(recipient.displayname, email)
            yield email, to_address

    def sendAll(self):
        """Send notifications to all recipients."""
        for email, to_address in self.iterRecipients():
            headers, subject, body = self.generateEmail(email)
            simple_sendmail(
                self.from_address, to_address, subject, body, headers)
