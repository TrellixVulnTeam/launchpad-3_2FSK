#!/usr/bin/env python
"""Initialise a new distrorelease from its parent

It performs two additional tasks before call initialiseFromParent:

* check_queue (ensure parent's mutable queues are empty)
* copy_architectures (copy parent's architectures and set
                      nominatedarchindep properly)

which may be integrated in the its workflow.
"""

import _pythonpath

import sys
from optparse import OptionParser

from zope.component import getUtility
from contrib.glock import GlobalLock

from canonical.database.sqlbase import (
    sqlvalues, flush_database_updates, cursor, flush_database_caches)
from canonical.lp import (
    initZopeless, READ_COMMITTED_ISOLATION)
from canonical.lp.dbschema import (
    DistroReleaseQueueStatus, BuildStatus, PackagePublishingPocket)
from canonical.launchpad.interfaces import (
    IDistributionSet, NotFoundError)
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger, logger_options)


def main():
    # Parse command-line arguments
    parser = OptionParser()
    logger_options(parser)

    parser.add_option("-N", "--dry-run", action="store_true",
                      dest="dryrun", metavar="DRY_RUN", default=False,
                      help="Whether to treat this as a dry-run or not.")

    parser.add_option("-d", "--distro", dest="distribution", metavar="DISTRO",
                      default="ubuntu",
                      help="Distribution name")

    parser.add_option("-c", "--changeslist", dest="changeslist",
                      metavar="CHANGESLIST", default=None,
                      help="Distrorelease changes list address")

    (options, args) = parser.parse_args()

    log = logger(options, "initialiase")

    if len(args) != 1:
        log.error("Need to be given exactly one non-option argument. "
                  "Namely the distrorelease to initialiase.")
        return 1

    distrorelease_name = args[0]

    log.debug("Acquiring lock")
    lock = GlobalLock('/var/lock/launchpad-initialiase.lock')
    lock.acquire(blocking=True)

    log.debug("Initialising connection.")

    ztm = initZopeless(dbuser='lucille', isolation=READ_COMMITTED_ISOLATION)
    execute_zcml_for_scripts()

    try:
        distribution = getUtility(IDistributionSet)[options.distribution]
        distrorelease = distribution[distrorelease_name]
    except NotFoundError, info:
        log.error(info)
        return 1

    # XXX cprov 20060526: these two extra function must be
    # integrated in IDistroRelease.initialiseFromParent workflow.
    log.debug('Check empty mutable queues in parentrelease')
    check_queue(distrorelease)

    log.debug('Check for no pending builds in parentrelease')
    check_builds(distrorelease)

    log.debug('Copying distroarchreleases from parent '
              'and setting nominatedarchindep.')
    copy_architectures(distrorelease)

    log.debug('initialising from parent, copying publishing records.')
    distrorelease.initialiseFromParent()

    if options.changeslist:
        log.debug('Setting %s changes list address to: %s'
                  % (distrorelease.title, options.changeslist))
        distrorelease.changeslist = options.changeslist

    if options.dryrun:
        log.debug('Dry-Run mode, transaction aborted.')
        ztm.abort()
    else:
        log.debug('Committing transaction.')
        ztm.commit()

    log.debug("Releasing lock")
    lock.release()
    return 0


def check_builds(distrorelease):
    """Assertions for no remaining pending builds."""
    parentrelease = distrorelease.parentrelease

    pending_builds = parentrelease.getBuildRecords(
        BuildStatus.NEEDSBUILD, pocket=PackagePublishingPocket.RELEASE)

    assert (pending_builds.count() == 0,
            'Parent must not have PENDING builds')

def check_queue(distrorelease):
    """Assertions on empty mutable queues in parentrelease."""
    parentrelease = distrorelease.parentrelease

    new_items = parentrelease.getQueueItems(
        DistroReleaseQueueStatus.NEW,
        pocket=PackagePublishingPocket.RELEASE)
    accepted_items = parentrelease.getQueueItems(
        DistroReleaseQueueStatus.ACCEPTED,
        pocket=PackagePublishingPocket.RELEASE)
    unapproved_items = parentrelease.getQueueItems(
        DistroReleaseQueueStatus.UNAPPROVED,
        pocket=PackagePublishingPocket.RELEASE)

    assert (new_items.count() == 0,
            'Parent NEW queue must be empty')
    assert (accepted_items.count() == 0,
            'Parent ACCEPTED queue must be empty')
    assert (unapproved_items.count() == 0,
            'Parent UNAPPROVED queue must be empty')

def copy_architectures(distrorelease):
    """Overlap SQLObject and copy architecture from the parent.

    Also set the nominatedarchindep properly in target.
    """
    flush_database_updates()
    cur = cursor()
    cur.execute("""
    INSERT INTO DistroArchRelease
          (distrorelease, processorfamily, architecturetag, owner, official)
    SELECT %s, processorfamily, architecturetag, %s, official
    FROM DistroArchRelease WHERE distrorelease = %s
    """ % sqlvalues(distrorelease, distrorelease.owner,
                    distrorelease.parentrelease))
    flush_database_caches()

    distrorelease.nominatedarchindep = distrorelease[
        distrorelease.parentrelease.nominatedarchindep.architecturetag]


if __name__ == '__main__':
    sys.exit(main())

