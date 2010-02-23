# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'MentoringOffer',
    'MentoringOfferSet',
    ]

from datetime import datetime, timedelta
import pytz

from zope.interface import implements

from sqlobject import ForeignKey

from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.mentoringoffer import (
    IMentoringOffer, IMentoringOfferSet)

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol


class MentoringOffer(SQLBase):
    """See IMentoringOffer."""

    implements(IMentoringOffer)

    _defaultOrder = ['-date_created', '-id']

    # db field names
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    date_created = UtcDateTimeCol(notNull=True, default=DEFAULT)
    team = ForeignKey(
        dbName='team', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    bug = ForeignKey(dbName='bug', notNull=False,
                     foreignKey='Bug', default=None)
    specification = ForeignKey(dbName='specification', notNull=False,
                     foreignKey='Specification', default=None)

    # attributes
    @property
    def target(self):
        """See IMentoringOffer."""
        if self.bug:
            return self.bug
        return self.specification

    @property
    def subscription_request(self):
        """See IMentoringOffer.

        In this case, we return the subscription status of the person on the
        underlying target.
        """
        return self.target.isSubscribed(self.owner)


class MentoringOfferSet:
    """See IMentoringOfferSet."""

    implements(IMentoringOfferSet)

    displayname = 'the Launchpad Mentorship Manager'
    title = 'Launchpad Mentorship Manager'

    @property
    def mentoring_offers(self):
        """See IHasMentoringOffers."""
        # import here to avoid circular imports
        from lp.blueprints.model.specification import Specification
        from lp.bugs.model.bugtask import BugTask
        via_specs = MentoringOffer.select("""
            Specification.id = MentoringOffer.specification AND NOT
            (""" + Specification.completeness_clause +")",
            clauseTables=['Specification'],
            distinct=True)
        via_bugs = MentoringOffer.select("""
            BugTask.bug = Bug.id AND
            Bug.private IS FALSE AND
            BugTask.bug = MentoringOffer.bug AND NOT (
            """ + BugTask.completeness_clause + ")",
            clauseTables=['BugTask', 'Bug'],
            distinct=True)
        return via_specs.union(via_bugs, orderBy=['-date_created'])

    @property
    def recent_completed_mentorships(self):
        """See IHasMentoringOffers."""
        # import here to avoid circular imports
        from lp.blueprints.model.specification import Specification
        from lp.bugs.model.bugtask import BugTask
        now = datetime.now(pytz.timezone('UTC'))
        yearago = now - timedelta(365)
        via_specs = MentoringOffer.select("""
            MentoringOffer.date_created > %s AND
            """ % sqlvalues(yearago) + """
            Specification.id = MentoringOffer.specification AND
            (""" + Specification.completeness_clause +")",
            clauseTables=['Specification'],
            distinct=True)
        via_bugs = MentoringOffer.select("""
            MentoringOffer.date_created > %s AND
            """ % sqlvalues(yearago) + """
            BugTask.bug = MentoringOffer.bug AND (
            """ + BugTask.completeness_clause + ")",
            clauseTables=['BugTask'],
            distinct=True)
        return via_specs.union(via_bugs)

