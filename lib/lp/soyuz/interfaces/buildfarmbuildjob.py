# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface to support UI for most build-farm jobs."""

__metaclass__ = type
__all__ = [
    'IBuildFarmBuildJob'
    ]

from canonical.launchpad import _
from lazr.restful.fields import Reference
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJob
from lp.soyuz.interfaces.build import IBuild


class IBuildFarmBuildJob(IBuildFarmJob):
    """An `IBuildFarmJob` with an `IBuild` reference."""
    build = Reference(
        IBuild, title=_("Build"), required=True, readonly=True,
        description=_("Build record associated with this job."))
