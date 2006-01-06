# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BugTracker', 'BugTrackerSet']

import urllib

from zope.interface import implements

from sqlobject import ForeignKey, StringCol, MultipleJoin, RelatedJoin
from sqlobject.sqlbuilder import AND

from canonical.launchpad.helpers import shortlist
from canonical.lp.dbschema import EnumCol, BugTrackerType
from canonical.database.sqlbase import (SQLBase, flush_database_updates,
    quote)
from canonical.launchpad.database.bug import Bug
from canonical.launchpad.database.bugwatch import BugWatch
from canonical.launchpad.interfaces import (
    IBugTracker, IBugTrackerSet, NotFoundError)



class BugTracker(SQLBase):
    """A class to access the BugTracker table of the db. Each BugTracker is a
    distinct instance of that bug tracking tool. For example, each Bugzilla
    deployment is a separate BugTracker. bugzilla.mozilla.org and
    bugzilla.gnome.org are each distinct BugTracker's.
    """
    implements(IBugTracker)
    _table = 'BugTracker'
    bugtrackertype = EnumCol(dbName='bugtrackertype',
        schema=BugTrackerType, notNull=True)
    name = StringCol(notNull=True, unique=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    baseurl = StringCol(notNull=True)
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    contactdetails = StringCol(notNull=False)
    watches = MultipleJoin('BugWatch', joinColumn='bugtracker',
        orderBy='remotebug')
    projects = RelatedJoin('Project', intermediateTable='ProjectBugTracker',
        joinColumn='bugtracker', otherColumn='project',
        orderBy='name')

    @property
    def watches(self):
        """See IBugTracker"""
        return BugWatch.selectBy(bugtrackerID=self.id, orderBy="remotebug")

    @property
    def latestwatches(self):
        """See IBugTracker"""
        return BugWatch.selectBy(
            bugtrackerID=self.id, orderBy="-datecreated")[:10]

    def getBugsWatching(self, remotebug):
        """See IBugTracker"""
        return shortlist(Bug.select(AND(BugWatch.q.bugID == Bug.q.id,
                                        BugWatch.q.bugtrackerID == self.id,
                                        BugWatch.q.remotebug == remotebug),
                                    distinct=True,
                                    orderBy=['datecreated']))


class BugTrackerSet:
    """Implements IBugTrackerSet for a container or set of BugTracker's,
    either the full set in the db, or a subset.
    """

    implements(IBugTrackerSet)

    table = BugTracker

    def __init__(self):
        self.title = 'Launchpad-registered Bug Trackers'

    def __getitem__(self, name):
        item = self.table.selectOne(self.table.q.name == name)
        if item is None:
            raise NotFoundError(name)
        else:
            return item

    def __iter__(self):
        for row in self.table.select():
            yield row

    def normalise_baseurl(self, baseurl):
        # turn https to http, and raise an exception elsewhere
        schema, rest = urllib.splittype(baseurl)
        if schema not in ['http', 'https']:
            return baseurl
        if schema == 'https':
            schema = 'http'
        return '%s:%s' % (schema, rest)

    def queryByBaseURL(self, baseurl):
        return BugTracker.selectOneBy(baseurl=baseurl)

    def search(self):
        """See canonical.launchpad.interfaces.IBugTrackerSet."""
        return BugTracker.select()

    def ensureBugTracker(self, baseurl, owner, bugtrackertype,
        title=None, summary=None, contactdetails=None, name=None):
        # first try and find one without normalisation
        bugtracker = self.queryByBaseURL(baseurl)
        if bugtracker is not None:
            return bugtracker
        # now try and normalise it
        baseurl = self.normalise_baseurl(baseurl)
        bugtracker = self.queryByBaseURL(baseurl)
        if bugtracker is not None:
            return bugtracker
        # create the bugtracker, we don't know about it. we'll use the
        # normalised base url
        if name is None:
            scheme, host = urllib.splittype(baseurl)
            host, path = urllib.splithost(host)
            name = 'auto-%s' % host
        if title is None:
            title = quote('Bug tracker at %s' % baseurl)
        if summary is None:
            summary = ("This bugtracker was automatically created. Please "
                       "edit the details to get it correct!")
        if contactdetails is None:
            contactdetails = 'No contact details provided.'
        bugtracker = BugTracker(name=name,
            bugtrackertype=bugtrackertype,
            title=title, summary=summary, baseurl=baseurl,
            contactdetails=contactdetails, owner=owner)
        flush_database_updates()
        return bugtracker

    @property
    def bugtracker_count(self):
        return BugTracker.select().count()

    def getMostActiveBugTrackers(self, limit=None):
        """See canonical.launchpad.interfaces.IBugTrackerSet."""
        result = shortlist(self.search(), longest_expected=20)
        result.sort(key=lambda bugtracker: -bugtracker.watches.count())
        if limit and limit > 0:
            return result[:limit]
        else:
            return result

