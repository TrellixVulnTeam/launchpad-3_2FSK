# (c) Canonical Software Ltd. 2004-2006, all rights reserved.
"""
Processes removals of packages that are scheduled for deletion.
"""

import datetime
import pytz
import os

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import sqlvalues

from canonical.launchpad.database.publishing import (
    SourcePackageFilePublishing, SecureSourcePackagePublishingHistory,
    BinaryPackageFilePublishing, SecureBinaryPackagePublishingHistory)
from canonical.launchpad.interfaces import (
    NotInPool, ISecureSourcePackagePublishingHistory,
    ISecureBinaryPackagePublishingHistory)
from canonical.lp.dbschema import PackagePublishingStatus


class DeathRow:
    """A Distribution Archive Removal Processor."""
    def __init__(self, distribution, diskpool, logger):
        self.distribution = distribution
        self.diskpool = diskpool
        self._removeFile = diskpool.removeFile
        self.logger = logger

    def reap(self, dry_run=False):
        """Reap packages that should be removed from the distribution.

        Looks through all packages that are in PENDINGREMOVAL status and
        have scheduleddeletiondate is in the past, try to remove their
        files from the archive pool (which may be impossible if they are
        used by other packages which are published), and mark them as
        removed."""
        if dry_run:
            # Don't actually remove the files if we are dry running
            def _mockRemoveFile(cn, sn, fn):
                self.logger.debug("(Not really!) removing %s %s/%s" %
                                  (cn, sn, fn))
                fullpath = self.diskpool.pathFor(cn, sn, fn)
                if not os.path.exists(fullpath):
                    raise NotInPool
                return os.lstat(fullpath).st_size
            self._removeFile = _mockRemoveFile

        source_files, binary_files = self._collectCondemned()
        records = self._tryRemovingFromDisk(source_files, binary_files)
        self._markPublicationRemoved(records)

    def _collectCondemned(self):
        source_files = SourcePackageFilePublishing.select("""
            publishingstatus = %s AND
            sourcepackagefilepublishing.archive = %s AND
            SourcePackagePublishingHistory.id =
                 SourcePackageFilePublishing.sourcepackagepublishing AND
            SourcePackagePublishingHistory.scheduleddeletiondate <= %s
            """ % sqlvalues(PackagePublishingStatus.PENDINGREMOVAL,
                            self.distribution.main_archive, UTC_NOW),
            clauseTables=['SourcePackagePublishingHistory'],
            orderBy="id")

        self.logger.debug("%d Sources" % source_files.count())

        binary_files = BinaryPackageFilePublishing.select("""
            publishingstatus = %s AND
            binarypackagefilepublishing.archive = %s AND
            BinaryPackagePublishingHistory.id =
                 BinaryPackageFilePublishing.binarypackagepublishing AND
            BinaryPackagePublishingHistory.scheduleddeletiondate <= %s
            """ % sqlvalues(PackagePublishingStatus.PENDINGREMOVAL,
                            self.distribution.main_archive, UTC_NOW),
            clauseTables=['BinaryPackagePublishingHistory'],
            orderBy="id")

        self.logger.debug("%d Binaries" % binary_files.count())

        return (source_files, binary_files)

    def canRemove(self, publication_class, file_md5):
        """Check if given MD5 can be removed from the archive pool.

        Check the archive reference-counter implemented in:
        `SecureSourcePackagePublishingHistory` or
        `SecureBinaryPackagePublishingHistory`.

        Only allow removal of unnecessary files.
        """
        clauses = []
        clauseTables = []

        if ISecureSourcePackagePublishingHistory.implementedBy(
            publication_class):
            clauses.append("""
                SecureSourcePackagePublishingHistory.status != %s AND
                SecureSourcePackagePublishingHistory.archive = %s AND
                SecureSourcePackagePublishingHistory.sourcepackagerelease =
                    SourcePackageReleaseFile.sourcepackagerelease AND
                SourcePackageReleaseFile.libraryfile = LibraryFileAlias.id
            """ % sqlvalues(PackagePublishingStatus.REMOVED,
                            self.distribution.main_archive))
            clauseTables.append('SourcePackageReleaseFile')
        elif ISecureBinaryPackagePublishingHistory.implementedBy(
            publication_class):
            clauses.append("""
                SecureBinaryPackagePublishingHistory.status != %s AND
                SecureBinaryPackagePublishingHistory.archive = %s AND
                SecureBinaryPackagePublishingHistory.binarypackagerelease =
                    BinaryPackageFile.binarypackagerelease AND
                BinaryPackageFile.libraryfile = LibraryFileAlias.id
            """ % sqlvalues(PackagePublishingStatus.REMOVED,
                            self.distribution.main_archive))
            clauseTables.append('BinaryPackageFile')
        else:
            raise AssertionError("%r is not supported." % publication_class)

        clauses.append("""
           LibraryFileAlias.content = LibraryFileContent.id AND
           LibraryFileContent.md5 = %s
        """ % sqlvalues(file_md5))
        clauseTables.extend(
            ['LibraryFileAlias', 'LibraryFileContent'])

        all_publications = publication_class.select(
            " AND ".join(clauses), clauseTables=clauseTables)

        right_now = datetime.datetime.now(pytz.timezone('UTC'))
        for pub in all_publications:
            # Deny removal if any reference is still active.
            if (pub.status != PackagePublishingStatus.PENDINGREMOVAL):
                return False
            # Deny removal if any reference is still in 'quarantine'.
            # See PubConfig.pendingremovalduration value.
            if (pub.scheduleddeletiondate > right_now):
                return False

        return True

    def _tryRemovingFromDisk(self, condemned_source_files,
                             condemned_binary_files):
        """Take the list of publishing records provided and unpublish them.

        You should only pass in entries you want to be unpublished because
        this will result in the files being removed if they're not otherwise
        in use.
        """
        bytes = 0
        condemned_files = set()
        condemned_records = set()
        considered_md5s = set()
        details = {}

        content_files = (
            (SecureSourcePackagePublishingHistory, condemned_source_files),
            (SecureBinaryPackagePublishingHistory, condemned_binary_files),)

        for publication_class, pub_files in content_files:
            for pub_file in pub_files:
                file_md5 = pub_file.libraryfilealias.content.md5
                # Check if the LibraryFileAlias in question was already
                # verified. If it was, continue.
                if file_md5 in considered_md5s:
                    continue
                considered_md5s.add(file_md5)

                filename = pub_file.libraryfilealiasfilename
                # Check if the removal is allowed, if not continue.
                if not self.canRemove(publication_class, file_md5):
                    continue

                # Update local containers, in preparation to file removal.
                pub_file_details = (
                    pub_file.libraryfilealiasfilename,
                    pub_file.sourcepackagename,
                    pub_file.componentname,
                    )
                file_path = self.diskpool.pathFor(*pub_file_details)
                details.setdefault(file_path, pub_file_details)
                condemned_files.add(file_path)
                condemned_records.add(pub_file.publishing_record)

        self.logger.info(
            "Removing %s files marked for reaping" % len(condemned_files))

        for condemned_file in sorted(condemned_files, reverse=True):
            file_name, source_name, component_name = details[condemned_file]
            try:
                bytes += self._removeFile(
                    component_name, source_name, file_name)
            except NotInPool:
                # It's safe for us to let this slide because it means that
                # the file is already gone.
                self.logger.debug(
                    "File to remove %s %s/%s is not in pool, skipping" %
                    (component_name, source_name, file_name))
            except:
                self.logger.exception(
                    "Removing file %s %s/%s generated exception, continuing" %
                    (component_name, source_name, file_name))

        self.logger.info("Total bytes freed: %s" % bytes)

        return condemned_records

    def _markPublicationRemoved(self, condemned_records):
        # Now that the os.remove() calls have been made, simply let every
        # now out-of-date record be marked as removed.
        self.logger.debug("Marking %s condemned packages as removed." %
                          len(condemned_records))
        for record in condemned_records:
            record.status = PackagePublishingStatus.REMOVED
            record.dateremoved = UTC_NOW

