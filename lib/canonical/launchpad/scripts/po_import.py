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

            if entry_to_import is None:
                # There are no entries to import.
                # Execute the auto approve algorithm to save Rosetta experts
                # some work when possible.
                if translation_import_queue.executeAutomaticReviews(self.ztm):
                    self.logger.info(
                        'The automatic approval system approved some entries.'
                        )

                # Remove obsolete entries from the queue.
                removed_entries = translation_import_queue.cleanUpQueue()
                if removed_entries > 0:
                    self.logger.info('Removed %d entries from the queue.' %
                        removed_entries)
                    zmt.commit()
                # Exit the loop.
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

