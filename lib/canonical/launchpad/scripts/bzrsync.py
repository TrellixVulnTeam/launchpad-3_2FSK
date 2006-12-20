#!/usr/bin/python
# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""Import version control metadata from a Bazaar branch into the database."""

__metaclass__ = type

__all__ = [
    "BzrSync",
    ]

import sys
import os
import logging
from datetime import datetime

import pytz
from zope.component import getUtility
from bzrlib.branch import Branch
from bzrlib.revision import NULL_REVISION
from bzrlib.errors import NoSuchRevision

from sqlobject import AND
from canonical.lp import initZopeless
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IBranchSet, IRevisionSet)

UTC = pytz.timezone('UTC')


class RevisionModifiedError(Exception):
    """An error indicating that a revision has been modified."""
    pass


class BzrSync:
    """Import version control metadata from Bazaar2 branches into the database.

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
        try:
            self.bzr_history = self.bzr_branch.revision_history()
        except:
            self.bzr_branch.unlock()
            raise

    def close(self):
        """Explicitly release resources."""
        # release the read lock on the bzrlib branch
        self.bzr_branch.unlock()
        # prevent further use of that object
        self.bzr_branch = None
        self.db_branch = None
        self.bzr_history = None

    def syncHistoryAndClose(self):
        """Import all revisions in the branch and release resources.

        Convenience method that implements the proper try/finally idiom for the
        common case of calling `syncHistory` and immediately `close`.
        """
        try:
            self.syncHistory()
        finally:
            self.close()

    def syncHistory(self):
        """Import all revisions in the branch."""
        # Keep track if something was actually loaded in the database.
        did_something = False

        self.logger.info(
            "synchronizing ancestry for branch: %s", self.bzr_branch.base)

        # synchronise Revision objects
        ancestry = self.bzr_branch.repository.get_ancestry(
            self.bzr_branch.last_revision())
        curr = 0
        last = len(ancestry)
        for revision_id in ancestry:
            curr = curr + 1
            if revision_id is None:
                self.logger.debug("%d of %d: revision_id is None",
                                  curr, last)
                continue
            # If the revision is a ghost, it won't appear in the repository.
            try:
                revision = self.bzr_branch.repository.get_revision(revision_id)
            except NoSuchRevision:
                self.logger.debug("%d of %d: %s is a ghost",
                                  curr, last, revision_id)
                continue
            if self.syncRevision(revision, curr, last):
                did_something = True

        # now synchronise the RevisionNumber objects
        if self.syncRevisionNumbers():
            did_something = True

        return did_something

    def syncRevision(self, bzr_revision, curr, last):
        """Import the revision with the given revision_id.

        :param bzr_revision: the revision to import
        :type bzr_revision: bzrlib.revision.Revision
        """
        revision_id = bzr_revision.revision_id
        self.logger.debug("%d of %d: synchronizing revision: %s",
                          curr, last, revision_id)

        # If did_something is True, new information was found and
        # loaded into the database.
        did_something = False

        self.trans_manager.begin()

        db_revision = getUtility(IRevisionSet).getByRevisionId(revision_id)
        if db_revision is not None:
            # Verify that the revision in the database matches the
            # revision from the branch.  Currently we just check that
            # the parent revision list matches.
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
            revision_date = datetime.fromtimestamp(
                bzr_revision.timestamp, tz=UTC)

            db_revision = getUtility(IRevisionSet).new(
                revision_id=revision_id,
                log_body=bzr_revision.message,
                revision_date=revision_date,
                revision_author=bzr_revision.committer,
                owner=self._admin,
                parent_ids=bzr_revision.parent_ids)
            did_something = True

        if did_something:
            self.trans_manager.commit()
        else:
            self.trans_manager.abort()

        return did_something

    def syncRevisionNumbers(self):
        """Synchronise the revision numbers for the branch."""
        self.logger.info(
            "synchronizing revision numbers for branch: %s",
            self.bzr_branch.base)

        did_something = False
        self.trans_manager.begin()
        # now synchronise the RevisionNumber objects
        for (index, revision_id) in enumerate(self.bzr_history):
            # sequence numbers start from 1
            sequence = index + 1
            if self.syncRevisionNumber(sequence, revision_id):
                did_something = True

        # finally truncate any further revision numbers (if they exist):
        if self.db_branch.truncateHistory(len(self.bzr_history) + 1):
            did_something = True

        # record that the branch has been updated.
        if len(self.bzr_history) > 0:
            last_revision = self.bzr_history[-1]
        else:
            last_revision = NULL_REVISION

        revision_count = len(self.bzr_history)
        if (last_revision != self.db_branch.last_scanned_id) or \
           (revision_count != self.db_branch.revision_count):
            self.db_branch.updateScannedDetails(last_revision, revision_count)
            did_something = True

        if did_something:
            self.trans_manager.commit()
        else:
            self.trans_manager.abort()

        return did_something

    def syncRevisionNumber(self, sequence, revision_id):
        """Import the revision number with the given sequence and revision_id

        :param sequence: the sequence number for this revision number
        :type sequence: int
        :param revision_id: GUID of the revision
        :type revision_id: str
        """
        did_something = False

        self.trans_manager.begin()

        db_revision = getUtility(IRevisionSet).getByRevisionId(revision_id)
        db_revno = self.db_branch.getRevisionNumber(sequence)

        # If the database revision history has diverged, so we
        # truncate the database history from this point on.  The
        # replacement revision numbers will be created in their place.
        if db_revno is not None and db_revno.revision != db_revision:
            if self.db_branch.truncateHistory(sequence):
                did_something = True
            db_revno = None

        if db_revno is None:
            db_revno = self.db_branch.createRevisionNumber(
                sequence, db_revision)
            did_something = True

        if did_something:
            self.trans_manager.commit()
        else:
            self.trans_manager.abort()

        return did_something


def main(branch_id):
    # Load branch with the given branch_id.
    trans_manager = initZopeless(dbuser="importd")
    status = 0

    # Prepare logger
    class Formatter(logging.Formatter):
        def format(self, record):
            if record.levelno != logging.INFO:
                record.prefix = record.levelname.lower()+": "
            else:
                record.prefix = ""
            return logging.Formatter.format(self, record)
    formatter = Formatter("%(prefix)s%(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger = logging.getLogger("BzrSync")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    branch = getUtility(IBranchSet).get(branch_id)
    if branch is None:
        logger.error("Branch not found: %d" % branch_id)
        status = 1
    else:
        bzrsync = BzrSync(trans_manager, branch, logger=logger)
        bzrsync.syncHistoryAndClose()
    return status

if __name__ == '__main__':
    execute_zcml_for_scripts()

    if len(sys.argv) != 2:
        sys.exit("Usage: bzrsync.py <branch_id>")
    branch_id = int(sys.argv[1])
    status = main(branch_id)
    sys.exit(status)
