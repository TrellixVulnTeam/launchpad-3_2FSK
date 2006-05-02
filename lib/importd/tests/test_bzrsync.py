#!/usr/bin/env python
# Copyright (c) 2005 Canonical Ltd.
# Author: Gustavo Niemeyer <gustavo@niemeyer.net>
#         David Allouche <david@allouche.net>

import logging
import random
import time
import os
import unittest

from bzrlib.branch import Branch as BzrBranch
from bzrlib.uncommit import uncommit

import transaction
from canonical.launchpad.database import (
    Branch, Revision, RevisionNumber, RevisionParent, RevisionAuthor)

from importd.bzrsync import BzrSync, RevisionModifiedError
from importd.tests import TestUtil
from importd.tests.helpers import WebserverHelper, ZopelessUtilitiesHelper


class TestBzrSync(unittest.TestCase):

    AUTHOR = "Revision Author <author@example.com>"
    LOG = "Log message"

    def setUp(self):
        self.webserver_helper = WebserverHelper()
        self.webserver_helper.setUp()
        self.utilities_helper = ZopelessUtilitiesHelper()
        self.utilities_helper.setUp()
        self.setUpBzrBranch()
        self.setUpDBBranch()
        self.setUpAuthor()

    def tearDown(self):
        self.utilities_helper.tearDown()
        self.webserver_helper.tearDown()

    def path(self, name):
        return self.webserver_helper.path(name)

    def url(self, name):
        return self.webserver_helper.get_remote_url(name)

    def setUpBzrBranch(self):
        self.bzr_branch_relpath = "bzr_branch"
        self.bzr_branch_abspath = self.path(self.bzr_branch_relpath)
        self.bzr_branch_url = self.url(self.bzr_branch_relpath)
        os.mkdir(self.bzr_branch_abspath)
        self.bzr_branch = BzrBranch.initialize(self.bzr_branch_abspath)

    def setUpDBBranch(self):
        transaction.begin()
        randomownerid = 1
        self.db_branch = Branch(name="test",
                                url=self.bzr_branch_url,
                                home_page=None,
                                title="Test branch",
                                summary="Branch for testing",
                                product=None,
                                owner=randomownerid)
        transaction.commit()

    def setUpAuthor(self):
        self.db_author = RevisionAuthor.selectOneBy(name=self.AUTHOR)
        if not self.db_author:
            transaction.begin()
            self.db_author = RevisionAuthor(name=self.AUTHOR)
            transaction.commit()

    def getCounts(self):
        return (Revision.select().count(),
                RevisionNumber.select().count(),
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
        revision_pair = (old_revision_count+new_revisions,
                         new_revision_count)
        revisionnumber_pair = (old_revisionnumber_count+new_numbers,
                               new_revisionnumber_count)
        revisionparent_pair = (old_revisionparent_count+new_parents,
                               new_revisionparent_count)
        revisionauthor_pair = (old_revisionauthor_count+new_authors,
                               new_revisionauthor_count)
        self.assertEqual(revision_pair[0], revision_pair[1],
                         "Wrong Revision count (should be %d, not %d)"
                         % revision_pair)
        self.assertEqual(revisionnumber_pair[0], revisionnumber_pair[1],
                         "Wrong RevisionNumber count (should be %d, not %d)"
                         % revisionnumber_pair)
        self.assertEqual(revisionparent_pair[0], revisionparent_pair[1],
                         "Wrong RevisionParent count (should be %d, not %d)"
                         % revisionparent_pair)
        self.assertEqual(revisionauthor_pair[0], revisionauthor_pair[1],
                         "Wrong RevisionAuthor count (should be %d, not %d)"
                         % revisionauthor_pair)

    def syncAndCount(self, new_revisions=0, new_numbers=0,
                     new_parents=0, new_authors=0):
        counts = self.getCounts()
        BzrSync(transaction, self.db_branch.id).syncHistory()
        self.assertCounts(
            counts, new_revisions=new_revisions, new_numbers=new_numbers,
            new_parents=new_parents, new_authors=new_authors)

    def commitRevision(self, message=None, committer=None,
                       pending_merges=[]):
        file = open(os.path.join(self.bzr_branch_abspath, "file"), "w")
        file.write(str(time.time()+random.random()))
        file.close()
        working_tree = self.bzr_branch.bzrdir.open_workingtree()
        inventory = working_tree.read_working_inventory()
        if not inventory.has_filename("file"):
            working_tree.add("file")
        if message is None:
            message = self.LOG
        if committer is None:
            committer = self.AUTHOR
        working_tree.add_pending_merge(*pending_merges)
        working_tree.commit(message, committer=committer)

    def uncommitRevision(self):
        uncommit(self.bzr_branch)

    def test_empty_branch(self):
        # Importing an empty branch does nothing.
        self.syncAndCount()

    def test_import_revision(self):
        # Importing a revision in history adds one revision and number.
        self.commitRevision()
        self.syncAndCount(new_revisions=1, new_numbers=1)

    def test_import_uncommit(self):
        # Second import honours uncommit.
        self.commitRevision()
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.uncommitRevision()
        self.syncAndCount(new_numbers=-1)
        self.assertEqual(self.db_branch.revision_count(), 0)

    def test_import_recommit(self):
        # Second import honours uncommit followed by commit.
        self.commitRevision('first')
        self.syncAndCount(new_revisions=1, new_numbers=1)
        self.uncommitRevision()
        self.commitRevision('second')
        self.syncAndCount(new_revisions=1)
        self.assertEqual(self.db_branch.revision_count(), 1)
        [revno] = self.db_branch.revision_history
        self.assertEqual(revno.revision.log_body, 'second')

    def test_import_revision_with_url(self):
        # Importing a revision passing the url parameter works.
        self.commitRevision()
        counts = self.getCounts()
        bzrsync = BzrSync(transaction, self.db_branch.id, self.bzr_branch_url)
        bzrsync.syncHistory()
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

    def test_shorten_history(self):
        # commit some revisions with two paths to the head revision
        self.commitRevision()
        merge_rev_id = self.bzr_branch.last_revision()
        self.commitRevision()
        self.commitRevision(pending_merges=[merge_rev_id])
        self.syncAndCount(new_revisions=3, new_numbers=3, new_parents=3)

        # now do a sync with a the shorter history.
        old_revision_history = self.bzr_branch.revision_history()
        new_revision_history = (old_revision_history[:-2] +
                                old_revision_history[-1:])

        counts = self.getCounts()
        bzrsync = BzrSync(transaction, self.db_branch.id)
        bzrsync.bzr_history = new_revision_history
        bzrsync.syncHistory()
        # the new history is one revision shorter:
        self.assertCounts(
            counts, new_revisions=0, new_numbers=-1,
            new_parents=0, new_authors=0)

    def test_revision_modified(self):
        # test that modifications to the parents list get caught.
        class FakeRevision:
            revision_id = ['rev42']
            parent_ids = ['rev1', 'rev2']
            committer = self.AUTHOR
            message = self.LOG
            timestamp = 1000000000.0
            timezone = 0
        bzrsync = BzrSync(transaction, self.db_branch.id)
        # synchronise the fake revision:
        counts = self.getCounts()
        bzrsync.syncRevision(FakeRevision)
        self.assertCounts(
            counts, new_revisions=1, new_numbers=0,
            new_parents=2, new_authors=0)

        # verify that synchronising the revision twice passes and does
        # not create a second revision object:
        counts = self.getCounts()
        bzrsync.syncRevision(FakeRevision)
        self.assertCounts(
            counts, new_revisions=0, new_numbers=0,
            new_parents=0, new_authors=0)

        # verify that adding a parent gets caught:
        FakeRevision.parent_ids.append('rev3')
        self.assertRaises(RevisionModifiedError,
                          bzrsync.syncRevision, FakeRevision)

        # verify that removing a parent gets caught:
        FakeRevision.parent_ids = ['rev1']
        self.assertRaises(RevisionModifiedError,
                          bzrsync.syncRevision, FakeRevision)

        # verify that reordering the parents gets caught:
        FakeRevision.parent_ids = ['rev2', 'rev1']
        self.assertRaises(RevisionModifiedError,
                          bzrsync.syncRevision, FakeRevision)


TestUtil.register(__name__)

