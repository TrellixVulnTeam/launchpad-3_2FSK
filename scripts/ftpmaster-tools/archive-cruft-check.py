#!/usr/bin/python2.5 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403

"""Archive Cruft checker.

A kind of archive garbage collector, supersede NBS binaries (not build
from source).
"""
import _pythonpath
import optparse
import sys

from canonical.config import config
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger, logger_options)
from lp.soyuz.scripts.ftpmaster import (
    ArchiveCruftChecker, ArchiveCruftCheckerError)
from canonical.lp import initZopeless
from contrib.glock import GlobalLock


def main():
    # Parse command-line arguments
    parser = optparse.OptionParser()

    logger_options(parser)

    parser.add_option(
        "-d", "--distro", dest="distro", help="remove from DISTRO")
    parser.add_option(
        "-n", "--no-action", dest="action", default=True,
        action="store_false", help="don't do anything")
    parser.add_option(
        "-s", "--suite", dest="suite", help="only act on SUITE")

    (options, args) = parser.parse_args()

    log = logger(options, "archive-cruft-check")

    log.debug("Acquiring lock")
    lock = GlobalLock('/var/lock/launchpad-archive-cruft-check.lock')
    lock.acquire(blocking=True)

    log.debug("Initialising connection.")
    execute_zcml_for_scripts()
    ztm = initZopeless(dbuser=config.archivepublisher.dbuser)


    if len(args) > 0:
        archive_path = args[0]
    else:
        log.error('ARCHIVEPATH is require')
        return 1

    checker = ArchiveCruftChecker(
        log, distribution_name=options.distro, suite=options.suite,
        archive_path=archive_path)

    try:
        checker.initialize()
    except ArchiveCruftCheckerError, info:
        log.error(info)
        return 1

# XXX cprov 2007-06-26 bug=121784: Disabling by distro-team request.
#    if checker.nbs_to_remove and options.action:
#        checker.doRemovals()
#        ztm.commit()

    lock.release()
    return 0


if __name__ == '__main__':
    sys.exit(main())
