# Copyright 2007 Canonical Ltd.  All rights reserved.

"""External bugtrackers."""

__metaclass__ = type

import cgi
import csv
import email
import os.path
import re
import socket
import sys
import urllib
import urllib2
import xml.parsers.expat

from email.Utils import parseaddr
from itertools import chain
from urlparse import urlunparse
from xml.dom import minidom

import ClientCookie

from BeautifulSoup import BeautifulSoup, Comment, SoupStrainer
from zope.component import getUtility
from zope.interface import implements

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical import encoding
from canonical.database.sqlbase import commit
from canonical.launchpad.scripts import log, debbugs
from canonical.launchpad.interfaces import (
    BugTaskImportance, BugTaskStatus, BugTrackerType, BugWatchErrorType,
    IBugWatchSet, IExternalBugTracker, IMessageSet, IPersonSet,
    PersonCreationRationale, ISupportsBugImport, ISupportsCommentImport,
    UNKNOWN_REMOTE_IMPORTANCE, UNKNOWN_REMOTE_STATUS)
from canonical.launchpad.webapp import errorlog
from canonical.launchpad.webapp.url import urlparse


# The user agent we send in our requests
LP_USER_AGENT = "Launchpad Bugscraper/0.2 (https://bugs.launchpad.net/)"


#
# Exceptions caught in scripts/checkwatches.py
#


class BugWatchUpdateError(Exception):
    """Base exception for when we fail to update watches for a tracker."""


class UnknownBugTrackerTypeError(BugWatchUpdateError):
    """Exception class to catch systems we don't have a class for yet."""

    def __init__(self, bugtrackertypename, bugtrackername):
        BugWatchUpdateError.__init__(self)
        self.bugtrackertypename = bugtrackertypename
        self.bugtrackername = bugtrackername

    def __str__(self):
        return self.bugtrackertypename


class UnsupportedBugTrackerVersion(BugWatchUpdateError):
    """The bug tracker version is not supported."""


class UnparseableBugTrackerVersion(BugWatchUpdateError):
    """The bug tracker version could not be parsed."""


class UnparseableBugData(BugWatchUpdateError):
    """The bug tracker provided bug data that could not be parsed."""


class BugTrackerConnectError(BugWatchUpdateError):
    """Exception class to catch misc errors contacting a bugtracker."""

    def __init__(self, url, error):
        BugWatchUpdateError.__init__(self)
        self.url = url
        self.error = str(error)

    def __str__(self):
        return "%s: %s" % (self.url, self.error)


#
# Exceptions caught locally
#


class BugWatchUpdateWarning(Exception):
    """An exception representing a warning.

    This is a flag exception for the benefit of the OOPS machinery.
    """


class InvalidBugId(BugWatchUpdateWarning):
    """The bug id wasn't in the format the bug tracker expected.

    For example, Bugzilla and debbugs expect the bug id to be an
    integer.
    """


class BugNotFound(BugWatchUpdateWarning):
    """The bug was not found in the external bug tracker."""


#
# OOPS reporting.
#


def report_oops(message=None, properties=None, info=None):
    """Record an oops for the current exception.

    This must only be called while handling an exception.

    :param message: custom explanatory error message. Do not use
        str(exception) to fill in this parameter, it should only be
        set when a human readable error has been explicitly generated.

    :param properties: Properties to record in the OOPS report.
    :type properties: An iterable of (name, value) tuples.

    :param info: Exception info.
    :type info: The return value of `sys.exc_info()`.
    """
    # Get the current exception info first of all.
    if info is None:
        info = sys.exc_info()

    # Collect properties to report.
    if properties is None:
        properties = []
    else:
        properties = list(properties)

    if message is not None:
        properties.append(('error-explanation', message))

    # Create the dummy request object.
    request = errorlog.ScriptRequest(properties)
    errorlog.globalErrorUtility.raising(info, request)

    return request


def report_warning(message, properties=None, info=None):
    """Create and report a warning as an OOPS.

    If no exception info is passed in this will create a generic
    `BugWatchUpdateWarning` to record. The reason is that the stack
    trace may be useful for later diagnosis.

    :param message: See `report_oops`.
    :param properties: See `report_oops`.
    :param info: See `report_oops`.
    """
    if info is None:
        # Raise and catch the exception so that sys.exc_info will
        # return our warning and stack trace.
        try:
            raise BugWatchUpdateWarning
        except BugWatchUpdateWarning:
            return report_oops(message, properties)
    else:
        return report_oops(message, properties, info)


_exception_to_bugwatcherrortype = [
   (BugTrackerConnectError, BugWatchErrorType.CONNECTION_ERROR),
   (UnparseableBugData, BugWatchErrorType.UNPARSABLE_BUG),
   (UnparseableBugTrackerVersion, BugWatchErrorType.UNPARSABLE_BUG_TRACKER),
   (UnsupportedBugTrackerVersion, BugWatchErrorType.UNSUPPORTED_BUG_TRACKER),
   (UnknownBugTrackerTypeError, BugWatchErrorType.UNSUPPORTED_BUG_TRACKER),
   (socket.timeout, BugWatchErrorType.TIMEOUT)]

def get_bugwatcherrortype_for_error(error):
    """Return the correct `BugWatchErrorType` for a given error."""
    for exc_type, bugwatcherrortype in _exception_to_bugwatcherrortype:
        if isinstance(error, exc_type):
            return bugwatcherrortype
    else:
        return BugWatchErrorType.UNKNOWN


class ExternalBugTracker:
    """Base class for an external bug tracker."""

    implements(IExternalBugTracker)
    batch_size = None
    batch_query_threshold = config.checkwatches.batch_query_threshold
    import_comments = config.checkwatches.import_comments

    def __init__(self, txn, bugtracker):
        self.bugtracker = bugtracker
        self.baseurl = bugtracker.baseurl.rstrip('/')
        self.txn = txn

    def urlopen(self, request, data=None):
        return urllib2.urlopen(request, data)

    def initializeRemoteBugDB(self, bug_ids):
        """Do any initialization before each bug watch is updated.

        It's optional to override this method.
        """
        self.bugs = {}
        if len(bug_ids) > self.batch_query_threshold:
            self.bugs = self.getRemoteBugBatch(bug_ids)
        else:
            # XXX: 2007-08-24 Graham Binns
            #      It might be better to do this synchronously for the sake of
            #      handling timeouts nicely. For now, though, we do it
            #      sequentially for the sake of easing complexity and making
            #      testing easier.
            for bug_id in bug_ids:
                bug_id, remote_bug = self.getRemoteBug(bug_id)

                if bug_id is not None:
                    self.bugs[bug_id] = remote_bug

    def getRemoteBug(self, bug_id):
        """Retrieve and return a single bug from the remote database.

        The bug is returned as a tuple in the form (id, bug). This ensures
        that bug ids are formatted correctly for the current
        ExternalBugTracker. If no data can be found for bug_id, (None,
        None) will be returned.

        A BugTrackerConnectError will be raised if anything goes wrong.
        """
        raise NotImplementedError(self.getRemoteBug)

    def getRemoteBugBatch(self, bug_ids):
        """Retrieve and return a set of bugs from the remote database.

        A BugTrackerConnectError will be raised if anything goes wrong.
        """
        raise NotImplementedError(self.getRemoteBugBatch)

    def getRemoteImportance(self, bug_id):
        """Return the remote importance for the given bug id.

        Raise BugNotFound if the bug can't be found.
        Raise InvalidBugId if the bug id has an unexpected format.
        Raise UnparseableBugData if the bug data cannot be parsed.
        """
        # This method should be overridden by subclasses, so we raise a
        # NotImplementedError if this version of it gets called for some
        # reason.
        raise NotImplementedError(self.getRemoteImportance)

    def getRemoteStatus(self, bug_id):
        """Return the remote status for the given bug id.

        Raise BugNotFound if the bug can't be found.
        Raise InvalidBugId if the bug id has an unexpected format.
        """
        raise NotImplementedError(self.getRemoteStatus)

    def _fetchPage(self, page):
        """Fetch a page from the remote server.

        A BugTrackerConnectError will be raised if anything goes wrong.
        """
        try:
            return self.urlopen(page)
        except (urllib2.HTTPError, urllib2.URLError), val:
            raise BugTrackerConnectError(self.baseurl, val)

    def _getPage(self, page):
        """GET the specified page on the remote HTTP server."""
        # For some reason, bugs.kde.org doesn't allow the regular urllib
        # user-agent string (Python-urllib/2.x) to access their
        # bugzilla, so we send our own instead.
        request = urllib2.Request("%s/%s" % (self.baseurl, page),
                                  headers={'User-agent': LP_USER_AGENT})
        return self._fetchPage(request).read()

    def _postPage(self, page, form):
        """POST to the specified page.

        :form: is a dict of form variables being POSTed.
        """
        url = "%s/%s" % (self.baseurl, page)
        post_data = urllib.urlencode(form)
        request = urllib2.Request(url, headers={'User-agent': LP_USER_AGENT})
        url = self.urlopen(request, data=post_data)
        page_contents = url.read()
        return page_contents

    def _getBugWatch(self, bug_watch_id):
        """Return the bug watch with id `bug_watch_id`."""
        return getUtility(IBugWatchSet).get(bug_watch_id)

    def _getBugWatchesByRemoteBug(self, bug_watch_ids):
        """Returns a dictionary of bug watches mapped to remote bugs.

        For each bug watch id fetches the corresponding bug watch and
        appends it to a list of bug watches pointing to one remote
        bug - the key of the returned mapping."""
        bug_watches_by_remote_bug = {}
        for bug_watch_id in bug_watch_ids:
            bug_watch = self._getBugWatch(bug_watch_id)
            remote_bug = bug_watch.remotebug
            # There can be multiple bug watches pointing to the same
            # remote bug; because of that, we need to store lists of bug
            # watches related to the remote bug, and later update the
            # status of each one of them.
            if remote_bug not in bug_watches_by_remote_bug:
                bug_watches_by_remote_bug[remote_bug] = []
            bug_watches_by_remote_bug[remote_bug].append(bug_watch)
        return bug_watches_by_remote_bug

    @property
    def _oops_properties(self):
        """Properties that are useful to record in an OOPS report.

        Return an iterable of 2-tuples (name, value).

        Subclasses should override this, but chain their properties
        after these, perhaps with the use of `itertools.chain`.
        """
        return [('batch_size', self.batch_size),
                ('batch_query_threshold', self.batch_query_threshold),
                ('import_comments', self.import_comments),
                ('externalbugtracker', self.__class__.__name__),
                ('baseurl', self.baseurl)]

    def info(self, message):
        """Record an informational message related to this bug tracker."""
        log.info(message)

    def warning(self, message, properties=None, info=None):
        """Record a warning related to this bug tracker."""
        if properties is None:
            properties = self._oops_properties
        else:
            properties = chain(properties, self._oops_properties)
        report_warning(message, properties, info)
        # Also put it in the log.
        log.warning(message)

    def error(self, message, properties=None, info=None):
        """Record an error related to this external bug tracker."""
        if properties is None:
            properties = self._oops_properties
        else:
            properties = chain(properties, self._oops_properties)
        report_oops(message, properties, info)
        # Also put it in the log.
        log.error(message, exc_info=info)

    def importBugComments(self, bug_watch):
        """See `ISupportsCommentImport`."""
        imported_comments = 0
        for comment_id in self.getCommentIds(bug_watch):
            displayname, email = self.getPosterForComment(
                bug_watch, comment_id)

            poster = getUtility(IPersonSet).ensurePerson(
                email, displayname, PersonCreationRationale.BUGIMPORT,
                comment='when importing comments for %s.' % bug_watch.title)

            comment_message = self.getMessageForComment(
                bug_watch, comment_id, poster)
            if not bug_watch.hasComment(comment_id):
                bug_watch.addComment(comment_id, comment_message)
                imported_comments += 1

        if imported_comments > 0:
            self.info("Imported %(count)i comments for remote bug "
                "%(remotebug)s on %(bugtracker_url)s into Launchpad bug "
                "%(bug_id)s." %
                {'count': imported_comments,
                 'remotebug': bug_watch.remotebug,
                 'bugtracker_url': self.baseurl,
                 'bug_id': bug_watch.bug.id})


#
# Bugzilla
#

class Bugzilla(ExternalBugTracker):
    """An ExternalBugTrack for dealing with remote Bugzilla systems."""

    implements(IExternalBugTracker)
    batch_query_threshold = 0 # Always use the batch method.

    def __init__(self, txn, bugtracker, version=None):
        super(Bugzilla, self).__init__(txn, bugtracker)
        self.version = self._parseVersion(version)
        self.is_issuezilla = False
        self.remote_bug_status = {}

    def _parseDOMString(self, contents):
        """Return a minidom instance representing the XML contents supplied"""
        # Some Bugzilla sites will return pages with content that has
        # broken encoding. It's unfortunate but we need to guess the
        # encoding that page is in, and then encode() it into the utf-8
        # that minidom requires.
        contents = encoding.guess(contents).encode("utf-8")
        return minidom.parseString(contents)

    def _probe_version(self):
        """Retrieve and return a remote bugzilla version.

        If the version cannot be parsed from the remote server
        `UnparseableBugTrackerVersion` will be raised. If the remote
        server cannot be reached `BugTrackerConnectError` will be
        raised.
        """
        version_xml = self._getPage('xml.cgi?id=1')
        try:
            document = self._parseDOMString(version_xml)
        except xml.parsers.expat.ExpatError, e:
            raise BugTrackerConnectError(self.baseurl,
                "Failed to parse output when probing for version: %s" % e)
        bugzilla = document.getElementsByTagName("bugzilla")
        if not bugzilla:
            # Welcome to Disneyland. The Issuezilla tracker replaces
            # "bugzilla" with "issuezilla".
            bugzilla = document.getElementsByTagName("issuezilla")
            if bugzilla:
                self.is_issuezilla = True
            else:
                raise UnparseableBugTrackerVersion(
                    'Failed to parse version from xml.cgi for %s: could '
                    'not find top-level bugzilla element'
                    % self.baseurl)
        version = bugzilla[0].getAttribute("version")
        return self._parseVersion(version)

    def _parseVersion(self, version):
        """Return a Bugzilla version parsed into a tuple.

        A typical tuple will be in the form (major_version,
        minor_version), so the version string '2.15' would be returned
        as (2, 15).

        If the passed version is None, None will be returned.
        If the version cannot be parsed `UnparseableBugTrackerVersion`
        will be raised.
        """
        if version is None:
            return None

        try:
            # Get rid of trailing -rh, -debian, etc.
            version = version.split("-")[0]
            # Ignore plusses in the version.
            version = version.replace("+", "")
            # We need to convert the version to a tuple of integers if
            # we are to compare it correctly.
            version = tuple(int(x) for x in version.split("."))
        except ValueError:
            raise UnparseableBugTrackerVersion(
                'Failed to parse version %r for %s' %
                (version, self.baseurl))

        return version

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, remote_status):
        """See `IExternalBugTracker`.

        Bugzilla status consist of two parts separated by space, where
        the last part is the resolution. The resolution is optional.
        """
        if not remote_status or remote_status == UNKNOWN_REMOTE_STATUS:
            return BugTaskStatus.UNKNOWN
        if ' ' in remote_status:
            remote_status, resolution = remote_status.split(' ', 1)
        else:
            resolution = ''

        if remote_status in ['ASSIGNED', 'ON_DEV', 'FAILS_QA', 'STARTED']:
            # FAILS_QA, ON_DEV: bugzilla.redhat.com
            # STARTED: OOO Issuezilla
            malone_status = BugTaskStatus.INPROGRESS
        elif remote_status in ['NEEDINFO', 'NEEDINFO_REPORTER',
                               'WAITING', 'SUSPENDED']:
            # NEEDINFO_REPORTER: bugzilla.redhat.com
            # SUSPENDED, WAITING: http://gcc.gnu.org/bugzilla
            #   though SUSPENDED applies to something pending discussion
            #   in a larger/separate context.
            malone_status = BugTaskStatus.INCOMPLETE
        elif (remote_status in
            ['PENDINGUPLOAD', 'MODIFIED', 'RELEASE_PENDING', 'ON_QA']):
            # RELEASE_PENDING, MODIFIED, ON_QA: bugzilla.redhat.com
            malone_status = BugTaskStatus.FIXCOMMITTED
        elif remote_status in ['REJECTED']:
            # REJECTED: bugzilla.kernel.org
            malone_status = BugTaskStatus.INVALID
        elif remote_status in ['RESOLVED', 'VERIFIED', 'CLOSED']:
            # depends on the resolution:
            if resolution in ['CODE_FIX', 'CURRENTRELEASE', 'ERRATA',
                              'FIXED', 'NEXTRELEASE',
                              'PATCH_ALREADY_AVAILABLE', 'RAWHIDE']:

                # The following resolutions come from bugzilla.redhat.com.
                # All of them map to Malone's FIXRELEASED status:
                #     CODE_FIX, CURRENTRELEASE, ERRATA, NEXTRELEASE,
                #     PATCH_ALREADY_AVAILABLE, RAWHIDE
                malone_status = BugTaskStatus.FIXRELEASED
            elif resolution == 'WONTFIX':
                # VERIFIED WONTFIX maps directly to WONTFIX
                malone_status = BugTaskStatus.WONTFIX
            else:
                #XXX: Bjorn Tillenius 2005-02-03 Bug=31745:
                #     Which are the valid resolutions? We should fail
                #     if we don't know of the resolution.
                malone_status = BugTaskStatus.INVALID
        elif remote_status in ['REOPENED', 'NEW', 'UPSTREAM', 'DEFERRED']:
            # DEFERRED: bugzilla.redhat.com
            malone_status = BugTaskStatus.CONFIRMED
        elif remote_status in ['UNCONFIRMED']:
            malone_status = BugTaskStatus.NEW
        else:
            self.warning(
                "Unknown Bugzilla status '%s' at %s." % (
                    remote_status, self.baseurl))
            malone_status = BugTaskStatus.UNKNOWN

        return malone_status

    def initializeRemoteBugDB(self, bug_ids):
        """See `ExternalBugTracker`.

        This method is overriden so that Bugzilla version issues can be
        accounted for.
        """
        if self.version is None:
            self.version = self._probe_version()

        super(Bugzilla, self).initializeRemoteBugDB(bug_ids)

    def getRemoteBug(self, bug_id):
        """See `ExternalBugTracker`."""
        return (bug_id, self.getRemoteBugBatch([bug_id]))

    def getRemoteBugBatch(self, bug_ids):
        """See `ExternalBugTracker`."""
        # XXX: GavinPanella 2007-10-25 bug=153532: The modification of
        # self.remote_bug_status later on is a side-effect that should
        # really not be in this method, but for the fact that
        # getRemoteStatus needs it at other times. Perhaps
        # getRemoteBug and getRemoteBugBatch could return RemoteBug
        # objects which have status properties that would replace
        # getRemoteStatus.
        if self.is_issuezilla:
            buglist_page = 'xml.cgi'
            data = {'download_type' : 'browser',
                    'output_configured' : 'true',
                    'include_attachments' : 'false',
                    'include_dtd' : 'true',
                    'id'      : ','.join(bug_ids),
                    }
            bug_tag = 'issue'
            id_tag = 'issue_id'
            status_tag = 'issue_status'
            resolution_tag = 'resolution'
        elif self.version < (2, 16):
            buglist_page = 'xml.cgi'
            data = {'id': ','.join(bug_ids)}
            bug_tag = 'bug'
            id_tag = 'bug_id'
            status_tag = 'bug_status'
            resolution_tag = 'resolution'
        else:
            buglist_page = 'buglist.cgi'
            data = {'form_name'   : 'buglist.cgi',
                    'bug_id_type' : 'include',
                    'bug_id'      : ','.join(bug_ids),
                    }
            if self.version < (2, 17, 1):
                data.update({'format' : 'rdf'})
            else:
                data.update({'ctype'  : 'rdf'})
            bug_tag = 'bz:bug'
            id_tag = 'bz:id'
            status_tag = 'bz:bug_status'
            resolution_tag = 'bz:resolution'

        buglist_xml = self._postPage(buglist_page, data)
        try:
            document = self._parseDOMString(buglist_xml)
        except xml.parsers.expat.ExpatError, e:
            raise UnparseableBugData('Failed to parse XML description for '
                '%s bugs %s: %s' % (self.baseurl, bug_ids, e))

        bug_nodes = document.getElementsByTagName(bug_tag)
        for bug_node in bug_nodes:
            # We use manual iteration to pick up id_tags instead of
            # getElementsByTagName because the latter does a recursive
            # search, and in some documents we've found the id_tag to
            # appear under other elements (such as "has_duplicates") in
            # the document hierarchy.
            bug_id_nodes = [node for node in bug_node.childNodes if
                            node.nodeName == id_tag]
            if not bug_id_nodes:
                # Something in the output is really weird; this will
                # show up as a bug not found, but we can catch that
                # later in the error logs.
                continue
            bug_id_node = bug_id_nodes[0]
            assert len(bug_id_node.childNodes) == 1, (
                "id node should contain a non-empty text string.")
            bug_id = str(bug_id_node.childNodes[0].data)
            # This assertion comes in late so we can at least tell what
            # bug caused this crash.
            assert len(bug_id_nodes) == 1, ("Should be only one id node, "
                "but %s had %s." % (bug_id, len(bug_id_nodes)))

            status_nodes = bug_node.getElementsByTagName(status_tag)
            if not status_nodes:
                # Older versions of bugzilla used bz:status; this was
                # later changed to bz:bug_status. For robustness, and
                # because there is practically no risk of reading wrong
                # data here, just try the older format as well.
                status_nodes = bug_node.getElementsByTagName("bz:status")
            assert len(status_nodes) == 1, ("Couldn't find a status "
                                            "node for bug %s." % bug_id)
            bug_status_node = status_nodes[0]
            assert len(bug_status_node.childNodes) == 1, (
                "status node for bug %s should contain a non-empty "
                "text string." % bug_id)
            status = bug_status_node.childNodes[0].data

            resolution_nodes = bug_node.getElementsByTagName(resolution_tag)
            assert len(resolution_nodes) <= 1, (
                "Should be only one resolution node for bug %s." % bug_id)
            if resolution_nodes:
                assert len(resolution_nodes[0].childNodes) <= 1, (
                    "Resolution for bug %s should just contain "
                    "a string." % bug_id)
                if resolution_nodes[0].childNodes:
                    resolution = resolution_nodes[0].childNodes[0].data
                    status += ' %s' % resolution
            self.remote_bug_status[bug_id] = status

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        """See ExternalBugTracker."""
        if not bug_id.isdigit():
            raise InvalidBugId(
                "Bugzilla (%s) bug number not an integer: %s" % (
                    self.baseurl, bug_id))
        try:
            return self.remote_bug_status[bug_id]
        except KeyError:
            raise BugNotFound(bug_id)

#
# Debbugs
#

debbugsstatusmap = {'open':      BugTaskStatus.NEW,
                    'forwarded': BugTaskStatus.CONFIRMED,
                    'done':      BugTaskStatus.FIXRELEASED}


class DebBugsDatabaseNotFound(BugTrackerConnectError):
    """The Debian bug database was not found."""


class DebBugs(ExternalBugTracker):
    """A class that deals with communications with a debbugs db."""

    implements(ISupportsBugImport, ISupportsCommentImport)

    # We don't support different versions of debbugs.
    version = None
    debbugs_pl = os.path.join(
        os.path.dirname(debbugs.__file__), 'debbugs-log.pl')

    def __init__(self, txn, bugtracker, db_location=None):
        super(DebBugs, self).__init__(txn, bugtracker)
        if db_location is None:
            self.db_location = config.malone.debbugs_db_location
        else:
            self.db_location = db_location

        if not os.path.exists(os.path.join(self.db_location, 'db-h')):
            raise DebBugsDatabaseNotFound(
                self.db_location, '"db-h" not found.')

        # The debbugs database is split in two parts: a current
        # database, which is kept under the 'db-h' directory, and
        # the archived database, which is kept under 'archive'. The
        # archived database is used as a fallback, as you can see in
        # getRemoteStatus
        self.debbugs_db = debbugs.Database(
            self.db_location, self.debbugs_pl)
        if os.path.exists(os.path.join(self.db_location, 'archive')):
            self.debbugs_db_archive = debbugs.Database(
                self.db_location, self.debbugs_pl, subdir="archive")

    def initializeRemoteBugDB(self, bug_ids):
        """See `ExternalBugTracker`.

        This method is overridden (and left empty) here to avoid breakage when
        the continuous bug-watch checking spec is implemented.
        """

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, remote_status):
        """Convert a debbugs status to a Malone status.

        A debbugs status consists of either two or three parts,
        separated with space; the status and severity, followed by
        optional tags. The tags are also separated with a space
        character.
        """
        if not remote_status or remote_status == UNKNOWN_REMOTE_STATUS:
            return BugTaskStatus.UNKNOWN
        parts = remote_status.split(' ')
        if len(parts) < 2:
            self.warning('Malformed debbugs status: %r.' % remote_status)
            return BugTaskStatus.UNKNOWN
        status = parts[0]
        severity = parts[1]
        tags = parts[2:]

        # For the moment we convert only the status, not the severity.
        try:
            malone_status = debbugsstatusmap[status]
        except KeyError:
            self.warning('Unknown debbugs status "%s".' % status)
            malone_status = BugTaskStatus.UNKNOWN
        if status == 'open':
            confirmed_tags = [
                'help', 'confirmed', 'upstream', 'fixed-upstream']
            fix_committed_tags = ['pending', 'fixed', 'fixed-in-experimental']
            if 'moreinfo' in tags:
                malone_status = BugTaskStatus.INCOMPLETE
            for confirmed_tag in confirmed_tags:
                if confirmed_tag in tags:
                    malone_status = BugTaskStatus.CONFIRMED
                    break
            for fix_committed_tag in fix_committed_tags:
                if fix_committed_tag in tags:
                    malone_status = BugTaskStatus.FIXCOMMITTED
                    break
            if 'wontfix' in tags:
                malone_status = BugTaskStatus.WONTFIX

        return malone_status

    def _findBug(self, bug_id):
        if not bug_id.isdigit():
            raise InvalidBugId(
                "Debbugs bug number not an integer: %s" % bug_id)
        try:
            debian_bug = self.debbugs_db[int(bug_id)]
        except KeyError:
            # If we couldn't find it in the main database, there's
            # always the archive.
            try:
                debian_bug = self.debbugs_db_archive[int(bug_id)]
            except KeyError:
                raise BugNotFound(bug_id)

        return debian_bug

    def _loadLog(self, debian_bug):
        """Load the debbugs comment log for a given bug.

        This method is analogous to _findBug() in that if the comment
        log cannot be loaded from the main database it will attempt to
        load the log from the archive database.

        If no comment log can be found, a debbugs.LogParseFailed error
        will be raised.
        """
        # If we can't find the log in the main database we try the
        # archive.
        try:
            self.debbugs_db.load_log(debian_bug)
        except debbugs.LogParseFailed:
            # If there is no log for this bug in the archive a
            # LogParseFailed error will be raised. However, we let that
            # propagate upwards since we need to make the callsite deal
            # with the fact that there's no log to parse.
            self.debbugs_db_archive.load_log(debian_bug)

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        """See ExternalBugTracker."""
        debian_bug = self._findBug(bug_id)
        if not debian_bug.severity:
            # 'normal' is the default severity in debbugs.
            severity = 'normal'
        else:
            severity = debian_bug.severity
        new_remote_status = ' '.join(
            [debian_bug.status, severity] + debian_bug.tags)
        return new_remote_status

    def getReporter(self, remote_bug):
        """See ISupportsBugImport."""
        debian_bug = self._findBug(remote_bug)
        reporter_name, reporter_email = parseaddr(debian_bug.originator)
        return reporter_name, reporter_email

    def getTarget(self, remote_bug):
        """See ISupportsBugImport."""
        debian_bug = self._findBug(remote_bug)
        return debian_bug.package

    def getSummaryAndDescription(self, remote_bug):
        """See ISupportsBugImport."""
        debian_bug = self._findBug(remote_bug)
        return debian_bug.subject, debian_bug.description

    def getCommentIds(self, bug_watch):
        """Return all the comment IDs for a given remote bug."""
        debian_bug = self._findBug(bug_watch.remotebug)
        self._loadLog(debian_bug)

        comment_ids = []
        for comment in debian_bug.comments:
            parsed_comment = email.message_from_string(comment)
            comment_ids.append(parsed_comment['message-id'])

        return comment_ids

    def getPosterForComment(self, bug_watch, comment_id):
        """Return a tuple of (name, emailaddress) for a comment's poster."""
        debian_bug = self._findBug(bug_watch.remotebug)
        self._loadLog(debian_bug)

        for comment in debian_bug.comments:
            parsed_comment = email.message_from_string(comment)
            if parsed_comment['message-id'] == comment_id:
                return parseaddr(parsed_comment['from'])

    def getMessageForComment(self, bug_watch, comment_id, poster):
        """Return a Message object for a comment."""
        debian_bug = self._findBug(bug_watch.remotebug)
        self._loadLog(debian_bug)

        for comment in debian_bug.comments:
            parsed_comment = email.message_from_string(comment)
            if parsed_comment['message-id'] == comment_id:
                message = getUtility(IMessageSet).fromEmail(comment, poster,
                    parsed_message=parsed_comment)

                commit()
                return message

#
# Mantis
#

class MantisLoginHandler(ClientCookie.HTTPRedirectHandler):
    """Handler for ClientCookie.build_opener to automatically log-in
    to Mantis anonymously if needed.

    The ALSA bug tracker is the only tested Mantis installation that
    actually needs this. For ALSA bugs, the dance is like so:

      1. We request bug 3301 ('jack sensing problem'):
           https://bugtrack.alsa-project.org/alsa-bug/view.php?id=3301

      2. Mantis redirects us to:
           .../alsa-bug/login_page.php?return=%2Falsa-bug%2Fview.php%3Fid%3D3301

      3. We notice this, rewrite the query, and skip to login.php:
           .../alsa-bug/login.php?return=%2Falsa-bug%2Fview.php%3Fid%3D3301&username=guest&password=guest

      4. Mantis accepts our credentials then redirects us to the bug
         view page via a cookie test page (login_cookie_test.php)
    """

    def rewrite_url(self, url):
        scheme, host, path, params, query, fragment = urlparse(url)

        # If we can, skip the login page and submit credentials
        # directly. The query should contain a 'return' parameter
        # which, if our credentials are accepted, means we'll be
        # redirected back from whence we came. In other words, we'll
        # end up back at the bug page we first requested.
        login_page = '/login_page.php'
        if path.endswith(login_page):
            path = path[:-len(login_page)] + '/login.php'
            query = cgi.parse_qs(query, True)
            query['username'] = query['password'] = ['guest']
            if 'return' not in query:
                message = (
                    "Mantis redirected us to the login page "
                    "but did not set a return path.")
                report_warning(message)
                log.warning(message)
            query = urllib.urlencode(query, True)
            url = urlunparse(
                (scheme, host, path, params, query, fragment))

        # XXX: Previous versions of the Mantis external bug tracker
        # fetched login_anon.php in addition to the login.php method
        # above, but none of the Mantis installations tested actually
        # needed this. For example, the ALSA bugtracker actually
        # issues an error "Your account may be disabled" when
        # accessing this page. For now it's better to *not* try this
        # page because we may end up annoying admins with spurious
        # login attempts. -- Gavin Panella, 2007-08-28.

        return url

    def redirect_request(self, newurl, req, fp, code, msg, headers):
        # XXX: Gavin Panella 2007-08-27: The argument order here is
        # different from that in urllib2.HTTPRedirectHandler.
        # ClientCookie is meant to mimic urllib2 (and does subclass
        # it), so this is probably a bug.

        return ClientCookie.HTTPRedirectHandler.redirect_request(
            self, self.rewrite_url(newurl), req, fp, code, msg, headers)


class Mantis(ExternalBugTracker):
    """An `ExternalBugTracker` for dealing with Mantis instances.

    For a list of tested Mantis instances and their behaviour when
    exported from, see http://launchpad.canonical.com/MantisBugtrackers.
    """

    # Custom opener that automatically sends anonymous credentials to
    # Mantis if (and only if) needed.
    _opener = ClientCookie.build_opener(MantisLoginHandler)

    def urlopen(self, request, data=None):
        # We use ClientCookie to make following cookies transparent.
        # This is required for certain bugtrackers that require
        # cookies that actually do anything (as is the case with
        # Mantis). It's basically a drop-in replacement for
        # urllib2.urlopen() that tracks cookies. We also have a
        # customised ClientCookie opener to handle transparent
        # authentication.
        return self._opener.open(request, data)

    @cachedproperty
    def csv_data(self):
        """Attempt to retrieve a CSV export from the remote server.

        If the export fails (i.e. the response is 0-length), None will
        be returned.
        """
        # Next step is getting our query filter cookie set up; we need
        # to do this weird submit in order to get the closed bugs
        # included in the results; the default Mantis filter excludes
        # them. It's unlikely that all these parameters are actually
        # necessary, but it's easy to prepare the complete set from a
        # view_all_bugs.php form dump so let's keep it complete.
        data = {
           'type': '1',
           'page_number': '1',
           'view_type': 'simple',
           'reporter_id[]': '0',
           'user_monitor[]': '0',
           'handler_id[]': '0',
           'show_category[]': '0',
           'show_severity[]': '0',
           'show_resolution[]': '0',
           'show_profile[]': '0',
           'show_status[]': '0',
           # Some of the more modern Mantis trackers use
           # a value of 'hide_status[]': '-2' here but it appears that
           # [none] works. Oops, older Mantis uses 'none' here. Gross!
           'hide_status[]': '[none]',
           'show_build[]': '0',
           'show_version[]': '0',
           'fixed_in_version[]': '0',
           'show_priority[]': '0',
           'per_page': '50',
           'view_state': '0',
           'sticky_issues': 'on',
           'highlight_changed': '6',
           'relationship_type': '-1',
           'relationship_bug': '0',
           # Hack around the fact that the sorting parameter has
           # changed over time.
           'sort': 'last_updated',
           'sort_0': 'last_updated',
           'dir': 'DESC',
           'dir_0': 'DESC',
           'search': '',
           'filter': 'Apply Filter',
        }
        self.page = self._postPage("view_all_set.php?f=3", data)

        # Finally grab the full CSV export, which uses the
        # MANTIS_VIEW_ALL_COOKIE set in the previous step to specify
        # what's being viewed.
        csv_data = self._getPage("csv_export.php")

        if not csv_data:
            return None
        else:
            return csv_data

    def canUseCSVExports(self):
        """Return True if a Mantis instance supports CSV exports.

        If the Mantis instance cannot or does not support CSV exports,
        False will be returned.
        """
        return self.csv_data is not None

    def initializeRemoteBugDB(self, bug_ids):
        """See `ExternalBugTracker`.

        This method is overridden so that it can take into account the
        fact that not all Mantis instances support CSV exports. In
        those cases all bugs will be imported individually, regardless
        of how many there are.
        """
        self.bugs = {}

        if (len(bug_ids) > self.batch_query_threshold and
            self.canUseCSVExports()):
            # We only query for batches of bugs if the remote Mantis
            # instance supports CSV exports, otherwise we default to
            # screen-scraping on a per bug basis regardless of how many bugs
            # there are to retrieve.
            self.bugs = self.getRemoteBugBatch(bug_ids)
        else:
            for bug_id in bug_ids:
                bug_id, remote_bug = self.getRemoteBug(bug_id)

                if bug_id is not None:
                    self.bugs[bug_id] = remote_bug

    def getRemoteBug(self, bug_id):
        """See `ExternalBugTracker`."""
        # Only parse tables to save time and memory. If we didn't have
        # to check for application errors in the page (using
        # _checkForApplicationError) then we could be much more
        # specific than this.
        bug_page = BeautifulSoup(
            self._getPage('view.php?id=%s' % bug_id),
            convertEntities=BeautifulSoup.HTML_ENTITIES,
            parseOnlyThese=SoupStrainer('table'))

        app_error = self._checkForApplicationError(bug_page)
        if app_error:
            app_error_code, app_error_message = app_error
            # 1100 is ERROR_BUG_NOT_FOUND in Mantis (see
            # mantisbt/core/constant_inc.php).
            if app_error_code == '1100':
                return None, None
            else:
                raise BugWatchUpdateError(
                    "Mantis APPLICATION ERROR #%s: %s" % (
                    app_error_code, app_error_message))

        bug = {
            'id': bug_id,
            'status': self._findValueRightOfKey(bug_page, 'Status'),
            'resolution': self._findValueRightOfKey(bug_page, 'Resolution')}

        return int(bug_id), bug

    def getRemoteBugBatch(self, bug_ids):
        """See `ExternalBugTracker`."""
        # You may find this zero in "\r\n0" funny. Well I don't. This is
        # to work around the fact that Mantis' CSV export doesn't cope
        # with the fact that the bug summary can contain embedded "\r\n"
        # characters! I don't see a better way to handle this short of
        # not using the CSV module and forcing all lines to have the
        # same number as fields as the header.
        # XXX: kiko 2007-07-05: Report Mantis bug.
        # XXX: allenap 2007-09-06: Reported in LP as bug #137780.
        csv_data = self.csv_data.strip().split("\r\n0")

        if not csv_data:
            raise UnparseableBugData("Empty CSV for %s" % self.baseurl)

        # Clean out stray, unquoted newlines inside csv_data to avoid
        # the CSV module blowing up.
        csv_data = [s.replace("\r", "") for s in csv_data]
        csv_data = [s.replace("\n", "") for s in csv_data]

        # The first line of the CSV file is the header. We need to read
        # it because different Mantis instances have different header
        # ordering and even different columns in the export.
        self.headers = [h.lower() for h in csv_data.pop(0).split(",")]
        if len(self.headers) < 2:
            raise UnparseableBugData("CSV header mangled: %r" % self.headers)

        if not csv_data:
            # A file with a header and no bugs is also useless.
            raise UnparseableBugData("CSV for %s contained no bugs!"
                                     % self.baseurl)

        try:
            bugs = {}
            # Using the CSV reader is pretty much essential since the
            # data that comes back can include title text which can in
            # turn contain field separators -- you don't want to handle
            # the unquoting yourself.
            for bug_line in csv.reader(csv_data):
                bug = self._processCSVBugLine(bug_line)
                bugs[int(bug['id'])] = bug

            return bugs

        except csv.Error, error:
            raise UnparseableBugData(
                "Exception parsing CSV file: %s." % error)

    def _processCSVBugLine(self, bug_line):
        """Processes a single line of the CSV.

        Adds the bug it represents to self.bugs.
        """
        required_fields = ['id', 'status', 'resolution']
        bug = {}
        for header in self.headers:
            try:
                data = bug_line.pop(0)
            except IndexError:
                self.warning("Line '%r' incomplete." % bug_line)
                return
            bug[header] = data
        for field in required_fields:
            if field not in bug:
                self.warning("Bug %s lacked field '%r'." % (bug['id'], field))
                return
            try:
                # See __init__ for an explanation of why we use integer
                # IDs in the internal data structure.
                bug_id = int(bug['id'])
            except ValueError:
                self.warning("Encountered invalid bug ID: %r." % bug['id'])
                return

        return bug

    def _checkForApplicationError(self, page_soup):
        """If Mantis does not find the bug it still returns a 200 OK
        response, so we need to look into the page to figure it out.

        If there is no error, None is returned.

        If there is an error, a 2-tuple of (code, message) is
        returned, both unicode strings.
        """
        app_error = page_soup.find(
            text=lambda node: (node.startswith('APPLICATION ERROR ')
                               and node.parent['class'] == 'form-title'
                               and not isinstance(node, Comment)))
        if app_error:
            app_error_code = ''.join(c for c in app_error if c.isdigit())
            app_error_message = app_error.findNext('p')
            if app_error_message is not None:
                app_error_message = app_error_message.string
            return app_error_code, app_error_message

        return None

    def _findValueRightOfKey(self, page_soup, key):
        """Scrape a value from a Mantis bug view page where the value
        is displayed to the right of the key.

        The Mantis bug view page uses HTML tables for both layout and
        representing tabular data, often within the same table. This
        method assumes that the key and value are on the same row,
        adjacent to one another, with the key preceeding the value:

        ...
        <td>Key</td>
        <td>Value</td>
        ...

        This method does not compensate for colspan or rowspan.
        """
        key_node = page_soup.find(
            text=lambda node: (node.strip() == key
                               and not isinstance(node, Comment)))
        if key_node is None:
            raise UnparseableBugData(
                "Key %r not found." % (key,))

        value_cell = key_node.findNext('td')
        if value_cell is None:
            raise UnparseableBugData(
                "Value cell for key %r not found." % (key,))

        value_node = value_cell.string
        if value_node is None:
            raise UnparseableBugData(
                "Value for key %r not found." % (key,))

        return value_node.strip()

    def _findValueBelowKey(self, page_soup, key):
        """Scrape a value from a Mantis bug view page where the value
        is displayed directly below the key.

        The Mantis bug view page uses HTML tables for both layout and
        representing tabular data, often within the same table. This
        method assumes that the key and value are within the same
        column on adjacent rows, with the key preceeding the value:

        ...
        <tr>...<td>Key</td>...</tr>
        <tr>...<td>Value</td>...</tr>
        ...

        This method does not compensate for colspan or rowspan.
        """
        key_node = page_soup.find(
            text=lambda node: (node.strip() == key
                               and not isinstance(node, Comment)))
        if key_node is None:
            raise UnparseableBugData(
                "Key %r not found." % (key,))

        key_cell = key_node.parent
        if key_cell is None:
            raise UnparseableBugData(
                "Cell for key %r not found." % (key,))

        key_row = key_cell.parent
        if key_row is None:
            raise UnparseableBugData(
                "Row for key %r not found." % (key,))

        try:
            key_pos = key_row.findAll('td').index(key_cell)
        except ValueError:
            raise UnparseableBugData(
                "Key cell in row for key %r not found." % (key,))

        value_row = key_row.findNextSibling('tr')
        if value_row is None:
            raise UnparseableBugData(
                "Value row for key %r not found." % (key,))

        value_cell = value_row.findAll('td')[key_pos]
        if value_cell is None:
            raise UnparseableBugData(
                "Value cell for key %r not found." % (key,))

        value_node = value_cell.string
        if value_node is None:
            raise UnparseableBugData(
                "Value for key %r not found." % (key,))

        return value_node.strip()

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        if not bug_id.isdigit():
            raise InvalidBugId(
                "Mantis (%s) bug number not an integer: %s" % (
                    self.baseurl, bug_id))

        try:
            bug = self.bugs[int(bug_id)]
        except KeyError:
            raise BugNotFound(bug_id)

        # Use a colon and a space to join status and resolution because
        # there is a chance that statuses contain spaces, and because
        # it makes display of the data nicer.
        return "%(status)s: %(resolution)s" % bug

    def _getStatusFromCSV(self, bug_id):
        try:
            bug = self.bugs[int(bug_id)]
        except KeyError:
            raise BugNotFound(bug_id)
        else:
            return bug['status'], bug['resolution']

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, status_and_resolution):
        if (not status_and_resolution or
            status_and_resolution == UNKNOWN_REMOTE_STATUS):
            return BugTaskStatus.UNKNOWN

        remote_status, remote_resolution = status_and_resolution.split(
            ": ", 1)

        if remote_status == 'assigned':
            return BugTaskStatus.INPROGRESS
        if remote_status == 'feedback':
            return BugTaskStatus.INCOMPLETE
        if remote_status in ['new']:
            return BugTaskStatus.NEW
        if remote_status in ['confirmed', 'acknowledged']:
            return BugTaskStatus.CONFIRMED
        if remote_status in ['resolved', 'closed']:
            if remote_resolution == 'fixed':
                return BugTaskStatus.FIXRELEASED
            if remote_resolution == 'reopened':
                return BugTaskStatus.NEW
            if remote_resolution in ["unable to reproduce", "not fixable",
                                     'suspended']:
                return BugTaskStatus.INVALID
            if remote_resolution == "won't fix":
                return BugTaskStatus.WONTFIX
            if remote_resolution == 'duplicate':
                # XXX: kiko 2007-07-05: Follow duplicates
                return BugTaskStatus.INVALID
            if remote_resolution in ['open', 'no change required']:
                # XXX: kiko 2007-07-05: Pretty inconsistently used
                return BugTaskStatus.FIXRELEASED

        self.warning("Unknown status/resolution %s/%s." %
                     (remote_status, remote_resolution))
        return BugTaskStatus.UNKNOWN


class Trac(ExternalBugTracker):
    """An ExternalBugTracker instance for handling Trac bugtrackers."""

    ticket_url = 'ticket/%i?format=csv'
    batch_url = 'query?%s&order=resolution&format=csv'

    def __init__(self, txn, bugtracker):
        super(Trac, self).__init__(txn, bugtracker)
        self.batch_query_threshold = 10

    def supportsSingleExports(self, bug_ids):
        """Return True if the Trac instance provides CSV exports for single
        tickets, False otherwise.

        :bug_ids: A list of bug IDs that we can use for discovery purposes.
        """
        valid_ticket = False
        html_ticket_url = '%s/%s' % (
            self.baseurl, self.ticket_url.replace('?format=csv', ''))

        bug_ids = list(bug_ids)
        while not valid_ticket and len(bug_ids) > 0:
            try:
                # We try to retrive the ticket in HTML form, since that will
                # tell us whether or not it is actually a valid ticket
                ticket_id = int(bug_ids.pop())
                html_data = self.urlopen(html_ticket_url % ticket_id)
            except (ValueError, urllib2.HTTPError):
                # If we get an HTTP error we can consider the ticket to be
                # invalid. If we get a ValueError then the ticket_id couldn't
                # be intified and it's of no use to us anyway.
                pass
            else:
                # If we didn't get an error we can try to get the ticket in
                # CSV form. If this fails then we can consider single ticket
                # exports to be unsupported.
                try:
                    csv_data = self.urlopen(
                        "%s/%s" % (self.baseurl, self.ticket_url % ticket_id))
                    return csv_data.headers.subtype == 'csv'
                except (urllib2.HTTPError, urllib2.URLError):
                    return False
        else:
            # If we reach this point then we likely haven't had any valid
            # tickets or something else is wrong. Either way, we can only
            # assume that CSV exports of single tickets aren't supported.
            return False

    def getRemoteBug(self, bug_id):
        """See `ExternalBugTracker`."""
        bug_id = int(bug_id)
        query_url = "%s/%s" % (self.baseurl, self.ticket_url % bug_id)
        reader = csv.DictReader(self._fetchPage(query_url))
        return (bug_id, reader.next())

    def getRemoteBugBatch(self, bug_ids):
        """See `ExternalBugTracker`."""
        id_string = '&'.join(['id=%s' % id for id in bug_ids])
        query_url = "%s/%s" % (self.baseurl, self.batch_url % id_string)
        remote_bugs = csv.DictReader(self._fetchPage(query_url))

        bugs = {}
        for remote_bug in remote_bugs:
            # We're only interested in the bug if it's one of the ones in
            # bug_ids, just in case we get all the tickets in the Trac
            # instance back instead of only the ones we want.
            if remote_bug['id'] not in bug_ids:
                continue

            bugs[int(remote_bug['id'])] = remote_bug

        return bugs

    def initializeRemoteBugDB(self, bug_ids):
        """See `ExternalBugTracker`.

        This method overrides ExternalBugTracker.initializeRemoteBugDB()
        so that the remote Trac instance's support for single ticket
        exports can be taken into account.

        If the URL specified for the bugtracker is not valid a
        BugTrackerConnectError will be raised.
        """
        self.bugs = {}
        # When there are less than batch_query_threshold bugs to update
        # we make one request per bug id to the remote bug tracker,
        # providing it supports CSV exports per-ticket. If the Trac
        # instance doesn't support exports-per-ticket we fail over to
        # using the batch export method for retrieving bug statuses.
        if (len(bug_ids) < self.batch_query_threshold and
            self.supportsSingleExports(bug_ids)):
            for bug_id in bug_ids:
                # If we can't get the remote bug for any reason a
                # BugTrackerConnectError will be raised at this point.
                remote_id, remote_bug = self.getRemoteBug(bug_id)
                self.bugs[remote_id] = remote_bug

        # For large lists of bug ids we retrieve bug statuses as a batch
        # from the remote bug tracker so as to avoid effectively DOSing
        # it.
        else:
            self.bugs = self.getRemoteBugBatch(bug_ids)

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        """Return the remote status for the given bug id.

        Raise BugNotFound if the bug can't be found.
        Raise InvalidBugId if the bug id has an unexpected format.
        """
        try:
            bug_id = int(bug_id)
        except ValueError:
            raise InvalidBugId(
                "bug_id must be convertable an integer: %s" % str(bug_id))

        try:
            remote_bug = self.bugs[bug_id]
        except KeyError:
            raise BugNotFound(bug_id)

        # If the bug has a valid resolution as well as a status then we return
        # that, since it's more informative than the status field on its own.
        if (remote_bug.has_key('resolution') and
            remote_bug['resolution'] not in ['', '--', None]):
            return remote_bug['resolution']
        else:
            try:
                return remote_bug['status']
            except KeyError:
                # Some Trac instances don't include the bug status in their
                # CSV exports. In those cases we raise a warning.
                self.warning("Trac ticket %i defines no status." % bug_id)
                return UNKNOWN_REMOTE_STATUS

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, remote_status):
        """See `IExternalBugTracker`"""
        status_map = {
            'accepted': BugTaskStatus.CONFIRMED,
            'assigned': BugTaskStatus.CONFIRMED,
            # XXX: 2007-08-06 Graham Binns:
            #      We should follow dupes if possible.
            'duplicate': BugTaskStatus.CONFIRMED,
            'fixed': BugTaskStatus.FIXRELEASED,
            'closed': BugTaskStatus.FIXRELEASED,
            'invalid': BugTaskStatus.INVALID,
            'new': BugTaskStatus.NEW,
            'open': BugTaskStatus.NEW,
            'reopened': BugTaskStatus.NEW,
            'wontfix': BugTaskStatus.WONTFIX,
            'worksforme': BugTaskStatus.INVALID,
            UNKNOWN_REMOTE_STATUS: BugTaskStatus.UNKNOWN,
        }

        try:
            return status_map[remote_status]
        except KeyError:
            self.warning("Unknown remote status '%s'." % remote_status)
            return BugTaskStatus.UNKNOWN


class Roundup(ExternalBugTracker):
    """An ExternalBugTracker descendant for handling Roundup bug trackers."""

    def __init__(self, txn, bugtracker):
        """Create a new Roundup instance.

        :bugtracker: The Roundup bugtracker.

        If the bug tracker's baseurl is one which points to
        bugs.python.org, the behaviour of the Roundup bugtracker will be
        different from that which it exhibits to every other Roundup bug
        tracker, since the Python Roundup instance is very specific to
        Python and in fact behaves rather more like SourceForge than
        Roundup.
        """
        super(Roundup, self).__init__(txn, bugtracker)

        if self.isPython():
            # The bug export URLs differ only from the base Roundup ones
            # insofar as they need to include the resolution column in
            # order for us to be able to successfully export it.
            self.single_bug_export_url = (
                "issue?@action=export_csv&@columns=title,id,activity,"
                "status,resolution&@sort=id&@group=priority&@filter=id"
                "&@pagesize=50&@startwith=0&id=%i")
            self.batch_bug_export_url = (
                "issue?@action=export_csv&@columns=title,id,activity,"
                "status,resolution&@sort=activity&@group=priority"
                "&@pagesize=50&@startwith=0")
        else:
            # XXX: 2007-08-29 Graham Binns
            #      I really don't like these URLs but Roundup seems to
            #      be very sensitive to changing them. These are the
            #      only ones that I can find that work consistently on
            #      all the roundup instances I can find to test them
            #      against, but I think that refining these should be
            #      looked into at some point.
            self.single_bug_export_url = (
                "issue?@action=export_csv&@columns=title,id,activity,"
                "status&@sort=id&@group=priority&@filter=id"
                "&@pagesize=50&@startwith=0&id=%i")
            self.batch_bug_export_url = (
                "issue?@action=export_csv&@columns=title,id,activity,"
                "status&@sort=activity&@group=priority&@pagesize=50"
                "&@startwith=0")

    @property
    def status_map(self):
        """Return the remote status -> BugTaskStatus mapping for the
        current remote bug tracker.
        """
        if self.isPython():
            # Python bugtracker statuses come in two parts: status and
            # resolution. Both of these are integer values. We can look
            # them up in the form status_map[status][resolution]
            return {
                # Open issues (status=1). We also use this as a fallback
                # for statuses 2 and 3, for which the mappings are
                # different only in a few instances.
                1: {
                    None: BugTaskStatus.NEW,       # No resolution
                    1: BugTaskStatus.CONFIRMED,    # Resolution: accepted
                    2: BugTaskStatus.CONFIRMED,    # Resolution: duplicate
                    3: BugTaskStatus.FIXCOMMITTED, # Resolution: fixed
                    4: BugTaskStatus.INVALID,      # Resolution: invalid
                    5: BugTaskStatus.CONFIRMED,    # Resolution: later
                    6: BugTaskStatus.INVALID,      # Resolution: out-of-date
                    7: BugTaskStatus.CONFIRMED,    # Resolution: postponed
                    8: BugTaskStatus.WONTFIX,      # Resolution: rejected
                    9: BugTaskStatus.CONFIRMED,    # Resolution: remind
                    10: BugTaskStatus.WONTFIX,     # Resolution: wontfix
                    11: BugTaskStatus.INVALID,     # Resolution: works for me
                    UNKNOWN_REMOTE_STATUS: BugTaskStatus.UNKNOWN},

                # Closed issues (status=2)
                2: {
                    None: BugTaskStatus.WONTFIX,   # No resolution
                    1: BugTaskStatus.FIXCOMMITTED, # Resolution: accepted
                    3: BugTaskStatus.FIXRELEASED,  # Resolution: fixed
                    7: BugTaskStatus.WONTFIX},     # Resolution: postponed

                # Pending issues (status=3)
                3: {
                    None: BugTaskStatus.INCOMPLETE,# No resolution
                    7: BugTaskStatus.WONTFIX},     # Resolution: postponed
            }

        else:
            # Our mapping of Roundup => Launchpad statuses.  Roundup
            # statuses are integer-only and highly configurable.
            # Therefore we map the statuses available by default so that
            # they can be overridden by subclassing the Roundup class.
            return {
                1: BugTaskStatus.NEW,          # Roundup status 'unread'
                2: BugTaskStatus.CONFIRMED,    # Roundup status 'deferred'
                3: BugTaskStatus.INCOMPLETE,   # Roundup status 'chatting'
                4: BugTaskStatus.INCOMPLETE,   # Roundup status 'need-eg'
                5: BugTaskStatus.INPROGRESS,   # Roundup status 'in-progress'
                6: BugTaskStatus.INPROGRESS,   # Roundup status 'testing'
                7: BugTaskStatus.FIXCOMMITTED, # Roundup status 'done-cbb'
                8: BugTaskStatus.FIXRELEASED,  # Roundup status 'resolved'
                UNKNOWN_REMOTE_STATUS: BugTaskStatus.UNKNOWN}

    def isPython(self):
        """Return True if the remote bug tracker is at bugs.python.org.

        Return False otherwise.
        """
        return 'bugs.python.org' in self.baseurl

    def _getBug(self, bug_id):
        """Return the bug with the ID bug_id from the internal bug list.

        :param bug_id: The ID of the remote bug to return.
        :type bug_id: int

        BugNotFound will be raised if the bug does not exist.
        InvalidBugId will be raised if bug_id is not of a valid format.
        """
        try:
            bug_id = int(bug_id)
        except ValueError:
            raise InvalidBugId(
                "bug_id must be convertible an integer: %s." % str(bug_id))

        try:
            return self.bugs[bug_id]
        except KeyError:
            raise BugNotFound(bug_id)

    def getRemoteBug(self, bug_id):
        """See `ExternalBugTracker`."""
        bug_id = int(bug_id)
        query_url = '%s/%s' % (
            self.baseurl, self.single_bug_export_url % bug_id)
        reader = csv.DictReader(self._fetchPage(query_url))
        return (bug_id, reader.next())

    def getRemoteBugBatch(self, bug_ids):
        """See `ExternalBugTracker`"""
        # XXX: 2007-08-28 Graham Binns
        #      At present, Roundup does not support exporting only a
        #      subset of bug ids as a batch (launchpad bug 135317). When
        #      this bug is fixed we need to change this method to only
        #      export the bug ids needed rather than hitting the remote
        #      tracker for a potentially massive number of bugs.
        query_url = '%s/%s' % (self.baseurl, self.batch_bug_export_url)
        remote_bugs = csv.DictReader(self._fetchPage(query_url))
        bugs = {}
        for remote_bug in remote_bugs:
            # We're only interested in the bug if it's one of the ones in
            # bug_ids.
            if remote_bug['id'] not in bug_ids:
                continue

            bugs[int(remote_bug['id'])] = remote_bug

        return bugs

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        """See `ExternalBugTracker`."""
        remote_bug = self._getBug(bug_id)
        if self.isPython():
            # A remote bug must define a status and a resolution, even
            # if that resolution is 'None', otherwise we can't
            # accurately assign a BugTaskStatus to it.
            try:
                status = remote_bug['status']
                resolution = remote_bug['resolution']
            except KeyError:
                raise UnparseableBugData(
                    "Remote bug %s does not define both a status and a "
                    "resolution." % bug_id)

            # Remote status is stored as a string, so for sanity's sake
            # we return an easily-parseable string.
            return '%s:%s' % (status, resolution)

        else:
            try:
                return remote_bug['status']
            except KeyError:
                raise UnparseableBugData(
                    "Remote bug %s does not define a status.")

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, remote_status):
        """See `IExternalBugTracker`."""
        # XXX: 2007-09-04 Graham Binns
        #      We really shouldn't have to do this here because we
        #      should logically never be passed UNKNOWN_REMOTE_STATUS as
        #      a status to convert in the first place. Unfortunately,
        #      that's exactly what ExternalBugTracker.updateBugWatches()
        #      does (LP bug 136391), so until that bug is fixed we make
        #      this check here for the sake of avoiding silly errors.
        if remote_status == UNKNOWN_REMOTE_STATUS:
            return BugTaskStatus.UNKNOWN

        if self.isPython():
            return self._convertPythonRemoteStatus(remote_status)
        else:
            try:
                return self.status_map[int(remote_status)]
            except (KeyError, ValueError):
                self.warning("Unknown remote status '%s'." % remote_status)
                return BugTaskStatus.UNKNOWN

    def _convertPythonRemoteStatus(self, remote_status):
        """Convert a Python bug status into a BugTaskStatus.

        :remote_status: A bugs.python.org status string in the form
            '<status>:<resolution>', where status is an integer and
            resolution is an integer or None. An AssertionError will be
            raised if these conditions are not met.
        """
        try:
            status, resolution = remote_status.split(':')
        except ValueError:
            raise AssertionError(
                "The remote status must be a string of the form "
                "<status>:<resolution>.")

        try:
            status = int(status)

            # If we can't find the status in our status map we can give
            # up now.
            if not self.status_map.has_key(status):
                self.warning("Unknown remote status '%s'." % remote_status)
                return BugTaskStatus.UNKNOWN
        except ValueError:
            raise AssertionError("The remote status must be an integer.")

        if resolution.isdigit():
            resolution = int(resolution)
        elif resolution == 'None':
            resolution = None
        else:
            raise AssertionError(
                "The resolution must be an integer or 'None'.")

        # We look the status/resolution mapping up first in the status's
        # dict then in the dict for status #1 (open) if we can't find
        # it.
        if self.status_map[status].has_key(resolution):
            return self.status_map[status][resolution]
        elif self.status_map[1].has_key(resolution):
            return self.status_map[1][resolution]
        else:
            self.warning("Unknown remote status '%s'." % remote_status)
            return BugTaskStatus.UNKNOWN


class SourceForge(ExternalBugTracker):
    """An ExternalBugTracker for SourceForge bugs."""

    # We only allow ourselves to update one SourceForge bug at a time to
    # avoid getting clobbered by SourceForge's rate limiting code.
    export_url = 'support/tracker.php?aid=%s'
    batch_size = 1

    def __init__(self, txn, bugtracker):
        super(SourceForge, self).__init__(txn, bugtracker)

    def initializeRemoteBugDB(self, bug_ids):
        """See `ExternalBugTracker`.

        We override this method because SourceForge does not provide a
        nice way for us to export bug statuses en masse. Instead, we
        resort to screen-scraping on a per-bug basis. Therefore the
        usual choice of batch vs. single export does not apply here and
        we only perform single exports.
        """
        self.bugs = {}

        for bug_id in bug_ids:
            query_url = self.export_url % bug_id
            page_data = self._getPage(query_url)

            soup = BeautifulSoup(page_data)
            status_tag = soup.find(text=re.compile('Status:'))

            # If we can't find a status line in the output from
            # SourceForge there's little point in continuing.
            if not status_tag:
                raise UnparseableBugData(
                    'Remote bug %s does not define a status.' % bug_id)

            # We can extract the status by finding the grandparent tag.
            # Happily, BeautifulSoup will turn the contents of this tag
            # into a newline-delimited list from which we can then
            # extract the requisite data.
            status_row = status_tag.findParent().findParent()
            status = status_row.contents[-1]
            status = status.strip()

            # We need to do the same for Resolution, though if we can't
            # find it it's not critical.
            resolution_tag = soup.find(text=re.compile('Resolution:'))
            if resolution_tag:
                resolution_row = resolution_tag.findParent().findParent()
                resolution = resolution_row.contents[-1]
                resolution = resolution.strip()
            else:
                resolution = None

            self.bugs[int(bug_id)] = {
                'id': int(bug_id),
                'status': status,
                'resolution': resolution}

    def getRemoteImportance(self, bug_id):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        UNKNOWN_REMOTE_IMPORTANCE will always be returned.
        """
        return UNKNOWN_REMOTE_IMPORTANCE

    def getRemoteStatus(self, bug_id):
        """See `ExternalBugTracker`."""
        try:
            bug_id = int(bug_id)
        except ValueError:
            raise InvalidBugId(
                "bug_id must be convertible to an integer: %s" % str(bug_id))

        try:
            remote_bug = self.bugs[bug_id]
        except KeyError:
            raise BugNotFound(bug_id)

        try:
            return '%(status)s:%(resolution)s' % remote_bug
        except KeyError:
            raise UnparseableBugData(
                "Remote bug %i does not define a status." % bug_id)

    def convertRemoteImportance(self, remote_importance):
        """See `ExternalBugTracker`.

        This method is implemented here as a stub to ensure that
        existing functionality is preserved. As a result,
        BugTaskImportance.UNKNOWN will always be returned.
        """
        return BugTaskImportance.UNKNOWN

    def convertRemoteStatus(self, remote_status):
        """See `IExternalBugTracker`."""
        # XXX: 2007-09-06 Graham Binns
        #      We shouldn't have to do this, but
        #      ExternalBugTracker.updateBugWatches() will pass us
        #      UNKNOWN_BUG_STATUS if it gets it from getRemoteStatus()
        #      (Launchpad bug 136391).
        if remote_status == UNKNOWN_REMOTE_STATUS:
            return BugTaskStatus.UNKNOWN

        # SourceForge statuses come in two parts: status and
        # resolution. Both of these are strings. We can look
        # them up in the form status_map[status][resolution]
        status_map = {
            # We use the open status as a fallback when we can't find an
            # exact mapping for the other statuses.
            'Open' : {
                None: BugTaskStatus.NEW,
                'Accepted': BugTaskStatus.CONFIRMED,
                'Duplicate': BugTaskStatus.CONFIRMED,
                'Fixed': BugTaskStatus.FIXCOMMITTED,
                'Invalid': BugTaskStatus.INVALID,
                'Later': BugTaskStatus.CONFIRMED,
                'Out of Date': BugTaskStatus.INVALID,
                'Postponed': BugTaskStatus.CONFIRMED,
                'Rejected': BugTaskStatus.WONTFIX,
                'Remind': BugTaskStatus.CONFIRMED,

                # Some custom SourceForge trackers misspell this, so we
                # deal with the syntactically incorrect version, too.
                "Won't Fix": BugTaskStatus.WONTFIX,
                'Wont Fix': BugTaskStatus.WONTFIX,
                'Works For Me': BugTaskStatus.INVALID,
            },

            'Closed': {
                None: BugTaskStatus.FIXRELEASED,
                'Accepted': BugTaskStatus.FIXCOMMITTED,
                'Fixed': BugTaskStatus.FIXRELEASED,
                'Postponed': BugTaskStatus.WONTFIX,
            },

            'Pending': {
                None: BugTaskStatus.INCOMPLETE,
                'Postponed': BugTaskStatus.WONTFIX,
            },
        }

        # We have to deal with situations where we can't get a
        # resolution to go with the status, so we define both even if we
        # can't get both from SourceForge.
        if ':' in remote_status:
            status, resolution = remote_status.split(':')

            if resolution == 'None':
                resolution = None
        else:
            status = remote_status
            resolution = None

        if status not in status_map:
            self.warning("Unknown status '%s'" % remote_status)
            return BugTaskStatus.UNKNOWN

        local_status = status_map[status].get(
            resolution, status_map['Open'].get(resolution))
        if local_status is None:
            self.warning("Unknown status '%s'" % remote_status)
            return BugTaskStatus.UNKNOWN
        else:
            return local_status


class RequestTracker(ExternalBugTracker):
    """`ExternalBugTracker` subclass for handling RT imports."""

    ticket_url = 'REST/1.0/ticket/%s/show'
    batch_url = 'REST/1.0/search/ticket/'
    batch_query_threshold = 1

    @property
    def credentials(self):
        """Return the authentication credentials needed to log in.

        If there are specific credentials for the current RT instance,
        these will be returned. Otherwise the RT default guest
        credentials (username and password of 'guest') will be returned.
        """
        credentials_map = {
            'rt.cpan.org': {'user': 'launchpad@launchpad.net',
                            'pass': 'th4t3'}}

        hostname = urlparse(self.baseurl)[1]
        try:
            return credentials_map[hostname]
        except KeyError:
            return {'user': 'guest', 'pass': 'guest'}

    def _logIn(self, opener):
        """Attempt to log in to the remote RT service.

        :param opener: An instance of urllib2.OpenerDirector
            to be used to connect to the remote server.

        If HTTPError or URLErrors are encountered at any point in this
        process, they will be raised to be caught at the callsite.

        This method is separate from the _opener property so as to allow
        us to test the _opener property without having to connect to a
        remote server.
        """
        # To log in to an RT instance we must pass a username and
        # password to its login form, as a user would from the web.
        opener.open('%s/' % self.baseurl, urllib.urlencode(
            self.credentials))

    @cachedproperty
    def _opener(self):
        """Return a urllib2.OpenerDirector for the remote RT instance.

        An attempt will be made to log in to the remote instance before
        the opener is returned. If logging in is not successful a
        BugTrackerConnectError will be raised
        """
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())

        # Attempt to log in to the remote system. Raise an error if we
        # can't.
        try:
            self._logIn(opener)
        except (urllib2.HTTPError, urllib2.URLError), error:
            raise BugTrackerConnectError('%s/' % self.baseurl,
                "Unable to authenticate with remote RT service: "
                "Could not submit login form: " +
                error.message)

        return opener

    def urlopen(self, request, data=None):
        """Return a handle to a remote resource.

        This method overrides that of `ExternalBugTracker` so that the
        custom URL opener for RequestTracker instances can be used.
        """
        # We create our own opener so as to handle the RT authentication
        # cookies that need to be passed around.
        return self._opener.open(request, data)

    def getRemoteBug(self, bug_id):
        """See `ExternalBugTracker`."""
        ticket_url = self.ticket_url % str(bug_id)
        query_url = '%s/%s' % (self.baseurl, ticket_url)
        try:
            bug_data = self.urlopen(query_url)
        except urllib2.HTTPError, error:
            raise BugTrackerConnectError(ticket_url, error.message)

        # We use the first line of the response to ensure that we've
        # made a successful request.
        firstline = bug_data.readline().strip().split(' ')
        if firstline[1] != '200':
            # If anything goes wrong we raise a BugTrackerConnectError.
            # We included in the error message the status code and error
            # message returned by the server.
            raise BugTrackerConnectError(
                query_url,
                "Unable to retrieve bug %s. The remote server returned the "
                "following error: %s." %
                (str(bug_id), " ".join(firstline[1:])))

        # RT's REST interface returns tickets in RFC822 format, so we
        # can use the email module to parse them.
        bug = email.message_from_string(bug_data.read().strip())
        if bug.get('id') is None:
            return None, None
        else:
            bug_id = bug['id'].replace('ticket/', '')
            return int(bug_id), bug

    def getRemoteBugBatch(self, bug_ids):
        """See `ExternalBugTracker`."""
        # We need to ensure that all the IDs are strings first.
        id_list = [str(id) for id in bug_ids]
        query = "id = " + "OR id = ".join(id_list)

        query_url = '%s/%s' % (self.baseurl, self.batch_url)
        request_params = {'query': query, 'format': 'l'}
        try:
            bug_data = self.urlopen(query_url, urllib.urlencode(
                request_params))
        except urllib2.HTTPError, error:
            raise BugTrackerConnectError(query_url, error.message)

        # We use the first line of the response to ensure that we've
        # made a successful request.
        firstline = bug_data.readline().strip().split(' ')
        if firstline[1] != '200':
            # If anything goes wrong we raise a BugTrackerConnectError.
            # We included in the error message the status code and error
            # message returned by the server.
            bug_id_string = ", ".join([str(bug_id) for bug_id in bug_ids])
            raise BugTrackerConnectError(
                query_url,
                "Unable to retrieve bugs %s. The remote server returned the "
                "following error:  %s." %
                (bug_id_string, " ".join(firstline[1:])))

        # Tickets returned in RT multiline format are separated by lines
        # containing only --\n.
        tickets = bug_data.read().split("--\n")
        bugs = {}
        for ticket in tickets:
            ticket = ticket.strip()

            # RT's REST interface returns tickets in RFC822 format, so we
            # can use the email module to parse them.
            bug = email.message_from_string(ticket)

            # We only bother adding the bug to the bugs dict if we
            # actually have some data worth adding.
            if bug.get('id') is not None:
                bug_id = bug['id'].replace('ticket/', '')
                bugs[int(bug_id)] = bug

        return bugs

    def getRemoteStatus(self, bug_id):
        """Return the remote status of a given bug.

        See `ExternalBugTracker`.
        """
        try:
            bug_id = int(bug_id)
        except ValueError:
            raise InvalidBugId(
                "RequestTracker bug ids must be integers (was passed %r)"
                % bug_id)

        if bug_id not in self.bugs:
            raise BugNotFound(bug_id)

        return self.bugs[bug_id]['status']

    def getRemoteImportance(self, bug_id):
        """See `IExternalBugTracker`."""
        pass

    def convertRemoteImportance(self, remote_importance):
        """See `IExternalBugTracker`."""
        return UNKNOWN_REMOTE_IMPORTANCE

    def convertRemoteStatus(self, remote_status):
        """Convert an RT status into a Launchpad BugTaskStatus."""
        status_map = {
            'new': BugTaskStatus.NEW,
            'open': BugTaskStatus.CONFIRMED,
            'stalled': BugTaskStatus.CONFIRMED,
            'rejected': BugTaskStatus.INVALID,
            'resolved': BugTaskStatus.FIXRELEASED,
            UNKNOWN_REMOTE_STATUS.lower(): BugTaskStatus.UNKNOWN}

        try:
            remote_status = remote_status.lower()
            return status_map[remote_status]
        except KeyError:
            self.warning("Unknown status '%s'." % remote_status)
            return BugTaskStatus.UNKNOWN


BUG_TRACKER_CLASSES = {
    BugTrackerType.BUGZILLA: Bugzilla,
    BugTrackerType.DEBBUGS: DebBugs,
    BugTrackerType.MANTIS: Mantis,
    BugTrackerType.TRAC: Trac,
    BugTrackerType.ROUNDUP: Roundup,
    BugTrackerType.RT: RequestTracker,
    BugTrackerType.SOURCEFORGE: SourceForge
    }


def get_external_bugtracker(txn, bugtracker):
    """Return an `ExternalBugTracker` for bugtracker."""
    bugtrackertype = bugtracker.bugtrackertype
    bugtracker_class = BUG_TRACKER_CLASSES.get(bugtracker.bugtrackertype)
    if bugtracker_class is not None:
        return bugtracker_class(txn, bugtracker)
    else:
        raise UnknownBugTrackerTypeError(bugtrackertype.name,
            bugtracker.name)
