#!/usr/bin/python2.4
# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Refresh and verify cached POFile translation statistics."""

from canonical.config import config

from canonical.launchpad.scripts.base import LaunchpadCronScript
from canonical.launchpad.scripts.verify_pofile_stats import (
    VerifyPOFileStatsProcess)


class VerifyPOFileStats(LaunchpadCronScript):
    def main(self):
        VerifyPOFileStatsProcess(self.txn, self.logger).run()


if __name__ == '__main__':
    script = VerifyPOFileStats(name="pofile-stats")
    script.lock_and_run()

