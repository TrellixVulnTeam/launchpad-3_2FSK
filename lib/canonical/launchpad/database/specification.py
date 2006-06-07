# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Specification', 'SpecificationSet']


from zope.interface import implements

from sqlobject import (
    ForeignKey, IntCol, StringCol, SQLMultipleJoin, SQLRelatedJoin, BoolCol)

from canonical.launchpad.interfaces import (
    ISpecification, ISpecificationSet)

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.database.specificationdependency import (
    SpecificationDependency)
from canonical.launchpad.database.specificationbug import (
    SpecificationBug)
from canonical.launchpad.database.specificationfeedback import (
    SpecificationFeedback)
from canonical.launchpad.database.specificationsubscription import (
    SpecificationSubscription)
from canonical.launchpad.database.sprintspecification import (
    SprintSpecification)
from canonical.launchpad.database.sprint import Sprint
from canonical.launchpad.helpers import (
    contactEmailAddresses, check_permission)

from canonical.launchpad.components.specification import SpecificationDelta

from canonical.lp.dbschema import (
    EnumCol, SpecificationStatus, SpecificationPriority,
    SpecificationDelivery, SpecificationGoalStatus)


class Specification(SQLBase):
    """See ISpecification."""

    implements(ISpecification)

    _defaultOrder = ['-priority', 'status', 'name', 'id']

    # db field names
    name = StringCol(unique=True, notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    status = EnumCol(schema=SpecificationStatus, notNull=True,
        default=SpecificationStatus.BRAINDUMP)
    priority = EnumCol(schema=SpecificationPriority, notNull=True,
        default=SpecificationPriority.UNDEFINED)
    assignee = ForeignKey(dbName='assignee', notNull=False,
        foreignKey='Person', default=None)
    drafter = ForeignKey(dbName='drafter', notNull=False,
        foreignKey='Person', default=None)
    approver = ForeignKey(dbName='approver', notNull=False,
        foreignKey='Person', default=None)
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
    goalstatus = EnumCol(schema=SpecificationGoalStatus, notNull=True,
        default=SpecificationGoalStatus.PROPOSED)
    milestone = ForeignKey(dbName='milestone',
        foreignKey='Milestone', notNull=False, default=None)
    specurl = StringCol(notNull=True)
    whiteboard = StringCol(notNull=False, default=None)
    needs_discussion = BoolCol(notNull=True, default=True)
    direction_approved = BoolCol(notNull=True, default=False)
    informational = BoolCol(notNull=True, default=False)
    man_days = IntCol(notNull=False, default=None)
    delivery = EnumCol(schema=SpecificationDelivery, notNull=True,
        default=SpecificationDelivery.UNKNOWN)
    superseded_by = ForeignKey(dbName='superseded_by',
        foreignKey='Specification', notNull=False, default=None)

    # useful joins
    subscriptions = SQLMultipleJoin('SpecificationSubscription',
        joinColumn='specification', orderBy='id')
    subscribers = SQLRelatedJoin('Person',
        joinColumn='specification', otherColumn='person',
        intermediateTable='SpecificationSubscription', orderBy='name')
    feedbackrequests = SQLMultipleJoin('SpecificationFeedback',
        joinColumn='specification', orderBy='id')
    sprint_links = SQLMultipleJoin('SprintSpecification', orderBy='id',
        joinColumn='specification')
    sprints = SQLRelatedJoin('Sprint', orderBy='name',
        joinColumn='specification', otherColumn='sprint',
        intermediateTable='SprintSpecification')
    buglinks = SQLMultipleJoin('SpecificationBug', joinColumn='specification',
        orderBy='id')
    bugs = SQLRelatedJoin('Bug',
        joinColumn='specification', otherColumn='bug',
        intermediateTable='SpecificationBug', orderBy='id')
    spec_dependency_links = SQLMultipleJoin('SpecificationDependency',
        joinColumn='specification', orderBy='id')

    dependencies = SQLRelatedJoin('Specification', joinColumn='specification',
        otherColumn='dependency', orderBy='title',
        intermediateTable='SpecificationDependency')
    blocked_specs = SQLRelatedJoin('Specification', joinColumn='dependency',
        otherColumn='specification', orderBy='title',
        intermediateTable='SpecificationDependency')

    # attributes
    @property
    def target(self):
        """See ISpecification."""
        if self.product:
            return self.product
        return self.distribution

    def retarget(self, product=None, distribution=None):
        """See ISpecification."""
        assert not (product and distribution)
        assert (product or distribution)

        # we need to ensure that there is not already a spec with this name
        # for this new target
        if product:
            assert product.getSpecification(self.name) is None
        elif distribution:
            assert distribution.getSpecification(self.name) is None

        self.productseries = None
        self.distrorelease = None
        self.milestone = None
        self.product = product
        self.distribution = distribution
        self.delivery = SpecificationDelivery.UNKNOWN

    @property
    def goal(self):
        """See ISpecification."""
        if self.productseries:
            return self.productseries
        return self.distrorelease

    def getSprintSpecification(self, sprintname):
        """See ISpecification."""
        for sprintspecification in self.sprint_links:
            if sprintspecification.sprint.name == sprintname:
                return sprintspecification
        return None

    def getFeedbackRequests(self, person):
        """See ISpecification."""
        reqlist = []
        for fbreq in self.feedbackrequests:
            if fbreq.reviewer.id == person.id:
                reqlist.append(fbreq)
        return reqlist

    def notificationRecipientAddresses(self):
        """See ISpecification."""
        related_people = [
            self.owner, self.assignee, self.approver, self.drafter]
        related_people = [
            person for person in related_people if person is not None]
        subscribers = [
            subscription.person for subscription in self.subscriptions]
        addresses = set()
        for person in related_people + subscribers:
            addresses.update(contactEmailAddresses(person))
        return sorted(addresses)

    # emergent properties
    @property
    def is_incomplete(self):
        """See ISpecification."""
        return not self.is_complete

    # Several other classes need to generate lists of specifications, and
    # one thing they often have to filter for is completeness. We maintain
    # this single canonical query string here so that it does not have to be
    # cargo culted into Product, Distribution, ProductSeries etc
    completeness_clause =  """
                Specification.delivery = %d 
                """ % SpecificationDelivery.IMPLEMENTED.value + """
            OR 
                Specification.status IN ( %d, %d ) 
                """ % (SpecificationStatus.OBSOLETE.value,
                       SpecificationStatus.SUPERSEDED.value) + """
            OR 
               (Specification.informational IS TRUE AND 
                Specification.status = %d)
                """ % SpecificationStatus.APPROVED.value

    @property
    def is_complete(self):
        """See ISpecification. This should be a code implementation of the
        SQL in self.completeness. Just for completeness.
        """
        return (self.status in [
                    SpecificationStatus.OBSOLETE,
                    SpecificationStatus.SUPERSEDED,
                    ]
                or self.delivery == SpecificationDelivery.IMPLEMENTED
                or (self.informational is True and
                    self.status == SpecificationStatus.APPROVED))

    @property
    def is_blocked(self):
        """See ISpecification."""
        for spec in self.dependencies:
            if spec.is_incomplete:
                return True
        return False

    @property
    def has_release_goal(self):
        """See ISpecification."""
        if (self.goal is not None and
            self.goalstatus == SpecificationGoalStatus.ACCEPTED):
            return True
        return False

    def getDelta(self, old_spec, user):
        """See ISpecification."""
        changes = {}
        for field_name in ("title", "summary", "whiteboard", "specurl",
            "productseries", "distrorelease", "milestone"):
            # fields for which we simply show the new value when they
            # change
            old_val = getattr(old_spec, field_name)
            new_val = getattr(self, field_name)
            if old_val != new_val:
                changes[field_name] = new_val

        for field_name in ("name", "priority", "status", "target", "approver",
                "assignee", "drafter"):
            # fields for which we show old => new when their values change
            old_val = getattr(old_spec, field_name)
            new_val = getattr(self, field_name)
            if old_val != new_val:
                changes[field_name] = {}
                changes[field_name]["old"] = old_val
                changes[field_name]["new"] = new_val

        old_bugs = old_spec.bugs
        new_bugs = self.bugs
        for bug in old_bugs:
            if bug not in new_bugs:
                if not changes.has_key('bugs_unlinked'):
                    changes['bugs_unlinked'] = []
                changes['bugs_unlinked'].append(bug)
        for bug in new_bugs:
            if bug not in old_bugs:
                if not changes.has_key('bugs_linked'):
                    changes['bugs_linked'] = []
                changes['bugs_linked'].append(bug)

        if changes:
            changes["specification"] = self
            changes["user"] = user

            return SpecificationDelta(**changes)
        else:
            return None

    # subscriptions
    def subscribe(self, person):
        """See ISpecification."""
        # first see if a relevant subscription exists, and if so, return it
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                return sub
        # since no previous subscription existed, create and return a new one
        return SpecificationSubscription(specification=self, person=person)

    def unsubscribe(self, person):
        """See ISpecification."""
        # see if a relevant subscription exists, and if so, delete it
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                SpecificationSubscription.delete(sub.id)
                return

    # queueing
    def queue(self, reviewer, requester, queuemsg=None):
        """See ISpecification."""
        for fbreq in self.feedbackrequests:
            if (fbreq.reviewer.id == reviewer.id and
                fbreq.requester == requester.id):
                # we have a relevant request already, update it
                fbreq.queuemsg = queuemsg
                return fbreq
        # since no previous feedback request existed for this person,
        # create a new one
        return SpecificationFeedback(
            specification=self,
            reviewer=reviewer,
            requester=requester,
            queuemsg=queuemsg)

    def unqueue(self, reviewer, requester):
        """See ISpecification."""
        # see if a relevant queue entry exists, and if so, delete it
        for fbreq in self.feedbackrequests:
            if (fbreq.reviewer.id == reviewer.id and
                fbreq.requester.id == requester.id):
                SpecificationFeedback.delete(fbreq.id)
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

    # sprint linking
    def linkSprint(self, sprint):
        """See ISpecification."""
        for sprint_link in self.sprint_links:
            if sprint_link.sprint.id == sprint.id:
                return sprint_link
        return SprintSpecification(specification=self, sprint=sprint)

    def unlinkSprint(self, sprint):
        """See ISpecification."""
        for sprint_link in self.sprint_links:
            if sprint_link.sprint.id == sprint.id:
                SprintSpecification.delete(sprint_link.id)
                return sprint_link

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

    def _all_deps(self, deps):
        for dep in self.dependencies:
            if dep not in deps:
                deps.add(dep)
                dep._all_deps(deps)

    def all_deps(self):
        deps = set()
        self._all_deps(deps)
        return sorted(deps, key=lambda s: (s.status, s.priority, s.title))

    def all_blocked(self, higher=None):
        if higher is None:
            higher = []
        blocked = set(higher)
        for block in self.blocked_specs:
            if block not in blocked:
                blocked.add(block)
                blocked = blocked.union(block.all_blocked(higher=blocked))
        return sorted(blocked, key=lambda s: (s.status, s.priority, s.title))


class SpecificationSet:
    """The set of feature specifications."""

    implements(ISpecificationSet)

    def __init__(self):
        """See ISpecificationSet."""
        self.title = 'Specifications registered in Launchpad'

    def __iter__(self):
        """See ISpecificationSet."""
        for row in Specification.select():
            yield row

    def getByName(self, name):
        """See ISpecificationSet."""
        specification = Specification.selectOneBy(name=name)
        if specification is None:
            return None 
        return specification

    def getByURL(self, url):
        """See ISpecificationSet."""
        specification = Specification.selectOneBy(specurl=url)
        if specification is None:
            return None 
        return specification

    @property
    def latest_specs(self):
        """See ISpecificationSet."""
        return Specification.select(orderBy='-datecreated')[:10]

    @property
    def upcoming_sprints(self):
        """See ISpecificationSet."""
        return Sprint.select("time_starts > 'NOW'", orderBy='-time_starts',
            limit=5)

    def new(self, name, title, specurl, summary, status,
        owner, approver=None, product=None, distribution=None, assignee=None,
        drafter=None, whiteboard=None,
        priority=SpecificationPriority.UNDEFINED):
        """See ISpecificationSet."""
        return Specification(name=name, title=title, specurl=specurl,
            summary=summary, priority=priority, status=status,
            owner=owner, approver=approver, product=product,
            distribution=distribution, assignee=assignee, drafter=drafter,
            whiteboard=whiteboard)

