# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BugWatchSet."""

__metaclass__ = type

import transaction
import unittest

from datetime import datetime, timedelta
from pytz import utc

from urlparse import urlunsplit

from zope.component import getUtility

from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.launchpad.webapp import urlsplit
from canonical.launchpad.scripts.garbo import BugWatchActivityPruner
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.testing import (
    DatabaseFunctionalLayer, LaunchpadFunctionalLayer, LaunchpadZopelessLayer)

from lp.bugs.interfaces.bugtracker import BugTrackerType, IBugTrackerSet
from lp.bugs.interfaces.bugwatch import (
    BugWatchActivityStatus, IBugWatchSet, NoBugTrackerFound,
    UnrecognizedBugTrackerURL)
from lp.bugs.scripts.checkwatches.scheduler import (
    BugWatchScheduler, MAX_SAMPLE_SIZE)
from lp.registry.interfaces.person import IPersonSet

from lp.testing import TestCaseWithFactory


class ExtractBugTrackerAndBugTestBase:
    """Test base for testing BugWatchSet.extractBugTrackerAndBug."""
    layer = LaunchpadFunctionalLayer

    # A URL to an unregistered bug tracker.
    base_url = None

    # The bug tracker type to be tested.
    bugtracker_type = None

    # A sample URL to a bug in the bug tracker.
    bug_url = None

    # The bug id in the sample bug_url.
    bug_id = None

    def setUp(self):
        login(ANONYMOUS)
        self.bugwatch_set = getUtility(IBugWatchSet)
        self.bugtracker_set = getUtility(IBugTrackerSet)
        self.sample_person = getUtility(IPersonSet).getByEmail(
            'test@canonical.com')

    def test_unknown_baseurl(self):
        # extractBugTrackerAndBug raises an exception if it can't even
        # decide what kind of bug tracker the bug URL points to.
        self.assertRaises(
            UnrecognizedBugTrackerURL,
            self.bugwatch_set.extractBugTrackerAndBug,
            'http://no.such/base/url/42')

    def test_registered_tracker_url(self):
        # If extractBugTrackerAndBug can extract a base URL, and there is a
        # bug tracker registered with that URL, the registered bug
        # tracker will be returned, together with the bug id that was
        # extracted from the bug URL.
        expected_tracker = self.bugtracker_set.ensureBugTracker(
             self.base_url, self.sample_person, self.bugtracker_type)
        bugtracker, bug = self.bugwatch_set.extractBugTrackerAndBug(
            self.bug_url)
        self.assertEqual(bugtracker, expected_tracker)
        self.assertEqual(bug, self.bug_id)

    def test_unregistered_tracker_url(self):
        # A NoBugTrackerFound exception is raised if extractBugTrackerAndBug
        # can extract a base URL and bug id from the URL but there's no
        # such bug tracker registered in Launchpad.
        self.failUnless(
            self.bugtracker_set.queryByBaseURL(self.base_url) is None)
        try:
            bugtracker, bug = self.bugwatch_set.extractBugTrackerAndBug(
                self.bug_url)
        except NoBugTrackerFound, error:
            # The raised exception should contain enough information so
            # that we can register a new bug tracker.
            self.assertEqual(error.base_url, self.base_url)
            self.assertEqual(error.remote_bug, self.bug_id)
            self.assertEqual(error.bugtracker_type, self.bugtracker_type)
        else:
            self.fail(
                "NoBugTrackerFound wasn't raised by extractBugTrackerAndBug")


class MantisExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Mantis URLs."""

    bugtracker_type = BugTrackerType.MANTIS
    bug_url = 'http://some.host/bugs/view.php?id=3224'
    base_url = 'http://some.host/bugs/'
    bug_id = '3224'


class BugzillaExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Bugzilla URLs."""

    bugtracker_type = BugTrackerType.BUGZILLA
    bug_url = 'http://some.host/bugs/show_bug.cgi?id=3224'
    base_url = 'http://some.host/bugs/'
    bug_id = '3224'


class IssuezillaExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Issuezilla.

    Issuezilla is practically the same as Buzilla, so we treat it as a
    normal BUGZILLA type.
    """

    bugtracker_type = BugTrackerType.BUGZILLA
    bug_url = 'http://some.host/bugs/show_bug.cgi?issue=3224'
    base_url = 'http://some.host/bugs/'
    bug_id = '3224'


class RoundUpExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with RoundUp URLs."""

    bugtracker_type = BugTrackerType.ROUNDUP
    bug_url = 'http://some.host/some/path/issue377'
    base_url = 'http://some.host/some/path/'
    bug_id = '377'


class TracExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Trac URLs."""

    bugtracker_type = BugTrackerType.TRAC
    bug_url = 'http://some.host/some/path/ticket/42'
    base_url = 'http://some.host/some/path/'
    bug_id = '42'


class DebbugsExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Debbugs URLs."""

    bugtracker_type = BugTrackerType.DEBBUGS
    bug_url = 'http://some.host/some/path/cgi-bin/bugreport.cgi?bug=42'
    base_url = 'http://some.host/some/path/'
    bug_id = '42'


class DebbugsExtractBugTrackerAndBugShorthandTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure extractBugTrackerAndBug works for short Debbugs URLs."""

    bugtracker_type = BugTrackerType.DEBBUGS
    bug_url = 'http://bugs.debian.org/42'
    base_url = 'http://bugs.debian.org/'
    bug_id = '42'

    def test_unregistered_tracker_url(self):
        # bugs.debian.org is already registered, so no dice.
        pass

class SFExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with SF URLs.

    We have only one SourceForge tracker registered in Launchpad, so we
    don't care about the aid and group_id, only about atid which is the
    bug id.
    """

    bugtracker_type = BugTrackerType.SOURCEFORGE
    bug_url = (
        'http://sourceforge.net/tracker/index.php'
        '?func=detail&aid=1568562&group_id=84122&atid=575154')
    base_url = 'http://sourceforge.net/'
    bug_id = '1568562'

    def test_unregistered_tracker_url(self):
        # The SourceForge tracker is always registered, so this test
        # doesn't make sense for SourceForge URLs.
        pass

    def test_aliases(self):
        """Test that parsing SourceForge URLs works with the SF aliases."""
        original_bug_url = self.bug_url
        original_base_url = self.base_url
        url_bits = urlsplit(original_bug_url)
        sf_bugtracker = self.bugtracker_set.getByName(name='sf')

        # Carry out all the applicable tests for each alias.
        for alias in sf_bugtracker.aliases:
            alias_bits = urlsplit(alias)
            self.base_url = alias

            bug_url_bits = (
                alias_bits[0],
                alias_bits[1],
                url_bits[2],
                url_bits[3],
                url_bits[4],
                )

            self.bug_url = urlunsplit(bug_url_bits)

            self.test_registered_tracker_url()
            self.test_unknown_baseurl()

        self.bug_url = original_bug_url
        self.base_url = original_base_url


class SFTracker2ExtractBugTrackerAndBugTest(SFExtractBugTrackerAndBugTest):
    """Ensure extractBugTrackerAndBug works for new SF tracker URLs."""

    bugtracker_type = BugTrackerType.SOURCEFORGE
    bug_url = (
        'http://sourceforge.net/tracker2/'
        '?func=detail&aid=1568562&group_id=84122&atid=575154')
    base_url = 'http://sourceforge.net/'
    bug_id = '1568562'


class XForgeExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure extractBugTrackerAndBug works with SourceForge-like URLs.
    """

    bugtracker_type = BugTrackerType.SOURCEFORGE
    bug_url = (
        'http://gforge.example.com/tracker/index.php'
        '?func=detail&aid=90812&group_id=84122&atid=575154')
    base_url = 'http://gforge.example.com/'
    bug_id = '90812'


class RTExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with RT URLs."""

    bugtracker_type = BugTrackerType.RT
    bug_url = 'http://some.host/Ticket/Display.html?id=2379'
    base_url = 'http://some.host/'
    bug_id = '2379'


class CpanExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with CPAN URLs."""

    bugtracker_type = BugTrackerType.RT
    bug_url = 'http://rt.cpan.org/Public/Bug/Display.html?id=2379'
    base_url = 'http://rt.cpan.org/'
    bug_id = '2379'


class SavannahExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Savannah URLs.
    """

    bugtracker_type = BugTrackerType.SAVANE
    bug_url = 'http://savannah.gnu.org/bugs/?22003'
    base_url = 'http://savannah.gnu.org/'
    bug_id = '22003'

    def test_unregistered_tracker_url(self):
        # The Savannah tracker is always registered, so this test
        # doesn't make sense for Savannah URLs.
        pass


class SavaneExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with Savane URLs.
    """

    bugtracker_type = BugTrackerType.SAVANE
    bug_url = 'http://savane.example.com/bugs/?12345'
    base_url = 'http://savane.example.com/'
    bug_id = '12345'


class EmailAddressExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with email addresses.
    """

    bugtracker_type = BugTrackerType.EMAILADDRESS
    bug_url = 'mailto:foo.bar@example.com'
    base_url = 'mailto:foo.bar@example.com'
    bug_id = ''

    def test_extract_bug_tracker_and_bug_rejects_invalid_email_address(self):
        # BugWatch.extractBugTrackerAndBug() will reject invalid email
        # addresses.
        self.assertRaises(UnrecognizedBugTrackerURL,
            self.bugwatch_set.extractBugTrackerAndBug,
            url='this\.is@@a.bad.email.address')


class PHPProjectBugTrackerExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works with PHP bug URLs.
    """

    bugtracker_type = BugTrackerType.PHPPROJECT
    bug_url = 'http://phptracker.example.com/bug.php?id=12345'
    base_url = 'http://phptracker.example.com/'
    bug_id = '12345'


class GoogleCodeBugTrackerExtractBugTrackerAndBugTest(
    ExtractBugTrackerAndBugTestBase, unittest.TestCase):
    """Ensure BugWatchSet.extractBugTrackerAndBug works for Google Code URLs.
    """

    bugtracker_type = BugTrackerType.GOOGLE_CODE
    bug_url = 'http://code.google.com/p/myproject/issues/detail?id=12345'
    base_url = 'http://code.google.com/p/myproject/issues'
    bug_id = '12345'


class TestBugWatchSet(TestCaseWithFactory):
    """Tests for the bugwatch updating system."""

    layer = LaunchpadZopelessLayer

    def test_getBugWatchesForRemoteBug(self):
        # getBugWatchesForRemoteBug() returns bug watches from that
        # refer to the remote bug.
        bug_watches_alice = [
            self.factory.makeBugWatch(remote_bug="alice"),
            ]
        bug_watches_bob = [
            self.factory.makeBugWatch(remote_bug="bob"),
            self.factory.makeBugWatch(remote_bug="bob"),
            ]
        bug_watch_set = getUtility(IBugWatchSet)
        # Passing in the remote bug ID gets us every bug watch that
        # refers to that remote bug.
        self.failUnlessEqual(
            set(bug_watches_alice),
            set(bug_watch_set.getBugWatchesForRemoteBug('alice')))
        self.failUnlessEqual(
            set(bug_watches_bob),
            set(bug_watch_set.getBugWatchesForRemoteBug('bob')))
        # The search can be narrowed by passing in a list or other
        # iterable collection of bug watch IDs.
        bug_watches_limited = bug_watches_alice + bug_watches_bob[:1]
        self.failUnlessEqual(
            set(bug_watches_bob[:1]),
            set(bug_watch_set.getBugWatchesForRemoteBug('bob', [
                        bug_watch.id for bug_watch in bug_watches_limited])))


class TestBugWatchBugTasks(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugWatchBugTasks, self).setUp('test@canonical.com')
        self.bug_watch = self.factory.makeBugWatch()

    def test_bugtasks(self):
        # BugWatch.bugtasks is always a list.
        self.assertIsInstance(
            self.bug_watch.bugtasks, list)


class TestBugWatchActivityPruner(TestCaseWithFactory):
    """TestCase for the BugWatchActivityPruner."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestBugWatchActivityPruner, self).setUp(
            'foo.bar@canonical.com')
        self.bug_watch = self.factory.makeBugWatch()
        for i in range(10):
            self.bug_watch.addActivity()

        self.pruner = BugWatchActivityPruner(QuietFakeLogger())
        transaction.commit()

    def test_getPrunableBugWatchIds(self):
        # BugWatchActivityPruner.getPrunableBugWatchIds() will return a
        # set containing the IDs of BugWatches whose activity can be
        # pruned.
        prunable_ids = self.pruner.getPrunableBugWatchIds(1)
        self.assertEqual(1, len(prunable_ids))
        self.failUnless(
            self.bug_watch.id in prunable_ids,
            "BugWatch ID not present in prunable_ids.")

        # Even if we specify a bigger chunk size, only one result will
        # be returned.
        prunable_ids = self.pruner.getPrunableBugWatchIds(10)
        self.assertEqual(1, len(prunable_ids))

        # If we add another BugWatch with prunable activity, it too will
        # be returned.
        new_watch = self.factory.makeBugWatch()
        for i in range(10):
            new_watch.addActivity()

        prunable_ids = self.pruner.getPrunableBugWatchIds(10)
        self.assertEqual(2, len(prunable_ids))

    def test_pruneBugWatchActivity(self):
        # BugWatchActivityPruner.pruneBugWatchActivity() will prune the
        # activity for all the BugWatches whose IDs are passed to it.
        prunable_ids = self.pruner.getPrunableBugWatchIds(1)

        self.layer.switchDbUser('garbo')
        self.pruner.pruneBugWatchActivity(prunable_ids)

        prunable_ids = self.pruner.getPrunableBugWatchIds(1)
        self.assertEqual(0, len(prunable_ids))

    def test_call_prunes_activity(self):
        # BugWatchActivityPruner is a callable object. Calling it will
        # cause it to prune the BugWatchActivity of prunable watches.
        self.layer.switchDbUser('garbo')
        self.pruner(chunk_size=1)

        prunable_ids = self.pruner.getPrunableBugWatchIds(1)
        self.assertEqual(0, len(prunable_ids))

    def test_isDone(self):
        # BugWatchActivityPruner.isDone() returns True when there are no
        # more prunable BugWatches. Until then, it returns False.
        self.layer.switchDbUser('garbo')
        self.assertFalse(self.pruner.isDone())
        self.pruner(chunk_size=1)
        self.assertTrue(self.pruner.isDone())

    def test_pruneBugWatchActivity_leaves_most_recent(self):
        # BugWatchActivityPruner.pruneBugWatchActivity() will delete all
        # but the n most recent BugWatchActivity items for a bug watch,
        # where n is determined by checkwatches.scheduler.MAX_SAMPLE_SIZE.
        for i in range(5):
            self.bug_watch.addActivity(message="Activity %s" % i)
        transaction.commit()

        self.layer.switchDbUser('garbo')
        self.assertEqual(15, self.bug_watch.activity.count())
        self.pruner.pruneBugWatchActivity([self.bug_watch.id])
        self.assertEqual(MAX_SAMPLE_SIZE, self.bug_watch.activity.count())

        messages = [activity.message for activity in self.bug_watch.activity]
        for i in range(MAX_SAMPLE_SIZE):
            self.failUnless("Activity %s" % i in messages)


class TestBugWatchScheduler(TestCaseWithFactory):
    """Tests for the BugWatchScheduler, which runs as part of garbo."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugWatchScheduler, self).setUp('foo.bar@canonical.com')
        # We'll make sure that all the other bug watches look like
        # they've been scheduled so that only our watch gets scheduled.
        for watch in getUtility(IBugWatchSet).search():
            watch.next_check = datetime.now(utc)
        self.bug_watch = self.factory.makeBugWatch()
        self.scheduler = BugWatchScheduler(QuietFakeLogger())
        transaction.commit()

    def test_scheduler_schedules_unchecked_watches(self):
        # The BugWatchScheduler will schedule a BugWatch that has never
        # been checked to be checked immediately.
        self.bug_watch.next_check = None
        self.scheduler(1)

        self.assertNotEqual(None, self.bug_watch.next_check)
        self.assertTrue(
            self.bug_watch.next_check <= datetime.now(utc))

    def test_scheduler_schedules_working_watches(self):
        # If a watch has been checked and has never failed its next
        # check will be scheduled for 24 hours after its last check.
        now = datetime.now(utc)
        self.bug_watch.lastchecked = now
        self.bug_watch.next_check = None
        transaction.commit()
        self.scheduler(1)

        self.assertEqual(
            now + timedelta(hours=24), self.bug_watch.next_check)

    def test_scheduler_schedules_failing_watches(self):
        # If a watch has failed once, it will be scheduled more than 24
        # hours after its last check.
        now = datetime.now(utc)
        self.bug_watch.lastchecked = now

        # The delay depends on the number of failures that the watch has
        # had.
        for failure_count in range(1, 6):
            self.bug_watch.next_check = None
            self.bug_watch.addActivity(
                result=BugWatchActivityStatus.BUG_NOT_FOUND)
            transaction.commit()
            self.scheduler(1)

            coefficient = self.scheduler.delay_coefficient * failure_count
            self.assertEqual(
                now + timedelta(days=1 + coefficient),
                self.bug_watch.next_check)

        # The scheduler only looks at the last 5 activity items, so even
        # if there have been more failures the maximum delay will be 7
        # days.
        for count in range(10):
            self.bug_watch.addActivity(
                result=BugWatchActivityStatus.BUG_NOT_FOUND)
        self.bug_watch.next_check = None
        transaction.commit()
        self.scheduler(1)
        self.assertEqual(
            now + timedelta(days=7), self.bug_watch.next_check)

    def test_scheduler_doesnt_schedule_scheduled_watches(self):
        # The scheduler will ignore watches whose next_check has been
        # set.
        next_check_date = datetime.now(utc) + timedelta(days=1)
        self.bug_watch.next_check = next_check_date
        transaction.commit()
        self.scheduler(1)

        self.assertEqual(next_check_date, self.bug_watch.next_check)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
