# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser code for the malone application."""

__metaclass__ = type
__all__ = [
    'MaloneApplicationNavigation',
    'MaloneContextMenu',
    ]


from zope.component import getUtility
from zope.security.interfaces import Unauthorized

import canonical.launchpad.layers

from canonical.launchpad.webapp import (
    ContextMenu, Link, Navigation, canonical_url, stepto)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.menu import NavigationMenu

from lp.bugs.browser.bug import MaloneView
from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.interfaces.bugtracker import IBugTrackerSet
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.malone import IMaloneApplication
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.product import IProductSet


class MaloneApplicationNavigation(Navigation):

    usedfor = IMaloneApplication

    newlayer = canonical.launchpad.layers.BugsLayer

    @stepto('bugs')
    def bugs(self):
        return getUtility(IBugSet)

    @stepto('bugtrackers')
    def bugtrackers(self):
        return getUtility(IBugTrackerSet)

    @stepto('cve')
    def cve(self):
        return getUtility(ICveSet)

    @stepto('distros')
    def distros(self):
        return getUtility(IDistributionSet)

    @stepto('projects')
    def projects(self):
        return getUtility(IProductSet)

    @stepto('products')
    def products(self):
        return self.redirectSubTree(
            canonical_url(getUtility(IProductSet)), status=301)

    def traverse(self, name):
        # Make /bugs/$bug.id, /bugs/$bug.name /malone/$bug.name and
        # /malone/$bug.id Just Work
        bug = getUtility(IBugSet).getByNameOrID(name)
        if not check_permission("launchpad.View", bug):
            raise Unauthorized("Bug %s is private" % name)
        return bug


class MaloneContextMenu(ContextMenu):
    # XXX mpt 2006-03-27: No longer visible on Bugs front page.
    usedfor = IMaloneApplication
    links = ['cvetracker']

    def cvetracker(self):
        text = 'CVE tracker'
        return Link('cve/', text, icon='cve')


class MaloneRelatedPages(NavigationMenu):

    facet = 'bugs'
    title = 'Related pages'
    usedfor = MaloneView
    links = ['bugtrackers', 'cvetracker']

    def bugtrackers(self):
        url = canonical_url(getUtility(IBugTrackerSet))
        text = "Bug trackers"
        return Link(url, text, icon='bug')

    def cvetracker(self):
        text = 'CVE tracker'
        return Link('cve/', text, icon='cve')
