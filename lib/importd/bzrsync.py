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

from canonical.lp import initZopeless
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.database import (
    Person, Branch, Revision, RevisionNumber, RevisionParent, RevisionAuthor)
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IBranchSet, NotFoundError)


class BzrSync:
    """Import version control metadata from Bazaar2 branches into the database.
    """

    def __init__(self, trans_manager, branch_id, branch_url=None, logger=None):
        self.trans_manager = trans_manager
        branchset = getUtility(IBranchSet)
        # Will raise NotFoundError when the branch is not found.
        self.db_branch = branchset[branch_id]
        if branch_url is None:
            branch_url = self.db_branch.url
        self.bzr_branch = BzrBranch.open(branch_url)
        self.bzr_history = self.bzr_branch.revision_history()
        self._seen_ids = set()
        self._admin = getUtility(ILaunchpadCelebrities).admin
        if logger is None:
            logger = logging.getLogger(self.__class__.__name__)
        self.logger = logger

    def syncHistory(self, doparents=True):
        """Import all revisions in the branch's revision-history.

        :param doparents: If true, also import parents of imported revisions.
        """
        self.logger.info(
            "synchronizing history for branch: %s" % self.bzr_branch.base)

        # Keep track if something was actually loaded in the database.
        didsomething = False

        if doparents:
            pending_parents = []
        else:
            pending_parents = None

        for revision_id in self.bzr_history:
            didsomething |= self.syncRevision(revision_id, pending_parents)
        if pending_parents:
            didsomething |= self.syncPendingParents(pending_parents)
        didsomething |= self.truncateHistory()

        return didsomething

    def syncRevision(self, revision_id, pending_parents=None):
        """Import the revision with the given revision_id.

        :param revision_id: GUID of the revision to import.
        :type revision_id: str
        :param pending_parents: append GUID of revision parents to that list,
            for subsequent processing by `syncPendingParents`.
        :type pending_parents: list or None
        """
        # Prevent the same revision from being synchronized twice.
        # This may happen when processing parents, for instance.
        if revision_id in self._seen_ids:
            return False
        self._seen_ids.add(revision_id)

        self.logger.debug("synchronizing revision: %s" % revision_id)

        # If didsomething is True, new information was found and
        # loaded into the database.
        didsomething = False

        try:
            bzr_revision = self.bzr_branch.repository.get_revision(revision_id)
        except NoSuchRevision:
            return didsomething

        self.trans_manager.begin()

        db_revision = Revision.selectOneBy(revision_id=revision_id)
        if not db_revision:
            # Revision not yet in the database. Load it.
            timestamp = bzr_revision.timestamp
            if bzr_revision.timezone:
                timestamp += bzr_revision.timezone
            revision_date = datetime.fromtimestamp(timestamp, tz=UTC)
            db_author = RevisionAuthor.selectOneBy(name=bzr_revision.committer)
            if not db_author:
                db_author = RevisionAuthor(name=bzr_revision.committer)
            db_revision = Revision(revision_id=revision_id,
                                   log_body=bzr_revision.message,
                                   revision_date=revision_date,
                                   revision_author=db_author.id,
                                   owner=self._admin.id)
            didsomething = True

        if pending_parents is not None:
            # Caller requested to be informed about pending parents.
            # Provide information about them. Notice that the database
            # scheme was changed to not use the parent_id as a foreign
            # key, so they could be loaded right here, and just loading
            # the revision themselves postponed to avoid recursion.
            seen_parent_ids = set()
            for sequence, parent_id in enumerate(bzr_revision.parent_ids):
                if parent_id not in seen_parent_ids:
                    seen_parent_ids.add(parent_id)
                    pending_parents.append((revision_id, sequence, parent_id))

        if revision_id in self.bzr_history:
            # Revision is in history, so append it to the RevisionNumber
            # table as well, if not yet there.
            bzr_revno = self.bzr_history.index(revision_id) + 1
            db_revno = RevisionNumber.selectOneBy(
                sequence=bzr_revno, branchID=self.db_branch.id)

            if db_revno and db_revno.revision.revision_id != revision_id:
                db_revno.revision = db_revision.id
                didsomething = True

            if not db_revno:
                db_revno = RevisionNumber(
                    sequence=bzr_revno,
                    revision=db_revision.id,
                    branch=self.db_branch.id)
                didsomething = True

            # Sanity check that recorded revision history and ancestry match
            # TODO: need to record parents immediately!

            # TODO: check that recorded parent list is equal to parent list in
            # branch.

        if didsomething:
            self.trans_manager.commit()
        else:
            self.trans_manager.abort()

        return didsomething

    def syncPendingParents(self, pending_parents, recurse=True):
        """Load parents with the information provided by syncRevision()

        :param pending_parents: GUIDs of revisions to import.
        :type pending_parents: iterable of str
        :param recurse: If true, parents of parents will be loaded as well.
        """
        # Keep track if something was actually loaded in the database.
        didsomething = False

        if recurse:
            pending_parents = list(pending_parents)
            sync_pending_parents = pending_parents
        else:
            sync_pending_parents = None

        while pending_parents:
            # Pop each element from the pending_parents queue and process it.
            # If recurse is True, syncRevision() may append additional
            # items to the list, which will be processed as well.
            revision_id, sequence, parent_id = pending_parents.pop(0)
            didsomething |= self.syncRevision(parent_id, sync_pending_parents)
            db_revision = Revision.selectOneBy(revision_id=revision_id)
            db_parent = RevisionParent.selectOneBy(revisionID=db_revision.id,
                                                   parent_id=parent_id)
            if db_parent:
                assert db_parent.sequence == sequence, (
                    "Revision %r already has parent %r  with index %d. But we"
                    " tried to import this parent again with index %d."
                    % (db_revision.revision_id, parent_id,
                       db_parent.sequence, sequence))
            else:
                self.trans_manager.begin()
                RevisionParent(revision=db_revision.id, parent_id=parent_id,
                               sequence=sequence)
                self.trans_manager.commit()
                didsomething = True

        return didsomething

    def truncateHistory(self):
        """Remove excess RevisionNumber rows.

        That is needed 'uncommit' or 'pull/push --overwrite' shortened the
        revision history. RevisionNumber rows with a sequence matching entries
        in the bzr history are updated by syncRevision, but we need to
        separately delete the excess rows.
        """
        db_history_len = self.db_branch.revision_history.count()
        excess = db_history_len - len(self.bzr_history)
        # syncRevision should be called on every item of the branch history
        # before truncating history, so the history recorded in the database
        # must be already at least as long as the history of the branch.
        assert excess >= 0
        if excess == 0:
            return False
        self.trans_manager.begin()
        for revno in self.db_branch.latest_revisions(excess):
            revno.destroySelf()
        self.trans_manager.commit()
        return True


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
        bzrsync.syncHistory()
    return status

if __name__ == '__main__':
    execute_zcml_for_scripts()

    if len(sys.argv) != 2:
        sys.exit("Usage: bzrsync.py <branch_id>")
    branch_id = int(sys.argv[1])
    status = main(branch_id)
    sys.exit(status)
