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
from zope.schema.interfaces import IObject
from zope.component import getUtility

from canonical.launchpad import _
from canonical.launchpad.fields import (
    ContentNameField, StrippedTextLine, URIField)
from canonical.launchpad.interfaces.person import IPerson
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.name import name_validator

from canonical.lazr import DBEnumeratedType, DBItem
from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, exported)
from canonical.lazr.fields import CollectionField, Reference


LOCATION_SCHEMES_ALLOWED = 'http', 'https', 'mailto'


class BugTrackerNameField(ContentNameField):

    errormessage = _("%s is already in use by another bugtracker.")

    @property
    def _content_iface(self):
        return IBugTracker

    def _getByName(self, name):
        return getUtility(IBugTrackerSet).getByName(name)


class BugTrackerURL(URIField):
    """A bug tracker URL that's not used by any other bug trackers.

    When checking if the URL is already registered with another
    bugtracker, it takes into account that the URL may differ slightly,
    i.e. it could end with a slash or be https instead of http.
    """

    def _validate(self, input):
        """Check that the URL is not already in use by another bugtracker."""
        super(BugTrackerURL, self)._validate(input)
        bugtracker = getUtility(IBugTrackerSet).queryByBaseURL(input)
        if bugtracker is not None and bugtracker != self.context:
            raise LaunchpadValidationError(
                "%s is already registered in Launchpad." % input)


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
        SourceForge or SourceForge derivative

        SorceForge is a collaborative revision control and software
        development management system. It has several derivatives,
        including GForge, RubyForge, BerliOS and JavaForge.
        """)

    MANTIS = DBItem(6, """
        Mantis

        Mantis is a web-based bug tracking system written in PHP.
        """)

    RT = DBItem(7, """
        Request Tracker (RT)

        RT is a web-based ticketing system written in Perl.
        """)

    EMAILADDRESS = DBItem(8, """
        Email Address

        Bugs are tracked by email, perhaps on a mailing list.
        """)

    SAVANE = DBItem(9, """
        Savane

        Savane is a web-based project hosting system which includes
        support and request tracking. The best-known example of Savane
        is GNU's Savannah.
        """)

    PHPPROJECT = DBItem(10, """
        PHP Project Bugtracker

        The bug tracker developed by the PHP project.
        """)


class IBugTracker(Interface):
    """A remote bug system."""
    export_as_webservice_entry()

    id = Int(title=_('ID'))
    bugtrackertype = exported(
        Choice(title=_('Bug Tracker Type'),
               vocabulary=BugTrackerType,
               default=BugTrackerType.BUGZILLA),
        exported_as='bug_tracker_type')
    name = exported(
        BugTrackerNameField(
            title=_('Name'),
            constraint=name_validator,
            description=_('An URL-friendly name for the bug tracker, '
                          'such as "mozilla-bugs".')))
    title = exported(
        TextLine(
            title=_('Title'),
            description=_('A descriptive label for this tracker to show '
                          'in listings.')))
    summary = exported(
        Text(
            title=_('Summary'),
            description=_(
                'A brief introduction or overview of this bug '
                'tracker instance.'),
            required=False))
    baseurl = exported(
        BugTrackerURL(
            title=_('Location'),
            allowed_schemes=LOCATION_SCHEMES_ALLOWED,
            description=_(
                'The top-level URL for the bug tracker, or an upstream email '
                'address. This must be accurate so that Launchpad can link '
                'to external bug reports.')),
        exported_as='base_url')
    aliases = exported(
        List(
            title=_('Location aliases'),
            description=_(
                'A list of URLs or email addresses that all lead to the '
                'same bug tracker, or commonly seen typos, separated by '
                'whitespace.'),
            value_type=BugTrackerURL(
                allowed_schemes=LOCATION_SCHEMES_ALLOWED),
            required=False),
        exported_as='base_url_aliases')
    owner = exported(
        Reference(title=_('Owner'), schema=IPerson),
        exported_as='registrant')
    contactdetails = exported(
        Text(
            title=_('Contact details'),
            description=_(
                'The contact details for the external bug tracker (so that, '
                'for example, its administrators can be contacted about a '
                'security breach).'),
            required=False),
        exported_as='contact_details')
    watches = exported(
        CollectionField(
            title=_('The remote watches on this bug tracker.'),
            value_type=Reference(schema=IObject)))
    projects = Attribute('The projects that use this bug tracker.')
    products = Attribute('The products that use this bug tracker.')
    latestwatches = Attribute('The last 10 watches created.')
    imported_bug_messages = Attribute(
        'Bug messages that have been imported from this bug tracker.')

    def getBugFilingLink(remote_product):
        """Return the bug filing link for a given product on the tracker.

        :param remote_product: The name of the product on which the bug
            is to be filed. This is usually a string but can also take
            other forms. For example, SourceForge requires a GroupID and
            an ATID in order to be able to file a bug. These are passed
            in as a tuple of (group_id, at_id).
        :return: The absolute URL of the bug filing form for
            `remote_product` on the remote tracker or None if one doesn't
            exist for the current BugTrackerType.
        """

    def getBugsWatching(remotebug):
        """Get the bugs watching the given remote bug in this bug tracker."""

    def getBugWatchesNeedingUpdate(hours_since_last_check):
        """Get the bug watches needing to be updated.

        All bug watches not being updated for the last
        :hours_since_last_check: hours are considered needing to be
        updated.
        """

    def getLinkedPersonByName(name):
        """Return the `IBugTrackerPerson` for a given name on a bugtracker.

        :param name: The name of the person on the bugtracker in
            `bugtracker`.
        :return: an `IBugTrackerPerson`.
        """

    def linkPersonToSelf(name, person):
        """Link a Person to the BugTracker using a given name.

        :param name: The name used for person on bugtracker.
        :param person: The `IPerson` to link to bugtracker.
        :raise BugTrackerPersonAlreadyExists: If `name` has already been
            used to link a person to `bugtracker`.
        :return: An `IBugTrackerPerson`.
        """

    def ensurePersonForSelf(
        display_name, email, rationale, creation_comment):
        """Return the correct `IPerson` for a given name on a bugtracker.

        :param bugtracker: The `IBugTracker` for which we should have a
            given Person.
        :param display_name: The name of the Person on `bugtracker`.
        :param email: The Person's email address if available. If `email`
            is supplied a Person will be created or retrieved using that
            email address and no `IBugTrackerPerson` records will be created.
        :param rationale: The `PersonCreationRationale` used to create a
            new `IPerson` for this `name` and `bugtracker`, if necessary.
        :param creation_comment: The creation comment for the `IPerson`
            if one is created.
         """

    def destroySelf():
        """Delete this bug tracker."""


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

    def getPillarsForBugtrackers(bug_trackers):
        """Return dict mapping bugtrackers to lists of pillars."""


class IBugTrackerAlias(Interface):
    """Another URL for a remote bug system.

    Used to prevent accidental duplication of bugtrackers and so
    reduce the gardening burden.
    """

    id = Int(title=_('ID'))
    bugtracker = Object(
        title=_('The bugtracker for which this is an alias.'),
        schema=IBugTracker)
    base_url = BugTrackerURL(
        title=_('Location'),
        allowed_schemes=LOCATION_SCHEMES_ALLOWED,
        description=_('Another URL or email address for the bug tracker.'))


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
