# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'Sprint',
    'SprintSet',
    'HasSprintsMixin',
    ]


from sqlobject import (
    ForeignKey,
    StringCol,
    )
from storm.locals import (
    Desc,
    Not,
    Or,
    Select,
    Store,
    )
from zope.component import getUtility
from zope.interface import implements

from lp.app.interfaces.launchpad import (
    IHasIcon,
    IHasLogo,
    IHasMugshot,
    ILaunchpadCelebrities,
    )
from lp.blueprints.enums import (
    SpecificationFilter,
    SpecificationImplementationStatus,
    SpecificationSort,
    SprintSpecificationStatus,
    )
from lp.blueprints.interfaces.sprint import (
    ISprint,
    ISprintSet,
    )
from lp.blueprints.model.specification import HasSpecificationsMixin
from lp.blueprints.model.sprintattendance import SprintAttendance
from lp.blueprints.model.sprintspecification import SprintSpecification
from lp.app.enums import InformationType
from lp.registry.interfaces.person import (
    IPersonSet,
    validate_public_person,
    )
from lp.registry.model.hasdrivers import HasDriversMixin
from lp.services.database.constants import DEFAULT
from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.sqlbase import (
    flush_database_updates,
    quote,
    SQLBase,
    )
from lp.services.database.stormexpr import fti_search


class Sprint(SQLBase, HasDriversMixin, HasSpecificationsMixin):
    """See `ISprint`."""

    implements(ISprint, IHasLogo, IHasMugshot, IHasIcon)

    _defaultOrder = ['name']

    # db field names
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    name = StringCol(notNull=True, alternateID=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    driver = ForeignKey(
        dbName='driver', foreignKey='Person',
        storm_validator=validate_public_person)
    home_page = StringCol(notNull=False, default=None)
    homepage_content = StringCol(default=None)
    icon = ForeignKey(
        dbName='icon', foreignKey='LibraryFileAlias', default=None)
    logo = ForeignKey(
        dbName='logo', foreignKey='LibraryFileAlias', default=None)
    mugshot = ForeignKey(
        dbName='mugshot', foreignKey='LibraryFileAlias', default=None)
    address = StringCol(notNull=False, default=None)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    time_zone = StringCol(notNull=True)
    time_starts = UtcDateTimeCol(notNull=True)
    time_ends = UtcDateTimeCol(notNull=True)

    # attributes

    # we want to use this with templates that can assume a displayname,
    # because in many ways a sprint behaves just like a project or a
    # product - it has specs
    @property
    def displayname(self):
        return self.title

    @property
    def drivers(self):
        """See IHasDrivers."""
        if self.driver is not None:
            return [self.driver, self.owner]
        return [self.owner]

    @property
    def attendees(self):
        # Only really used in tests.
        return [a.attendee for a in self.attendances]

    def spec_filter_clause(self, filter=None):
        """Figure out the appropriate query for specifications on a sprint.

        We separate out the query generation from the normal
        specifications() method because we want to reuse this query in the
        specificationLinks() method.
        """
        # import here to avoid circular deps
        from lp.blueprints.model.specification import Specification
        from lp.registry.model.product import Product
        query = [Specification.information_type == InformationType.PUBLIC,
                 SprintSpecification.sprintID == self.id,
                 SprintSpecification.specificationID == Specification.id,
                 Or(Specification.product == None,
                    Not(Specification.productID.is_in(Select(Product.id,
                        Product.active == False))))]
        if not filter:
            filter = set([SpecificationFilter.ACCEPTED])
        if SpecificationFilter.INFORMATIONAL in filter:
            query.append(Specification.implementation_status ==
                         SpecificationImplementationStatus.INFORMATIONAL)
        if SpecificationFilter.COMPLETE in filter:
            query.append(Specification.storm_completeness())
        if SpecificationFilter.INCOMPLETE in filter:
            query.append(Not(Specification.storm_completeness()))
        sprint_status = []
        if SpecificationFilter.PROPOSED in filter:
            sprint_status.append(SprintSpecificationStatus.PROPOSED)
        if SpecificationFilter.ACCEPTED in filter:
            sprint_status.append(SprintSpecificationStatus.ACCEPTED)
        statuses = [SprintSpecification.status == status for status in
                    sprint_status]
        if len(statuses) > 0:
            query.append(Or(*statuses))
        for constraint in filter:
            if not isinstance(constraint, basestring):
                continue
            query.append(fti_search(Specification, constraint))
        return query

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None,
                       prejoin_people=None):
        """See IHasSpecifications."""
        if filter is None:
            filter = set([SpecificationFilter.ACCEPTED])
        query = self.spec_filter_clause(filter=filter)
        # import here to avoid circular deps
        from lp.blueprints.model.specification import Specification
        assert prejoin_people is None or not prejoin_people
        result = Store.of(self).find(Specification, *query)
        if sort is not None:
            assert sort == SpecificationSort.DATE
            order = (Desc(SprintSpecification.date_created), Specification.id)
            if (SpecificationFilter.ALL not in filter and
                SpecificationFilter.PROPOSED not in filter):
                order = (Desc(SprintSpecification.date_decided),) + order
            result = result.order_by(*order)
        if quantity is not None:
            result = result[:quantity]
        return result

    def specificationLinks(self, sort=None, quantity=None, filter=None):
        """See `ISprint`."""
        assert sort is None
        assert quantity is None
        query = self.spec_filter_clause(filter=filter)
        result = Store.of(self).find(SprintSpecification, *query)
        return result

    def getSpecificationLink(self, speclink_id):
        """See `ISprint`.

        NB: we expose the horrible speclink.id because there is no unique
        way to refer to a specification outside of a product or distro
        context. Here we are a sprint that could cover many products and/or
        distros.
        """
        speclink = SprintSpecification.get(speclink_id)
        assert (speclink.sprint.id == self.id)
        return speclink

    def acceptSpecificationLinks(self, idlist, decider):
        """See `ISprint`."""
        for sprintspec in idlist:
            speclink = self.getSpecificationLink(sprintspec)
            speclink.acceptBy(decider)

        # we need to flush all the changes we have made to disk, then try
        # the query again to see if we have any specs remaining in this
        # queue
        flush_database_updates()

        return self.specifications(
                        filter=[SpecificationFilter.PROPOSED]).count()

    def declineSpecificationLinks(self, idlist, decider):
        """See `ISprint`."""
        for sprintspec in idlist:
            speclink = self.getSpecificationLink(sprintspec)
            speclink.declineBy(decider)

        # we need to flush all the changes we have made to disk, then try
        # the query again to see if we have any specs remaining in this
        # queue
        flush_database_updates()

        return self.specifications(
                        filter=[SpecificationFilter.PROPOSED]).count()

    # attendance
    def attend(self, person, time_starts, time_ends, is_physical):
        """See `ISprint`."""
        # First see if a relevant attendance exists, and if so, update it.
        attendance = Store.of(self).find(
            SprintAttendance,
            SprintAttendance.sprint == self,
            SprintAttendance.attendee == person).one()
        if attendance is None:
            # Since no previous attendance existed, create a new one.
            attendance = SprintAttendance(sprint=self, attendee=person)
        attendance.time_starts = time_starts
        attendance.time_ends = time_ends
        attendance.is_physical = is_physical
        return attendance

    def removeAttendance(self, person):
        """See `ISprint`."""
        Store.of(self).find(
            SprintAttendance,
            SprintAttendance.sprint == self,
            SprintAttendance.attendee == person).remove()

    @property
    def attendances(self):
        result = list(Store.of(self).find(
            SprintAttendance,
            SprintAttendance.sprint == self))
        people = [a.attendeeID for a in result]
        # In order to populate the person cache we need to materialize the
        # result set.  Listification should do.
        list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                people, need_validity=True))
        return sorted(result, key=lambda a: a.attendee.displayname.lower())

    # linking to specifications
    def linkSpecification(self, spec):
        """See `ISprint`."""
        for speclink in self.spec_links:
            if speclink.spec.id == spec.id:
                return speclink
        return SprintSpecification(sprint=self, specification=spec)

    def unlinkSpecification(self, spec):
        """See `ISprint`."""
        for speclink in self.spec_links:
            if speclink.spec.id == spec.id:
                SprintSpecification.delete(speclink.id)
                return speclink

    def isDriver(self, user):
        """See `ISprint`."""
        admins = getUtility(ILaunchpadCelebrities).admin
        return (user.inTeam(self.owner) or
                user.inTeam(self.driver) or
                user.inTeam(admins))


class SprintSet:
    """The set of sprints."""

    implements(ISprintSet)

    def __init__(self):
        """See `ISprintSet`."""
        self.title = 'Sprints and meetings'

    def __getitem__(self, name):
        """See `ISprintSet`."""
        return Sprint.selectOneBy(name=name)

    def __iter__(self):
        """See `ISprintSet`."""
        return iter(Sprint.select("time_ends > 'NOW'", orderBy='time_starts'))

    @property
    def all(self):
        return Sprint.select(orderBy='-time_starts')

    def new(self, owner, name, title, time_zone, time_starts, time_ends,
            summary, address=None, driver=None, home_page=None,
            mugshot=None, logo=None, icon=None):
        """See `ISprintSet`."""
        return Sprint(owner=owner, name=name, title=title,
            time_zone=time_zone, time_starts=time_starts,
            time_ends=time_ends, summary=summary, driver=driver,
            home_page=home_page, mugshot=mugshot, icon=icon,
            logo=logo, address=address)


class HasSprintsMixin:
    """A mixin class implementing the common methods for any class
    implementing IHasSprints.
    """

    def _getBaseQueryAndClauseTablesForQueryingSprints(self):
        """Return the base SQL query and the clauseTables to be used when
        querying sprints related to this object.

        Subclasses must overwrite this method if it doesn't suit them.
        """
        query = """
            Specification.%s = %s
            AND Specification.id = SprintSpecification.specification
            AND SprintSpecification.sprint = Sprint.id
            AND SprintSpecification.status = %s
            """ % (self._table, self.id,
                   quote(SprintSpecificationStatus.ACCEPTED))
        return query, ['Specification', 'SprintSpecification']

    @property
    def sprints(self):
        """See IHasSprints."""
        query, tables = self._getBaseQueryAndClauseTablesForQueryingSprints()
        return Sprint.select(
            query, clauseTables=tables, orderBy='-time_starts', distinct=True)

    @property
    def coming_sprints(self):
        """See IHasSprints."""
        query, tables = self._getBaseQueryAndClauseTablesForQueryingSprints()
        query += " AND Sprint.time_ends > 'NOW'"
        return Sprint.select(
            query, clauseTables=tables, orderBy='time_starts',
            distinct=True, limit=5)

    @property
    def past_sprints(self):
        """See IHasSprints."""
        query, tables = self._getBaseQueryAndClauseTablesForQueryingSprints()
        query += " AND Sprint.time_ends <= 'NOW'"
        return Sprint.select(
            query, clauseTables=tables, orderBy='-time_starts',
            distinct=True)
