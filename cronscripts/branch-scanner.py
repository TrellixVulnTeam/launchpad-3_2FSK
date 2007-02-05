#!/usr/bin/env python
# Copyright 2005 Canonical Ltd.  All rights reserved.
# Author: Gustavo Niemeyer <gustavo@niemeyer.net>
#         David Allouche <david@allouche.net>

"""Update bzr branches information in the database"""


import _pythonpath
import logging

from canonical.config import config
from canonical.launchpad.scripts.base import LaunchpadScript
from canonical.launchpad.scripts.branch_scanner import BranchScanner


class UpdateBranches(LaunchpadScript):
    def main(self):
        # We don't want debug messages from bzr at that point.
        bzr_logger = logging.getLogger("bzr")
        bzr_logger.setLevel(logging.INFO)

        # Customize the oops reporting config
        oops_prefix = config.branchscanner.errorreports.oops_prefix
        config.launchpad.errorreports.oops_prefix = oops_prefix
        errordir = config.branchscanner.errorreports.errordir
        config.launchpad.errorreports.errordir = errordir

        BranchScanner(self.txn, self.logger).scanAllBranches()


if __name__ == '__main__':
    script = UpdateBranches("updatebranches", dbuser=config.branchscanner.dbuser)
    script.lock_and_run()

