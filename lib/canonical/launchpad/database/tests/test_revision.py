# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Tests for Revisions."""

__metaclass__ = type

import datetime
import time
from unittest import TestCase, TestLoader

import psycopg2
import pytz
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.sqlbase import cursor
from canonical.launchpad.ftests import login, logout
from canonical.launchpad.interfaces import (
    IBranchSet, IRevisionSet)
from canonical.launchpad.testing import LaunchpadObjectFactory
from canonical.testing import LaunchpadZopelessLayer


class TestTipRevisionsForBranches(TestCase):
    """Test that the tip revisions get returned properly."""

    # The LaunchpadZopelessLayer is used as the setUp needs to
    # switch database users in order to create revisions for the
    # test branches.
    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('test@canonical.com')

        factory = LaunchpadObjectFactory()
        branches = [factory.makeBranch() for count in range(5)]
        branch_ids = [branch.id for branch in branches]
        transaction.commit()
        launchpad_dbuser = config.launchpad.dbuser
        LaunchpadZopelessLayer.switchDbUser(config.branchscanner.dbuser)
        for branch in branches:
            factory.makeRevisionsForBranch(branch)
        transaction.commit()
        LaunchpadZopelessLayer.switchDbUser(launchpad_dbuser)
        # Retrieve the updated branches (due to transaction boundaries).
        branch_set = getUtility(IBranchSet)
        self.branches = [branch_set.get(id) for id in branch_ids]
        self.revision_set = getUtility(IRevisionSet)

    def tearDown(self):
        logout()

    def _breakTransaction(self):
        # make sure the current transaction can not be committed by
        # sending a broken SQL statement to the database
        try:
            cursor().execute('break this transaction')
        except psycopg2.DatabaseError:
            pass

    def testNoBranches(self):
        """Assert that when given an empty list, an empty list is returned."""
        bs = self.revision_set
        revisions = bs.getTipRevisionsForBranches([])
        self.assertTrue(revisions is None)

    def testOneBranches(self):
        """When given one branch, one branch revision is returned."""
        revisions = list(
            self.revision_set.getTipRevisionsForBranches(
                self.branches[:1]))
        # XXX jamesh 2008-06-02: ensure that branch[0] is loaded
        self.branches[0].last_scanned_id
        self._breakTransaction()
        self.assertEqual(1, len(revisions))
        revision = revisions[0]
        self.assertEqual(self.branches[0].last_scanned_id,
                         revision.revision_id)
        # By accessing to the revision_author we can confirm that the
        # revision author has in fact been retrieved already.
        revision_author = revision.revision_author
        self.assertTrue(revision_author is not None)

    def testManyBranches(self):
        """Assert multiple branch revisions are returned correctly."""
        revisions = list(
            self.revision_set.getTipRevisionsForBranches(
                self.branches))
        self._breakTransaction()
        self.assertEqual(5, len(revisions))
        for revision in revisions:
            # By accessing to the revision_author we can confirm that the
            # revision author has in fact been retrieved already.
            revision_author = revision.revision_author
            self.assertTrue(revision_author is not None)

    def test_timestampToDatetime_with_negative_fractional(self):
        # timestampToDatetime should convert a negative, fractional timestamp
        # into a valid, sane datetime object.
        revision_set = removeSecurityProxy(getUtility(IRevisionSet))
        UTC = pytz.timezone('UTC')
        timestamp = -0.5
        date = revision_set._timestampToDatetime(timestamp)
        self.assertEqual(
            date, datetime.datetime(1969, 12, 31, 23, 59, 59, 500000, UTC))

    def test_timestampToDatetime(self):
        # timestampTODatetime should convert a regular timestamp into a valid,
        # sane datetime object.
        revision_set = removeSecurityProxy(getUtility(IRevisionSet))
        UTC = pytz.timezone('UTC')
        timestamp = time.time()
        date = datetime.datetime.fromtimestamp(timestamp, tz=UTC)
        self.assertEqual(date, revision_set._timestampToDatetime(timestamp))


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
