# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = ['BuildFarmJob']


from zope.component import getUtility
from zope.interface import classProvides, implements

from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR, IStoreSelector, MAIN_STORE)
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJob, IBuildFarmCandidateJobSelection,
    ISpecificBuildFarmJobClass)


class BuildFarmJob:
    """Mix-in class for `IBuildFarmJob` implementations."""
    implements(IBuildFarmJob)
    classProvides(
        IBuildFarmCandidateJobSelection, ISpecificBuildFarmJobClass)

    # Most build-farm job types have a Build associated, but not all.
    # Default to None, so that the attribute is at least defined.
    # XXX JeroenVermeulen 2010-03-11 bug=536819: this needs to be
    # handled better, and formalized.
    build = None

    def score(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError

    def getLogFileName(self):
        """See `IBuildFarmJob`."""
        return 'buildlog.txt'

    def getName(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError

    def getTitle(self):
        """See `IBuildFarmJob`."""
        raise NotImplementedError

    def jobStarted(self):
        """See `IBuildFarmJob`."""
        pass

    def jobReset(self):
        """See `IBuildFarmJob`."""
        pass

    def jobAborted(self):
        """See `IBuildFarmJob`."""
        pass

    @property
    def processor(self):
        """See `IBuildFarmJob`."""
        return None

    @property
    def virtualized(self):
        """See `IBuildFarmJob`."""
        return None

    @staticmethod
    def addCandidateSelectionCriteria(processor, virtualized):
        """See `IBuildFarmCandidateJobSelection`."""
        return ('')

    @classmethod
    def getByJob(cls, job):
        """See `ISpecificBuildFarmJobClass`.
        This base implementation should work for most build farm job
        types, but some need to override it.
        """
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        return store.find(cls, cls.job == job).one()

    @staticmethod
    def postprocessCandidate(job, logger):
        """See `IBuildFarmCandidateJobSelection`."""
        return True

