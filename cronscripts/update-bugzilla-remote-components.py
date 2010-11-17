#!/usr/bin/python -S
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403
import _pythonpath

import time

from canonical.config import config
from lp.services.scripts.base import LaunchpadCronScript
from canonical.launchpad.scripts.bzremotecomponentfinder import (
    BugzillaRemoteComponentFinder,
    )


class UpdateRemoteComponentsFromBugzilla(LaunchpadCronScript):

    def add_my_options(self):
        self.parser.add_option(
            "-b", "--bugtracker", dest="bugtracker",
            help="Update only the bug tracker with this name in launchpad")

    def main(self):
        start_time = time.time()
        finder = BugzillaRemoteComponentFinder(
            self.logger)
        finder.getRemoteProductsAndComponents(
            bugtracker_name=self.options.bugtracker)

        run_time = time.time() - start_time
        print("Time for this run: %.3f seconds." % run_time)


if __name__ == "__main__":

    updater = UpdateRemoteComponentsFromBugzilla(
        "updatebugzillaremotecomponents",
        dbuser=config.updatebugzillaremotecomponents.dbuser)
    updater.lock_and_run()
