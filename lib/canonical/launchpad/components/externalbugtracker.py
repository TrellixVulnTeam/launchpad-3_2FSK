# Copyright 2006 Canonical Ltd.  All rights reserved.

"""External bugtrackers."""

__metaclass__ = type

import os.path
import urllib
import urllib2
import xml.parsers.expat
from xml.dom import minidom

from zope.interface import implements

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.lp.dbschema import BugTrackerType, BugTaskStatus
from canonical.launchpad.scripts import log, debbugs
from canonical.launchpad.interfaces import (
    IExternalBugtracker, UNKNOWN_REMOTE_STATUS)

# The user agent we send in our requests
LP_USER_AGENT = "Launchpad Bugscraper/0.1 (http://launchpad.net/malone)"


class UnknownBugTrackerTypeError(Exception):
    """Exception class to catch systems we don't have a class for yet."""

    def __init__(self, bugtrackertypename, bugtrackername):
        self.bugtrackertypename = bugtrackertypename
        self.bugtrackername = bugtrackername

    def __str__(self):
        return self.bugtrackertypename


class UnsupportedBugTrackerVersion(Exception):
    """The bug tracker version is not supported."""


class BugTrackerConnectError(Exception):
    """Exception class to catch misc errors contacting a bugtracker."""

    def __init__(self, url, error):
        self.url = url
        self.error = str(error)

    def __str__(self):
        return "%s: %s" % (self.url, self.error)


class InvalidBugId(Exception):
    """The bug id wasn't in the format the bug tracker expected.

    For example, Bugzilla and debbugs expect the bug id to be an
    integer.
    """


class BugNotFound(Exception):
    """The bug was not found in the external bug tracker."""


def get_external_bugtracker(bugtracker, version=None):
    """Return an ExternalBugTracker for bugtracker."""
    bugtrackertype = bugtracker.bugtrackertype
    if bugtrackertype == BugTrackerType.BUGZILLA:
        return Bugzilla(bugtracker.baseurl, version)
    elif bugtrackertype == BugTrackerType.DEBBUGS:
        return DebBugs()
    else:
        raise UnknownBugTrackerTypeError(bugtrackertype.name,
            bugtracker.name)


class ExternalBugTracker:
    """Base class for an external bug tracker."""

    implements(IExternalBugtracker)

    def _initializeRemoteBugDB(self, bug_ids):
        """Do any initialization before each bug watch is updated.

        It's optional to override this method.
        """

    def _getRemoteStatus(self, bug_id):
        """Return the remote status for the given bug id.

        Raise BugNotFound if the bug can't be found.
        Raise InvalidBugId if the bug id has an unexpected format.
        """
        raise NotImplementedError(self._getRemoteStatus)

    def updateBugWatches(self, bug_watches):
        """Update the given bug watches."""
        bug_watches_by_remote_bug = {}
        for bug_watch in bug_watches:
            #XXX: Use remotebug.strip() until bug 34105 is fixed.
            #     -- Bjorn Tillenius, 2006-03-09
            bug_watches_by_remote_bug[bug_watch.remotebug.strip()] = bug_watch
        bug_ids_to_update = set(bug_watches_by_remote_bug.keys())
        self._initializeRemoteBugDB(bug_ids_to_update)
        for bug_id in bug_ids_to_update:
            bug_watch = bug_watches_by_remote_bug[bug_id]
            bug_watch.lastchecked = UTC_NOW
            try:
                new_remote_status = self._getRemoteStatus(bug_id)
            except InvalidBugId, error:
                log.warn("Invalid bug id %r on %s" % (bug_id, self.baseurl))
                new_remote_status = UNKNOWN_REMOTE_STATUS
            except BugNotFound:
                log.warn("Didn't find bug %r on %s" % (bug_id, self.baseurl))
                new_remote_status = UNKNOWN_REMOTE_STATUS

            new_malone_status = self.convertRemoteStatus(new_remote_status)
            old_malone_status = self.convertRemoteStatus(bug_watch.remotestatus)
            if (new_remote_status != bug_watch.remotestatus or
                new_malone_status != old_malone_status):
                bug_watch.updateStatus(new_remote_status, new_malone_status)


class Bugzilla(ExternalBugTracker):
    """A class that deals with communications with a remote Bugzilla system."""

    implements(IExternalBugtracker)

    def __init__(self, baseurl, version=None):
        if baseurl.endswith("/"):
            baseurl = baseurl[:-1]
        self.baseurl = baseurl
        self.version = version

    def _getPage(self, page):
        """GET the specified page on the remote HTTP server."""
        # For some reason, bugs.kde.org doesn't allow the regular urllib
        # user-agent string (Python-urllib/2.x) to access their
        # bugzilla, so we send our own instead.
        request = urllib2.Request("%s/%s" % (self.baseurl, page),
                                  headers={'User-agent': LP_USER_AGENT})
        try:
            url = urllib2.urlopen(request)
        except (urllib2.HTTPError, urllib2.URLError), val:
            raise BugTrackerConnectError(self.baseurl, val)
        page_contents = url.read()
        return page_contents

    def _postPage(self, page, form):
        """POST to the specified page.

        :form: is a dict of form variables being POSTed.
        """
        url = "%s/%s" % (self.baseurl, page)
        post_data = urllib.urlencode(form)
        request = urllib2.Request(url, headers={'User-agent': LP_USER_AGENT})
        url = urllib2.urlopen(request, data=post_data)
        page_contents = url.read()
        return page_contents

    def _probe_version(self):
        version_xml = self._getPage('xml.cgi?id=1')
        try:
            document = minidom.parseString(version_xml)
        except xml.parsers.expat.ExpatError, e:
            raise BugTrackerConnectError(self.baseurl, "Failed to parse output "
                                         "when probing for version: %s" % e)
        bugzilla = document.getElementsByTagName("bugzilla")
        if not bugzilla:
            return None
        version = bugzilla[0].getAttribute("version")
        return version

    def convertRemoteStatus(self, remote_status):
        """See IExternalBugtracker.

        Bugzilla status consist of two parts separated by space, where
        the last part is the resolution. The resolution is optional.
        """
        if not remote_status or remote_status == UNKNOWN_REMOTE_STATUS:
            return BugTaskStatus.UNKNOWN
        if ' ' in remote_status:
            remote_status, resolution = remote_status.split(' ', 1)
        else:
            resolution = ''

        if remote_status == 'ASSIGNED':
           malone_status = BugTaskStatus.INPROGRESS
        elif remote_status == 'NEEDINFO':
            malone_status = BugTaskStatus.NEEDSINFO
        elif remote_status == 'PENDINGUPLOAD':
            malone_status = BugTaskStatus.FIXCOMMITTED
        elif remote_status in ['RESOLVED', 'VERIFIED', 'CLOSED']:
            # depends on the resolution:
            if resolution == 'FIXED':
                malone_status = BugTaskStatus.FIXRELEASED
            else:
                #XXX: Which are the valid resolutions? We should fail
                #     if we don't know of the resolution. Bug 31745.
                #     -- Bjorn Tillenius, 2005-02-03
                malone_status = BugTaskStatus.REJECTED
        elif remote_status in ['REOPENED', 'NEW', 'UPSTREAM']:
            malone_status = BugTaskStatus.CONFIRMED
        elif remote_status in ['UNCONFIRMED']:
            malone_status = BugTaskStatus.UNCONFIRMED
        else:
            log.warning(
                "Unknown Bugzilla status '%s' at %s" % (
                    remote_status, self.baseurl))
            malone_status = BugTaskStatus.UNKNOWN

        return malone_status

    def _initializeRemoteBugDB(self, bug_ids):
        """See ExternalBugTracker."""
        if self.version is None:
            self.version = self._probe_version()
        if self.version < '2.16':
            raise UnsupportedBugTrackerVersion(
                "Unsupported version %r for %s" % (self.version, self.baseurl))

        data = {'form_name'   : 'buglist.cgi',
                'bug_id_type' : 'include',
                'bug_id'      : ','.join(bug_ids),
                }
        if self.version < '2.17.1':
            data.update({'format' : 'rdf'})
            status_tag = "bz:status"
        else:
            data.update({'ctype'  : 'rdf'})
            status_tag = "bz:bug_status"
        buglist_xml = self._postPage('buglist.cgi', data)
        try:
            document = minidom.parseString(buglist_xml)
        except xml.parsers.expat.ExpatError, e:
            log.error('Failed to parse XML description for %s bugs %s: %s' %
                      (self.baseurl, bug_ids, e))
            return False

        bug_nodes = document.getElementsByTagName('bz:bug')
        self.remote_bug_status = {}
        for bug_node in bug_nodes:
            bug_id_nodes = bug_node.getElementsByTagName("bz:id")
            assert len(bug_id_nodes) == 1, "Should be only one id node."
            bug_id_node = bug_id_nodes[0]
            assert len(bug_id_node.childNodes) == 1, (
                "id node should contain a non-empty text string.")
            bug_id = str(bug_id_node.childNodes[0].data)

            status_nodes = bug_node.getElementsByTagName(status_tag)
            assert len(status_nodes) == 1, "Should be only one status node."
            bug_status_node = status_nodes[0]
            assert len(bug_status_node.childNodes) == 1, (
                "status node should contain a non-empty text string.")
            status = bug_status_node.childNodes[0].data

            resolution_nodes = bug_node.getElementsByTagName('bz:resolution')
            assert len(resolution_nodes) <= 1, (
                "Only one resolution node is allowed.")
            if resolution_nodes:
                assert len(resolution_nodes[0].childNodes) <= 1, (
                    "Resolution should contain a, possible empty, string.")
                if resolution_nodes[0].childNodes:
                    resolution = resolution_nodes[0].childNodes[0].data
                    status += ' %s' % resolution
            self.remote_bug_status[bug_id] = status

        return True

    def _getRemoteStatus(self, bug_id):
        """See ExternalBugTracker."""
        if not bug_id.isdigit():
            raise InvalidBugId(
                "Bugzilla (%s) bug number not an integer: %s" % (
                    self.baseurl, bug_id))
        try:
            return self.remote_bug_status[bug_id]
        except KeyError:
            raise BugNotFound(bug_id)


debbugsstatusmap = {'open':      BugTaskStatus.UNCONFIRMED,
                    'forwarded': BugTaskStatus.CONFIRMED,
                    'done':      BugTaskStatus.FIXRELEASED}


class DebBugs(ExternalBugTracker):
    """A class that deals with communications with a debbugs db."""

    implements(IExternalBugtracker)

    # We don't support different versions of debbugs.
    version = None
    debbugs_pl = os.path.join(
        os.path.dirname(debbugs.__file__), 'debbugs-log.pl')

    def __init__(self, db_location=None):
        if db_location is None:
            self.db_location = config.malone.debbugs_db_location
        else:
            self.db_location = db_location

    @property
    def baseurl(self):
        return self.db_location

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
            log.error('Malformed debbugs status: %r' % remote_status)
            return BugTaskStatus.UNKNOWN
        status = parts[0]
        severity = parts[1]
        tags = parts[2:]

        # For the moment we convert only the status, not the severity.
        try:
            malone_status = debbugsstatusmap[status]
        except KeyError:
            log.warn('Unknown debbugs status "%s"' % status)
            malone_status = BugTaskStatus.UNKNOWN
        if status == 'open':
            confirmed_tags = [
                'help', 'confirmed', 'upstream', 'fixed-upstream', 'wontfix']
            fix_committed_tags = ['pending', 'fixed', 'fixed-in-experimental']
            if 'moreinfo' in tags:
                malone_status = BugTaskStatus.NEEDSINFO
            for confirmed_tag in confirmed_tags:
                if confirmed_tag in tags:
                    malone_status = BugTaskStatus.CONFIRMED
                    break
            for fix_committed_tag in fix_committed_tags:
                if fix_committed_tag in tags:
                    malone_status = BugTaskStatus.FIXCOMMITTED
                    break

        return malone_status

    def _initializeRemoteBugDB(self, bug_ids):
        """See ExternalBugTracker."""
        if not os.path.exists(os.path.join(self.db_location, 'db-h')):
            log.error("There's no debbugs db at %s" % self.db_location)
            self.debbugs_db = None
        else:
            self.debbugs_db = debbugs.Database(
                self.db_location, self.debbugs_pl)

    def _getRemoteStatus(self, bug_id):
        """See ExternalBugTracker."""
        if self.debbugs_db is None:
            raise BugNotFound(bug_id)
        if not bug_id.isdigit():
            raise InvalidBugId(
                "Debbugs bug number not an integer: %s" % bug_id)
        try:
            debian_bug = self.debbugs_db[int(bug_id)]
        except KeyError:
            raise BugNotFound(bug_id)
        if not debian_bug.severity:
            # 'normal' is the default severity in debbugs.
            severity = 'normal'
        else:
            severity = debian_bug.severity
        new_remote_status = ' '.join(
            [debian_bug.status, severity] + debian_bug.tags)
        return new_remote_status
