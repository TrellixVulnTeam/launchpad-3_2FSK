# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Milestone views."""

__metaclass__ = type

__all__ = [
    'MilestoneSetNavigation',
    'MilestoneNavigation',
    'MilestoneFacets',
    'MilestoneContextMenu',
    'MilestoneAddView',
    'MilestoneEditView',
    ]

from zope.component import getUtility

from canonical.launchpad.interfaces import (
    IProduct, IDistribution, IMilestone, IMilestoneSet)
from canonical.launchpad.browser.editview import SQLObjectEditView

from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, ContextMenu, Link,
    enabled_with_permission, GetitemNavigation, Navigation)


class MilestoneSetNavigation(GetitemNavigation):

    usedfor = IMilestoneSet


# XXX: 20051214 jamesh
# This class is required in order to make use of a side effect of
# Navigation.publishTraverse: adding context objects to
# request.traversed_objects.
class MilestoneNavigation(Navigation):

    usedfor = IMilestone


class MilestoneFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IMilestone."""

    usedfor = IMilestone

    enable_only = ['overview']

    def overview(self):
        target = ''
        text = 'Overview'
        summary = 'General information about %s' % self.context.displayname
        return Link(target, text, summary)


class MilestoneContextMenu(ContextMenu):

    usedfor = IMilestone

    links = ['edit', 'admin']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Edit Milestone'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def admin(self):
        text = 'Admin Milestone'
        return Link('+admin', text, icon='edit')


class MilestoneAddView:
    def create(self, name, dateexpected=None):
        """We will use the newMilestone method on the ProductSeries or
        Distrorelease context to make the milestone."""
        return self.context.newMilestone(name, dateexpected=dateexpected)

    def add(self, content):
        """Skipping 'adding' this content to a container, because
        this is a placeless system."""
        return content

    def nextURL(self):
        return '.'


class MilestoneEditView(SQLObjectEditView):

    def changed(self):
        self.request.response.redirect('../..')
