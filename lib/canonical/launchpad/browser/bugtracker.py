# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Bug tracker views."""

__metaclass__ = type

__all__ = [
    'BugTrackerSetNavigation',
    'BugTrackerContextMenu',
    'BugTrackerSetContextMenu',
    'BugTrackerView',
    'BugTrackerAddView',
    'BugTrackerEditView',
    'BugTrackerNavigation',
    'RemoteBug',
    ]

from zope.interface import implements
from zope.component import getUtility
from zope.app.form.browser.editview import EditView

from canonical.launchpad.interfaces import (
    IProject, IProjectBugTrackerSet, IBugTracker, IBugTrackerSet, IRemoteBug,
    ILaunchBag)
from canonical.launchpad.webapp import (
    canonical_url, ContextMenu, Link, Navigation, GetitemNavigation,
    redirection, LaunchpadView)
from canonical.launchpad.webapp.batching import BatchNavigator


class BugTrackerSetNavigation(GetitemNavigation):

    usedfor = IBugTrackerSet

    def breadcrumb(self):
        return 'Remote Bug Trackers'


class BugTrackerContextMenu(ContextMenu):

    usedfor = IBugTracker

    links = ['edit']

    def edit(self):
        text = 'Change Details'
        return Link('+edit', text, icon='edit')


class BugTrackerSetContextMenu(ContextMenu):

    usedfor = IBugTrackerSet

    links = ['newbugtracker']

    def newbugtracker(self):
        text = 'Register Bug Tracker'
        return Link('+newbugtracker', text, icon='add')


class BugTrackerAddView:

    def create(self, name, bugtrackertype, title, summary, baseurl,
               contactdetails):
        """Create the IBugTracker."""
        btset = getUtility(IBugTrackerSet)
        bugtracker = btset.ensureBugTracker(
            name=name,
            bugtrackertype=bugtrackertype,
            title=title,
            summary=summary,
            baseurl=baseurl,
            contactdetails=contactdetails,
            owner=getUtility(ILaunchBag).user)
        # if we are creating this on a Project then we should link to it too
        if IProject.providedBy(self.context):
            projectbugtracker = getUtility(IProjectBugTrackerSet).new(
                project=self.context,
                bugtracker=bugtracker)
        # keep track of the new one
        self._newtracker_ = bugtracker
        return bugtracker

    def add(self, content):
        return content

    def nextURL(self):
        return canonical_url(self._newtracker_)


class BugTrackerView(LaunchpadView):

    usedfor = IBugTracker

    def initialize(self):
        self.batchnav = BatchNavigator(self.context.watches, self.request)


class BugTrackerEditView(EditView):

    usedfor = IBugTracker

    def changed(self):
        self.request.response.redirect(canonical_url(self.context))


class BugTrackerNavigation(Navigation):

    usedfor = IBugTracker

    def breadcrumb(self):
        return self.context.title

    def traverse(self, remotebug):
        bugs = self.context.getBugsWatching(remotebug)
        if len(bugs) == 0:
            # no bugs watching => not found
            return None
        elif len(bugs) == 1:
            # one bug watching => redirect to that bug
            return redirection(canonical_url(bugs[0]))
        else:
            # else list the watching bugs
            return RemoteBug(self.context, remotebug, bugs)


class RemoteBug:
    """Represents a bug in a remote bug tracker."""

    implements(IRemoteBug)

    def __init__(self, bugtracker, remotebug, bugs):
        self.bugtracker = bugtracker
        self.remotebug = remotebug
        self.bugs = bugs

    @property
    def title(self):
        return 'Remote Bug #%s in %s' % (self.remotebug,
                                         self.bugtracker.title)

