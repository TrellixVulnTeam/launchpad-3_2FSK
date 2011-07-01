# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities for the update-bugzilla-remote-components cronscript"""

__metaclass__ = type
__all__ = [
    'BugzillaRemoteComponentFinder',
    'BugzillaRemoteComponentScraper',
    ]

import re
from urllib2 import (
    HTTPError,
    urlopen,
    )
from BeautifulSoup import BeautifulSoup
from canonical.launchpad.scripts.logger import log as default_log
from zope.component import getUtility
from lp.bugs.interfaces.bugtracker import (
    BugTrackerType,
    IBugTrackerSet,
    )
from lp.bugs.model.bugtracker import (
    BugTrackerComponent,
    )
from canonical.launchpad.interfaces.lpstorm import IStore


def dictFromCSV(line):
    items_dict = {}
    for item in line.split(","):
        item = item.strip()
        item = item.replace("'", "")
        item = item.replace("\\", "")
        items_dict[item] = {
            'name': item,
            }
    return items_dict


class BugzillaRemoteComponentScraper:
    """Scrapes Bugzilla query.cgi page for lists of products and components"""

    re_cpts = re.compile(r'cpts\[(\d+)\] = \[(.*)\]')
    re_vers = re.compile(r'vers\[(\d+)\] = \[(.*)\]')

    def __init__(self, base_url=None):
        self.base_url = re.sub(r'/$', '', base_url)
        self.url = "%s/query.cgi?format=advanced" % (self.base_url)
        self.products = {}

    def getPage(self):
        return urlopen(self.url).read()

    def parsePage(self, page_text):
        soup = BeautifulSoup(page_text)
        if soup is None:
            return None

        # Load products into a list since Bugzilla references them
        # by index number
        products = []
        for product in soup.find(
            name='select',
            onchange="doOnSelectProduct(2);").contents:
            if product.string != "\n":
                products.append({
                    'name': product.string,
                    'components': {},
                    'versions': None,
                    })

        for script_text in soup.findAll(name="script"):
            if script_text is None or script_text.string is None:
                continue
            for line in script_text.string.split(";"):
                m = self.re_cpts.search(line)
                if m:
                    num = int(m.group(1))
                    products[num]['components'] = dictFromCSV(m.group(2))

                m = self.re_vers.search(line)
                if m:
                    num = int(m.group(1))
                    products[num]['versions'] = dictFromCSV(m.group(2))

        # Re-map list into dict for easier lookups
        for product in products:
            product_name = product['name']
            self.products[product_name] = product

        return True


class BugzillaRemoteComponentFinder:
    """Updates remote components for all Bugzillas registered in Launchpad"""

    # Names of bug trackers we should not pull data from
    _BLACKLIST = [
        u"ubuntu-bugzilla",
        u"mozilla.org",
        ]

    def __init__(self, logger=None, static_bugzilla_scraper=None):
        """Instantiates object, without performing any parsing.

        :param logger: A logger object
        :param static_bugzilla_scraper: Substitute this custom bugzilla
         scraper object instead of constructing a new
         BugzillaRemoteComponentScraper for each bugtracker's URL.  This
         is intended for testing purposes to avoid needing to make remote
         web connections.
        """
        self.logger = logger
        if logger is None:
            self.logger = default_log
        self.static_bugzilla_scraper = static_bugzilla_scraper

    def getRemoteProductsAndComponents(self, bugtracker_name=None):
        lp_bugtrackers = getUtility(IBugTrackerSet)
        if bugtracker_name is not None:
            lp_bugtrackers = [
                lp_bugtrackers.getByName(bugtracker_name),
                ]
            if not lp_bugtrackers or len(lp_bugtrackers) != 1:
                self.logger.warning(
                    "Could not find specified bug tracker %s",
                    bugtracker_name)
        for lp_bugtracker in lp_bugtrackers:
            if lp_bugtracker.bugtrackertype != BugTrackerType.BUGZILLA:
                continue
            if lp_bugtracker.name in self._BLACKLIST:
                continue

            self.logger.info("%s: %s" % (
                lp_bugtracker.name, lp_bugtracker.baseurl))

            if self.static_bugzilla_scraper is not None:
                bz_bugtracker = self.static_bugzilla_scraper
            else:
                bz_bugtracker = BugzillaRemoteComponentScraper(
                    base_url=lp_bugtracker.baseurl)

            try:
                self.logger.debug("...Fetching page")
                page_text = bz_bugtracker.getPage()
            except HTTPError, error:
                self.logger.error("Error fetching %s: %s" % (
                    lp_bugtracker.baseurl, error))
                continue
            except:
                self.logger.error("Failed to access %s" % (
                    lp_bugtracker.baseurl))
                continue

            self.logger.debug("...Parsing html")
            bz_bugtracker.parsePage(page_text)

            self.logger.debug("...Storing new data to Launchpad")
            self.storeRemoteProductsAndComponents(
                bz_bugtracker, lp_bugtracker)

    def storeRemoteProductsAndComponents(self, bz_bugtracker, lp_bugtracker):
        components_to_add = []
        for product in bz_bugtracker.products.itervalues():
            # Look up the component group id from Launchpad for the product
            # if it already exists.  Otherwise, add it.
            lp_component_group = lp_bugtracker.getRemoteComponentGroup(
                product['name'])
            if lp_component_group is None:
                lp_component_group = lp_bugtracker.addRemoteComponentGroup(
                    product['name'])
                if lp_component_group is None:
                    self.logger.warning("Failed to add new component group")
                    continue
            else:
                for component in lp_component_group.components:
                    if (component.name in product['components'] or
                        component.is_visible == False or
                        component.is_custom == True):
                        # We already know something about this component,
                        # or a user has configured it, so ignore it
                        del product['components'][component.name]
                    else:
                        # Component is now missing from Bugzilla,
                        # so drop it here too
                        component.remove()

            # The remaining components in the collection will need to be
            # added to launchpad.  Record them for now.
            for component in product['components'].values():
                components_to_add.append(
                    "('%s', %d, 'True', 'False')" % (
                        component['name'], lp_component_group.id))

        if len(components_to_add) > 0:
            sqltext = """
            INSERT INTO BugTrackerComponent
            (name, component_group, is_visible, is_custom)
            VALUES %s""" % ",\n ".join(components_to_add)

            self.logger.debug("...Inserting components into database")
            store = IStore(BugTrackerComponent)
            store.execute(sqltext)
            store.commit()
            store.flush()
            self.logger.debug("...Done")
