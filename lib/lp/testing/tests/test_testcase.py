# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests relating to the Launchpad TestCase classes here."""

__metaclass__ = type

from StringIO import StringIO
import sys
import unittest

from storm.store import Store
from zope.component import getUtility

from canonical.launchpad.webapp import errorlog
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    FunctionalLayer,
    )
from lp.code.interfaces.branch import IBranchSet
from lp.testing import (
    record_statements,
    TestCaseWithFactory,
    )


class TestRecordStatements(TestCaseWithFactory):
    """Test the statement recorder."""

    layer = DatabaseFunctionalLayer

    def test_counter_positive(self):
        # The base TestCase setUp adds a statement counter.
        branch, statements = record_statements(self.factory.makeBranch)
        self.assertTrue(len(statements) > 0)

    def test_store_invalidation_counts(self):
        # When creating objects with the factory, they stay in the storm
        # cache, sometimes we want to confirm that no more queries are
        # happening, so we need to clear the cache to avoid getting cached
        # objects where there would normally be queries.
        branch = self.factory.makeBranch()
        store = Store.of(branch)

        # Make sure everything is in the database.
        store.flush()
        # Reset the store to clear the cache (not just invalidate).
        store.reset()
        branch = getUtility(IBranchSet).getByUniqueName(branch.unique_name)
        self.assertStatementCount(1, getattr, branch, "owner")


class TestCaptureOops(TestCaseWithFactory):

    layer = FunctionalLayer

    def trigger_oops(self):
        try:
            raise AssertionError("Exception to get a traceback.")
        except AssertionError:
            errorlog.globalErrorUtility.raising(sys.exc_info())

    def test_no_oops_gives_no_details(self):
        self.assertEqual(0, len(self.oopses))
        self.attachOopses()
        self.assertEqual(
            0, len([a for a in self.getDetails() if "oops" in a]))

    def test_one_oops_gives_one_detail(self):
        self.assertEqual(0, len(self.oopses))
        self.trigger_oops()
        self.attachOopses()
        self.assertEqual(
            ["oops-0"], [a for a in self.getDetails() if "oops" in a])

    def test_two_oops_gives_two_details(self):
        self.assertEqual(0, len(self.oopses))
        self.trigger_oops()
        self.trigger_oops()
        self.attachOopses()
        self.assertEqual(
            ["oops-0", "oops-1"],
            sorted([a for a in self.getDetails() if "oops" in a]))

    def test_oops_content(self):
        self.assertEqual(0, len(self.oopses))
        self.trigger_oops()
        self.attachOopses()
        oops = errorlog.globalErrorUtility.getLastOopsReport()
        # We have to serialise and read in again, as that is what
        # getLastOopsReport does, and doing so changes whether the
        # timezone is in the timestamp.
        content = StringIO()
        content.writelines(self.getDetails()['oops-0'].iter_text())
        content.seek(0)
        from_details = errorlog.ErrorReport.read(content)
        self.assertEqual(
            oops.get_chunks(),
            from_details.get_chunks())


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

