# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0231

"""Helper classes for testing ExternalSystem."""

__metaclass__ = type

import os
import re
import random
import time
import urlparse
import xmlrpclib

from cStringIO import StringIO
from datetime import datetime, timedelta
from httplib import HTTPMessage

from zope.component import getUtility

from canonical.config import config
from canonical.database.sqlbase import commit, ZopelessTransactionManager
from canonical.launchpad.components.externalbugtracker import (
    BugNotFound, BugTrackerConnectError, Bugzilla, DebBugs,
    ExternalBugTracker, Mantis, RequestTracker, Roundup, SourceForge,
    Trac, TracXMLRPCTransport)
from canonical.launchpad.components.externalbugtracker.bugzilla import (
    BugzillaXMLRPCTransport)
from canonical.launchpad.components.externalbugtracker.trac import (
    LP_PLUGIN_BUG_IDS_ONLY, LP_PLUGIN_FULL,
    LP_PLUGIN_METADATA_AND_COMMENTS, LP_PLUGIN_METADATA_ONLY)
from canonical.launchpad.ftests import login, logout
from canonical.launchpad.interfaces import (
    BugTaskImportance, BugTaskStatus, UNKNOWN_REMOTE_IMPORTANCE,
    UNKNOWN_REMOTE_STATUS)
from canonical.launchpad.database import BugTracker
from canonical.launchpad.interfaces import IBugTrackerSet, IPersonSet
from canonical.launchpad.interfaces.logintoken import ILoginTokenSet
from canonical.launchpad.scripts import debbugs
from canonical.launchpad.testing.systemdocs import ordered_dict_as_string
from canonical.launchpad.xmlrpc import ExternalBugTrackerTokenAPI
from canonical.testing.layers import LaunchpadZopelessLayer


def new_bugtracker(bugtracker_type, base_url='http://bugs.some.where'):
    """Create a new bug tracker using the 'launchpad db user.

    Before calling this function, the current transaction should be
    commited, since the current connection to the database will be
    closed. After returning from this function, a new connection using
    the checkwatches db user is created.
    """
    assert ZopelessTransactionManager._installed is not None, (
        "This function can only be used for Zopeless tests.")
    LaunchpadZopelessLayer.switchDbUser('launchpad')
    owner = getUtility(IPersonSet).getByEmail('no-priv@canonical.com')
    bugtracker_set = getUtility(IBugTrackerSet)
    index = 1
    name = '%s-checkwatches' % (bugtracker_type.name.lower(),)
    while bugtracker_set.getByName("%s-%d" % (name, index)) is not None:
        index += 1
    name += '-%d' % index
    bugtracker = BugTracker(
        name=name,
        title='%s *TESTING*' % (bugtracker_type.title,),
        bugtrackertype=bugtracker_type,
        baseurl=base_url,
        summary='-', contactdetails='-',
        owner=owner)
    commit()
    LaunchpadZopelessLayer.switchDbUser(config.checkwatches.dbuser)
    return getUtility(IBugTrackerSet).getByName(name)


def read_test_file(name):
    """Return the contents of the test file named :name:

    Test files are located in lib/canonical/launchpad/ftests/testfiles
    """
    file_path = os.path.join(os.path.dirname(__file__), 'testfiles', name)

    test_file = open(file_path, 'r')
    return test_file.read()


def print_bugwatches(bug_watches, convert_remote_status=None):
    """Print the bug watches for a BugTracker, ordered by remote bug id.

    :bug_watches: A set of BugWatches to print.

    :convert_remote_status: A convertRemoteStatus method from an
        ExternalBugTracker instance, which will convert a bug's remote
        status into a Launchpad BugTaskStatus. See
        `ExternalBugTracker.convertRemoteStatus()`.

    Bug watches will be printed in the form: Remote bug <id>:
    <remote_status>. If convert_remote_status is callable it will be
    used to convert the watches' remote statuses to Launchpad
    BugTaskStatuses and these will be output instead.
    """
    watches = dict((int(bug_watch.remotebug), bug_watch)
        for bug_watch in bug_watches)

    for remote_bug_id in sorted(watches.keys()):
        status = watches[remote_bug_id].remotestatus
        if callable(convert_remote_status):
            status = convert_remote_status(status)

        print 'Remote bug %d: %s' % (remote_bug_id, status)


def convert_python_status(status, resolution):
    """Convert a human readable status and resolution into a Python
    bugtracker status and resolution string.
    """
    status_map = {'open': 1, 'closed': 2, 'pending': 3}
    resolution_map = {
        'None': 'None',
        'accepted': 1,
        'duplicate': 2,
        'fixed': 3,
        'invalid': 4,
        'later': 5,
        'out-of-date': 6,
        'postponed': 7,
        'rejected': 8,
        'remind': 9,
        'wontfix': 10,
        'worksforme': 11
    }

    return "%s:%s" % (status_map[status], resolution_map[resolution])

def set_bugwatch_error_type(bug_watch, error_type):
    """Set the last_error_type field of a bug watch to a given error type."""
    login('test@canonical.com')
    bug_watch.remotestatus = None
    bug_watch.last_error_type = error_type
    bug_watch.updateStatus(UNKNOWN_REMOTE_STATUS, BugTaskStatus.UNKNOWN)
    logout()


class TestExternalBugTracker(ExternalBugTracker):
    """A test version of `ExternalBugTracker`.

    Implements all the methods required of an `IExternalBugTracker`
    implementation, though it doesn't actually do anything.
    """

    def __init__(self, baseurl='http://example.com/'):
        super(TestExternalBugTracker, self).__init__(baseurl)

    def convertRemoteStatus(self, remote_status):
        """Always return UNKNOWN_REMOTE_STATUS.

        This method exists to satisfy the implementation requirements of
        `IExternalBugTracker`.
        """
        return BugTaskStatus.UNKNOWN

    def getRemoteImportance(self, bug_id):
        """Stub implementation."""
        return UNKNOWN_REMOTE_IMPORTANCE

    def convertRemoteImportance(self, remote_importance):
        """Stub implementation."""
        return BugTaskImportance.UNKNOWN

    def getRemoteStatus(self, bug_id):
        """Stub implementation."""
        return UNKNOWN_REMOTE_STATUS


class TestBrokenExternalBugTracker(TestExternalBugTracker):
    """A test version of ExternalBugTracker, designed to break."""

    initialize_remote_bugdb_error = None
    get_remote_status_error = None

    def initializeRemoteBugDB(self, bug_ids):
        """Raise the error specified in initialize_remote_bugdb_error.

        If initialize_remote_bugdb_error is None, None will be returned.
        See `ExternalBugTracker`.
        """
        if self.initialize_remote_bugdb_error:
            # We have to special case BugTrackerConnectError as it takes
            # two non-optional arguments.
            if self.initialize_remote_bugdb_error is BugTrackerConnectError:
                raise self.initialize_remote_bugdb_error(
                    "http://example.com", "Testing")
            else:
                raise self.initialize_remote_bugdb_error("Testing")

    def getRemoteStatus(self, bug_id):
        """Raise the error specified in get_remote_status_error.

        If get_remote_status_error is None, None will be returned.
        See `ExternalBugTracker`.
        """
        if self.get_remote_status_error:
            raise self.get_remote_status_error("Testing")


class TestBugzilla(Bugzilla):
    """Bugzilla ExternalSystem for use in tests.

    It overrides _getPage and _postPage, so that access to a real Bugzilla
    instance isn't needed.
    """
    # We set the batch_query_threshold to zero so that only
    # getRemoteBugBatch() is used to retrieve bugs, since getRemoteBug()
    # calls getRemoteBugBatch() anyway.
    batch_query_threshold = 0
    trace_calls = False

    version_file = 'gnome_bugzilla_version.xml'
    buglist_file = 'gnome_buglist.xml'
    bug_item_file = 'gnome_bug_li_item.xml'

    buglist_page = 'buglist.cgi'
    bug_id_form_element = 'bug_id'

    def __init__(self, baseurl, version=None):
        Bugzilla.__init__(self, baseurl, version=version)
        self.bugzilla_bugs = self._getBugsToTest()

    def getExternalBugTrackerToUse(self):
        # Always return self here since we test this separately.
        return self

    def _getBugsToTest(self):
        """Return a dict with bugs in the form bug_id: (status, resolution)"""
        return {3224: ('RESOLVED', 'FIXED'),
                328430: ('UNCONFIRMED', '')}

    def _readBugItemFile(self):
        """Reads in the file for an individual bug item.

        This method exists really only to allow us to check that the
        file is being used. So what?
        """
        return read_test_file(self.bug_item_file)

    def _getPage(self, page):
        """GET a page.

        Only handles xml.cgi?id=1 so far.
        """
        if self.trace_calls:
            print "CALLED _getPage()"
        if page == 'xml.cgi?id=1':
            data = read_test_file(self.version_file)
            # Add some latin1 to test bug 61129
            return data % dict(non_ascii_latin1="\xe9")
        else:
            raise AssertionError('Unknown page: %s' % page)

    def _postPage(self, page, form):
        """POST to the specified page.

        :form: is a dict of form variables being POSTed.

        Only handles buglist.cgi so far.
        """
        if self.trace_calls:
            print "CALLED _postPage()"
        if page == self.buglist_page:
            buglist_xml = read_test_file(self.buglist_file)
            bug_ids = str(form[self.bug_id_form_element]).split(',')
            bug_li_items = []
            status_tag = None
            for bug_id in bug_ids:
                bug_id = int(bug_id)
                if bug_id not in self.bugzilla_bugs:
                    #Unknown bugs aren't included in the resulting xml.
                    continue
                bug_status, bug_resolution = self.bugzilla_bugs[int(bug_id)]
                bug_item = self._readBugItemFile() % {
                    'bug_id': bug_id,
                    'status': bug_status,
                    'resolution': bug_resolution,
                    }
                bug_li_items.append(bug_item)
            return buglist_xml % {
                'bug_li_items': '\n'.join(bug_li_items),
                'page': page
            }
        else:
            raise AssertionError('Unknown page: %s' % page)


class TestWeirdBugzilla(TestBugzilla):
    """Test support for a few corner cases in Bugzilla.

        - UTF8 data in the files being parsed.
        - bz:status instead of bz:bug_status
    """
    bug_item_file = 'weird_non_ascii_bug_li_item.xml'

    def _getBugsToTest(self):
        return {2000: ('ASSIGNED', ''),
                123543: ('RESOLVED', 'FIXED')}


class TestBrokenBugzilla(TestBugzilla):
    """Test parsing of a Bugzilla which returns broken XML."""
    bug_item_file = 'broken_bug_li_item.xml'

    def _getBugsToTest(self):
        return {42: ('ASSIGNED', ''),
                2000: ('RESOLVED', 'FIXED')}


class TestIssuezilla(TestBugzilla):
    """Test support for Issuezilla, with slightly modified XML."""
    version_file = 'issuezilla_version.xml'
    buglist_file = 'issuezilla_buglist.xml'
    bug_item_file = 'issuezilla_item.xml'

    buglist_page = 'xml.cgi'
    bug_id_form_element = 'id'

    def _getBugsToTest(self):
        return {2000: ('RESOLVED', 'FIXED'),
                123543: ('ASSIGNED', '')}


class TestOldBugzilla(TestBugzilla):
    """Test support for older Bugzilla versions."""
    version_file = 'ximian_bugzilla_version.xml'
    buglist_file = 'ximian_buglist.xml'
    bug_item_file = 'ximian_bug_item.xml'

    buglist_page = 'xml.cgi'
    bug_id_form_element = 'id'

    def _getBugsToTest(self):
        return {42: ('RESOLVED', 'FIXED'),
                123543: ('ASSIGNED', '')}


class FakeHTTPConnection:
    """A fake HTTP connection."""
    def putheader(self, header, value):
        print "%s: %s" % (header, value)


class TestBugzillaXMLRPCTransport(BugzillaXMLRPCTransport):
    """A test implementation of the Bugzilla XML-RPC interface."""

    local_datetime = None
    timezone = 'UTC'
    utc_offset = 0
    print_method_calls = False

    bugs = {
        1: {'alias': '',
            'assigned_to': 'test@canonical.com',
            'component': 'GPPSystems',
            'creation_time': datetime(2008, 6, 10, 16, 19, 53),
            'id': 1,
            'internals': {},
            'is_open': True,
            'last_change_time': datetime(2008, 6, 10, 16, 19, 53),
            'priority': 'P1',
            'product': 'HeartOfGold',
            'resolution': 'FIXED',
            'severity': 'normal',
            'status': 'RESOLVED',
            'summary': "That bloody robot still exists.",
            },
        2: {'alias': 'bug-two',
            'assigned_to': 'marvin@heartofgold.ship',
            'component': 'Crew',
            'creation_time': datetime(2008, 6, 11, 9, 23, 12),
            'id': 2,
            'internals': {},
            'is_open': True,
            'last_change_time': datetime(2008, 6, 11, 9, 24, 29),
            'priority': 'P1',
            'product': 'HeartOfGold',
            'resolution': '',
            'severity': 'high',
            'status': 'NEW',
            'summary': 'Collect unknown persons in docking bay 2.',
            },
        }

    # Map aliases onto bugs.
    bug_aliases = {
        'bug-two': 2,
        }

    # Comments are mapped to bug IDs.
    comment_id_index = 4
    new_comment_time = datetime(2008, 6, 20, 11, 42, 42)
    bug_comments = {
        1: {
            1: {'author': 'trillian',
                'id': 1,
                'number': 1,
                'text': "I'd really appreciate it if Marvin would "
                        "enjoy life a bit.",
                'time': datetime(2008, 6, 16, 12, 44, 29),
                },
            2: {'author': 'marvin',
                'id': 3,
                'number': 2,
                'text': "Life? Don't talk to me about life.",
                'time': datetime(2008, 6, 16, 13, 22, 29),
                },
            },
        2: {
            1: {'author': 'trillian',
                'id': 2,
                'number': 1,
                'text': "Bring the passengers to the bridge please Marvin.",
                'time': datetime(2008, 6, 16, 13, 8, 8),
                },
             2: {'author': 'Ford Prefect <ford.prefect@h2g2.com>',
                'id': 4,
                'number': 2,
                'text': "I appear to have become a perfectly safe penguin.",
                'time': datetime(2008, 6, 17, 20, 28, 40),
                },
            },
        }

    # Map namespaces onto method names.
    methods = {
        'Bug': ['add_comment', 'comments', 'get_bugs'],
        'Launchpad': ['login', 'time'],
        'Test': ['login_required']
        }

    # Methods that require authentication.
    auth_required_methods = [
        'add_comment',
        'login_required',
        ]

    expired_cookie = None

    def expireCookie(self, cookie):
        """Mark the cookie as expired."""
        self.expired_cookie = cookie

    def request(self, host, handler, request, verbose=None):
        """Call the corresponding XML-RPC method.

        The method name and arguments are extracted from `request`. The
        method on this class with the same name as the XML-RPC method is
        called, with the extracted arguments passed on to it.
        """
        args, method_name = xmlrpclib.loads(request)
        method_prefix, method_name = method_name.split('.')

        assert method_prefix in self.methods, (
            "All methods should be in one of the following namespaces: %s"
            % self.methods.keys())

        assert method_name in self.methods[method_prefix], (
            "No method '%s' in namespace '%s'." %
            (method_name, method_prefix))

        # If the method requires authentication and we have no auth
        # cookie, throw a Fault.
        if (method_name in self.auth_required_methods and
            (self.auth_cookie is None or
             self.auth_cookie == self.expired_cookie)):
            raise xmlrpclib.Fault(410, 'Login Required')

        if self.print_method_calls:
            if len(args) > 0:
                arguments = ordered_dict_as_string(args[0])
            else:
                arguments = ''

            print "CALLED %s.%s(%s)" % (method_prefix, method_name, arguments)

        method = getattr(self, method_name)
        return method(*args)

    def time(self):
        """Return a dict of the local time, UTC time and the timezone."""
        local_datetime = self.local_datetime
        if local_datetime is None:
            local_datetime = datetime(2008, 5, 1, 1, 1, 1)

        # We return xmlrpc dateTimes rather than doubles since that's
        # what BugZilla will return.
        local_time = xmlrpclib.DateTime(local_datetime.timetuple())

        utc_date_time = local_datetime - timedelta(seconds=self.utc_offset)
        utc_time = xmlrpclib.DateTime(utc_date_time.timetuple())
        return {
            'local_time': local_time,
            'utc_time': utc_time,
            'tz_name': self.timezone,
            }

    def login_required(self):
        # This method only exists to demonstrate login required methods.
        return "Wonderful, you've logged in! Aren't you a clever biped?"

    def _consumeLoginToken(self, token_text):
        """Try to consume a login token."""
        token = getUtility(ILoginTokenSet)[token_text]

        if token.tokentype.name != 'BUGTRACKER':
            raise AssertionError(
                'Invalid token type: %s' % token.tokentype.name)
        if token.date_consumed is not None:
            raise AssertionError("Token has already been consumed.")
        token.consume()

        if self.print_method_calls:
            print "Successfully validated the token."

    def _handleLoginToken(self, token_text):
        """A wrapper around _consumeLoginToken().

        We can override this method when we need to do things Zopelessly.
        """
        self._consumeLoginToken(token_text)

    def login(self, arguments):
        token_text = arguments['token']

        self._handleLoginToken(token_text)

        # Generate some random cookies to use.
        random_cookie_1 = str(random.random())
        random_cookie_2 = str(random.random())

        # Reset the headers so that we don't end up with long strings of
        # repeating cookies.
        self.last_response_headers = HTTPMessage(StringIO())

        self.last_response_headers.addheader(
            'set-cookie', 'Bugzilla_login=%s;' % random_cookie_1)
        self.last_response_headers.addheader(
            'set-cookie', 'Bugzilla_logincookie=%s;' % random_cookie_2)

        # We always return the same user ID.
        # This has to be listified because xmlrpclib tries to expand
        # sequences of length 1.
        return [{'user_id': 42}]

    def get_bugs(self, arguments):
        """Return a list of bug dicts for a given set of bug IDs."""
        bug_ids = arguments['ids']
        bugs_to_return = []
        bugs = dict(self.bugs)

        # We enforce permissiveness, since we'll always call this method
        # with permissive=True in the Real World.
        permissive = arguments.get('permissive', False)
        assert permissive, "get_bugs() must be called with permissive=True"

        for id in bug_ids:
            # If the ID is an int, look up the bug directly. We copy the
            # bug dict into a local variable so we can manipulate the
            # data in it.
            try:
                id = int(id)
                bug_dict = dict(self.bugs[int(id)])
            except ValueError:
                bug_dict = dict(self.bugs[self.bug_aliases[id]])

            # Update the DateTime fields of the bug dict so that they
            # look like ones that would be sent over XML-RPC.
            for time_field in ('creation_time', 'last_change_time'):
                datetime_value = bug_dict[time_field]
                timestamp = time.mktime(datetime_value.timetuple())
                xmlrpc_datetime = xmlrpclib.DateTime(timestamp)
                bug_dict[time_field] = xmlrpc_datetime

            bugs_to_return.append(bug_dict)

        # "Why are you returning a list here?" I hear you cry. Well,
        # dear reader, it's because xmlrpclib:1387 tries to expand
        # sequences of length 1. When you return a dict, that line
        # explodes in your face. Annoying? Insane? You bet.
        return [{'bugs': bugs_to_return}]

    def comments(self, arguments):
        """Return comments for a given set of bugs."""
        # We'll always pass bug IDs when we call comments().
        assert 'bug_ids' in arguments, (
            "Bug.comments() must always be called with a bug_ids parameter.")

        bug_ids = arguments['bug_ids']
        comment_ids = arguments.get('ids')
        fields_to_return = arguments.get('include')
        comments_by_bug_id = {}

        def copy_comment(comment):
            # Copy wanted fields.
            comment = dict(
                (key, value) for (key, value) in comment.iteritems()
                if fields_to_return is None or key in fields_to_return)
            # Replace the time field with an XML-RPC DateTime.
            if 'time' in comment:
                comment['time'] = xmlrpclib.DateTime(
                    comment['time'].timetuple())
            return comment

        for bug_id in bug_ids:
            comments_for_bug = self.bug_comments[bug_id].values()
            comments_by_bug_id[bug_id] = [
                copy_comment(comment) for comment in comments_for_bug
                if comment_ids is None or comment['id'] in comment_ids]

        # More xmlrpclib:1387 odd-knobbery avoidance.
        return [{'bugs': comments_by_bug_id}]

    def add_comment(self, arguments):
        """Add a comment to a bug."""
        assert 'id' in arguments, (
            "Bug.add_comment() must always be called with an id parameter.")
        assert 'comment' in arguments, (
            "Bug.add_comment() must always be called with an comment "
            "parameter.")

        bug_id = arguments['id']
        comment = arguments['comment']

        # If the bug doesn't exist, raise a fault.
        if int(bug_id) not in self.bugs:
            raise xmlrpclib.Fault(101, "Bug #%s does not exist." % bug_id)

        # If we don't have comments for the bug already, create an empty
        # comment dict.
        if bug_id not in self.bug_comments:
            self.bug_comments[bug_id] = {}

        # Work out the number for the new comment on that bug.
        if len(self.bug_comments[bug_id]) == 0:
            comment_number = 1
        else:
            comment_numbers = sorted(self.bug_comments[bug_id].keys())
            latest_comment_number = comment_numbers[-1]
            comment_number = latest_comment_number + 1

        # Add the comment to the bug.
        comment_id = self.comment_id_index + 1
        comment_dict = {
            'author': 'launchpad',
            'id': comment_id,
            'number': comment_number,
            'time': self.new_comment_time,
            'text': comment,
            }
        self.bug_comments[bug_id][comment_number] = comment_dict

        self.comment_id_index = comment_id

        # We have to return a list here because xmlrpclib will try to
        # expand sequences of length 1. Trying to do that on a dict will
        # cause it to explode.
        return [{'comment_id': comment_id}]


class TestMantis(Mantis):
    """Mantis ExternalSystem for use in tests.

    It overrides _getPage and _postPage, so that access to a real
    Mantis instance isn't needed.
    """

    trace_calls = False

    def _getPage(self, page):
        if self.trace_calls:
            print "CALLED _getPage(%r)" % (page,)
        if page == "csv_export.php":
            return read_test_file('mantis_example_bug_export.csv')
        elif page.startswith('view.php?id='):
            bug_id = page.split('id=')[-1]
            return read_test_file('mantis--demo--bug-%s.html' % bug_id)
        else:
            return ''

    def _postPage(self, page, form):
        if self.trace_calls:
            print "CALLED _postPage(%r, ...)" % (page,)
        return ''

    def cleanCache(self):
        """Clean the csv_data cache."""
        # Remove the self._csv_data_cached_value if it exists.
        try:
            del self._csv_data_cached_value
        except AttributeError:
            pass


class TestTrac(Trac):
    """Trac ExternalBugTracker for testing purposes.

    It overrides urlopen, so that access to a real Trac instance isn't needed,
    and supportsSingleExports so that the tests don't fail due to the lack of
    a network connection. Also, it overrides the default batch_query_threshold
    for the sake of making test data sane.
    """

    # We remove the batch_size limit for the purposes of the tests so
    # that we can test batching and not batching correctly.
    batch_size = None
    batch_query_threshold = 10
    csv_export_file = None
    supports_single_exports = True
    trace_calls = False

    def getExternalBugTrackerToUse(self):
        return self

    def supportsSingleExports(self, bug_ids):
        """See `Trac`."""
        return self.supports_single_exports

    def urlopen(self, url):
        file_path = os.path.join(os.path.dirname(__file__), 'testfiles')

        if self.trace_calls:
            print "CALLED urlopen(%r)" % (url,)

        if self.csv_export_file is not None:
            csv_export_file = self.csv_export_file
        elif re.match('.*/ticket/[0-9]+\?format=csv$', url):
            csv_export_file = 'trac_example_single_ticket_export.csv'
        else:
            csv_export_file = 'trac_example_ticket_export.csv'

        return open(file_path + '/' + csv_export_file, 'r')


class MockTracRemoteBug:
    """A mockup of a remote Trac bug."""

    def __init__(self, id, last_modified=None, status=None, resolution=None,
        comments=None):
        self.id = id
        self.last_modified = last_modified
        self.status = status
        self.resolution = resolution

        if comments is not None:
            self.comments = comments
        else:
            self.comments = []

    def asDict(self):
        """Return the bug's metadata, but not its comments, as a dict."""
        return {
            'id': self.id,
            'status': self.status,
            'resolution': self.resolution,}


class TestInternalXMLRPCTransport:
    """Test XML-RPC Transport for the internal XML-RPC server.

    This transport executes all methods as the 'launchpad' db user, and
    then switches back to the 'checkwatches' user.
    """

    def request(self, host, handler, request, verbose=None):
        args, method_name = xmlrpclib.loads(request)
        method = getattr(self, method_name)
        LaunchpadZopelessLayer.switchDbUser('launchpad')
        result = method(*args)
        LaunchpadZopelessLayer.txn.commit()
        LaunchpadZopelessLayer.switchDbUser(config.checkwatches.dbuser)
        return result

    def newBugTrackerToken(self):
        token_api = ExternalBugTrackerTokenAPI(None, None)
        print "Using XML-RPC to generate token."
        return token_api.newBugTrackerToken()


def strip_trac_comment(comment):
    """Tidy up a comment dict and return it as the Trac LP Plugin would."""
    # bug_info() doesn't return comment users, so we delete them.
    if 'user' in comment:
        del comment['user']

    return comment


class TestTracXMLRPCTransport(TracXMLRPCTransport):
    """An XML-RPC transport to be used when testing Trac."""

    remote_bugs = {}
    seconds_since_epoch = None
    local_timezone = 'UTC'
    utc_offset = 0
    expired_cookie = None

    def expireCookie(self, cookie):
        """Mark the cookie as expired."""
        self.expired_cookie = cookie

    def request(self, host, handler, request, verbose=None):
        """Call the corresponding XML-RPC method.

        The method name and arguments are extracted from `request`. The
        method on this class with the same name as the XML-RPC method is
        called, with the extracted arguments passed on to it.
        """
        assert handler.endswith('/xmlrpc'), (
            'The Trac endpoint must end with /xmlrpc')
        args, method_name = xmlrpclib.loads(request)
        prefix = 'launchpad.'
        assert method_name.startswith(prefix), (
            'All methods should be in the launchpad namespace')
        if (self.auth_cookie is None or
            self.auth_cookie == self.expired_cookie):
            # All the Trac XML-RPC methods need authentication.
            raise xmlrpclib.ProtocolError(
                method_name, errcode=403, errmsg="Forbidden",
                headers=None)

        method_name = method_name[len(prefix):]
        method = getattr(self, method_name)
        return method(*args)

    def bugtracker_version(self):
        """Return the bug tracker version information."""
        return ['0.11.0', '1.0', False]

    def time_snapshot(self):
        """Return the current time."""
        if self.seconds_since_epoch is None:
            local_time = int(time.time())
        else:
            local_time = self.seconds_since_epoch
        utc_time = local_time - self.utc_offset
        return [self.local_timezone, local_time, utc_time]

    @property
    def utc_time(self):
        """Return the current UTC time for this bug tracker."""
        # This is here for the sake of not having to use
        # time_snapshot()[2] all the time, which is a bit opaque.
        return self.time_snapshot()[2]

    def bug_info(self, level, criteria=None):
        """Return info about a bug or set of bugs.

        :param level: The level of detail to return about the bugs
            requested. This can be one of:
            0: Return IDs only.
            1: Return Metadata only.
            2: Return Metadata + comment IDs.
            3: Return all data about each bug.

        :param criteria: The selection criteria by which bugs will be
            returned. Possible keys include:
            modified_since: An integer timestamp. If specified, only
                bugs modified since this timestamp will
                be returned.
            bugs: A list of bug IDs. If specified, only bugs whose IDs are in
                this list will be returned.

        Return a list of [ts, bugs] where ts is a utc timestamp as
        returned by `time_snapshot()` and bugs is a list of bug dicts.
        """
        # XXX 2008-04-12 gmb:
        #     This is only a partial implementation of this; it will
        #     grow over time as implement different methods that call
        #     this method. See bugs 203564, 158703 and 158705.

        # We sort the list of bugs for the sake of testing.
        bug_ids = sorted([bug_id for bug_id in self.remote_bugs.keys()])
        bugs_to_return = []
        missing_bugs = []

        for bug_id in bug_ids:
            bugs_to_return.append(self.remote_bugs[bug_id])

        if criteria is None:
            criteria = {}

        # If we have a modified_since timestamp, we return bugs modified
        # since that time.
        if 'modified_since' in criteria:
            # modified_since is an integer timestamp, so we convert it
            # to a datetime.
            modified_since = datetime.fromtimestamp(
                criteria['modified_since'])

            bugs_to_return = [
                bug for bug in bugs_to_return
                if bug.last_modified > modified_since]

        # If we have a list of bug IDs specified, we only return
        # those members of bugs_to_return that are in that
        # list.
        if 'bugs' in criteria:
            bugs_to_return = [
                bug for bug in bugs_to_return
                if bug.id in criteria['bugs']]

            # We make a separate list of bugs that don't exist so that
            # we can return them with a status of 'missing' later.
            missing_bugs = [
                bug_id for bug_id in criteria['bugs']
                if bug_id not in self.remote_bugs]

        # We only return what's required based on the level parameter.
        # For level 0, only IDs are returned.
        if level == LP_PLUGIN_BUG_IDS_ONLY:
            bugs_to_return = [{'id': bug.id} for bug in bugs_to_return]
        # For level 1, we return the bug's metadata, too.
        elif level == LP_PLUGIN_METADATA_ONLY:
            bugs_to_return = [bug.asDict() for bug in bugs_to_return]
        # At level 2, we also return comment IDs for each bug.
        elif level == LP_PLUGIN_METADATA_AND_COMMENTS:
            bugs_to_return = [
                dict(bug.asDict(), comments=[
                    comment['id'] for comment in bug.comments])
                for bug in bugs_to_return]
        # At level 3, we return the full comment dicts along with the
        # bug metadata. Tne comment dicts do not include the user field,
        # however.
        elif level == LP_PLUGIN_FULL:
            bugs_to_return = [
                dict(bug.asDict(),
                     comments=[strip_trac_comment(dict(comment))
                               for comment in bug.comments])
                for bug in bugs_to_return]

        # Tack the missing bugs onto the end of our list of bugs. These
        # will always be returned in the same way, no matter what the
        # value of the level argument.
        missing_bugs = [
            {'id': bug_id, 'status': 'missing'} for bug_id in missing_bugs]

        return [self.utc_time, bugs_to_return + missing_bugs]

    def get_comments(self, comments):
        """Return a list of comment dicts.

        :param comments: The IDs of the comments to return. Comments
            that don't exist will be returned with a type value of
            'missing'.
        """
        # It's a bit tedious having to loop through all the bugs and
        # their comments like this, but it's easier than creating a
        # horribly complex implementation for the sake of testing.
        comments_to_return = []

        for bug in self.remote_bugs.values():
            for comment in bug.comments:
                if comment['id'] in comments:
                    comments_to_return.append(comment)

        # For each of the missing ones, return a dict with a type of
        # 'missing'.
        comment_ids_to_return = sorted([
            comment['id'] for comment in comments_to_return])
        missing_comments = [
            {'id': comment_id, 'type': 'missing'}
            for comment_id in comments
            if comment_id not in comment_ids_to_return]

        return [self.utc_time, comments_to_return + missing_comments]

    def add_comment(self, bugid, comment):
        """Add a comment to a bug.

        :param bugid: The integer ID of the bug to which the comment
            should be added.
        :param comment: The comment to be added as a string.
        """
        # Calculate the comment ID from the bug's ID and the number of
        # comments against that bug.
        comments = self.remote_bugs[str(bugid)].comments
        comment_id = "%s-%s" % (bugid, len(comments) + 1)

        comment_dict = {
            'comment': comment,
            'id': comment_id,
            'time': self.utc_time,
            'type': 'comment',
            'user': 'launchpad',
            }

        comments.append(comment_dict)

        return [self.utc_time, comment_id]


class TestRoundup(Roundup):
    """Roundup ExternalBugTracker for testing purposes.

    It overrides urlopen, so that access to a real Roundup instance isn't
    needed.
    """

    # We remove the batch_size limit for the purposes of the tests so
    # that we can test batching and not batching correctly.
    batch_size = None
    trace_calls = False

    def urlopen(self, url):
        if self.trace_calls:
            print "CALLED urlopen(%r)" % (url,)

        file_path = os.path.join(os.path.dirname(__file__), 'testfiles')

        if self.isPython():
            return open(
                file_path + '/' + 'python_example_ticket_export.csv', 'r')
        else:
            return open(
                file_path + '/' + 'roundup_example_ticket_export.csv', 'r')


class TestRequestTracker(RequestTracker):
    """A Test-oriented `RequestTracker` implementation.

    Overrides _getPage() and _postPage() so that access to an RT
    instance is not needed.
    """
    trace_calls = False
    simulate_bad_response = False

    def urlopen(self, page, data=None):
        file_path = os.path.join(os.path.dirname(__file__), 'testfiles')
        path = urlparse.urlparse(page)[2].lstrip('/')
        if self.trace_calls:
            print "CALLED urlopen(%r)" % path

        if self.simulate_bad_response:
            return open(file_path + '/' + 'rt-sample-bug-bad.txt')

        if path == self.batch_url:
            return open(file_path + '/' + 'rt-sample-bug-batch.txt')
        else:
            # We extract the ticket ID from the url and use that to find
            # the test file we want.
            page_re = re.compile('REST/1.0/ticket/([0-9]+)/show')
            bug_id = page_re.match(path).groups()[0]

            return open(file_path + '/' + 'rt-sample-bug-%s.txt' % bug_id)


class TestSourceForge(SourceForge):
    """Test-oriented SourceForge ExternalBugTracker.

    Overrides _getPage() so that access to SourceForge itself is not
    required.
    """

    trace_calls = False

    def _getPage(self, page):
        if self.trace_calls:
            print "CALLED _getPage(%r)" % (page,)

        page_re = re.compile('support/tracker.php\?aid=([0-9]+)')
        bug_id = page_re.match(page).groups()[0]

        file_path = os.path.join(
            os.path.dirname(__file__), 'testfiles',
            'sourceforge-sample-bug-%s.html' % bug_id)
        return open(file_path, 'r').read()


class TestDebianBug(debbugs.Bug):
    """A debbugs bug that doesn't require the debbugs db."""

    def __init__(self, reporter_email='foo@example.com', package='evolution',
                 summary='Test Summary', description='Test description.',
                 status='open', severity=None, tags=None, id=None):
        if tags is None:
            tags = []
        self.originator = reporter_email
        self.package = package
        self.subject = summary
        self.description = description
        self.status = status
        self.severity = severity
        self.tags = tags
        self.id = id
        self._emails = []

    def __getattr__(self, name):
        # We redefine this method here to as to avoid some of the
        # behaviour of debbugs.Bug from raising spurious errors during
        # testing.
        return getattr(self, name, None)


class TestDebBugsDB:
    """A debbugs db object that doesn't require access to the debbugs db."""

    def __init__(self):
        self._data_path = os.path.join(os.path.dirname(__file__),
            'testfiles')
        self._data_file = 'debbugs-1-comment.txt'
        self.fail_on_load_log = False

    @property
    def data_file(self):
        return os.path.join(self._data_path, self._data_file)

    def load_log(self, bug):
        """Load the comments for a particular debian bug."""
        if self.fail_on_load_log:
            raise debbugs.LogParseFailed(
                'debbugs-log.pl exited with code 512')

        comment_data = open(self.data_file).read()
        bug._emails = []
        bug.comments = [comment.strip() for comment in
            comment_data.split('--\n')]


class TestDebBugs(DebBugs):
    """A Test-oriented Debbugs ExternalBugTracker.

    It allows you to pass in bugs to be used, instead of relying on an
    existing debbugs db.
    """
    sync_comments = False

    def __init__(self, baseurl, bugs):
        super(TestDebBugs, self).__init__(baseurl)
        self.bugs = bugs
        self.debbugs_db = TestDebBugsDB()

    def _findBug(self, bug_id):
        if bug_id not in self.bugs:
            raise BugNotFound(bug_id)

        bug = self.bugs[bug_id]
        self.debbugs_db.load_log(bug)
        return bug

