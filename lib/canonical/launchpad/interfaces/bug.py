# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Interfaces related to bugs."""

__metaclass__ = type

__all__ = [
    'CreatedBugWithNoBugTasksError',
    'IBug',
    'IBugSet',
    'IBugDelta',
    'IBugAddForm',
    ]

from zope.component import getUtility
from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, Int, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.interfaces.validation import non_duplicate_bug
from canonical.launchpad.interfaces.messagetarget import IMessageTarget
from canonical.launchpad.interfaces.launchpad import NotFoundError
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.fields import (
    ContentNameField, Title, BugField)


class BugNameField(ContentNameField):
    errormessage = _("%s is already in use by another bug.")

    @property
    def _content_iface(self):
        return IBug

    def _getByName(self, name):
        try:
            return getUtility(IBugSet).getByNameOrID(name)
        except NotFoundError:
            return None


class CreatedBugWithNoBugTasksError(Exception):
    """Raised when a bug is created with no bug tasks."""


class IBug(IMessageTarget):
    """The core bug entry."""

    id = Int(
        title=_('Bug ID'), required=True, readonly=True)
    datecreated = Datetime(
        title=_('Date Created'), required=True, readonly=True)
    name = BugNameField(
        title=_('Nickname'), required=False,
        description=_("""A short and unique name for this bug.
        Add a nickname only if you often need to retype the URL
        but have trouble remembering the bug number."""),
        constraint=name_validator)
    title = Title(
        title=_('Summary'), required=True,
        description=_("""A one-line summary of the problem."""))
    description = Text(
        title=_('Description'), required=True,
        description=_("""A detailed description of the problem,
        including the steps required to reproduce it."""))
    ownerID = Int(title=_('Owner'), required=True, readonly=True)
    owner = Attribute("The owner's IPerson")
    duplicateof = BugField(
        title=_('Duplicate Of'), required=False, constraint=non_duplicate_bug)
    communityscore = Int(
        title=_('Community Score'), required=True, readonly=True, default=0)
    communitytimestamp = Datetime(
        title=_('Community Timestamp'), required=True, readonly=True)
    hits = Int(
        title=_('Hits'), required=True, readonly=True, default=0)
    hitstimestamp = Datetime(
        title=_('Hits Timestamp'), required=True, readonly=True)
    activityscore = Int(
        title=_('Activity Score'), required=True, readonly=True,
        default=0)
    activitytimestamp = Datetime(
        title=_('Activity Timestamp'), required=True, readonly=True)
    private = Bool(
        title=_("Keep bug confidential"), required=False,
        description=_("Make this bug visible only to its subscribers"),
        default=False)
    security_related = Bool(
        title=_("Security related"), required=False,
        description=_(
        "Select this option if the bug is a security issue"),
        default=False)
    displayname = TextLine(title=_("Text of the form 'Bug #X"),
        readonly=True)
    activity = Attribute('SQLObject.Multijoin of IBugActivity')
    initial_message = Attribute(
        "The message that was specified when creating the bug")
    bugtasks = Attribute('BugTasks on this bug, sorted upstream, then '
        'ubuntu, then other distroreleases.')
    productinfestations = Attribute('List of product release infestations.')
    packageinfestations = Attribute('List of package release infestations.')
    watches = Attribute('SQLObject.Multijoin of IBugWatch')
    externalrefs = Attribute('SQLObject.Multijoin of IBugExternalRef')
    cves = Attribute('CVE entries related to this bug.')
    cve_links = Attribute('LInks between this bug and CVE entries.')
    subscriptions = Attribute('SQLObject.Multijoin of IBugSubscription')
    duplicates = Attribute(
        'MultiJoin of the bugs which are dups of this one')
    attachments = Attribute("List of bug attachments.")
    tickets = Attribute("List of support tickets related to this bug.")
    specifications = Attribute("List of related specifications.")
    bug_branches = Attribute(
        "Branches associated with this bug, usually "
        "branches on which this bug is being fixed.")

    def followup_subject():
        """Return a candidate subject for a followup message."""

    # subscription-related methods
    def subscribe(person):
        """Subscribe person to the bug. Returns an IBugSubscription."""

    def unsubscribe(person):
        """Remove this person's subscription to this bug."""

    def isSubscribed(person):
        """Is person subscribed to this bug?

        Returns True if the user is explicitly subscribed to this bug
        (no matter what the type of subscription), otherwise False.
        """

    def notificationRecipientAddresses():
        """Return the list of email addresses that recieve notifications.

        If this bug is a duplicate of another bug, the CC'd list of
        the dup target will be appended to the list of recipient
        addresses.
        """

    def addChangeNotification(text, person):
        """Add a bug change notification."""

    def addCommentNotification(message):
        """Add a bug comment notification."""

    def addWatch(bugtracker, remotebug, owner):
        """Create a new watch for this bug on the given remote bug and bug
        tracker, owned by the person given as the owner.
        """

    def hasBranch(branch):
        """Is this branch linked to this bug?"""

    def addBranch(branch, status):
        """Associate a branch with this bug.

        Returns an IBugBranch.
        """

    # CVE related methods
    def linkCVE(cve, user=None):
        """Ensure that this CVE is linked to this bug."""

    def unlinkCVE(cve, user=None):
        """Ensure that any links between this bug and the given CVE are
        removed.
        """

    def findCvesInText(self, text):
        """Find any CVE references in the given text, make sure they exist
        in the database, and are linked to this bug.
        """


class IBugDelta(Interface):
    """The quantitative change made to a bug that was edited."""

    bug = Attribute("The IBug, after it's been edited.")
    bugurl = Attribute("The absolute URL to the bug.")
    user = Attribute("The IPerson that did the editing.")

    # fields on the bug itself
    title = Attribute("A dict with two keys, 'old' and 'new', or None.")
    description = Attribute("A dict with two keys, 'old' and 'new', or None.")
    private = Attribute("A dict with two keys, 'old' and 'new', or None.")
    security_related = Attribute(
        "A dict with two keys, 'old' and 'new', or None.")
    name = Attribute("A dict with two keys, 'old' and 'new', or None.")
    duplicateof = Attribute(
        "A dict with two keys, 'old' and 'new', or None. Key values are "
        "IBug's")

    # other things linked to the bug
    external_reference = Attribute(
        "A dict with two keys, 'old' and 'new', or None. Key values are "
        "IBugExternalRefs.")
    bugwatch = Attribute(
        "A dict with two keys, 'old' and 'new', or None. Key values are "
        "IBugWatch's.")
    attachment = Attribute(
        "A dict with two keys, 'old' and 'new', or None. Key values are "
        "IBugAttachment's.")
    cve = Attribute(
        "A dict with two keys, 'old' and 'new', or None. Key values are "
        "ICve's")
    added_bugtasks = Attribute(
        "A list or tuple of IBugTasks, one IBugTask, or None.")
    bugtask_deltas = Attribute(
        "A sequence of IBugTaskDeltas, one IBugTaskDelta or None.")


class IBugAddForm(IBug):
    """Information we need to create a bug"""
    id = Int(title=_("Bug #"), required=False)
    product = Choice(
            title=_("Product"), required=False,
            description=_("""The thing you found this bug in,
            which was installed by something other than apt-get, rpm,
            emerge or similar"""),
            vocabulary="Product")
    packagename = Choice(
            title=_("Package Name"), required=False,
            description=_("""The package you found this bug in,
            which was installed via apt-get, rpm, emerge or similar."""),
            vocabulary="BinaryAndSourcePackageName")
    distribution = Choice(
            title=_("Linux Distribution"), required=True,
            description=_(
                "Ubuntu, Debian, Gentoo, etc. You can file bugs only on "
                "distrubutions using Malone as their primary bug "
                "tracker."),
            vocabulary="DistributionUsingMalone")
    owner = Int(title=_("Owner"), required=True)
    comment = Text(title=_('Description'), required=True,
            description=_("""A detailed description of the problem you are
            seeing."""))
    private = Bool(
            title=_("Should this bug be kept confidential?"), required=False,
            description=_(
                "Check this box if, for example, this bug exposes a security "
                "vulnerability. If you select this option, you must manually "
                "CC the people to whom this bug should be visible."),
            default=False)


class IBugSet(Interface):
    """A set of bugs."""

    def get(bugid):
        """Get a specific bug by its ID.

        If it can't be found, NotFoundError will be raised.
        """

    def getByNameOrID(bugid):
        """Get a specific bug by its ID or nickname

        If it can't be found, NotFoundError will be raised.
        """

    def searchAsUser(user, duplicateof=None, orderBy=None, limit=None):
        """Find bugs matching the search criteria provided.

        To search as an anonymous user, the user argument passed
        should be None.
        """

    def queryByRemoteBug(bugtracker, remotebug):
        """Find one or None bugs in Malone that have a BugWatch matching the
        given bug tracker and remote bug id."""

    def createBug(self, distribution=None, sourcepackagename=None,
                  binarypackagename=None, product=None, comment=None,
                  description=None, msg=None, datecreated=None, title=None,
                  security_related=False, private=False, owner=None):
        """Create a bug and return it.

        Things to note when using this factory:

          * if no description is passed, the comment will be used as the
            description

          * the reporter will be subscribed to the bug

          * distribution, product and package contacts (whichever ones are
            applicable based on the bug report target) will bug subscribed to
            all *public bugs only*

          * for public upstreams bugs where there is no upstream bug contact,
            the product owner will be subscribed instead

          * if either product or distribution is specified, an appropiate
            bug task will be created

          * binarypackagename, if not None, will be added to the bug's
            description
        """

