# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snapshot adapter for the Storm result set."""

from storm.zope.interfaces import IResultSet

from zope.interface import implementer
from zope.component import adapter

from lazr.lifecycle.interfaces import ISnapshotValueFactory

from canonical.launchpad.helpers import shortlist

@implementer(ISnapshotValueFactory)
@adapter(IResultSet) # And ISQLObjectResultSet.
def snapshot_sql_result(value):
    # SQLMultipleJoin and SQLRelatedJoin return
    # SelectResults, which doesn't really help the Snapshot
    # object. We therefore list()ify the values; this isn't
    # perfect but allows deltas to be generated reliably.

    # DO NOT CHECK IN
    #return shortlist(value, longest_expected=100, hardlimit=5000)
    return shortlist(value, longest_expected=100, hardlimit=105)
