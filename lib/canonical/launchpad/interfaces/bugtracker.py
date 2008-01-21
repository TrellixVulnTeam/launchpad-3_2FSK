# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Bug tracker interfaces."""

__metaclass__ = type

__all__ = [
    'BugTrackerType',
    'IBugTracker',
    'IBugTrackerAlias',
    'IBugTrackerAliasSet',
    'IBugTrackerSet',
    'IRemoteBug']

from zope.interface import Attribute, Interface
from zope.schema import (
    Choice, Int, List, Object, Text, TextLine)
from zope.component import getUtility

from canonical.launchpad import _
from canonical.launchpad.fields import (
    ContentNameField, StrippedTextLine, UniqueField, URIField)
from canonical.launchpad.validators.name import name_validator

from canonical.lazr import DBEnumeratedType, DBItem

class BugTrackerNameField(ContentNameField):

    errormessage = _("%s is already in use by another bugtracker.")

    @property
    def _content_iface(self):
        return IBugTracker

    def _getByName(self, name):
        return getUtility(IBugTrackerSet).getByName(name)


class BugTrackerBaseURL(UniqueField):
    """A bug tracker base URL that's not used by any other bug trackers.

    When checking if the URL is already registered with another
    bugtracker, it takes into account that the URL may differ slightly,
    i.e. it could end with a slash or be https instead of http.
    """

    errormessage = _("%s is already registered in Launchpad.")
    attribute = 'baseurl'

    @property
    def _content_iface(self):
        return IBugTracker

    def _getByAttribute(self, base_url):
        """See `UniqueField`."""
        return getUtility(IBugTrackerSet).queryByBaseURL(base_url)


class BugTrackerType(DBEnumeratedType):
    """The Types of BugTracker Supported by Launchpad.

    This enum is used to differentiate between the different types of Bug
    Tracker that are supported by Malone in the Launchpad.
    """

    BUGZILLA = DBItem(1, """
        Bugzilla

        The godfather of open source bug tracking, the Bugzilla system was
        developed for the Mozilla project and is now in widespread use. It
        is big and ugly but also comprehensive.
        """)

    DEBBUGS = DBItem(2, """
        Debbugs

        The debbugs tracker is email based, and allows you to treat every
        bug like a small mailing list.
        """)

    ROUNDUP = DBItem(3, """
        Roundup

        Roundup is a lightweight, customisable and fast web/email based bug
        tracker written in Python.
        """)

    TRAC = DBItem(4, """
        Trac

        Trac is an enhanced wiki and issue tracking system for
        software development projects.
        """)

    SOURCEFORGE = DBItem(5, """
        SourceForge

        SourceForge is a project hosting service which includes bug,
        support and request tracking.
        """)

    MANTIS = DBItem(6, """
        Mantis

        Mantis is a web-based bug tracking system written in PHP.
        """)

    RT = DBItem(7, """
        Request Tracker (RT)

        RT is a web-based ticketing system written in Perl.
        """)


class IBugTracker(Interface):
    """A remote bug system."""

    id = Int(title=_('ID'))
    bugtrackertype = Choice(
        title=_('Bug Tracker Type'),
        vocabulary=BugTrackerType,
        default=BugTrackerType.BUGZILLA)
    name = BugTrackerNameField(
        title=_('Name'),
        constraint=name_validator,
        description=_('An URL-friendly name for the bug tracker, '
        'such as "mozilla-bugs".'))
    title = TextLine(
        title=_('Title'),
        description=_(
            'A descriptive label for this tracker to show in listings.'))
    summary = Text(
        title=_('Summary'),
        description=_(
            'A brief introduction or overview of this bug tracker instance.'),
        required=False)
    baseurl = BugTrackerBaseURL(
        title=_('Base URL'),
        description=_(
            'The top-level URL for the bug tracker. This must be accurate '
            'so that Launchpad can link to external bug reports.'))
    aliases = List(
        title=_('Base URL aliases'),
        description=_(
            'A list of URLs that all lead to the same bug tracker, '
            'or commonly seen typos.'),
        value_type=URIField(), required=False)
    owner = Int(title=_('Owner'))
    contactdetails = Text(
        title=_('Contact details'),
        description=_(
            'The contact details for the external bug tracker (so that, for '
            'example, its administrators can be contacted about a security '
            'breach).'),
        required=False)
    watches = Attribute('The remote watches on this bug tracker.')
    projects = Attribute('The projects that use this bug tracker.')
    products = Attribute('The products that use this bug tracker.')
    latestwatches = Attribute('The last 10 watches created.')

    def getBugsWatching(remotebug):
        """Get the bugs watching the given remote bug in this bug tracker."""

    def getBugWatchesNeedingUpdate(hours_since_last_check):
        """Get the bug watches needing to be updated.

        All bug watches not being updated for the last
        :hours_since_last_check: hours are considered needing to be
        updated.
        """


class IBugTrackerSet(Interface):
    """A set of IBugTracker's.

    Each BugTracker is a distinct instance of a bug tracking tool. For
    example, bugzilla.mozilla.org is distinct from bugzilla.gnome.org.
    """

    title = Attribute('Title')

    bugtracker_count = Attribute("The number of registered bug trackers.")

    def get(bugtracker_id, default=None):
        """Get a BugTracker by its id.

        If no tracker with the given id exists, return default.
        """

    def getByName(name, default=None):
        """Get a BugTracker by its name.

        If no tracker with the given name exists, return default.
        """

    def getBugTrackersByName(bug_trackers=[]):
        """Return all the bug trackers for the names specified.

        :param bug_trackers: A list of the bug tracker names to
            retrieve
        """

    def __getitem__(name):
        """Get a BugTracker by its name in the database.

        Note: We do not want to expose the BugTracker.id to the world
        so we use its name.
        """

    def __iter__():
        """Iterate through BugTrackers."""

    def queryByBaseURL(baseurl):
        """Return one or None BugTracker's by baseurl"""

    def ensureBugTracker(baseurl, owner, bugtrackertype,
        title=None, summary=None, contactdetails=None, name=None):
        """Make sure that there is a bugtracker for the given base url.

        If not, create one using the given attributes.
        """

    def search():
        """Search all the IBugTrackers in the system."""

    def getMostActiveBugTrackers(limit=None):
        """Return the top IBugTrackers.

        Returns a list of IBugTracker objects, ordered by the number
        of bugwatches for each tracker, from highest to lowest.
        """


class IBugTrackerAlias(Interface):
    """Another URL for a remote bug system.

    Used to prevent accidental duplication of bugtrackers and so
    reduce the gardening burden.
    """

    id = Int(title=_('ID'))
    bugtracker = Object(
        title=_('The bugtracker for which this is an alias.'),
        schema=IBugTracker)
    base_url = BugTrackerBaseURL(
        title=_('Base URL'),
        description=_('Another top-level URL for the bug tracker.'))


class IBugTrackerAliasSet(Interface):
    """A set of IBugTrackerAliases."""

    def queryByBugTracker(bugtracker):
        """Query IBugTrackerAliases by BugTracker."""


class IRemoteBug(Interface):
    """A remote bug for a given bug tracker."""

    bugtracker = Choice(title=_('Bug System'), required=True,
        vocabulary='BugTracker', description=_("The bug tracker in which "
        "the remote bug is found."))

    remotebug = StrippedTextLine(title=_('Remote Bug'), required=True,
        readonly=False, description=_("The bug number of this bug in the "
        "remote bug system."))

    bugs = Attribute(
        _("A list of the Launchpad bugs watching the remote bug."))

    title = TextLine(
        title=_('Title'),
        description=_('A descriptive label for this remote bug'))
