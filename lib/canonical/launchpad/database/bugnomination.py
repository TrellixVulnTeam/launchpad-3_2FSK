# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Database classes related to bug nomination.

A bug nomination is a suggestion from a user that a bug be fixed in a
particular distro release or product series. A bug may have zero, one,
or more nominations.
"""

__metaclass__ = type
__all__ = [
    'BugNomination',
    'BugNominationSet']

from datetime import datetime

import pytz

from zope.component import getUtility
from zope.interface import implements

from sqlobject import ForeignKey, SQLObjectNotFound

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import (
    IBugNomination, IBugTaskSet, IBugNominationSet, NotFoundError)
from canonical.lp import dbschema

class BugNomination(SQLBase):
    implements(IBugNomination)
    _table = "BugNomination"

    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    decider = ForeignKey(
        dbName='decider', foreignKey='Person', notNull=False, default=None)
    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    date_decided = UtcDateTimeCol(notNull=False, default=None)
    distrorelease = ForeignKey(
        dbName='distrorelease', foreignKey='DistroRelease',
        notNull=False, default=None)
    productseries = ForeignKey(
        dbName='productseries', foreignKey='ProductSeries',
        notNull=False, default=None)
    bug = ForeignKey(dbName='bug', foreignKey='Bug', notNull=True)
    status = dbschema.EnumCol(
        dbName='status', notNull=True, schema=dbschema.BugNominationStatus,
        default=dbschema.BugNominationStatus.PROPOSED)

    @property
    def target(self):
        """See IBugNomination."""
        return self.distrorelease or self.productseries

    def approve(self, approver):
        """See IBugNomination."""
        self.status = dbschema.BugNominationStatus.APPROVED
        self.decider = approver
        self.date_decided = datetime.now(pytz.timezone('UTC'))

        bugtaskset = getUtility(IBugTaskSet)
        if self.distrorelease:
            # Figure out which packages are affected in this distro for
            # this bug.
            targets = []
            distribution = self.distrorelease.distribution
            distrorelease = self.distrorelease
            for task in self.bug.bugtasks:
                if not task.distribution == distribution:
                    continue
                if task.sourcepackagename:
                    return bugtaskset.createTask(
                        bug=self.bug, owner=approver,
                        distrorelease=distrorelease,
                        sourcepackagename=task.sourcepackagename)
                else:
                    return bugtaskset.createTask(
                        bug=self.bug, owner=approver,
                        distrorelease=distrorelease)
        else:
            return bugtaskset.createTask(
                bug=self.bug, owner=approver, productseries=self.productseries)

    def decline(self, decliner):
        """See IBugNomination."""
        self.status = dbschema.BugNominationStatus.DECLINED
        self.decider = decliner
        self.date_decided = datetime.now(pytz.timezone('UTC'))

    def isProposed(self):
        """See IBugNomination."""
        return self.status == dbschema.BugNominationStatus.PROPOSED

    def isDeclined(self):
        """See IBugNomination."""
        return self.status == dbschema.BugNominationStatus.DECLINED

    def isApproved(self):
        """See IBugNomination."""
        return self.status == dbschema.BugNominationStatus.APPROVED


class BugNominationSet:
    """See IBugNominationSet."""
    implements(IBugNominationSet)

    def get(self, id):
        """See IBugNominationSet."""
        try:
            return BugNomination.get(id)
        except SQLObjectNotFound:
            raise NotFoundError(id)
