# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import re
from urlparse import urlparse, urlunparse

import transaction
from zope.component import getUtility
from zope.interface import implements
from zope.event import notify
from zope.exceptions import NotFoundError
from zope.security.management import queryInteraction

from canonical.config import config
from canonical.launchpad.helpers import Snapshot
from canonical.launchpad.interfaces import (
    ILaunchBag, IMessageSet, IBugEmailCommand, IBugTaskEmailCommand,
    IBugEditEmailCommand, IBugTaskEditEmailCommand, IBug, IBugTask,
    IMailHandler, IBugMessageSet, CreatedBugWithNoBugTasksError,
    EmailProcessingError, IUpstreamBugTask, IDistroBugTask,
    IDistroReleaseBugTask, IWeaklyAuthenticatedPrincipal, ITicket, ITicketSet,
    ISpecificationSet)
from canonical.launchpad.mail.commands import emailcommands, get_error_message
from canonical.launchpad.mail.sendmail import sendmail
from canonical.launchpad.mail.specexploder import get_spec_url_from_moin_mail
from canonical.launchpad.mailnotification import (
    send_process_error_notification)
from canonical.launchpad.webapp import canonical_url

from canonical.launchpad.event import (
    SQLObjectModifiedEvent, SQLObjectCreatedEvent)
from canonical.launchpad.event.interfaces import (
    ISQLObjectModifiedEvent, ISQLObjectCreatedEvent)


def get_main_body(signed_msg):
    """Returns the first text part of the email."""
    msg = signed_msg.signedMessage
    if msg is None:
        # The email wasn't signed.
        msg = signed_msg
    if msg.is_multipart():
        for part in msg.get_payload():
            if part.get_content_type() == 'text/plain':
                return part.get_payload(decode=True)
    else:
        return msg.get_payload(decode=True)


def get_bugtask_type(bugtask):
    """Returns the specific IBugTask interface the the bugtask provides.

        >>> from canonical.launchpad.interfaces import (
        ...     IUpstreamBugTask, IDistroBugTask, IDistroReleaseBugTask)
        >>> from zope.interface import classImplementsOnly
        >>> class BugTask:
        ...     pass

    :bugtask: has to provide a specific bugtask interface:

        >>> get_bugtask_type(BugTask()) #doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        AssertionError...

    When it does, the specific interface is returned:

        >>> classImplementsOnly(BugTask, IUpstreamBugTask)
        >>> get_bugtask_type(BugTask()) #doctest: +ELLIPSIS
        <...IUpstreamBugTask>

        >>> classImplementsOnly(BugTask, IDistroBugTask)
        >>> get_bugtask_type(BugTask()) #doctest: +ELLIPSIS
        <...IDistroBugTask>

        >>> classImplementsOnly(BugTask, IDistroReleaseBugTask)
        >>> get_bugtask_type(BugTask()) #doctest: +ELLIPSIS
        <...IDistroReleaseBugTask>
    """
    bugtask_interfaces = [
        IUpstreamBugTask, IDistroBugTask, IDistroReleaseBugTask
        ]
    for interface in bugtask_interfaces:
        if interface.providedBy(bugtask):
            return interface
    # The bugtask didn't provide any specific interface.
    raise AssertionError(
        'No specific bugtask interface was provided by %r' % bugtask)


def guess_bugtask(bug, person):
    """Guess which bug task the person intended to edit.

    Return None if no bug task could be guessed.
    """
    if len(bug.bugtasks) == 1:
        return bug.bugtasks[0]
    else:
        for bugtask in bug.bugtasks:
            if IUpstreamBugTask.providedBy(bugtask):
                # Is the person an upstream maintainer?
                if person.inTeam(bugtask.product.owner):
                    return bugtask
            elif IDistroBugTask.providedBy(bugtask):
                # Is the person a member of the distribution?
                if person.inTeam(bugtask.distribution.members):
                    return bugtask
                else:
                    # Is the person one of the package bug contacts?
                    distro_sourcepackage = bugtask.distribution.getSourcePackage(
                        bugtask.sourcepackagename)
                    if distro_sourcepackage.isBugContact(person):
                        return bugtask

    return None


def get_current_principal():
    """Get the principal from the current interaction."""
    interaction = queryInteraction()
    principals = [
        participation.principal
        for participation in interaction.participations]
    assert len(principals) == 1, (
        "There should be only one principal in the current interaction.")
    return principals[0]


class IncomingEmailError(Exception):
    """Indicates that something went wrong processing the mail."""

    def __init__(self, message, failing_command=None):
        self.message = message
        self.failing_command = failing_command


class MaloneHandler:
    """Handles emails sent to Malone.

    It only handles mail sent to new@... and $bugid@..., where $bugid is a
    positive integer.
    """
    implements(IMailHandler)

    allow_unknown_users = False

    def getCommands(self, signed_msg):
        """Returns a list of all the commands found in the email."""
        commands = []
        content = get_main_body(signed_msg)
        if content is None:
            return []
        # First extract all commands from the email.
        command_names = emailcommands.names()
        for line in content.splitlines():  
            # All commands have to be indented.
            if line.startswith(' ') or line.startswith('\t'):
                command_string = line.strip()
                words = command_string.split(' ')
                if words and words[0] in command_names:
                    command = emailcommands.get(
                        name=words[0], string_args=words[1:])
                    commands.append(command)
        return commands


    def process(self, signed_msg, to_addr, filealias=None, log=None):
        """See IMailHandler."""
        commands = self.getCommands(signed_msg)
        user, host = to_addr.split('@')
        add_comment_to_bug = False

        try:
            if len(commands) > 0:
                current_principal = get_current_principal()
                # The security machinery doesn't know about
                # IWeaklyAuthenticatedPrincipal yet, so do a manual
                # check. Later we can rely on the security machinery to
                # cause Unauthorized errors.
                if IWeaklyAuthenticatedPrincipal.providedBy(current_principal):
                    if signed_msg.signature is None:
                        error_message = get_error_message('not-signed.txt')
                    else:
                        import_url = canonical_url(
                            getUtility(ILaunchBag).user) + '/+editpgpkeys'
                        error_message = get_error_message(
                            'key-not-registered.txt', import_url=import_url)
                    raise IncomingEmailError(error_message)

            if user.lower() == 'new':
                # A submit request.
                commands.insert(0, emailcommands.get('bug', ['new']))
                if signed_msg.signature is None:
                    raise IncomingEmailError(
                        get_error_message('not-gpg-signed.txt'))
            elif user.isdigit():
                # A comment to a bug. We set add_comment_to_bug to True so
                # that the comment gets added to the bug later. We don't add
                # the comment now, since we want to let the 'bug' command
                # handle the possible errors that can occur while getting
                # the bug.
                add_comment_to_bug = True
                commands.insert(0, emailcommands.get('bug', [user]))
            elif user.lower() != 'edit':
                # Indicate that we didn't handle the mail.
                return False

            bug = None
            bug_event = None
            bugtask = None
            bugtask_event = None

            while len(commands) > 0:
                command = commands.pop(0)
                try:
                    if IBugEmailCommand.providedBy(command):
                        if bug_event is not None:
                            notify(bug_event)
                            bug_event = None

                        bug, bug_event = command.execute(signed_msg, filealias)
                        if add_comment_to_bug:
                            messageset = getUtility(IMessageSet)
                            message = messageset.fromEmail(
                                signed_msg.as_string(),
                                owner=getUtility(ILaunchBag).user,
                                filealias=filealias,
                                parsed_message=signed_msg,
                                fallback_parent=bug.initial_message)
                            bugmessage = bug.linkMessage(message)
                            notify(SQLObjectCreatedEvent(bugmessage))
                            add_comment_to_bug = False
                    elif IBugTaskEmailCommand.providedBy(command):
                        if bugtask_event is not None:
                            if not ISQLObjectCreatedEvent.providedBy(
                                bug_event):
                                notify(bugtask_event)
                            bugtask_event = None
                        bugtask, bugtask_event = command.execute(bug)
                    elif IBugEditEmailCommand.providedBy(command):
                        bug, bug_event = command.execute(bug, bug_event)
                    elif IBugTaskEditEmailCommand.providedBy(command):
                        if bugtask is None:
                            bugtask = guess_bugtask(
                                bug, getUtility(ILaunchBag).user)
                            if bugtask is None:
                                raise IncomingEmailError(get_error_message(
                                    'no-default-affects.txt',
                                    bug_id=bug.id,
                                    nr_of_bugtasks=len(bug.bugtasks)))
                        bugtask, bugtask_event = command.execute(
                            bugtask, bugtask_event)

                except EmailProcessingError, error:
                    raise IncomingEmailError(
                        str(error), failing_command=command)

            if bug_event is not None:
                try:
                    notify(bug_event)
                except CreatedBugWithNoBugTasksError:
                    raise IncomingEmailError(
                        get_error_message('no-affects-target-on-submit.txt'))
            if bugtask_event is not None:
                if not ISQLObjectCreatedEvent.providedBy(bug_event):
                    notify(bugtask_event)

        except IncomingEmailError, error:
            transaction.abort()
            send_process_error_notification(
                str(getUtility(ILaunchBag).user.preferredemail.email),
                'Submit Request Failure',
                error.message, error.failing_command)

        return True


class SupportTrackerHandler:
    """Handles emails sent to the support tracker."""

    implements(IMailHandler)

    allow_unknown_users = False

    _ticket_address = re.compile(r'^ticket(?P<id>\d+)@.*')

    def process(self, signed_msg, to_addr, filealias=None, log=None):
        """See IMailHandler."""
        match = self._ticket_address.match(to_addr)
        if match:
            ticket_id = int(match.group('id'))
            ticket = getUtility(ITicketSet).get(ticket_id)
            if ticket is None:
                # No such ticket, don't process the email.
                return False

            unmodified_ticket = Snapshot(ticket, providing=ITicket)
            messageset = getUtility(IMessageSet)
            message = messageset.fromEmail(
                signed_msg.parsed_string,
                owner=getUtility(ILaunchBag).user,
                filealias=filealias,
                parsed_message=signed_msg)
            ticket.linkMessage(message)
            notify(SQLObjectModifiedEvent(
                ticket, unmodified_ticket, ['messages']))
            return True
        else:
            return False


class SpecificationHandler:
    """Handles emails sent to specs.launchpad.net."""

    implements(IMailHandler)

    allow_unknown_users = True

    _spec_changes_address = re.compile(r'^notifications@.*')

    # The list of hosts where the Ubuntu wiki is located. We could do a
    # more general solution, but this kind of setup is unusual, and it
    # will be mainly the Ubuntu and Launchpad wikis that will use this
    # notification forwarder.
    UBUNTU_WIKI_HOSTS = [
        'wiki.ubuntu.com', 'wiki.edubuntu.org', 'wiki.kubuntu.org']

    def _getSpecByURL(self, url):
        """Returns a spec that is associated with the URL.

        It takes into account that the same Ubuntu wiki is on three
        different hosts.
        """
        scheme, host, path, params, query, fragment = urlparse(url)
        if host in self.UBUNTU_WIKI_HOSTS:
            for ubuntu_wiki_host in self.UBUNTU_WIKI_HOSTS:
                possible_url = urlunparse(
                    (scheme, ubuntu_wiki_host, path, params, query,
                     fragment))
                spec = getUtility(ISpecificationSet).getByURL(possible_url)
                if spec is not None:
                    break
        else:
            spec = getUtility(ISpecificationSet).getByURL(url)
        return spec

    def process(self, signed_msg, to_addr, filealias=None, log=None):
        """See IMailHandler."""
        match = self._spec_changes_address.match(to_addr)
        if not match:
            # We handle only spec-changes at the moment.
            return False
        our_address = "notifications@%s" % config.launchpad.specs_domain
        # Check for emails that we sent.
        if signed_msg['X-Loop'] and our_address in signed_msg.get_all('X-Loop'):
            if log and filealias:
                log.warning(
                    'Got back a notification we sent: %s' % filealias.url)
            return True
        # Check for emails that Launchpad sent us.
        if signed_msg['Sender'] == config.bounce_address:
            if log and filealias:
                log.warning(
                    'We received an email from Launchpad: %s' % filealias.url)
            return True
        # When sending the email, the sender will be set so that it's
        # clear that we're the one sending the email, not the original
        # sender.
        del signed_msg['Sender']

        mail_body = signed_msg.get_payload(decode=True)
        spec_url = get_spec_url_from_moin_mail(mail_body)
        if spec_url is not None:
            if log is not None:
                log.debug('Found a spec URL: %s' % spec_url)
            spec = self._getSpecByURL(spec_url)
            if spec is not None:
                if log is not None:
                    log.debug('Found a corresponding spec: %s' % spec.name)
                # Add an X-Loop header, in order to prevent mail loop.
                signed_msg.add_header('X-Loop', our_address)
                notification_addresses = spec.notificationRecipientAddresses()
                if log is not None:
                    log.debug(
                        'Sending notification to: %s' % 
                            ', '.join(notification_addresses))
                sendmail(signed_msg, to_addrs=notification_addresses)

            elif log is not None:
                log.debug("Didn't find a corresponding spec for %s" % spec_url)
        elif log is not None:
            log.debug("Didn't find a specification URL")
        return True


class MailHandlers:
    """All the registered mail handlers."""

    def __init__(self):
        self._handlers = {
            config.launchpad.bugs_domain: MaloneHandler(),
            config.launchpad.specs_domain: SpecificationHandler(),
            config.tickettracker.email_domain: SupportTrackerHandler()
            }

    def get(self, domain):
        """Return the handler for the given email domain.

        Return None if no such handler exists.

            >>> handlers = MailHandlers()
            >>> handlers.get('bugs.launchpad.net') #doctest: +ELLIPSIS
            <...MaloneHandler...>
            >>> handlers.get('no.such.domain') is None
            True
        """
        return self._handlers.get(domain)

    def add(self, domain, handler):
        """Adds a handler for a domain.

            >>> handlers = MailHandlers()
            >>> handlers.get('some.domain') is None
            True
            >>> handler = object()
            >>> handlers.add('some.domain', handler)
            >>> handlers.get('some.domain') is handler
            True

        If there already is a handler for the domain, the old one will
        get overwritten:

            >>> new_handler = object()
            >>> handlers.add('some.domain', new_handler)
            >>> handlers.get('some.domain') is new_handler
            True
        """
        self._handlers[domain] = handler


mail_handlers = MailHandlers()
