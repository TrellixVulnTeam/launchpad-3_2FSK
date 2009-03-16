#!/usr/bin/python2.4
# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Startup and shutdown slon processes.

On production and staging we probably want to use the standard
/etc/init.d/slony1 script instead of this tool.
"""

import _pythonpath

import os.path
import subprocess
import sys
from optparse import OptionParser

from canonical.config import config
from canonical.database.postgresql import ConnectionString
from canonical.database.sqlbase import connect
from canonical.launchpad.scripts import logger, logger_options
import replication.helpers

__metaclass__ = type
__all__ = []


def main():
    parser = OptionParser(
        "Usage: %prog [options] "
        "[start [nickname connection_string] | stop [nickname]]")
    parser.add_option(
        '-l', '--lag', default=None, dest="lag", metavar='PGINTERVAL',
        help="Lag events by PGINTERVAL, such as '10 seconds' or '2 minutes'")
    logger_options(parser)
    options, args = parser.parse_args()

    if len(args) == 0:
        parser.error("No command given.")

    elif len(args) == 1:
        explicit = None

    elif len(args) == 2:
        parser.error("nickname or connection_string missing.")

    elif len(args) == 3:
        explicit = replication.helpers.Node(
            None, args[1], args[2], None)

    else:
        parser.error("Too many arguments.")

    command = args[0]
    if command not in ['start', 'stop']:
        parser.error("Unknown command %s." % command)

    log = logger(options)

    if explicit is not None:
        nodes = [explicit]
    else:
        nodes = replication.helpers.get_all_cluster_nodes(connect('slony'))

    if command == 'start':
        return start(log, nodes, options.lag)
    else:
        return stop(log, nodes)


def get_pidfile(nickname):
    return os.path.join(
        config.canonical.pid_dir, 'lpslon_%s_%s.pid' % (
        nickname, config.instance_name))

def get_logfile(nickname):
    return os.path.join(
        config.root, 'database', 'replication',
        'lpslon_%s_%s.log' % (nickname, config.instance_name))


def start(log, nodes, lag=None):
    for node in nodes:
        pidfile = get_pidfile(node.nickname)
        logfile = get_logfile(node.nickname)

        log.info("Starting %s slon daemon." % node.nickname)
        log.debug("Logging to %s" % logfile)
        log.debug("PID file %s" % pidfile)
        # Hard code suitable command line arguments for development.
        slon_args = "-d 2 -s 10000 -t 30000"
        if lag is not None:
            slon_args = "%s -l '%s'" % (slon_args, lag)
        cmd = [
            "/sbin/start-stop-daemon",
            "--start",
            "--background",
            "--pidfile", pidfile,
            "--oknodo",
            "--exec", "/usr/bin/slon",
            "--startas", "/bin/sh",
            "--", "-c",
            "slon -p %s %s %s '%s' > %s" % (
                pidfile, slon_args, replication.helpers.CLUSTERNAME,
                node.connection_string, logfile)]
        log.debug("Running %s" % repr(cmd))
        return_code = subprocess.call(cmd)
        if return_code != 0:
            log.fatal("Failed. Return code %s" % return_code)
            return return_code

    return 0


def stop(log, nodes):
    for node in nodes:
        pidfile = get_pidfile(node.nickname)
        logfile = get_logfile(node.nickname)

        if not os.path.exists(pidfile):
            log.info(
                "%s slon daemon not running. Doing nothing."
                % node.nickname)
            continue
        log.info("Stopping %s slon daemon." % node.nickname)
        log.debug("PID file %s" % pidfile)
        cmd = [
            "/sbin/start-stop-daemon",
            "--stop",
            "--pidfile", pidfile,
            "--oknodo"]
        log.debug("Running %s" % repr(cmd))
        return_code = subprocess.call(cmd)
        if return_code != 0:
            log.fatal("Failed. Return code %s" % return_code)
            return return_code

    return 0


if __name__ == '__main__':
    sys.exit(main())
