#!/usr/bin/python
# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""Import version control metadata from a Bazaar branch into the database."""

__metaclass__ = type

__all__ = [
    "BzrSync",
    ]

import logging
import sys
from datetime import datetime, timedelta

import pytz
from zope.component import getUtility
from bzrlib.branch import Branch
from bzrlib.revision import NULL_REVISION
from bzrlib.errors import NoSuchRevision

from canonical.launchpad.interfaces import (
    IBugSet, ILaunchpadCelebrities, IBugBranchRevisionSet, IBranchRevisionSet,
    IRevisionSet, NotFoundError)
from canonical.launchpad.webapp import errorlog

UTC = pytz.timezone('UTC')


class RevisionModifiedError(Exception):
    """An error indicating that a revision has been modified."""
    pass


class BzrSync:
    """Import version control metadata from a Bazaar branch into the database.

    If the contructor succeeds, a read-lock for the underlying bzrlib branch is
    held, and must be released by calling the `close` method.
    """

    def __init__(self, trans_manager, branch, branch_url=None, logger=None):
        self.trans_manager = trans_manager
        self._admin = getUtility(ILaunchpadCelebrities).admin
        if logger is None:
            logger = logging.getLogger(self.__class__.__name__)
        self.logger = logger
        self.db_branch = branch
        if branch_url is None:
            branch_url = self.db_branch.url
        self.bzr_branch = Branch.open(branch_url)
        self.bzr_branch.lock_read()

    def close(self):
        """Explicitly release resources."""
        # release the read lock on the bzrlib branch
        self.bzr_branch.unlock()
        # prevent further use of that object
        self.bzr_branch = None
        self.db_branch = None
        self.bzr_history = None

    def syncBranchAndClose(self):
        """Synchronize the database with a Bazaar branch and release resources.

        Convenience method that implements the proper for the common case of
        calling `syncBranch` and `close`.
        """
        try:
            self.syncBranch()
        finally:
            self.close()

    def syncBranch(self):
        """Synchronize the database view of a branch with Bazaar data.

        Several tables must be updated:

        * Revision: there must be one Revision row for each revision in the
          branch ancestry. If the row for a revision that has just been added
          to the branch is already present, it must be checked for consistency.

        * BranchRevision: there must be one BrancheRevision row for each
          revision in the branch ancestry. If history revisions became merged
          revisions, the corresponding rows must be changed.

        * Branch: the branch-scanner status information must be updated when
          the sync is complete.
        """
        self.logger.info("Scanning branch: %s",self.db_branch.unique_name)
        self.logger.info("    from %s", self.bzr_branch.base)
        # Get the history and ancestry from the branch first, to fail early
        # if something is wrong with the branch.
        self.retrieveBranchDetails()
        # The BranchRevision, Revision and RevisionParent tables are only
        # written to by the branch-scanner, so they are not subject to
        # write-lock contention. Update them all in a single transaction to
        # improve the performance and allow garbage collection in the future.
        self.trans_manager.begin()
        self.retrieveDatabaseAncestry()
        (revisions_to_insert_or_check, branchrevisions_to_delete,
            branchrevisions_to_insert) = self.planDatabaseChanges()
        self.syncRevisions(revisions_to_insert_or_check)
        self.deleteBranchRevisions(branchrevisions_to_delete)
        self.insertBranchRevisions(branchrevisions_to_insert)
        self.trans_manager.commit()
        # The Branch table is written to by other systems, including the web
        # UI, so we need to update it in a short transaction to avoid causing
        # timeouts in the webapp. This opens a small race window where the
        # revision data is updated in the database, but the Branch table has
        # not been updated. Since this has no ill-effect, and can only err on
        # the pessimistic side (tell the user the data has not yet been updated
        # althought it has), the race is accetpable.
        self.trans_manager.begin()
        self.updateBranchStatus()
        self.trans_manager.commit()

    def retrieveDatabaseAncestry(self):
        """Efficiently retrieve ancestry from the database."""
        self.logger.info("Retrieving ancestry from database.")
        branch_revision_set = getUtility(IBranchRevisionSet)
        self.db_ancestry, self.db_history, self.db_branch_revision_map = \
            branch_revision_set.getScannerDataForBranch(self.db_branch)

    def retrieveBranchDetails(self):
        """Retrieve ancestry from the the bzr branch on disk."""
        self.logger.info("Retrieving ancestry from bzrlib.")
        self.last_revision = self.bzr_branch.last_revision()
        # Make bzr_ancestry a set for consistency with db_ancestry.
        bzr_ancestry_ordered = \
            self.bzr_branch.repository.get_ancestry(self.last_revision)
        first_ancestor = bzr_ancestry_ordered.pop(0)
        assert first_ancestor is None, 'history horizons are not supported'
        self.bzr_ancestry = set(bzr_ancestry_ordered)
        self.bzr_history = self.bzr_branch.revision_history()

    def planDatabaseChanges(self):
        """Plan database changes to synchronize with bzrlib data.

        Use the data retrieved by `retrieveDatabaseAncestry` and
        `retrieveBranchDetails` to plan the changes to apply to the database.
        """
        self.logger.info("Planning changes.")
        bzr_ancestry = self.bzr_ancestry
        bzr_history = self.bzr_history
        db_ancestry = self.db_ancestry
        db_history = self.db_history
        db_branch_revision_map = self.db_branch_revision_map

        # Find the length of the common history.
        common_len = min(len(bzr_history), len(db_history))
        while common_len > 0:
            # The outer conditional improves efficiency. Without it, the
            # algorithm is O(history-size * change-size), which can be
            # excessive if a long branch is replaced by another long branch
            # with a distant (or no) common mainline parent. The inner
            # conditional is needed for correctness with branches where the
            # history does not follow the line of leftmost parents.
            if db_history[common_len - 1] == bzr_history[common_len - 1]:
                if db_history[:common_len] == bzr_history[:common_len]:
                    break
            common_len -= 1

        # Revisions added to the branch's ancestry.
        added_ancestry = bzr_ancestry.difference(db_ancestry)

        # Revision added or removed from the branch's history. These lists may
        # include revisions whose history position has merely changed.
        removed_history = db_history[common_len:]
        added_history = bzr_history[common_len:]

        # Merged (non-history) revisions in the database and the bzr branch.
        old_merged = db_ancestry.difference(db_history)
        new_merged = bzr_ancestry.difference(bzr_history)

        # Revisions added or removed from the set of merged revisions.
        removed_merged = old_merged.difference(new_merged)
        added_merged = new_merged.difference(old_merged)

        # We must delete BranchRevision rows for all revisions which where
        # removed from the ancestry or whose sequence value has changed.
        branchrevisions_to_delete = set(
            db_branch_revision_map[revid]
            for revid in removed_merged.union(removed_history))

        # We must insert BranchRevision rows for all revisions which were added
        # to the ancestry or whose sequence value has changed.
        branchrevisions_to_insert = list(
            self.getRevisions(added_merged.union(added_history)))

        # We must insert, or check for consistency, all revisions which were
        # added to the ancestry.
        revisions_to_insert_or_check = added_ancestry

        return (revisions_to_insert_or_check, branchrevisions_to_delete,
            branchrevisions_to_insert)

    def syncRevisions(self, revisions_to_insert_or_check):
        """Import all the revisions added to the ancestry of the branch."""
        self.logger.info("Inserting or checking %d revisions.",
            len(revisions_to_insert_or_check))
        # Add new revisions to the database.
        for revision_id in revisions_to_insert_or_check:
            # If the revision is a ghost, it won't appear in the repository.
            try:
                revision = self.bzr_branch.repository.get_revision(revision_id)
            except NoSuchRevision:
                continue
            self.syncOneRevision(revision)

    def syncOneRevision(self, bzr_revision):
        """Import the revision with the given revision_id.

        :param bzr_revision: the revision to import
        :type bzr_revision: bzrlib.revision.Revision
        """
        revision_id = bzr_revision.revision_id
        revision_set = getUtility(IRevisionSet)
        db_revision = revision_set.getByRevisionId(revision_id)
        if db_revision is not None:
            # Verify that the revision in the database matches the
            # revision from the branch.  Currently we just check that
            # the parent revision list matches.
            self.logger.debug("Checking revision: %s", revision_id)
            db_parents = db_revision.parents
            bzr_parents = bzr_revision.parent_ids

            seen_parents = set()
            for sequence, parent_id in enumerate(bzr_parents):
                if parent_id in seen_parents:
                    continue
                seen_parents.add(parent_id)
                matching_parents = [db_parent for db_parent in db_parents
                                    if db_parent.parent_id == parent_id]
                if len(matching_parents) == 0:
                    raise RevisionModifiedError(
                        'parent %s was added since last scan' % parent_id)
                elif len(matching_parents) > 1:
                    raise RevisionModifiedError(
                        'parent %s is listed multiple times in db' % parent_id)
                if matching_parents[0].sequence != sequence:
                    raise RevisionModifiedError(
                        'parent %s reordered (old index %d, new index %d)'
                        % (parent_id, matching_parents[0].sequence, sequence))
            if len(seen_parents) != len(db_parents):
                removed_parents = [db_parent.parent_id
                                   for db_parent in db_parents
                                   if db_parent.parent_id not in seen_parents]
                raise RevisionModifiedError(
                    'some parents removed since last scan: %s'
                    % (removed_parents,))
        else:
            # Revision not yet in the database. Load it.
            self.logger.debug("Inserting revision: %s", revision_id)
            revision_date = self._timestampToDatetime(bzr_revision.timestamp)
            db_revision = revision_set.new(
                revision_id=revision_id,
                log_body=bzr_revision.message,
                revision_date=revision_date,
                revision_author=bzr_revision.committer,
                owner=self._admin,
                parent_ids=bzr_revision.parent_ids)
            self._makeBugRevisionLink(db_revision, bzr_revision)

    def _makeBugRevisionLink(self, db_revision, bzr_revision):
        try:
            bug_id = int(bzr_revision.properties['launchpad:bug'])
        except KeyError:
            return
        except ValueError:
            errorlog.globalErrorUtility.raising(sys.exc_info())
            return
        bug_set = getUtility(IBugSet)
        try:
            bug = bug_set.get(bug_id)
        except NotFoundError:
            errorlog.globalErrorUtility.raising(sys.exc_info())
            return
        if not bug.hasBranch(self.db_branch):
            bug.addBranch(self.db_branch)
        bbr_set = getUtility(IBugBranchRevisionSet)
        # XXX - add a record to the bug activity log
        # XXX - make sure the 'status' field is correct
        return bbr_set.new(
            bug=bug_set.get(bug_id), branch=self.db_branch,
            revision=db_revision)

    def getRevisions(self, limit=None):
        """Generate revision IDs that make up the branch's ancestry.

        Generate a sequence of (sequence, revision-id) pairs to be inserted
        into the branchrevision (nee revisionnumber) table.

        :param limit: set of revision ids, only yield tuples whose revision-id
            is in this set. Defaults to the full ancestry of the branch.
        """
        if limit is None:
            limit = self.bzr_ancestry
        for (index, revision_id) in enumerate(self.bzr_history):
            if revision_id in limit:
                # sequence numbers start from 1
                yield index + 1, revision_id
        for revision_id in limit.difference(set(self.bzr_history)):
            yield None, revision_id

    def _timestampToDatetime(self, timestamp):
        """Convert the given timestamp to a datetime object.

        This works around a bug in Python that causes datetime.fromtimestamp
        to raise an exception if it is given a negative, fractional timestamp.

        :param timestamp: A timestamp from a bzrlib.revision.Revision
        :type timestamp: float

        :return: A datetime corresponding to the given timestamp.
        """
        # Work around Python bug #1646728.
        # See https://launchpad.net/bugs/81544.
        int_timestamp = int(timestamp)
        revision_date = datetime.fromtimestamp(int_timestamp, tz=UTC)
        revision_date += timedelta(seconds=timestamp - int_timestamp)
        return revision_date

    def deleteBranchRevisions(self, branchrevisions_to_delete):
        """Delete a batch of BranchRevision rows."""
        self.logger.info("Deleting %d branchrevision records.",
            len(branchrevisions_to_delete))
        branch_revision_set = getUtility(IBranchRevisionSet)
        for branchrevision in sorted(branchrevisions_to_delete):
            branch_revision_set.delete(branchrevision)

    def insertBranchRevisions(self, branchrevisions_to_insert):
        """Insert a batch of BranchRevision rows."""
        self.logger.info("Inserting %d branchrevision records.",
            len(branchrevisions_to_insert))
        branch_revision_set = getUtility(IBranchRevisionSet)
        revision_set = getUtility(IRevisionSet)
        for sequence, revision_id in branchrevisions_to_insert:
            db_revision = revision_set.getByRevisionId(revision_id)
            branch_revision_set.new(self.db_branch, sequence, db_revision)

    def updateBranchStatus(self):
        """Update the branch-scanner status in the database Branch table."""
        # Record that the branch has been updated.
        self.logger.info("Updating branch scanner status.")
        if len(self.bzr_history) > 0:
            last_revision = self.bzr_history[-1]
        else:
            last_revision = NULL_REVISION

        # FIXME: move that conditional logic down to updateScannedDetails.
        # -- DavidAllouche 2007-02-22
        revision_count = len(self.bzr_history)
        if (last_revision != self.db_branch.last_scanned_id) or \
               (revision_count != self.db_branch.revision_count):
            self.db_branch.updateScannedDetails(last_revision, revision_count)
