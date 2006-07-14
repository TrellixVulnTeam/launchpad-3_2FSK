#!/usr/bin/env python
"""Archive Override Check

Given a distribution to run on, report any override inconsistence found.
It basically check if all published source and binaries are coherent.
"""

import _pythonpath

from optparse import OptionParser
import sys

from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger, logger_options)
from canonical.launchpad.scripts.ftpmaster import  PubSourceChecker
from canonical.launchpad.interfaces import (
    IDistributionSet, NotFoundError)
from canonical.lp import (
    initZopeless, READ_COMMITTED_ISOLATION)
from canonical.lp.dbschema import (
    PackagePublishingStatus, PackagePublishingPocket, BuildStatus)

from contrib.glock import GlobalLock

def main():
    # Parse command-line arguments
    parser = OptionParser()
    logger_options(parser)

    parser.add_option("-d", "--distribution", action="store",
                      dest="distribution", metavar="DISTRO", default="ubuntu",
                      help="Distribution to consider")

    parser.add_option("-s", "--suite", action="store",
                      dest="suite", metavar="SUITE", default=None,
                      help=("Suite to consider, if not passed consider the "
                            "currentrelease and the RELEASE pocket"))

    (options, args) = parser.parse_args()

    log = logger(options, "archive-override-check")

    log.debug("Acquiring lock")
    lock = GlobalLock('/var/lock/archive-override-check.lock')
    lock.acquire(blocking=True)

    log.debug("Initialising connection.")
    ztm = initZopeless(dbuser='lucille', isolation=READ_COMMITTED_ISOLATION)
    execute_zcml_for_scripts()

    try:
        try:
            distribution = getUtility(IDistributionSet)[options.distribution]
            if options.suite is None:
                distrorelease = distribution.currentrelease
                pocket = PackagePublishingPocket.RELEASE
            else:
                distrorelease, pocket = distribution.getDistroReleaseAndPocket(
                    options.suite)

            log.debug("Considering: %s/%s/%s/%s."
                      % (distribution.name, distrorelease.name, pocket.name,
                         distrorelease.releasestatus.name))

            checkOverrides(distrorelease, pocket, log)

        except NotFoundError, info:
            log.error('Not found: %s' % info)

    finally:
        log.debug("Rolling back any remaining transactions.")
        ztm.abort()
        log.debug("Releasing lock")
        lock.release()

    return 0


def checkOverrides(distrorelease, pocket, log):
    """Initialize and handle PubSourceChecker.

    Iterate over PUBLISHED sources and perform PubSourceChecker.check()
    on each published Source/Binaries couple.
    """
    spps = distrorelease.getSourcePackagePublishing(
        status=PackagePublishingStatus.PUBLISHED,
        pocket=pocket)

    log.debug('%s published sources' % spps.count())

    for spp in spps:
        checker= PubSourceChecker(spp.sourcepackagerelease.name,
                                  spp.sourcepackagerelease.version,
                                  spp.component.name, spp.section.name,
                                  spp.sourcepackagerelease.urgency.name)

        for bpp in spp.publishedBinaries():
            checker.addBinary(bpp.binarypackagerelease.name,
                              bpp.binarypackagerelease.version,
                              bpp.distroarchrelease.architecturetag,
                              bpp.component.name, bpp.section.name,
                              bpp.binarypackagerelease.priority.name)

        checker.check()

        report = checker.renderReport()

        if report:
            print report

if __name__ == '__main__':
    sys.exit(main())

