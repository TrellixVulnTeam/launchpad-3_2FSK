# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface of the `SourcePackageRecipe` content type."""

__metaclass__ = type
__all__ = [
    'ForbiddenInstruction',
    'ISourcePackageRecipe',
    'ISourcePackageRecipeData',
    'ISourcePackageRecipeSource',
    'TooNewRecipeFormat',
    ]

from lazr.restful.fields import CollectionField, Reference

from zope.interface import Attribute, Interface
from zope.schema import Datetime, Object, TextLine

from canonical.launchpad import _
from canonical.launchpad.validators.name import name_validator

from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.sourcepackagename import ISourcePackageName

from lp.code.interfaces.branch import IBranch


class ForbiddenInstruction(Exception):
    """A forbidden instruction was found in the recipe."""

    def __init__(self, instruction_name):
        super(ForbiddenInstruction, self).__init__()
        self.instruction_name = instruction_name


class TooNewRecipeFormat(Exception):
    """The format of the recipe supplied was too new."""

    def __init__(self, supplied_format, newest_supported):
        super(TooNewRecipeFormat, self).__init__()
        self.supplied_format = supplied_format
        self.newest_supported = newest_supported


class ISourcePackageRecipeData(Interface):
    """A recipe as database data, not text."""

    base_branch = Object(
        schema=IBranch, title=_("Base branch"), description=_(
            "The base branch to use when building the recipe."))

    deb_version_template = TextLine(
        title=_('deb-version template'),
        description = _(
            'The template that will be used to generate a deb version.'),)


class ISourcePackageRecipe(IHasOwner, ISourcePackageRecipeData):
    """An ISourcePackageRecipe describes how to build a source package.

    More precisely, it describes how to combine a number of branches into a
    debianized source tree.
    """

    date_created = Datetime(required=True, readonly=True)
    date_last_modified = Datetime(required=True, readonly=True)

    registrant = Reference(
        IPerson, title=_("The person who created this recipe"), readonly=True)
    owner = Reference(
        IPerson, title=_("The person or team who can edit this recipe"),
        readonly=False)
    distroseries = Reference(
        IDistroSeries, title=_("The distroseries this recipe will build a "
                               "source package for"),
        readonly=True)
    sourcepackagename = Reference(
        ISourcePackageName, title=_("The name of the source package this "
                                    "recipe will build a source package"),
        readonly=True)

    name = TextLine(
            title=_("Name"), required=True,
            constraint=name_validator,
            description=_("The name of this recipe."))

    builder_recipe = Attribute(
        _("The bzr-builder data structure for the recipe."))

    def getReferencedBranches():
        """An iterator of the branches referenced by this recipe."""

    def requestBuild(archive, distroseries, requester, pocket):
        """Request that the recipe be built in to the specified archive.

        :param archive: The IArchive which you want the build to end up in.
        :param requester: the person requesting the build.
        :param pocket: the pocket that should be targeted.
        :raises: various specific upload errors if the requestor is not
            able to upload to the archive.
        """

    builds = CollectionField(title=_("Related SourcePackageRecpieBuilds."),
        value_type=Reference(schema=Interface))


class ISourcePackageRecipeSource(Interface):
    """A utility of this interface can be used to create and access recipes.
    """

    def new(registrant, owner, distroseries, sourcepackagename, name,
            builder_recipe):
        """Create an `ISourcePackageRecipe`."""
