#!/usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403

"""Cron job to update remote_products using SourceForge project data."""

import time
import _pythonpath

from canonical.config import config
from lp.services.scripts.base import LaunchpadCronScript
from canonical.launchpad.scripts.sfremoteproductfinder import (
    SourceForgeRemoteProductFinder)


class UpdateRemoteProductsFromSourceForge(LaunchpadCronScript):

    def main(self):
        start_time = time.time()

        finder = SourceForgeRemoteProductFinder(self.txn, self.logger)
        finder.setRemoteProductsFromSourceForge()

        run_time = time.time() - start_time
        self.logger.info("Time for this run: %.3f seconds." % run_time)


if __name__ == '__main__':
    script = UpdateRemoteProductsFromSourceForge(
        "updateremoteproduct",
        dbuser=config.updatesourceforgeremoteproduct.dbuser)
    script.lock_and_run()
