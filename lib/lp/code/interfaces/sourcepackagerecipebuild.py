# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0213

"""Interfaces for source package builds."""

__metaclass__ = type
__all__ = [
    'ISourcePackageRecipeBuild',
    'ISourcePackageRecipeBuildSource',
    'ISourcePackageRecipeBuildJob',
    'ISourcePackageRecipeBuildJobSource',
    ]

from lazr.restful.fields import Reference

from zope.interface import Interface
from zope.schema import Int, Object

from canonical.launchpad import _

from lp.buildmaster.interfaces.buildbase import IBuildBase
from lp.soyuz.interfaces.buildfarmbuildjob import IBuildFarmBuildJob
from lp.code.interfaces.sourcepackagerecipe import ISourcePackageRecipe
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.sourcepackagename import ISourcePackageName
from lp.services.job.interfaces.job import IJob
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease


class ISourcePackageRecipeBuild(IBuildBase):
    """A build of a source package."""

    id = Int(title=_("Identifier for this build."))

    distroseries = Reference(
        IDistroSeries, title=_("The distroseries being built for"),
        readonly=True)

    sourcepackagename = Reference(
        ISourcePackageName,
        title=_("The name of the source package being built"),
        readonly=True)

    requester = Object(
        schema=IPerson, required=False,
        title=_("The person who wants this to be done."))

    recipe = Object(
        schema=ISourcePackageRecipe, required=True,
        title=_("The recipe being built."))

    source_package_release = Reference(
        ISourcePackageRelease, title=_("The produced source package release"),
        readonly=True)


class ISourcePackageRecipeBuildSource(Interface):
    """A utility of this interface be used to create source package builds."""

    def new(sourcepackage, recipe, requester, date_created=None):
        """Create an `ISourcePackageRecipeBuild`.

        :param sourcepackage: The `ISourcePackage` that this is building.
        :param recipe: The `ISourcePackageRecipe` that this is building.
        :param requester: The `IPerson` who wants to build it.
        :param date_created: The date this build record was created. If not
            provided, defaults to now.
        :return: `ISourcePackageRecipeBuild`.
        """

    def getById(build_id):
        """Return the `ISourcePackageRecipeBuild` for the given build id.

        :param build_id: The id of the build to return.
        :return: `ISourcePackageRecipeBuild`
        """


class ISourcePackageRecipeBuildJob(IBuildFarmBuildJob):
    """A read-only interface for recipe build jobs."""

    job = Reference(
        IJob, title=_("Job"), required=True, readonly=True,
        description=_("Data common to all job types."))


class ISourcePackageRecipeBuildJobSource(Interface):
    """A utility of this interface used to create _things_."""

    def new(build, job):
        """Create a new `ISourcePackageRecipeBuildJob`.

        :param build: An `ISourcePackageRecipeBuild`.
        :param job: An `IJob`.
        :return: `ISourcePackageRecipeBuildJob`.
        """
