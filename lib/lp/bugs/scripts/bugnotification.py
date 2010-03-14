# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0702

"""Functions related to sending bug notifications."""

__metaclass__ = type

from zope.component import getUtility

from canonical.config import config
from canonical.database.sqlbase import rollback, begin
from canonical.launchpad.helpers import emailPeople, get_email_template
from lp.bugs.interfaces.bugmessage import IBugMessageSet
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import IPersonSet
from canonical.launchpad.mailnotification import (
    generate_bug_add_email, MailWrapper, BugNotificationBuilder,
    get_bugmail_from_address)
from canonical.launchpad.scripts.logger import log
from canonical.launchpad.webapp import canonical_url


def construct_email_notifications(bug_notifications):
    """Construct an email from a list of related bug notifications.

    The person and bug has to be the same for all notifications, and
    there can be only one comment.
    """
    first_notification = bug_notifications[0]
    bug = first_notification.bug
    person = first_notification.message.owner
    subject = first_notification.message.subject

    comment = None
    references = []
    text_notifications = []

    recipients = {}
    for notification in bug_notifications:
        for recipient in notification.recipients:
            for email_person in emailPeople(recipient.person):
                recipients[email_person] = recipient

    for notification in bug_notifications:
        assert notification.bug == bug, bug.id
        assert notification.message.owner == person, person.id
        if notification.is_comment:
            assert comment is None, (
                "Only one of the notifications is allowed to be a comment.")
            comment = notification.message

    if bug.duplicateof is not None:
        text_notifications.append(
            '*** This bug is a duplicate of bug %d ***\n    %s' %
                (bug.duplicateof.id, canonical_url(bug.duplicateof)))

    if comment is not None:
        if comment == bug.initial_message:
            subject, text = generate_bug_add_email(bug)
        else:
            text = comment.text_contents
        text_notifications.append(text)

        msgid = comment.rfc822msgid
        email_date = comment.datecreated

        reference = comment.parent
        while reference is not None:
            references.insert(0, reference.rfc822msgid)
            reference = reference.parent
    else:
        msgid = first_notification.message.rfc822msgid
        email_date = first_notification.message.datecreated

    for notification in bug_notifications:
        if notification.message == comment:
            # Comments were just handled in the previous if block.
            continue
        text = notification.message.text_contents.rstrip()
        text_notifications.append(text)

    if bug.initial_message.rfc822msgid not in references:
        # Ensure that references contain the initial message ID
        references.insert(0, bug.initial_message.rfc822msgid)

    # At this point we've got the data we need to construct the
    # messages. Now go ahead and actually do that.
    messages = []
    mail_wrapper = MailWrapper(width=72)
    content = '\n\n'.join(text_notifications)
    from_address = get_bugmail_from_address(person, bug)
    # comment_syncing_team can be either None or '' to indicate unset.
    if comment is not None and config.malone.comment_syncing_team:
        # The first time we import comments from a bug watch, a comment
        # notification is added, originating from the Bug Watch Updater.
        bug_watch_updater = getUtility(
            ILaunchpadCelebrities).bug_watch_updater
        is_initial_import_notification = (comment.owner == bug_watch_updater)
        bug_message = getUtility(IBugMessageSet).getByBugAndMessage(
            bug, comment)
        comment_syncing_team = getUtility(IPersonSet).getByName(
            config.malone.comment_syncing_team)
        # Only members of the comment syncing team should get comment
        # notifications related to bug watches or initial comment imports.
        if (is_initial_import_notification or
            (bug_message is not None and bug_message.bugwatch is not None)):
            recipients = dict(
                (email_person, recipient)
                for email_person, recipient in recipients.items()
                if recipient.person.inTeam(comment_syncing_team))
    bug_notification_builder = BugNotificationBuilder(bug)
    sorted_recipients = sorted(
        recipients.items(), key=lambda t: t[0].preferredemail.email)
    for email_person, recipient in sorted_recipients:
        address = str(email_person.preferredemail.email)
        reason = recipient.reason_body
        rationale = recipient.reason_header

        # XXX deryck 2009-11-17 Bug #484319
        # This should be refactored to add a link inside the
        # code where we build `reason`.  However, this will
        # require some extra work, and this small change now
        # will ease pain for a lot of unhappy users.
        if 'direct subscriber' in reason and 'member of' not in reason:
            unsubscribe_notice = ('To unsubscribe from this bug, go to:\n'
                '%s/+subscribe' % canonical_url(bug.bugtasks[0]))
        else:
            unsubscribe_notice = ''

        body_data = {
            'content': mail_wrapper.format(content),
            'bug_title': bug.title,
            'bug_url': canonical_url(bug),
            'unsubscribe_notice': unsubscribe_notice,
            'notification_rationale': mail_wrapper.format(reason)}

        # If the person we're sending to receives verbose notifications
        # we include the description and status of the bug in the email
        # footer.
        if email_person.verbose_bugnotifications:
            email_template = 'bug-notification-verbose.txt'
            body_data['bug_description'] = bug.description

            status_base = "Status in %s: %s"
            status_strings = []
            for bug_task in bug.bugtasks:
                status_strings.append(status_base % (bug_task.target.title,
                    bug_task.status.title))

            body_data['bug_statuses'] = "\n".join(status_strings)
        else:
            email_template = 'bug-notification.txt'

        body = get_email_template(email_template) % body_data
        msg = bug_notification_builder.build(
            from_address, address, body, subject, email_date,
            rationale, references, msgid)
        messages.append(msg)

    return bug_notifications, messages

def _log_exception_and_restart_transaction():
    """Log an exception and restart the current transaction.

    It's important to restart the transaction if an exception occurs,
    since if it's a DB exception, the transaction isn't usable anymore.
    """
    log.exception(
        "An exception was raised while building the email notification.")
    rollback()
    begin()


def get_email_notifications(bug_notifications, date_emailed=None):
    """Return the email notifications pending to be sent.

    The intention of this code is to ensure that as many notifications
    as possible are batched into a single email. The criteria is that
    the notifications:
        - Must share the same owner.
        - Must be related to the same bug.
        - Must contain at most one comment.
    """
    # Avoid spurious lint about possibly undefined loop variables.
    notification = None
    # Copy bug_notifications because we will modify it as we go.
    bug_notifications = list(bug_notifications)
    while bug_notifications:
        found_comment = False
        notification_batch = []
        bug = bug_notifications[0].bug
        person = bug_notifications[0].message.owner
        # What the loop below does is find the largest contiguous set of
        # bug notifications as specified above.
        #
        # Note that we iterate over a copy of the notifications here
        # because we are modifying bug_modifications as we go.
        for notification in list(bug_notifications):
            if notification.is_comment and found_comment:
                # Oops, found a second comment, stop batching.
                break
            if notification.bug != bug:
                # Found a different change, stop batching.
                break
            if notification.message.owner != person:
                # Ah, we've found a change made by somebody else; time
                # to stop batching too.
                break
            notification_batch.append(notification)
            bug_notifications.remove(notification)
            if notification.is_comment:
                found_comment = True

        if date_emailed is not None:
            notification.date_emailed = date_emailed
        # We don't want bugs preventing all bug notifications from
        # being sent, so catch and log all exceptions.
        try:
            yield construct_email_notifications(notification_batch)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            _log_exception_and_restart_transaction()

