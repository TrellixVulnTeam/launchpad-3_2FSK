# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0213,E0211

"""Interfaces including and related to IJob."""

__metaclass__ = type

__all__ = [
    'IJob',
    'IRunnableJob',
    'JobStatus',
    'LeaseHeld',
    ]


from zope.interface import Interface, Attribute
from zope.schema import Choice, Datetime, Int, Text
from lazr.enum import DBEnumeratedType, DBItem

from canonical.launchpad import _


class LeaseHeld(Exception):
    """Raised when attempting to acquire a list that is already held."""

    def __init__(self):
        Exception.__init__(self, 'Lease is already held.')


class JobStatus(DBEnumeratedType):
    """Values that ICodeImportJob.state can take."""

    WAITING = DBItem(0, """
        Waiting

        The job is waiting to be run.
        """)

    RUNNING = DBItem(1, """
        Running

        The job is currently running.
        """)

    COMPLETED = DBItem(2, """
        Completed

        The job has run to successful completion.
        """)

    FAILED = DBItem(3, """
        Failed

        The job was run, but failed.  Will not be run again.
        """)

    SUSPENDED = DBItem(4, """
        Suspended

        The job is suspended because it's dependencies are deactivated.
        """)


class IJob(Interface):
    """Basic attributes of a job."""

    scheduled_start = Datetime(
        title=_('Time when the IJob was scheduled to start.'))

    date_created = Datetime(title=_('Time when the IJob was created.'))

    date_started = Datetime(title=_('Time when the IJob started.'))

    date_finished = Datetime(title=_('Time when the IJob ended.'))

    lease_expires = Datetime(title=_('Time when the lease expires.'))

    log = Text(title=_('The log of the job.'))

    status = Choice(
        vocabulary=JobStatus, readonly=True,
        description=_("The current state of the job."))

    attempt_count = Int(title=_(
        'The number of attempts to perform this job that have been made.'))

    def acquireLease(duration=300):
        """Acquire the lease for this Job, or raise LeaseHeld."""

    def getTimeout():
        """Determine how long this job can run before timing out."""

    def start():
        """Mark the job as started."""

    def complete():
        """Mark the job as completed."""

    def fail():
        """Indicate that the job has failed permanently.

        Only running jobs can fail.
        """

    def queue():
        """Mark the job as queued for processing."""

    def suspend():
        """Mark the job as suspended.

        Only waiting jobs can be suspended."""

    def resume():
        """Mark the job as waiting.

        Only suspended jobs can be resumed."""


class IRunnableJob(IJob):
    """Interface for jobs that can be run via the JobRunner."""

    def notifyOops(oops):
        """Notify interested parties that this job produced an OOPS.

        :param oops: The oops produced by this Job.
        """

    def getOopsVars():
        """Return a list of variables to appear in the OOPS.

        These vars should help determine why the jobs OOPsed.
        """

    user_error_types = Attribute(
        'A tuple of exception classes which result from user error.')

    def notifyUserError(e):
        """Notify interested parties that this job encountered a user error.

        :param e: The exception encountered by this job.
        """

    def run():
        """Run this job."""
