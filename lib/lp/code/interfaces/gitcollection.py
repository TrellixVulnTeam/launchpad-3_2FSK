# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A collection of Git repositories.

See `IGitCollection` for more details.
"""

__metaclass__ = type
__all__ = [
    'IAllGitRepositories',
    'IGitCollection',
    'InvalidGitFilter',
    ]

from zope.interface import Interface


class InvalidGitFilter(Exception):
    """Raised when an `IGitCollection` cannot apply the given filter."""


class IGitCollection(Interface):
    """A collection of Git repositories.

    An `IGitCollection` is an immutable collection of Git repositories. It
    has two kinds of methods: filter methods and query methods.

    Query methods get information about the contents of the collection. See
    `IGitCollection.count` and `IGitCollection.getRepositories`.

    Filter methods return new IGitCollection instances that have some sort
    of restriction. Examples include `ownedBy`, `visibleByUser` and
    `inProject`.

    Implementations of this interface are not 'content classes'. That is, they
    do not correspond to a particular row in the database.

    This interface is intended for use within Launchpad, not to be exported as
    a public API.
    """

    def count():
        """The number of repositories in this collection."""

    def is_empty():
        """Is this collection empty?"""

    def ownerCounts():
        """Return the number of different repository owners.

        :return: a tuple (individual_count, team_count) containing the
            number of individuals and teams that own repositories in this
            collection.
        """

    def getRepositories(eager_load=False):
        """Return a result set of all repositories in this collection.

        The returned result set will also join across the specified tables
        as defined by the arguments to this function.  These extra tables
        are joined specifically to allow the caller to sort on values not in
        the GitRepository table itself.

        :param eager_load: If True trigger eager loading of all the related
            objects in the collection.
        """

    def getRepositoryIds():
        """Return a result set of all repository ids in this collection."""

    def getTeamsWithRepositories(person):
        """Return the teams that person is a member of that have
        repositories."""

    def inProject(project):
        """Restrict the collection to repositories in 'project'."""

    def inProjectGroup(projectgroup):
        """Restrict the collection to repositories in 'projectgroup'."""

    def inDistribution(distribution):
        """Restrict the collection to repositories in 'distribution'."""

    def inDistributionSourcePackage(distro_source_package):
        """Restrict to repositories in a package for a distribution."""

    def isPersonal():
        """Restrict the collection to personal repositories."""

    def isPrivate():
        """Restrict the collection to private repositories."""

    def isExclusive():
        """Restrict the collection to repositories owned by exclusive
        people."""

    def ownedBy(person):
        """Restrict the collection to repositories owned by 'person'."""

    def ownedByTeamMember(person):
        """Restrict the collection to repositories owned by 'person' or a
        team of which person is a member.
        """

    def registeredBy(person):
        """Restrict the collection to repositories registered by 'person'."""

    def search(term):
        """Search the collection for repositories matching 'term'.

        :param term: A string.
        :return: A `ResultSet` of repositories that matched.
        """

    def visibleByUser(person):
        """Restrict the collection to repositories that person is allowed to
        see."""

    def withIds(*repository_ids):
        """Restrict the collection to repositories with the specified ids."""


class IAllGitRepositories(IGitCollection):
    """A `IGitCollection` representing all Git repositories in Launchpad."""
