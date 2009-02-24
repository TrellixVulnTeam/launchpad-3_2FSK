#!/usr/bin/python2.4
# Copyright 2009 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0403

"""Create BranchMergeProposals from email."""

__metaclass__ = type

import _pythonpath
from zope.component import getUtility

from canonical.config import config
from canonical.codehosting.jobs import JobRunner
from canonical.codehosting.vfs import get_puller_server
from canonical.launchpad.interfaces.branchmergeproposal import (
    ICreateMergeProposalJobSource,)
from canonical.launchpad.scripts.base import LaunchpadCronScript
from canonical.launchpad.webapp.errorlog import globalErrorUtility


class RunCreateMergeProposalJobs(LaunchpadCronScript):
    """Run create merge proposal jobs."""

    def main(self):
        globalErrorUtility.configure('create_merge_proposals')
        job_source = getUtility(ICreateMergeProposalJobSource)
        runner = JobRunner.fromReady(job_source)
        server = get_puller_server()
        server.setUp()
        try:
            runner.runAll()
            self.logger.info(
                'Ran %d CreateMergeProposalJobs.' % len(runner.completed_jobs))
        finally:
            server.tearDown()


if __name__ == '__main__':
    script = RunCreateMergeProposalJobs(
        'create_merge_proposals', config.create_merge_proposals.dbuser)
    script.lock_and_run()
