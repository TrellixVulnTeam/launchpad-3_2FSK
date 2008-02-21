# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Bug watch interfaces."""

__metaclass__ = type

__all__ = [
    'BugWatchErrorType',
    'IBugWatch',
    'IBugWatchSet',
    'NoBugTrackerFound',
    'UnrecognizedBugTrackerURL',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Choice, Datetime, Int, TextLine, Text

from canonical.launchpad import _
from canonical.launchpad.fields import StrippedTextLine
from canonical.launchpad.interfaces import IHasBug
from canonical.lazr import DBEnumeratedType, DBItem

class BugWatchErrorType(DBEnumeratedType):
    """An enumeration of possible BugWatch errors."""

    UNKNOWN = DBItem(999, """
        Unknown

        Launchpad encountered an unexpected error when trying to
        retrieve the bug from the remote server.
        """)

    BUG_NOT_FOUND = DBItem(1, """
        Bug Not Found

        Launchpad could not find the specified bug on the remote server.
        """)

    CONNECTION_ERROR = DBItem(2, """
        Connection Error

        Launchpad was unable to connect to the remote server.
        """)

    INVALID_BUG_ID = DBItem(3, """
        Invalid Bug ID

        The specified bug ID is not valid.
        """)

    TIMEOUT = DBItem(4, """
        Timeout

        Launchpad encountered a timeout when trying to connect to the
        remote server and was unable to retrieve the bug's status.
        """)

    UNPARSABLE_BUG = DBItem(5, """
        Unparsable Bug

        Launchpad could not extract a status from the data it received
        from the remote server.
        """)

    UNPARSABLE_BUG_TRACKER = DBItem(6, """
        Unparsable Bug Tracker Version

        Launchpad could not determine the version of the bug tracker 
        software running on the remote server.
        """)

    UNSUPPORTED_BUG_TRACKER = DBItem(7, """
        Unsupported Bugtracker

        The remote server is using bug tracker software which Launchpad
        does not currently support.
        """)


class IBugWatch(IHasBug):
    """A bug on a remote system."""

    id = Int(title=_('ID'), required=True, readonly=True)
    bug = Int(title=_('Bug ID'), required=True, readonly=True)
    bugtracker = Choice(title=_('Bug System'), required=True,
        vocabulary='BugTracker', description=_("You can register "
        "new bug trackers from the Launchpad Bugs home page."))
    remotebug = StrippedTextLine(title=_('Remote Bug'), required=True,
        readonly=False, description=_("The bug number of this bug in the "
        "remote bug tracker."))
    remotestatus = TextLine(title=_('Remote Status'))
    remote_importance = TextLine(title=_('Remote Importance'))
    lastchanged = Datetime(title=_('Last Changed'))
    lastchecked = Datetime(title=_('Last Checked'))
    last_error_type = Choice(title=_('Last Error Type'),
        vocabulary=BugWatchErrorType)
    datecreated = Datetime(
            title=_('Date Created'), required=True, readonly=True)
    owner = Int(title=_('Owner'), required=True, readonly=True)

    # useful joins
    bugtasks = Attribute('The tasks which this watch will affect. '
        'In Launchpad, a bug watch can be linked to one or more tasks, and '
        'if it is linked and we notice a status change in the watched '
        'bug then we will try to update the Launchpad bug task accordingly.')

    # properties
    needscheck = Attribute("A True or False indicator of whether or not "
        "this watch needs to be synchronised. The algorithm used considers "
        "the severity of the bug, as well as the activity on the bug, to "
        "ensure that we spend most effort on high-importance and "
        "high-activity bugs.")

    # required for launchpad pages
    title = Text(title=_('Bug watch title'), readonly=True)

    url = Text(title=_('The URL at which to view the remote bug.'),
        readonly=True)

    def updateImportance(remote_importance, malone_importance):
        """Update the importance of the bug watch and any linked bug task.

        The lastchanged attribute gets set to the current time.
        """

    def updateStatus(remote_status, malone_status):
        """Update the status of the bug watch and any linked bug task.

        The lastchanged attribute gets set to the current time.
        """

    def destroySelf():
        """Delete this bug watch."""

    def getLastErrorMessage():
        """Return a string describing the contents of last_error_type."""

    def hasComment(comment_id):
        """Return True if a comment has been imported for the BugWatch.

        If the comment has not been imported, return False.

        :param comment_id: The remote ID of the comment.
        """

    def addComment(comment_id, message):
        """Link and imported comment to the BugWatch.

        :param comment_id: The remote ID of the comment.

        :param message: The imported comment as a Launchpad Message object.
        """


class IBugWatchSet(Interface):
    """The set of IBugWatch's."""

    bug = Int(title=_("Bug id"), readonly=True)
    title = Attribute('Title')

    def __getitem__(key):
        """Get a BugWatch"""

    def __iter__():
        """Iterate through BugWatches for a given bug."""

    def get(id):
        """Get an IBugWatch by its ID.

        Raise a NotFoundError if there is no IBugWatch
        matching the given id.
        """

    def search():
        """Search through all the IBugWatches in the system."""

    def fromText(text, bug, owner):
        """Create one or more BugWatch's by analysing the given text. This
        will look for reference to known or new bug tracking instances and
        create the relevant watches. It returns a (possibly empty) list of
        watches created.
        """

    def fromMessage(message, bug):
        """Create one or more BugWatch's by analysing the given email. The
        owner of the BugWatch's will be the sender of the message.
        It returns a (possibly empty) list of watches created.
        """

    def createBugWatch(bug, owner, bugtracker, remotebug):
        """Create an IBugWatch.

        :bug: The IBug to which the watch is linked.
        :owner: The IPerson who created the IBugWatch.
        :bugtracker: The external IBugTracker.
        :remotebug: A string.
        """

    def extractBugTrackerAndBug(url):
        """Extract the bug tracker and the bug number for the given URL.

        A tuple in the form of (bugtracker, remotebug) is returned,
        where bugtracker is a registered IBugTracer, and remotebug is a
        text string.

        A NoBugTrackerFound exception is raised if the base URL can be
        extracted, but no such bug tracker is registered in Launchpad.

        If no bug tracker type can be guessed, None is returned.
        """


class NoBugTrackerFound(Exception):
    """No bug tracker with the base_url is registered in Launchpad."""

    def __init__(self, base_url, remote_bug, bugtracker_type):
        Exception.__init__(self, base_url, remote_bug, bugtracker_type)
        self.base_url = base_url
        self.remote_bug = remote_bug
        self.bugtracker_type = bugtracker_type


class UnrecognizedBugTrackerURL(Exception):
    """The given URL isn't used by any bug tracker we support."""
