# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BugWatch', 'BugWatchSet']

import re
import cgi
import urllib
import urlparse

from zope.interface import implements
from zope.component import getUtility

# SQL imports
from sqlobject import ForeignKey, StringCol, SQLObjectNotFound, SQLMultipleJoin

from canonical.lp.dbschema import (
    BugTrackerType, BugTaskPriority, BugTaskImportance)

from canonical.database.sqlbase import SQLBase, flush_database_updates
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import (
    IBugWatch, IBugWatchSet, IBugTrackerSet, NotFoundError)
from canonical.launchpad.database.bugset import BugSetBase


bugzillaref = re.compile(r'(https?://.+/)show_bug.cgi.+id=(\d+).*')
roundupref = re.compile(r'(https?://.+/)issue(\d+).*')
tracref = re.compile(r'(https?://.+/)tickets/(\d+)')


class BugWatch(SQLBase):
    """See canonical.launchpad.interfaces.IBugWatch."""
    implements(IBugWatch)
    _table = 'BugWatch'
    bug = ForeignKey(dbName='bug', foreignKey='Bug', notNull=True)
    bugtracker = ForeignKey(dbName='bugtracker',
                foreignKey='BugTracker', notNull=True)
    remotebug = StringCol(notNull=True)
    remotestatus = StringCol(notNull=False, default=None)
    lastchanged = UtcDateTimeCol(notNull=False, default=None)
    lastchecked = UtcDateTimeCol(notNull=False, default=None)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)

    # useful joins
    bugtasks = SQLMultipleJoin('BugTask', joinColumn='bugwatch',
        orderBy=['-datecreated'])

    @property
    def title(self):
        """See canonical.launchpad.interfaces.IBugWatch."""
        return "%s #%s" % (self.bugtracker.title, self.remotebug)

    @property
    def url(self):
        """See canonical.launchpad.interfaces.IBugWatch."""
        url_formats = {
            # XXX 20050712 kiko: slash-suffixing the bugtracker baseurl
            # protects us from the bugtracker baseurl not ending in
            # slashes -- should we instead ensure when it is entered?
            # Filed bug 1434.
            BugTrackerType.BUGZILLA: '%s/show_bug.cgi?id=%s',
            BugTrackerType.TRAC:     '%s/ticket/%s',
            BugTrackerType.DEBBUGS:  '%s/cgi-bin/bugreport.cgi?bug=%s',
            BugTrackerType.ROUNDUP:  '%s/issue%s'
        }
        bt = self.bugtracker.bugtrackertype
        if bt == BugTrackerType.SOURCEFORGE:
            return self._sf_url()
        elif not url_formats.has_key(bt):
            raise AssertionError('Unknown bug tracker type %s' % bt)
        return url_formats[bt] % (self.bugtracker.baseurl, self.remotebug)

    def _sf_url(self):
        # XXX: validate that the bugtracker URL has atid and group_id in
        # it.
        #
        # Sourceforce has a pretty nasty URL model, with two codes that
        # specify what project are looking at. This code disassembles
        # it, sets the bug number and then reassembles it again.
        # http://sourceforge.net/tracker/?atid=737291
        #                                &group_id=136955
        #                                &func=detail
        #                                &aid=1337833
        method, base, path, query, frag = \
            urlparse.urlsplit(self.bugtracker.baseurl)
        params = cgi.parse_qs(query)
        params['func'] = "detail"
        params['aid'] = self.remotebug
        param_string = urllib.urlencode(params, doseq=True)
        return urlparse.urlunsplit((method, base, path, param_string, frag))

    @property
    def needscheck(self):
        """See canonical.launchpad.interfaces.IBugWatch."""
        return True

    def updateStatus(self, remote_status, malone_status):
        """See IBugWatch."""
        self.remotestatus = remote_status
        self.lastchanged = UTC_NOW
        for linked_bugtask in self.bugtasks:
            linked_bugtask.status = malone_status
            # We don't yet support updating the following values.
            linked_bugtask.priority = BugTaskPriority.UNKNOWN
            linked_bugtask.importance = BugTaskImportance.UNKNOWN
            linked_bugtask.assignee = None


class BugWatchSet(BugSetBase):
    """A set for BugWatch"""

    implements(IBugWatchSet)
    table = BugWatch

    def __init__(self, bug=None):
        BugSetBase.__init__(self, bug)
        self.title = 'A set of bug watches'

    def get(self, watch_id):
        """See canonical.launchpad.interfaces.IBugWatchSet."""
        try:
            return BugWatch.get(watch_id)
        except SQLObjectNotFound:
            raise NotFoundError, watch_id

    def search(self):
        return BugWatch.select()

    def _find_watches(self, pattern, trackertype, text, bug, owner):
        """Find the watches in a piece of text, based on a given pattern and
        tracker type."""
        newwatches = []
        # let's look for matching entries
        matches = pattern.findall(text)
        if len(matches) == 0:
            return []
        for match in matches:
            # let's see if we already know about this bugtracker
            bugtrackerset = getUtility(IBugTrackerSet)
            baseurl = match[0]
            remotebug = match[1]
            # make sure we have a bugtracker
            bugtracker = bugtrackerset.ensureBugTracker(baseurl, owner,
                trackertype)
            # see if there is a bugwatch for this remote bug on this bug
            bugwatch = None
            for watch in bug.watches:
                if (watch.bugtracker == bugtracker and
                    watch.remotebug == remotebug):
                    bugwatch = watch
                    break
            if bugwatch is None:
                bugwatch = BugWatch(bugtracker=bugtracker, bug=bug,
                    remotebug=remotebug, owner=owner)
                newwatches.append(bugwatch)
                if len(newwatches) > 0:
                    flush_database_updates()
        return newwatches

    def fromText(self, text, bug, owner):
        """See IBugTrackerSet.fromText."""
        watches = set([])
        for pattern, trackertype in [
            (bugzillaref, BugTrackerType.BUGZILLA),
            (roundupref, BugTrackerType.ROUNDUP),
            (tracref, BugTrackerType.TRAC),
            ]:
            watches = watches.union(self._find_watches(pattern, 
                trackertype, text, bug, owner))
        return sorted(watches, key=lambda a: (a.bugtracker.name,
            a.remotebug))

    def fromMessage(self, message, bug):
        """See IBugWatchSet."""
        watches = set()
        for messagechunk in message:
            if messagechunk.blob is not None:
                # we don't process attachments
                continue
            elif messagechunk.content is not None:
                # look for potential BugWatch URL's and create the trackers
                # and watches as needed
                watches = watches.union(self.fromText(messagechunk.content,
                    bug, message.owner))
            else:
                raise AssertionError('MessageChunk without content or blob.')
        return sorted(watches, key=lambda a: a.remotebug)

    def createBugWatch(self, bug, owner, bugtracker, remotebug):
        """See canonical.launchpad.interfaces.IBugWatchSet."""
        return BugWatch(
            bug=bug, owner=owner, datecreated=UTC_NOW, lastchanged=UTC_NOW, 
            bugtracker=bugtracker, remotebug=remotebug)

