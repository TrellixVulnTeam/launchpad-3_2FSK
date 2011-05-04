# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""`TranslationTemplatesBuild` class."""

__metaclass__ = type
__all__ = [
    'TranslationTemplatesBuild',
    ]

from storm.locals import (
    Int,
    Reference,
    Storm,
    )
from storm.store import Store
from zope.interface import (
    classProvides,
    implements,
    )
from zope.security.proxy import ProxyFactory

from canonical.launchpad.interfaces.lpstorm import IStore
from lp.buildmaster.model.buildfarmjob import BuildFarmJobDerived
from lp.code.model.branchjob import (
    BranchJob,
    BranchJobType,
    )
from lp.translations.interfaces.translationtemplatesbuild import (
    ITranslationTemplatesBuild,
    ITranslationTemplatesBuildSource,
    )
from lp.translations.model.translationtemplatesbuildjob import (
    TranslationTemplatesBuildJob,
    )


class TranslationTemplatesBuild(BuildFarmJobDerived, Storm):
    """A `BuildFarmJob` extension for translation templates builds."""

    implements(ITranslationTemplatesBuild)
    classProvides(ITranslationTemplatesBuildSource)

    __storm_table__ = 'TranslationTemplatesBuild'

    id = Int(name='id', primary=True)
    build_farm_job_id = Int(name='build_farm_job', allow_none=False)
    build_farm_job = Reference(build_farm_job_id, 'BuildFarmJob.id')
    branch_id = Int(name='branch', allow_none=False)
    branch = Reference(branch_id, 'Branch.id')

    def __init__(self, build_farm_job, branch):
        super(TranslationTemplatesBuild, self).__init__()
        self.build_farm_job = build_farm_job
        self.branch = branch

    def makeJob(self):
        """See `IBuildFarmJobOld`."""
        store = IStore(BranchJob)

        # Pass public HTTP URL for the branch.
        metadata = {
            'branch_url': self.branch.composePublicURL(),
            'build_id': self.id,
            }
        branch_job = BranchJob(
            self.branch, BranchJobType.TRANSLATION_TEMPLATES_BUILD, metadata)
        store.add(branch_job)
        return TranslationTemplatesBuildJob(branch_job)

    @classmethod
    def _getStore(cls, store=None):
        """Return `store` if given, or the default."""
        if store is None:
            return IStore(cls)
        else:
            return store

    @classmethod
    def create(cls, build_farm_job, branch):
        """See `ITranslationTemplatesBuildSource`."""
        build = TranslationTemplatesBuild(build_farm_job, branch)
        store = cls._getStore()
        store.add(build)
        store.flush()
        return build

    @classmethod
    def getByID(cls, build_id, store=None):
        """See `ITranslationTemplatesBuildSource`."""
        store = cls._getStore(store)
        match = store.find(
            TranslationTemplatesBuild,
            TranslationTemplatesBuild.id == build_id)
        return match.one()

    @classmethod
    def getByBuildFarmJob(cls, buildfarmjob_id, store=None):
        """See `ITranslationTemplatesBuildSource`."""
        store = cls._getStore(store)
        match = store.find(
            TranslationTemplatesBuild,
            TranslationTemplatesBuild.build_farm_job == buildfarmjob_id)
        return match.one()

    @classmethod
    def findByBranch(cls, branch, store=None):
        """See `ITranslationTemplatesBuildSource`."""
        store = cls._getStore(store)
        return store.find(
            TranslationTemplatesBuild,
            TranslationTemplatesBuild.branch == branch)


def get_translation_templates_build_for_build_farm_job(build_farm_job):
    """Return a `TranslationTemplatesBuild` from its `BuildFarmJob`."""
    build = Store.of(build_farm_job).find(
        TranslationTemplatesBuild,
        TranslationTemplatesBuild.build_farm_job == build_farm_job).one()
    return ProxyFactory(build)
