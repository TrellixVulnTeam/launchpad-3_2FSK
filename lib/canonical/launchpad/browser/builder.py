# Copyright 2004 Canonical Ltd.  All rights reserved.

"""Browser views for builders."""

__metaclass__ = type

__all__ = ['BuilderSetNavigation', 'BuildFarmFacets', 'BuilderFacets',
           'BuilderSetAddView', 'BuilderView']

import datetime
import pytz

from sqlobject import SQLObjectNotFound

import zope.security.interfaces
from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser.add import AddView
from zope.app.event.objectevent import ObjectCreatedEvent, ObjectModifiedEvent

from canonical.lp import dbschema
from canonical.database.constants import UTC_NOW

from canonical.launchpad.interfaces import (
    IPerson, IBuilderSet, IBuilder, IBuildSet
    )

from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, Link, GetitemNavigation, stepthrough)


class BuilderSetNavigation(GetitemNavigation):

    usedfor = IBuilderSet

    @stepthrough('+build')
    def traverse_build(self, name):
        try:
            build_id = int(name)
        except ValueError:
            return None
        try:
            return self.context.getBuild(build_id)
        except SQLObjectNotFound:
            return None


class BuildFarmFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IBuilderSet."""
    enable_only = ['overview']

    usedfor = IBuilderSet


class BuilderFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IBuilder."""
    enable_only = ['overview']

    usedfor = IBuilder


class BuilderView:
    """Default Builder view class

    Implements useful actions and colect useful set for the pagetemplate.
    """
    __used_for__ = IBuilder

    def now(self):
        """Offers the timestamp for page rendering."""
        UTC = pytz.timezone('UTC')
        return datetime.datetime.now(UTC)

    def cancelBuildJob(self):
        """Cancel curent job in builder."""
        builder_id = self.request.form.get('BUILDERID')
        if not builder_id:
            return
        # XXX cprov 20051014
        # The 'self.context.slave.abort()' seems to work with the new
        # BuilderSlave class added by dsilvers, but I won't release it
        # until we can test it properly, since we can only 'abort' slaves
        # in BUILDING state it does depends of the major issue for testing
        # Auto Build System, getting slave building something sane. 
        return '<p>Cancel (%s). Not implemented yet</p>' % builder_id

    def lastBuilds(self):
        """Wrap up the IBuilderSet.lastBuilds method."""
        # XXX cprov 20050823
        # recover the number of items from the UI
        return getUtility(IBuildSet).getBuildsForBuilder(self.context)


class BuilderSetAddView(AddView):
    """Builder add view

    Extends zope AddView and uses IBuilderSet utitlity to create a new IBuilder
    """
    __used_for__ = IBuilderSet

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        # add the owner information for the product
        owner = IPerson(self.request.principal, None)
        if not owner:
            raise zope.security.interfaces.Unauthorized(
                "Need an authenticated Launchpad owner")

        kw = {}
        for key, value in data.items():
            kw[str(key)] = value
        kw['owner'] = owner

        # grab a BuilderSet utility
        builder_util = getUtility(IBuilderSet)
        # XXX cprov 20050621
        # expand dict !!
        builder = builder_util.new(**kw)
        notify(ObjectCreatedEvent(builder))
        self._nextURL = kw['name']
        return builder

    def nextURL(self):
        return self._nextURL
