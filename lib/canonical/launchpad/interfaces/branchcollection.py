# Copyright 2009 Canonical Ltd.  All rights reserved.

"""A collection of branches."""

__metaclass__ = type
__all__ = [
    'IBranchCollection',
    ]

from zope.interface import Interface


class IBranchCollection(Interface):
    """A collection of branches.

    An `IBranchCollection` is an immutable collection of branches. It has two
    kinds of methods: filter methods and query methods.

    Query methods get information about the contents of collection. See
    `IBranchCollection.count` and `IBranchCollection.getBranches`.

    Filter methods return new IBranchCollection instances that have some sort
    of restriction. Examples include `ownedBy`, `visibleByUser` and
    `inProduct`.
    """

    # Note to developers: This interface should be extended with more query
    # methods. It would be great to have methods like getRecentRevisions on
    # arbitrary branch collections. Other statistical methods would be good
    # too, e.g. number of different branch owners in this collection.

    # XXX: Write tests to guarantee that adapted objects are being secured via
    # this interface.

    def count():
        """The number of branches in this collection."""

    def getBranches():
        """Return a result set of all branches in this collection."""

    def inProduct(product):
        """Restrict the collection to branches in 'product'."""

    def inProject(project):
        """Restrict the collection to branches in 'project'."""

    def inSourcePackage(package):
        """Restrict the collection to branches in 'package'."""

    def ownedBy(person):
        """Restrict the collection to branches owned by 'person'."""

    def registeredBy(person):
        """Restrict the collection to branches registered by 'person'."""

    def relatedTo(person):
        """Restrict the collection to branches related to 'person'.

        That is, branches that 'person' owns, registered or is subscribed to.
        """

    def subscribedBy(person):
        """Restrict the collection to branches subscribed to by 'person'."""

    def visibleByUser(person):
        """Restrict the collection to branches that person is allowed to see.
        """

    def withLifecycleStatus(*statuses):
        """Restrict the collection to branches with the given statuses."""

# XXX: adapters / easy access methods for common views / concepts
# - source package
# - project
# - global set (i.e. IBranchSet)


# XXX: Merge in trunk and resolve conflicts
