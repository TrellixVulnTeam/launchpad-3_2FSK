#!/usr/bin/python

# Copyright 2005 Canonical Ltd

"""Queue management script

"""

import os
import sys

from optparse import OptionParser
from zope.component import getUtility

from canonical.lp import initZopeless
from canonical.config import config
from canonical.launchpad.scripts import (execute_zcml_for_scripts,
                                         logger, logger_options)

from canonical.launchpad.interfaces import (
    NotFoundError, IDistributionSet, IDistroReleaseQueueSet,
    IComponentSet, ISectionSet, QueueInconsistentStateError)

from canonical.lp.dbschema import (
    DistroReleaseQueueStatus, PackagePublishingPriority)

from canonical.launchpad.webapp.tales import DurationFormatterAPI

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


# XXX cprov 20051219: this code is duplicated thousand times in LP
# actually it is very handy, but to use it properly it should be integrated
# in Librarian API as ILibraryFileAlias.chuncks().

def filechunks(file, chunk_size=256*1024):
    """Return an iterator which reads chunks of the given file."""
    # We use the two-arg form of the iterator here to form an iterator
    # which reads chunks from the given file.
    return iter(lambda: file.read(chunk_size), '')


HEAD = "-" * 9 + "|----|" + "-" * 22 + "|" + "-" * 22 + "|" + "-" * 15
FOOT_MARGIN = " " * (9+6+1+22+1+22+2)
RULE = "-" * (12+9+6+1+22+1+22+2)


class QueueActionError(Exception):
    """Identify Errors occurred within QueueAction class and its children."""


class QueueAction:
    """Queue Action base class.

    Implements a bunch of common/useful method designed to provide easy
    DistroReleaseQueue handling.
    """
    distro = None
    distrorelease = None
    queue = None
    queue_size = 0
    items = None
    items_size = 0

    def __init__(self, distro, distrorelease, queue, args):
        """Initialises passed variables. """
        self.args = args
        self.distro = distro
        self.distrorelease = distrorelease
        self.queue = queue
        self.queue_size = getUtility(IDistroReleaseQueueSet).count()
        self.buildItems()

    def buildItems(self):
        """Builds a list of affected records based on the filter argument."""
        try:
            term = self.args[0]
        except IndexError:
            self.printUsage("Missed filter argument, use '*' for all records.")

        if term == '*':
            term = ''

        if term.isdigit():
            try:
                item = getUtility(IDistroReleaseQueueSet).get(int(term))
            except NotFoundError, info:
                raise QueueActionError('Queue Item not found: %s' % info)

            self.items = [item]
            self.items_size = 1
        else:
            version = None
            if '/' in term:
                term, version = term.strip().split('/')

            self.items = self.distrorelease.getSourceQueueItems(
                status=self.queue, name=term, version=version)
            self.items_size = self.items.count()

    def run(self):
        """Place holder for command action."""
        raise NotImplemented('No action implemented.')

    def printTitle(self, action):
        """Common title/summary presentation method."""
        print ("%s %s/%s (%s) %s/%s"
               % (action, self.distro.name, self.distrorelease.name,
                  self.queue.name, self.items_size, self.queue_size))

    def printHead(self):
        """Table head presentation method."""
        print HEAD

    def printBottom(self):
        """Displays the table bottom and a small statistic information."""
        print FOOT_MARGIN + "%d/%d total" % (self.items_size, self.queue_size)

    def printRule(self):
        """Displays a rule line. """
        print RULE

    def printUsage(self, extended_info=None):
        """Display the class docstring as usage message.

        Raise QueueActionError with optional extended_info argument
        """
        print self.__doc__
        raise QueueActionError(extended_info)

    def visualiseItem(self, queue_item):
        """Print out a one line summary of the queue item provided."""
        spn = queue_item.sourcepackagename.name
        sourceful = len(queue_item.sources) > 0
        binaryful = len(queue_item.builds) > 0
        sourcever = queue_item.sourceversion
        age = DurationFormatterAPI(queue_item.age).approximateduration()
        vis_item = "%8d | " % queue_item.id
        if sourceful:
            vis_item += "S"
        else:
            vis_item += "-"
        if binaryful:
            vis_item += "B | "
        else:
            vis_item += "- | "
        if len(spn) > 20:
            spn = spn[:20]
        else:
            spn += " " * (20 - len(spn))
        vis_item += spn + " | "
        sourcever = str(sourcever)
        if len(sourcever) > 20:
            sourcever = sourcever[:20]
        else:
            sourcever += " " * (20 - len(sourcever))
        vis_item += sourcever + " | " + age
        print vis_item

    def printInfo(self, queue_item):
        """Displays additional information about the provided queue item."""
        for source in queue_item.sources:
            spr = source.sourcepackagerelease
            print ("Source: %s/%s Component: %s Section: %s"
                   % (spr.sourcepackagename.name, spr.version,
                      spr.component.name, spr.section.name))
        for build in queue_item.builds:
            for bpr in build.build.binarypackages:
                print ("Binary: %s/%s/%s Component: %s Section: %s "
                       "Priority: %s"
                       % (bpr.binarypackagename.name, bpr.version,
                          build.build.distroarchrelease.architecturetag,
                          bpr.component.name, bpr.section.name,
                          bpr.priority.name))


class QueueActionList(QueueAction):
    """Queue List action.

    queue list <filter>
    """
    def run(self):
        """List the filtered queue ordered by date."""
        self.printTitle('Listing')
        self.printHead()
        for queue_item in self.items:
            self.visualiseItem(queue_item)
        self.printHead()
        self.printBottom()


class QueueActionInfo(QueueAction):
    """Queue info action.

    queue info <filter>
    """
    def run(self):
        """Display additional info about filtered queue."""
        self.printTitle('Info')
        self.printRule()
        for queue_item in self.items:
            #self.visualiseItem(queue_item)
            self.printInfo(queue_item)

        self.printRule()
        self.printBottom()


class QueueActionFetch(QueueAction):
    """Queue fetch action.

    queue fetch <filter>
    """
    def run(self):
        self.printTitle('Fetching')
        self.printRule()
        for queue_item in self.items:
            print "Constructing %s" % queue_item.changesfilename
            changes_file_alias = queue_item.changesfilealias
            changes_file_alias.open()
            changes_file = open(queue_item.changesfilename, "w")
            changes_file.write(changes_file_alias.read())
            changes_file.close()
            changes_file_alias.close()

            file_list = []
            for source in queue_item.sources:
                file_list.extend(source.sourcepackagerelease.files)

            for build in queue_item.builds:
                for bpr in build.build.binarypackages:
                    file_list.extend(bpr.files)

            for file_ref in file_list:
                libfile = file_ref.libraryfile
                print "Constructing %s" % libfile.filename
                libfile.open()
                out_file = open(libfile.filename, "w")
                for chunk in filechunks(libfile):
                    out_file.write(chunk)
                out_file.close()
                libfile.close()

        self.printRule()
        self.printBottom()


class QueueActionReject(QueueAction):
    """Queue reject action.

    queue reject <filter>
    """
    def run(self):
        """Perform Reject action."""
        self.printTitle('Rejecting')
        self.printRule()
        for queue_item in self.items:
            print 'Rejecting %s' % queue_item.sourcepackagename.name
            try:
                queue_item.set_rejected()
            except QueueInconsistentStateError, info:
                print ('** %s could not be rejected due %s'
                       % (queue_item.sourcepackagename.name, info))

        self.printRule()
        self.printBottom()


class QueueActionAccept(QueueAction):
    """Queue Accept action.

    queue accept <filter>
    """
    def run(self):
        """Perform Accept action."""
        self.printTitle('Accepting')
        self.printRule()
        for queue_item in self.items:
            print 'Accepting %s' % queue_item.sourcepackagename.name
            try:
                queue_item.set_accepted()
            except QueueInconsistentStateError, info:
                print ('** %s could not be accepted due %s'
                       % (queue_item.sourcepackagename.name, info))
        self.printRule()
        self.printBottom()


class QueueActionOverride(QueueAction):
    """Queue override action.

    queue override <filter> [override_stanza*]

    Where override_stanza is one of:
    source [<component>]/[<section>]
    binary <binaryname> [<component>]/[<section>]/[<priority>]

    In each case, when you want to leave an override alone leave it blank.

    So, to set the binary 'ed' to have section 'editors' but leave the
    component and priority alone, do:

    queue override <filter> binary ed /editors/

    Or, to set ed's source's section to editors, do:

    queue override <filter> source /editors
    """
    supported_override_stanzas = ['source', 'binary']

    def run(self):
        """Perform Override action."""
        self.printTitle('Overriding')
        self.printRule()

        try:
            override_stanza = self.args[1]
            assert override_stanza in self.supported_override_stanzas
        except IndexError, info:
            self.printUsage('Missed override_stanza.')
        except AssertionError, info:
            self.printUsage('Not supported override_stanza: %s'
                            % override_stanza)

        getattr(self, '_override_' + override_stanza)()

        self.printRule()
        self.printBottom()

    def _override_source(self):
        """Overrides sourcepackagereleases selected.

        It doesn't check Component/Section Selection, this is a task
        for queue state-machine.
        """
        try:
            overrides = self.args[2]
            component_name, section_name = overrides.split('/')
        except IndexError, info:
            self.printUsage('Missed override_stanza argument')
        except ValueError, info:
            self.printUsage('Misapplied override_stanza argument: %s'
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
            for source in queue_item.sources:
                source.sourcepackagerelease.override(
                    component=component, section=section)
                self.printInfo(queue_item)

    def _override_binary(self):
        """Overrides binarypackagereleases selected"""
        # XXX cprov 20051219: not tested at all
        try:
            overrides = self.args[2]
            component_name, section_name, priority_name = overrides.split('/')
        except IndexError, info:
            self.printUsage('Missed override_argument argument')
        except ValueError, info:
            self.printUsage('Misapplied override_stanza argument: %s'
                            % overrides)

        component = None
        section = None
        priority = None
        try:
            if component_name:
                component = getUtility(IComponentSet)[component_name]
            if section_name:
                section = getUtility(ISectionSet)[section_name]
            priority = name_priority_map[priority_name]
        except (NotFoundError, KeyError), info:
            raise QueueActionError('Not Found: %s' % info)

        for queue_item in self.items:
            for build in queue_item.builds:
                for binary in build.build.binarypackages:
                    binary.override(component=component, section=section,
                                    priority=priority)
                self.printInfo(queue_item)

queue_actions = {
    'list': QueueActionList,
    'info': QueueActionInfo,
    'fetch': QueueActionFetch,
    'accept': QueueActionAccept,
    'reject': QueueActionReject,
    'override': QueueActionOverride,
    }


def main():
    parser = OptionParser()
    logger_options(parser)

    parser.add_option("-Q", "--queue",
                      dest="queue", metavar="QUEUE", default="new",
                      help="Which queue to consider")
    parser.add_option("-D", "--distro",
                      dest="distro", metavar="DISTRO", default="ubuntu",
                      help="Which distro to look in")
    parser.add_option("-R", "--distrorelease",
                      dest="distrorelease", metavar="DISTRORELEASE",
                      default="breezy-autotest",
                      help="Which distrorelease to look in")

    parser.add_option("-N", "--dry-run", action="store_true",
                      dest="dryrun", metavar="DRY_RUN", default=False,
                      help="Whether to treat this as a dry-run or not.")

    parser.add_option("-A", "--announcelist",
                      dest="announcelist", metavar="ANNOUNCELIST",
                      default=None,
                      help="Overrides the announcement list for accepts.")

    options, args = parser.parse_args()

    log = logger(options, "queue")

    print ("Initialising connection to queue %s/%s %s"
           % (options.distro, options.distrorelease, options.queue))

    if options.queue not in name_queue_map:
        print "Unable to map queue name %s" % options.queue
        return

    queue = name_queue_map[options.queue]

    ztm = initZopeless(dbuser=config.uploadqueue.dbuser)
    execute_zcml_for_scripts()

    try:
        distro = getUtility(IDistributionSet).getByName(options.distro)
        distrorelease = distro[options.distrorelease]
        action = args[0]
        arguments = args[1:]
        queue_action = queue_actions[action]
    except NotFoundError, info:
        print 'Unable to found: %s' % info
    except IndexError:
        print 'No <action> <filter> provided.'
    except KeyError:
        print 'Wrong Action: %s' % action
    else:
        try:
            queue_action(distro,distrorelease, queue, arguments).run()
        except QueueActionError, info:
            print info
        else:
            if options.dryrun:
                print "Not Commiting, DRYRUN mode"
                return 1
            ztm.commit()
            return 0
    return 1

if __name__ == '__main__':
    sys.exit(main())
