# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'SpecificationWorkItem',
    ]

from zope.interface import implements

from storm.locals import (
    Bool,
    Int,
    Reference,
    Unicode,
    )

from lp.services.database.constants import DEFAULT
from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.enumcol import EnumCol
from lp.services.database.stormbase import StormBase

from lp.blueprints.enums import SpecificationWorkItemStatus
from lp.blueprints.interfaces.specificationworkitem import (
    ISpecificationWorkItem,
    )
from lp.registry.interfaces.person import validate_public_person


class SpecificationWorkItem(StormBase):
    implements(ISpecificationWorkItem)

    __storm_table__ = 'SpecificationWorkItem'

    id = Int(primary=True)
    title = Unicode(allow_none=False)
    specification_id = Int(name='specification')
    specification = Reference(specification_id, 'Specification.id')
    assignee_id = Int(name='assignee', validator=validate_public_person)
    assignee = Reference(assignee_id, 'Person.id')
    milestone_id = Int(name='milestone')
    milestone = Reference(milestone_id, 'Milestone.id')
    status = EnumCol(
        schema=SpecificationWorkItemStatus,
        notNull=True, default=SpecificationWorkItemStatus.TODO)
    date_created = UtcDateTimeCol(notNull=True, default=DEFAULT)
    # XXX: Need to decide whether we'll use sequential values here or leave
    # gaps between the numbers we use to make it cheap to insert new items in
    # the middle.
    sequence = Int(allow_none=False)
    # XXX: Should we reset the sequence when a WI is marked as deleted?
    # XXX: Do we need to keep track of the date when it was deleted?
    deleted = Bool(allow_none=False, default=False)

    def __repr__(self):
        title = self.title.encode('ASCII', 'backslashreplace')
        return '<SpecificationWorkItem [%s] %s: %s of %s>' % (
            self.assignee, title, self.status, self.specification)

    def __init__(self, title, status, specification, assignee, milestone,
                 sequence):
        self.title=title
        self.status=status
        self.specification = specification
        self.assignee=assignee
        self.milestone=milestone
        self.sequence=sequence
