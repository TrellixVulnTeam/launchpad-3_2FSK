# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

from zope.testing.doctest import NORMALIZE_WHITESPACE, ELLIPSIS
from zope.testing.doctestunit import DocTestSuite

from lazr.lifecycle.snapshot import Snapshot

from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.testing import LaunchpadFunctionalLayer

from lp.bugs.interfaces.bugtracker import BugTrackerType, IBugTracker
from lp.testing import TestCaseWithFactory


class TestBugTracker(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        login(ANONYMOUS)

    def test_multi_product_constraints_observed(self):
        """BugTrackers for which multi_product=True should return None
        when no remote product is passed to getBugFilingURL().

        BugTrackers for which multi_product=False should still return a
        URL even when getBugFilingURL() is passed no remote product.
        """
        for type in BugTrackerType.items:
            bugtracker = self.factory.makeBugTracker(bugtrackertype=type)

            bugtracker_urls = bugtracker.getBugFilingAndSearchLinks(None)
            bug_filing_url = bugtracker_urls['bug_filing_url']
            bug_search_url = bugtracker_urls['bug_search_url']

            if bugtracker.multi_product:
                self.assertTrue(
                    bug_filing_url is None,
                    "getBugFilingAndSearchLinks() should return a "
                    "bug_filing_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
                self.assertTrue(
                    bug_search_url is None,
                    "getBugFilingAndSearchLinks() should return a "
                    "bug_search_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
            else:
                self.assertTrue(
                    bug_filing_url is not None,
                    "getBugFilingAndSearchLinks() should not return a "
                    "bug_filing_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
                self.assertTrue(
                    bug_search_url is not None,
                    "getBugFilingAndSearchLinks() should not return a "
                    "bug_search_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)

    def test_watches_not_in_snapshot(self):
        # A snapshot of an IBugTracker will not contain a copy of the
        # 'watches' property.
        marker = object()
        original = self.factory.makeBugTracker()
        self.failUnless(getattr(original, 'watches', marker) is not marker)
        snapshot = Snapshot(original, providing=IBugTracker)
        self.failUnless(getattr(snapshot, 'watches', marker) is marker)


def test_suite():
    suite = unittest.TestSuite()
    doctest_suite = DocTestSuite(
        'lp.bugs.model.bugtracker',
        optionflags=NORMALIZE_WHITESPACE|ELLIPSIS)

    suite.addTest(unittest.makeSuite(TestBugTracker))
    suite.addTest(doctest_suite)
    return suite

