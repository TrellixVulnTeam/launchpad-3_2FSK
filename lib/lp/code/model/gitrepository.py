# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'get_git_repository_privacy_filter',
    'GitRepository',
    'GitRepositorySet',
    ]

from bzrlib import urlutils
import pytz
from storm.expr import (
    Coalesce,
    Join,
    Or,
    Select,
    SQL,
    )
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from storm.store import Store
from zope.component import getUtility
from zope.interface import implements

from lp.app.enums import (
    InformationType,
    PRIVATE_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    )
from lp.app.interfaces.informationtype import IInformationType
from lp.app.interfaces.launchpad import IPrivacy
from lp.app.interfaces.services import IService
from lp.code.errors import GitTargetError
from lp.code.interfaces.gitrepository import (
    GitIdentityMixin,
    IGitRepository,
    IGitRepositorySet,
    user_has_special_git_repository_access,
    )
from lp.registry.errors import CannotChangeInformationType
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactSource,
    IAccessPolicySource,
    )
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.sharingjob import (
    IRemoveArtifactSubscriptionsJobSource,
    )
from lp.registry.model.accesspolicy import (
    AccessPolicyGrant,
    reconcile_access_for_artifact,
    )
from lp.registry.model.teammembership import TeamParticipation
from lp.services.config import config
from lp.services.database.constants import (
    DEFAULT,
    UTC_NOW,
    )
from lp.services.database.enumcol import EnumCol
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import (
    Array,
    ArrayAgg,
    ArrayIntersects,
    )
from lp.services.propertycache import cachedproperty


def git_repository_modified(repository, event):
    """Update the date_last_modified property when a GitRepository is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on Git repositories.
    """
    repository.date_last_modified = UTC_NOW


class GitRepository(StormBase, GitIdentityMixin):
    """See `IGitRepository`."""

    __storm_table__ = 'GitRepository'

    implements(IGitRepository, IHasOwner, IPrivacy, IInformationType)

    id = Int(primary=True)

    date_created = DateTime(
        name='date_created', tzinfo=pytz.UTC, allow_none=False)
    date_last_modified = DateTime(
        name='date_last_modified', tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, 'Person.id')

    owner_id = Int(name='owner', allow_none=False)
    owner = Reference(owner_id, 'Person.id')

    project_id = Int(name='project', allow_none=True)
    project = Reference(project_id, 'Product.id')

    distribution_id = Int(name='distribution', allow_none=True)
    distribution = Reference(distribution_id, 'Distribution.id')

    sourcepackagename_id = Int(name='sourcepackagename', allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, 'SourcePackageName.id')

    name = Unicode(name='name', allow_none=False)

    information_type = EnumCol(enum=InformationType, notNull=True)
    owner_default = Bool(name='owner_default', allow_none=False)
    target_default = Bool(name='target_default', allow_none=False)
    access_policy = Int(name='access_policy')

    def __init__(self, registrant, owner, name, information_type, date_created,
                 project=None, distribution=None, sourcepackagename=None):
        super(GitRepository, self).__init__()
        self.registrant = registrant
        self.owner = owner
        self.name = name
        self.information_type = information_type
        self.date_created = date_created
        self.date_last_modified = date_created
        self.project = project
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.owner_default = False
        self.target_default = False

    @property
    def unique_name(self):
        names = {"owner": self.owner.name, "repository": self.name}
        if self.project is not None:
            fmt = "~%(owner)s/%(project)s"
            names["project"] = self.project.name
        elif self.distribution is not None:
            fmt = "~%(owner)s/%(distribution)s/+source/%(source)s"
            names["distribution"] = self.distribution.name
            names["source"] = self.sourcepackagename.name
        else:
            fmt = "~%(owner)s"
        fmt += "/g/%(repository)s"
        return fmt % names

    def __repr__(self):
        return "<GitRepository %r (%d)>" % (self.unique_name, self.id)

    @property
    def target(self):
        """See `IGitRepository`."""
        if self.project is None:
            if self.distribution is None:
                return self.owner
            else:
                return self.distro_source_package
        else:
            return self.project

    def setTarget(self, user, target):
        """See `IGitRepository`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def _getSearchClauses(self):
        if self.project is not None:
            return [GitRepository.project == self.project]
        elif self.distribution is not None:
            return [
                GitRepository.distribution == self.distribution,
                GitRepository.sourcepackagename == self.sourcepackagename,
                ]
        else:
            return [
                GitRepository.project == None,
                GitRepository.distribution == None,
                ]

    def setOwnerDefault(self, value):
        """See `IGitRepository`."""
        if value:
            # Look for an existing owner-target default and remove it.  It
            # may also be a target default, in which case we need to remove
            # that too.
            clauses = [
                GitRepository.owner == self.owner,
                GitRepository.owner_default == True,
                ] + self._getSearchClauses()
            existing = Store.of(self).find(GitRepository, *clauses).one()
            if existing is not None:
                existing.target_default = False
                existing.owner_default = False
        self.owner_default = value

    def setTargetDefault(self, value):
        """See `IGitRepository`."""
        if value:
            # Any target default must also be an owner-target default.
            self.setOwnerDefault(True)
            # Look for an existing target default and remove it.
            clauses = [
                GitRepository.target_default == True,
                ] + self._getSearchClauses()
            existing = Store.of(self).find(GitRepository, *clauses).one()
            if existing is not None:
                existing.target_default = False
        self.target_default = value

    @property
    def displayname(self):
        return self.git_identity

    def getInternalPath(self):
        """See `IGitRepository`."""
        # This may need to change later to improve support for sharding.
        return str(self.id)

    def codebrowse_url(self):
        """See `IGitRepository`."""
        return urlutils.join(
            config.codehosting.git_browse_root, self.unique_name)

    @cachedproperty
    def distro_source_package(self):
        """See `IGitRepository`."""
        if self.distribution is not None:
            return self.distribution.getSourcePackage(self.sourcepackagename)
        else:
            return None

    @property
    def private(self):
        return self.information_type in PRIVATE_INFORMATION_TYPES

    def _reconcileAccess(self):
        """Reconcile the repository's sharing information.

        Takes the information_type and target and makes the related
        AccessArtifact and AccessPolicyArtifacts match.
        """
        wanted_links = None
        pillars = []
        # For private personal repositories, we calculate the wanted grants.
        if (not self.project and not self.distribution and
            not self.information_type in PUBLIC_INFORMATION_TYPES):
            aasource = getUtility(IAccessArtifactSource)
            [abstract_artifact] = aasource.ensure([self])
            wanted_links = set(
                (abstract_artifact, policy) for policy in
                getUtility(IAccessPolicySource).findByTeam([self.owner]))
        else:
            # We haven't yet quite worked out how distribution privacy
            # works, so only work for projects for now.
            if self.project is not None:
                pillars = [self.project]
        reconcile_access_for_artifact(
            self, self.information_type, pillars, wanted_links)

    def addToLaunchBag(self, launchbag):
        """See `IGitRepository`."""
        launchbag.add(self.project)
        launchbag.add(self.distribution)

    @cachedproperty
    def _known_viewers(self):
        """A set of known persons able to view this repository.

        This method must return an empty set or repository searches will
        trigger late evaluation.  Any 'should be set on load' properties
        must be done by the repository search.

        If you are tempted to change this method, don't. Instead see
        visibleByUser which defines the just-in-time policy for repository
        visibility, and IGitCollection which honours visibility rules.
        """
        return set()

    def visibleByUser(self, user):
        """See `IGitRepository`."""
        if self.information_type in PUBLIC_INFORMATION_TYPES:
            return True
        elif user is None:
            return False
        elif user.id in self._known_viewers:
            return True
        else:
            # XXX cjwatson 2015-02-06: Fill this in once IGitCollection is
            # in place.
            return False

    def getAllowedInformationTypes(self, user):
        """See `IGitRepository`."""
        if user_has_special_git_repository_access(user):
            # Admins can set any type.
            types = set(PUBLIC_INFORMATION_TYPES + PRIVATE_INFORMATION_TYPES)
        else:
            # Otherwise the permitted types are defined by the namespace.
            # XXX cjwatson 2015-01-19: Define permitted types properly.  For
            # now, non-admins only get public repository access.
            types = set(PUBLIC_INFORMATION_TYPES)
        return types

    def transitionToInformationType(self, information_type, user,
                                    verify_policy=True):
        """See `IGitRepository`."""
        if self.information_type == information_type:
            return
        if (verify_policy and
            information_type not in self.getAllowedInformationTypes(user)):
            raise CannotChangeInformationType("Forbidden by project policy.")
        self.information_type = information_type
        self._reconcileAccess()
        # XXX cjwatson 2015-02-05: Once we have repository subscribers, we
        # need to grant them access if necessary.  For now, treat the owner
        # as always subscribed, which is just about enough to make the
        # GitCollection tests pass.
        if information_type in PRIVATE_INFORMATION_TYPES:
            # Grant the subscriber access if they can't see the repository.
            service = getUtility(IService, "sharing")
            blind_subscribers = service.getPeopleWithoutAccess(
                self, [self.owner])
            if len(blind_subscribers):
                service.ensureAccessGrants(
                    blind_subscribers, user, gitrepositories=[self],
                    ignore_permissions=True)
        # As a result of the transition, some subscribers may no longer have
        # access to the repository.  We need to run a job to remove any such
        # subscriptions.
        getUtility(IRemoveArtifactSubscriptionsJobSource).create(user, [self])

    def setOwner(self, new_owner, user):
        """See `IGitRepository`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def destroySelf(self):
        raise NotImplementedError


class GitRepositorySet:
    """See `IGitRepositorySet`."""

    implements(IGitRepositorySet)

    def new(self, registrant, owner, target, name, information_type=None,
            date_created=DEFAULT):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def getPersonalRepository(self, person, repository_name):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def getProjectRepository(self, person, project, repository_name=None):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def getPackageRepository(self, person, distribution, sourcepackagename,
                              repository_name=None):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitNamespace is in
        # place.
        raise NotImplementedError

    def getByPath(self, user, path):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitLookup is in place.
        raise NotImplementedError

    def getDefaultRepository(self, target, owner=None):
        """See `IGitRepositorySet`."""
        clauses = []
        if IProduct.providedBy(target):
            clauses.append(GitRepository.project == target)
        elif IDistributionSourcePackage.providedBy(target):
            clauses.append(GitRepository.distribution == target.distribution)
            clauses.append(
                GitRepository.sourcepackagename == target.sourcepackagename)
        elif owner is not None:
            raise GitTargetError(
                "Cannot get a person's default Git repository for another "
                "person.")
        if owner is not None:
            clauses.append(GitRepository.owner == owner)
            clauses.append(GitRepository.owner_default == True)
        else:
            clauses.append(GitRepository.target_default == True)
        return IStore(GitRepository).find(GitRepository, *clauses).one()

    def getRepositories(self, limit=50, eager_load=True):
        """See `IGitRepositorySet`."""
        # XXX cjwatson 2015-02-06: Fill this in once IGitCollection is in
        # place.
        raise NotImplementedError


def get_git_repository_privacy_filter(user):
    public_filter = GitRepository.information_type.is_in(
        PUBLIC_INFORMATION_TYPES)

    if user is None:
        return [public_filter]

    artifact_grant_query = Coalesce(
        ArrayIntersects(
            SQL("GitRepository.access_grants"),
            Select(
                ArrayAgg(TeamParticipation.teamID),
                tables=TeamParticipation,
                where=(TeamParticipation.person == user)
            )), False)

    policy_grant_query = Coalesce(
        ArrayIntersects(
            Array(GitRepository.access_policy),
            Select(
                ArrayAgg(AccessPolicyGrant.policy_id),
                tables=(AccessPolicyGrant,
                        Join(TeamParticipation,
                            TeamParticipation.teamID ==
                            AccessPolicyGrant.grantee_id)),
                where=(TeamParticipation.person == user)
            )), False)

    return [Or(public_filter, artifact_grant_query, policy_grant_query)]
