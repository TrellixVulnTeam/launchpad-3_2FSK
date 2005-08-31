# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Specification', 'SpecificationSet']

import datetime

from zope.interface import implements

from sqlobject import (
    ForeignKey, IntCol, StringCol, IntervalCol, MultipleJoin, RelatedJoin)

from canonical.launchpad.interfaces import (
    ISpecification, ISpecificationSet)

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.database.specificationdependency import \
    SpecificationDependency
from canonical.launchpad.database.specificationbug import \
    SpecificationBug
from canonical.launchpad.database.specificationreview import \
    SpecificationReview
from canonical.launchpad.database.specificationsubscription import \
    SpecificationSubscription

from canonical.lp.dbschema import (
    EnumCol, SpecificationStatus, SpecificationPriority)


class Specification(SQLBase):
    """See ISpecification."""

    implements(ISpecification)

    _defaultOrder = ['status', '-priority']

    # db field names
    name = StringCol(unique=True, notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    status = EnumCol(schema=SpecificationStatus, notNull=True,
        default=SpecificationStatus.BRAINDUMP)
    priority = EnumCol(schema=SpecificationPriority, notNull=True,
        default=SpecificationPriority.MEDIUM)
    assignee = ForeignKey(dbName='assignee', notNull=False,
        foreignKey='Person')
    drafter = ForeignKey(dbName='drafter', notNull=False,
        foreignKey='Person')
    approver = ForeignKey(dbName='approver', notNull=False,
        foreignKey='Person')
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    product = ForeignKey(dbName='product', foreignKey='Product',
        notNull=False, default=None)
    productseries = ForeignKey(dbName='productseries',
        foreignKey='ProductSeries', notNull=False, default=None)
    distribution = ForeignKey(dbName='distribution',
        foreignKey='Distribution', notNull=False, default=None)
    distrorelease = ForeignKey(dbName='distrorelease',
        foreignKey='DistroRelease', notNull=False, default=None)
    milestone = ForeignKey(dbName='milestone',
        foreignKey='Milestone', notNull=False, default=None)
    specurl = StringCol(notNull=True)
    whiteboard = StringCol(notNull=False, default=None)

    # useful joins
    subscriptions = MultipleJoin('SpecificationSubscription',
        joinColumn='specification', orderBy='id')
    subscribers = RelatedJoin('Person',
        joinColumn='specification', otherColumn='person',
        intermediateTable='SpecificationSubscription', orderBy='name')
    reviews = MultipleJoin('SpecificationReview',
        joinColumn='specification', orderBy='id')
    buglinks = MultipleJoin('SpecificationBug', joinColumn='specification',
        orderBy='id')
    bugs = RelatedJoin('Bug',
        joinColumn='specification', otherColumn='bug',
        intermediateTable='SpecificationBug', orderBy='datecreated')
    dependencies = RelatedJoin('Specification', joinColumn='specification',
        otherColumn='dependency', orderBy='title',
        intermediateTable='SpecificationDependency')
    spec_dependency_links = MultipleJoin('SpecificationDependency',
        joinColumn='specification', orderBy='id')
    blocked_specs = RelatedJoin('Specification', joinColumn='dependency',
        otherColumn='specification', orderBy='title',
        intermediateTable='SpecificationDependency')

    # attributes
    @property
    def target(self):
        """See ISpecification."""
        if self.product:
            return self.product
        return self.distribution

    # subscriptions
    def subscribe(self, person):
        """See ISpecification."""
        # first see if a relevant subscription exists, and if so, update it
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                return sub
        # since no previous subscription existed, create a new one
        return SpecificationSubscription(
            specification=self,
            person=person)

    def unsubscribe(self, person):
        """See ISpecification."""
        # see if a relevant subscription exists, and if so, delete it
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                SpecificationSubscription.delete(sub.id)
                return

    # queueing
    def queue(self, reviewer, requestor, queuemsg=None):
        """See ISpecification."""
        # first see if a relevant queue entry exists, and if so, update it
        for review in self.reviews:
            if review.reviewer.id == reviewer.id:
                review.requestor = requestor
                review.queuemsg = queuemsg
                return review
        # since no previous review existed for this person, create a new one
        return SpecificationReview(
            specification=self,
            reviewer=reviewer,
            requestor=requestor,
            queuemsg=queuemsg)

    def unqueue(self, reviewer):
        """See ISpecification."""
        # see if a relevant queue entry exists, and if so, delete it
        for review in self.reviews:
            if review.reviewer.id == reviewer.id:
                SpecificationReview.delete(review.id)
                return

    # linking to bugs
    def linkBug(self, bug_number):
        """See ISpecification."""
        for buglink in self.buglinks:
            if buglink.bug.id == bug_number:
                return buglink
        return SpecificationBug(specification=self, bug=bug_number)

    def unLinkBug(self, bug_number):
        """See ISpecification."""
        # see if a relevant bug link exists, and if so, delete it
        for buglink in self.buglinks:
            if buglink.bug.id == bug_number:
                SpecificationBug.delete(buglink.id)
                return buglink

    # dependencies
    def createDependency(self, specification):
        """See ISpecification."""
        for deplink in self.spec_dependency_links:
            if deplink.dependency.id == specification.id:
                return deplink
        return SpecificationDependency(specification=self,
            dependency=specification)

    def removeDependency(self, specification):
        """See ISpecification."""
        # see if a relevant dependency link exists, and if so, delete it
        for deplink in self.spec_dependency_links:
            if deplink.dependency.id == specification.id:
                SpecificationDependency.delete(deplink.id)
                return deplink

    def all_deps(self, higher=[]):
        deps = set(higher)
        for dep in self.dependencies:
            if dep not in deps:
                deps.add(dep)
                deps = deps.union(dep.all_deps(higher=deps))
        return sorted(deps, key=lambda a: (a.status, a.priority,
            a.title))

    def all_blocked(self, higher=[]):
        blocked = set(higher)
        for block in self.blocked_specs:
            if block not in blocked:
                blocked.add(block)
                blocked = blocked.union(block.all_blocked(higher=blocked))
        return sorted(blocked, key=lambda a: (a.status, a.priority,
            a.title))


class SpecificationSet:
    """The set of feature specifications."""

    implements(ISpecificationSet)

    def __init__(self):
        """See ISpecificationSet."""
        self.title = 'Launchpad Feature Specifications'

    def __iter__(self):
        """See ISpecificationSet."""
        for row in Specification.select():
            yield row

    def new(self, name, title, specurl, summary, priority, status,
        owner, approver=None, product=None, distribution=None, assignee=None,
        drafter=None, whiteboard=None):
        """See ISpecificationSet."""
        return Specification(name=name, title=title, specurl=specurl,
            summary=summary, priority=priority, status=status,
            owner=owner, approver=approver, product=product,
            distribution=distribution, assignee=assignee, drafter=drafter,
            whiteboard=whiteboard)

