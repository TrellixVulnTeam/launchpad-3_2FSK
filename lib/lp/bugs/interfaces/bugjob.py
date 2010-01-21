# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for using the Jobs system for Bugs."""

__metaclass__ = type
__all__ = [
    'BugJobType',
    'IBugJob',
    'ICalculateBugHeatJob',
    'ICalculateBugHeatJobSource',
    ]

from zope.interface import Attribute, Interface
from zope.schema import Int, Object

from canonical.launchpad import _

from lazr.enum import DBEnumeratedType, DBItem
from lp.bugs.interfaces.bug import IBug
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob


class BugJobType(DBEnumeratedType):
    """Values that IBugJob.job_type can take."""

    UPDATE_HEAT = DBItem(0, """
        Update the heat for a bug.

        This job recalculates the heat for a Bug.
        """)


class IBugJob(Interface):
    """A Job related to a Bug."""

    id = Int(
        title=_('DB ID'), required=True, readonly=True,
        description=_("The tracking number for this job."))

    bug = Object(
        title=_('The Bug this job is about'),
        schema=IBug, required=True)

    job = Object(title=_('The common Job attributes'), schema=IJob,
        required=True)

    metadata = Attribute('A dict of data about the job.')

    def destroySelf():
        """Destroy this object."""


class ICalculateBugHeatJob(IRunnableJob):
    """A Job to calculate bug heat."""


class ICalculateBugHeatJobSource(IJobSource):
    """Interface for acquiring CalculateBugHeatJobs."""

    def create(bug):
        """Create a new ICalculateBugHeatJob for a bug."""
