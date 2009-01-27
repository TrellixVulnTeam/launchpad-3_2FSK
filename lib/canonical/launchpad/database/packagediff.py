# Copyright 2004-2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'PackageDiff',
    'PackageDiffSet',
    ]

import gzip
import os
import shutil
import subprocess
import tempfile

from sqlobject import ForeignKey
from storm.expr import Desc, In
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.interfaces.packagediff import (
    IPackageDiff, IPackageDiffSet, PackageDiffStatus)
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)
from canonical.librarian.utils import copy_and_close


def perform_deb_diff(tmp_dir, out_filename, from_files, to_files):
    """Perform a (deb)diff on two packages.

    A debdiff will be invoked on the files associated with the
    two packages to be diff'ed. The resulting output will be a tuple
    containing the process return code and the STDERR output.

    :param tmp_dir: The temporary directory with the package files.
    :type tmp_dir: ``str``
    :param out_filename: The name of the file that will hold the
        resulting debdiff output.
    :type tmp_dir: ``str``
    :param from_files: A list with the names of the files associated
        with the first package.
    :type from_files: ``list``
    :param to_files: A list with the names of the files associated
        with the second package.
    :type to_files: ``list``
    """
    compressed_bytes = -1
    [from_dsc] = [name for name in from_files
                  if name.lower().endswith('.dsc')]
    [to_dsc] = [name for name in to_files
                if name.lower().endswith('.dsc')]
    args = ['debdiff', from_dsc, to_dsc]

    full_path = os.path.join(tmp_dir, out_filename)
    out_file = None
    try:
        out_file = open(full_path, 'w')
        process = subprocess.Popen(
            args, stdout=out_file, stderr=subprocess.PIPE, cwd=tmp_dir)
        stdout, stderr = process.communicate()
    finally:
        if out_file is not None:
            out_file.close()

    return process.returncode, stderr


def download_file(destination_path, libraryfile):
    """Download a file from the librarian to the destination path.

    :param destination_path: Absolute destination path (where the
        file should be downloaded to).
    :type destination_path: ``str``
    :param libraryfile: The librarian file that is to be downloaded.
    :type libraryfile: ``LibraryFileAlias``
    """
    libraryfile.open()
    destination_file = open(destination_path, 'w')
    copy_and_close(libraryfile, destination_file)


class PackageDiff(SQLBase):
    """A Package Diff request."""

    implements(IPackageDiff)

    _defaultOrder = ['id']

    date_requested = UtcDateTimeCol(notNull=False, default=UTC_NOW)

    requester = ForeignKey(
        dbName='requester', foreignKey='Person', notNull=True)

    from_source = ForeignKey(
        dbName="from_source", foreignKey='SourcePackageRelease', notNull=True)

    to_source = ForeignKey(
        dbName="to_source", foreignKey='SourcePackageRelease', notNull=True)

    date_fulfilled = UtcDateTimeCol(notNull=False, default=None)

    diff_content = ForeignKey(
        dbName="diff_content", foreignKey='LibraryFileAlias',
        notNull=False, default=None)

    status = EnumCol(
        dbName='status', notNull=True, schema=PackageDiffStatus,
        default=PackageDiffStatus.PENDING)

    @property
    def title(self):
        """See `IPackageDiff`."""
        ancestry_archive = self.from_source.upload_archive
        if ancestry_archive == self.to_source.upload_archive:
            ancestry_identifier = self.from_source.version
        else:
            ancestry_identifier = "%s (in %s)" % (
                self.from_source.version,
                ancestry_archive.distribution.name.capitalize())
        return '%s to %s' % (ancestry_identifier, self.to_source.version)

    @property
    def private(self):
        """See `IPackageDiff`."""
        return self.to_source.upload_archive.private

    def performDiff(self):
        """See `IPackageDiff`.

        This involves creating a temporary directory, downloading the files
        from both SPRs involved from the librarian, running debdiff, storing
        the output in the librarian and updating the PackageDiff record.
        """
        # Create the temporary directory where the files will be
        # downloaded to and where the debdiff will be performed.
        tmp_dir = tempfile.mkdtemp()

        try:
            directions = ('from', 'to')

            # Keep track of the files belonging to the respective packages.
            downloaded = dict(zip(directions, ([], [])))

            # Please note that packages may have files in common.
            files_seen = []

            # Make it easy to iterate over packages.
            packages = dict(
                zip(directions, (self.from_source, self.to_source)))

            # Iterate over the packages to be diff'ed.
            for direction, package in packages.iteritems():
                # Create distinct directory locations for
                # 'from' and 'to' files.
                absolute_path = os.path.join(tmp_dir, direction)
                os.makedirs(absolute_path)

                # Download the files associated with each package in
                # their corresponding relative location.
                for file in package.files:
                    the_name = file.libraryfile.filename
                    relative_location = os.path.join(direction, the_name)
                    downloaded[direction].append(relative_location)
                    destination_path = os.path.join(absolute_path, the_name)
                    download_file(destination_path, file.libraryfile)

            # All downloads are done. Construct the name of the resulting
            # diff file.
            result_filename = '%s_%s_%s.diff' % (
                self.from_source.sourcepackagename.name,
                self.from_source.version,
                self.to_source.version)

            # Perform the actual diff operation.
            return_code, stderr = perform_deb_diff(
                tmp_dir, result_filename, downloaded['from'],
                downloaded['to'])

            # `debdiff` failed, mark the package diff request accordingly
            # and return.
            if return_code != 0:
                self.status = PackageDiffStatus.FAILED
                return

            # Compress the generated diff.
            out_file = open(os.path.join(tmp_dir, result_filename))
            gzip_result_filename = result_filename + '.gz'
            gzip_file_path = os.path.join(tmp_dir, gzip_result_filename)
            gzip_file = gzip.GzipFile(gzip_file_path, mode='wb')
            copy_and_close(out_file, gzip_file)

            # Calculate the compressed size.
            gzip_size = os.path.getsize(gzip_file_path)

            # Upload the compressed diff to librarian and update
            # the package diff request.
            gzip_file = open(gzip_file_path)
            try:
                librarian_set = getUtility(ILibraryFileAliasSet)
                self.diff_content = librarian_set.create(
                    gzip_result_filename, gzip_size, gzip_file,
                    'application/gzipped-patch', restricted=self.private)
            finally:
                gzip_file.close()

            # Last but not least, mark the diff as COMPLETED.
            self.date_fulfilled = UTC_NOW
            self.status = PackageDiffStatus.COMPLETED
        finally:
            shutil.rmtree(tmp_dir)


class PackageDiffSet:
    """This class is to deal with Distribution related stuff"""

    implements(IPackageDiffSet)

    def __iter__(self):
        """See `IPackageDiffSet`."""
        return iter(PackageDiff.select(orderBy=['-id']))

    def get(self, diff_id):
        """See `IPackageDiffSet`."""
        return PackageDiff.get(diff_id)

    def getPendingDiffs(self, limit=None):
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result = store.find(
            PackageDiff, PackageDiff.status == PackageDiffStatus.PENDING)
        result.order_by(PackageDiff.id)
        return result.config(limit=limit)

    def getDiffsToReleases(self, sprs):
        """See `IPackageDiffSet`."""
        if len(sprs) == 0:
            return EmptyResultSet()
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        spr_ids = [spr.id for spr in sprs]
        result = store.find(PackageDiff, In(PackageDiff.to_sourceID, spr_ids))
        result.order_by(PackageDiff.to_sourceID,
                        Desc(PackageDiff.date_requested))
        return result
