# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Interfaces including and related to IJob."""

__metaclass__ = type

__all__ = [
    'IJob',
    'JobStatus',
    ]


from canonical.lazr import DBEnumeratedType, DBItem
from zope.interface import Interface
from zope.schema import Choice, Datetime, Int, Text

from canonical.launchpad import _


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


class IJob(Interface):

    scheduled_start = Datetime(
        title=_('Time when the IJob was scheduled to start.'))

    date_created = Datetime(title=_('Time when the IJob was created.'))

    date_started = Datetime(title=_('Time when the IJob started.'))

    date_ended = Datetime(title=_('Time when the IJob ended.'))

    lease_expires = Datetime(title=_('Time when the lease expires.'))

    log = Text(title=_('The log of the job.'))

    status = Choice(
        vocabulary=JobStatus, readonly=True,
        description=_("The current state of the job."))

    attempt_count = Int(title=_(
        'The number of attempts to perform this job that have been made.'))
