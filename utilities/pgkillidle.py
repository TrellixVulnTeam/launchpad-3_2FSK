#!/usr/bin/python2.4
# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Kill <IDLE> in transaction connections that have hung around for too long.
"""

__metaclass__ = type
__all__ = []


from optparse import OptionParser
import os
import psycopg2
import signal
import sys


def main():
    parser = OptionParser()
    parser.add_option(
        '-c', '--connection', type='string', dest='connect_string',
        default='', help="Psycopg connection string",
        )
    parser.add_option(
        '-s', '--max-idle-seconds', type='int',
        dest='max_idle_seconds', default=10*60,
        help='Maximum seconds time idle but open transactions are allowed',
        )
    parser.add_option(
        '-q', '--quiet', action='store_true', dest="quiet",
        default=False, help='Silence output',
        )
    parser.add_option(
        '-n', '--dry-run', action='store_true', default=False,
        dest='dryrun', help="Dry run - don't kill anything",
        )
    parser.add_option(
        '-i', '--ignore', action='append', dest='ignore',
        help='Ignore connections by USER', metavar='USER')
    options, args = parser.parse_args()
    if len(args) > 0:
        parser.error('Too many arguments')

    ignore_sql = ' AND usename <> %s' * len(options.ignore or [])

    con = psycopg2.connect(options.connect_string)
    cur = con.cursor()
    cur.execute("""
        SELECT usename, procpid, backend_start, query_start
        FROM pg_stat_activity
        WHERE current_query = '<IDLE> in transaction'
            AND query_start < CURRENT_TIMESTAMP - '%d seconds'::interval %s
        ORDER BY procpid
        """ % (options.max_idle_seconds, ignore_sql), options.ignore)

    rows = cur.fetchall()

    if len(rows) == 0:
        if not options.quiet:
            print 'No IDLE transactions to kill'
            return 0

    for usename, procpid, backend_start, query_start in rows:
        print 'Killing %d, %s, %s' % (
            procpid, backend_start, query_start,
            )
        if not options.dryrun:
            os.kill(procpid, signal.SIGTERM)
    return 0


if __name__ == '__main__':
    sys.exit(main())
