# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Components related to specifications."""

__metaclass__ = type

from zope.interface import implements

from canonical.launchpad.interfaces import ISpecificationDelta

class SpecificationDelta:
    """See canonical.launchpad.interfaces.ISpecificationDelta."""
    implements(ISpecificationDelta)
    def __init__(self, specification, user, title=None,
        summary=None, whiteboard=None, specurl=None, productseries=None,
        distrorelease=None, milestone=None, name=None, priority=None,
        status=None, target=None, bugs_linked=None, bugs_unlinked=None,
        approver=None, assignee=None, drafter=None):
        self.specification = specification
        self.user = user
        self.title = title
        self.summary = summary
        self.whiteboard = whiteboard
        self.specurl = specurl
        self.productseries = productseries
        self.distrorelease = distrorelease
        self.milestone = milestone
        self.name = name
        self.priority = priority
        self.status = status
        self.target = target
        self.approver = approver
        self.assignee = assignee
        self.drafter = drafter
        self.bugs_linked = bugs_linked
        self.bugs_unlinked = bugs_unlinked

