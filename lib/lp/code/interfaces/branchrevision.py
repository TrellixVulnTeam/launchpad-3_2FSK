# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""BranchRevision interfaces."""

__metaclass__ = type
__all__ = ['IBranchRevision', 'IBranchRevisionSet']

from zope.interface import Interface, Attribute
from zope.schema import Int

from canonical.launchpad import _


class IBranchRevision(Interface):
    """The association between a revision and a branch.

    BranchRevision records the relation of all revisions that are part of the
    ancestry of a branch. History revisions have an integer sequence, merged
    revisions have sequence set to None.
    """
    # XXX JeroenVermeulen 2010-07-12: We're dropping this column.
    id = Int(title=_('The database revision ID'))

    sequence = Int(
        title=_("Revision number"), required=True,
        description=_("The index of the revision within the branch's history."
            " None for merged revisions which are not part of the history."))
    branch = Attribute("The branch this revision is included in.")
    revision = Attribute("A revision that is included in the branch.")


class IBranchRevisionSet(Interface):
    """The set of all branch-revision associations."""

    def delete(branch_revision_id):
        """Delete the BranchRevision."""
