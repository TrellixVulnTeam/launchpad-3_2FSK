# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Database classes for linking specifications and branches."""

__metaclass__ = type

__all__ = [
    "SpecificationBranch",
    "SpecificationBranchSet",
    ]

from sqlobject import ForeignKey, IN, StringCol

from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import (
    ISpecificationBranch, ISpecificationBranchSet)


class SpecificationBranch(SQLBase):
    """See canonical.launchpad.interfaces.ISpecificationBranch."""
    implements(ISpecificationBranch)

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    specification = ForeignKey(dbName="specification",
                               foreignKey="Specification", notNull=True)
    branch = ForeignKey(dbName="branch", foreignKey="Branch", notNull=True)
    summary = StringCol(dbName="summary", notNull=False, default=None)


class SpecificationBranchSet:

    implements(ISpecificationBranchSet)

    def getSpecificationBranchesForBranches(self, branches, user):
        """See `ISpecificationBranchSet`."""
        branch_ids = [branch.id for branch in branches]
        if not branch_ids:
            return []

        # When specification gain the ability to be private, this
        # method will need to be updated to enforce the privacy checks.
        return SpecificationBranch.select(
            IN(SpecificationBranch.q.branchID, branch_ids))
