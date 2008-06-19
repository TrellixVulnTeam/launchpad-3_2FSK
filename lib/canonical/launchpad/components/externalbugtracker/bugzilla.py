# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Bugzilla ExternalBugTracker utility."""

__metaclass__ = type
__all__ = [
    'Bugzilla',
    'BugzillaLPPlugin',
    ]

import pytz
import time
import xml.parsers.expat
import xmlrpclib

from datetime import datetime
from xml.dom import minidom

from zope.interface import implements

from canonical import encoding
from canonical.launchpad.components.externalbugtracker import (
    BugNotFound, BugTrackerConnectError, ExternalBugTracker, InvalidBugId,
    LookupTree, UnknownRemoteStatusError, UnparseableBugData,
    UnparseableBugTrackerVersion)
from canonical.launchpad.interfaces import (
    BugTaskStatus, BugTaskImportance, UNKNOWN_REMOTE_IMPORTANCE)
from canonical.launchpad.interfaces.externalbugtracker import (
    ISupportsCommentImport)
from canonical.launchpad.webapp.url import urlappend


class Bugzilla(ExternalBugTracker):
    """An ExternalBugTrack for dealing with remote Bugzilla systems."""

    batch_query_threshold = 0 # Always use the batch method.

    def __init__(self, baseurl, version=None):
        super(Bugzilla, self).__init__(baseurl)
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

    _status_lookup_titles = 'Bugzilla status', 'Bugzilla resolution'
    _status_lookup = LookupTree(
        ('ASSIGNED', 'ON_DEV', 'FAILS_QA', 'STARTED',
         BugTaskStatus.INPROGRESS),
        ('NEEDINFO', 'NEEDINFO_REPORTER', 'WAITING', 'SUSPENDED',
         BugTaskStatus.INCOMPLETE),
        ('PENDINGUPLOAD', 'MODIFIED', 'RELEASE_PENDING', 'ON_QA',
         BugTaskStatus.FIXCOMMITTED),
        ('REJECTED', BugTaskStatus.INVALID),
        ('RESOLVED', 'VERIFIED', 'CLOSED',
            LookupTree(
                ('CODE_FIX', 'CURRENTRELEASE', 'ERRATA', 'NEXTRELEASE',
                 'PATCH_ALREADY_AVAILABLE', 'FIXED', 'RAWHIDE',
                 BugTaskStatus.FIXRELEASED),
                ('WONTFIX', BugTaskStatus.WONTFIX),
                (BugTaskStatus.INVALID,))),
        ('REOPENED', 'NEW', 'UPSTREAM', 'DEFERRED', BugTaskStatus.CONFIRMED),
        ('UNCONFIRMED', BugTaskStatus.NEW),
        )

    def convertRemoteStatus(self, remote_status):
        """See `IExternalBugTracker`.

        Bugzilla status consist of two parts separated by space, where
        the last part is the resolution. The resolution is optional.
        """
        try:
            return self._status_lookup.find(*remote_status.split())
        except KeyError:
            raise UnknownRemoteStatusError(remote_status)

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


class BugzillaLPPlugin(Bugzilla):
    """An `ExternalBugTracker` to handle BugZillas using the LP Plugin."""

    implements(ISupportsCommentImport)

    def __init__(self, baseurl, xmlrpc_transport=None):
        super(BugzillaLPPlugin, self).__init__(baseurl)

        if xmlrpc_transport is None:
            xmlrpc_transport = BugzillaXMLRPCTransport()
        else:
            self.xmlrpc_transport = xmlrpc_transport

        self.xmlrpc_endpoint = urlappend(self.baseurl, 'xmlrpc.cgi')

    def initializeRemoteBugDB(self, bug_ids):
        """See `IExternalBugTracker`."""
        self.bugs = {}
        self.bug_aliases = {}

        server = xmlrpclib.ServerProxy(
            self.xmlrpc_endpoint, transport=self.xmlrpc_transport)

        # First, grab the bugs from the remote server.
        request_args = {
            'ids': bug_ids,
            'permissive': True,
            }
        response_dict = server.Bug.get_bugs(request_args)
        remote_bugs = response_dict['bugs']

        # Now copy them into the local bugs dict.
        for remote_bug in remote_bugs:
            self.bugs[remote_bug['id']] = remote_bug

            # The bug_aliases dict is a mapping between aliases and bug
            # IDs. We use the aliases dict to look up the correct ID for
            # a bug. This allows us to reference a bug by either ID or
            # alias.
            if remote_bug['alias'] and remote_bug['alias'] in bug_ids:
                self.bug_aliases[remote_bug['alias']] = remote_bug['id']

    def getCurrentDBTime(self):
        """See `IExternalBugTracker`."""
        server = xmlrpclib.ServerProxy(
            self.xmlrpc_endpoint, transport=self.xmlrpc_transport)

        time_dict = server.Launchpad.time()

        # Return the UTC time sent by the server so that we don't have
        # to care about timezones.
        server_timestamp = time.mktime(
            time.strptime(
                str(time_dict['utc_time']), '%Y%m%dT%H:%M:%S'))

        server_utc_time = datetime.utcfromtimestamp(server_timestamp)
        return server_utc_time.replace(tzinfo=pytz.timezone('UTC'))

    def _getActualBugId(self, bug_id):
        """Return the actual bug id for an alias or id."""
        # See if bug_id is actually an alias.
        actual_bug_id = self.bug_aliases.get(bug_id)

        # bug_id isn't an alias, so try turning it into an int and
        # looking the bug up by ID.
        if actual_bug_id is None:
            try:
                return int(bug_id)
            except ValueError:
                # If bug_id can't be int()'d then it's likely an alias
                # that doesn't exist, so raise BugNotFound.
                raise BugNotFound(bug_id)

    def getRemoteStatus(self, bug_id):
        """See `IExternalBugTracker`."""
        actual_bug_id = self._getActualBugId(bug_id)

        try:
            status = self.bugs[actual_bug_id]['status']
            resolution = self.bugs[actual_bug_id]['resolution']

            if resolution != '' and resolution is not None:
                return "%s %s" % (status, resolution)
            else:
                return status

        except KeyError:
            raise BugNotFound(bug_id)

    def getCommentIds(self, bug_watch):
        """See `ISupportsCommentImport`."""
        actual_bug_id = self._getActualBugId(bug_watch.remotebug)

        # Check that the bug exists, first.
        if actual_bug_id not in self.bugs:
            raise BugNotFound(bug_watch.remotebug)

        server = xmlrpclib.ServerProxy(
            self.xmlrpc_endpoint, transport=self.xmlrpc_transport)

        # Get only the remote comment IDs and store them in the
        # 'comments' field of the bug.
        request_params = {
            'bug_ids': [actual_bug_id],
            'include': ['id'],
            }
        bug_comments_dict = server.Bug.comments(request_params)

        bug_comments = bug_comments_dict['bugs'][actual_bug_id]
        return [comment['id'] for comment in bug_comments]

    def fetchComments(self, bug_watch, comment_ids):
        """See `ISupportsCommentImport`."""
        actual_bug_id = self._getActualBugId(bug_watch.remotebug)

        # Complain if the bug doesn't exist.
        if actual_bug_id not in self.bugs:
            raise BugNotFound(bug_watch.remotebug)

        server = xmlrpclib.ServerProxy(
            self.xmlrpc_endpoint, transport=self.xmlrpc_transport)

        # Fetch the comments we want.
        request_params = {
            'bug_ids': [actual_bug_id],
            'ids': comment_ids,
            }
        bug_comments_dict = server.Bug.comments(request_params)
        bug_comments = bug_comments_dict['bugs'][actual_bug_id]

        self.bugs[actual_bug_id]['comments'] = bug_comments


class BugzillaXMLRPCTransport(xmlrpclib.Transport):
    """XML-RPC Transport for Bugzilla bug trackers.

    Sends a cookie header for authentication.
    """

    auth_cookie = None

    def send_host(self, connection, host):
        """Send the host and cookie headers."""
        xmlrpclib.Transport.send_host(self, connection, host)
        if self.auth_cookie is not None:
            connection.putheader('Cookie', self.auth_cookie)
