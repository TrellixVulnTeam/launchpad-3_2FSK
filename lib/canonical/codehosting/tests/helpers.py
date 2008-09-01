# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Common helpers for codehosting tests."""

__metaclass__ = type
__all__ = [
    'AvatarTestCase',
    'adapt_suite',
    'BranchTestCase',
    'CodeHostingTestProviderAdapter',
    'CodeHostingRepositoryTestProviderAdapter',
    'create_branch_with_one_revision',
    'deferToThread',
    'FakeLaunchpad',
    'LoomTestMixin',
    'make_bazaar_branch_and_tree',
    'ServerTestCase',
    'TestResultWrapper',
    ]

import os
import threading
import unittest

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import FileExists, PermissionDenied, TransportNotPossible
from bzrlib.plugins.loom import branch as loom_branch
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.errors import SmartProtocolError

from canonical.authserver.interfaces import (
    LAUNCHPAD_SERVICES, PERMISSION_DENIED_FAULT_CODE)
from canonical.codehosting.transport import branch_id_to_path
from canonical.config import config
from canonical.launchpad.interfaces import BranchType
from canonical.testing import TwistedLayer

from twisted.internet import defer, threads
from twisted.python.util import mergeFunctionMetadata
from twisted.trial.unittest import TestCase as TrialTestCase
from twisted.web.xmlrpc import Fault


class AvatarTestCase(TrialTestCase):
    """Base class for tests that need a LaunchpadAvatar with some basic sample
    data.
    """

    layer = TwistedLayer

    def setUp(self):
        # A basic user dict, 'alice' is a member of no teams (aside from the
        # user themself).
        self.aliceUserDict = {
            'id': 1,
            'name': 'alice',
            'teams': [{'id': 1, 'name': 'alice'}],
            'initialBranches': [(1, [])]
        }

        # An slightly more complex user dict for a user, 'bob', who is also a
        # member of a team.
        self.bobUserDict = {
            'id': 2,
            'name': 'bob',
            'teams': [{'id': 2, 'name': 'bob'},
                      {'id': 3, 'name': 'test-team'}],
            'initialBranches': [(2, []), (3, [])]
        }


def exception_names(exceptions):
    """Return a list of exception names for the given exception list."""
    if isinstance(exceptions, tuple):
        names = []
        for exc in exceptions:
            names.extend(exception_names(exc))
    elif exceptions is TransportNotPossible:
        # Unfortunately, not all exceptions render themselves as their name.
        # More cases like this may need to be added
        names = ["Transport operation not possible"]
    elif exceptions is PermissionDenied:
        names = ['Permission denied', 'PermissionDenied']
    else:
        names = [exceptions.__name__]
    return names


class LoomTestMixin:
    """Mixin to provide Bazaar test classes with limited loom support."""

    def loomify(self, branch):
        tree = branch.create_checkout('checkout')
        tree.lock_write()
        try:
            tree.branch.nick = 'bottom-thread'
            loom_branch.loomify(tree.branch)
        finally:
            tree.unlock()
        loom_tree = tree.bzrdir.open_workingtree()
        loom_tree.lock_write()
        loom_tree.branch.new_thread('bottom-thread')
        loom_tree.commit('this is a commit', rev_id='commit-1')
        loom_tree.unlock()
        loom_tree.branch.record_loom('sample loom')
        self.get_transport().delete_tree('checkout')
        return loom_tree

    def makeLoomBranchAndTree(self, tree_directory):
        """Make a looms-enabled branch and working tree."""
        tree = self.make_branch_and_tree(tree_directory)
        tree.lock_write()
        try:
            tree.branch.nick = 'bottom-thread'
            loom_branch.loomify(tree.branch)
        finally:
            tree.unlock()
        loom_tree = tree.bzrdir.open_workingtree()
        loom_tree.lock_write()
        loom_tree.branch.new_thread('bottom-thread')
        loom_tree.commit('this is a commit', rev_id='commit-1')
        loom_tree.unlock()
        loom_tree.branch.record_loom('sample loom')
        return loom_tree


class ServerTestCase(TrialTestCase, TestCaseWithTransport, LoomTestMixin):

    server = None

    def getDefaultServer(self):
        raise NotImplementedError("No default server")

    def installServer(self, server):
        self.server = server

    def setUp(self):
        super(ServerTestCase, self).setUp()

        if self.server is None:
            self.installServer(self.getDefaultServer())

        self.server.setUp()
        self.addCleanup(self.server.tearDown)

    def __str__(self):
        return self.id()

    def assertTransportRaises(self, exception, f, *args, **kwargs):
        """A version of assertRaises() that also catches SmartProtocolError.

        If SmartProtocolError is raised, the error message must
        contain the exception name.  This is to cover Bazaar's
        handling of unexpected errors in the smart server.
        """
        # XXX: JamesHenstridge 2007-10-08 bug=118736
        # This helper should not be needed, but some of the exceptions
        # we raise (such as PermissionDenied) are not yet handled by
        # the smart server protocol as of bzr-0.91.
        names = exception_names(exception)
        try:
            f(*args, **kwargs)
        except SmartProtocolError, inst:
            for name in names:
                if name in str(inst):
                    break
            else:
                raise self.failureException("%s not raised" % names)
            return inst
        except exception, inst:
            return inst
        else:
            raise self.failureException("%s not raised" % names)

    def getTransport(self, relpath=None):
        return self.server.getTransport(relpath)


def deferToThread(f):
    """Run the given callable in a separate thread and return a Deferred which
    fires when the function completes.
    """
    def decorated(*args, **kwargs):
        d = defer.Deferred()
        def runInThread():
            return threads._putResultInDeferred(d, f, args, kwargs)

        t = threading.Thread(target=runInThread)
        t.start()
        return d
    return mergeFunctionMetadata(f, decorated)


class FakeLaunchpad:
    """Stub RPC interface to Launchpad.

    If the 'failing_branch_name' attribute is set and createBranch() is called
    with its value for the branch_name parameter, a Fault will be raised with
    code and message taken from the 'failing_branch_code' and
    'failing_branch_string' attributes respectively.
    """

    failing_branch_name = None
    failing_branch_code = None
    failing_branch_string = None

    def __init__(self):
        self._person_set = {
            1: dict(name='testuser', displayname='Test User',
                    emailaddresses=['spiv@test.com'], wikiname='TestUser',
                    teams=[1, 2]),
            2: dict(name='testteam', displayname='Test Team', teams=[]),
            3: dict(name='name12', displayname='Other User',
                    emailaddresses=['test@test.com'], wikiname='OtherUser',
                    teams=[3]),
            }
        self._product_set = {
            1: dict(name='firefox'),
            2: dict(name='thunderbird'),
            }
        self._branch_set = {}
        self.createBranch(None, 'testuser', 'firefox', 'baz')
        self.createBranch(None, 'testuser', 'firefox', 'qux')
        self.createBranch(None, 'testuser', '+junk', 'random')
        self.createBranch(None, 'testteam', 'firefox', 'qux')
        self.createBranch(None, 'name12', '+junk', 'junk.dev')
        self._request_mirror_log = []

    def _lookup(self, item_set, item_id):
        row = dict(item_set[item_id])
        row['id'] = item_id
        return row

    def _insert(self, item_set, item_dict):
        new_id = max(item_set.keys() + [0]) + 1
        item_set[new_id] = item_dict
        return new_id

    def getDefaultStackedOnBranch(self, login_id, product_name):
        if product_name == '+junk':
            return ''
        elif product_name == 'evolution':
            # This has to match the sample data. :(
            return '/~vcs-imports/evolution/main'
        elif product_name == 'firefox':
            return ''
        else:
            raise ValueError(
                "The crappy mock authserver doesn't know how to translate: %r"
                % (product_name,))

    def createBranch(self, login_id, user, product, branch_name):
        """See `IHostedBranchStorage.createBranch`.

        Also see the description of 'failing_branch_name' in the class
        docstring.
        """
        if self.failing_branch_name == branch_name:
            raise Fault(self.failing_branch_code, self.failing_branch_string)
        user_id = None
        for id, user_info in self._person_set.iteritems():
            if user_info['name'] == user:
                user_id = id
        if user_id is None:
            return ''
        product_id = self.fetchProductID(product)
        if product_id is None:
            return ''
        user = self.getUser(user_id)
        if product_id == '' and 'team' in user['name']:
            raise Fault(PERMISSION_DENIED_FAULT_CODE,
                        'Cannot create team-owned +junk branches.')
        new_branch = dict(
            name=branch_name, user_id=user_id, product_id=product_id)
        for branch in self._branch_set.values():
            if branch == new_branch:
                raise ValueError("Already have branch: %r" % (new_branch,))
        return self._insert(self._branch_set, new_branch)

    def fetchProductID(self, name):
        """See IHostedBranchStorage.fetchProductID."""
        if name == '+junk':
            return ''
        for product_id, product_info in self._product_set.iteritems():
            if product_info['name'] == name:
                return product_id
        return None

    def getBranchInformation(self, login_id, user_name, product_name,
                             branch_name):
        for branch_id, branch in self._branch_set.iteritems():
            owner = self._lookup(self._person_set, branch['user_id'])
            if branch['product_id'] == '':
                product = '+junk'
            else:
                product = self._product_set[branch['product_id']]['name']
            if ((owner['name'], product, branch['name'])
                == (user_name, product_name, branch_name)):
                if login_id == LAUNCHPAD_SERVICES:
                    return branch_id, 'r'
                logged_in_user = self._lookup(self._person_set, login_id)
                if owner['id'] in logged_in_user['teams']:
                    return branch_id, 'w'
                else:
                    return branch_id, 'r'
        return '', ''

    def getUser(self, loginID):
        """See IUserDetailsStorage.getUser."""
        matching_user_id = None
        for user_id, user_dict in self._person_set.iteritems():
            loginIDs = [user_id, user_dict['name']]
            loginIDs.extend(user_dict.get('emailaddresses', []))
            if loginID in loginIDs:
                matching_user_id = user_id
                break
        if matching_user_id is None:
            return ''
        user_dict = self._lookup(self._person_set, matching_user_id)
        user_dict['teams'] = [
            self._lookup(self._person_set, id) for id in user_dict['teams']]
        return user_dict

    def getBranchesForUser(self, personID):
        """See IHostedBranchStorage.getBranchesForUser."""
        product_branches = {}
        for branch_id, branch in self._branch_set.iteritems():
            if branch['user_id'] != personID:
                continue
            product_branches.setdefault(
                branch['product_id'], []).append((branch_id, branch['name']))
        result = []
        for product, branches in product_branches.iteritems():
            if product == '':
                result.append(('', '', branches))
            else:
                result.append(
                    (product, self._product_set[product]['name'], branches))
        return result

    def requestMirror(self, loginID, branchID):
        self._request_mirror_log.append((loginID, branchID))


def clone_test(test, new_id):
    """Return a clone of the given test."""
    from copy import deepcopy
    new_test = deepcopy(test)
    def make_new_test_id():
        return lambda: new_id
    new_test.id = make_new_test_id()
    return new_test


class CodeHostingTestProviderAdapter:
    """Test adapter to run a single test against many codehosting servers."""

    def __init__(self, servers):
        self._servers = servers

    def adaptForServer(self, test, serverFactory):
        server = serverFactory()
        new_test = clone_test(test, '%s(%s)' % (test.id(), server._schema))
        new_test.installServer(server)
        return new_test

    def adapt(self, test):
        result = unittest.TestSuite()
        for server in self._servers:
            new_test = self.adaptForServer(test, server)
            result.addTest(new_test)
        return result


def make_bazaar_branch_and_tree(db_branch):
    """Make a dummy Bazaar branch and working tree from a database Branch."""
    assert db_branch.branch_type == BranchType.HOSTED, (
        "Can only create branches for HOSTED branches: %r"
        % db_branch)
    branch_dir = os.path.join(
        config.codehosting.branches_root, branch_id_to_path(db_branch.id))
    return create_branch_with_one_revision(branch_dir)


def adapt_suite(adapter, base_suite):
    from bzrlib.tests import iter_suite_tests
    suite = unittest.TestSuite()
    for test in iter_suite_tests(base_suite):
        suite.addTests(adapter.adapt(test))
    return suite


def create_branch_with_one_revision(branch_dir):
    """Create a dummy Bazaar branch at the given directory."""
    if not os.path.exists(branch_dir):
        os.makedirs(branch_dir)
    try:
        tree = BzrDir.create_standalone_workingtree(branch_dir)
    except FileExists:
        return
    f = open(os.path.join(branch_dir, 'hello'), 'w')
    f.write('foo')
    f.close()
    tree.commit('message')
    return tree


class TestResultWrapper:
    """A wrapper for `TestResult` that knows about bzrlib's `TestSkipped`."""

    def __init__(self, result):
        self.result = result

    def addError(self, test_case, exc_info):
        if not isinstance(exc_info[1], TestSkipped):
            self.result.addError(test_case, exc_info)

    def addFailure(self, test_case, exc_info):
        self.result.addFailure(test_case, exc_info)

    def addSuccess(self, test_case):
        self.result.addSuccess(test_case)

    def startTest(self, test_case):
        self.result.startTest(test_case)

    def stopTest(self, test_case):
        self.result.stopTest(test_case)
