#!/usr/bin/python -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Initialize a new distroseries from its parent series."""

from optparse import OptionParser
import sys

import _pythonpath
from contrib.glock import GlobalLock
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts,
    logger,
    logger_options,
    )
from canonical.lp import initZopeless
from lp.app.errors import NotFoundError
from lp.registry.interfaces.distribution import IDistributionSet
from lp.soyuz.scripts.initialize_distroseries import (
    InitializationError,
    InitializeDistroSeries,
    )


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

    parser.add_option(
        "-a", "--arches", dest="arches",
        help="A comma-seperated list of arches to limit the child "
        "distroseries to inheriting")

    (options, args) = parser.parse_args()

    log = logger(options, "initialize")

    if len(args) != 1:
        log.error("Need to be given exactly one non-option argument. "
                  "Namely the distroseries to initialize.")
        return 1

    distroseries_name = args[0]

    log.debug("Acquiring lock")
    lock = GlobalLock('/var/lock/launchpad-initialize.lock')
    lock.acquire(blocking=True)

    log.debug("Initializing connection.")

    execute_zcml_for_scripts()
    ztm = initZopeless(dbuser=config.initializedistroseries.dbuser)

    try:
        # 'ubuntu' is the default option.distribution value
        distribution = getUtility(IDistributionSet)[options.distribution]
        distroseries = distribution[distroseries_name]
    except NotFoundError, info:
        log.error('%s not found' % info)
        return 1

    try:
        log.debug('Check empty mutable queues in parentseries')
        log.debug('Check for no pending builds in parentseries')
        log.debug('Copying distroarchseries from parent(s) '
                      'and setting nominatedarchindep.')
        arches = ()
        if options.arches is not None:
            arches = tuple(options.arches.split(','))
        ids = InitializeDistroSeries(distroseries, arches=arches)
        ids.check()
        log.debug('initializing from parent(s), copying publishing records.')
        ids.initialize()
    except InitializationError, e:
        ztm.abort()
        log.error(e)
        return 1

    if options.dryrun:
        log.debug('Dry-Run mode, transaction aborted.')
        ztm.abort()
    else:
        log.debug('Committing transaction.')
        ztm.commit()

    log.debug("Releasing lock")
    lock.release()
    return 0


if __name__ == '__main__':
    sys.exit(main())
