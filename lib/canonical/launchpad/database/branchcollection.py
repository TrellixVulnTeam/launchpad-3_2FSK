# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Implementations of `IBranchCollection`."""

__metaclass__ = type
__all__ = [
    'GenericBranchCollection',
    ]

from storm.expr import And, LeftJoin, Join, Or, Select

from zope.interface import implements

from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet)
from canonical.launchpad.database.branch import Branch
from canonical.launchpad.database.branchsubscription import BranchSubscription
from canonical.launchpad.database.product import Product
from canonical.launchpad.database.teammembership import TeamParticipation
from canonical.launchpad.interfaces.branch import (
    user_has_special_branch_access)
from canonical.launchpad.interfaces.branchcollection import IBranchCollection
from canonical.launchpad.interfaces.codehosting import LAUNCHPAD_SERVICES


class GenericBranchCollection:
    """See `IBranchCollection`."""

    implements(IBranchCollection)

    def __init__(self, store, branch_filter_expressions=None, tables=None,
                 name=None, displayname=None):
        self._store = store
        if branch_filter_expressions is None:
            branch_filter_expressions = []
        self._branch_filter_expressions = branch_filter_expressions
        if tables is None:
            tables = [Branch, LeftJoin(Product, Branch.product == Product.id)]
        self._tables = tables
        self.name = name
        self.displayname = displayname

    @property
    def count(self):
        """See `IBranchCollection`."""
        return self.getBranches().count()

    def filterBy(self, tables, *expressions):
        """Return a subset of this collection, filtered by 'expressions'."""
        # No need for explicit 'tables': http://paste.ubuntu.com/118711/
        return self.__class__(
            self._store, self._branch_filter_expressions + list(expressions),
            self._tables + tables, name=self.name,
            displayname=self.displayname)

    def getBranches(self):
        """See `IBranchCollection`."""
        results = self._store.using(*(self._tables)).find(
            Branch, *(self._branch_filter_expressions))
        def identity(x):
            return x
        # Decorate the result set to work around bug 217644.
        return DecoratedResultSet(results, identity)

    def inSourcePackage(self, source_package):
        """See `IBranchCollection`."""
        return self.filterBy(
            [], Branch.distroseries == source_package.distroseries,
            Branch.sourcepackagename == source_package.sourcepackagename)

    def inProduct(self, product):
        """See `IBranchCollection`."""
        return self.filterBy([], Branch.product == product)

    def inProject(self, project):
        """See `IBranchCollection`."""
        return self.filterBy(
            [], Product.project == project.id)

    def ownedBy(self, person):
        """See `IBranchCollection`."""
        return self.filterBy([], Branch.owner == person)

    def registeredBy(self, person):
        """See `IBranchCollection`."""
        return self.filterBy([], Branch.registrant == person)

    def relatedTo(self, person):
        """See `IBranchCollection`."""
        return self.filterBy(
            [Join(BranchSubscription,
                  BranchSubscription.branch == Branch.id)],
            Or(Branch.owner == person,
               Branch.registrant == person,
               BranchSubscription.person == person))

    def subscribedBy(self, person):
        """See `IBranchCollection`."""
        return self.filterBy(
            [Join(BranchSubscription,
                  BranchSubscription.branch == Branch.id)],
            BranchSubscription.person == person)

    def visibleByUser(self, person):
        """See `IBranchCollection`."""
        if (person == LAUNCHPAD_SERVICES or
            user_has_special_branch_access(person)):
            return self
        # Do this in a sub-query to avoid making the main query a DISTINCT
        # one, which would make sorting and the like harder.
        visible_branches = Select(
            Branch.id,
            Or(Branch.private == False,
               And(Branch.owner == TeamParticipation.teamID,
                   TeamParticipation.person == person),
               And(BranchSubscription.branch == Branch.id,
                   BranchSubscription.person == TeamParticipation.teamID,
                   TeamParticipation.person == person)),
            distinct=True)
        return self.filterBy([], Branch.id.is_in(visible_branches))

    def withLifecycleStatus(self, *statuses):
        """See `IBranchCollection`."""
        return self.filterBy([], Branch.lifecycle_status.is_in(statuses))
