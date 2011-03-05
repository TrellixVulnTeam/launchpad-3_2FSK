#!/usr/bin/python -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0103,W0403

# This script updates the cached stats in the system

import _pythonpath

from zope.component import getUtility
from canonical.database.sqlbase import ISOLATION_LEVEL_READ_COMMITTED
from canonical.launchpad.interfaces.launchpadstatistic import (
    ILaunchpadStatisticSet,
    )
from lp.services.scripts.base import LaunchpadCronScript
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from canonical.config import config


class StatUpdater(LaunchpadCronScript):

    def main(self):
        self.logger.debug('Starting the stats update')

        # Note that we do not issue commits here in the script; content
        # objects are responsible for committing.
        distroset = getUtility(IDistributionSet)
        for distro in distroset:
            for distroseries in distro.series:
                distroseries.updateStatistics(self.txn)

        launchpad_stats = getUtility(ILaunchpadStatisticSet)
        launchpad_stats.updateStatistics(self.txn)

        getUtility(IPersonSet).updateStatistics(self.txn)

        self.logger.debug('Finished the stats update')


if __name__ == '__main__':
    script = StatUpdater('launchpad-stats', dbuser=config.statistician.dbuser)
    script.lock_and_run(isolation=ISOLATION_LEVEL_READ_COMMITTED)
