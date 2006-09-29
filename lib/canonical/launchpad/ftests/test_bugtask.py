# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Bugtask related tests that are too complex to be readable as doctests."""

__metaclass__ = type

import unittest

from zope.component import getUtility

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestCase
from canonical.launchpad.interfaces import (
    BugTaskSearchParams, IBugSet, IDistributionSet, IUpstreamBugTask,
    RESOLVED_BUGTASK_STATUSES, UNRESOLVED_BUGTASK_STATUSES, IBugTaskSet,
    ILaunchBag, IBugWatchSet, IProductSet)
from canonical.launchpad.searchbuilder import any
from canonical.lp.dbschema import BugTaskStatus


class BugTaskSearchBugsElsewhereTest(LaunchpadFunctionalTestCase):
    """Tests for searching bugs filtering on related bug tasks.

    It also acts as a helper class, which makes related doctests more
    readable, since they can use methods from this class."""

    def __init__(self, methodName='runTest', helper_only=False):
        """If helper_only is True, set up it only as a helper class."""
        if not helper_only:
            LaunchpadFunctionalTestCase.__init__(self, methodName=methodName)

    def setUp(self):
        LaunchpadFunctionalTestCase.setUp(self)
        distroset = getUtility(IDistributionSet)

        self.login('test@canonical.com')

        # We don't need to be logged in to run the tests.
        self.login(user=None)

    def _getBugTaskByTarget(self, bug, target):
        """Return a bug's bugtask for the given target."""
        for bugtask in bug.bugtasks:
            if bugtask.target == target:
                return bugtask
        else:
            raise AssertionError(
                "Didn't find a %s task on bug %s." % (
                    target.bugtargetname, bug.id))

    def setUpBugsResolvedUpstreamTests(self):
        """Modify some bugtasks to match the resolved upstream filter."""
        bugset = getUtility(IBugSet)
        productset = getUtility(IProductSet)
        firefox = productset.getByName("firefox")
        thunderbird = productset.getByName("thunderbird")

        # Mark an upstream task on bug #1 "Fix Released"
        bug_one = bugset.get(1)
        firefox_upstream = self._getBugTaskByTarget(bug_one, firefox)
        self.assert_(firefox_upstream.product.official_malone)
        self.old_firefox_status = firefox_upstream.status
        firefox_upstream.transitionToStatus(BugTaskStatus.FIXRELEASED)
        self.firefox_upstream = firefox_upstream

        # Mark an upstream task on bug #9 "Fix Committed"
        bug_nine = bugset.get(9)
        thunderbird_upstream = self._getBugTaskByTarget(bug_nine, thunderbird)
        self.old_thunderbird_status = thunderbird_upstream.status
        thunderbird_upstream.transitionToStatus(BugTaskStatus.FIXCOMMITTED)
        self.thunderbird_upstream = thunderbird_upstream
        
        # Add a watch to a Debian bug for bug #2, and mark the task Fix
        # Released.
        bug_two = bugset.get(2)
        current_user = getUtility(ILaunchBag).user
        bugtaskset = getUtility(IBugTaskSet)
        bugwatchset = getUtility(IBugWatchSet)

        # Get a debbugs watch.
        watch_debbugs_327452 = bugwatchset.get(9)
        self.assertEquals(watch_debbugs_327452.bugtracker.name, "debbugs")
        self.assertEquals(watch_debbugs_327452.remotebug, "327452")

        # Associate the watch to a Fix Released task.
        debian = getUtility(IDistributionSet).getByName("debian")
        debian_firefox = debian.getSourcePackage("mozilla-firefox")
        bug_two_in_debian_firefox = self._getBugTaskByTarget(
            bug_two, debian_firefox)
        bug_two_in_debian_firefox.bugwatch = watch_debbugs_327452
        bug_two_in_debian_firefox.transitionToStatus(BugTaskStatus.FIXRELEASED)

        flush_database_updates()

    def tearDown(self):
        self.login('test@canonical.com')
        self.tearDownBugsElsewhereTests()
        LaunchpadFunctionalTestCase.tearDown(self)

    def tearDownBugsElsewhereTests(self):
        """Resets the modified bugtasks to their original statuses."""
        self.firefox_upstream.transitionToStatus(self.old_firefox_status)
        self.thunderbird_upstream.transitionToStatus(
            self.old_thunderbird_status)
        flush_database_updates()

    def assertBugTaskIsPendingBugWatchElsewhere(self, bugtask):
        """Assert the the bugtask is pending a bug watch elsewhere.

        Pending a bugwatch elsewhere means that at least one of the bugtask's
        related task's target isn't using Malone, and that
        related_bugtask.bugwatch is None.
        """
        non_malone_using_bugtasks = [
            related_task for related_task in bugtask.related_tasks
            if not related_task.target_uses_malone
            ]
        pending_bugwatch_bugtasks = [
            related_bugtask for related_bugtask in non_malone_using_bugtasks
            if related_bugtask.bugwatch is None
            ]
        self.assert_(len(pending_bugwatch_bugtasks) > 0)

    def assertBugTaskIsResolvedUpstream(self, bugtask):
        """Make sure at least one of the related upstream tasks is resolved.
        
        "Resolved", for our purposes, means either that one of the related
        tasks is an upstream task in FIXCOMMITTED or FIXRELEASED state, or
        it is a task with a bugwatch, and in FIXCOMMITTED, FIXRELEASED, or
        REJECTED state.
        """
        resolved_upstream_states = [
            BugTaskStatus.FIXCOMMITTED, BugTaskStatus.FIXRELEASED]
        resolved_bugwatch_states = [
            BugTaskStatus.FIXCOMMITTED, BugTaskStatus.FIXRELEASED,
            BugTaskStatus.REJECTED]

        # Helper functions for the list comprehension below.
        def _is_resolved_upstream_task(bugtask):
            return (
                IUpstreamBugTask.providedBy(bugtask) and
                bugtask.status in resolved_upstream_states)

        def _is_resolved_bugwatch_task(bugtask):
            return (
                bugtask.bugwatch and bugtask.status in
                resolved_bugwatch_states)

        resolved_related_tasks = [
            related_task for related_task in bugtask.related_tasks
            if (_is_resolved_upstream_task(related_task) or
                _is_resolved_bugwatch_task(related_task))
            ]

        self.assert_(len(resolved_related_tasks) > 0)

    def _hasUpstreamTask(self, bug):
        """Does this bug have an upstream task associated with it?

        Returns True if yes, otherwise False.
        """
        for bugtask in bug.bugtasks:
            if IUpstreamBugTask.providedBy(bugtask):
                return True
        return False

    def assertShouldBeShownOnNoUpstreamTaskSearch(self, bugtask):
        """Should the bugtask be shown in the search no upstream task search?

        Returns True if yes, otherwise False.
        """
        self.assert_(not self._hasUpstreamTask(bugtask.bug))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(BugTaskSearchBugsElsewhereTest))
    return suite

if __name__ == '__main__':
    unittest.main()

