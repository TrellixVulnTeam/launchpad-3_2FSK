# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Functions used with the Rosetta PO import script."""

__metaclass__ = type

from zope.component import getUtility

from canonical.launchpad.interfaces import ITranslationImportQueue
from canonical.lp.dbschema import RosettaImportStatus

class ImportProcess:
    """Import .po and .pot files attached to Rosetta."""

    def __init__(self, ztm, logger):
        """Initialize the ImportProcess object.

        Get two arguments, the Zope Transaction Manager and a logger for the
        warning/errors messages.
        """
        self.ztm = ztm
        self.logger = logger

    def run(self):
        """Execute the import of entries from the queue."""
        # Get the queue.
        translation_import_queue = getUtility(ITranslationImportQueue)

        while True:
            # Execute the imports until we stop having entries to import.

            # Get the top element from the queue.
            entry_to_import = translation_import_queue.getFirstEntryToImport()

            # Execute the auto approve algorithm to save Rosetta experts some
            # work when possible.
            if entry_to_import is None:
                auto_approve(translation_import_queue, self.logger, self.ztm)
                break

            assert entry_to_import.import_into is not None, (
                "Broken entry, it's Approved but lacks the place where it"
                " should be imported! Look at the top of the import queue")

            # Do the import.
            title = '[Unknown Title]'
            try:
                title = entry_to_import.import_into.title
                self.logger.info('Importing: %s' % title)
                entry_to_import.import_into.importFromQueue(self.logger)
            except KeyboardInterrupt:
                self.ztm.abort()
                raise
            except:
                # If we have any exception, log it, abort the transaction and
                # set the status to FAILED.
                self.logger.error('Got an unexpected exception while'
                                  ' importing %s' % title, exc_info=1)
                # We are going to abort the transaction, need to save the id
                # of this entry to update its status.
                failed_entry_id = entry_to_import.id
                self.ztm.abort()
                # Get the needed objects to set the failed entry status as
                # FAILED.
                translation_import_queue = getUtility(ITranslationImportQueue)
                entry_to_import = translation_import_queue[failed_entry_id]
                entry_to_import.status = RosettaImportStatus.FAILED
                self.ztm.commit()
                # Go to process next entry.
                continue

            # As soon as the import is done, we commit the transaction
            # so it's not lost.
            try:
                self.ztm.commit()
            except KeyboardInterrupt:
                self.ztm.abort()
                raise
            except:
                # If we have any exception, we log it and abort the
                # transaction.
                self.logger.error('We got an unexpected exception while'
                                  ' committing the transaction', exc_info=1)
                self.ztm.abort()

def auto_approve(translation_import_queue, logger, ztm):
    """Attempt to approve requests without human intervention.

    Look for entries in translation_import_queue that look like they can
    be approved automatically.

    Also, detect requests that should be blocked, and block them in their
    entirety (with all their .pot and .po files).
    """

    # There may be corner cases where an 'optimistic approval' could
    # import a .po file to the wrong IPOFile (but the right language).
    # The savings justify that risk.  The problem can only occur where,
    # for a given productseries/sourcepackage, we have two potemplates in
    # the same directory, each with its own set of .po files, and for some
    # reason one of the .pot files has not been added to the queue.  Then
    # we would import both sets of .po files to that template.  This is
    # not a big issue because the two templates will rarely share an
    # identical msgid, and especially because it's not a very common
    # layout in the free software world.
    if translation_import_queue.executeOptimisticApprovals(ztm):
        logger.info(
            'The automatic approval system approved some entries.')

    removed_entries = translation_import_queue.cleanUpQueue()
    if removed_entries > 0:
        logger.info('Removed %d entries from the queue.' %
            removed_entries)
        ztm.commit()

    # We need to block entries automatically to save Rosetta experts some
    # work when a complete set of .po files and a .pot file should not be
    # imported into the system.  We have the same corner case as with the
    # previous approval method, but in this case it's a matter of changing
    # the status back from "blocked" to "needs review," or approving it
    # directly so no data will be lost and a lot of work is saved.
    blocked_entries = (
        translation_import_queue.executeOptimisticBlock(ztm))
    if blocked_entries > 0:
        logger.info('Blocked %d entries from the queue.' %
            blocked_entries)
        ztm.commit()

