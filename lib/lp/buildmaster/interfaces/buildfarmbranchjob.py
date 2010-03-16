# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface."""

__metaclass__ = type
__all__ = [
    'IBuildFarmBranchJob'
    ]

from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.code.interfaces.branchjob import IBranchJob


class IBuildFarmBranchJob(IBuildFarmJob, IBranchJob):
    """An `IBuildFarmJob` that's also an `IBranchJob`.

    Use this interface for `IBuildFarmJob` implementations that do not
    have a "build" attribute but do implement `IBranchJob`, so that the
    UI can render appropriate status information.
    """
