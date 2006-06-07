#!/usr/bin/env python
# Copyright 2004 Canonical Ltd.  All rights reserved.
# Author: Daniel Silverstone <daniel.silverstone@canonical.com>
#         Celso Providelo <celso.providelo@canonical.com>
#
# Build Jobs initialisation
#
__metaclass__ = type

import _pythonpath

import sys
import os
from optparse import OptionParser

from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.interfaces import IDistroArchReleaseSet
from canonical.launchpad.scripts.builddmaster import BuilddMaster
from canonical.launchpad.scripts.lockfile import LockFile
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger_options, logger)
from canonical.lp import (
    initZopeless, READ_COMMITTED_ISOLATION)

_default_lockfile = '/var/lock/buildd-master.lock'


def rebuildQueue(log, tm):
    """Look for and initialise new build jobs."""
    buildMaster = BuilddMaster(log, tm)

    # Simple container
    distroreleases = set()

    # For every distroarchrelease we can find; put it into the build master
    for archrelease in getUtility(IDistroArchReleaseSet):
        distroreleases.add(archrelease.distrorelease)
        buildMaster.addDistroArchRelease(archrelease)

    # For each distrorelease we care about; scan for sourcepackagereleases
    # with no build associated with the distroarchreleases we're
    # interested in
    for distrorelease in distroreleases:
        buildMaster.createMissingBuilds(distrorelease)

    # inspect depwaiting and look retry those which seems possible
    buildMaster.retryDepWaiting()

    # For each build record in NEEDSBUILD, ensure it has a
    # buildqueue entry
    buildMaster.addMissingBuildQueueEntries()

    # Re-score the NEEDSBUILD properly
    buildMaster.sanitiseAndScoreCandidates()

# XXX cprov 20060606: i know this is evil and ugly but, right now,
# modifying launchpad/scripts/builddmaster.py and tests would be painfully.
class FakeZtm:
    """This class only satisfy the callsites which uses commit method

    Real ZTM handling is done in main.
    """
    def commit(self):
        pass

    def abort(self):
        pass

if __name__ == '__main__':
    parser = OptionParser()
    logger_options(parser)

    parser.add_option("-N", "--dry-run", action="store_true",
                      dest="dryrun", metavar="DRY_RUN", default=False,
                      help="Whether to treat this as a dry-run or not.")

    (options, arguments) = parser.parse_args()

    if arguments:
        parser.error("Unhandled arguments %r" % arguments)

    log = logger(options, 'queuebuilder')

    if os.path.exists("/srv/launchpad.net/ubuntu-archive/cron.daily.lock"):
        # Quick and dirty "don't start if the publisher is here"
        log.error("cron.daily is running, exiting.")
        sys.exit(1)

    log.info("Rebuilding Build Queue.")

    locker = LockFile(_default_lockfile, logger=log)
    try:
        locker.acquire()
    except OSError:
        log.error("Cannot Acquire Lock.")
        sys.exit(1)

    # setup a transaction manager
    ztm = initZopeless(dbuser=config.builddmaster.dbuser,
                       isolation=READ_COMMITTED_ISOLATION)
    execute_zcml_for_scripts()

    try:
        rebuildQueue(log, FakeZtm())
    finally:
        if not options.dryrun:
            log.debug("Commiting changes.")
            log.info("Buildd Queue Rebuilt.")
            ztm.commit()
        else:
            log.debug("Dry Run, changes not commited.")
            ztm.abort()

    locker.release()

