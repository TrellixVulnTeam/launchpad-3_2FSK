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
from canonical.database.enumcol import EnumCol

from canonical.lp import dbschema

from canonical.launchpad.interfaces import (
    IBugNomination, IBugTaskSet, IBugNominationSet,
    ILaunchpadCelebrities, NotFoundError)

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
    status = EnumCol(
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
                    bugtaskset.createTask(
                        bug=self.bug, owner=approver,
                        distrorelease=distrorelease,
                        sourcepackagename=task.sourcepackagename)
                else:
                    bugtaskset.createTask(
                        bug=self.bug, owner=approver,
                        distrorelease=distrorelease)
        else:
            bugtaskset.createTask(
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

    def canApprove(self, person):
        """See IBugNomination."""
        if person.inTeam(getUtility(ILaunchpadCelebrities).admin):
            return True
        for driver in self.target.drivers:
            if person.inTeam(driver):
                return True

        if self.distrorelease is not None:
            # For distributions anyone that can upload to the
            # distribution may approve nominations.
            bug_components = set()
            distribution = self.distrorelease.distribution
            for bugtask in self.bug.bugtasks:
                if (bugtask.distribution == distribution
                    and bugtask.sourcepackagename is not None):
                    source_package = self.distrorelease.getSourcePackage(
                        bugtask.sourcepackagename)
                    bug_components.add(
                        source_package.latest_published_component)
            if len(bug_components) == 0:
                # If the bug isn't targeted to a source package, allow
                # any uploader to approve the nomination.
                bug_components = set(
                    upload_component.component
                    for upload_component in distribution.uploaders)
            for upload_component in distribution.uploaders:
                if (upload_component.component in bug_components and
                    person.inTeam(upload_component.uploader)):
                    return True

        return False

class BugNominationSet:
    """See IBugNominationSet."""
    implements(IBugNominationSet)

    def get(self, id):
        """See IBugNominationSet."""
        try:
            return BugNomination.get(id)
        except SQLObjectNotFound:
            raise NotFoundError(id)
