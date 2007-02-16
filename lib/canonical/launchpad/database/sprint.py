# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'Sprint',
    'SprintSet',
    ]


from zope.interface import implements

from sqlobject import (
    ForeignKey, StringCol, SQLRelatedJoin)

from canonical.launchpad.interfaces import (
    IHasGotchiAndEmblem, ISprint, ISprintSet)

from canonical.database.sqlbase import (
    SQLBase, flush_database_updates, quote)
from canonical.database.constants import DEFAULT 
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.database.sprintattendance import SprintAttendance
from canonical.launchpad.database.sprintspecification import (
    SprintSpecification)

from canonical.lp.dbschema import (
    SprintSpecificationStatus, SpecificationFilter, SpecificationSort)


class Sprint(SQLBase):
    """See ISprint."""

    implements(ISprint, IHasGotchiAndEmblem)

    _defaultOrder = ['name']
    default_gotchi_resource = '/@@/sprint-mugshot'
    default_gotchi_heading_resource = '/@@/sprint-heading'
    default_emblem_resource = '/@@/sprint'

    # db field names
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    name = StringCol(notNull=True, alternateID=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    driver = ForeignKey(dbName='driver', foreignKey='Person')
    home_page = StringCol(notNull=False, default=None)
    homepage_content = StringCol(default=None)
    emblem = ForeignKey(
        dbName='emblem', foreignKey='LibraryFileAlias', default=None)
    gotchi = ForeignKey(
        dbName='gotchi', foreignKey='LibraryFileAlias', default=None)
    gotchi_heading = ForeignKey(
        dbName='gotchi_heading', foreignKey='LibraryFileAlias', default=None)
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

    # useful joins
    attendees = SQLRelatedJoin('Person',
        joinColumn='sprint', otherColumn='attendee',
        intermediateTable='SprintAttendance', orderBy='name')

    def spec_filter_clause(self, filter=None):
        """Figure out the appropriate query for specifications on a sprint.

        We separate out the query generation from the normal
        specifications() method because we want to reuse this query in the
        specificationLinks() method.
        """

        # Make a new list of the filter, so that we do not mutate what we
        # were passed as a filter
        if not filter:
            # filter could be None or [] then we decide the default
            # which for a sprint is to show everything approved
            filter = [SpecificationFilter.ACCEPTED]

        # figure out what set of specifications we are interested in. for
        # sprint, we need to be able to filter on the basis of:
        #
        #  - completeness.
        #  - acceptance for sprint agenda.
        #  - informational.
        #
        base = """SprintSpecification.sprint = %d AND
                  SprintSpecification.specification = Specification.id AND 
                  (Specification.product IS NULL OR
                   Specification.product NOT IN
                    (SELECT Product.id FROM Product
                     WHERE Product.active IS FALSE))
                  """ % self.id
        query = base

        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += ' AND Specification.informational IS TRUE'
        
        # import here to avoid circular deps
        from canonical.launchpad.database.specification import Specification

        # filter based on completion. see the implementation of
        # Specification.is_complete() for more details
        completeness =  Specification.completeness_clause

        if SpecificationFilter.COMPLETE in filter:
            query += ' AND ( %s ) ' % completeness
        elif SpecificationFilter.INCOMPLETE in filter:
            query += ' AND NOT ( %s ) ' % completeness

        # look for specs that have a particular SprintSpecification
        # status (proposed, accepted or declined)
        if SpecificationFilter.ACCEPTED in filter:
            query += ' AND SprintSpecification.status = %d' % (
                SprintSpecificationStatus.ACCEPTED.value)
        elif SpecificationFilter.PROPOSED in filter:
            query += ' AND SprintSpecification.status = %d' % (
                SprintSpecificationStatus.PROPOSED.value)
        elif SpecificationFilter.DECLINED in filter:
            query += ' AND SprintSpecification.status = %d' % (
                SprintSpecificationStatus.DECLINED.value)
        
        # ALL is the trump card
        if SpecificationFilter.ALL in filter:
            query = base
        
        # Filter for specification text
        for constraint in filter:
            if isinstance(constraint, basestring):
                # a string in the filter is a text search filter
                query += ' AND Specification.fti @@ ftq(%s) ' % quote(
                    constraint)

        return query

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None):
        """See IHasSpecifications."""

        query = self.spec_filter_clause(filter=filter)
        if filter == None:
            filter = []

        # import here to avoid circular deps
        from canonical.launchpad.database.specification import Specification

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = ['-priority', 'Specification.status',
                     'Specification.name']
        elif sort == SpecificationSort.DATE:
            # we need to establish if the listing will show specs that have
            # been decided only, or will include proposed specs.
            show_proposed = set([
                SpecificationFilter.ALL,
                SpecificationFilter.PROPOSED,
                ])
            if len(show_proposed.intersection(set(filter))) > 0:
                # we are showing proposed specs so use the date proposed
                # because not all specs will have a date decided.
                order = ['-SprintSpecification.date_created',
                         'Specification.id']
            else:
                # this will show only decided specs so use the date the spec
                # was accepted or declined for the sprint
                order = ['-SprintSpecification.date_decided',
                         '-SprintSpecification.date_created',
                         'Specification.id']

        # now do the query, and remember to prejoin to people
        results = Specification.select(query, orderBy=order, limit=quantity,
            clauseTables=['SprintSpecification'])
        return results.prejoin(['assignee', 'approver', 'drafter'])

    def specificationLinks(self, sort=None, quantity=None, filter=None):
        """See ISprint."""

        query = self.spec_filter_clause(filter=filter)

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = ['-priority', 'status', 'name']
        elif sort == SpecificationSort.DATE:
            order = ['-datecreated', 'id']

        results = SprintSpecification.select(query,
            clauseTables=['Specification'], orderBy=order, limit=quantity)
        return results.prejoin(['specification'])

    def getSpecificationLink(self, speclink_id):
        """See ISprint.
        
        NB: we expose the horrible speclink.id because there is no unique
        way to refer to a specification outside of a product or distro
        context. Here we are a sprint that could cover many products and/or
        distros.
        """
        speclink = SprintSpecification.get(speclink_id)
        assert (speclink.sprint.id == self.id)
        return speclink

    def acceptSpecificationLinks(self, idlist, decider):
        """See ISprint."""
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
        """See ISprint."""
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
    def attend(self, person, time_starts, time_ends):
        """See ISprint."""
        # first see if a relevant attendance exists, and if so, update it
        for attendance in self.attendances:
            if attendance.attendee.id == person.id:
                attendance.time_starts = time_starts
                attendance.time_ends = time_ends
                return attendance
        # since no previous attendance existed, create a new one
        return SprintAttendance(sprint=self, attendee=person,
            time_starts=time_starts, time_ends=time_ends)

    def removeAttendance(self, person):
        """See ISprint."""
        for attendance in self.attendances:
            if attendance.attendee.id == person.id:
                attendance.destroySelf()
                return

    @property
    def attendances(self):
        ret = SprintAttendance.selectBy(sprint=self)
        return sorted(ret.prejoin(['attendee']), key=lambda a: a.attendee.name)

    # linking to specifications
    def linkSpecification(self, spec):
        """See ISprint."""
        for speclink in self.spec_links:
            if speclink.spec.id == spec.id:
                return speclink
        return SprintSpecification(sprint=self, specification=spec)

    def unlinkSpecification(self, spec):
        """See ISprint."""
        for speclink in self.spec_links:
            if speclink.spec.id == spec.id:
                SprintSpecification.delete(speclink.id)
                return speclink


class SprintSet:
    """The set of sprints."""

    implements(ISprintSet)

    def __init__(self):
        """See ISprintSet."""
        self.title = 'Sprints and meetings'

    def __getitem__(self, name):
        """See ISprintSet."""
        return Sprint.selectOneBy(name=name)

    def __iter__(self):
        """See ISprintSet."""
        return iter(Sprint.select(orderBy='-time_starts'))

    def new(self, owner, name, title, time_zone, time_starts, time_ends,
            summary=None, driver=None, home_page=None, gotchi=None,
            gotchi_heading=None, emblem=None):
        """See ISprintSet."""
        return Sprint(owner=owner, name=name, title=title,
            time_zone=time_zone, time_starts=time_starts,
            time_ends=time_ends, summary=summary, driver=driver,
            home_page=home_page, gotchi=gotchi, emblem=emblem,
            gotchi_heading=gotchi_heading)

