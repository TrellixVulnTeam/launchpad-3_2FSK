# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Git repository interfaces."""

__metaclass__ = type

__all__ = [
    'GitIdentityMixin',
    'git_repository_name_validator',
    'IGitRepository',
    'IGitRepositorySet',
    'user_has_special_git_repository_access',
    ]

import re

from lazr.restful.fields import (
    Reference,
    ReferenceChoice,
    )
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Int,
    Text,
    TextLine,
    )

from lp import _
from lp.app.enums import InformationType
from lp.app.validators import LaunchpadValidationError
from lp.code.interfaces.hasgitrepositories import IHasGitRepositories
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.role import IPersonRoles
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )


GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE = _(
    "Git repository names must start with a number or letter.  The characters "
    "+, -, _, . and @ are also allowed after the first character.  Repository "
    "names must not end with \".git\".")


# This is a copy of the pattern in database/schema/patch-2209-61-0.sql.
# Don't change it without changing that.
valid_git_repository_name_pattern = re.compile(
    r"^(?i)[a-z0-9][a-z0-9+\.\-@_]*\Z")


def valid_git_repository_name(name):
    """Return True iff the name is valid as a Git repository name.

    The rules for what is a valid Git repository name are described in
    GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE.
    """
    if (not name.endswith(".git") and
        valid_git_repository_name_pattern.match(name)):
        return True
    return False


def git_repository_name_validator(name):
    """Return True if the name is valid, or raise a LaunchpadValidationError.
    """
    if not valid_git_repository_name(name):
        raise LaunchpadValidationError(
            _("Invalid Git repository name '${name}'. ${message}",
              mapping={
                  "name": name,
                  "message": GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE,
                  }))
    return True


class IGitRepositoryView(Interface):
    """IGitRepository attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), readonly=True, required=True)

    date_created = Datetime(
        title=_("Date created"), required=True, readonly=True)

    date_last_modified = Datetime(
        title=_("Date last modified"), required=True, readonly=True)

    registrant = PublicPersonChoice(
        title=_("Registrant"), required=True, readonly=True,
        vocabulary="ValidPersonOrTeam",
        description=_("The person who registered this Git repository."))

    owner = PersonChoice(
        title=_("Owner"), required=True, readonly=False,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_(
            "The owner of this Git repository. This controls who can modify "
            "the repository."))

    project = ReferenceChoice(
        title=_("Project"), required=False, readonly=True,
        vocabulary="Product", schema=IProduct,
        description=_(
            "The project that this Git repository belongs to, or None."))

    # The distribution and sourcepackagename attributes are exported
    # together as distro_source_package.
    distribution = Choice(
        title=_("Distribution"), required=False,
        vocabulary="Distribution",
        description=_(
            "The distribution that this Git repository belongs to, or None."))

    sourcepackagename = Choice(
        title=_("Source Package Name"), required=False,
        vocabulary="SourcePackageName",
        description=_(
            "The source package that this Git repository belongs to, or None. "
            "Source package repositories always belong to a distribution."))

    distro_source_package = Reference(
        title=_(
            "The IDistributionSourcePackage that this Git repository belongs "
            "to, or None."),
        schema=IDistributionSourcePackage, required=False, readonly=True)

    target = Reference(
        title=_("Target"), required=True, readonly=True,
        schema=IHasGitRepositories,
        description=_("The target of the repository."))

    information_type = Choice(
        title=_("Information Type"), vocabulary=InformationType,
        required=True, readonly=True, default=InformationType.PUBLIC,
        description=_(
            "The type of information contained in this repository."))

    owner_default = Bool(
        title=_("Owner default"), required=True, readonly=True,
        description=_(
            "Whether this repository is the default for its owner and "
            "target."))

    target_default = Bool(
        title=_("Target default"), required=True, readonly=True,
        description=_(
            "Whether this repository is the default for its target."))

    unique_name = Text(
        title=_("Unique name"), readonly=True,
        description=_(
            "Unique name of the repository, including the owner and project "
            "names."))

    displayname = Text(
        title=_("Display name"), readonly=True,
        description=_("Display name of the repository."))

    shortened_path = Attribute(
        "The shortest reasonable version of the path to this repository.")

    git_identity = Text(
        title=_("Git identity"), readonly=True,
        description=_(
            "If this is the default repository for some target, then this is "
            "'lp:' plus a shortcut version of the path via that target.  "
            "Otherwise it is simply 'lp:' plus the unique name."))

    def getCodebrowseUrl():
        """Construct a browsing URL for this branch."""

    def addToLaunchBag(launchbag):
        """Add information about this branch to `launchbag'.

        Use this when traversing to this branch in the web UI.

        In particular, add information about the branch's target to the
        launchbag. If the branch has a product, add that; if it has a source
        package, add lots of information about that.

        :param launchbag: `ILaunchBag`.
        """

    def visibleByUser(user):
        """Can the specified user see this repository?"""

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this repository.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def getInternalPath():
        """Get the internal path to this repository.

        This is used on the storage backend.
        """

    def getRepositoryLinks():
        """Return a sorted list of `ICanHasLinkedGitRepository` objects.

        There is one result for each related object that the repository is
        linked to.  For example, in the case where a branch is linked to a
        project and is also its owner's preferred branch for that project,
        the link objects for both the project and the person-project are
        returned.

        The sorting uses the defined order of the linked objects where the
        more important links are sorted first.
        """

    def getRepositoryIdentities():
        """A list of aliases for a repository.

        Returns a list of tuples of path and context object.  There is at
        least one alias for any repository, and that is the repository
        itself.  For linked repositories, the context object is the
        appropriate linked object.

        Where a repository is linked to a product or a distribution source
        package, the repository is available through a number of different
        URLs.  These URLs are the aliases for the repository.

        For example, a repository which is linked to the 'fooix' project and
        which is also its owner's preferred repository for that project is
        accessible using:
          fooix - the linked object is the project fooix
          ~fooix-owner/fooix - the linked object is the person-project
              ~fooix-owner and fooix
          ~fooix-owner/fooix/g/fooix - the unique name of the repository
              where the linked object is the repository itself.
        """


class IGitRepositoryModerateAttributes(Interface):
    """IGitRepository attributes that can be edited by more than one community.
    """

    # XXX cjwatson 2015-01-29: Add some advice about default repository
    # naming.
    name = TextLine(
        title=_("Name"), required=True,
        constraint=git_repository_name_validator,
        description=_(
            "The repository name. Keep very short, unique, and descriptive, "
            "because it will be used in URLs."))


class IGitRepositoryModerate(Interface):
    """IGitRepository methods that can be called by more than one community."""

    def transitionToInformationType(information_type, user,
                                    verify_policy=True):
        """Set the information type for this repository.

        :param information_type: The `InformationType` to transition to.
        :param user: The `IPerson` who is making the change.
        :param verify_policy: Check if the new information type complies
            with the `IGitNamespacePolicy`.
        """


class IGitRepositoryEdit(Interface):
    """IGitRepository methods that require launchpad.Edit permission."""

    def setOwnerDefault(value):
        """Set whether this repository is the default for its owner-target.

        :param value: True if this repository should be the owner-target
        default, otherwise False.
        """

    def setTargetDefault(value):
        """Set whether this repository is the default for its target.

        :param value: True if this repository should be the target default,
        otherwise False.
        """

    def setOwner(new_owner, user):
        """Set the owner of the repository to be `new_owner`."""

    def setTarget(user, target):
        """Set the target of the repository."""

    def destroySelf():
        """Delete the specified repository."""


class IGitRepository(IGitRepositoryView, IGitRepositoryModerateAttributes,
                     IGitRepositoryModerate, IGitRepositoryEdit):
    """A Git repository."""

    private = Bool(
        title=_("Repository is confidential"), required=False, readonly=True,
        description=_("This repository is visible only to its subscribers."))


class IGitRepositorySet(Interface):
    """Interface representing the set of Git repositories."""

    def new(registrant, owner, target, name, information_type=None,
            date_created=None):
        """Create a Git repository and return it.

        :param registrant: The `IPerson` who registered the new repository.
        :param owner: The `IPerson` who owns the new repository.
        :param target: The `IProduct`, `IDistributionSourcePackage`, or
            `IPerson` that the new repository is associated with.
        :param name: The repository name.
        :param information_type: Set the repository's information type to
            one different from the target's default.  The type must conform
            to the target's code sharing policy.  (optional)
        """

    def getByPath(user, path):
        """Find a repository by its path.

        Any of these forms may be used, with or without a leading slash:
            Unique names:
                ~OWNER/PROJECT/g/NAME
                ~OWNER/DISTRO/+source/SOURCE/g/NAME
                ~OWNER/g/NAME
            Owner-target default aliases:
                ~OWNER/PROJECT
                ~OWNER/DISTRO/+source/SOURCE
            Official aliases:
                PROJECT
                DISTRO/+source/SOURCE

        Return None if no match was found.
        """

    def getPersonalRepository(person, repository_name):
        """Find a personal repository."""

    def getProjectRepository(person, project, repository_name=None):
        """Find a project repository."""

    def getPackageRepository(person, distribution, sourcepackagename,
                             repository_name=None):
        """Find a package repository."""

    def getDefaultRepository(target, owner=None):
        """Get the default repository for a target or owner-target.

        :param target: An `IHasGitRepositories`.
        :param owner: An `IPerson`, in which case search for that person's
            default repository for this target; or None, in which case
            search for the overall default repository for this target.
        """

    def getRepositories(limit=50, eager_load=True):
        """Return a collection of repositories.

        :param eager_load: If True (the default because this is used in the
            web service and it needs the related objects to create links)
            eager load related objects (projects, etc.).
        """


class GitIdentityMixin:
    """This mixin class determines Git repository paths.

    Used by both the model GitRepository class and the browser repository
    listing item.  This allows the browser code to cache the associated
    links which reduces query counts.
    """

    @property
    def shortened_path(self):
        """See `IGitRepository`."""
        path, context = self.getRepositoryIdentities()[0]
        return path

    @property
    def git_identity(self):
        """See `IGitRepository`."""
        return "lp:" + self.shortened_path

    def getRepositoryLinks(self):
        """See `IGitRepository`."""
        # XXX cjwatson 2015-02-06: This will return shortcut links once
        # they're implemented.
        return []

    def getRepositoryIdentities(self):
        """See `IGitRepository`."""
        identities = [
            (link.path, link.context) for link in self.getRepositoryLinks()]
        identities.append((self.unique_name, self))
        return identities


def user_has_special_git_repository_access(user):
    """Admins have special access.

    :param user: An `IPerson` or None.
    """
    if user is None:
        return False
    roles = IPersonRoles(user)
    if roles.in_admin:
        return True
    return False
