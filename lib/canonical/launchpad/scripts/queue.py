# Copyright Canonical Limited 2006
"""Ftpmaster queue tool libraries."""

__metaclass__ = type

__all__ = [
    'CommandRunner',
    'CommandRunnerError',
    'name_queue_map'
    ]

import os
import sys
import tempfile
from email import message_from_string
import pytz
from datetime import datetime

from zope.component import getUtility

from canonical.launchpad.interfaces import (
    NotFoundError, IDistributionSet, IDistroReleaseQueueSet,
    IComponentSet, ISectionSet, QueueInconsistentStateError,
    IPersonSet)

from canonical.archivepublisher.tagfiles import (
    parse_tagfile, TagFileParseError)
from canonical.archivepublisher.template_messages import (
    announce_template, rejection_template)
from canonical.archivepublisher.utils import (
    safe_fix_maintainer, ParseMaintError)
from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.encoding import ascii_smash, guess as guess_encoding
from canonical.launchpad.mail import sendmail
from canonical.launchpad.webapp.tales import DurationFormatterAPI
from canonical.librarian.utils import filechunks
from canonical.lp.dbschema import (
    DistroReleaseQueueStatus, PackagePublishingPriority,
    PackagePublishingPocket)


name_queue_map = {
    "new": DistroReleaseQueueStatus.NEW,
    "unapproved": DistroReleaseQueueStatus.UNAPPROVED,
    "accepted": DistroReleaseQueueStatus.ACCEPTED,
    "done": DistroReleaseQueueStatus.DONE,
    "rejected": DistroReleaseQueueStatus.REJECTED
    }

name_priority_map = {
    'required': PackagePublishingPriority.REQUIRED,
    'important': PackagePublishingPriority.IMPORTANT,
    'standard': PackagePublishingPriority.STANDARD,
    'optional': PackagePublishingPriority.OPTIONAL,
    'extra': PackagePublishingPriority.EXTRA,
    '': None
    }

#XXX cprov 20060919: we need to use template engine instead of harcoded
# format variables.
HEAD = "-" * 9 + "|----|" + "-" * 22 + "|" + "-" * 22 + "|" + "-" * 15
FOOT_MARGIN = " " * (9 + 6 + 1 + 22 + 1 + 22 + 2)
RULE = "-" * (12 + 9 + 6 + 1 + 22 + 1 + 22 + 2)

FILTERMSG="""
    Omit the filter for all records.
    Filter string consists of a queue ID or a pair <name>[/<version>]:

    28
    apt
    apt/1

    Use '-e' command line argument for exact matches:

    -e apt
    -e apt/1.0-1
"""


class QueueActionError(Exception):
    """Identify Errors occurred within QueueAction class and its children."""


class QueueAction:
    """Queue Action base class.

    Implements a bunch of common/useful method designed to provide easy
    DistroReleaseQueue handling.
    """

    def __init__(self, distribution_name, suite_name, queue, terms,
                 announcelist, display, no_mail=True, exact_match=False):
        """Initialises passed variables. """
        self.terms = terms
        self.exact_match = exact_match
        self.queue = queue
        self.no_mail = no_mail
        self.distribution_name = distribution_name
        self.suite_name = suite_name
        self.announcelist = announcelist
        self.default_sender = "%s <%s>" % (
            config.uploader.default_sender_name,
            config.uploader.default_sender_address)
        self.default_recipient = "%s <%s>" % (
            config.uploader.default_recipient_name,
            config.uploader.default_recipient_address)
        self.display = display

    @cachedproperty
    def size(self):
        """Return the size of the queue in question."""
        return getUtility(IDistroReleaseQueueSet).count(
            status=self.queue, distrorelease=self.distrorelease,
            pocket=self.pocket)

    def setDefaultContext(self):
        """Set default distribuiton, distrorelease, announcelist."""
        # if not found defaults to 'ubuntu'
        distroset = getUtility(IDistributionSet)
        try:
            self.distribution = distroset[self.distribution_name]
        except NotFoundError, info:
            self.distribution = distroset['ubuntu']

        if self.suite_name:
            # defaults to distro.currentrelease if passed distrorelease is
            # misapplied or not found.
            try:
                self.distrorelease, self.pocket = (
                    self.distribution.getDistroReleaseAndPocket(
                    self.suite_name))
            except NotFoundError, info:
                raise QueueActionError('Context not found: "%s/%s"'
                                       % (self.distribution.name,
                                          self.suite_name))
        else:
            self.distrorelease = self.distribution.currentrelease
            self.pocket = PackagePublishingPocket.RELEASE

        if not self.announcelist:
            self.announcelist = self.distrorelease.changeslist


    def initialize(self):
        """Builds a list of affected records based on the filter argument."""
        self.setDefaultContext()

        try:
            term = self.terms[0]
        except IndexError:
            # if no argument is passed, present all available results in
            # the selected queue.
            term = ''

        # refuse old-style '*' argument since we do not support
        # wildcards yet.
        if term == '*':
            self.displayUsage(FILTERMSG)

        if term.isdigit():
            # retrieve DistroReleaseQueue item by id
            try:
                item = getUtility(IDistroReleaseQueueSet).get(int(term))
            except NotFoundError, info:
                raise QueueActionError('Queue Item not found: %s' % info)

            if item.status != self.queue:
                raise QueueActionError(
                    'Item %s is in queue %s' % (item.id, item.status.name))

            if (item.distrorelease != self.distrorelease or
                item.pocket != self.pocket):
                raise QueueActionError(
                    'Item %s is in %s/%s-%s not in %s/%s-%s'
                    % (item.id, item.distrorelease.distribution.name,
                       item.distrorelease.name, item.pocket.name,
                       self.distrorelease.distribution.name,
                       self.distrorelease.name, self.pocket.name))

            self.items = [item]
            self.items_size = 1
            self.term = None
        else:
            # retrieve DistroReleaseQueue item by name/version key
            version = None
            if '/' in term:
                term, version = term.strip().split('/')

            self.items = self.distrorelease.getQueueItems(
                status=self.queue, name=term, version=version,
                exact_match=self.exact_match, pocket=self.pocket)
            self.items_size = self.items.count()
            self.term = term

    def run(self):
        """Place holder for command action."""
        raise NotImplemented('No action implemented.')

    def displayTitle(self, action):
        """Common title/summary presentation method."""
        self.display("%s %s/%s (%s) %s/%s" % (
            action, self.distribution.name, self.suite_name,
            self.queue.name, self.items_size, self.size))

    def displayHead(self):
        """Table head presentation method."""
        self.display(HEAD)

    def displayBottom(self):
        """Displays the table bottom and a small statistic information."""
        self.display(
            FOOT_MARGIN + "%d/%d total" % (self.items_size, self.size))

    def displayRule(self):
        """Displays a rule line. """
        self.display(RULE)

    def displayUsage(self, extended_info=None):
        """Display the class docstring as usage message.

        Raise QueueActionError with optional extended_info argument
        """
        self.display(self.__doc__)
        raise QueueActionError(extended_info)

    def displayItem(self, queue_item):
        """Display one line summary of the queue item provided."""
        source_tag = '-'
        build_tag = '-'
        displayname = queue_item.displayname
        version = queue_item.displayversion
        age = DurationFormatterAPI(
            datetime.now(pytz.timezone('UTC')) -
            queue_item.datecreated).approximateduration()

        # XXX cprov 20060731: source_tag and build_tag ('S' & 'B')
        # are necessary simply to keep the format legaxy.
        # We may discuss a more reasonable output format later
        # and avoid extra boring code. The IDRQ.displayname should
        # do should be enough.
        if queue_item.sources.count() > 0:
            source_tag = 'S'
        if queue_item.builds.count() > 0:
            build_tag = 'B'
            displayname = "%s (%s)" % (queue_item.displayname,
                                       queue_item.displayarchs)

        self.display("%8d | %s%s | %s | %s | %s" %
                     (queue_item.id, source_tag, build_tag,
                      displayname.ljust(20)[:20], version.ljust(20)[:20], age))

    def displayInfo(self, queue_item, only=None):
        """Displays additional information about the provided queue item.

        Optionally pass a binarypackagename via 'only' argument to display
        only exact matches within the selected build queue items.
        """
        for source in queue_item.sources:
            spr = source.sourcepackagerelease
            self.display("\t | * %s/%s Component: %s Section: %s"
                         % (spr.sourcepackagename.name, spr.version,
                            spr.component.name, spr.section.name))

        for queue_build in queue_item.builds:
            for bpr in queue_build.build.binarypackages:
                if only and only != bpr.name:
                    continue
                dar = queue_build.build.distroarchrelease
                binarypackagename = bpr.binarypackagename.name
                # inspect the publication history of each binary
                darbp = dar.getBinaryPackage(binarypackagename)
                if darbp.currentrelease is not None:
                    status_flag = "*"
                else:
                    status_flag = "N"

                self.display("\t | %s %s/%s/%s Component: %s Section: %s "
                             "Priority: %s"
                             % (status_flag, binarypackagename, bpr.version,
                                dar.architecturetag, bpr.component.name,
                                bpr.section.name, bpr.priority.name))

        for queue_custom in queue_item.customfiles:
            self.display("\t | * %s Format: %s"
                         % (queue_custom.libraryfilealias.filename,
                            queue_custom.customformat.name))

    def displayMessage(self, message):
        """Display formated message."""
        self.display("Would be sending a mail:")
        self.display("   Subject: %s" % message['Subject'])
        self.display("   Sender: %s" % message['From'])
        self.display("   Recipients: %s" % message['To'])
        self.display("   Bcc: %s" % message['Bcc'])
        self.display("   Body:")
        for line in message.get_payload().split("\n"):
            self.display(line)

    def send_email(self, message):
        """Send the mails provided using the launchpad mail infrastructure."""
        mail_message = message_from_string(ascii_smash(message))
        mail_message['X-Katie'] = "Launchpad actually"
        # XXX cprov 20060711: workaround for bug # 51742, empty 'To:' due
        # invalid uploader LP email on reject. We always have Bcc:, so, it's
        # promoted to To:
        if not mail_message['To']:
            mail_message['X-Non-LP-Uploader'] = ""
            mail_message.replace_header('To', self.default_recipient)
            mail_message.replace_header('Bcc', '')

        if not self.no_mail:
            sendmail(mail_message)
            return

        self.displayMessage(mail_message)

    # XXX: dsilvers: 20050203: This code is essentially cargo-culted from
    # nascentupload.py and ideally should be migrated into a database
    # method.
    def _components_valid_for(self, person):
        """Return the set of components this person could upload to."""

        possible_components = set()
        for acl in self.distribution.uploaders:
            if person in acl:
                possible_components.add(acl.component.name)

        return possible_components

    def is_person_in_keyring(self, person):
        """Return whether or not the specified person is in the keyring."""
        in_keyring = len(self._components_valid_for(person)) > 0
        return in_keyring

    # The above were stolen for this code to be useful.
    def filter_addresses(self, addresslist):
        """Filter the list of addresses provided based on the distribution's
        permitted uploaders.
        """
        okay = []
        person_util = getUtility(IPersonSet)
        for address in addresslist:
            p = person_util.getByEmail(address)
            if p is not None:
                if self.is_person_in_keyring(p):
                    okay.append(address)
        return okay

    def find_addresses_from(self, changesfile):
        """Given a libraryfilealias which is a changes file, find a
        set of permitted recipients for the current distrorelease.
        """
        full_set = set()
        recipient_addresses = []
        from_address = self.default_sender

        temp_fd, temp_name = tempfile.mkstemp()
        temp_fd = os.fdopen(temp_fd, "w")

        changesfile.open()
        temp_fd.write(changesfile.read())
        temp_fd.close()
        changesfile.close()

        try:
            changes = parse_tagfile(temp_name, allow_unsigned=True)
        except TagFileParseError, e:
            os.remove(temp_name)
        else:
            os.remove(temp_name)

            (rfc822, rfc2047, name, email) = safe_fix_maintainer(
                changes['maintainer'], 'maintainer')
            full_set.add(email)

            (rfc822, rfc2047, name, email) = safe_fix_maintainer(
                changes['changed-by'], 'changed-by')
            full_set.add(email)

            # Finally, filter the set of recipients based on the whitelist
            recipient_addresses.extend(self.filter_addresses(full_set))

            if email in recipient_addresses:
                from_address = rfc2047

        # Return the sender for the announce and any recipients for the
        # accept/reject messages themselves
        return from_address, recipient_addresses


class QueueActionHelp:
    """Present provided actions summary"""
    def __init__(self, **kargs):
        self.kargs = kargs
        self.kargs['no_mail'] = True
        self.actions = kargs['terms']

    def initialize(self):
        """Mock initialization """
        pass

    def run (self):
        """Present the actions description summary"""
        # present summary for specific or all commands
        if not self.actions:
            actions_help = queue_actions.items()
        else:
            actions_help = [(k, v) for k, v in queue_actions.items()
                            if k in self.actions]
        # extract summary from docstring of specified commands
        for action, wrapper in actions_help:
            if action is 'help':
                continue
            wobj = wrapper(**self.kargs)
            summary = wobj.__doc__.splitlines()[0]
            self.display('\t%s : %s ' % (action, summary))


class QueueActionReport(QueueAction):
    """Present a report about the size of available queues"""
    def initialize(self):
        """Mock initialization """
        self.setDefaultContext()

    def run(self):
        """Display the queues size."""
        self.display("Report for %s/%s" % (self.distribution.name,
                                           self.distrorelease.name))

        for queue in name_queue_map.values():
            size = getUtility(IDistroReleaseQueueSet).count(
                status=queue, distrorelease=self.distrorelease,
                pocket=self.pocket)
            self.display("\t%s -> %s entries" % (queue.name, size))


class QueueActionInfo(QueueAction):
    """Present the Queue item including its contents.

    Presents the contents of the selected upload(s).

    queue info <filter>
    """
    def run(self):
        """Present the filtered queue ordered by date."""
        self.displayTitle('Listing')
        self.displayHead()
        for queue_item in self.items:
            self.displayItem(queue_item)
            self.displayInfo(queue_item)
        self.displayHead()
        self.displayBottom()


class QueueActionFetch(QueueAction):
    """Fetch the contents of a queue item.

    Download the contents of the selected upload(s).

    queue fetch <filter>
    """
    def run(self):
        self.displayTitle('Fetching')
        self.displayRule()
        for queue_item in self.items:
            self.display("Constructing %s" % queue_item.changesfile.filename)
            changes_file_alias = queue_item.changesfile
            changes_file_alias.open()
            changes_file = open(queue_item.changesfile.filename, "w")
            changes_file.write(changes_file_alias.read())
            changes_file.close()
            changes_file_alias.close()

            file_list = []
            for source in queue_item.sources:
                for spr_file in source.sourcepackagerelease.files:
                    file_list.append(spr_file.libraryfile)

            for build in queue_item.builds:
                for bpr in build.build.binarypackages:
                    for bpr_file in bpr.files:
                        file_list.append(bpr_file.libraryfile)

            for custom in queue_item.customfiles:
                file_list.append(custom.libraryfilealias)

            for libfile in file_list:
                self.display("Constructing %s" % libfile.filename)
                libfile.open()
                out_file = open(libfile.filename, "w")
                for chunk in filechunks(libfile):
                    out_file.write(chunk)
                out_file.close()
                libfile.close()

        self.displayRule()
        self.displayBottom()


class QueueActionReject(QueueAction):
    """Reject the contents of a queue item.

    Move the selected upload(s) to the REJECTED queue.

    queue reject <filter>
    """
    def run(self):
        """Perform Reject action."""
        self.displayTitle('Rejecting')
        self.displayRule()
        for queue_item in self.items:
            self.display('Rejecting %s' % queue_item.displayname)
            try:
                queue_item.setRejected()
            except QueueInconsistentStateError, info:
                self.display('** %s could not be rejected due %s'
                             % (queue_item.displayname, info))
            else:
                summary = []
                for queue_source in queue_item.sources:
                    # XXX: dsilvers: 20060203: This needs to be able to
                    # be given a reason for the rejection, otherwise it's
                    # not desperately useful.
                    src_rel = queue_source.sourcepackagerelease
                    summary.append('%s %s was REJECTED.\n\t'
                                   'Component: %s Section: %s'
                                   % (src_rel.name, src_rel.version,
                                      src_rel.component.name,
                                      src_rel.section.name))

                for queue_build in queue_item.builds:
                    summary.append(
                        '%s (%s) was REJECTED'
                        % (queue_build.build.title, queue_build.build.id))

                for queue_custom in queue_item.customfiles:
                    summary.append(
                        '%s (%s) was REJECTED'
                        % (queue_custom.libraryfilealias.filename,
                           queue_custom.libraryfilealias.url))

                sender, recipients = self.find_addresses_from(
                        queue_item.changesfile)

                queue_item.changesfile.open()
                # XXX cprov 20060221: guess_encoding breaks the
                # GPG signature.
                changescontent = guess_encoding(
                    queue_item.changesfile.read())
                queue_item.changesfile.close()

                replacements = {
                    "SENDER": sender,
                    "RECIPIENT": ", ".join(recipients),
                    "CHANGES": queue_item.changesfile.filename,
                    "SUMMARY": "\n".join(summary),
                    "CHANGESFILE": changescontent,
                    "DEFAULT_RECIPIENT": self.default_recipient,
                    }

                # append an email describing this action.
                message = rejection_template % replacements
                self.send_email(message)

        self.displayRule()
        self.displayBottom()


class QueueActionAccept(QueueAction):
    """Accept the contents of a queue item.

    Move the selected upload(s) to the ACCEPTED queue.

    queue accept <filter>
    """
    def run(self):
        """Perform Accept action."""
        self.displayTitle('Accepting')
        self.displayRule()
        for queue_item in self.items:
            self.display('Accepting %s' % queue_item.displayname)
            try:
                queue_item.setAccepted()
            except QueueInconsistentStateError, info:
                self.display('** %s could not be accepted due %s'
                             % (queue_item.displayname, info))
            else:
                summary = []
                for queue_source in queue_item.sources:
                    # XXX: dsilvers: 20060203: This needs to be able to
                    # be given a reason for the rejection, otherwise it's
                    # not desperately useful.
                    src_rel = queue_source.sourcepackagerelease
                    summary.append('%s %s was ACCEPTED.\n\t'
                                   'Component: %s Section: %s'
                                   % (src_rel.name, src_rel.version,
                                      src_rel.component.name,
                                      src_rel.section.name))

                for queue_build in queue_item.builds:
                    summary.append(
                        '%s (%s) was ACCEPTED' % (queue_build.build.title,
                                                  queue_build.build.id))

                for queue_custom in queue_item.customfiles:
                    summary.append(
                        '%s (%s) was ACCEPTED'
                        % (queue_custom.libraryfilealias.filename,
                           queue_custom.libraryfilealias.url))

                # We send a notification email only if the upload
                # was sourceful, or had exactly one customfile and
                # no binaries.
                if (queue_item.sources.count()
                    or (queue_item.builds.count() == 0
                        and queue_item.customfiles.count() == 1)):
                    self.sendAcceptEmail(queue_item, "\n".join(summary))

        self.displayRule()
        self.displayBottom()

    def sendAcceptEmail(self, queue_item, summary):
        """Send an accept email.

        Take the summary given, and derive the rest of the information
        for the email from the queue_item.
        """
        # We only send accept emails for sourceful or single-custom
        # uploads
        assert(queue_item.sources.count() or
               (queue_item.builds.count() == 0 and
                queue_item.customfiles.count() == 1))

        sender, recipients = self.find_addresses_from(
            queue_item.changesfile)
        # only announce for acceptation
        if self.announcelist is not None:
            recipients.append(self.announcelist)

        queue_item.changesfile.open()
        # XXX cprov 20060221: guess_encoding breaks the
        # GPG signature.
        changescontent = guess_encoding(
            queue_item.changesfile.read())
        queue_item.changesfile.close()

        replacements = {
            "MAINTAINERFROM": sender,
            "SOURCE": queue_item.displayname,
            "VERSION": queue_item.displayversion,
            "ARCH": queue_item.displayarchs,
            "CHANGESFILE": changescontent,
            "SUMMARY": summary,
            "ANNOUNCE": ", ".join(recipients),
            "DEFAULT_RECIPIENT": self.default_recipient
        }

        # append an email describing this action.
        message = announce_template % replacements
        self.send_email(message)


class QueueActionOverride(QueueAction):
    """Override information in a queue item content.

    queue override <filter> [override_stanza*]

    Where override_stanza is one of:
    source [<component>]/[<section>]
    binary [<component>]/[<section>]/[<priority>]

    In each case, when you want to leave an override alone leave it blank.

    So, to set a binary to have section 'editors' but leave the
    component and priority alone, do:

    queue override <filter> binary /editors/

    Binaries can only be overridden by passing a name filter, so it will
    only override the binary package which matches the filter.

    Or, to set a source's section to editors, do:

    queue override <filter> source /editors
    """
    supported_override_stanzas = ['source', 'binary']

    def run(self):
        """Perform Override action."""
        self.displayTitle('Overriding')
        self.displayRule()

        try:
            override_stanza = self.terms[1]
        except IndexError, info:
            self.displayUsage('Missing override_stanza.')
            return

        if override_stanza not in self.supported_override_stanzas:
            self.displayUsage('Not supported override_stanza: %s'
                            % override_stanza)
            return

        return getattr(self, '_override_' + override_stanza)()

    def _override_source(self):
        """Overrides sourcepackagereleases selected.

        It doesn't check Component/Section Selection, this is a task
        for queue state-machine.
        """
        try:
            overrides = self.terms[2]
            component_name, section_name = overrides.split('/')
        except IndexError, info:
            self.displayUsage('Missing override_stanza argument')
        except ValueError, info:
            self.displayUsage('Misapplied override_stanza argument: %s'
                            % overrides)

        component = None
        section = None
        try:
            if component_name:
                component = getUtility(IComponentSet)[component_name]
            if section_name:
                section = getUtility(ISectionSet)[section_name]
        except NotFoundError, info:
            raise QueueActionError('Not Found: %s' % info)

        for queue_item in self.items:
            # There's usually only one item in queue_item.sources.
            for source in queue_item.sources:
                source.sourcepackagerelease.override(component=component,
                                                     section=section)
                self.displayInfo(queue_item)

    def _override_binary(self):
        """Overrides binarypackagereleases selected"""
        if not self.term:
            self.displayUsage('Cannot Override BinaryPackage retrieved by ID')

        try:
            overrides = self.terms[2]
            component_name, section_name, priority_name = overrides.split('/')
        except IndexError, info:
            self.displayUsage('Missing "name override_argument" argument')
        except ValueError, info:
            self.displayUsage('Misapplied override_stanza argument: %s'
                            % overrides)
        component = None
        section = None
        priority = None
        try:
            if component_name:
                component = getUtility(IComponentSet)[component_name]
            if section_name:
                section = getUtility(ISectionSet)[section_name]
            if priority_name:
                priority = name_priority_map[priority_name]
        except (NotFoundError, KeyError), info:
            raise QueueActionError('Not Found: %s' % info)

        overridden = None
        for queue_item in self.items:
            for build in queue_item.builds:
                # Different than DistroReleaseQueueSources
                # DistroReleaseQueueBuild points to a Build, that can,
                # and usually does, point to multiple BinaryPackageReleases.
                # So we need to carefully select the requested package to be
                # overridden
                for binary in build.build.binarypackages:
                    if binary.name == self.term:
                        overridden = binary.name
                        self.display("Overriding %s_%s (%s/%s/%s)"
                                     % (binary.name, binary.version,
                                        binary.component.name,
                                        binary.section.name,
                                        binary.priority.name))
                        binary.override(component=component, section=section,
                                        priority=priority)
                        # break loop, just in case
                        break

        if not overridden:
            self.displayUsage('No matches for "%s".' % self.term)

        self.displayInfo(queue_item, only=overridden)


queue_actions = {
    'help': QueueActionHelp,
    'info': QueueActionInfo,
    'fetch': QueueActionFetch,
    'accept': QueueActionAccept,
    'reject': QueueActionReject,
    'override': QueueActionOverride,
    'report': QueueActionReport,
    }


def default_display(text):
    """Unified presentation method."""
    print text


class CommandRunnerError(Exception):
    """Command Runner Failure"""


class CommandRunner:
    """A wrapper for queue_action classes."""
    def __init__(self, queue, distribution_name, suite_name,
                 announcelist, no_mail, display=default_display):
        self.queue = queue
        self.distribution_name = distribution_name
        self.suite_name = suite_name
        self.announcelist = announcelist
        self.no_mail = no_mail
        self.display = display

    def execute(self, terms, exact_match=False):
        """Execute a single queue action."""
        self.display('Running: "%s"' % " ".join(terms))

        # check syntax, abort process if anything gets wrong
        try:
            action = terms[0]
            arguments = terms[1:]
        except IndexError:
            raise CommandRunnerError('Invalid sentence, use help.')

        # check action availability,
        try:
            queue_action = queue_actions[action]
        except KeyError:
            raise CommandRunnerError('Unknown Action: %s' % action)

        # perform the required action on queue.
        try:
            # be sure to send every args via kargs
            self.queue_action = queue_action(
                distribution_name=self.distribution_name,
                suite_name=self.suite_name,
                announcelist=self.announcelist,
                queue=self.queue,
                no_mail=self.no_mail,
                display=self.display,
                terms=arguments,
                exact_match=exact_match)
            self.queue_action.initialize()
            self.queue_action.run()
        except QueueActionError, info:
            raise CommandRunnerError(info)
