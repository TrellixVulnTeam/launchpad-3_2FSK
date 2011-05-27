#!/usr/bin/python2.6 -S
# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Confirm the database systems are ready to be patched as best we can."""

import _pythonpath

from datetime import timedelta
from optparse import OptionParser
import sys

import psycopg2

from canonical.database.sqlbase import (
    connect,
    ISOLATION_LEVEL_AUTOCOMMIT,
    )
from canonical.launchpad.scripts import (
    db_options,
    logger,
    logger_options,
    )
from canonical import lp
import replication.helpers


# Ignore connections by these users.
SYSTEM_USERS = frozenset(['postgres', 'slony', 'nagios', 'lagmon'])

# How lagged the cluster can be before failing the preflight check.
MAX_LAG = timedelta(seconds=45)


class DatabasePreflight:
    def __init__(self, log, master_con):
        self.log = log
        self.is_replicated = replication.helpers.slony_installed(master_con)
        if self.is_replicated:
            self.nodes = set(
                replication.helpers.get_all_cluster_nodes(master_con))
            for node in self.nodes:
                node.con = psycopg2.connect(node.connection_string)
                node.con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        else:
            node = replication.helpers.Node(None, None, None, True)
            node.con = master_con
            self.nodes = set([node])

        # Create a list of nodes subscribed to the replicated sets we
        # are modifying.
        cur = master_con.cursor()
        cur.execute("""
            WITH subscriptions AS (
                SELECT *
                FROM _sl.sl_subscribe
                WHERE sub_set = 1 AND sub_active IS TRUE)
            SELECT sub_provider FROM subscriptions
            UNION
            SELECT sub_receiver FROM subscriptions
            """)
        lpmain_node_ids = set(row[0] for row in cur.fetchall())
        self.lpmain_nodes = set(
            node for node in self.nodes
            if node.node_id in lpmain_node_ids)

    def check_is_superuser(self):
        """Return True if all the node connections are as superusers."""
        success = True
        for node in self.nodes:
            cur = node.con.cursor()
            cur.execute("""
                SELECT current_database(), pg_user.usesuper
                FROM pg_user
                WHERE usename = current_user
                """)
            dbname, is_super = cur.fetchone()
            if is_super:
                self.log.debug("Connected to %s as a superuser.", dbname)
            else:
                self.log.fatal("Not connected to %s as a superuser.", dbname)
                success = False
        return success

    def check_open_connections(self):
        """False if any lpmain nodes have connections from non-system users.

        We only check on subscribed nodes, as there will be active systems
        connected to other nodes in the replication cluster (such as the
        SSO servers).

        System users are defined by SYSTEM_USERS.
        """
        success = True
        for node in self.lpmain_nodes:
            cur = node.con.cursor()
            cur.execute("""
                SELECT datname, usename, COUNT(*) AS num_connections
                FROM pg_stat_activity
                WHERE
                    datname=current_database()
                    AND procpid <> pg_backend_pid()
                GROUP BY datname, usename
                """)
            for datname, usename, num_connections in cur.fetchall():
                if usename in SYSTEM_USERS:
                    self.log.debug(
                        "%s has %d connections by %s",
                        datname, num_connections, usename)
                else:
                    self.log.fatal(
                        "%s has %d connections by %s",
                        datname, num_connections, usename)
                    success = False
        if success:
            self.log.info("Only system users connected to the cluster")
        return success

    def check_long_running_transactions(self, max_secs=10):
        """Return False if any nodes have long running transactions open.

        max_secs defines what is long running. For database rollouts,
        this will be short. Even if the transaction is benign like a
        autovacuum task, we should wait until things have settled down.
        """
        success = True
        for node in self.nodes:
            cur = node.con.cursor()
            cur.execute("""
                SELECT
                    datname, usename,
                    age(current_timestamp, xact_start) AS age, current_query
                FROM pg_stat_activity
                WHERE
                    age(current_timestamp, xact_start) > interval '%d secs'
                    AND datname=current_database()
                """ % max_secs)
            for datname, usename, age, current_query in cur.fetchall():
                self.log.fatal(
                    "%s has transaction by %s open %s",
                    datname, usename, age)
                success = False
        if success:
            self.log.info("No long running transactions detected.")
        return success

    def check_replication_lag(self):
        """Return False if the replication cluster is badly lagged."""
        if not self.is_replicated:
            self.log.debug("Not replicated - no replication lag.")
            return True

        # Check replication lag on every node just in case there are
        # disagreements.
        max_lag = timedelta(seconds=-1)
        max_lag_node = None
        for node in self.nodes:
            cur = node.con.cursor()
            cur.execute("""
                SELECT current_database(),
                max(st_lag_time) AS lag FROM _sl.sl_status
            """)
            dbname, lag = cur.fetchone()
            if lag > max_lag:
                max_lag = lag
                max_lag_node = node
            self.log.debug(
                "%s reports database lag of %s.", dbname, lag)
        if max_lag <= MAX_LAG:
            self.log.info("Database cluster lag is ok (%s)", max_lag)
            return True
        else:
            self.log.fatal("Database cluster lag is high (%s)", max_lag)
            return False

    def check_can_sync(self):
        """Return True if a sync event is acknowledged by all nodes.

        We only wait 30 seconds for the sync, because we require the
        cluster to be quiescent.
        """
        if self.is_replicated:
            success = replication.helpers.sync(30)
            if success:
                self.log.info(
                    "Replication events are being propagated.")
            else:
                self.log.fatal(
                    "Replication events are not being propagated.")
                self.log.fatal(
                    "One or more replication daemons may be down.")
                self.log.fatal(
                    "Bounce the replication daemons and check the logs.")
            return success
        else:
            return True

    def check_all(self):
        """Run all checks.

        If any failed, return False. Otherwise return True.
        """
        if not self.check_is_superuser():
            # No point continuing - results will be bogus without access
            # to pg_stat_activity
            return False

        success = True
        if not self.check_open_connections():
            success = False
        if not self.check_long_running_transactions():
            success = False
        if not self.check_replication_lag():
            success = False
        if not self.check_can_sync():
            success = False
        return success


def main():
    parser = OptionParser()
    db_options(parser)
    logger_options(parser)
    (options, args) = parser.parse_args()
    if args:
        parser.error("Too many arguments")

    log = logger(options)

    master_con = connect(lp.dbuser)
    master_con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    preflight_check = DatabasePreflight(log, master_con)

    if preflight_check.check_all():
        log.info('Preflight check succeeded. Good to go.')
        return 0
    else:
        log.error('Preflight check failed.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
