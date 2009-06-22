# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0401,C0301

__metaclass__ = type

from datetime import datetime, timedelta
from pprint import pformat
import copy
import os
import shutil
import subprocess
import tempfile
import unittest

from bzrlib.transport import get_transport

import pytz
from storm.store import Store

import transaction
from zope.component import getUtility
import zope.event
from zope.interface.verify import verifyClass, verifyObject
from zope.security.proxy import (
    isinstance as zope_isinstance, removeSecurityProxy)

from lp.codehosting.bzrutils import ensure_base
from lp.codehosting.vfs import branch_id_to_path, get_multi_server
from canonical.config import config
# Import the login and logout functions here as it is a much better
# place to import them from in tests.
from canonical.launchpad.webapp.interfaces import ILaunchBag

from lp.testing._login import (
    ANONYMOUS, is_logged_in, login, login_person, logout)
from lp.testing._tales import test_tales

from twisted.python.util import mergeFunctionMetadata


class FakeTime:
    """Provides a controllable implementation of time.time()."""

    def __init__(self, start):
        """Set up the instance.

        :param start: The value that will initially be returned by `now()`.
        """
        self._now = start

    def advance(self, amount):
        """Advance the value that will be returned by `now()` by 'amount'."""
        self._now += amount

    def now(self):
        """Use this bound method instead of time.time in tests."""
        return self._now


class TestCase(unittest.TestCase):
    """Provide Launchpad-specific test facilities."""

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        self._cleanups = []

    def __str__(self):
        """Return the fully qualified Python name of the test.

        Zope uses this method to determine how to print the test in the
        runner. We use the test's id in order to make the test easier to find,
        and also so that modifications to the id will show up. This is
        particularly important with bzrlib-style test multiplication.
        """
        return self.id()

    def _runCleanups(self, result):
        """Run the cleanups that have been added with addCleanup.

        See the docstring for addCleanup for more information.

        Returns True if all cleanups ran without error, False otherwise.
        """
        ok = True
        while self._cleanups:
            function, arguments, keywordArguments = self._cleanups.pop()
            try:
                function(*arguments, **keywordArguments)
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self.__exc_info())
                ok = False
        return ok

    def addCleanup(self, function, *arguments, **keywordArguments):
        """Add a cleanup function to be called before tearDown.

        Functions added with addCleanup will be called in reverse order of
        adding after the test method and before tearDown.

        If a function added with addCleanup raises an exception, the error
        will be recorded as a test error, and the next cleanup will then be
        run.

        Cleanup functions are always called before a test finishes running,
        even if setUp is aborted by an exception.
        """
        self._cleanups.append((function, arguments, keywordArguments))

    def installFixture(self, fixture):
        """Install 'fixture', an object that has a `setUp` and `tearDown`.

        `installFixture` will run 'fixture.setUp' and schedule
        'fixture.tearDown' to be run during the test's tear down (using
        `addCleanup`).

        :param fixture: Any object that has a `setUp` and `tearDown` method.
        """
        fixture.setUp()
        self.addCleanup(fixture.tearDown)

    def assertProvides(self, obj, interface):
        """Assert 'obj' provides 'interface'.

        You should probably be using `assertCorrectlyProvides`.
        """
        self.assertTrue(
            interface.providedBy(obj),
            "%r does not provide %r" % (obj, interface))

    def assertCorrectlyProvides(self, obj, interface):
        """Assert 'obj' may correctly provides 'interface'."""
        self.assertTrue(
            interface.providedBy(obj),
            "%r does not provide %r." % (obj, interface))
        self.assertTrue(
            verifyObject(interface, obj),
            "%r claims to provide %r but does not do so correctly."
            % (obj, interface))

    def assertClassImplements(self, cls, interface):
        """Assert 'cls' may correctly implement 'interface'."""
        self.assertTrue(
            verifyClass(interface, cls),
            "%r does not correctly implement %r." % (cls, interface))

    def assertNotifies(self, event_type, callable_obj, *args, **kwargs):
        """Assert that a callable performs a given notification.

        :param event_type: The type of event that notification is expected
            for.
        :param callable_obj: The callable to call.
        :param *args: The arguments to pass to the callable.
        :param **kwargs: The keyword arguments to pass to the callable.
        :return: (result, event), where result was the return value of the
            callable, and event is the event emitted by the callable.
        """
        result, events = capture_events(callable_obj, *args, **kwargs)
        if len(events) == 0:
            raise AssertionError('No notification was performed.')
        elif len(events) > 1:
            raise AssertionError('Too many (%d) notifications performed.'
                % len(events))
        elif not isinstance(events[0], event_type):
            raise AssertionError('Wrong event type: %r (expected %r).' %
                (events[0], event_type))
        return result, events[0]

    def assertNoNotification(self, callable_obj, *args, **kwargs):
        """Assert that no notifications are generated by the callable.

        :param callable_obj: The callable to call.
        :param *args: The arguments to pass to the callable.
        :param **kwargs: The keyword arguments to pass to the callable.
        """
        result, events = capture_events(callable_obj, *args, **kwargs)
        if len(events) == 1:
            raise AssertionError('An event was generated: %r.' % events[0])
        elif len(events) > 1:
            raise AssertionError('Events were generated: %s.' %
                                 ', '.join([repr(event) for event in events]))
        return result

    def assertSqlAttributeEqualsDate(self, sql_object, attribute_name, date):
        """Fail unless the value of the attribute is equal to the date.

        Use this method to test that date value that may be UTC_NOW is equal
        to another date value. Trickery is required because SQLBuilder truth
        semantics cause UTC_NOW to appear equal to all dates.

        :param sql_object: a security-proxied SQLObject instance.
        :param attribute_name: the name of a database column in the table
            associated to this object.
        :param date: `datetime.datetime` object or `UTC_NOW`.
        """
        # XXX: Aaron Bentley 2008-04-14: Probably does not belong here, but
        # better location not clear. Used primarily for testing ORM objects,
        # which ought to use factory.
        sql_object = removeSecurityProxy(sql_object)
        sql_class = type(sql_object)
        store = Store.of(sql_object)
        found_object = store.find(
            sql_class, **({'id': sql_object.id, attribute_name: date}))
        if found_object is None:
            self.fail(
                "Expected %s to be %s, but it was %s."
                % (attribute_name, date, getattr(sql_object, attribute_name)))

    def assertEqual(self, a, b, message=''):
        """Assert that 'a' equals 'b'."""
        if a == b:
            return
        if message:
            message += '\n'
        self.fail("%snot equal:\na = %s\nb = %s\n"
                  % (message, pformat(a), pformat(b)))

    def assertIsInstance(self, instance, assert_class):
        """Assert that an instance is an instance of assert_class.

        instance and assert_class have the same semantics as the parameters
        to isinstance.
        """
        self.assertTrue(zope_isinstance(instance, assert_class),
            '%r is not an instance of %r' % (instance, assert_class))

    def assertIs(self, expected, observed):
        """Assert that `expected` is the same object as `observed`."""
        self.assertTrue(expected is observed,
                        "%r is not %r" % (expected, observed))

    def assertIsNot(self, expected, observed):
        """Assert that `expected` is not the same object as `observed`."""
        self.assertTrue(expected is not observed,
                        "%r is %r" % (expected, observed))

    def assertIn(self, needle, haystack):
        """Assert that 'needle' is in 'haystack'."""
        self.assertTrue(
            needle in haystack, '%r not in %r' % (needle, haystack))

    def assertNotIn(self, needle, haystack):
        """Assert that 'needle' is not in 'haystack'."""
        self.assertFalse(
            needle in haystack, '%r in %r' % (needle, haystack))

    def assertContentEqual(self, iter1, iter2):
        """Assert that 'iter1' has the same content as 'iter2'."""
        list1 = sorted(iter1)
        list2 = sorted(iter2)
        self.assertEqual(
            list1, list2, '%s != %s' % (pformat(list1), pformat(list2)))

    def assertRaises(self, excClass, callableObj, *args, **kwargs):
        """Assert that a callable raises a particular exception.

        :param excClass: As for the except statement, this may be either an
            exception class, or a tuple of classes.
        :param callableObj: A callable, will be passed ``*args`` and
            ``**kwargs``.

        Returns the exception so that you can examine it.
        """
        try:
            callableObj(*args, **kwargs)
        except excClass, e:
            return e
        else:
            if getattr(excClass, '__name__', None) is not None:
                excName = excClass.__name__
            else:
                # probably a tuple
                excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def assertRaisesWithContent(self, exception, exception_content,
                                func, *args):
        """Check if the given exception is raised with given content.

        If the exception isn't raised or the exception_content doesn't
        match what was raised an AssertionError is raised.
        """
        exception_name = str(exception).split('.')[-1]

        try:
            func(*args)
        except exception, err:
            self.assertEqual(str(err), exception_content)
        else:
            raise AssertionError(
                "'%s' was not raised" % exception_name)

    def assertBetween(self, lower_bound, variable, upper_bound):
        """Assert that 'variable' is strictly between two boundaries."""
        self.assertTrue(
            lower_bound < variable < upper_bound,
            "%r < %r < %r" % (lower_bound, variable, upper_bound))

    def pushConfig(self, section, **kwargs):
        """Push some key-value pairs into a section of the config.

        The config values will be restored during test tearDown.
        """
        name = self.factory.getUniqueString()
        body = '\n'.join(["%s: %s"%(k, v) for k, v in kwargs.iteritems()])
        config.push(name, "\n[%s]\n%s\n" % (section, body))
        self.addCleanup(config.pop, name)

    def run(self, result=None):
        if result is None:
            result = self.defaultTestResult()
        result.startTest(self)
        testMethod = getattr(self, self.__testMethodName)
        try:
            try:
                self.setUp()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self.__exc_info())
                self._runCleanups(result)
                return

            ok = False
            try:
                testMethod()
                ok = True
            except self.failureException:
                result.addFailure(self, self.__exc_info())
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self.__exc_info())

            cleanupsOk = self._runCleanups(result)
            try:
                self.tearDown()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self.__exc_info())
                ok = False
            if ok and cleanupsOk:
                result.addSuccess(self)
        finally:
            result.stopTest(self)

    def setUp(self):
        unittest.TestCase.setUp(self)
        from lp.testing.factory import ObjectFactory
        self.factory = ObjectFactory()


class TestCaseWithFactory(TestCase):

    def setUp(self, user=ANONYMOUS):
        TestCase.setUp(self)
        login(user)
        self.addCleanup(logout)
        from lp.testing.factory import LaunchpadObjectFactory
        self.factory = LaunchpadObjectFactory()
        self.real_bzr_server = False

    def useTempDir(self):
        """Use a temporary directory for this test."""
        tempdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tempdir))
        cwd = os.getcwd()
        os.chdir(tempdir)
        self.addCleanup(lambda: os.chdir(cwd))

    def getUserBrowser(self, url=None):
        """Return a Browser logged in as a fresh user, maybe opened at `url`.
        """
        # Do the import here to avoid issues with import cycles.
        from canonical.launchpad.testing.pages import setupBrowser
        login(ANONYMOUS)
        user = self.factory.makePerson(password='test')
        naked_user = removeSecurityProxy(user)
        email = naked_user.preferredemail.email
        logout()
        browser = setupBrowser(
            auth="Basic %s:test" % str(email))
        if url is not None:
            browser.open(url)
        return browser

    def create_branch_and_tree(self, tree_location='.', product=None,
                               hosted=False, db_branch=None, format=None,
                               **kwargs):
        """Create a database branch, bzr branch and bzr checkout.

        :param tree_location: The path on disk to create the tree at.
        :param product: The product to associate with the branch.
        :param hosted: If True, create in the hosted area.  Otherwise, create
            in the mirrored area.
        :param db_branch: If supplied, the database branch to use.
        :param format: Override the default bzrdir format to create.
        :return: a `Branch` and a workingtree.
        """
        from bzrlib.bzrdir import BzrDir, format_registry
        if format is not None and isinstance(format, basestring):
            format = format_registry.get(format)()
        if db_branch is None:
            if product is None:
                db_branch = self.factory.makeAnyBranch(**kwargs)
            else:
                db_branch = self.factory.makeProductBranch(product, **kwargs)
        if hosted:
            branch_url = db_branch.getPullURL()
        else:
            branch_url = db_branch.warehouse_url
        if self.real_bzr_server:
            transaction.commit()
        transport = get_transport(branch_url)
        if not self.real_bzr_server:
            transport.clone('../..').ensure_base()
            transport.clone('..').ensure_base()
        self.addCleanup(transport.delete_tree, '.')
        bzr_branch = BzrDir.create_branch_convenience(
            branch_url, format=format)
        return db_branch, bzr_branch.create_checkout(
            tree_location, lightweight=True)

    @staticmethod
    def getBranchPath(branch, base):
        """Return the path of the branch in the mirrored area.

        This always uses the configured mirrored area, ignoring whatever
        server might be providing lp-mirrored: urls.
        """
        # XXX gary 2009-5-28 bug 381325
        # This is a work-around for some failures on PQM, arguably caused by
        # relying on test set-up that is happening in the Makefile rather than
        # the actual test set-up.
        ensure_base(get_transport(base))
        return os.path.join(base, branch_id_to_path(branch.id))

    def createMirroredBranchAndTree(self):
        """Create a database branch, bzr branch and bzr checkout.

        This always uses the configured mirrored area, ignoring whatever
        server might be providing lp-mirrored: urls.

        Unlike normal codehosting operation, the working tree is stored in the
        branch directory.

        The branch and tree files are automatically deleted at the end of the
        test.

        :return: a `Branch` and a workingtree.
        """
        from bzrlib.bzrdir import BzrDir
        db_branch = self.factory.makeAnyBranch()
        transport = get_transport(
            self.getBranchPath(
                db_branch, config.codehosting.internal_branch_by_id_root))
        # Ensure the parent directories exist so that we can stick a branch
        # in them.
        transport.clone('../../..').ensure_base()
        transport.clone('../..').ensure_base()
        transport.clone('..').ensure_base()
        bzr_branch = BzrDir.create_branch_convenience(
            transport.base, possible_transports=[transport])
        self.addCleanup(lambda: transport.delete_tree('.'))
        return db_branch, bzr_branch.bzrdir.open_workingtree()

    def useTempBzrHome(self):
        self.useTempDir()
        # Avoid leaking local user configuration into tests.
        old_bzr_home = os.environ.get('BZR_HOME')
        def restore_bzr_home():
            if old_bzr_home is None:
                del os.environ['BZR_HOME']
            else:
                os.environ['BZR_HOME'] = old_bzr_home
        os.environ['BZR_HOME'] = os.getcwd()
        self.addCleanup(restore_bzr_home)

    def useBzrBranches(self, real_server=False):
        """Prepare for using bzr branches.

        This sets up support for lp-hosted and lp-mirrored URLs,
        changes to a temp directory, and overrides the bzr home directory.

        :param real_server: If true, use the "real" code hosting server,
            using an xmlrpc server, etc.
        """
        from lp.codehosting.scanner.tests.test_bzrsync import (
            FakeTransportServer)
        self.useTempBzrHome()
        self.real_bzr_server = real_server
        if real_server:
            server = get_multi_server(write_hosted=True, write_mirrored=True)
            server.setUp()
            self.addCleanup(server.destroy)
        else:
            os.mkdir('lp-mirrored')
            mirror_server = FakeTransportServer(get_transport('lp-mirrored'))
            mirror_server.setUp()
            self.addCleanup(mirror_server.tearDown)
            os.mkdir('lp-hosted')
            hosted_server = FakeTransportServer(
                get_transport('lp-hosted'), url_prefix='lp-hosted:///')
            hosted_server.setUp()
            self.addCleanup(hosted_server.tearDown)


def capture_events(callable_obj, *args, **kwargs):
    """Capture the events emitted by a callable.

    :param callable_obj: The callable to call.
    :param *args: The arguments to pass to the callable.
    :param **kwargs: The keyword arguments to pass to the callable.
    :return: (result, events), where result was the return value of the
        callable, and events are the events emitted by the callable.
    """
    events = []
    def on_notify(event):
        events.append(event)
    old_subscribers = zope.event.subscribers[:]
    try:
        zope.event.subscribers[:] = [on_notify]
        result = callable_obj(*args, **kwargs)
        return result, events
    finally:
        zope.event.subscribers[:] = old_subscribers


def get_lsb_information():
    """Returns a dictionary with the LSB host information.

    Code stolen form /usr/bin/lsb-release
    """
    distinfo = {}
    if os.path.exists('/etc/lsb-release'):
        for line in open('/etc/lsb-release'):
            line = line.strip()
            if not line:
                continue
            # Skip invalid lines
            if not '=' in line:
                continue
            var, arg = line.split('=', 1)
            if var.startswith('DISTRIB_'):
                var = var[8:]
                if arg.startswith('"') and arg.endswith('"'):
                    arg = arg[1:-1]
                distinfo[var] = arg

    return distinfo


def with_anonymous_login(function):
    """Decorate 'function' so that it runs in an anonymous login."""
    def wrapped(*args, **kwargs):
        login(ANONYMOUS)
        try:
            return function(*args, **kwargs)
        finally:
            logout()
    return mergeFunctionMetadata(function, wrapped)


def run_with_login(person, function, *args, **kwargs):
    """Run 'function' with 'person' logged in."""
    current_person = getUtility(ILaunchBag).user
    logout()
    login_person(person)
    try:
        return function(*args, **kwargs)
    finally:
        logout()
        login_person(current_person)


def time_counter(origin=None, delta=timedelta(seconds=5)):
    """A generator for yielding datetime values.

    Each time the generator yields a value, the origin is incremented
    by the delta.

    >>> now = time_counter(datetime(2007, 12, 1), timedelta(days=1))
    >>> now.next()
    datetime.datetime(2007, 12, 1, 0, 0)
    >>> now.next()
    datetime.datetime(2007, 12, 2, 0, 0)
    >>> now.next()
    datetime.datetime(2007, 12, 3, 0, 0)
    """
    if origin is None:
        origin = datetime.now(pytz.UTC)
    now = origin
    while True:
        yield now
        now += delta


def run_script(cmd_line):
    """Run the given command line as a subprocess.

    Return a 3-tuple containing stdout, stderr and the process' return code.

    The environment given to the subprocess is the same as the one in the
    parent process except for the PYTHONPATH, which is removed so that the
    script, passed as the `cmd_line` parameter, will fail if it doesn't set it
    up properly.
    """
    env = copy.copy(os.environ)
    env.pop('PYTHONPATH', None)
    process = subprocess.Popen(
        cmd_line, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env)
    (out, err) = process.communicate()
    return out, err, process.returncode
