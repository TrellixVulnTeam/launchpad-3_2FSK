# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Event handlers that send email notifications."""

__metaclass__ = type

import datetime
from difflib import unified_diff

from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart
from email.MIMEMessage import MIMEMessage
from email.Utils import formatdate

from operator import attrgetter
import re
import rfc822
import textwrap

from zope.component import getUtility
from zope.interface import implements
from zope.security.proxy import isinstance as zope_isinstance

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.components.branch import BranchDelta
from canonical.config import config
from canonical.launchpad.event.interfaces import ISQLObjectModifiedEvent
from canonical.launchpad.interfaces import (
    BranchSubscriptionDiffSize, BranchSubscriptionNotificationLevel,
    IBranch, IBugTask, IEmailAddressSet, INotificationRecipientSet, IPerson,
    ISpecification, ITeamMembershipSet, IUpstreamBugTask, QuestionAction,
    TeamMembershipStatus, UnknownRecipientError)
from canonical.launchpad.mail import (
    sendmail, simple_sendmail, simple_sendmail_from_person, format_address)
from canonical.launchpad.components.bug import BugDelta
from canonical.launchpad.helpers import (
    contactEmailAddresses, get_email_template, shortlist)
from canonical.launchpad.webapp import canonical_url


CC = "CC"


class MailWrapper:
    """Wraps text that should be included in an email.

        :width: how long should the lines be
        :indent: specifies how much indentation the lines should have
        :indent_first_line: indicates whether the first line should be
                            indented or not.

    Note that MailWrapper doesn't guarantee that all lines will be less
    than :width:, sometimes it's better not to break long lines in
    emails. See textformatting.txt for more information.
    """

    def __init__(self, width=72, indent='', indent_first_line=True):
        self.indent = indent
        self.indent_first_line = indent_first_line
        self._text_wrapper = textwrap.TextWrapper(
            width=width, subsequent_indent=indent,
            replace_whitespace=False, break_long_words=False)

    def format(self, text):
        """Format the text to be included in an email."""
        wrapped_lines = []

        if self.indent_first_line:
            indentation = self.indent
        else:
            indentation = ''

        # We don't care about trailing whitespace.
        text = text.rstrip()

        # Normalize dos-style line endings to unix-style.
        text = text.replace('\r\n', '\n')

        for paragraph in text.split('\n\n'):
            lines = paragraph.split('\n')

            if len(lines) == 1:
                # We use TextWrapper only if the paragraph consists of a
                # single line, like in the case where a person enters a
                # comment via the web ui, without breaking the lines
                # manually.
                self._text_wrapper.initial_indent = indentation
                wrapped_lines += self._text_wrapper.wrap(paragraph)
            else:
                # If the user has gone through the trouble of wrapping
                # the lines, we shouldn't re-wrap them for him.
                wrapped_lines += (
                    [indentation + lines[0]] +
                    [self.indent + line for line in lines[1:]])

            if not self.indent_first_line:
                # 'indentation' was temporarily set to '' in order to
                # prevent the first line from being indented. Set it
                # back to self.indent so that the rest of the lines get
                # indented.
                indentation = self.indent

            # Add an empty line so that the paragraphs get separated by
            # a blank line when they are joined together again.
            wrapped_lines.append('')

        # We added one line too much, remove it.
        wrapped_lines = wrapped_lines[:-1]
        return '\n'.join(wrapped_lines)


class NotificationRecipientSet:
    """Set of recipients along the rationale for being in the set."""

    implements(INotificationRecipientSet)

    def __init__(self):
        """Create a new empty set."""
        # We maintain a mapping of person to rationale, as well as a
        # a mapping of all the emails to the person that hold the rationale
        # for that email. That way, adding a person and a team containing
        # that person will preserve the rationale associated when the email
        # was first added.
        self._personToRationale = {}
        self._emailToPerson = {}

    def getEmails(self):
        """See `INotificationRecipientSet`."""
        return sorted(self._emailToPerson.keys())

    def getRecipients(self):
        """See `INotificationRecipientSet`."""
        return sorted(
            self._personToRationale.keys(),  key=attrgetter('displayname'))

    def __iter__(self):
        """See `INotificationRecipientSet`."""
        return iter(self.getRecipients())

    def __contains__(self, person_or_email):
        """See `INotificationRecipientSet`."""
        if zope_isinstance(person_or_email, (str, unicode)):
            return person_or_email in self._emailToPerson
        elif IPerson.providedBy(person_or_email):
            return person_or_email in self._personToRationale
        else:
            return False

    def __nonzero__(self):
        """See `INotificationRecipientSet`."""
        return bool(self._personToRationale)

    def getReason(self, person_or_email):
        """See `INotificationRecipientSet`."""
        if zope_isinstance(person_or_email, basestring):
            try:
                person = self._emailToPerson[person_or_email]
            except KeyError:
                raise UnknownRecipientError(person_or_email)
        elif IPerson.providedBy(person_or_email):
            person = person_or_email
        else:
            raise AssertionError(
                'Not an IPerson or email address: %r' % person_or_email)
        try:
            return self._personToRationale[person]
        except KeyError:
            raise UnknownRecipientError(person)

    def add(self, persons, reason, header):
        """See `INotificationRecipientSet`."""

        if IPerson.providedBy(persons):
            persons = [persons]

        for person in persons:
            assert IPerson.providedBy(person), (
                'You can only add() IPerson: %r' % person)
            # If the person already has a rationale, keep the first one.
            if person in self._personToRationale:
                continue
            self._personToRationale[person] = reason, header
            for email in contactEmailAddresses(person):
                old_person = self._emailToPerson.get(email)
                # Only associate this email to the person, if there was
                # no association or if the previous one was to a team and
                # the newer one is to a person.
                if (old_person is None
                    or (old_person.isTeam() and not person.isTeam())):
                    self._emailToPerson[email] = person

    def update(self, recipient_set):
        """See `INotificationRecipientSet`."""
        for person in recipient_set:
            if person in self._personToRationale:
                continue
            reason, header = recipient_set.getReason(person)
            self.add(person, reason, header)


class BugNotificationRecipients(NotificationRecipientSet):
    """A set of emails and rationales notified for a bug change.

    Each email address registered in a BugNotificationRecipients is
    associated to a string and a header that explain why the address is
    being emailed. For instance, if the email address is that of a
    distribution bug contact for a bug, the string and header will make
    that fact clear.

    The string is meant to be rendered in the email footer. The header
    is meant to be used in an X-Launchpad-Message-Rationale header.

    The first rationale registered for an email address is the one
    which will be used, regardless of other rationales being added
    for it later. This gives us a predictable policy of preserving
    the first reason added to the registry; the callsite should
    ensure that the manipulation of the BugNotificationRecipients
    instance is done in preferential order.

    Instances of this class are meant to be returned by
    IBug.getBugNotificationRecipients().
    """
    implements(INotificationRecipientSet)
    def __init__(self, duplicateof=None):
        """Constructs a new BugNotificationRecipients instance.

        If this bug is a duplicate, duplicateof should be used to
        specify which bug ID it is a duplicate of.

        Note that there are two duplicate situations that are
        important:
          - One is when this bug is a duplicate of another bug:
            the subscribers to the main bug get notified of our
            changes.
          - Another is when the bug we are changing has
            duplicates; in that case, direct subscribers of
            duplicate bugs get notified of our changes.
        These two situations are catered respectively by the
        duplicateof parameter above and the addDupeSubscriber method.
        Don't confuse them!
        """
        NotificationRecipientSet.__init__(self)
        self.duplicateof = duplicateof

    def _addReason(self, person, reason, header):
        """Adds a reason (text and header) for a person.

        It takes care of modifying the message when the person is notified
        via a duplicate.
        """
        if self.duplicateof is not None:
            reason = reason + " (via bug %s)" % self.duplicateof.id
            header = header + " via Bug %s" % self.duplicateof.id
        reason = "You received this bug notification because you %s." % reason
        self.add(person, reason, header)

    def addDupeSubscriber(self, person):
        """Registers a subscriber of a duplicate of this bug."""
        reason = "Subscriber of Duplicate"
        if person.isTeam():
            text = ("are a member of %s, which is a subscriber "
                    "of a duplicate bug" % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a direct subscriber of a duplicate bug"
        self._addReason(person, text, reason)

    def addDirectSubscriber(self, person):
        """Registers a direct subscriber of this bug."""
        reason = "Subscriber"
        if person.isTeam():
            text = ("are a member of %s, which is a direct subscriber"
                    % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a direct subscriber of the bug"
        self._addReason(person, text, reason)

    def addAssignee(self, person):
        """Registers an assignee of a bugtask of this bug."""
        reason = "Assignee"
        if person.isTeam():
            text = ("are a member of %s, which is a bug assignee"
                    % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a bug assignee"
        self._addReason(person, text, reason)

    def addDistroBugContact(self, person, distro):
        """Registers a distribution bug contact for this bug."""
        reason = "Bug Contact (%s)" % distro.displayname
        # All displaynames in these reasons should be changed to bugtargetname
        # (as part of bug 113262) once bugtargetname is finalized for packages
        # (bug 113258). Changing it before then would be excessively
        # disruptive.
        if person.isTeam():
            text = ("are a member of %s, which is the bug contact for %s" %
                (person.displayname, distro.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the bug contact for %s" % distro.displayname
        self._addReason(person, text, reason)

    def addPackageBugContact(self, person, package):
        """Registers a package bug contact for this bug."""
        reason = "Bug Contact (%s)" % package.displayname
        if person.isTeam():
            text = ("are a member of %s, which is a bug contact for %s" %
                (person.displayname, package.displayname))
            reason += " @%s" % person.name
        else:
            text = "are a bug contact for %s" % package.displayname
        self._addReason(person, text, reason)

    def addUpstreamBugContact(self, person, upstream):
        """Registers an upstream bug contact for this bug."""
        reason = "Bug Contact (%s)" % upstream.displayname
        if person.isTeam():
            text = ("are a member of %s, which is the bug contact for %s" %
                (person.displayname, upstream.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the bug contact for %s" % upstream.displayname
        self._addReason(person, text, reason)

    def addUpstreamRegistrant(self, person, upstream):
        """Registers an upstream product registrant for this bug."""
        reason = "Registrant (%s)" % upstream.displayname
        if person.isTeam():
            text = ("are a member of %s, which is the registrant for %s" %
                (person.displayname, upstream.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the registrant for %s" % upstream.displayname
        self._addReason(person, text, reason)


def construct_bug_notification(bug, from_address, address, body, subject,
        email_date, rationale_header=None, references=None, msgid=None):
    """Constructs a MIMEText message based on a bug and a set of headers."""
    msg = MIMEText(body.encode('utf8'), 'plain', 'utf8')
    msg['From'] = from_address
    msg['To'] = address
    msg['Reply-To'] = get_bugmail_replyto_address(bug)
    if references is not None:
        msg['References'] = ' '.join(references)
    msg['Sender'] = config.bounce_address
    msg['Date'] = formatdate(
        rfc822.mktime_tz(email_date.utctimetuple() + (0,)))
    if msgid is not None:
        msg['Message-Id'] = msgid
    subject_prefix = "[Bug %d]" % bug.id
    if subject_prefix in subject:
        msg['Subject'] = subject
    else:
        msg['Subject'] = "%s %s" % (subject_prefix, subject)

    # Add X-Launchpad-Bug headers.
    for bugtask in bug.bugtasks:
        msg.add_header('X-Launchpad-Bug', bugtask.asEmailHeaderValue())

    if rationale_header is not None:
        msg.add_header('X-Launchpad-Message-Rationale', rationale_header)
    return msg


def _send_bug_details_to_new_bugcontacts(
    bug, previous_subscribers, current_subscribers):
    """Send an email containing full bug details to new bug subscribers.

    This function is designed to handle situations where bugtasks get
    reassigned to new products or sourcepackages, and the new bugcontacts
    need to be notified of the bug.
    """
    prev_subs_set = set(previous_subscribers)
    cur_subs_set = set(current_subscribers)
    new_subs = cur_subs_set.difference(prev_subs_set)

    to_addrs = set()
    for new_sub in new_subs:
        to_addrs.update(contactEmailAddresses(new_sub))

    if not to_addrs:
        return

    from_addr = format_address(
        'Launchpad Bug Tracker',
        "%s@%s" % (bug.id, config.launchpad.bugs_domain))
    # Now's a good a time as any for this email; don't use the original
    # reported date for the bug as it will just confuse mailer and
    # recipient.
    email_date = datetime.datetime.now()

    # The new subscriber email is effectively the initial message regarding
    # a new bug. The bug's initial message is used in the References
    # header to establish the message's context in the email client.
    references = [bug.initial_message.rfc822msgid]
    recipients = bug.getBugNotificationRecipients()

    for to_addr in sorted(to_addrs):
        reason, rationale_header = recipients.getReason(to_addr)
        subject, contents = generate_bug_add_email(
            bug, new_recipients=True, reason=reason)
        msg = construct_bug_notification(
            bug, from_addr, to_addr, contents, subject, email_date,
            rationale_header=rationale_header, references=references)
        sendmail(msg)


def update_security_contact_subscriptions(modified_bugtask, event):
    """Subscribe the new security contact when a bugtask's product changes.

    No change is made for private bugs.
    """
    if event.object.bug.private:
        return

    if not IUpstreamBugTask.providedBy(event.object):
        return

    bugtask_before_modification = event.object_before_modification
    bugtask_after_modification = event.object

    if (bugtask_before_modification.product !=
        bugtask_after_modification.product):
        new_product = bugtask_after_modification.product
        if new_product.security_contact:
            bugtask_after_modification.bug.subscribe(
                new_product.security_contact)


def get_bugmail_from_address(person, bug):
    """Returns the right From: address to use for a bug notification."""
    if person.preferredemail is not None:
        return format_address(person.displayname, person.preferredemail.email)

    # XXX: Bjorn Tillenius 2006-04-05:
    # The person doesn't have a preferred email set, but he
    # added a comment (either via the email UI, or because he was
    # imported as a deaf reporter). It shouldn't be possible to use the
    # email UI if you don't have a preferred email set, but work around
    # it for now by trying hard to find the right email address to use.
    email_addresses = shortlist(
        getUtility(IEmailAddressSet).getByPerson(person))
    if not email_addresses:
        # XXX: Bjorn Tillenius 2006-05-21:
        # A user should always have at least one email address,
        # but due to bug 33427, this isn't always the case.
        return format_address(person.displayname,
            "%s@%s" % (bug.id, config.launchpad.bugs_domain))

    # At this point we have no validated emails to use: if any of the
    # person's emails had been validated the preferredemail would be
    # set. Since we have no idea of which email address is best to use,
    # we choose the first one.
    return format_address(person.displayname, email_addresses[0].email)


def get_bugmail_replyto_address(bug):
    """Return an appropriate bugmail Reply-To address.

    :bug: the IBug.

    :user: an IPerson whose name will appear in the From address, e.g.:

        From: Foo Bar via Malone <123@bugs...>
    """
    return u"Bug %d <%s@%s>" % (bug.id, bug.id, config.launchpad.bugs_domain)


def get_bugmail_error_address():
    """Return a suitable From address for a bug transaction error email."""
    return config.malone.bugmail_error_from_address


def send_process_error_notification(to_address, subject, error_msg,
                                    original_msg, failing_command=None):
    """Send a mail about an error occurring while using the email interface.

    Tells the user that an error was encountered while processing his
    request and attaches the original email which caused the error to
    happen.

        :to_address: The address to send the notification to.
        :subject: The subject of the notification.
        :error_msg: The error message that explains the error.
        :original_msg: The original message sent by the user.
        :failing_command: The command that caused the error to happen.
    """
    if failing_command is not None:
        failed_command_information = 'Failing command:\n    %s' % str(
            failing_command)
    else:
        failed_command_information = ''

    body = get_email_template('email-processing-error.txt') % {
            'failed_command_information': failed_command_information,
            'error_msg': error_msg}
    mailwrapper = MailWrapper(width=72)
    body = mailwrapper.format(body)
    error_part = MIMEText(body.encode('utf-8'), 'plain', 'utf-8')

    msg = MIMEMultipart()
    msg['To'] = to_address
    msg['From'] = get_bugmail_error_address()
    msg['Subject'] = subject
    msg.attach(error_part)
    msg.attach(MIMEMessage(original_msg))
    sendmail(msg)


def notify_errors_list(message, file_alias_url):
    """Sends an error to the Launchpad errors list."""
    template = get_email_template('notify-unhandled-email.txt')
    # We add the error message in as a header too
    # (X-Launchpad-Unhandled-Email) so we can create filters in the
    # Launchpad-Error-Reports Mailman mailing list.
    simple_sendmail(
        get_bugmail_error_address(), [config.launchpad.errors_address],
        'Unhandled Email: %s' % file_alias_url,
        template % {'url': file_alias_url, 'error_msg': message},
        headers={'X-Launchpad-Unhandled-Email': message}
        )


def generate_bug_add_email(bug, new_recipients=False, reason=None):
    """Generate a new bug notification from the given IBug.

    If new_recipients is supplied we generate a notification explaining
    that the new recipients have been subscribed to the bug. Otherwise
    it's just a notification of a new bug report.
    """
    subject = u"[Bug %d] %s" % (bug.id, bug.title)

    if bug.private:
        # This is a confidential bug.
        visibility = u"Private"
    else:
        # This is a public bug.
        visibility = u"Public"

    bug_info = []
    # Add information about the affected upstreams and packages.
    for bugtask in bug.bugtasks:
        bug_info.append(u"** Affects: %s" % bugtask.bugtargetname)
        bug_info.append(u"     Importance: %s" % bugtask.importance.title)

        if bugtask.assignee:
            # There's a person assigned to fix this task, so show that
            # information too.
            bug_info.append(
                u"     Assignee: %s" % bugtask.assignee.displayname)
        bug_info.append(u"         Status: %s\n" % bugtask.status.title)

    if bug.tags:
        bug_info.append('\n** Tags: %s' % ' '.join(bug.tags))

    mailwrapper = MailWrapper(width=72)
    if new_recipients:
        contents = ("You have been subscribed to a %(visibility)s bug:\n\n"
                    "%(description)s\n\n%(bug_info)s")
        # The visibility appears mid-phrase so.. hack hack.
        visibility = visibility.lower()
        # XXX: kiko, 2007-03-21:
        # We should really have a centralized way of adding this
        # footer, but right now we lack a INotificationRecipientSet
        # for this particular situation.
        contents += (
            "\n-- \n%(bug_title)s\n%(bug_url)s\n%(notification_rationale)s")
    else:
        contents = ("%(visibility)s bug reported:\n\n"
                    "%(description)s\n\n%(bug_info)s")

    contents = contents % {
        'visibility' : visibility, 'bug_url' : canonical_url(bug),
        'bug_info': "\n".join(bug_info), 'bug_title': bug.title,
        'description': mailwrapper.format(bug.description),
        'notification_rationale': reason}

    contents = contents.rstrip()

    return (subject, contents)


def get_unified_diff(old_text, new_text, text_width):
    r"""Return a unified diff of the two texts.

    Before the diff is produced, the texts are wrapped to the given text
    width.

        >>> print get_unified_diff(
        ...     'Some text\nAnother line\n',
        ...     'Some more text\nAnother line\n',
        ...     text_width=72)
        - Some text
        + Some more text
          Another line

    """
    mailwrapper = MailWrapper(width=72)
    old_text_wrapped = mailwrapper.format(old_text or '')
    new_text_wrapped = mailwrapper.format(new_text or '')

    lines_of_context = len(old_text_wrapped.splitlines())
    text_diff = unified_diff(
        old_text_wrapped.splitlines(),
        new_text_wrapped.splitlines(),
        n=lines_of_context)
    # Remove the diff header, which consists of the first three
    # lines.
    text_diff = list(text_diff)[3:]
    # Let's simplify the diff output by removing the helper lines,
    # which begin with '?'.
    text_diff = [
        diff_line for diff_line in text_diff
        if not diff_line.startswith('?')
        ]
    # Add a whitespace between the +/- and the text line.
    text_diff = [
        re.sub('^([\+\- ])(.*)', r'\1 \2', line)
        for line in text_diff
        ]
    text_diff = '\n'.join(text_diff)
    return text_diff


def get_bug_edit_notification_texts(bug_delta):
    """Generate a list of edit notification texts based on the bug_delta.

    bug_delta is an object that provides IBugDelta. The return value
    is a list of unicode strings.
    """
    # figure out what's been changed; add that information to the
    # list as appropriate
    changes = []
    if bug_delta.duplicateof is not None:
        new_bug_dupe = bug_delta.duplicateof['new']
        old_bug_dupe = bug_delta.duplicateof['old']
        assert new_bug_dupe is not None or old_bug_dupe is not None
        assert new_bug_dupe != old_bug_dupe
        if old_bug_dupe is not None:
            change_info = (
                u"** This bug is no longer a duplicate of bug %d\n" %
                    old_bug_dupe.id)
            change_info += u'   %s' % old_bug_dupe.title
            changes.append(change_info)
        if new_bug_dupe is not None:
            change_info = (
                u"** This bug has been marked a duplicate of bug %d\n" %
                    new_bug_dupe.id)
            change_info += '   %s' % new_bug_dupe.title
            changes.append(change_info)

    if bug_delta.title is not None:
        change_info = u"** Summary changed:\n\n"
        change_info += u"- %s\n" % bug_delta.title['old']
        change_info += u"+ %s" % bug_delta.title['new']
        changes.append(change_info)

    if bug_delta.description is not None:
        description_diff = get_unified_diff(
            bug_delta.description['old'],
            bug_delta.description['new'], 72)

        change_info = u"** Description changed:\n\n"
        change_info += description_diff
        changes.append(change_info)

    if bug_delta.private is not None:
        if bug_delta.private['new']:
            visibility = "Private"
        else:
            visibility = "Public"
        changes.append(u"** Visibility changed to: %s" % visibility)

    if bug_delta.security_related is not None:
        if bug_delta.security_related['new']:
            changes.append(
                u"** This bug has been flagged as a security issue")
        else:
            changes.append(
                u"** This bug is no longer flagged as a security issue")

    if bug_delta.tags is not None:
        new_tags = set(bug_delta.tags['new'])
        old_tags = set(bug_delta.tags['old'])
        added_tags = sorted(new_tags.difference(old_tags))
        removed_tags = sorted(old_tags.difference(new_tags))
        if added_tags:
            changes.append(u'** Tags added: %s' % ' '.join(added_tags))
        if removed_tags:
            changes.append(u'** Tags removed: %s' % ' '.join(removed_tags))

    if bug_delta.external_reference is not None:
        old_ext_ref = bug_delta.external_reference.get('old')
        if old_ext_ref is not None:
            changes.append(u'** Web link removed: %s' % old_ext_ref.url)
        new_ext_ref = bug_delta.external_reference['new']
        if new_ext_ref is not None:
            changes.append(u'** Web link added: %s' % new_ext_ref.url)

    if bug_delta.bugwatch is not None:
        old_bug_watch = bug_delta.bugwatch.get('old')
        if old_bug_watch:
            change_info = u"** Bug watch removed: %s #%s\n" % (
                old_bug_watch.bugtracker.title, old_bug_watch.remotebug)
            change_info += u"   %s" % old_bug_watch.url
            changes.append(change_info)
        new_bug_watch = bug_delta.bugwatch['new']
        if new_bug_watch:
            change_info = u"** Bug watch added: %s #%s\n" % (
                new_bug_watch.bugtracker.title, new_bug_watch.remotebug)
            change_info += u"   %s" % new_bug_watch.url
            changes.append(change_info)

    if bug_delta.cve is not None:
        new_cve = bug_delta.cve.get('new', None)
        old_cve = bug_delta.cve.get('old', None)
        if old_cve:
            changes.append(u"** CVE removed: %s" % old_cve.url)
        if new_cve:
            changes.append(u"** CVE added: %s" % new_cve.url)

    if bug_delta.attachment is not None and bug_delta.attachment['new']:
        added_attachment = bug_delta.attachment['new']
        change_info = '** Attachment added: "%s"\n' % added_attachment.title
        change_info += "   %s" % added_attachment.libraryfile.http_url
        changes.append(change_info)

    if bug_delta.bugtask_deltas is not None:
        bugtask_deltas = bug_delta.bugtask_deltas
        # Use zope_isinstance, to ensure that this Just Works with
        # security-proxied objects.
        if not zope_isinstance(bugtask_deltas, (list, tuple)):
            bugtask_deltas = [bugtask_deltas]
        for bugtask_delta in bugtask_deltas:
            change_info = u"** Changed in: %s\n" % (
                bugtask_delta.bugtask.bugtargetname)

            for fieldname, displayattrname in (
                ("product", "displayname"), ("sourcepackagename", "name"),
                ("importance", "title"), ("bugwatch", "title")):
                change = getattr(bugtask_delta, fieldname)
                if change:
                    oldval_display, newval_display = _get_task_change_values(
                        change, displayattrname)
                    change_info += _get_task_change_row(
                        fieldname, oldval_display, newval_display)

            if bugtask_delta.assignee is not None:
                oldval_display = u"(unassigned)"
                newval_display = u"(unassigned)"
                if bugtask_delta.assignee.get('old'):
                    oldval_display = bugtask_delta.assignee['old'].browsername
                if bugtask_delta.assignee.get('new'):
                    newval_display = bugtask_delta.assignee['new'].browsername

                changerow = (
                    u"%(label)13s: %(oldval)s => %(newval)s\n" % {
                    'label' : u"Assignee", 'oldval' : oldval_display,
                    'newval' : newval_display})
                change_info += changerow

            for fieldname, displayattrname in (
                ("status", "title"), ("target", "name")):
                change = getattr(bugtask_delta, fieldname)
                if change:
                    oldval_display, newval_display = _get_task_change_values(
                        change, displayattrname)
                    change_info += _get_task_change_row(
                        fieldname, oldval_display, newval_display)
            changes.append(change_info.rstrip())

    if bug_delta.added_bugtasks is not None:
        # Use zope_isinstance, to ensure that this Just Works with
        # security-proxied objects.
        if zope_isinstance(bug_delta.added_bugtasks, (list, tuple)):
            added_bugtasks = bug_delta.added_bugtasks
        else:
            added_bugtasks = [bug_delta.added_bugtasks]

        for added_bugtask in added_bugtasks:
            if added_bugtask.bugwatch:
                change_info = u"** Also affects: %s via\n" % (
                    added_bugtask.bugtargetname)
                change_info += u"   %s\n" % added_bugtask.bugwatch.url
            else:
                change_info = u"** Also affects: %s\n" % (
                    added_bugtask.bugtargetname)
            change_info += u"%13s: %s\n" % (u"Importance",
                added_bugtask.importance.title)
            if added_bugtask.assignee:
                assignee = added_bugtask.assignee
                if assignee.preferredemail is not None:
                    change_info += u"%13s: %s <%s>\n" % (
                        u"Assignee", assignee.name, assignee.preferredemail.email)
                else:
                    change_info += u"%13s: %s\n" % (u"Assignee", assignee.name)
            change_info += u"%13s: %s" % (
                u"Status", added_bugtask.status.title)
            changes.append(change_info)

    return changes


def _get_task_change_row(label, oldval_display, newval_display):
    """Return a row formatted for display in task change info."""
    return u"%(label)13s: %(oldval)s => %(newval)s\n" % {
        'label' : label.capitalize(),
        'oldval' : oldval_display,
        'newval' : newval_display}


def _get_task_change_values(task_change, displayattrname):
    """Return the old value and the new value for a task field change."""
    oldval = task_change.get('old')
    newval = task_change.get('new')

    oldval_display = None
    newval_display = None

    if oldval:
        oldval_display = getattr(oldval, displayattrname)
    if newval:
        newval_display = getattr(newval, displayattrname)

    return (oldval_display, newval_display)


def get_bug_delta(old_bug, new_bug, user):
    """Compute the delta from old_bug to new_bug.

    old_bug and new_bug are IBug's. user is an IPerson. Returns an
    IBugDelta if there are changes, or None if there were no changes.
    """
    changes = {}

    for field_name in ("title", "description",  "name", "private",
                       "security_related", "duplicateof", "tags"):
        # fields for which we show old => new when their values change
        old_val = getattr(old_bug, field_name)
        new_val = getattr(new_bug, field_name)
        if old_val != new_val:
            changes[field_name] = {}
            changes[field_name]["old"] = old_val
            changes[field_name]["new"] = new_val

    if changes:
        changes["bug"] = new_bug
        changes["bugurl"] = canonical_url(new_bug)
        changes["user"] = user

        return BugDelta(**changes)
    else:
        return None


def notify_bug_added(bug, event):
    """Send an email notification that a bug was added.

    Event must be an ISQLObjectCreatedEvent.
    """

    bug.addCommentNotification(bug.initial_message)


def notify_bug_modified(modified_bug, event):
    """Notify the Cc'd list that this bug has been modified.

    modified_bug bug must be an IBug. event must be an
    ISQLObjectModifiedEvent.
    """
    bug_delta = get_bug_delta(
        old_bug=event.object_before_modification,
        new_bug=event.object, user=event.user)

    assert bug_delta is not None

    add_bug_change_notifications(bug_delta)


def add_bug_change_notifications(bug_delta):
    """Generate bug notifications and add them to the bug."""
    changes = get_bug_edit_notification_texts(bug_delta)
    for text_change in changes:
        bug_delta.bug.addChangeNotification(
            text_change, person=bug_delta.user)


def notify_bugtask_added(bugtask, event):
    """Notify CC'd list that this bug has been marked as needing fixing
    somewhere else.

    bugtask must be in IBugTask. event must be an
    ISQLObjectModifiedEvent.
    """
    bugtask = event.object

    bug_delta = BugDelta(
        bug=bugtask.bug,
        bugurl=canonical_url(bugtask.bug),
        user=event.user,
        added_bugtasks=bugtask)

    add_bug_change_notifications(bug_delta)


def notify_bugtask_edited(modified_bugtask, event):
    """Notify CC'd subscribers of this bug that something has changed
    on this task.

    modified_bugtask must be an IBugTask. event must be an
    ISQLObjectModifiedEvent.
    """
    bugtask_delta = event.object.getDelta(event.object_before_modification)
    bug_delta = BugDelta(
        bug=event.object.bug,
        bugurl=canonical_url(event.object.bug),
        bugtask_deltas=bugtask_delta,
        user=event.user)

    add_bug_change_notifications(bug_delta)

    previous_subscribers = event.object_before_modification.bug_subscribers
    current_subscribers = event.object.bug_subscribers
    _send_bug_details_to_new_bugcontacts(
        event.object.bug, previous_subscribers, current_subscribers)
    update_security_contact_subscriptions(modified_bugtask, event)


def notify_bug_comment_added(bugmessage, event):
    """Notify CC'd list that a message was added to this bug.

    bugmessage must be an IBugMessage. event must be an
    ISQLObjectCreatedEvent. If bugmessage.bug is a duplicate the
    comment will also be sent to the dup target's subscribers.
    """
    bug = bugmessage.bug
    bug.addCommentNotification(bugmessage.message)


def notify_bug_external_ref_added(ext_ref, event):
    """Notify CC'd list that a new web link has been added for this
    bug.

    ext_ref must be an IBugExternalRef. event must be an
    ISQLObjectCreatedEvent.
    """
    bug_delta = BugDelta(
        bug=ext_ref.bug,
        bugurl=canonical_url(ext_ref.bug),
        user=event.user,
        external_reference={'new' : ext_ref})

    add_bug_change_notifications(bug_delta)


def notify_bug_external_ref_edited(edited_ext_ref, event):
    """Notify CC'd list that a web link has been edited.

    edited_ext_ref must be an IBugExternalRef. event must be an
    ISQLObjectModifiedEvent.
    """
    old = event.object_before_modification
    new = event.object
    if ((old.url != new.url) or (old.title != new.title)):
        # A change was made that's worth sending an edit
        # notification about.
        bug_delta = BugDelta(
            bug=new.bug,
            bugurl=canonical_url(new.bug),
            user=event.user,
            external_reference={'old' : old, 'new' : new})

        add_bug_change_notifications(bug_delta)


def notify_bug_watch_added(watch, event):
    """Notify CC'd list that a new watch has been added for this bug.

    watch must be an IBugWatch. event must be an
    ISQLObjectCreatedEvent.
    """
    bug_delta = BugDelta(
        bug=watch.bug,
        bugurl=canonical_url(watch.bug),
        user=event.user,
        bugwatch={'new' : watch})

    add_bug_change_notifications(bug_delta)


def notify_bug_watch_modified(modified_bug_watch, event):
    """Notify CC'd bug subscribers that a bug watch was edited.

    modified_bug_watch must be an IBugWatch. event must be an
    ISQLObjectModifiedEvent.
    """
    old = event.object_before_modification
    new = event.object
    if ((old.bugtracker != new.bugtracker) or
        (old.remotebug != new.remotebug)):
        # there is a difference worth notifying about here
        # so let's keep going
        bug_delta = BugDelta(
            bug=new.bug,
            bugurl=canonical_url(new.bug),
            user=event.user,
            bugwatch={'old' : old, 'new' : new})

        add_bug_change_notifications(bug_delta)


def notify_bug_cve_added(bugcve, event):
    """Notify CC'd list that a new cve ref has been added to this bug.

    bugcve must be an IBugCve. event must be an ISQLObjectCreatedEvent.
    """
    bug_delta = BugDelta(
        bug=bugcve.bug,
        bugurl=canonical_url(bugcve.bug),
        user=event.user,
        cve={'new': bugcve.cve})

    add_bug_change_notifications(bug_delta)

def notify_bug_cve_deleted(bugcve, event):
    """Notify CC'd list that a cve ref has been removed from this bug.

    bugcve must be an IBugCve. event must be an ISQLObjectDeletedEvent.
    """
    bug_delta = BugDelta(
        bug=bugcve.bug,
        bugurl=canonical_url(bugcve.bug),
        user=event.user,
        cve={'old': bugcve.cve})

    add_bug_change_notifications(bug_delta)


def notify_bug_attachment_added(bugattachment, event):
    """Notify CC'd list that a new attachment has been added.

    bugattachment must be an IBugAttachment. event must be an
    ISQLObjectCreatedEvent.
    """
    bug = bugattachment.bug
    bug_delta = BugDelta(
        bug=bug,
        bugurl=canonical_url(bug),
        user=event.user,
        attachment={'new' : bugattachment})

    add_bug_change_notifications(bug_delta)


def notify_bug_attachment_removed(bugattachment, event):
    """Notify that an attachment has been removed."""
    bug = bugattachment.bug
    # Include the URL, since it will still be downloadable until the
    # Librarian garbage collector removes it.
    change_info = '\n'.join([
        '** Attachment removed: "%s"\n' % bugattachment.title,
        '   %s' %  bugattachment.libraryfile.http_url])
    bug.addChangeNotification(change_info, person=event.user)


def notify_invitation_to_join_team(event):
    """Notify team admins that the team has been invited to join another team.

    The notification will include a link to a page in which any team admin can
    accept the invitation.

    XXX: Guilherme Salgado 2007-05-08:
    At some point we may want to extend this functionality to allow invites
    to be sent to users as well, but for now we only use it for teams.
    """
    member = event.member
    assert member.isTeam()
    team = event.team
    membership = getUtility(ITeamMembershipSet).getByPersonAndTeam(
        member, team)
    assert membership is not None

    reviewer = membership.reviewer
    admin_addrs = member.getTeamAdminsEmailAddresses()
    from_addr = format_address('Launchpad', config.noreply_from_address)
    subject = (
        'Launchpad: %s was invited to join %s' % (member.name, team.name))
    templatename = 'membership-invitation.txt'
    template = get_email_template(templatename)
    msg = template % {
        'reviewer': '%s (%s)' % (reviewer.browsername, reviewer.name),
        'member': '%s (%s)' % (member.browsername, member.name),
        'team': '%s (%s)' % (team.browsername, team.name),
        'membership_invitations_url':
            "%s/+invitation/%s" % (canonical_url(member), team.name)}
    msg = MailWrapper().format(msg)
    simple_sendmail(from_addr, admin_addrs, subject, msg)


def notify_team_join(event):
    """Notify team admins that a new person choose to join the team.

    If the team's policy is Moderated, the email will say that the membership
    is pending approval. Otherwise it'll say that the person has joined the
    team and who added that person to the team.
    """
    person = event.person
    team = event.team
    membership = getUtility(ITeamMembershipSet).getByPersonAndTeam(
        person, team)
    assert membership is not None
    reviewer = membership.reviewer
    approved, admin, proposed = [
        TeamMembershipStatus.APPROVED, TeamMembershipStatus.ADMIN,
        TeamMembershipStatus.PROPOSED]
    admin_addrs = team.getTeamAdminsEmailAddresses()

    from_addr = format_address('Launchpad', config.noreply_from_address)

    if reviewer != person and membership.status in [approved, admin]:
        # Somebody added this person as a member, we better send a
        # notification to the person too.
        member_addrs = contactEmailAddresses(person)

        subject = (
            'Launchpad: %s is now a member of %s' % (person.name, team.name))
        templatename = 'new-member-notification.txt'
        if person.isTeam():
            templatename = 'new-member-notification-for-teams.txt'

        template = get_email_template(templatename)
        msg = template % {
            'reviewer': '%s (%s)' % (reviewer.browsername, reviewer.name),
            'member': '%s (%s)' % (person.browsername, person.name),
            'team': '%s (%s)' % (team.browsername, team.name)}
        msg = MailWrapper().format(msg)
        simple_sendmail(from_addr, member_addrs, subject, msg)

        # The member's email address may be in admin_addrs too; let's remove
        # it so the member don't get two notifications.
        admin_addrs = set(admin_addrs).difference(set(member_addrs))

    # Yes, we can have teams with no members; not even admins.
    if not admin_addrs:
        return

    replacements = {
        'person_name': "%s (%s)" % (person.browsername, person.name),
        'team_name': "%s (%s)" % (team.browsername, team.name),
        'reviewer_name': "%s (%s)" % (reviewer.browsername, reviewer.name),
        'url': canonical_url(membership)}

    headers = {}
    if membership.status in [approved, admin]:
        template = get_email_template(
            'new-member-notification-for-admins.txt')
        subject = (
            'Launchpad: %s is now a member of %s' % (person.name, team.name))
    elif membership.status == proposed:
        template = get_email_template('pending-membership-approval.txt')
        subject = (
            "Launchpad: %s wants to join team %s" % (person.name, team.name))
        headers = {"Reply-To": person.preferredemail.email}
    else:
        raise AssertionError(
            "Unexpected membership status: %s" % membership.status)

    msg = MailWrapper().format(template % replacements)
    simple_sendmail(from_addr, admin_addrs, subject, msg, headers=headers)


def dispatch_linked_question_notifications(bugtask, event):
    """Send notifications to linked question subscribers when the bugtask
    status change.
    """
    for question in bugtask.bug.questions:
        QuestionLinkedBugStatusChangeNotification(question, event)


class QuestionNotification:
    """Base class for a notification related to a question.

    Creating an instance of that class will build the notification and
    send it to the appropriate recipients. That way, subclasses of
    QuestionNotification can be registered as event subscribers.
    """

    def __init__(self, question, event):
        """Base constructor.

        It saves the question and event in attributes and then call
        the initialize() and send() method.
        """
        self.question = question
        self.event = event
        self.initialize()
        if self.shouldNotify():
            self.send()

    def getFromAddress(self):
        """Return a formatted email address suitable for user in the From
        header of the question notification.

        Default is Event Person Display Name <question#@answertracker_domain>
        """
        return format_address(
            self.event.user.displayname,
            'question%s@%s' % (
                self.question.id, config.answertracker.email_domain))

    def getSubject(self):
        """Return the subject of the notification.

        Default to [Question #dd]: Title
        """
        return '[Question #%s]: %s' % (self.question.id, self.question.title)

    def getBody(self):
        """Return the content of the notification message.

        This method must be implemented by a subclass.
        """
        raise NotImplementedError

    def getHeaders(self):
        """Return additional headers to add to the email.

        Default implementation adds a X-Launchpad-Question header.
        """
        question = self.question
        headers = dict()
        if self.question.distribution:
            if question.sourcepackagename:
                sourcepackage = question.sourcepackagename.name
            else:
                sourcepackage = 'None'
            target = 'distribution=%s; sourcepackage=%s;' % (
                question.distribution.name, sourcepackage)
        else:
            target = 'product=%s;' % question.product.name
        if question.assignee:
            assignee = question.assignee.name
        else:
            assignee = 'None'

        headers['X-Launchpad-Question'] = (
            '%s status=%s; assignee=%s; priority=%s; language=%s' % (
                target, question.status.title, assignee,
                question.priority.title, question.language.code))

        return headers

    def getRecipients(self):
        """Return the recipient of the notification.

        Default to the question's subscribers that speaks the request
        languages. If the question owner is subscribed, he's always consider
        to speak the language.

        :return: A `INotificationRecipientSet` containing the recipients and
                 rationale.
        """
        return self.question.getSubscribers()

    def initialize(self):
        """Initialization hook for subclasses.

        This method is called before send() and can be use for any
        setup purpose.

        Default does nothing.
        """
        pass

    def shouldNotify(self):
        """Return if there is something to notify about.

        When this method returns False, no notification will be sent.
        By default, all event trigger a notification.
        """
        return True

    def send(self):
        """Sends the notification to all the notification recipients.

        This method takes care of adding the rationale for contacting each
        recipient and also sets the X-Launchpad-Message-Rationale header on
        each message.
        """
        from_address = self.getFromAddress()
        subject = self.getSubject()
        body = self.getBody()
        headers = self.getHeaders()
        recipients = self.getRecipients()
        wrapper = MailWrapper()
        for email in recipients.getEmails():
            rationale, header = recipients.getReason(email)
            headers['X-Launchpad-Message-Rationale'] = header
            body_parts = [body, wrapper.format(rationale)]
            if '-- ' not in body:
                body_parts.insert(1, '-- ')
            simple_sendmail(
                from_address, email, subject, '\n'.join(body_parts), headers)

    @property
    def unsupported_language(self):
        """Whether the question language is unsupported or not."""
        supported_languages = self.question.target.getSupportedLanguages()
        return self.question.language not in supported_languages

    @property
    def unsupported_language_warning(self):
        """Warning about the fact that the question is written in an
        unsupported language."""
        return get_email_template(
                'question-unsupported-language-warning.txt') % {
                'question_language': self.question.language.englishname,
                'target_name': self.question.target.displayname}


class QuestionAddedNotification(QuestionNotification):
    """Notification sent when a question is added."""

    def getBody(self):
        """See QuestionNotification."""
        question = self.question
        body = get_email_template('question-added-notification.txt') % {
            'target_name': question.target.displayname,
            'question_id': question.id,
            'question_url': canonical_url(question),
            'comment': question.description}
        if self.unsupported_language:
            body += self.unsupported_language_warning
        return body


class QuestionModifiedDefaultNotification(QuestionNotification):
    """Base implementation of a notification when a question is modified."""

    # Email template used to render the body.
    body_template = "question-modified-notification.txt"

    def initialize(self):
        """Save the old question for comparison. It also set the new_message
        attribute if a new message was added.
        """
        self.old_question = self.event.object_before_modification

        new_messages = set(
            self.question.messages).difference(self.old_question.messages)
        assert len(new_messages) <= 1, (
                "There shouldn't be more than one message for a "
                "notification.")
        if new_messages:
            self.new_message = new_messages.pop()
        else:
            self.new_message = None

        self.wrapper = MailWrapper()

    @cachedproperty
    def metadata_changes_text(self):
        """Textual representation of the changes to the question metadata."""
        question = self.question
        old_question = self.old_question
        indent = 4*' '
        info_fields = []
        if question.status != old_question.status:
            info_fields.append(indent + 'Status: %s => %s' % (
                old_question.status.title, question.status.title))
        if question.target != old_question.target:
            info_fields.append(
                indent + 'Project: %s => %s' % (
                old_question.target.displayname, question.target.displayname))

        old_bugs = set(old_question.bugs)
        bugs = set(question.bugs)
        for linked_bug in bugs.difference(old_bugs):
            info_fields.append(
                indent + 'Linked to bug: #%s\n' % linked_bug.id +
                indent + '%s\n' % canonical_url(linked_bug) +
                indent + '"%s"' % linked_bug.title)
        for unlinked_bug in old_bugs.difference(bugs):
            info_fields.append(
                indent + 'Removed link to bug: #%s\n' % unlinked_bug.id +
                indent + '%s\n' % canonical_url(unlinked_bug) +
                indent + '"%s"' % unlinked_bug.title)

        if question.faq != old_question.faq:
            if question.faq is None:
                info_fields.append(
                    indent + 'Related FAQ was removed:\n' +
                    indent + old_question.faq.title + '\n' +
                    indent + canonical_url(old_question.faq))
            else:
                info_fields.append(
                    indent + 'Related FAQ set to:\n' +
                    indent + question.faq.title + '\n' +
                    indent + canonical_url(question.faq))

        if question.title != old_question.title:
            info_fields.append('Summary changed to:\n%s' % question.title)
        if question.description != old_question.description:
            info_fields.append(
                'Description changed to:\n%s' % (
                    self.wrapper.format(question.description)))

        question_changes = '\n\n'.join(info_fields)
        return question_changes

    def getSubject(self):
        """When a comment is added, its title is used as the subject,
        otherwise the question title is used.
        """
        prefix = '[Question #%s]: ' % self.question.id
        if self.new_message:
            # Migrate old prefix.
            subject = self.new_message.subject.replace(
                '[Support #%s]: ' % self.question.id, prefix)
            if prefix in subject:
                return subject
            elif subject[0:4] in ['Re: ', 'RE: ', 're: ']:
                # Place prefix after possible reply prefix.
                return subject[0:4] + prefix + subject[4:]
            else:
                return prefix + subject
        else:
            return prefix + self.question.title

    def getHeaders(self):
        """Add a References header."""
        headers = QuestionNotification.getHeaders(self)
        if self.new_message:
            # XXX flacoste 2007-02-02 bug=83846: 
            # The first message cannot contain a References
            # because we don't create a Message instance for the
            # question description, so we don't have a Message-ID.
            index = list(self.question.messages).index(self.new_message)
            if index > 0:
                headers['References'] = (
                    self.question.messages[index-1].rfc822msgid)
        return headers

    def shouldNotify(self):
        """Only send a notification when a message was added or some
        metadata was changed.
        """
        return self.new_message or self.metadata_changes_text

    def getBody(self):
        """See QuestionNotification."""
        body = self.metadata_changes_text
        replacements = dict(
            question_id=self.question.id,
            target_name=self.question.target.displayname,
            question_url=canonical_url(self.question))

        if self.new_message:
            if body:
                body += '\n\n'
            body += self.getNewMessageText()
            replacements['new_message_id'] = list(
                self.question.messages).index(self.new_message)

        replacements['body'] = body

        return get_email_template(self.body_template) % replacements

    def getRecipients(self):
        """The default notification goes to all question subscribers that
        speak the request language, except the owner.
        """
        original_recipients = QuestionNotification.getRecipients(self)
        recipients = NotificationRecipientSet()
        owner = self.question.owner
        for person in original_recipients:
            if person != self.question.owner:
                rationale, header = original_recipients.getReason(person)
                recipients.add(person, rationale, header)
        return recipients

    # Header template used when a new message is added to the question.
    action_header_template = {
        QuestionAction.REQUESTINFO:
            '%(person)s requested for more information:',
        QuestionAction.CONFIRM:
            '%(person)s confirmed that the question is solved:',
        QuestionAction.COMMENT:
            '%(person)s posted a new comment:',
        QuestionAction.GIVEINFO:
            '%(person)s gave more information on the question:',
        QuestionAction.REOPEN:
            '%(person)s is still having a problem:',
        QuestionAction.ANSWER:
            '%(person)s proposed the following answer:',
        QuestionAction.EXPIRE:
            '%(person)s expired the question:',
        QuestionAction.REJECT:
            '%(person)s rejected the question:',
        QuestionAction.SETSTATUS:
            '%(person)s changed the question status:',
    }

    def getNewMessageText(self):
        """Should return the notification text related to a new message."""
        if not self.new_message:
            return ''

        header = self.action_header_template.get(
            self.new_message.action, '%(person)s posted a new message:') % {
            'person': self.new_message.owner.displayname}

        return '\n'.join([
            header, self.wrapper.format(self.new_message.text_contents)])


class QuestionModifiedOwnerNotification(QuestionModifiedDefaultNotification):
    """Notification sent to the owner when his question is modified."""

    # These actions will be done by the owner, so use the second person.
    action_header_template = dict(
        QuestionModifiedDefaultNotification.action_header_template)
    action_header_template.update({
        QuestionAction.CONFIRM:
            'You confirmed that the question is solved:',
        QuestionAction.GIVEINFO:
            'You gave more information on the question:',
        QuestionAction.REOPEN:
            'You are still having a problem:',
        })

    body_template = 'question-modified-owner-notification.txt'

    body_template_by_action = {
        QuestionAction.ANSWER: "question-answered-owner-notification.txt",
        QuestionAction.EXPIRE: "question-expired-owner-notification.txt",
        QuestionAction.REJECT: "question-rejected-owner-notification.txt",
        QuestionAction.REQUESTINFO: (
            "question-info-requested-owner-notification.txt"),
    }

    def initialize(self):
        """Set the template based on the new comment action."""
        QuestionModifiedDefaultNotification.initialize(self)
        if self.new_message:
            self.body_template = self.body_template_by_action.get(
                self.new_message.action, self.body_template)

    def getRecipients(self):
        """Return the owner of the question if he's still subscribed."""
        recipients = NotificationRecipientSet()
        owner = self.question.owner
        if self.question.isSubscribed(owner):
            original_recipients = self.question.getDirectSubscribers()
            rationale, header = original_recipients.getReason(owner)
            recipients.add(owner, rationale, header)
        return recipients

    def getBody(self):
        """See QuestionNotification."""
        body = QuestionModifiedDefaultNotification.getBody(self)
        if self.unsupported_language:
            body += self.unsupported_language_warning
        return body


class QuestionUnsupportedLanguageNotification(QuestionNotification):
    """Notification sent to answer contacts for unsupported languages."""

    def getSubject(self):
        """See QuestionNotification."""
        return '[Question #%s]: (%s) %s' % (
            self.question.id, self.question.language.englishname,
            self.question.title)

    def shouldNotify(self):
        """Return True when the question is in an unsupported language."""
        return self.unsupported_language

    def getRecipients(self):
        """Notify only the answer contacts."""
        return self.question.target.getAnswerContactRecipients(None)

    def getBody(self):
        """See QuestionNotification."""
        question = self.question
        return get_email_template(
                'question-unsupported-languages-added.txt') % {
            'target_name': question.target.displayname,
            'question_id': question.id,
            'question_url': canonical_url(question),
            'question_language': question.language.englishname,
            'comment': question.description}


class QuestionLinkedBugStatusChangeNotification(QuestionNotification):
    """Notification sent when a linked bug status is changed."""

    def initialize(self):
        """Create a notifcation for a linked bug status change."""
        assert ISQLObjectModifiedEvent.providedBy(self.event), (
            "Should only be subscribed for ISQLObjectModifiedEvent.")
        assert IBugTask.providedBy(self.event.object), (
            "Should only be subscribed for IBugTask modification.")
        self.bugtask = self.event.object
        self.old_bugtask = self.event.object_before_modification

    def shouldNotify(self):
        """Only send notification when the status changed."""
        return self.bugtask.status != self.old_bugtask.status

    def getSubject(self):
        """See QuestionNotification."""
        return "[Question #%s]: Status of bug #%s changed to '%s' in %s" % (
            self.question.id, self.bugtask.bug.id, self.bugtask.status.title,
            self.bugtask.target.displayname)

    def getBody(self):
        """See QuestionNotification."""
        if self.bugtask.statusexplanation:
            wrapper = MailWrapper()
            statusexplanation = (
                'Status change explanation given by %s:\n\n%s\n' % (
                    self.event.user.displayname,
                    wrapper.format(self.bugtask.statusexplanation)))
        else:
            statusexplanation = ''

        return get_email_template(
            'question-linked-bug-status-updated.txt') % {
                'bugtask_target_name': self.bugtask.target.displayname,
                'question_id': self.question.id,
                'question_title':self.question.title,
                'question_url': canonical_url(self.question),
                'bugtask_url':canonical_url(self.bugtask),
                'bug_id': self.bugtask.bug.id,
                'bugtask_title': self.bugtask.bug.title,
                'old_status': self.old_bugtask.status.title,
                'new_status': self.bugtask.status.title,
                'statusexplanation': statusexplanation}


def specification_notification_subject(spec):
    """Format the email subject line for a specification."""
    return '[Blueprint %s] %s' % (spec.name, spec.title)

def notify_specification_modified(spec, event):
    """Notify the related people that a specification has been modifed."""
    spec_delta = spec.getDelta(event.object_before_modification, event.user)
    if spec_delta is None:
        # XXX: Bjorn Tillenius 2006-03-08:
        #      Ideally, if an ISQLObjectModifiedEvent event is generated,
        #      spec_delta shouldn't be None. I'm not confident that we
        #      have enough test yet to assert this, though.
        return

    subject = specification_notification_subject(spec)
    indent = ' '*4
    info_lines = []
    for dbitem_name in ('definition_status', 'priority'):
        title = ISpecification[dbitem_name].title
        assert ISpecification[dbitem_name].required, (
            "The mail notification assumes %s can't be None" % dbitem_name)
        dbitem_delta = getattr(spec_delta, dbitem_name)
        if dbitem_delta is not None:
            old_item = dbitem_delta['old']
            new_item = dbitem_delta['new']
            info_lines.append("%s%s: %s => %s" % (
                indent, title, old_item.title, new_item.title))

    for person_attrname in ('approver', 'assignee', 'drafter'):
        title = ISpecification[person_attrname].title
        person_delta = getattr(spec_delta, person_attrname)
        if person_delta is not None:
            old_person = person_delta['old']
            if old_person is None:
                old_value = "(none)"
            else:
                old_value = old_person.displayname
            new_person = person_delta['new']
            if new_person is None:
                new_value = "(none)"
            else:
                new_value = new_person.displayname
            info_lines.append(
                "%s%s: %s => %s" % (indent, title, old_value, new_value))

    mail_wrapper = MailWrapper(width=72)
    if spec_delta.whiteboard is not None:
        if info_lines:
            info_lines.append('')
        info_lines.append('Whiteboard changed to:')
        info_lines.append('')
        info_lines.append(mail_wrapper.format(spec_delta.whiteboard))

    if not info_lines:
        # The specification was modified, but we don't yet support
        # sending notification for the change.
        return
    body = get_email_template('specification-modified.txt') % {
        'editor': event.user.displayname,
        'info_fields': '\n'.join(info_lines),
        'spec_title': spec.title,
        'spec_url': canonical_url(spec)}

    for address in spec.notificationRecipientAddresses():
        simple_sendmail_from_person(event.user, address, subject, body)


def email_branch_modified_notifications(branch, to_addresses,
                                        from_address, contents,
                                        recipients):
    """Send notification emails using the branch email template.

    Emails are sent one at a time to the listed addresses.
    """
    branch_title = branch.title
    if branch_title is None:
        branch_title = ''
    subject = '[Branch %s] %s' % (branch.unique_name, branch_title)
    headers = {'X-Launchpad-Branch': branch.unique_name}

    template = get_email_template('branch-modified.txt')
    params = {
        'contents': contents,
        'branch_title': branch_title,
        'branch_url': canonical_url(branch),
         }
    for address in to_addresses:
        subscription, rationale = recipients.getReason(address)
        if subscription.person.isTeam():
            params['unsubscribe_url'] = canonical_url(subscription)
        else:
            params['unsubscribe_url'] = (
                canonical_url(branch) + '/+edit-subscription')
        headers['X-Launchpad-Message-Rationale'] = rationale

        body = template % params
        simple_sendmail(from_address, address, subject, body, headers)


def send_branch_revision_notifications(branch, from_address, message, diff):
    """Notify subscribers that a revision has been added (or removed)."""
    diff_size = diff.count('\n') + 1

    diff_size_to_email = dict(
        [(item, set()) for item in BranchSubscriptionDiffSize.items])

    recipients = branch.getNotificationRecipients()
    interested_levels = (
        BranchSubscriptionNotificationLevel.DIFFSONLY,
        BranchSubscriptionNotificationLevel.FULL)
    for email_address in recipients.getEmails():
        subscription, ignored = recipients.getReason(email_address)
        if subscription.notification_level in interested_levels:
            diff_size_to_email[subscription.max_diff_lines].add(email_address)

    for max_diff in diff_size_to_email:
        addresses = diff_size_to_email[max_diff]
        if len(addresses) == 0:
            continue
        if max_diff != BranchSubscriptionDiffSize.WHOLEDIFF:
            if max_diff == BranchSubscriptionDiffSize.NODIFF:
                contents = message
            elif diff_size > max_diff.value:
                diff_msg = (
                    'The size of the diff (%d lines) is larger than your '
                    'specified limit of %d lines' % (
                    diff_size, max_diff.value))
                contents = "%s\n%s" % (message, diff_msg)
            else:
                contents = "%s\n%s" % (message, diff)
        else:
            contents = "%s\n%s" % (message, diff)
        email_branch_modified_notifications(
            branch, addresses, from_address, contents, recipients)


def send_branch_modified_notifications(branch, event):
    """Notify the related people that a branch has been modifed."""
    branch_delta = BranchDelta.construct(
        event.object_before_modification, branch, event.user)
    if branch_delta is None:
        return
    # If there is no one interested, then bail out early.
    recipients = branch.getNotificationRecipients()

    to_addresses = set()
    interested_levels = (
        BranchSubscriptionNotificationLevel.ATTRIBUTEONLY,
        BranchSubscriptionNotificationLevel.FULL)
    for email_address in recipients.getEmails():
        subscription, ignored = recipients.getReason(email_address)
        if subscription.notification_level in interested_levels:
            to_addresses.add(email_address)

    indent = ' '*4
    info_lines = []

    # Fields for which we have old and new values.
    for field_name in ('name', 'title', 'url'):
        delta = getattr(branch_delta, field_name)
        if delta is not None:
            title = IBranch[field_name].title
            old_item = delta['old']
            if old_item is None:
                old_item = '(not set)'
            new_item = delta['new']
            if new_item is None:
                new_item = '(not set)'
            info_lines.append("%s%s: %s => %s" % (
                indent, title, old_item, new_item))

    # lifecycle_status is different as it is an Enum type.
    if branch_delta.lifecycle_status is not None:
        old_item = branch_delta.lifecycle_status['old']
        new_item = branch_delta.lifecycle_status['new']
        title = IBranch['lifecycle_status'].title
        info_lines.append("%s%s: %s => %s" % (
            indent, title, old_item.title, new_item.title))

    # Fields for which we only have the new value.
    for field_name in ('summary', 'whiteboard'):
        delta = getattr(branch_delta, field_name)
        if delta is not None:
            title = IBranch[field_name].title
            if info_lines:
                info_lines.append('')
            info_lines.append('%s changed to:\n\n%s' % (title, delta))

    if not info_lines:
        # The specification was modified, but we don't yet support
        # sending notification for the change.
        return

    from_address = format_address(
        event.user.displayname, event.user.preferredemail.email)
    contents = '\n'.join(info_lines)
    email_branch_modified_notifications(
        branch, to_addresses, from_address, contents, recipients)

def notify_specification_subscription_created(specsub, event):
    """Notify a user that they have been subscribed to a blueprint."""
    user = event.user
    spec = specsub.specification
    person = specsub.person
    subject = specification_notification_subject(spec)
    mailwrapper = MailWrapper(width=72)
    body = mailwrapper.format(
        'You are now subscribed to the blueprint '
        '%(blueprint_name)s - %(blueprint_title)s.\n\n'
        '--\n  %(blueprint_url)s' %
        {'blueprint_name' : spec.name,
         'blueprint_title' : spec.title,
         'blueprint_url' : canonical_url(spec)})
    for address in contactEmailAddresses(person):
        simple_sendmail_from_person(user, address, subject, body)

def notify_specification_subscription_modified(specsub, event):
    """Notify a subscriber to a blueprint that their
    subscription has changed.
    """
    user = event.user
    spec = specsub.specification
    person = specsub.person
    # Only send a notification if the
    # subscription changed by someone else.
    if person == user:
        return
    subject = specification_notification_subject(spec)
    if specsub.essential:
        specsub_type = 'Participation essential'
    else:
        specsub_type = 'Participation non-essential'
    mailwrapper = MailWrapper(width=72)
    body = mailwrapper.format(        
        'Your subscription to the blueprint '
        '%(blueprint_name)s - %(blueprint_title)s '
        'has changed to [%(specsub_type)s].\n\n'
        '--\n  %(blueprint_url)s' %
        {'blueprint_name' : spec.name,
         'blueprint_title' : spec.title,
         'specsub_type' : specsub_type,
         'blueprint_url' : canonical_url(spec)})
    for address in contactEmailAddresses(person):
        simple_sendmail_from_person(user, address, subject, body)
