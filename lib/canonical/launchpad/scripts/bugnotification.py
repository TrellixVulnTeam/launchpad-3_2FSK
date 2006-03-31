# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Functions related to sending bug notifications."""

__metaclass__ = type

from email.MIMEText import MIMEText
from email.Utils import formatdate
import rfc822

from canonical.config import config
from canonical.launchpad.helpers import get_email_template
from canonical.launchpad.mail import format_address
from canonical.launchpad.mailnotification import (
    get_bugmail_replyto_address, generate_bug_add_email,
    GLOBAL_NOTIFICATION_EMAIL_ADDRS)
from canonical.launchpad.webapp import canonical_url


def construct_email_notification(bug_notifications):
    """Construct an email from a list of related bug notifications.

    The person and bug has to be the same for all notifications, and
    there can be only one comment.
    """
    first_notification = bug_notifications[0]
    bug = first_notification.bug
    person = first_notification.message.owner
    msgid = first_notification.message.rfc822msgid
    subject = first_notification.message.subject
    comment = None

    notified_addresses = bug.notificationRecipientAddresses()
    if not bug.private:
        notified_addresses = (
            notified_addresses + GLOBAL_NOTIFICATION_EMAIL_ADDRS)

    notified_addresses = bug.notificationRecipientAddresses()
    if not bug.private:
        notified_addresses = (
            notified_addresses + GLOBAL_NOTIFICATION_EMAIL_ADDRS)
    for notification in bug_notifications:
        assert notification.bug == bug
        assert notification.message.owner == person
        if notification.is_comment:
            assert comment is None, (
                "Only one of the notifications is allowed to be a comment.")
            comment = notification.message
    text_notifications = [
        notification.message.text_contents.rstrip()
        for notification in bug_notifications
        if notification.message != comment
        ]
    if comment is not None:
        if comment == bug.initial_message:
            # It's a bug filed notifications.
            dummy, text = generate_bug_add_email(bug)
        else:
            text = comment.text_contents
        text_notifications.insert(0, text)
        msgid = comment.rfc822msgid

    if bug.duplicateof is not None:
        text_notifications.insert(
            0,
            '*** This bug is a duplicate of bug %d ***' % bug.duplicateof.id)
        if not bug.private:
            # This bug is a duplicate of another bug, so include the dup
            # target's subscribers in the recipient list, for comments
            # only.
            #
            # NOTE: if the dup is private, the dup target will not receive
            # notifications from the dup.
            #
            # Even though this use case seems highly contrived, I'd rather
            # be paranoid and not reveal anything unexpectedly about a
            # private bug.
            #
            # -- Brad Bollenbach, 2005-04-19
            duplicate_target_emails = \
                bug.duplicateof.notificationRecipientAddresses()
            # Merge the duplicate's notification recipient addresses with
            # those belonging to the dup target.
            notified_addresses = list(
                set(notified_addresses + duplicate_target_emails))

    content = '\n\n'.join(text_notifications)
    body = get_email_template('bug-notification.txt') % {
        'content': content,
        'bug_title': bug.title,
        'bug_url': canonical_url(bug)}

    # Set the references and date header.
    if comment:
        email_date = comment.datecreated
        references = []
        reference = comment.parent
        while reference is not None:
            references.insert(0, reference.rfc822msgid)
            reference = reference.parent
    else:
        email_date = first_notification.message.datecreated
        references = []
    if bug.initial_message.rfc822msgid not in references:
        references.insert(0, bug.initial_message.rfc822msgid)

    msg = MIMEText(body.encode('utf8'), 'plain', 'utf8')
    msg['From'] = format_address(
        person.displayname, person.preferredemail.email)
    msg['Reply-To'] = get_bugmail_replyto_address(bug)
    msg['References'] = ' '.join(references)
    msg['Sender'] = config.bounce_address
    msg['Date'] = formatdate(rfc822.mktime_tz(email_date.utctimetuple() + (0,)))
    msg['Message-Id'] = msgid
    msg['Subject'] = "[Bug %d] %s" % (bug.id, subject)

    # Add X-Launchpad-Bug headers.
    for bugtask in bug.bugtasks:
        msg.add_header('X-Launchpad-Bug', bugtask.asEmailHeaderValue())

    return bug_notifications, notified_addresses, msg


def get_email_notifications(bug_notifications, date_emailed=None):
    """Return the email notifications pending to be sent."""
    bug_notifications = list(bug_notifications)
    while bug_notifications:
        person_bug_notifications = []
        bug = bug_notifications[0].bug
        person = bug_notifications[0].message.owner
        # Create a copy of the list, so removing items from it won't
        # break the iteration over it.
        for notification in list(bug_notifications):
            if (notification.bug, notification.message.owner) != (bug, person):
                break
            person_bug_notifications.append(notification)
            bug_notifications.remove(notification)

        has_comment = False
        notifications_to_send = []
        for notification in person_bug_notifications:
            if date_emailed is not None:
                notification.date_emailed = date_emailed
            if notification.is_comment and has_comment:
                yield construct_email_notification(notifications_to_send)
                has_comment = False
                notifications_to_send = []
            if notification.is_comment:
                has_comment = True
            notifications_to_send.append(notification)
        if notifications_to_send:
            yield construct_email_notification(notifications_to_send)
