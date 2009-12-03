#!/usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403

"""Update or create previews diffs for branch merge proposals."""

__metaclass__ = type

import _pythonpath

from lp.codehosting.vfs import get_scanner_server
from lp.services.job.runner import JobCronScript, TwistedJobRunner
from lp.code.interfaces.branchmergeproposal import (
    IUpdatePreviewDiffJobSource,)


class RunUpdatePreviewDiffJobs(JobCronScript):
    """Run UpdatePreviewDiff jobs."""

    config_name = 'update_preview_diffs'
    source_interface = IUpdatePreviewDiffJobSource


if __name__ == '__main__':
    script = RunUpdatePreviewDiffJobs(TwistedJobRunner)
    script.lock_and_run()
