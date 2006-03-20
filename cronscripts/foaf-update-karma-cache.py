#!/usr/bin/env python
# Copyright 2005-2006 Canonical Ltd.  All rights reserved.

import _pythonpath

import sys
from optparse import OptionParser

from zope.component import getUtility

from canonical.config import config
from canonical.lp import initZopeless, AUTOCOMMIT_ISOLATION
from canonical.launchpad.scripts import (
        execute_zcml_for_scripts, logger_options, logger
        )
from canonical.launchpad.scripts.lockfile import LockFile
from canonical.launchpad.interfaces import IPersonSet
from canonical.database.sqlbase import connect

_default_lock_file = '/var/lock/launchpad-karma-update.lock'


def update_karma_cache():
    """Update the KarmaCache table for all valid Launchpad users.

    For each Launchpad user with a preferred email address, calculate his
    karmavalue for each category of actions we have and update his entry in
    the KarmaCache table. If a user doesn't have an entry for that category in
    KarmaCache a new one will be created.
    """
    # We use the autocommit transaction isolation level to minimize
    # contention, and also allows us to not bother explicitly calling
    # COMMIT all the time. This script in no way relies on transactions,
    # so it is safe.
    ztm = initZopeless(
            dbuser=config.karmacacheupdater.dbuser,
            implicitBegin=False, isolation=AUTOCOMMIT_ISOLATION
            )
    con = connect(config.karmacacheupdater.dbuser)
    con.set_isolation_level(AUTOCOMMIT_ISOLATION)
    cur = con.cursor()
    karma_expires_after = '1 year'

    # Calculate everyones karma. Karma degrades each day, becoming
    # worthless after karma_expires_after. This query produces odd results
    # when datecreated is in the future, but there is really no point adding
    # the extra WHEN clause.
    log.info("Calculating everyones karma")
    cur.execute("""
        SELECT person, category, ROUND(SUM(
            CASE WHEN datecreated + %(karma_expires_after)s::interval
                <= CURRENT_TIMESTAMP AT TIME ZONE 'UTC' THEN 0
            ELSE points * (1 - extract(
                EPOCH FROM CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - datecreated
                ) / extract(EPOCH FROM %(karma_expires_after)s::interval))
            END
            ))
        FROM Karma, KarmaAction
        WHERE action = KarmaAction.id
        GROUP BY person, category
        """, vars())

    # Suck into RAM to avoid tieing up resources on the DB.
    results = list(cur.fetchall())

    log.info("Got %d (person, category) scores", len(results))

    # Get a list of categories, which we will need shortly.
    categories = {}
    cur.execute("SELECT id, name from KarmaCategory")
    for id, name in cur.fetchall():
        categories[id] = name

    # Calculate normalization factor for each category. We currently have
    # category bloat, where translators dominate the top karma rankings.
    # By calculating a scaling factor automatically, this slant will be
    # removed even as more events are added or scoring tweaked.
    totals = {} # Total points per category
    for person, category, points in results:
        try:
            totals[category] += points
        except KeyError:
            totals[category] = points
    largest_total = max(totals.values())
    scaling = {} # Scaling factor to apply per category
    for category, total in totals.items():
        scaling[category] = float(largest_total) / float(total)
        log.info('Scaling %s by a factor of %0.4f' % (
            categories[category], scaling[category]
            ))

    # Note that we don't need to commit each iteration because we are running
    # in autocommit mode.
    for person, category, points in results:
        points *= scaling[category] # Scaled
        log.debug(
            "Setting person=%(person)d, category=%(category)d, "
            "points=%(points)d", vars()
            )

        if points <= 0:
            # Don't allow our table to bloat with inactive users
            cur.execute("""
                DELETE FROM KarmaCache WHERE
                person=%(person)s AND category=%(category)s
                """, vars())
        else:
            # Attempt to UPDATE. If no rows modified, perform an INSERT
            cur.execute("""
                UPDATE KarmaCache SET karmavalue=%(points)s
                WHERE person=%(person)s AND category=%(category)s
                """, vars())
            assert cur.rowcount in (0, 1), \
                    'Bad rowcount %r returned from DML' % (cur.rowcount,)
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO KarmaCache (person, category, karmavalue)
                    VALUES (%(person)s, %(category)s, %(points)s)
                    """, vars())

    # VACUUM KarmaCache since we have just touched every record in it
    cur.execute("""VACUUM KarmaCache""")

    # Update the KarmaTotalCache table
    log.info("Rebuilding KarmaTotalCache")
    # Trash old records
    cur.execute("""
        DELETE FROM KarmaTotalCache
        WHERE person NOT IN (SELECT person FROM KarmaCache)
        """)
    # Update existing records
    cur.execute("""
        UPDATE KarmaTotalCache SET karma_total=sum_karmavalue
        FROM (
            SELECT person AS sum_person, SUM(karmavalue) AS sum_karmavalue
            FROM KarmaCache GROUP BY person
            ) AS sums
        WHERE KarmaTotalCache.person = sum_person
        """)

    # VACUUM KarmaTotalCache since we have just touched every row in it.
    cur.execute("""VACUUM KarmaTotalCache""")

    # Insert new records into the KarmaTotalCache table. If deadlocks
    # become a problem, first LOCK the corresponding rows in the Person table
    # so the bulk insert cannot fail. We don't bother at the moment as this
    # would involve granting UPDATE rights on the Person table to the
    # karmacacheupdater user.
    ## cur.execute("BEGIN")
    ## cur.execute("""
    ##     SELECT * FROM Person
    ##     WHERE id NOT IN (SELECT person FROM KarmaTotalCache)
    ##     FOR UPDATE
    ##     """)
    cur.execute("""
        INSERT INTO KarmaTotalCache (person, karma_total)
        SELECT person, SUM(karmavalue) FROM KarmaCache
        WHERE person NOT IN (SELECT person FROM KarmaTotalCache)
        GROUP BY person
        """)
    ## cur.execute("COMMIT")


if __name__ == '__main__':
    parser = OptionParser()
    logger_options(parser)
    (options, arguments) = parser.parse_args()
    if arguments:
        parser.error("Unhandled arguments %s" % repr(arguments))
    execute_zcml_for_scripts()

    log = logger(options, 'karmacache')
    log.info("Updating the karma cache of Launchpad users.")

    lockfile = LockFile(_default_lock_file, logger=log)
    try:
        lockfile.acquire()
    except OSError:
        log.info("lockfile %s already exists, exiting", _default_lock_file)
        sys.exit(1)

    try:
        update_karma_cache()
    finally:
        lockfile.release()

    log.info("Finished updating the karma cache of Launchpad users.")

