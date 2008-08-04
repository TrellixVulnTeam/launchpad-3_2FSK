#!/usr/bin/python2.4
# Copyright (c) 2005-2006 Canonical Ltd.
# Author: Gustavo Niemeyer <gustavo@niemeyer.net>
#         David Allouche <david@allouche.net>
# pylint: disable-msg=W0141

import datetime
import email
import os
import random
import time
import unittest

from bzrlib.revision import NULL_REVISION
from bzrlib.uncommit import uncommit
from bzrlib.tests import TestCaseWithTransport
from bzrlib.transport import register_transport, unregister_transport
import pytz
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.database import (
    BranchRevision, Revision, RevisionAuthor, RevisionParent)
from canonical.launchpad.mail import stub
from canonical.launchpad.interfaces import (
    BranchFormat, BranchSubscriptionDiffSize,
    BranchSubscriptionNotificationLevel, CodeReviewNotificationLevel,
    ControlFormat, IBranchSet, IPersonSet, IRevisionSet, RepositoryFormat)
from canonical.launchpad.testing import LaunchpadObjectFactory
from canonical.codehosting.scanner.bzrsync import (
    BzrSync, RevisionModifiedError, get_diff, get_revision_message)
from canonical.codehosting.bzrutils import ensure_base
from canonical.testing import LaunchpadZopelessLayer


class FakeRevision:
    """Fake Bazaar `Revision` object used in tests."""

    def __init__(self, revision_id, parent_ids, committer, message, timestamp,
                 timezone, properties):
        self.revision_id = revision_id
        self.parent_ids = parent_ids
        self.committer = committer
        self.message = message
        self.timestamp = timestamp
        self.timezone = timezone
        self.properties = properties

    def get_apparent_author(self):
        return self.committer


class BzrSyncTestCase(TestCaseWithTransport):
    """Common base for BzrSync test cases."""

    layer = LaunchpadZopelessLayer

    AUTHOR = "Revision Author <author@example.com>"
    LOG = "Log message"

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        # The lp-mirrored transport is set up by the branch_scanner module.
        # Here we set up a fake so that we can test without worrying about
        # authservers and the like.
        self._url_prefix = 'lp-mirrored:///'
        register_transport(self._url_prefix, self._fakeTransportFactory)
        self.factory = LaunchpadObjectFactory()
        self.makeFixtures()
        self.lp_db_user = config.launchpad.dbuser
        self.switchDbUser(config.branchscanner.dbuser)
        self._setUpAuthor()

    def _fakeTransportFactory(self, url):
        self.assertTrue(url.startswith(self._url_prefix))
        return self.get_transport(url[len(self._url_prefix):])

    def switchDbUser(self, user):
        """We need to reset the config warehouse root after a switch."""
        LaunchpadZopelessLayer.switchDbUser(user)
        self.txn = LaunchpadZopelessLayer.txn

    def tearDown(self):
        unregister_transport('lp-mirrored:///', self._fakeTransportFactory)
        TestCaseWithTransport.tearDown(self)

    def makeFixtures(self):
        """Makes test fixtures before we switch to the scanner db user."""
        self.db_branch = self.makeDatabaseBranch()
        self.bzr_tree = self.makeBzrBranchAndTree(self.db_branch)
        self.bzr_branch = self.bzr_tree.branch

    def syncBazaarBranchToDatabase(self, bzr_branch, db_branch):
        """Sync `bzr_branch` into the database as `db_branch`."""
        syncer = self.makeBzrSync(db_branch)
        syncer.syncBranchAndClose(bzr_branch)

    def makeBzrBranchAndTree(self, db_branch, format=None):
        """Make a Bazaar branch at the warehouse location of `db_branch`."""
        ensure_base(self.get_transport(db_branch.unique_name))
        return self.make_branch_and_tree(db_branch.unique_name, format=format)

    def makeDatabaseBranch(self):
        """Make an arbitrary branch in the database."""
        LaunchpadZopelessLayer.txn.begin()
        new_branch = self.factory.makeBranch()
        # Unsubscribe the implicit owner subscription.
        new_branch.unsubscribe(new_branch.owner)
        LaunchpadZopelessLayer.txn.commit()
        return new_branch

    def _setUpAuthor(self):
        self.db_author = RevisionAuthor.selectOneBy(name=self.AUTHOR)
        if not self.db_author:
            self.txn.begin()
            self.db_author = RevisionAuthor(name=self.AUTHOR)
            self.txn.commit()

    def getCounts(self):
        """Return the number of rows in core revision-related tables.

        :return: (num_revisions, num_branch_revisions, num_revision_parents,
            num_revision_authors)
        """
        return (Revision.select().count(),
                BranchRevision.select().count(),
                RevisionParent.select().count(),
                RevisionAuthor.select().count())

    def assertCounts(self, counts, new_revisions=0, new_numbers=0,
                     new_parents=0, new_authors=0):
        (old_revision_count,
         old_revisionnumber_count,
         old_revisionparent_count,
         old_revisionauthor_count) = counts
        (new_revision_count,
         new_revisionnumber_count,
         new_revisionparent_count,
         new_revisionauthor_count) = self.getCounts()
        self.assertEqual(
            new_revisions,
            new_revision_count - old_revision_count,
            "Wrong number of new database Revisions.")
        self.assertEqual(
            new_numbers,
            new_revisionnumber_count - old_revisionnumber_count,
            "Wrong number of new BranchRevisions.")
        self.assertEqual(
            new_parents,
            new_revisionparent_count - old_revisionparent_count,
            "Wrong number of new RevisionParents.")
        self.assertEqual(
            new_authors,
            new_revisionauthor_count - old_revisionauthor_count,
            "Wrong number of new RevisionAuthors.")

    def makeBzrSync(self, db_branch):
        """Create a BzrSync instance for the test branch.

        This method allow subclasses to instrument the BzrSync instance used
        in syncBranch.
        """
        return BzrSync(self.txn, db_branch)

    def syncAndCount(self, db_branch=None, new_revisions=0, new_numbers=0,
                     new_parents=0, new_authors=0):
        """Run BzrSync and assert the number of rows added to each table."""
        if db_branch is None:
            db_branch = self.db_branch
        counts = self.getCounts()
        self.makeBzrSync(db_branch).syncBranchAndClose()
        self.assertCounts(
            counts, new_revisions=new_revisions, new_numbers=new_numbers,
            new_parents=new_parents, new_authors=new_authors)

    def commitRevision(self, message=None, committer=None,
                       extra_parents=None, rev_id=None,
                       timestamp=None, timezone=None, revprops=None):
        if message is None:
            message = self.LOG
        if committer is None:
            committer = self.AUTHOR
        if extra_parents is not None:
            self.bzr_tree.add_pending_merge(*extra_parents)
        self.bzr_tree.commit(
            message, committer=committer, rev_id=rev_id,
            timestamp=timestamp, timezone=timezone, allow_pointless=True,
            revprops=revprops)

    def uncommitRevision(self):
        branch = self.bzr_tree.branch
        uncommit(branch, tree=self.bzr_tree)

    def makeBranchWithMerge(self, base_rev_id, trunk_rev_id, branch_rev_id,
                            merge_rev_id):
        """Make a branch that has had another branch merged into it.

        Creates two Bazaar branches and two database branches associated with
        them. The first branch has three commits: the base revision, the
        'trunk' revision and the 'merged' revision.

        The second branch is branched from the base revision, has the 'branch'
        revision committed to it and is then merged into the first branch.

        Or, in other words::

               merge
                 |  \
                 |   \
                 |    \
               trunk   branch
                 |    /
                 |   /
                 |  /
                base

        :param base_rev_id: The revision ID of the initial commit.
        :param trunk_rev_id: The revision ID of the mainline commit.
        :param branch_rev_id: The revision ID of the revision committed to
            the branch that is merged into the mainline.
        :param merge_rev_id: The revision ID of the revision that merges the
            branch into the mainline branch.
        :return: (db_trunk, trunk_tree), (db_branch, branch_tree).
        """

        self.switchDbUser(self.lp_db_user)

        # Make the base revision.
        db_branch = self.makeDatabaseBranch()
        trunk_tree = self.makeBzrBranchAndTree(db_branch)
        trunk_tree.commit(u'base revision', rev_id=base_rev_id)

        # Branch from the base revision.
        new_db_branch = self.makeDatabaseBranch()
        branch_tree = self.makeBzrBranchAndTree(new_db_branch)
        branch_tree.pull(trunk_tree.branch)

        # Commit to both branches.
        trunk_tree.commit(u'trunk revision', rev_id=trunk_rev_id)
        branch_tree.commit(u'branch revision', rev_id=branch_rev_id)

        # Merge branch into trunk.
        trunk_tree.merge_from_branch(branch_tree.branch)
        trunk_tree.commit(u'merge revision', rev_id=merge_rev_id)

        LaunchpadZopelessLayer.txn.commit()
        self.switchDbUser(config.branchscanner.dbuser)

        return (db_branch, trunk_tree), (new_db_branch, branch_tree)

    def getBranchRevisions(self, db_branch):
        """Get a set summarizing the BranchRevision rows in the database.

        :return: A set of tuples (sequence, revision-id) for all the
            BranchRevisions rows belonging to self.db_branch.
        """
        return set(
            (branch_revision.sequence, branch_revision.revision.revision_id)
            for branch_revision
            in BranchRevision.selectBy(branch=db_branch))

    def writeToFile(self, filename="file", contents=None):
        """Set the contents of the specified file.

        This also adds the file to the bzr working tree if
        it isn't already there.
        """
        file = open(os.path.join(self.bzr_tree.basedir, filename), "w")
        if contents is None:
            file.write(str(time.time()+random.random()))
        else:
            file.write(contents)
        file.close()
        self.bzr_tree.lock_write()
        try:
            inventory = self.bzr_tree.read_working_inventory()
            if not inventory.has_filename(filename):
                self.bzr_tree.add(filename)
        finally:
            self.bzr_tree.unlock()


class TestBzrSync(BzrSyncTestCase):

    def isMainline(self, db_branch, revision_id):
        """Is `revision_id` in the mainline history of `db_branch`?"""
        for branch_revision in db_branch.revision_history:
            if branch_revision.revision.revision_id == revision_id:
                return True
        return False

    def assertInMainline(self, revision_id, db_branch):
        """Assert that `revision_id` is in the mainline of `db_branch`."""
        self.failUnless(
            self.isMainline(db_branch, revision_id),
            "%r not in mainline of %r" % (revision_id, db_branch))

    def assertNotInMainline(self, revision_id, db_branch):
        """Assert that `revision_id` is not in the mainline of `db_branch`."""
        self.failIf(
            self.isMainline(db_branch, revision_id),
            "%r in mainline of %r" % (revision_id, db_branch))

    def test_empty_branch(self):
        # Importing an empty branch does nothing.
        self.syncAndCount()
        self.assertEqual(self.db_branch.revision_count, 0)

    def test_import_revision(self):
        # Importing a revision in history adds one revision and number.
        self.commitRevision()
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.assertEqual(self.db_branch.revision_count, 1)

    def test_import_uncommit(self):
        # Second import honours uncommit.
        self.commitRevision()
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.uncommitRevision()
        self.syncAndCount(new_numbers=-1)
        self.assertEqual(self.db_branch.revision_count, 0)

    def test_import_recommit(self):
        # Second import honours uncommit followed by commit.
        # When scanning the uncommit and new commit
        # there should be an email generated saying that
        # 1 (in this case) revision has been removed,
        # and another email with the diff and log message.
        self.commitRevision('first')
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.assertEqual(self.db_branch.revision_count, 1)
        self.uncommitRevision()
        self.commitRevision('second')
        self.syncAndCount(new_revisions=1)
        self.assertEqual(self.db_branch.revision_count, 1)
        [revno] = self.db_branch.revision_history
        self.assertEqual(revno.revision.log_body, 'second')

    def test_import_revision_with_url(self):
        # Importing a revision passing the url parameter works.
        self.commitRevision()
        counts = self.getCounts()
        bzrsync = BzrSync(self.txn, self.db_branch)
        bzrsync.syncBranchAndClose()
        self.assertCounts(counts, new_revisions=1, new_numbers=1)

    def test_new_author(self):
        # Importing a different committer adds it as an author.
        author = "Another Author <another@example.com>"
        self.commitRevision(committer=author)
        self.syncAndCount(new_revisions=1, new_numbers=1, new_authors=1)
        db_author = RevisionAuthor.selectOneBy(name=author)
        self.assertTrue(db_author)
        self.assertEquals(db_author.name, author)

    def test_new_parent(self):
        # Importing two revisions should import a new parent.
        self.commitRevision()
        self.commitRevision()
        self.syncAndCount(new_revisions=2, new_numbers=2, new_parents=1)

    def test_sync_updates_branch(self):
        # test that the last scanned revision ID is recorded
        self.syncAndCount()
        self.assertEquals(NULL_REVISION, self.db_branch.last_scanned_id)
        last_modified = self.db_branch.date_last_modified
        last_scanned = self.db_branch.last_scanned
        self.commitRevision()
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.assertEquals(self.bzr_branch.last_revision(),
                          self.db_branch.last_scanned_id)
        self.assertTrue(self.db_branch.last_scanned > last_scanned,
                        "last_scanned was not updated")
        self.assertTrue(self.db_branch.date_last_modified > last_modified,
                        "date_last_modifed was not updated")

    def test_timestamp_parsing(self):
        # Test that the timezone selected does not affect the
        # timestamp recorded in the database.
        self.commitRevision(rev_id='rev-1',
                            timestamp=1000000000.0, timezone=0)
        self.commitRevision(rev_id='rev-2',
                            timestamp=1000000000.0, timezone=28800)
        self.syncAndCount(new_revisions=2, new_numbers=2, new_parents=1)
        rev_1 = Revision.selectOneBy(revision_id='rev-1')
        rev_2 = Revision.selectOneBy(revision_id='rev-2')
        UTC = pytz.timezone('UTC')
        dt = datetime.datetime.fromtimestamp(1000000000.0, UTC)
        self.assertEqual(rev_1.revision_date, dt)
        self.assertEqual(rev_2.revision_date, dt)

    def test_get_revisions_empty(self):
        # An empty branch should have no revisions.
        bzrsync = self.makeBzrSync(self.db_branch)
        bzr_ancestry, bzr_history = (
            bzrsync.retrieveBranchDetails(self.bzr_branch))
        self.assertEqual(
            [], list(bzrsync.getRevisions(bzr_history, bzr_ancestry)))

    def test_get_revisions_linear(self):
        # If the branch has a linear ancestry, getRevisions() should yield
        # each revision along with a sequence number, starting at 1.
        self.commitRevision(rev_id='rev-1')
        bzrsync = self.makeBzrSync(self.db_branch)
        bzr_ancestry, bzr_history = (
            bzrsync.retrieveBranchDetails(self.bzr_branch))
        self.assertEqual(
            [('rev-1', 1)], 
            list(bzrsync.getRevisions(bzr_history, bzr_ancestry)))

    def test_get_revisions_branched(self):
        # Confirm that these revisions are generated by getRevisions with None
        # as the sequence 'number'.
        (db_branch, bzr_tree), ignored = self.makeBranchWithMerge(
            'base', 'trunk', 'branch', 'merge')
        bzrsync = self.makeBzrSync(db_branch)
        bzr_ancestry, bzr_history = (
            bzrsync.retrieveBranchDetails(bzr_tree.branch))
        expected = set(
            [('base', 1), ('trunk', 2), ('merge', 3), ('branch', None)])
        self.assertEqual(
            expected, set(bzrsync.getRevisions(bzr_history, bzr_ancestry)))

    def test_sync_with_merged_branches(self):
        # Confirm that when we syncHistory, all of the revisions are included
        # correctly in the BranchRevision table.
        (db_branch, branch_tree), ignored = self.makeBranchWithMerge(
            'r1', 'r2', 'r1.1.1', 'r3')
        self.makeBzrSync(db_branch).syncBranchAndClose()
        expected = set(
            [(1, 'r1'), (2, 'r2'), (3, 'r3'), (None, 'r1.1.1')])
        self.assertEqual(self.getBranchRevisions(db_branch), expected)

    def test_sync_merged_to_merging(self):
        # A revision's sequence in the BranchRevision table will change from
        # not NULL to NULL if that revision changes from mainline to not
        # mainline when synced.

        (db_trunk, trunk_tree), (db_branch, branch_tree) = (
            self.makeBranchWithMerge('base', 'trunk', 'branch', 'merge'))

        self.syncBazaarBranchToDatabase(trunk_tree.branch, db_branch)
        self.assertInMainline('trunk', db_branch)

        self.syncBazaarBranchToDatabase(branch_tree.branch, db_branch)
        self.assertNotInMainline('trunk', db_branch)
        self.assertInMainline('branch', db_branch)

    def test_sync_merging_to_merged(self):
        # When replacing a branch by one of the branches it merged, the
        # database must be updated appropriately.
        (db_trunk, trunk_tree), (db_branch, branch_tree) = (
            self.makeBranchWithMerge('base', 'trunk', 'branch', 'merge'))
        # First, sync with the merging branch.
        self.syncBazaarBranchToDatabase(trunk_tree.branch, db_trunk)
        # Then sync with the merged branch.
        self.syncBazaarBranchToDatabase(branch_tree.branch, db_trunk)
        expected = set([(1, 'base'), (2, 'branch')])
        self.assertEqual(self.getBranchRevisions(db_trunk), expected)

    def test_retrieveBranchDetails(self):
        # retrieveBranchDetails should set last_revision, bzr_ancestry and
        # bzr_history on the BzrSync instance to match the information in the
        # Bazaar branch.
        (db_trunk, trunk_tree), ignored = self.makeBranchWithMerge(
            'base', 'trunk', 'branch', 'merge')
        bzrsync = self.makeBzrSync(db_trunk)
        bzr_ancestry, bzr_history = (
            bzrsync.retrieveBranchDetails(trunk_tree.branch))
        expected_ancestry = set(['base', 'trunk', 'branch', 'merge'])
        self.assertEqual(expected_ancestry, bzr_ancestry)
        self.assertEqual(['base', 'trunk', 'merge'], bzr_history)

    def test_retrieveDatabaseAncestry(self):
        # retrieveDatabaseAncestry should set db_ancestry and db_history to
        # Launchpad's current understanding of the branch state.
        # db_branch_revision_map should map Bazaar revision_ids to
        # BranchRevision.ids.

        # Use the sampledata for this test, so we do not have to rely on
        # BzrSync to fill the database. That would cause a circular
        # dependency, as the test setup would depend on
        # retrieveDatabaseAncestry.
        branch = getUtility(IBranchSet).getByUniqueName(
            '~name12/+junk/junk.contrib')
        sampledata = list(
            BranchRevision.selectBy(branch=branch).orderBy('sequence'))
        expected_ancestry = set(branch_revision.revision.revision_id
            for branch_revision in sampledata)
        expected_history = [branch_revision.revision.revision_id
            for branch_revision in sampledata
            if branch_revision.sequence is not None]
        expected_mapping = dict(
            (branch_revision.revision.revision_id, branch_revision.id)
            for branch_revision in sampledata)

        self.makeBzrBranchAndTree(branch)

        bzrsync = self.makeBzrSync(branch)
        db_ancestry, db_history, db_branch_revision_map = (
            bzrsync.retrieveDatabaseAncestry())
        self.assertEqual(expected_ancestry, set(db_ancestry))
        self.assertEqual(expected_history, list(db_history))
        self.assertEqual(expected_mapping, db_branch_revision_map)


class TestBzrSyncOneRevision(BzrSyncTestCase):
    """Tests for `BzrSync.syncOneRevision`."""

    def setUp(self):
        BzrSyncTestCase.setUp(self)
        self.bzrsync = self.makeBzrSync(self.db_branch)

    def test_timestampToDatetime_with_negative_fractional(self):
        # timestampToDatetime should convert a negative, fractional timestamp
        # into a valid, sane datetime object.
        UTC = pytz.timezone('UTC')
        timestamp = -0.5
        date = self.bzrsync._timestampToDatetime(timestamp)
        self.assertEqual(
            date, datetime.datetime(1969, 12, 31, 23, 59, 59, 500000, UTC))

    def test_timestampToDatetime(self):
        # timestampTODatetime should convert a regular timestamp into a valid,
        # sane datetime object.
        UTC = pytz.timezone('UTC')
        timestamp = time.time()
        date = datetime.datetime.fromtimestamp(timestamp, tz=UTC)
        self.assertEqual(date, self.bzrsync._timestampToDatetime(timestamp))

    def test_ancient_revision(self):
        # Test that we can sync revisions with negative, fractional
        # timestamps.

        # Make a negative, fractional timestamp and equivalent datetime
        UTC = pytz.timezone('UTC')
        old_timestamp = -0.5
        old_date = datetime.datetime(1969, 12, 31, 23, 59, 59, 500000, UTC)

        # Fake revision with negative timestamp.
        fake_rev = FakeRevision(
            revision_id='rev42', parent_ids=['rev1', 'rev2'],
            committer=self.AUTHOR, message=self.LOG, timestamp=old_timestamp,
            timezone=0, properties={})

        # Sync the revision.  The second parameter is a dict of revision ids
        # to revnos, and will error if the revision id is not in the dict.
        self.bzrsync.syncOneRevision(fake_rev, {'rev42': None})

        # Find the revision we just synced and check that it has the correct
        # date.
        revision = getUtility(IRevisionSet).getByRevisionId(
            fake_rev.revision_id)
        self.assertEqual(old_date, revision.revision_date)


class TestBzrSyncModified(BzrSyncTestCase):
    """Tests for BzrSync.syncOneRevision when the revision has been modified.
    """

    def setUp(self):
        BzrSyncTestCase.setUp(self)
        self.bzrsync = self.makeBzrSync(self.db_branch)

    def test_revision_modified(self):
        # test that modifications to the list of parents get caught.

        # Synchronise the fake revision:
        counts = self.getCounts()
        fake_revision = FakeRevision(
            revision_id='rev42', parent_ids=['rev1', 'rev2'],
            committer=self.AUTHOR, message=self.LOG, timestamp=1000000000.0,
            timezone=0, properties={})
        fake_revision_dict = {'rev42': None}
        self.bzrsync.syncOneRevision(fake_revision, fake_revision_dict)
        self.assertCounts(
            counts, new_revisions=1, new_numbers=0,
            new_parents=2, new_authors=0)

        # Verify that synchronising the revision twice passes and does
        # not create a second revision object:
        counts = self.getCounts()
        self.bzrsync.syncOneRevision(fake_revision, fake_revision_dict)
        self.assertCounts(
            counts, new_revisions=0, new_numbers=0,
            new_parents=0, new_authors=0)

        # Verify that adding a parent gets caught:
        fake_revision.parent_ids.append('rev3')
        self.assertRaises(
            RevisionModifiedError,
            self.bzrsync.syncOneRevision,
            fake_revision,
            fake_revision_dict)

        # Verify that removing a parent gets caught:
        fake_revision.parent_ids = ['rev1']
        self.assertRaises(
            RevisionModifiedError,
            self.bzrsync.syncOneRevision,
            fake_revision,
            fake_revision_dict)

        # Verify that reordering the parents gets caught:
        fake_revision.parent_ids = ['rev2', 'rev1']
        self.assertRaises(
            RevisionModifiedError,
            self.bzrsync.syncOneRevision,
            fake_revision,
            fake_revision_dict)


class TestBzrSyncEmail(BzrSyncTestCase):
    """Tests BzrSync support for generating branch email notifications."""

    def setUp(self):
        BzrSyncTestCase.setUp(self)
        stub.test_emails = []

    def makeDatabaseBranch(self):
        branch = BzrSyncTestCase.makeDatabaseBranch(self)
        LaunchpadZopelessLayer.txn.begin()
        test_user = getUtility(IPersonSet).getByEmail('test@canonical.com')
        branch.subscribe(
            test_user,
            BranchSubscriptionNotificationLevel.FULL,
            BranchSubscriptionDiffSize.FIVEKLINES,
            CodeReviewNotificationLevel.NOEMAIL)
        LaunchpadZopelessLayer.txn.commit()
        return branch

    def assertTextIn(self, expected, text):
        """Assert that expected is in text.

        Report expected and text in case of failure.
        """
        self.failUnless(expected in text, '%r not in %r' % (expected, text))

    def test_empty_branch(self):
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(len(stub.test_emails), 1)
        [initial_email] = stub.test_emails
        expected = 'First scan of the branch detected 0 revisions'
        email_body = email.message_from_string(initial_email[2]).get_payload()
        self.assertTextIn(expected, email_body)

    def test_import_revision(self):
        self.commitRevision()
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(len(stub.test_emails), 1)
        [initial_email] = stub.test_emails
        expected = ('First scan of the branch detected 1 revision'
                    ' in the revision history of the=\n branch.')
        email_body = email.message_from_string(initial_email[2]).get_payload()
        self.assertTextIn(expected, email_body)

    def test_import_uncommit(self):
        self.commitRevision()
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        stub.test_emails = []
        self.uncommitRevision()
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(len(stub.test_emails), 1)
        [uncommit_email] = stub.test_emails
        expected = '1 revision was removed from the branch.'
        email_body = email.message_from_string(
            uncommit_email[2]).get_payload()
        self.assertTextIn(expected, email_body)

    def test_import_recommit(self):
        # When scanning the uncommit and new commit
        # there should be an email generated saying that
        # 1 (in this case) revision has been removed,
        # and another email with the diff and log message.
        self.commitRevision('first')
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        stub.test_emails = []
        self.uncommitRevision()
        self.writeToFile(filename="hello.txt",
                         contents="Hello World\n")
        self.commitRevision('second')
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(len(stub.test_emails), 2)
        [uncommit_email, recommit_email] = stub.test_emails
        uncommit_email_body = uncommit_email[2]
        expected = '1 revision was removed from the branch.'
        self.assertTextIn(expected, uncommit_email_body)
        subject = (
            'Subject: [Branch %s] Test branch' % self.db_branch.unique_name)
        self.assertTextIn(expected, uncommit_email_body)
        recommit_email_body = recommit_email[2]
        body_bits = [
            'Subject: [Branch %s] Rev 1: second'
            % self.db_branch.unique_name,
            'revno: 1',
            'committer: Revision Author <author@example.com>',
            'branch nick: %s'  % self.bzr_branch.nick,
            'message:\n  second',
            'added:\n  hello.txt',
            "=3D=3D=3D added file 'hello.txt'",
            ]
        for bit in body_bits:
            self.assertTextIn(bit, recommit_email_body)

    def test_email_format(self):
        first_revision = 'rev-1'
        self.writeToFile(filename="hello.txt",
                         contents="Hello World\n")
        self.commitRevision(rev_id=first_revision,
                            message="Log message",
                            committer="Joe Bloggs <joe@example.com>",
                            timestamp=1000000000.0,
                            timezone=0)
        self.writeToFile(filename="hello.txt",
                         contents="Hello World\n\nFoo Bar\n")
        second_revision = 'rev-2'
        self.commitRevision(rev_id=second_revision,
                            message="Extended contents",
                            committer="Joe Bloggs <joe@example.com>",
                            timestamp=1000100000.0,
                            timezone=0)
        sync = self.makeBzrSync(self.db_branch)

        revision = self.bzr_branch.repository.get_revision(first_revision)
        diff = get_diff(self.bzr_branch, revision)
        expected = (
            "=== added file 'hello.txt'" '\n'
            "--- a/hello.txt" '\t' "1970-01-01 00:00:00 +0000" '\n'
            "+++ b/hello.txt" '\t' "2001-09-09 01:46:40 +0000" '\n'
            "@@ -0,0 +1,1 @@" '\n'
            "+Hello World" '\n'
            '\n')
        self.assertEqualDiff(diff, expected)
        expected = (
            u"-"*60 + '\n'
            "revno: 1" '\n'
            "committer: Joe Bloggs <joe@example.com>" '\n'
            "branch nick: %s" '\n'
            "timestamp: Sun 2001-09-09 01:46:40 +0000" '\n'
            "message:" '\n'
            "  Log message" '\n'
            "added:" '\n'
            "  hello.txt" '\n' % self.bzr_branch.nick)
        self.assertEqualDiff(
            get_revision_message(self.bzr_branch, revision), expected)

        expected_diff = (
            "=== modified file 'hello.txt'" '\n'
            "--- a/hello.txt" '\t' "2001-09-09 01:46:40 +0000" '\n'
            "+++ b/hello.txt" '\t' "2001-09-10 05:33:20 +0000" '\n'
            "@@ -1,1 +1,3 @@" '\n'
            " Hello World" '\n'
            "+" '\n'
            "+Foo Bar" '\n'
            '\n')
        expected_message = (
            u"-"*60 + '\n'
            "revno: 2" '\n'
            "committer: Joe Bloggs <joe@example.com>" '\n'
            "branch nick: %s" '\n'
            "timestamp: Mon 2001-09-10 05:33:20 +0000" '\n'
            "message:" '\n'
            "  Extended contents" '\n'
            "modified:" '\n'
            "  hello.txt" '\n' % self.bzr_branch.nick)
        revision = self.bzr_branch.repository.get_revision(second_revision)
        self.bzr_branch.lock_read()
        diff = get_diff(self.bzr_branch, revision)
        self.bzr_branch.unlock()
        self.assertEqualDiff(diff, expected_diff)
        message = get_revision_message(self.bzr_branch, revision)
        self.assertEqualDiff(message, expected_message)

    def test_message_encoding(self):
        """Test handling of non-ASCII commit messages."""
        rev_id = 'rev-1'
        self.commitRevision(
            rev_id=rev_id, message = u"Non ASCII: \xe9",
            committer=u"Non ASCII: \xed",
            timestamp=1000000000.0, timezone=0)
        sync = self.makeBzrSync(self.db_branch)
        revision = self.bzr_branch.repository.get_revision(rev_id)
        message = get_revision_message(self.bzr_branch, revision)
        # The revision message must be a unicode object.
        expected = (
            u'-' * 60 + '\n'
            u"revno: 1" '\n'
            u"committer: Non ASCII: \xed" '\n'
            u"branch nick: %s" '\n'
            u"timestamp: Sun 2001-09-09 01:46:40 +0000" '\n'
            u"message:" '\n'
            u"  Non ASCII: \xe9" '\n' % self.bzr_branch.nick)
        self.assertEqualDiff(message, expected)

    def test_diff_encoding(self):
        """Test handling of diff of files which are not utf-8."""
        # Since bzr does not know the encoding used for file contents, which
        # may even be no encoding at all (different part of the file using
        # different encodings), it generates diffs using utf-8 for file names
        # and raw 8 bit text for file contents.
        rev_id = 'rev-1'
        # Adding a file whose content is a mixture of latin-1 and utf-8. It
        # would be nice to use a non-ASCII file name, but getting it into the
        # branch through the filesystem would make the test dependent on the
        # value of sys.getfilesystemencoding().
        self.writeToFile(filename='un elephant',
                         contents='\xc7a trompe \xc3\xa9norm\xc3\xa9ment.\n')
        # XXX DavidAllouche 2007-04-26:
        # The binary file is not really needed here, but it triggers a
        # crasher bug with bzr-0.15 and earlier.
        self.writeToFile(filename='binary', contents=chr(0))
        self.commitRevision(rev_id=rev_id, timestamp=1000000000.0, timezone=0)
        sync = self.makeBzrSync(self.db_branch)
        revision = self.bzr_branch.repository.get_revision(rev_id)
        diff = get_diff(self.bzr_branch, revision)
        # The diff must be a unicode object, characters that could not be
        # decoded as utf-8 replaced by the unicode substitution character.
        expected = (
            u"=== added file 'binary'" '\n'
            u"Binary files a/binary\t1970-01-01 00:00:00 +0000"
            u" and b/binary\t2001-09-09 01:46:40 +0000 differ" '\n'
            u"=== added file 'un elephant'" '\n'
            u"--- a/un elephant\t1970-01-01 00:00:00 +0000" '\n'
            u"+++ b/un elephant\t2001-09-09 01:46:40 +0000" '\n'
            u"@@ -0,0 +1,1 @@" '\n'
            # \ufffd is the substitution character.
            u"+\ufffd trompe \xe9norm\xe9ment." '\n' '\n')
        self.assertEqualDiff(diff, expected)


class TestBzrSyncNoEmail(BzrSyncTestCase):
    """Tests BzrSync support for not generating branch email notifications
    when no one is interested.
    """

    def setUp(self):
        BzrSyncTestCase.setUp(self)
        stub.test_emails = []

    def assertNoPendingEmails(self, bzrsync):
        self.assertEqual(
            len(bzrsync._branch_mailer.pending_emails), 0,
            "There should be no pending emails.")

    def test_no_subscribers(self):
        self.assertEqual(self.db_branch.subscribers.count(), 0,
                         "There should be no subscribers to the branch.")

    def test_empty_branch(self):
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        self.assertNoPendingEmails(bzrsync)

    def test_import_revision(self):
        self.commitRevision()
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        self.assertNoPendingEmails(bzrsync)

    def test_import_uncommit(self):
        self.commitRevision()
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        stub.test_emails = []
        self.uncommitRevision()
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        self.assertNoPendingEmails(bzrsync)

    def test_import_recommit(self):
        # No emails should have been generated.
        self.commitRevision('first')
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        stub.test_emails = []
        self.uncommitRevision()
        self.writeToFile(filename="hello.txt",
                         contents="Hello World\n")
        self.commitRevision('second')
        bzrsync = self.makeBzrSync(self.db_branch)
        bzrsync.syncBranchAndClose()
        self.assertNoPendingEmails(bzrsync)


class TestRevisionProperty(BzrSyncTestCase):
    """Tests for storting revision properties."""

    def test_revision_properties(self):
        # Revisions with properties should have records stored in the
        # RevisionProperty table, accessible through Revision.getProperties().
        properties = {'name': 'value'}
        self.commitRevision(rev_id='rev1', revprops=properties)
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        # Check that properties were saved to the revision.
        bzr_revision = self.bzr_branch.repository.get_revision('rev1')
        self.assertEquals(properties, bzr_revision.properties)
        # Check that properties are stored in the database.
        db_revision = getUtility(IRevisionSet).getByRevisionId('rev1')
        self.assertEquals(properties, db_revision.getProperties())


class TestScanFormatPack(BzrSyncTestCase):
    """Test scanning of pack-format repositories."""

    def testRecognizePack(self):
        """Ensure scanner records correct formats for pack branches."""
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(self.db_branch.branch_format,
                         BranchFormat.BZR_BRANCH_6)
        self.assertEqual(self.db_branch.repository_format,
                         RepositoryFormat.BZR_KNITPACK_1)
        self.assertEqual(self.db_branch.control_format,
                         ControlFormat.BZR_METADIR_1)


class TestScanFormatKnit(BzrSyncTestCase):
    """Test scanning of knit-format repositories."""

    def makeBzrBranchAndTree(self, db_branch):
        return BzrSyncTestCase.makeBzrBranchAndTree(self, db_branch, 'knit')

    def testRecognizeKnit(self):
        """Ensure scanner records correct formats for knit branches."""
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(self.db_branch.branch_format,
                         BranchFormat.BZR_BRANCH_5)


class TestScanFormatWeave(BzrSyncTestCase):
    """Test scanning of weave-format branches.

    Weave is an "all-in-one" format, where branch, repo and tree formats are
    implied by the control directory format."""

    def makeBzrBranchAndTree(self, db_branch):
        return BzrSyncTestCase.makeBzrBranchAndTree(self, db_branch, 'weave')

    def testRecognizeWeave(self):
        """Ensure scanner records correct weave formats."""
        self.makeBzrSync(self.db_branch).syncBranchAndClose()
        self.assertEqual(self.db_branch.branch_format,
                         BranchFormat.BZR_BRANCH_4)
        self.assertEqual(self.db_branch.repository_format,
                         RepositoryFormat.BZR_REPOSITORY_6)
        self.assertEqual(self.db_branch.control_format,
                         ControlFormat.BZR_DIR_6)


class TestScanUnrecognizedFormat(BzrSyncTestCase):
    """Test scanning unrecognized formats"""

    def testUnrecognize(self):
        """Scanner should record UNRECOGNIZED for all format values."""
        class MockFormat:
            def get_format_string(self):
                return 'Unrecognizable'

        class MockWithFormat:
            def __init__(self):
                self._format = MockFormat()

        class MockBranch(MockWithFormat):
            bzrdir = MockWithFormat()
            repository = MockWithFormat()

        branch = MockBranch()
        self.makeBzrSync(self.db_branch).setFormats(branch)
        self.assertEqual(self.db_branch.branch_format,
                         BranchFormat.UNRECOGNIZED)
        self.assertEqual(self.db_branch.repository_format,
                         RepositoryFormat.UNRECOGNIZED)
        self.assertEqual(self.db_branch.control_format,
                         ControlFormat.UNRECOGNIZED)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
