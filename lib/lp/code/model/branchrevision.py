# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['BranchRevision', 'BranchRevisionSet']

from zope.interface import implements

from sqlobject import ForeignKey, IntCol

from canonical.database.sqlbase import SQLBase
from lp.code.interfaces.branchrevision import IBranchRevision, IBranchRevisionSet
class BranchRevision(SQLBase):
    """See IBranchRevision."""

    implements(IBranchRevision)

    _table = 'BranchRevision'

    branch = ForeignKey(
        dbName='branch', foreignKey='Branch', notNull=True)

    sequence = IntCol()
    revision = ForeignKey(
        dbName='revision', foreignKey='Revision', notNull=True)


class BranchRevisionSet:
    """See IBranchRevisionSet."""

    implements(IBranchRevisionSet)

    def delete(self, branch_revision_id):
        """See `IBranchRevisionSet`."""
        BranchRevision.delete(branch_revision_id)
