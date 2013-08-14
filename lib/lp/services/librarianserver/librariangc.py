# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Librarian garbage collection routines"""

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
import errno
import os
import re
import sys
from time import time

from swiftclient import client as swiftclient
from zope.interface import implements

from lp.services.config import config
from lp.services.database.postgresql import (
    drop_tables,
    listReferences,
    quoteIdentifier,
    )
from lp.services.features import getFeatureFlag
from lp.services.librarianserver import swift
from lp.services.librarianserver.storage import (
    _relFileLocation as relative_file_path,
    )
from lp.services.looptuner import (
    DBLoopTuner,
    ITunableLoop,
    )


log = None  # This is set by cronscripts/librarian-gc.py
debug = False


STREAM_CHUNK_SIZE = 64 * 1024


def file_exists(content_id):
    """True if the file exists either on disk or in Swift.

    Swift is only checked if the librarian.swift.enabled feature flag
    is set.
    """
    swift_enabled = getFeatureFlag('librarian.swift.enabled') or False
    if swift_enabled:
        swift_connection = swift.connection_pool.get()
        container, name = swift.swift_location(content_id)
        try:
            swift_connection.head_object(container, name)
            return True
        except swiftclient.ClientException as x:
            if x.http_status != 404:
                raise
            swift.connection_pool.put(swift_connection)
    return os.path.exists(get_file_path(content_id))


def open_stream(content_id):
    """Return an open file for the given content_id.

    Returns None if the file cannot be found.
    """
    swift_enabled = getFeatureFlag('librarian.swift.enabled') or False
    if swift_enabled:
        try:
            swift_connection = swift.connection_pool.get()
            container, name = swift.swift_location(content_id)
            chunks = swift_connection.get_object(
                container, name, resp_chunk_size=STREAM_CHUNK_SIZE)[1]
            return swift.SwiftStream(swift_connection, chunks)
        except swiftclient.ClientException as x:
            if x.http_status != 404:
                raise
    path = get_file_path(content_id)
    if os.path.exists(path):
        return open(path, 'rb')

    return None  # File not found.


def same_file(content_id_1, content_id_2):
    file1 = open_stream(content_id_1)
    file2 = open_stream(content_id_2)

    chunks_iter = iter(
        lambda: (file1.read(STREAM_CHUNK_SIZE), file2.read(STREAM_CHUNK_SIZE)),
        ('', ''))
    for chunk1, chunk2 in chunks_iter:
        if chunk1 != chunk2:
            return False
    return True


def confirm_no_clock_skew(con):
    """Raise an exception if there is significant clock skew between the
    database and this machine.

    It is theoretically possible to lose data if there is more than several
    hours of skew.
    """
    cur = con.cursor()
    cur.execute("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")
    db_now = cur.fetchone()[0]
    local_now = datetime.utcnow()
    five_minutes = timedelta(minutes=5)

    if -five_minutes < local_now - db_now < five_minutes:
        return
    else:
        raise Exception("%s clock skew between librarian and database" % (
            local_now - db_now,
            ))


def delete_expired_blobs(con):
    """Remove expired TemporaryBlobStorage entries and their corresponding
       LibraryFileAlias entries.

       We delete the LibraryFileAliases here as the default behavior of the
       garbage collector could leave them hanging around indefinitely.

       We also delete any linked ApportJob and Job records here.
    """
    cur = con.cursor()

    # Generate the list of expired blobs.
    cur.execute("""
        SELECT file_alias
        INTO TEMPORARY TABLE BlobAliasesToDelete
        FROM LibraryFileAlias, TemporaryBlobStorage
        WHERE file_alias = LibraryFileAlias.id
            AND expires < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
        """)

    # Generate the list of expired Jobs. We ignore jobs that have not
    # finished.
    cur.execute("""
        SELECT job
        INTO TEMPORARY TABLE JobsToDelete
        FROM Job, ApportJob, TemporaryBlobStorage, LibraryFileAlias
        WHERE
            ApportJob.blob = TemporaryBlobStorage.id
            AND Job.id = ApportJob.job
            AND Job.date_finished < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            AND TemporaryBlobStorage.file_alias = LibraryFileAlias.id
                AND expires < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
        """)

    # Delete expired ApportJob records.
    cur.execute("""
        DELETE FROM ApportJob
        USING JobsToDelete
        WHERE ApportJob.job = JobsToDelete.job
        """)

    # Delete expired Job records.
    cur.execute("""
        DELETE FROM Job
        USING JobsToDelete
        WHERE Job.id = JobsToDelete.job
        """)

    # Delete expired blobs.
    cur.execute("""
        DELETE FROM TemporaryBlobStorage
        USING BlobAliasesToDelete
        WHERE TemporaryBlobStorage.file_alias = BlobAliasesToDelete.file_alias
        """)

    # Delete LibraryFileAliases referencing expired blobs.
    cur.execute("""
        DELETE FROM LibraryFileAlias
        USING BlobAliasesToDelete
        WHERE file_alias = LibraryFileAlias.id
        """)
    log.info("Removed %d expired blobs" % cur.rowcount)
    con.commit()


def merge_duplicates(con):
    """Merge duplicate LibraryFileContent rows

    This is the first step in a full garbage collection run. We assume files
    are identical if their sha1 hashes and filesizes are identical. For every
    duplicate detected, we make all LibraryFileAlias entries point to one of
    them and delete the unnecessary duplicates from the filesystem and the
    database.
    """

    # Get a list of all (sha1, filesize) that are duplicated in
    # LibraryFileContent
    cur = con.cursor()
    cur.execute("""
        SELECT sha1, filesize
        FROM LibraryFileContent
        GROUP BY sha1, filesize
        HAVING COUNT(*) > 1
        """)
    rows = list(cur.fetchall())

    # Merge the duplicate entries, each one in a separate transaction
    for sha1, filesize in rows:
        cur = con.cursor()

        sha1 = sha1.encode('US-ASCII')  # Can't pass Unicode to execute (yet)

        # Get a list of our dupes. Where multiple files exist, we return
        # the most recently added one first, because this is the version
        # most likely to exist on the staging server (it should be
        # irrelevant on production).
        cur.execute("""
            SELECT id
            FROM LibraryFileContent
            WHERE sha1=%(sha1)s AND filesize=%(filesize)s
            ORDER BY datecreated DESC
            """, vars())
        dupes = [row[0] for row in cur.fetchall()]

        if debug:
            log.debug("Found duplicate LibraryFileContents")
            # Spit out more info in case it helps work out where
            # dupes are coming from.
            for dupe_id in dupes:
                cur.execute("""
                    SELECT id, filename, mimetype FROM LibraryFileAlias
                    WHERE content = %(dupe_id)s
                    """, vars())
                for id, filename, mimetype in cur.fetchall():
                    log.debug("> %d %s %s" % (id, filename, mimetype))

        # Make sure the first file exists on disk. Don't merge if it
        # doesn't. This shouldn't happen on production, so we don't try
        # and cope - just report and skip. However, on staging this will
        # be more common because database records has been synced from
        # production but the actual librarian contents has not.
        dupe1_id = dupes[0]
        if not file_exists(dupe1_id):
            if config.instance_name == 'staging':
                log.debug(
                        "LibraryFileContent %d data is missing", dupe1_id)
            else:
                log.warning(
                        "LibraryFileContent %d data is missing", dupe1_id)
            continue

        # Do a manual check that they really are identical, because we
        # employ paranoids. And we might as well cope with someone breaking
        # SHA1 enough that it becomes possible to create a SHA1 collision
        # with an identical filesize to an existing file. Which is pretty
        # unlikely. Where did I leave my tin foil hat?
        for dupe2_id in (dupe for dupe in dupes[1:]):
            # Check paths exist, because on staging they may not!
            if (file_exists(dupe2_id) and not same_file(dupe1_id, dupe2_id)):
                log.error(
                        "SHA-1 collision found. LibraryFileContent %d and "
                        "%d have the same SHA1 and filesize, but are not "
                        "byte-for-byte identical.",
                        dupe1_id, dupe2_id
                        )
                sys.exit(1)

        # Update all the LibraryFileAlias entries to point to a single
        # LibraryFileContent
        prime_id = dupes[0]
        other_ids = ', '.join(str(dupe) for dupe in dupes[1:])
        log.debug(
            "Making LibraryFileAliases referencing %s reference %s instead",
            other_ids, prime_id
            )
        for other_id in dupes[1:]:
            cur.execute("""
                UPDATE LibraryFileAlias SET content=%(prime_id)s
                WHERE content = %(other_id)s
                """, vars())

        log.debug("Committing")
        con.commit()


class ExpireAliases:
    """Expire expired LibraryFileAlias records.

    This simply involves setting the LibraryFileAlias.content to NULL.
    Unreferenced LibraryFileContent records are cleaned up elsewhere.
    """
    implements(ITunableLoop)

    def __init__(self, con):
        self.con = con
        self.total_expired = 0
        self._done = False

    def isDone(self):
        if self._done:
            log.info(
                "Expired %d LibraryFileAlias records." % self.total_expired)
            return True
        else:
            return False

    def __call__(self, chunksize):
        chunksize = int(chunksize)
        cur = self.con.cursor()
        cur.execute("""
            UPDATE LibraryFileAlias
            SET content=NULL
            WHERE id IN (
                SELECT id FROM LibraryFileAlias
                WHERE
                    content IS NOT NULL
                    AND expires < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                        - interval '1 week'
                LIMIT %d)
            """ % chunksize)
        self.total_expired += cur.rowcount
        if cur.rowcount == 0:
            self._done = True
        else:
            log.debug("Expired %d LibraryFileAlias records." % cur.rowcount)
        self.con.commit()


def expire_aliases(con):
    """Invoke ExpireLibraryFileAliases."""
    loop_tuner = DBLoopTuner(ExpireAliases(con), 5, log=log)
    loop_tuner.run()


class UnreferencedLibraryFileAliasPruner:
    """Delete unreferenced LibraryFileAliases.

    The LibraryFileContent records are left untouched for the code that
    knows how to delete them and the corresponding files on disk.

    This is the second step in a full garbage collection sweep. We determine
    which LibraryFileAlias entries are not being referenced by other objects
    in the database and delete them, if they are expired (expiry in the past
    or NULL).
    """
    implements(ITunableLoop)

    def __init__(self, con):
        self.con = con  # Database connection to use
        self.total_deleted = 0  # Running total
        self.index = 1

        log.info("Deleting unreferenced LibraryFileAliases")

        cur = con.cursor()

        drop_tables(cur, "ReferencedLibraryFileAlias")
        cur.execute("""
            CREATE TEMPORARY TABLE ReferencedLibraryFileAlias (
                alias integer)
            """)

        # Determine what columns link to LibraryFileAlias
        # references = [(table, column), ...]
        references = [
            tuple(ref[:2])
            for ref in listReferences(cur, 'libraryfilealias', 'id')
            if ref[0] != 'libraryfiledownloadcount'
            ]
        assert len(references) > 10, (
            'Database introspection returned nonsense')
        log.debug(
            "Found %d columns referencing LibraryFileAlias", len(references))

        # Find all relevant LibraryFileAlias references and fill in
        # ReferencedLibraryFileAlias
        for table, column in references:
            cur.execute("""
                INSERT INTO ReferencedLibraryFileAlias
                SELECT LibraryFileAlias.id
                FROM LibraryFileAlias, %(table)s
                WHERE LibraryFileAlias.id = %(table)s.%(column)s
                """ % {
                    'table': quoteIdentifier(table),
                    'column': quoteIdentifier(column)})
            log.debug("%s.%s references %d LibraryFileContent rows." % (
                table, column, cur.rowcount))
            con.commit()

        log.debug("Calculating unreferenced LibraryFileAlias set.")
        drop_tables(cur, "UnreferencedLibraryFileAlias")
        cur.execute("""
            CREATE TEMPORARY TABLE UnreferencedLibraryFileAlias (
                id serial PRIMARY KEY,
                alias integer UNIQUE)
            """)
        # Calculate the set of unreferenced LibraryFileAlias.
        # We also exclude all unexpired records - we don't remove them
        # even if they are unlinked. We currently don't remove stuff
        # until it has been expired for more than one week, but we will
        # change this if disk space becomes short and it actually will
        # make a noticeable difference. We handle excluding recently
        # created content here rather than earlier when creating the
        # ReferencedLibraryFileAlias table to handle uploads going on
        # while this script is running.
        cur.execute("""
            INSERT INTO UnreferencedLibraryFileAlias (alias)
            SELECT id AS alias FROM LibraryFileAlias
            WHERE
                content IS NULL
                OR ((expires IS NULL OR
                     expires <
                         CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                             - interval '1 week'
                    )
                    AND date_created <
                        CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                            - interval '1 week'
                   )
            EXCEPT
            SELECT alias FROM ReferencedLibraryFileAlias
            """)
        con.commit()
        drop_tables(cur, "ReferencedLibraryFileAlias")
        cur.execute(
            "SELECT COALESCE(max(id),0) FROM UnreferencedLibraryFileAlias")
        self.max_id = cur.fetchone()[0]
        log.debug(
            "%d unreferenced LibraryFileContent to remove." % self.max_id)
        con.commit()

    def isDone(self):
        if self.index > self.max_id:
            log.info(
                "Deleted %d LibraryFileAlias records." % self.total_deleted)
            return True
        else:
            return False

    def __call__(self, chunksize):
        chunksize = int(chunksize)
        cur = self.con.cursor()
        cur.execute("""
            DELETE FROM LibraryFileAlias
            WHERE id IN
                (SELECT alias FROM UnreferencedLibraryFileAlias
                WHERE id BETWEEN %s AND %s)
            """, (self.index, self.index + chunksize - 1))
        deleted_rows = cur.rowcount
        self.total_deleted += deleted_rows
        log.debug("Deleted %d LibraryFileAlias records." % deleted_rows)
        self.con.commit()
        self.index += chunksize


def delete_unreferenced_aliases(con):
    "Run the UnreferencedLibraryFileAliasPruner."
    loop_tuner = DBLoopTuner(
        UnreferencedLibraryFileAliasPruner(con), 5, log=log)
    loop_tuner.run()


class UnreferencedContentPruner:
    """Delete LibraryFileContent entries and their disk files that are
    not referenced by any LibraryFileAlias entries.

    Note that a LibraryFileContent can only be accessed through a
    LibraryFileAlias, so all entries in this state are garbage.
    """
    implements(ITunableLoop)

    def __init__(self, con):
        self.swift_enabled = getFeatureFlag(
            'librarian.swift.enabled') or False
        self.con = con
        self.index = 1
        self.total_deleted = 0
        cur = con.cursor()
        drop_tables(cur, "UnreferencedLibraryFileContent")
        cur.execute("""
            CREATE TEMPORARY TABLE UnreferencedLibraryFileContent (
                id serial PRIMARY KEY,
                content integer UNIQUE)
            """)
        cur.execute("""
            INSERT INTO UnreferencedLibraryFileContent (content)
            SELECT DISTINCT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = LibraryFileAlias.content
            WHERE LibraryFileAlias.content IS NULL
        """)
        cur.execute("""
            SELECT COALESCE(max(id), 0) FROM UnreferencedLibraryFileContent
            """)
        self.max_id = cur.fetchone()[0]
        log.debug(
            "%d unreferenced LibraryFileContent rows to remove."
            % self.max_id)

    def isDone(self):
        if self.index > self.max_id:
            log.info("Deleted %d unreferenced files." % self.total_deleted)
            return True
        else:
            return False

    def __call__(self, chunksize):
        chunksize = int(chunksize)

        cur = self.con.cursor()

        # Delete unreferenced LibraryFileContent entries.
        cur.execute("""
            DELETE FROM LibraryFileContent
            USING (
                SELECT content FROM UnreferencedLibraryFileContent
                WHERE id BETWEEN %s AND %s) AS UnreferencedLibraryFileContent
            WHERE
                LibraryFileContent.id = UnreferencedLibraryFileContent.content
            """, (self.index, self.index + chunksize - 1))
        rows_deleted = cur.rowcount
        self.total_deleted += rows_deleted
        self.con.commit()

        # Remove files from disk. We do this outside the transaction,
        # as the garbage collector happily deals with files that exist
        # on disk but not in the DB.
        cur.execute("""
            SELECT content FROM UnreferencedLibraryFileContent
            WHERE id BETWEEN %s AND %s
            """, (self.index, self.index + chunksize - 1))
        for content_id in (row[0] for row in cur.fetchall()):
            removed = []

            # Remove the file from disk, if it hasn't already been.
            path = get_file_path(content_id)
            try:
                os.unlink(path)
                removed.append('filesystem')
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

            # Remove the file from Swift, if it hasn't already been.
            if self.swift_enabled:
                container, name = swift.swift_location(content_id)
                with swift.connection() as swift_connection:
                    try:
                        swift_connection.delete_object(container, name)
                        removed.append('Swift')
                    except swiftclient.ClientException as x:
                        if x.http_status != 404:
                            raise

            if removed:
                log.debug(
                    "Deleted %s from %s", content_id, ' & '.join(removed))

            elif config.librarian_server.upstream_host is None:
                # It is normal to have files in the database that
                # are not on disk if the Librarian has an upstream
                # Librarian, such as on staging. Don't annoy the
                # operator with noise in this case.
                log.info("%s already deleted", path)
        self.con.rollback()

        self.index += chunksize


def delete_unreferenced_content(con):
    """Invoke UnreferencedContentPruner."""
    loop_tuner = DBLoopTuner(UnreferencedContentPruner(con), 5, log=log)
    loop_tuner.run()


def delete_unwanted_files(con):
    delete_unwanted_disk_files(con)
    swift_enabled = getFeatureFlag('librarian.swift.enabled') or False
    if swift_enabled:
        delete_unwanted_swift_files(con)


def delete_unwanted_disk_files(con):
    """Delete files found on disk that have no corresponding record in the
    database.

    Files will only be deleted if they were created more than one day ago
    to avoid deleting files that have just been uploaded but have yet to have
    the database records committed.
    """
    swift_enabled = getFeatureFlag('librarian.swift.enabled') or False

    cur = con.cursor()

    # Calculate all stored LibraryFileContent ids that we want to keep.
    # Results are ordered so we don't have to suck them all in at once.
    cur.execute("""
        SELECT id FROM LibraryFileContent ORDER BY id
        """)

    def get_next_wanted_content_id():
        result = cur.fetchone()
        if result is None:
            return None
        else:
            return result[0]

    removed_count = 0
    content_id = next_wanted_content_id = -1

    hex_content_id_re = re.compile('^[0-9a-f]{8}$')
    ONE_DAY = 24 * 60 * 60

    for dirpath, dirnames, filenames in os.walk(
        get_storage_root(), followlinks=True):

        # Ignore known and harmless noise in the Librarian storage area.
        if 'incoming' in dirnames:
            dirnames.remove('incoming')
        if 'lost+found' in dirnames:
            dirnames.remove('lost+found')
        filenames = set(filenames)
        filenames.discard('librarian.pid')
        filenames.discard('librarian.log')

        for dirname in dirnames[:]:
            if len(dirname) != 2:
                dirnames.remove(dirname)
                log.warning(
                    "Ignoring directory %s that shouldn't be here" % dirname)
                continue
            try:
                int(dirname, 16)
            except ValueError:
                dirnames.remove(dirname)
                log.warning("Ignoring invalid directory %s" % dirname)

        # We need everything in order to ensure we visit files in the
        # same order we retrieve wanted files from the database.
        dirnames.sort()
        filenames = sorted(filenames)

        # Noise in the storage area, or maybe we are looking at the wrong
        # path?
        if dirnames and filenames:
            log.warning(
                "%s contains both files %r and subdirectories %r. Skipping."
                % (dirpath, filenames, dirnames))
            continue

        for filename in filenames:
            path = os.path.join(dirpath, filename)
            hex_content_id = ''.join(path.split(os.sep)[-4:])
            if hex_content_id_re.search(hex_content_id) is None:
                log.warning(
                    "Ignoring invalid path %s" % path)
                continue

            content_id = int(hex_content_id, 16)

            while (next_wanted_content_id is not None
                    and content_id > next_wanted_content_id):

                next_wanted_content_id = get_next_wanted_content_id()

                if (config.librarian_server.upstream_host is None
                        and not swift_enabled  # Maybe the file is in Swift.
                        and next_wanted_content_id is not None
                        and next_wanted_content_id < content_id):
                    log.error(
                        "LibraryFileContent %d exists in the database but "
                        "was not found on disk." % next_wanted_content_id)

            file_wanted = (
                    next_wanted_content_id is not None
                    and next_wanted_content_id == content_id)

            if not file_wanted:
                if time() - os.path.getctime(path) < ONE_DAY:
                    log.debug(
                        "File %d not removed - created too recently"
                        % content_id)
                else:
                    # File uploaded a while ago but no longer wanted.
                    os.unlink(path)
                    log.debug("Deleted %s" % path)
                    removed_count += 1

    # Report any remaining LibraryFileContent that the database says
    # should exist but we didn't find on disk.
    if next_wanted_content_id == content_id:
        next_wanted_content_id = get_next_wanted_content_id()
    if not swift_enabled:
        while next_wanted_content_id is not None:
            log.error(
                "LibraryFileContent %d exists in the database but "
                "was not found on disk." % next_wanted_content_id)
            next_wanted_content_id = get_next_wanted_content_id()

    log.info(
            "Deleted %d files from disk that where no longer referenced "
            "in the db" % removed_count
            )


def swift_files():
    """Generate the (container, name) of all files stored in Swift.

    Results are yielded in numerical order.
    """
    with swift.connection() as swift_connection:
        try:
            container_num = 0
            while True:
                # We generate the container names, rather than query the
                # server, because the mock Swift implementation doesn't
                # support that operation.
                container = swift.SWIFT_CONTAINER_PREFIX + str(container_num)
                names = sorted(
                    swift_connection.get_container(
                        container, full_listing=True), key=int)
                for name in names:
                    yield (container, name)
                container_num += 1
        except swiftclient.ClientException as x:
            if x.http_status == 404:
                return
            raise


def delete_unwanted_swift_files(con):
    """Delete files found in Swift that have no corresponding db record."""
    assert getFeatureFlag('librarian.swift.enabled')

    cur = con.cursor()

    # Calculate the largest LibraryFileContent id that we want to risk
    # removing. We don't want to remove anything that was uploaded less
    # than a day ago to avoid removing things currently in process of
    # being uploaded.
    cur.execute("""
        SELECT max(id) FROM LibraryFileContent
        WHERE datecreated < CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            - '1 day'::interval
        """)
    max_removable_content_id = cur.fetchone()[0]
    con.rollback()

    # Calculate all stored LibraryFileContent ids that we want to keep.
    # Results are ordered so we don't have to suck them all in at once.
    cur.execute("""
        SELECT id FROM LibraryFileContent ORDER BY id
        """)

    def get_next_wanted_content_id():
        result = cur.fetchone()
        if result is None:
            return None
        else:
            return result[0]

    removed_count = 0
    content_id = next_wanted_content_id = -1

    for container, name in swift_files():
        content_id = int(name)

        while (next_wanted_content_id is not None
            and content_id > next_wanted_content_id):

            next_wanted_content_id = get_next_wanted_content_id()

            if (config.librarian_server.upstream_host is None
                    and next_wanted_content_id is not None
                    and next_wanted_content_id < content_id
                    and not os.path.exists(
                        get_file_path(next_wanted_content_id))):
                log.error(
                    "LibraryFileContent %d exists in the database but "
                    "was not found on disk nor in Swift."
                    % next_wanted_content_id)

        file_wanted = (
            next_wanted_content_id is not None
            and next_wanted_content_id == content_id)

        if not file_wanted:
            if content_id > max_removable_content_id:
                log.debug(
                    "File %d not removed - created too recently", content_id)
            else:
                with swift.connection() as swift_connection:
                    swift_connection.delete_object(container, name)
                log.debug(
                    'Deleted ({}, {}) from Swift'.format(container, name))
                removed_count += 1

    if next_wanted_content_id == content_id:
        next_wanted_content_id = get_next_wanted_content_id()
    while next_wanted_content_id is not None:
        log.error(
            "LibraryFileContent {} exists in the database but was not "
            "found in Swift.".format(next_wanted_content_id))
        next_wanted_content_id = get_next_wanted_content_id()

    log.info(
        "Deleted {} files from Swift that where no longer referenced"
        "in the db".format(removed_count))


def get_file_path(content_id):
    """Return the physical file path to the matching LibraryFileContent id.
    """
    assert isinstance(content_id, (int, long)), (
        'Invalid content_id %s' % repr(content_id))
    return os.path.join(get_storage_root(), relative_file_path(content_id))


def get_storage_root():
    """Return the path to the root of the Librarian storage area.

    Performs some basic sanity checking to avoid accidents.
    """
    storage_root = config.librarian_server.root
    # Do a basic sanity check.
    assert os.path.isdir(os.path.join(storage_root, 'incoming')), (
        '%s is not a Librarian storage area' % storage_root)
    return storage_root
