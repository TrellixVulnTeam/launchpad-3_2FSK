#!/usr/bin/python2.4
# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Send branch mail.

This script sends out all the mail jobs that are pending.
"""

__metaclass__ = type

import _pythonpath
from zope.component import getUtility

from canonical.launchpad.interfaces.branch import IRevisionMailJobSource
from canonical.launchpad.scripts.base import LaunchpadCronScript


class RunRevisionMailJobs(LaunchpadCronScript):
    """Run pending code mail jobs."""

    def main(self):
        getUtility(IRevisionMailJobSource).runAll()


if __name__ == '__main__':
    script = RunRevisionMailJobs('sendcodemail').run()
