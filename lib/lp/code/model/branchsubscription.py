# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['BranchSubscription']

from zope.interface import implements

from sqlobject import ForeignKey

from canonical.database.constants import DEFAULT
from canonical.database.sqlbase import SQLBase
from canonical.database.enumcol import EnumCol

from lp.code.enums import (
    BranchSubscriptionDiffSize, BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel)
from lp.code.interfaces.branchsubscription import IBranchSubscription
from lp.code.interfaces.branch import IBranchNavigationMenu
from lp.code.interfaces.branchtarget import IHasBranchTarget
from lp.registry.interfaces.person import (
    validate_person_not_private_membership)


class BranchSubscription(SQLBase):
    """A relationship between a person and a branch."""

    implements(IBranchSubscription, IBranchNavigationMenu, IHasBranchTarget)

    _table = 'BranchSubscription'

    person = ForeignKey(
        dbName='person', foreignKey='Person',
        storm_validator=validate_person_not_private_membership, notNull=True)
    branch = ForeignKey(dbName='branch', foreignKey='Branch', notNull=True)
    notification_level = EnumCol(enum=BranchSubscriptionNotificationLevel,
                                 notNull=True, default=DEFAULT)
    max_diff_lines = EnumCol(enum=BranchSubscriptionDiffSize,
                             notNull=False, default=DEFAULT)
    review_level = EnumCol(enum=CodeReviewNotificationLevel,
                                 notNull=True, default=DEFAULT)
    subscribed_by = ForeignKey(
        dbName='subscribed_by', foreignKey='Person',
        storm_validator=validate_person_not_private_membership, notNull=True)

    @property
    def target(self):
        """See `IHasBranchTarget`."""
        return self.branch.target
