# Copyright 2004 Canonical Ltd.  All rights reserved.

"""Browser views for builders."""

__metaclass__ = type

__all__ = ['BuilderSetNavigation',
           'BuilderSetFacets',
           'BuilderSetOverviewMenu',
           'BuilderSetView',
           'BuilderSetAddView',
           'BuilderNavigation',
           'BuilderFacets',
           'BuilderOverviewMenu',
           'BuilderView']

import datetime
import pytz

import zope.security.interfaces
from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser.add import AddView
from zope.app.event.objectevent import ObjectCreatedEvent

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.browser.build import BuildRecordsView
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces import (
    IBuilderSet, IBuilder, IBuildSet, IPerson, NotFoundError)
from canonical.launchpad.webapp import (
    ApplicationMenu, GetitemNavigation, Link, Navigation,
    StandardLaunchpadFacets, canonical_url, enabled_with_permission,
    stepthrough)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.tales import DateTimeFormatterAPI
from canonical.lazr import decorates


class BuilderSetNavigation(GetitemNavigation):
    """Navigation methods for IBuilderSet."""
    usedfor = IBuilderSet

    def breadcrumb(self):
        return 'Build Farm'

    @stepthrough('+build')
    def traverse_build(self, name):
        try:
            build_id = int(name)
        except ValueError:
            return None
        try:
            build = getUtility(IBuildSet).getByBuildID(build_id)
        except NotFoundError:
            return None
        else:
            return self.redirectSubTree(canonical_url(build))


class BuilderNavigation(Navigation):
    """Navigation methods for IBuilder."""
    usedfor = IBuilder

    def breadcrumb(self):
        return self.context.title


class BuilderSetFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IBuilderSet."""
    enable_only = ['overview']

    usedfor = IBuilderSet


class BuilderFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IBuilder."""
    enable_only = ['overview']

    usedfor = IBuilder


class BuilderSetOverviewMenu(ApplicationMenu):
    """Overview Menu for IBuilderSet."""
    usedfor = IBuilderSet
    facet = 'overview'
    links = ['add']

    @enabled_with_permission('launchpad.Admin')
    def add(self):
        text = 'Add builder'
        return Link('+new', text, icon='add')


class BuilderOverviewMenu(ApplicationMenu):
    """Overview Menu for IBuilder."""
    usedfor = IBuilder
    facet = 'overview'
    links = ['history', 'edit', 'mode', 'cancel', 'admin']

    def history(self):
        text = 'Show build history'
        return Link('+history', text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def mode(self):
        text = 'Change mode'
        return Link('+mode', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def cancel(self):
        text = 'Cancel current job'
        return Link('+cancel', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def admin(self):
        text = 'Administer builder'
        return Link('+admin', text, icon='edit')


class CommonBuilderView:
    """Common builder methods used in this file."""

    def now(self):
        """Offers the timestamp for page rendering."""
        UTC = pytz.timezone('UTC')
        return DateTimeFormatterAPI(datetime.datetime.now(UTC)).datetime()


class BuilderSetView(CommonBuilderView):
    """Default BuilderSet view class

    Simply provides CommonBuilderView for the BuilderSet pagetemplate.
    """
    __used_for__ = IBuilderSet

    @cachedproperty
    def non_virtual_build_queue_depth_by_arch(self):
        """Wrap `IBuilder.getBuildQueueDepthByArch` for the non-vitualised farm.

        Return the listified results.
        """
        return shortlist(
            self.context.getBuildQueueDepthByArch(virtualised=False))

    @cachedproperty
    def has_non_virtual_queued_builds(self):
        """Whether or not there are pending job in the non-virtual queue."""
        return bool(self.non_virtual_build_queue_depth_by_arch)

    @cachedproperty
    def virtual_build_queue_depth_by_arch(self):
        """Wrap `IBuilder.getBuildQueueDepthByArch` for the vitualised farm.

        Return the listified results.
        """
        return shortlist(
            self.context.getBuildQueueDepthByArch(virtualised=True))

    @cachedproperty
    def has_virtual_queued_builds(self):
        """Whether or not there are pending job in the virtual queue."""
        return bool(self.virtual_build_queue_depth_by_arch)



class HiddenBuilder:
    """Overrides a IBuilder building a private job.

    This class modifies IBuilder attributes that should not be exposed
    while building a job for private job (private PPA or Security).
    """
    decorates(IBuilder)

    failnotes = None
    currentjob = None
    builderok = False

    def __init__(self, context):
        self.context = context

    @property
    def status(self):
        if self.context.manual:
            mode = 'MANUAL'
        else:
            mode = 'AUTO'

        return "NOT OK: (%s)" % mode


class BuilderView(CommonBuilderView, BuildRecordsView):
    """Default Builder view class

    Implements useful actions for the page template.
    """
    __used_for__ = IBuilder

    def __init__(self, context, request):
        current_job = context.currentjob
        if current_job and not check_permission(
            'launchpad.View', current_job.build):
            # Cloak the builder.
            context = HiddenBuilder(context)
        super(BuilderView, self).__init__(context, request)

    def cancelBuildJob(self):
        """Cancel curent job in builder."""
        builder_id = self.request.form.get('BUILDERID')
        if not builder_id:
            return
        # XXX cprov 2005-10-14
        # The 'self.context.slave.abort()' seems to work with the new
        # BuilderSlave class added by dsilvers, but I won't release it
        # until we can test it properly, since we can only 'abort' slaves
        # in BUILDING state it does depends of the major issue for testing
        # Auto Build System, getting slave building something sane.
        return '<p>Cancel (%s). Not implemented yet.</p>' % builder_id

    @property
    def default_build_state(self):
        """Present all jobs by default."""
        return None

    @property
    def show_builder_info(self):
        """Hide Builder info, see BuildRecordsView for further details"""
        return False


class BuilderSetAddView(AddView):
    """Builder add view

    Extends zope AddView and uses IBuilderSet utitlity to create a new
    IBuilder.
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
        # XXX cprov 2005-06-21
        # expand dict !!
        builder = builder_util.new(**kw)
        notify(ObjectCreatedEvent(builder))
        self._nextURL = kw['name']
        return builder

    def nextURL(self):
        return self._nextURL
