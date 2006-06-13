#!/usr/bin/python
# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Import version control metadata from a Bazaar2 branch into the database."""

__metaclass__ = type

__all__ = [
    "BzrSync",
    ]

import sys
import os
import logging
from datetime import datetime

from pytz import UTC
from zope.component import getUtility
from bzrlib.branch import Branch as BzrBranch
from bzrlib.errors import NoSuchRevision

from sqlobject import AND, SQLObjectNotFound
from canonical.lp import initZopeless
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.database import (
    Person, Branch, Revision, RevisionNumber, RevisionParent, RevisionAuthor)
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IBranchSet, NotFoundError)


class RevisionModifiedError(Exception):
    """An error indicating that a revision has been modified."""
    pass


class BzrSync:
    """Import version control metadata from Bazaar2 branches into the database.

    If the contructor succeeds, a read-lock for the underlying bzrlib branch is
    held, and must be released by calling the `close` method.
    """

    def __init__(self, trans_manager, branch_id, branch_url=None, logger=None):
        self.trans_manager = trans_manager
        self._admin = getUtility(ILaunchpadCelebrities).admin
        if logger is None:
            logger = logging.getLogger(self.__class__.__name__)
        self.logger = logger
        branchset = getUtility(IBranchSet)
        # Will raise NotFoundError when the branch is not found.
        self.db_branch = branchset[branch_id]
        if branch_url is None:
            branch_url = self.db_branch.url
        self.bzr_branch = BzrBranch.open(branch_url)
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
        for revision_id in ancestry:
            if revision_id is None:
                continue
            # If the revision is a ghost, it won't appear in the repository.
            try:
                revision = self.bzr_branch.repository.get_revision(revision_id)
            except NoSuchRevision:
                continue
            if self.syncRevision(revision):
                did_something = True

        # now synchronise the RevisionNumber objects
        if self.syncRevisionNumbers():
            did_something = True

        return did_something

    def syncRevision(self, bzr_revision):
        """Import the revision with the given revision_id.

        :param bzr_revision: the revision to import
        :type bzr_revision: bzrlib.revision.Revision
        """
        revision_id = bzr_revision.revision_id
        self.logger.debug("synchronizing revision: %s", revision_id)

        # If did_something is True, new information was found and
        # loaded into the database.
        did_something = False

        self.trans_manager.begin()

        try:
            db_revision = Revision.byRevisionID(revision_id)
        except SQLObjectNotFound:
            db_revision = None
        if db_revision is not None:
            # Verify that the revision in the database matches the
            # revision from the branch.  Currently we just check that
            # the parent revision list matches.
            db_parents = shortlist(RevisionParent.selectBy(
                revisionID=db_revision.id, orderBy='sequence'))
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
            timestamp = bzr_revision.timestamp
            if bzr_revision.timezone:
                timestamp += bzr_revision.timezone
            revision_date = datetime.fromtimestamp(timestamp, tz=UTC)
            try:
                db_author = RevisionAuthor.byName(bzr_revision.committer)
            except SQLObjectNotFound:
                db_author = RevisionAuthor(name=bzr_revision.committer)
            db_revision = Revision(revision_id=revision_id,
                                   log_body=bzr_revision.message,
                                   revision_date=revision_date,
                                   revision_author=db_author.id,
                                   owner=self._admin.id)
            seen_parents = set()
            for sequence, parent_id in enumerate(bzr_revision.parent_ids):
                if parent_id in seen_parents:
                    continue
                seen_parents.add(parent_id)
                RevisionParent(revision=db_revision.id, sequence=sequence,
                               parent_id=parent_id)
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
        if self.truncateHistory():
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

        db_revision = Revision.byRevisionID(revision_id)
        db_revno = RevisionNumber.selectOneBy(
            sequence=sequence, branchID=self.db_branch.id)

        # If the database revision history has diverged, so we
        # truncate the database history from this point on.  The
        # replacement revision numbers will be created in their place.
        if db_revno is not None and db_revno.revision != db_revision:
            if self.truncateHistory(sequence):
                did_something = True
            db_revno = None

        if db_revno is None:
            db_revno = RevisionNumber(
                sequence=sequence,
                revision=db_revision.id,
                branch=self.db_branch.id)
            did_something = True

        if did_something:
            self.trans_manager.commit()
        else:
            self.trans_manager.abort()

        return did_something

    def truncateHistory(self, from_rev=None):
        """Remove excess RevisionNumber rows.

        :param from_rev: truncate from this revision on (defaults to
            truncating revisions past the current revision number).
        :type from_rev:  int or None

        If the revision history for the branch has changed, some of
        the RevisionNumber objects will no longer be valid.  These
        objects must be removed before the replacement RevisionNumbers
        can be created in the database.

        This function is expected to be called from within a transaction.
        """
        if from_rev is None:
            from_rev = len(self.bzr_history) + 1

        self.logger.debug("Truncating revision numbers from %d on", from_rev)
        revnos = RevisionNumber.select(AND(
            RevisionNumber.q.branchID == self.db_branch.id,
            RevisionNumber.q.sequence >= from_rev))
        did_something = False
        for revno in revnos:
            revno.destroySelf()
            did_something = True

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
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        bzrsync = BzrSync(trans_manager, branch_id, logger=logger)
    except NotFoundError:
        logger.error("Branch not found: %d" % branch_id)
        status = 1
    else:
        bzrsync.syncHistoryAndClose()
    return status

if __name__ == '__main__':
    execute_zcml_for_scripts()

    if len(sys.argv) != 2:
        sys.exit("Usage: bzrsync.py <branch_id>")
    branch_id = int(sys.argv[1])
    status = main(branch_id)
    sys.exit(status)
