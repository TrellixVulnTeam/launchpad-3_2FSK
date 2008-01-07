# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Announcement feed (syndication) views."""

# This module has been chosen to be the example for how to implement a new
# feed class.  While the two interfaces `IFeed` and `IFeedEntry` are heavily
# documented, additional documentation has been added to this module to
# clearly demonstrate the concepts required to implement a feed rather than
# simply referencing the interfaces.

__metaclass__ = type

__all__ = [
    'LaunchpadAnnouncementsFeed',
    'TargetAnnouncementsFeed',
    ]


import cgi
from zope.component import getUtility

from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.interfaces import (
    IAnnouncementSet, IDistribution, IHasAnnouncements, IProduct, IProject)
from canonical.launchpad.interfaces import IFeedsApplication
from canonical.lazr.feed import (
    FeedBase, FeedEntry, FeedPerson, FeedTypedData)


class AnnouncementsFeedBase(FeedBase):
    """Abstract class for announcement feeds."""

    # Every feed must have a feed name.  This name will be used to construct
    # the final element in the URL for the feed with the extension for one of
    # the supported feed types appended.  So announcement feeds will end with
    # 'announcements.atom' or 'announcements.html'.
    feedname = "announcements"

    @property
    def link_alternate(self):
        """See `IFeed`."""
        # Return the human-readable alternate URL for this feed.  For example:
        # https://launchpad.net/ubuntu/+announcements
        return "%s+announcements" % self._normalizedUrl(rootsite="mainsite")

    def itemToFeedEntry(self, announcement):
        """See `IFeed`."""
        # Given an instance of an announcement, create a FeedEntry out of it
        # and return.

        # The title for the FeedEntry is an IFeedTypedData instance and may be
        # plain text or html.
        title = self._entryTitle(announcement)
        # The link_alternate for the entry is the human-readable alternate URL
        # for the entry.  For example:
        # http://launchpad.net/ubuntu/+announcment/12
        entry_link_alternate = "%s%s" % (
            canonical_url(announcement.target, rootsite=self.rootsite),
            "/+announcement/%d" % announcement.id)
        # The content of the entry is the text displayed as the body in the
        # feed reader.  For announcements it is plain text but it must be
        # escaped to account for any special characters the user may have
        # entered, such as '&' and '<' because it will be embedded in the XML
        # document.
        content = FeedTypedData(cgi.escape(announcement.summary))
        # The entry for an announcement has distinct dates for created,
        # updated, and published.  For some data, the created and published
        # dates will be the same.  The announcements also only have a singe
        # author.
        entry = FeedEntry(title=title,
                          link_alternate=entry_link_alternate,
                          date_created=announcement.date_created,
                          date_updated=announcement.date_updated,
                          date_published=announcement.date_announced,
                          authors=[FeedPerson(
                                    announcement.registrant,
                                    rootsite="mainsite")],
                          content=content)
        return entry

    @property
    def link_self(self):
        """See `IFeed`."""

        # The self link is the URL for this particular feed.  For example:
        # http://feeds.launchpad.net/ubuntu/announcments.atom
        return "%s%s.%s" % (
            self._normalizedUrl(), self.feedname, self.format)

    def _entryTitle(self, announcement):
        """Return the title for the announcement.

        Override in each base class.
        """
        raise NotImplementedError

    def _normalizedUrl(self, rootsite=None):
        """Call 'canonical_url' and ensure the result ends with '/'.

        The results from calling 'canonical_url' are inconsistent as to
        whether a trailing '/' is present.  Normalize the results by ensuring
        a trailing '/' is at the end of the URL.
        """
        url = canonical_url(self.context, rootsite=rootsite)
        if not url.endswith('/'):
            url += '/'
        return url


class LaunchpadAnnouncementsFeed(AnnouncementsFeedBase):
    """Publish an Atom feed of all public announcements in Launchpad."""

    # The `usedfor` property identifies the class associated with this feed
    # class.  It is used by the `IFeedsDirective` in
    # launchpad/webapp/metazcml.py to provide a mapping from the supported
    # feed types to this class.  It is a more maintainable method than simply
    # listing each mapping in the zcml.  The only zcml change is to add this
    # class to the list of classes in the `browser:feeds` stanza of
    # launchpad/zcml/feeds.zcml.
    usedfor = IFeedsApplication

    def getItems(self):
        """See `IFeed`."""
        # Return a list of items that will be the entries in the feed.  Each
        # item shall be an instance of `IFeedEntry`.

        # The quantity is defined in FeedBase or config file.
        items = getUtility(IAnnouncementSet).announcements(
            limit=self.quantity)
        # Convert the items into their feed entry representation.
        items = [self.itemToFeedEntry(item) for item in items]
        return items

    def _entryTitle(self, announcement):
        """Return an `IFeedTypedData` instance for the feed title."""
        return FeedTypedData('[%s] %s' % (
                announcement.target.name, announcement.title))

    @property
    def title(self):
        """See `IFeed`."""
        # The textual representation of the title for the feed.
        return "Announcements published via Launchpad"

    @property
    def logo(self):
        """See `IFeed`."""
        # The logo is an image representing the feed.  Since this feed is for
        # all announcements in Launchpad, return the Launchpad logo.
        url = '/@@/launchpad-logo'
        return self.site_url + url

    @property
    def icon(self):
        """See `IFeed`."""
        # The icon is an icon representing the feed.  Since this feed is for
        # all announcements in Launchpad, return the Launchpad icon.
        url = '/@@/launchpad'
        return self.site_url + url


class TargetAnnouncementsFeed(AnnouncementsFeedBase):
    """Publish an Atom feed of all announcements.

    Used for any class that implements IHasAnnouncements such as project,
    product, or distribution.
    """
    # This view is used for any class implementing `IHasAnnouncments`.
    usedfor = IHasAnnouncements

    def getItems(self):
        """See `IFeed`."""
        # The quantity is defined in FeedBase or config file.
        items = self.context.announcements(limit=self.quantity)
        # Convert the items into their feed entry representation.
        items = [self.itemToFeedEntry(item) for item in items]
        return items

    def _entryTitle(self, announcement):
        return FeedTypedData(announcement.title)

    @property
    def title(self):
        """See `IFeed`."""
        return "%s Announcements" % self.context.displayname

    @property
    def logo(self):
        """See `IFeed`."""
        # The logo is different depending upon the context we are displaying.
        if self.context.logo is not None:
            return self.context.logo.getURL()
        elif IProject.providedBy(self.context):
            url = '/@@/project-logo'
        elif IProduct.providedBy(self.context):
            url = '/@@/product-logo'
        elif IDistribution.providedBy(self.context):
            url = '/@@/distribution-logo'
        else:
            raise AssertionError(
                "Context for TargetsAnnouncementsFeed does not provide an "
                "expected interface.")
        return self.site_url + url

    @property
    def icon(self):
        """See `IFeed`."""
        # The icon is customized based upon the context.
        if self.context.icon is not None:
            return self.context.icon.getURL()
        elif IProject.providedBy(self.context):
            url = '/@@/project'
        elif IProduct.providedBy(self.context):
            url = '/@@/product'
        elif IDistribution.providedBy(self.context):
            url = '/@@/distribution'
        else:
            raise AssertionError(
                "Context for TargetsAnnouncementsFeed does not provide an "
                "expected interface.")
        return self.site_url + url
