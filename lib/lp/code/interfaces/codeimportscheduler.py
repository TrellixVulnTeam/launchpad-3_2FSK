# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0213

"""Code import scheduler interfaces."""

__metaclass__ = type
__all__ = [
    'ICodeImportScheduler',
    'ICodeImportSchedulerApplication',
    ]


from canonical.launchpad.webapp.interfaces import ILaunchpadApplication

from zope.interface import Interface


class ICodeImportSchedulerApplication(ILaunchpadApplication):
    """Code import scheduler application root."""


class ICodeImportScheduler(Interface):
    """The code import scheduler.

    The code import scheduler is responsible for allocating import jobs to
    machines.  Code import slave machines call the getJobForMachine() method
    when they need more work to do.
    """

    def getJobForMachine(hostname, worker_limit):
        """Get a job to run on the slave 'hostname'.

        This method selects the most appropriate job for the machine,
        mark it as having started on said machine and return its id,
        or 0 if there are no jobs pending.
        """

    def getImportDataForJobID(job_id):
        """XXX."""

    def updateHeartbeat(job_id, log_tail):
        """XXX."""

    def finishJobID(job_id, status_name, log_file_alias_url):
        """XXX."""
