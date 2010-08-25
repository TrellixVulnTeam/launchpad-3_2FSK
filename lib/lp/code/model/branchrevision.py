# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['BranchRevision', 'BranchRevisionSet']

from storm.locals import (
    Int,
    Reference,
    Storm,
    )
from zope.interface import implements

from canonical.launchpad.interfaces.lpstorm import IMasterStore
from lp.code.interfaces.branchrevision import (
    IBranchRevision,
    IBranchRevisionSet,
    )


class BranchRevision(Storm):
    """See `IBranchRevision`."""
    __storm_table__ = 'BranchRevision'

    id = Int(primary=True)

    implements(IBranchRevision)

    branch_id = Int(name='branch', allow_none=False)
    branch = Reference(branch_id, 'Branch.id')

    revision_id = Int(name='revision', allow_none=False)
    revision = Reference(revision_id, 'Revision.id')

    sequence = Int(name='sequence', allow_none=True)

    def __init__(self, branch, revision, sequence=None):
        self.branch = branch
        self.revision = revision
        self.sequence = sequence


class BranchRevisionSet:
    """See `IBranchRevisionSet`."""

    implements(IBranchRevisionSet)

    def delete(self, branch_revision_id):
        """See `IBranchRevisionSet`."""
        match = IMasterStore(BranchRevision).find(
            BranchRevision, BranchRevision.id == branch_revision_id)
        match.remove()
