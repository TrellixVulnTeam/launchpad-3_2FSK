# Copyright Canonical

__metaclass__ = type

__all__ = [
    'PersonBugsFeed',
    'ProductBugsFeed',
    ]

import cgi
from datetime import datetime
from zope.app.pagetemplate import ViewPageTemplateFile

from canonical.lazr.feed import (
    FeedBase,FeedEntry, FeedPerson, FeedTypedData, MINUTES)
from canonical.launchpad.interfaces import (
    IPerson, IProduct)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.tales import FormattersAPI
from canonical.launchpad.browser import PersonRelatedBugsView

class ProductBugsFeed(FeedBase):

    # XXX, bac - This variable is currently not used.
    usedfor = IProduct

    # Will be served as:
    #     $product/latest-bugs.atom, and as
    # XXX    $product/latest-bugs.html, and as
    # XXX    $product/latest-bugs.js
    #feed_name = 'latest-bugs'
    feed_name = 'latest-bugs.atom'

    max_age = 30 * MINUTES

    def getTitle(self):
        # Title of the whole feed.
        return "Bugs in %s" % self.context.displayname

    def getURL(self):
        # URL to the homepage of the object represented by the feed.
        #return canonical_url(self.context, rootsite = "bugs")
        return "%s/%s" % (canonical_url(self.context), self.feed_name)

    def getItems(self, quantity=5):
        # Items in the feed.  The number of items is configured separately,
        # either globally for Launchpad as a whole, or in the ZCML.
        # If we find we have a requirement for different numbers of items per
        # feed, we'll include it in the class definition.
        if self.items is None:
            items = self.context.getLatestBugTasks(quantity=quantity)
            self.items = [self.itemToFeedEntry(item) for item in items]
        return self.items

    def getLogo(self):
        return "http://launchpad.dev/+icing/app-bugs.gif"

    def itemToFeedEntry(self, item):

        def unescape(s):
            s = s.replace("&lt;", "<")
            s = s.replace("&gt;", ">")
            # this has to be last:
            s = s.replace("&amp;", "&")
            return s

        bugtask = item
        bug = bugtask.bug
        title = FeedTypedData('[%s] %s' % (bug.id, bug.title))
        url = canonical_url(bugtask, rootsite="bugs")
        formatter = FormattersAPI(bug.description)
        # XXX bac, The Atom spec says all content is to be escaped.  When it
        # is escaped Safari and Firefox do not display the HTML correctly.
        #entry.content = cgi.escape(formatter.text_to_html())
        content = formatter.text_to_html()
        template = ViewPageTemplateFile('templates/bug.pt')
        #import pdb; pdb.set_trace(); # DO NOT COMMIT
        content = template(self)
        entry = FeedEntry(title = title,
                          id_ = url,
                          link_alternate = url,
                          date_updated = bug.date_last_updated,
                          date_published = bugtask.datecreated,
                          authors = [FeedPerson(bug.owner)],
                          content = FeedTypedData(content, content_type="xhtml"))
        return entry


class PersonBugsFeed(FeedBase, PersonRelatedBugsView):

    usedfor = IPerson

    # Will be served as:
    #     $product/latest-bugs.atom, and as
    # XXX    $product/latest-bugs.html, and as
    # XXX    $product/latest-bugs.js
    #feed_name = 'latest-bugs'
    feed_name = 'latest-bugs.atom'

    max_age = 30 * MINUTES

    def getTitle(self):
        # Title of the whole feed.
        return "Bugs for %s" % self.context.displayname

    def getURL(self):
        # URL to the homepage of the object represented by the feed.
        #return canonical_url(self.context, rootsite = "bugs")
        return "%s/%s" % (canonical_url(self.context), self.feed_name)

    def getItems(self, quantity=5):
        # Items in the feed.  The number of items is configured separately,
        # either globally for Launchpad as a whole, or in the ZCML.
        # If we find we have a requirement for different numbers of items per
        # feed, we'll include it in the class definition.
        if self.items is None:
            #items = self.context.getLatestBugs(quantity=quantity)
            items = self.search()
            self.items = [self.itemToFeedEntry(item) for item in items]
        return self.items

    def getLogo(self):
        return "http://launchpad.dev/+icing/app-bugs.gif"

    def itemToFeedEntry(self, item):
        bugtask = item
        bug = bugtask.bug
        title = FeedTypedData('[%s] %s' % (bug.id, bug.title))
        url = canonical_url(bugtask, rootsite="bugs")
        formatter = FormattersAPI(bug.description)
        # XXX bac, The Atom spec says all content is to be escaped.  When it
        # is escaped Safari and Firefox do not display the HTML correctly.
        #entry.content = cgi.escape(formatter.text_to_html())
        content = formatter.text_to_html()
        entry = FeedEntry(title = title,
                          id_ = url,
                          link_alternate = url,
                          date_updated = bug.date_last_updated,
                          date_published = bugtask.datecreated,
                          authors = [FeedPerson(bug.owner)],
                          content = FeedTypedData(content, content_type="html"))
        return entry
