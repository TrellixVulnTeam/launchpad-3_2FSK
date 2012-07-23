#!/usr/bin/python2.6 -S
# Copyright 2011-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Confirm the database systems are ready to be patched as best we can."""

__all__ = [
    'DatabasePreflight',
    'KillConnectionsPreflight',
    'NoConnectionCheckPreflight',
    'streaming_sync',
    ]

import _pythonpath

from datetime import timedelta
from optparse import OptionParser
import os.path
import time

from lp.services.database.sqlbase import (
    connect,
    ISOLATION_LEVEL_AUTOCOMMIT,
    sqlvalues,
    )
from lp.services.scripts import (
    db_options,
    logger,
    logger_options,
    )
import replication.helpers
from replication.helpers import Node
import upgrade

# Ignore connections by these users.
SYSTEM_USERS = frozenset(['postgres', 'slony', 'nagios', 'lagmon'])

# Fail checks if these users are connected. If a process should not be
# interrupted by a rollout, the database user it connects as should be
# added here. The preflight check will fail if any of these users are
# connected, so these systems will need to be shut down manually before
# a database update.
FRAGILE_USERS = frozenset([
    'buildd_manager',
    # process_accepted is fragile, but also fast so we likely shouldn't
    # need to ever manually shut it down.
    'process_accepted',
    'process_upload',
    'publish_distro',
    'publish_ftpmaster',
    ])

# If these users have long running transactions, just kill 'em. Entries
# added here must come with a bug number, a if part of Launchpad holds
# open a long running transaction it is a bug we need to fix.
BAD_USERS = frozenset([
    'karma',  # Bug #863109
    'rosettaadmin',  # Bug #863122
    'update-pkg-cache',  # Bug #912144
    'process_death_row',  # Bug #912146
    'langpack',  # Bug #912147
    ])

# How lagged the cluster can be before failing the preflight check.
# If this is set too low, perfectly normal state will abort rollouts. If
# this is set too high, then we will have unacceptable downtime as
# replication needs to catch up before the database patches will apply.
MAX_LAG = timedelta(seconds=60)


class DatabasePreflight:
    def __init__(self, log, standbys):
        master_con = connect(isolation=ISOLATION_LEVEL_AUTOCOMMIT)

        self.log = log
        self.is_slony = replication.helpers.slony_installed(master_con)
        if self.is_slony:
            self.nodes = set(
                replication.helpers.get_all_cluster_nodes(master_con))
            for node in self.nodes:
                node.con = node.connect(ISOLATION_LEVEL_AUTOCOMMIT)

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

            # Store a reference to the lpmain origin.
            lpmain_master_node_id = replication.helpers.get_master_node(
                master_con, 1).node_id
            self.lpmain_master_node = [
                node for node in self.lpmain_nodes
                    if node.node_id == lpmain_master_node_id][0]
        else:
            node = Node(None, None, None, True)
            node.con = master_con
            self.nodes = set([node])
            self.lpmain_nodes = self.nodes
            self.lpmain_master_node = node

        # Add streaming replication standbys, which unfortunately cannot be
        # detected reliably and has to be passed in via the command line.
        self._num_standbys = len(standbys)
        for standby in standbys:
            standby_node = Node(None, None, standby, False)
            standby_node.con = standby_node.connect(
                ISOLATION_LEVEL_AUTOCOMMIT)
            self.nodes.add(standby_node)
            self.lpmain_nodes.add(standby_node)

    def check_standby_count(self):
        # We sanity check the options as best we can to protect against
        # operator error.
        cur = self.lpmain_master_node.con.cursor()
        cur.execute("SELECT COUNT(*) FROM pg_stat_replication")
        required_standbys = cur.fetchone()[0]

        if required_standbys != self._num_standbys:
            self.log.fatal(
                "%d streaming standbys connected, but %d provided on cli"
                % (required_standbys, self._num_standbys))
            return False
        else:
            self.log.info(
                "%d streaming standby servers streaming", required_standbys)
            return True

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

    def check_fragile_connections(self):
        """Fail if any FRAGILE_USERS are connected to the cluster.

        If we interrupt these processes, we may have a mess to clean
        up. If they are connected, the preflight check should fail.
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
                    AND usename IN %s
                GROUP BY datname, usename
                """ % sqlvalues(FRAGILE_USERS))
            for datname, usename, num_connections in cur.fetchall():
                self.log.fatal(
                    "Fragile system %s running. %s has %d connections.",
                    usename, datname, num_connections)
                success = False
        if success:
            self.log.info(
                "No fragile systems connected to the cluster (%s)"
                % ', '.join(FRAGILE_USERS))
        return success

    def check_long_running_transactions(self, max_secs=60):
        """Return False if any nodes have long running transactions open.

        max_secs defines what is long running. For database rollouts,
        this will be short. Even if the transaction is benign like a
        autovacuum task, we should wait until things have settled down.

        We ignore transactions held open by BAD_USERS. These are bugs
        that need to be fixed, but we have determined that rudely aborting
        them is fine for now and there is no need to block a rollout on
        their behalf.
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
                if usename in BAD_USERS:
                    self.log.info(
                        "%s has transactions by %s open %s (ignoring)",
                        datname, usename, age)
                else:
                    self.log.fatal(
                        "%s has transaction by %s open %s",
                        datname, usename, age)
                    success = False
        if success:
            self.log.info("No long running transactions detected.")
        return success

    def check_replication_lag(self):
        """Return False if the replication cluster is badly lagged."""
        slony_lagged = False
        if self.is_slony:
            # Check replication lag on every node just in case there are
            # disagreements.
            max_lag = timedelta(seconds=-1)
            for node in self.nodes:
                cur = node.con.cursor()
                cur.execute("""
                    SELECT current_database(),
                    max(st_lag_time) AS lag FROM _sl.sl_status
                """)
                dbname, lag = cur.fetchone()
                if lag > max_lag:
                    max_lag = lag
                self.log.debug(
                    "%s reports database lag of %s.", dbname, lag)
            if max_lag <= MAX_LAG:
                self.log.info("Slony cluster lag is ok (%s)", max_lag)
                slony_lagged = False
            else:
                self.log.fatal("Slony cluster lag is high (%s)", max_lag)
                slony_lagged = True

        # Do something harmless to force changes to be streamed in case
        # system is idle.
        self.lpmain_master_node.con.cursor().execute(
            'ANALYZE LaunchpadDatabaseRevision')
        start_time = time.time()
        # Keep looking for low lag for 30 seconds, in case the system
        # was idle and streaming needs time to kick in.
        while time.time() < start_time + 30:
            max_lag = timedelta(seconds=-1)
            for node in self.nodes:
                cur = node.con.cursor()
                # streaming replication only works with 9.1 or later.
                # Remove this guard when SSO nodes are migrated to 9.1.
                cur.execute("""
                    select current_setting('server_version') >= '9.1'
                    """)
                is_pg91 = cur.fetchone()[0]
                if is_pg91:
                    cur.execute("""
                        SELECT current_setting('hot_standby') = 'on',
                        now() - pg_last_xact_replay_timestamp()
                        """)
                    is_standby, lag = cur.fetchone()
                    if is_standby:
                        self.log.debug2('streaming lag %s', lag)
                        max_lag = max(max_lag, lag)
            if max_lag < MAX_LAG:
                break
            time.sleep(0.2)

        if max_lag < timedelta(0):
            streaming_lagged = False
            self.log.debug("No streaming replication")
        elif max_lag > MAX_LAG:
            streaming_lagged = True
            self.log.fatal("Streaming replication lag is high (%s)", max_lag)
        else:
            streaming_lagged = False
            self.log.debug(
                "Streaming replication lag is not high (%s)", max_lag)

        return not (slony_lagged or streaming_lagged)

    def check_can_sync(self):
        """Return True if a sync event is acknowledged by all nodes.

        We only wait 30 seconds for the sync, because we require the
        cluster to be quiescent.
        """
        slony_success = True
        if self.is_slony:
            slony_success = replication.helpers.sync(30, exit_on_fail=False)
            if slony_success:
                self.log.info(
                    "Slony replication events are being propagated.")
            else:
                self.log.fatal(
                    "Slony replication events are not being propagated.")
                self.log.fatal(
                    "One or more slony replication daemons may be down.")
                self.log.fatal(
                    "Bounce the slony replication daemons and check logs.")

        # PG 9.1 streaming replication, or no replication.
        streaming_success = streaming_sync(self.lpmain_master_node.con, 30)
        if streaming_success:
            self.log.info("Streaming replicas syncing.")
        else:
            self.log.fatal("Streaming replicas not syncing.")

        return slony_success and streaming_success

    def report_patches(self):
        """Report what patches are due to be applied from this tree."""
        con = self.lpmain_master_node.con
        upgrade.log = self.log
        for patch_num, patch_file in upgrade.get_patchlist(con):
            self.log.info("%s is pending", os.path.basename(patch_file))

    def check_all(self):
        """Run all checks.

        If any failed, return False. Otherwise return True.
        """
        if not self.check_is_superuser():
            # No point continuing - results will be bogus without access
            # to pg_stat_activity
            return False

        self.report_patches()

        success = True
        if not self.check_standby_count():
            success = False
        if not self.check_replication_lag():
            success = False
        if not self.check_can_sync():
            success = False
        # Do checks on open transactions last to minimize race
        # conditions.
        if not self.check_open_connections():
            success = False
        if not self.check_long_running_transactions():
            success = False
        if not self.check_fragile_connections():
            success = False
        return success


class NoConnectionCheckPreflight(DatabasePreflight):
    def check_open_connections(self):
        return True


class KillConnectionsPreflight(DatabasePreflight):
    def check_open_connections(self):
        """Kill all non-system connections to Launchpad databases.

        We only check on subscribed nodes, as there will be active systems
        connected to other nodes in the replication cluster (such as the
        SSO servers).

        System users are defined by SYSTEM_USERS.
        """
        # We keep trying to terminate connections every 0.5 seconds for
        # up to 10 seconds.
        num_tries = 20
        seconds_to_pause = 0.5
        for loop_count in range(num_tries):
            all_clear = True
            for node in self.lpmain_nodes:
                cur = node.con.cursor()
                cur.execute("""
                    SELECT
                        procpid, datname, usename,
                        pg_terminate_backend(procpid)
                    FROM pg_stat_activity
                    WHERE
                        datname=current_database()
                        AND procpid <> pg_backend_pid()
                        AND usename NOT IN %s
                    """ % sqlvalues(SYSTEM_USERS))
                for procpid, datname, usename, ignored in cur.fetchall():
                    all_clear = False
                    if loop_count == num_tries - 1:
                        self.log.fatal(
                            "Unable to kill %s [%s] on %s",
                            usename, procpid, datname)
                    elif usename in BAD_USERS:
                        self.log.info(
                            "Killed %s [%s] on %s", usename, procpid, datname)
                    else:
                        self.log.warning(
                            "Killed %s [%s] on %s", usename, procpid, datname)
            if all_clear:
                break

            # Wait a little for any terminated connections to actually
            # terminate.
            time.sleep(seconds_to_pause)
        return all_clear


def streaming_sync(con, timeout=None):
    """Wait for streaming replicas to synchronize with master as of now.

    :param timeout: seconds to wait, None for no timeout.

    :returns: True if sync happened or no streaming replicas
              False if the timeout was passed.
    """
    cur = con.cursor()

    # Force a WAL switch, returning the current position.
    cur.execute('SELECT pg_switch_xlog()')
    wal_point = cur.fetchone()[0]
    start_time = time.time()
    while timeout is None or time.time() < start_time + timeout:
        cur.execute("""
            SELECT FALSE FROM pg_stat_replication
            WHERE replay_location < %s LIMIT 1
            """, (wal_point,))
        if cur.fetchone() is None:
            # All slaves, possibly 0, are in sync.
            return True
        time.sleep(0.2)
    return False


def main():
    parser = OptionParser()
    db_options(parser)
    logger_options(parser)
    parser.add_option(
        "--skip-connection-check", dest='skip_connection_check',
        default=False, action="store_true",
        help="Don't check open connections.")
    parser.add_option(
        "--kill-connections", dest='kill_connections',
        default=False, action="store_true",
        help="Kill non-system connections instead of reporting an error.")
    parser.add_option(
        '--standby', dest='standbys', default=[], action="append",
        metavar='CONN_STR',
        help="libpq connection string to a hot standby database")
    (options, args) = parser.parse_args()
    if args:
        parser.error("Too many arguments")

    if options.kill_connections and options.skip_connection_check:
        parser.error(
            "--skip-connection-check conflicts with --kill-connections")

    log = logger(options)

    if options.kill_connections:
        preflight_check = KillConnectionsPreflight(log, options.standbys)
    elif options.skip_connection_check:
        preflight_check = NoConnectionCheckPreflight(log, options.standbys)
    else:
        preflight_check = DatabasePreflight(log, options.standbys)

    if preflight_check.check_all():
        log.info('Preflight check succeeded. Good to go.')
        return 0
    else:
        log.error('Preflight check failed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
