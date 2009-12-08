# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# We like global!
# pylint: disable-msg=W0603,W0702

"""Layers used by Canonical tests.

Layers are the mechanism used by the Zope3 test runner to efficiently
provide environments for tests and are documented in the lib/zope/testing.

Note that every Layer should define all of setUp, tearDown, testSetUp
and testTearDown. If you don't do this, a base class' method will be called
instead probably breaking something.

Preferred style is to not use the 'cls' argument to Layer class methods,
as this is unambguious.

TODO: Make the Zope3 test runner handle multiple layers per test instead
of one, forcing us to attempt to make some sort of layer tree.
-- StuartBishop 20060619
"""

__metaclass__ = type
__all__ = [
    'AppServerLayer',
    'BaseLayer',
    'BaseWindmillLayer',
    'DatabaseFunctionalLayer',
    'DatabaseLayer',
    'ExperimentalLaunchpadZopelessLayer',
    'FunctionalLayer',
    'GoogleServiceLayer',
    'LaunchpadFunctionalLayer',
    'LaunchpadLayer',
    'LaunchpadScriptLayer',
    'LaunchpadZopelessLayer',
    'LayerInvariantError',
    'LayerIsolationError',
    'LibrarianLayer',
    'PageTestLayer',
    'TwistedAppServerLayer',
    'TwistedLaunchpadZopelessLayer',
    'TwistedLayer',
    'ZopelessAppServerLayer',
    'ZopelessDatabaseLayer',
    'ZopelessLayer',
    'disconnect_stores',
    'reconnect_stores',
    ]

import atexit
import datetime
import errno
import gc
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

from cProfile import Profile
from textwrap import dedent
from unittest import TestCase, TestResult
from urllib import urlopen

import psycopg2
from storm.zope.interfaces import IZStorm
import transaction
import wsgi_intercept

from windmill.bin.admin_lib import (
    start_windmill, teardown as windmill_teardown)

from zope.app.publication.httpfactory import chooseClasses
import zope.app.testing.functional
import zope.publisher.publish
from zope.app.testing.functional import FunctionalTestSetup, ZopePublication
from zope.component import getUtility, provideUtility
from zope.component.interfaces import ComponentLookupError
from zope.security.management import getSecurityPolicy
from zope.security.simplepolicies import PermissiveSecurityPolicy
from zope.server.logger.pythonlogger import PythonLogger

from canonical.lazr import pidfile
from canonical.config import CanonicalConfig, config, dbconfig
from canonical.database.revision import confirm_dbrevision
from canonical.database.sqlbase import cursor, ZopelessTransactionManager
from canonical.launchpad.interfaces import IMailBox, IOpenLaunchBag
from canonical.launchpad.ftests import ANONYMOUS, login, logout, is_logged_in
import lp.services.mail.stub
from lp.services.mail.mailbox import TestMailBox
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.testing.tests.googleserviceharness import (
    GoogleServiceTestSetup)
from canonical.launchpad.webapp.interfaces import (
        DEFAULT_FLAVOR, IStoreSelector, MAIN_STORE)
from canonical.launchpad.webapp.servers import (
    LaunchpadAccessLogger, register_launchpad_request_publication_factories)
from canonical.lazr.testing.layers import MockRootFolder
from canonical.lazr.timeout import (
    get_default_timeout_function, set_default_timeout_function)
from canonical.lp import initZopeless
from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.testing import reset_logging
from canonical.testing.profiled import profiled
from canonical.testing.smtpd import SMTPController


orig__call__ = zope.app.testing.functional.HTTPCaller.__call__
COMMA = ','
WAIT_INTERVAL = datetime.timedelta(seconds=180)


class LayerError(Exception):
    pass


class LayerInvariantError(LayerError):
    """Layer self checks have detected a fault. Invariant has been violated.

    This indicates the Layer infrastructure has messed up. The test run
    should be aborted.
    """
    pass


class LayerIsolationError(LayerError):
    """Test isolation has been broken, probably by the test we just ran.

    This generally indicates a test has screwed up by not resetting
    something correctly to the default state.

    The test suite should abort if it cannot clean up the mess as further
    test failures may well be spurious.
    """


def is_ca_available():
    """Returns true if the component architecture has been loaded"""
    try:
        getUtility(IOpenLaunchBag)
    except ComponentLookupError:
        return False
    else:
        return True


def disconnect_stores():
    """Disconnect Storm stores."""
    zstorm = getUtility(IZStorm)
    stores = [
        store for name, store in zstorm.iterstores() if name != 'session']

    # If we have any stores, abort the transaction and close them.
    if stores:
        for store in stores:
            zstorm.remove(store)
        transaction.abort()
        for store in stores:
            store.close()


def reconnect_stores(database_config_section='launchpad'):
    """Reconnect Storm stores, resetting the dbconfig to its defaults.

    After reconnecting, the database revision will be checked to make
    sure the right data is available.
    """
    disconnect_stores()
    dbconfig.setConfigSection(database_config_section)

    main_store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
    assert main_store is not None, 'Failed to reconnect'

    # Confirm the database has the right patchlevel
    confirm_dbrevision(cursor())

    # Confirm that SQLOS is again talking to the database (it connects
    # as soon as SQLBase._connection is accessed
    r = main_store.execute('SELECT count(*) FROM LaunchpadDatabaseRevision')
    assert r.get_one()[0] > 0, 'Storm is not talking to the database'

    session_store = getUtility(IZStorm).get('session', 'launchpad-session:')
    assert session_store is not None, 'Failed to reconnect'


def wait_children(seconds=120):
    """Wait for all children to exit.

    :param seconds: Maximum number of seconds to wait.  If None, wait
        forever.
    """
    now = datetime.datetime.now
    if seconds is None:
        until = None
    else:
        until = now() + datetime.timedelta(seconds=seconds)
    while True:
        try:
            os.waitpid(-1, os.WNOHANG)
        except OSError, error:
            if error.errno != errno.ECHILD:
                raise
            break
        if until is not None and now() > until:
            break


class BaseLayer:
    """Base layer.

    All out layers should subclass Base, as this is where we will put
    test isolation checks to ensure that tests to not leave global
    resources in a mess.

    XXX: StuartBishop 2006-07-12: Unit tests (tests with no layer) will not
    get these checks. The Z3 test runner should be updated so that a layer
    can be specified to use for unit tests.
    """
    # Set to True when we are running tests in this layer.
    isSetUp = False

    # The name of this test - this is the same output that the testrunner
    # displays. It is probably unique, but not guaranteed to be so.
    test_name = None

    # A flag to disable a check for threads still running after test
    # completion.  This is hopefully a temporary measure; see the comment
    # in tearTestDown.
    disable_thread_check = False

    @classmethod
    @profiled
    def setUp(cls):
        BaseLayer.isSetUp = True
        # Kill any Librarian left running from a previous test run.
        LibrarianTestSetup().tearDown()
        # Kill any database left lying around from a previous test run.
        try:
            DatabaseLayer.connect().close()
        except psycopg2.Error:
            pass
        else:
            DatabaseLayer._dropDb()

    @classmethod
    @profiled
    def tearDown(cls):
        BaseLayer.isSetUp = False

    @classmethod
    @profiled
    def testSetUp(cls):
        # Store currently running threads so we can detect if a test
        # leaves new threads running.
        BaseLayer._threads = threading.enumerate()
        BaseLayer.check()
        BaseLayer.original_working_directory = os.getcwd()

        # Tests and test infrastruture sometimes needs to know the test
        # name.  The testrunner doesn't provide this, so we have to do
        # some snooping.
        import inspect
        frame = inspect.currentframe()
        try:
            while frame.f_code.co_name != 'startTest':
                frame = frame.f_back
            BaseLayer.test_name = str(frame.f_locals['test'])
        finally:
            del frame # As per no-leak stack inspection in Python reference.

    @classmethod
    @profiled
    def testTearDown(cls):
        # Get our current working directory, handling the case where it no
        # longer exists (!).
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = None

        # Handle a changed working directory. If the test succeeded,
        # add an error. Then restore the working directory so the test
        # run can continue.
        if cwd != BaseLayer.original_working_directory:
            BaseLayer.flagTestIsolationFailure(
                    "Test failed to restore working directory.")
            os.chdir(BaseLayer.original_working_directory)

        BaseLayer.original_working_directory = None
        reset_logging()
        del lp.services.mail.stub.test_emails[:]
        BaseLayer.test_name = None
        BaseLayer.check()

        # Check for tests that leave live threads around early.
        # A live thread may be the cause of other failures, such as
        # uncollectable garbage.
        new_threads = [
            thread for thread in threading.enumerate()
            if thread not in BaseLayer._threads and thread.isAlive()
            ]

        if new_threads:
            # XXX gary 2008-12-03 bug=304913
            # The codehosting acceptance tests are intermittently leaving
            # threads around, apparently because of bzr. disable_thread_check
            # is a mechanism to turn off the BaseLayer behavior of causing a
            # test to fail if it leaves a thread behind. This comment is found
            # in both lp.codehosting.tests.test_acceptance and
            # canonical.testing.layers
            if BaseLayer.disable_thread_check:
                print ("ERROR DISABLED: "
                       "Test left new live threads: %s") % repr(new_threads)
            else:
                BaseLayer.flagTestIsolationFailure(
                    "Test left new live threads: %s" % repr(new_threads))

        BaseLayer.disable_thread_check = False
        del BaseLayer._threads

        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            BaseLayer.flagTestIsolationFailure(
                "Test left SIGCHLD handler.")

        # Objects with __del__ methods cannot participate in refence cycles.
        # Fail tests with memory leaks now rather than when Launchpad crashes
        # due to a leak because someone ignored the warnings.
        if gc.garbage:
            gc.collect() # Expensive, so only do if there might be garbage.
            if gc.garbage:
                BaseLayer.flagTestIsolationFailure(
                        "Test left uncollectable garbage\n"
                        "%s (referenced from %s)"
                        % (gc.garbage, gc.get_referrers(*gc.garbage)))

    @classmethod
    @profiled
    def check(cls):
        """Check that the environment is working as expected.

        We check here so we can detect tests that, for example,
        initialize the Zopeless or Functional environments and
        are using the incorrect layer.
        """
        if FunctionalLayer.isSetUp and ZopelessLayer.isSetUp:
            raise LayerInvariantError(
                "Both Zopefull and Zopeless CA environments setup")

        # Detect a test that causes the component architecture to be loaded.
        # This breaks test isolation, as it cannot be torn down.
        if (is_ca_available()
            and not FunctionalLayer.isSetUp
            and not ZopelessLayer.isSetUp):
            raise LayerIsolationError(
                "Component architecture should not be loaded by tests. "
                "This should only be loaded by the Layer."
                )

        # Detect a test that installed the Zopeless database adapter
        # but failed to unregister it. This could be done automatically,
        # but it is better for the tear down to be explicit.
        if ZopelessTransactionManager._installed is not None:
            raise LayerIsolationError(
                "Zopeless environment was setup and not torn down.")

        # Detect a test that forgot to reset the default socket timeout.
        # This safety belt is cheap and protects us from very nasty
        # intermittent test failures: see bug #140068 for an example.
        if socket.getdefaulttimeout() is not None:
            raise LayerIsolationError(
                "Test didn't reset the socket default timeout.")

    @classmethod
    def flagTestIsolationFailure(cls, message):
        """Handle a breakdown in test isolation.

        If the test that broke isolation thinks it succeeded,
        add an error. If the test failed, don't add a notification
        as the isolation breakdown is probably just fallout.

        The layer that detected the isolation failure still needs to
        repair the damage, or in the worst case abort the test run.
        """
        test_result = BaseLayer.getCurrentTestResult()
        if test_result.wasSuccessful():
            # pylint: disable-msg=W0702
            test_case = BaseLayer.getCurrentTestCase()
            try:
                raise LayerIsolationError(message)
            except:
                test_result.addError(test_case, sys.exc_info())

    @classmethod
    def getCurrentTestResult(cls):
        """Return the TestResult currently in play."""
        import inspect
        frame = inspect.currentframe()
        try:
            while True:
                f_self = frame.f_locals.get('self', None)
                if isinstance(f_self, TestResult):
                    return frame.f_locals['self']
                frame = frame.f_back
        finally:
            del frame # As per no-leak stack inspection in Python reference.

    @classmethod
    def getCurrentTestCase(cls):
        """Return the test currently in play."""
        import inspect
        frame = inspect.currentframe()
        try:
            while True:
                f_self = frame.f_locals.get('self', None)
                if isinstance(f_self, TestCase):
                    return f_self
                f_test = frame.f_locals.get('test', None)
                if isinstance(f_test, TestCase):
                    return f_test
                frame = frame.f_back
            return frame.f_locals['test']
        finally:
            del frame # As per no-leak stack inspection in Python reference.


class LibrarianLayer(BaseLayer):
    """Provides tests access to a Librarian instance.

    Calls to the Librarian will fail unless there is also a Launchpad
    database available.
    """
    _reset_between_tests = True

    @classmethod
    @profiled
    def setUp(cls):
        if not LibrarianLayer._reset_between_tests:
            raise LayerInvariantError(
                    "_reset_between_tests changed before LibrarianLayer "
                    "was actually used."
                    )
        the_librarian = LibrarianTestSetup()
        the_librarian.setUp()
        LibrarianLayer._check_and_reset()
        atexit.register(the_librarian.tearDown)

    @classmethod
    @profiled
    def tearDown(cls):
        if not LibrarianLayer._reset_between_tests:
            raise LayerInvariantError(
                    "_reset_between_tests not reset before LibrarianLayer "
                    "shutdown"
                    )
        LibrarianLayer._check_and_reset()
        LibrarianTestSetup().tearDown()

    @classmethod
    @profiled
    def _check_and_reset(cls):
        """Raise an exception if the Librarian has been killed.
        Reset the storage unless this has been disabled.
        """
        try:
            f = urlopen(config.librarian.download_url)
            f.read()
        except Exception, e:
            raise LayerIsolationError(
                    "Librarian has been killed or has hung."
                    "Tests should use LibrarianLayer.hide() and "
                    "LibrarianLayer.reveal() where possible, and ensure "
                    "the Librarian is restarted if it absolutetly must be "
                    "shutdown: " + str(e)
                    )
        if LibrarianLayer._reset_between_tests:
            LibrarianTestSetup().clear()

    @classmethod
    @profiled
    def testSetUp(cls):
        LibrarianLayer._check_and_reset()

    @classmethod
    @profiled
    def testTearDown(cls):
        if LibrarianLayer._hidden:
            LibrarianLayer.reveal()
        LibrarianLayer._check_and_reset()

    # Flag maintaining state of hide()/reveal() calls
    _hidden = False

    # Fake upload socket used when the librarian is hidden
    _fake_upload_socket = None

    @classmethod
    @profiled
    def hide(cls):
        """Hide the Librarian so nothing can find it. We don't want to
        actually shut it down because starting it up again is expensive.

        We do this by altering the configuration so the Librarian client
        looks for the Librarian server on the wrong port.
        """
        LibrarianLayer._hidden = True
        if LibrarianLayer._fake_upload_socket is None:
            # Bind to a socket, but don't listen to it.  This way we
            # guarantee that connections to the given port will fail.
            LibrarianLayer._fake_upload_socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            assert config.librarian.upload_host == 'localhost', (
                'Can only hide librarian if it is running locally')
            LibrarianLayer._fake_upload_socket.bind(('127.0.0.1', 0))

        host, port = LibrarianLayer._fake_upload_socket.getsockname()
        librarian_data = dedent("""
            [librarian]
            upload_port: %s
            """ % port)
        config.push('hide_librarian', librarian_data)

    @classmethod
    @profiled
    def reveal(cls):
        """Reveal a hidden Librarian.

        This just involves restoring the config to the original value.
        """
        LibrarianLayer._hidden = False
        config.pop('hide_librarian')


# We store a reference to the DB-API connect method here when we
# put a proxy in its place.
_org_connect = None


class DatabaseLayer(BaseLayer):
    """Provides tests access to the Launchpad sample database."""

    # If set to False, database will not be reset between tests. It is
    # your responsibility to set it back to True and call
    # Database.force_dirty_database() when you do so.
    _reset_between_tests = True

    @classmethod
    @profiled
    def setUp(cls):
        DatabaseLayer.force_dirty_database()
        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().tearDown()
        DatabaseLayer._reset_sequences_sql = LaunchpadTestSetup(
            dbname='launchpad_ftest_template').generateResetSequencesSQL()

    @classmethod
    @profiled
    def tearDown(cls):
        # Don't leave the DB lying around or it might break tests
        # that depend on it not being there on startup, such as found
        # in test_layers.py
        DatabaseLayer.force_dirty_database()
        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().tearDown()
        DatabaseLayer._reset_sequences_sql = None

    @classmethod
    @profiled
    def testSetUp(cls):
        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if DatabaseLayer._reset_between_tests:
            LaunchpadTestSetup(
                reset_sequences_sql=DatabaseLayer._reset_sequences_sql
                ).setUp()
        # Ensure that the database is connectable. Because we might have
        # just created it, keep trying for a few seconds incase PostgreSQL
        # is taking its time getting its house in order.
        attempts = 60
        for count in range(0, attempts):
            try:
                DatabaseLayer.connect().close()
            except psycopg2.Error:
                if count == attempts - 1:
                    raise
                time.sleep(0.5)
            else:
                break

        if DatabaseLayer.use_mockdb is True:
            DatabaseLayer.installMockDb()

    @classmethod
    @profiled
    def testTearDown(cls):
        if DatabaseLayer.use_mockdb is True:
            DatabaseLayer.uninstallMockDb()

        # Ensure that the database is connectable
        DatabaseLayer.connect().close()

        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if DatabaseLayer._reset_between_tests:
            LaunchpadTestSetup().tearDown()

        # Fail tests that forget to uninstall their database policies.
        from canonical.launchpad.webapp.adapter import StoreSelector
        while StoreSelector.get_current() is not None:
            BaseLayer.flagTestIsolationFailure(
                "Database policy %s still installed"
                % repr(StoreSelector.pop()))

    use_mockdb = False
    mockdb_mode = None

    @classmethod
    @profiled
    def installMockDb(cls):
        assert DatabaseLayer.mockdb_mode is None, 'mock db already installed'

        from canonical.testing.mockdb import (
                script_filename, ScriptRecorder, ScriptPlayer,
                )

        # We need a unique key for each test to store the mock db script.
        test_key = BaseLayer.test_name
        assert test_key, "Invalid test_key %r" % (test_key,)

        # Determine if we are in replay or record mode and setup our
        # mock db script.
        filename = script_filename(test_key)
        if os.path.exists(filename):
            DatabaseLayer.mockdb_mode = 'replay'
            DatabaseLayer.script = ScriptPlayer(test_key)
        else:
            DatabaseLayer.mockdb_mode = 'record'
            DatabaseLayer.script = ScriptRecorder(test_key)

        global _org_connect
        _org_connect = psycopg2.connect
        # Proxy real connections with our mockdb.
        def fake_connect(*args, **kw):
            return DatabaseLayer.script.connect(_org_connect, *args, **kw)
        psycopg2.connect = fake_connect

    @classmethod
    @profiled
    def uninstallMockDb(cls):
        if DatabaseLayer.mockdb_mode is None:
            return # Already uninstalled

        # Store results if we are recording
        if DatabaseLayer.mockdb_mode == 'record':
            DatabaseLayer.script.store()
            assert os.path.exists(DatabaseLayer.script.script_filename), (
                    "Stored results but no script on disk.")

        DatabaseLayer.mockdb_mode = None
        global _org_connect
        psycopg2.connect = _org_connect
        _org_connect = None

    @classmethod
    @profiled
    def force_dirty_database(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().force_dirty_database()

    @classmethod
    @profiled
    def connect(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        return LaunchpadTestSetup().connect()

    @classmethod
    @profiled
    def _dropDb(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        return LaunchpadTestSetup().dropDb()


def test_default_timeout():
    """Don't timeout by default in tests."""
    return None


class LaunchpadLayer(DatabaseLayer, LibrarianLayer):
    """Provides access to the Launchpad database and daemons.

    We need to ensure that the database setup runs before the daemon
    setup, or the database setup will fail because the daemons are
    already connected to the database.

    This layer is mainly used by tests that call initZopeless() themselves.
    """
    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        pass

    @classmethod
    @profiled
    def testSetUp(cls):
        # By default, don't make external service tests timeout.
        if get_default_timeout_function() is not None:
            raise LayerIsolationError(
                "Global default timeout function should be None.")
        set_default_timeout_function(test_default_timeout)

    @classmethod
    @profiled
    def testTearDown(cls):
        if get_default_timeout_function() is not test_default_timeout:
            raise LayerIsolationError(
                "Test didn't reset default timeout function.")
        set_default_timeout_function(None)

    # A database connection to the session database, created by the first
    # call to resetSessionDb.
    _raw_sessiondb_connection = None

    @classmethod
    @profiled
    def resetSessionDb(cls):
        """Reset the session database.

        Layers that need session database isolation call this explicitly
        in the testSetUp().
        """
        if LaunchpadLayer._raw_sessiondb_connection is None:
            from storm.uri import URI
            from canonical.launchpad.webapp.adapter import (
                LaunchpadSessionDatabase)
            launchpad_session_database = LaunchpadSessionDatabase(
                URI('launchpad-session:'))
            LaunchpadLayer._raw_sessiondb_connection = (
                launchpad_session_database.raw_connect())
        LaunchpadLayer._raw_sessiondb_connection.cursor().execute(
            "DELETE FROM SessionData")


def wsgi_application(environ, start_response):
    """This is a wsgi application for Zope functional testing.

    We use it with wsgi_intercept, which is itself mostly interesting
    for our webservice (lazr.restful) tests.
    """
    # Committing work done up to now is a convenience that the Zope
    # zope.app.testing.functional.HTTPCaller does.  We're replacing that bit,
    # so it is easiest to follow that lead, even if it feels a little loose.
    transaction.commit()
    # Let's support post-mortem debugging.
    if environ.pop('HTTP_X_ZOPE_HANDLE_ERRORS', 'True') == 'False':
        environ['wsgi.handleErrors'] = False
    handle_errors = environ.get('wsgi.handleErrors', True)
    # Now we do the proper dance to get the desired request.  This is an
    # almalgam of code from zope.app.testing.functional.HTTPCaller and
    # zope.publisher.paste.Application.
    request_cls, publication_cls = chooseClasses(
        environ['REQUEST_METHOD'], environ)
    publication = publication_cls(FunctionalTestSetup().db)
    request = request_cls(environ['wsgi.input'], environ)
    request.setPublication(publication)
    # The rest of this function is an amalgam of
    # zope.publisher.paste.Application.__call__ and van.testing.layers.
    request = zope.publisher.publish.publish(
        request, handle_errors=handle_errors)
    response = request.response
    # We sort these, and then put the status first, because
    # zope.testbrowser.testing does--and because it makes it easier to write
    # reliable tests.
    headers = sorted(response.getHeaders())
    status = response.getStatusString()
    headers.insert(0, ('Status', status))
    # Start the WSGI server response.
    start_response(status, headers)
    # Return the result body iterable.
    return response.consumeBodyIter()


class FunctionalLayer(BaseLayer):
    """Loads the Zope3 component architecture in appserver mode."""

    # Set to True if tests using the Functional layer are currently being run.
    isSetUp = False

    @classmethod
    @profiled
    def setUp(cls):
        FunctionalLayer.isSetUp = True
        FunctionalTestSetup().setUp()

        # Assert that FunctionalTestSetup did what it says it does
        if not is_ca_available():
            raise LayerInvariantError("Component architecture failed to load")

        # If our request publication factories were defined using ZCML,
        # they'd be set up by FunctionalTestSetup().setUp(). Since
        # they're defined by Python code, we need to call that code
        # here.
        register_launchpad_request_publication_factories()
        wsgi_intercept.add_wsgi_intercept(
            'localhost', 80, lambda: wsgi_application)

    @classmethod
    @profiled
    def tearDown(cls):
        FunctionalLayer.isSetUp = False
        wsgi_intercept.remove_wsgi_intercept('localhost', 80)
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    @profiled
    def testSetUp(cls):
        transaction.abort()
        transaction.begin()

        # Fake a root folder to keep Z3 ZODB dependencies happy.
        fs = FunctionalTestSetup()
        if not fs.connection:
            fs.connection = fs.db.open()
        root = fs.connection.root()
        root[ZopePublication.root_name] = MockRootFolder()

        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )

    @classmethod
    @profiled
    def testTearDown(cls):
        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )

        transaction.abort()


class ZopelessLayer(BaseLayer):
    """Layer for tests that need the Zopeless component architecture
    loaded using execute_zcml_for_scrips()
    """

    # Set to True if tests in the Zopeless layer are currently being run.
    isSetUp = False

    @classmethod
    @profiled
    def setUp(cls):
        ZopelessLayer.isSetUp = True
        execute_zcml_for_scripts()

        # Assert that execute_zcml_for_scripts did what it says it does.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded by "
                "execute_zcml_for_scripts")

        # If our request publication factories were defined using
        # ZCML, they'd be set up by execute_zcml_for_scripts(). Since
        # they're defined by Python code, we need to call that code
        # here.
        register_launchpad_request_publication_factories()

    @classmethod
    @profiled
    def tearDown(cls):
        ZopelessLayer.isSetUp = False
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    @profiled
    def testSetUp(cls):
        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )
        # This should not happen here, it should be caught by the
        # testTearDown() method. If it does, something very nasty
        # happened.
        if getSecurityPolicy() != PermissiveSecurityPolicy:
            raise LayerInvariantError(
                "Previous test removed the PermissiveSecurityPolicy.")

        # execute_zcml_for_scripts() sets up an interaction for the
        # anonymous user. A previous script may have changed or removed
        # the interaction, so set it up again
        login(ANONYMOUS)

    @classmethod
    @profiled
    def testTearDown(cls):
        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )
        # Make sure that a test that changed the security policy, reset it
        # back to its default value.
        if getSecurityPolicy() != PermissiveSecurityPolicy:
            raise LayerInvariantError(
                "This test removed the PermissiveSecurityPolicy and didn't "
                "restore it.")
        logout()


class TwistedLayer(BaseLayer):
    """A layer for cleaning up the Twisted thread pool."""

    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        pass

    @classmethod
    def _save_signals(cls):
        """Save the current signal handlers."""
        TwistedLayer._original_sigint = signal.getsignal(signal.SIGINT)
        TwistedLayer._original_sigterm = signal.getsignal(signal.SIGTERM)
        TwistedLayer._original_sigchld = signal.getsignal(signal.SIGCHLD)
        # XXX MichaelHudson, 2009-07-14, bug=399118: If a test case in this
        # layer launches a process with spawnProcess, there should really be a
        # SIGCHLD handler installed to avoid PotentialZombieWarnings.  But
        # some tests in this layer use tachandler and it is fragile when a
        # SIGCHLD handler is installed.  tachandler needs to be fixed.
        # from twisted.internet import reactor
        # signal.signal(signal.SIGCHLD, reactor._handleSigchld)

    @classmethod
    def _restore_signals(cls):
        """Restore the signal handlers."""
        signal.signal(signal.SIGINT, TwistedLayer._original_sigint)
        signal.signal(signal.SIGTERM, TwistedLayer._original_sigterm)
        signal.signal(signal.SIGCHLD, TwistedLayer._original_sigchld)

    @classmethod
    @profiled
    def testSetUp(cls):
        TwistedLayer._save_signals()
        from twisted.internet import interfaces, reactor
        from twisted.python import threadpool
        if interfaces.IReactorThreads.providedBy(reactor):
            pool = getattr(reactor, 'threadpool', None)
            # If the Twisted threadpool has been obliterated (probably by
            # testTearDown), then re-build it using the values that Twisted
            # uses.
            if pool is None:
                reactor.threadpool = threadpool.ThreadPool(0, 10)
                reactor.threadpool.start()

    @classmethod
    @profiled
    def testTearDown(cls):
        # Shutdown and obliterate the Twisted threadpool, to plug up leaking
        # threads.
        from twisted.internet import interfaces, reactor
        if interfaces.IReactorThreads.providedBy(reactor):
            reactor.suggestThreadPoolSize(0)
            pool = getattr(reactor, 'threadpool', None)
            if pool is not None:
                reactor.threadpool.stop()
                reactor.threadpool = None
        TwistedLayer._restore_signals()


class GoogleServiceLayer(BaseLayer):
    """Tests for Google web service integration."""

    @classmethod
    def setUp(cls):
        google = GoogleServiceTestSetup()
        google.setUp()
        atexit.register(google.tearDown)

    @classmethod
    def tearDown(cls):
        GoogleServiceTestSetup().tearDown()

    @classmethod
    def testSetUp(self):
        # We need to override BaseLayer.testSetUp(), or else we will
        # get a LayerIsolationError.
        pass

    @classmethod
    def testTearDown(self):
        # We need to override BaseLayer.testTearDown(), or else we will
        # get a LayerIsolationError.
        pass


class DatabaseFunctionalLayer(DatabaseLayer, FunctionalLayer):
    """Provides the database and the Zope3 application server environment."""

    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        pass

    @classmethod
    @profiled
    def testSetUp(cls):
        # Connect Storm
        reconnect_stores()

    @classmethod
    @profiled
    def testTearDown(cls):
        getUtility(IOpenLaunchBag).clear()

        # If tests forget to logout, we can do it for them.
        if is_logged_in():
            logout()

        # Disconnect Storm so it doesn't get in the way of database resets
        disconnect_stores()


class LaunchpadFunctionalLayer(LaunchpadLayer, FunctionalLayer,
                               GoogleServiceLayer):
    """Provides the Launchpad Zope3 application server environment."""
    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        pass

    @classmethod
    @profiled
    def testSetUp(cls):
        # Reset any statistics
        from canonical.launchpad.webapp.opstats import OpStats
        OpStats.resetStats()

        # Connect Storm
        reconnect_stores()

    @classmethod
    @profiled
    def testTearDown(cls):
        getUtility(IOpenLaunchBag).clear()

        # If tests forget to logout, we can do it for them.
        if is_logged_in():
            logout()

        # Reset any statistics
        from canonical.launchpad.webapp.opstats import OpStats
        OpStats.resetStats()

        # Disconnect Storm so it doesn't get in the way of database resets
        disconnect_stores()



class ZopelessDatabaseLayer(ZopelessLayer, DatabaseLayer):
    """Testing layer for unit tests with no need for librarian.

    Can be used wherever you're accustomed to using LaunchpadZopeless
    or LaunchpadScript layers, but there is no need for librarian.
    """

    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    @profiled
    def testSetUp(cls):
        # LaunchpadZopelessLayer takes care of reconnecting the stores
        if not LaunchpadZopelessLayer.isSetUp:
            reconnect_stores()

    @classmethod
    @profiled
    def testTearDown(cls):
        disconnect_stores()

    @classmethod
    @profiled
    def switchDbConfig(cls, database_config_section):
        reconnect_stores(database_config_section=database_config_section)


class LaunchpadScriptLayer(ZopelessLayer, LaunchpadLayer):
    """Testing layer for scripts using the main Launchpad database adapter"""

    @classmethod
    @profiled
    def setUp(cls):
        # Make a TestMailBox available
        # This is registered via ZCML in the LaunchpadFunctionalLayer
        # XXX flacoste 2006-10-25 bug=68189: This should be configured from
        # ZCML but execute_zcml_for_scripts() doesn't cannot support a
        # different testing configuration.
        provideUtility(TestMailBox(), IMailBox)

    @classmethod
    @profiled
    def tearDown(cls):
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    @profiled
    def testSetUp(cls):
        # LaunchpadZopelessLayer takes care of reconnecting the stores
        if not LaunchpadZopelessLayer.isSetUp:
            reconnect_stores()

    @classmethod
    @profiled
    def testTearDown(cls):
        disconnect_stores()

    @classmethod
    @profiled
    def switchDbConfig(cls, database_config_section):
        reconnect_stores(database_config_section=database_config_section)


class LaunchpadZopelessLayer(LaunchpadScriptLayer):
    """Full Zopeless environment including Component Architecture and
    database connections initialized.
    """

    isSetUp = False
    txn = ZopelessTransactionManager

    @classmethod
    @profiled
    def setUp(cls):
        LaunchpadZopelessLayer.isSetUp = True

    @classmethod
    @profiled
    def tearDown(cls):
        LaunchpadZopelessLayer.isSetUp = False

    @classmethod
    @profiled
    def testSetUp(cls):
        if ZopelessTransactionManager._installed is not None:
            raise LayerIsolationError(
                "Last test using Zopeless failed to tearDown correctly"
                )
        initZopeless()

        # Connect Storm
        reconnect_stores()

    @classmethod
    @profiled
    def testTearDown(cls):
        ZopelessTransactionManager.uninstall()
        if ZopelessTransactionManager._installed is not None:
            raise LayerInvariantError(
                "Failed to uninstall ZopelessTransactionManager"
                )
        # LaunchpadScriptLayer will disconnect the stores for us.

    @classmethod
    @profiled
    def commit(cls):
        transaction.commit()

    @classmethod
    @profiled
    def abort(cls):
        transaction.abort()

    @classmethod
    @profiled
    def switchDbUser(cls, dbuser):
        LaunchpadZopelessLayer.alterConnection(dbuser=dbuser)

    @classmethod
    @profiled
    def alterConnection(cls, **kw):
        """Reset the connection, and reopen the connection by calling
        initZopeless with the given keyword arguments.
        """
        ZopelessTransactionManager.uninstall()
        initZopeless(**kw)


class ExperimentalLaunchpadZopelessLayer(LaunchpadZopelessLayer):
    """LaunchpadZopelessLayer using the mock database."""

    @classmethod
    def setUp(cls):
        DatabaseLayer.use_mockdb = True

    @classmethod
    def tearDown(cls):
        DatabaseLayer.use_mockdb = False

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass


class MockHTTPTask:

    class MockHTTPRequestParser:
        headers = None
        first_line = None

    class MockHTTPServerChannel:
        # This is not important to us, so we can hardcode it here.
        addr = ['127.0.0.88', 80]

    request_data = MockHTTPRequestParser()
    channel = MockHTTPServerChannel()

    def __init__(self, response, first_line):
        self.request = response._request
        # We have no way of knowing when the task started, so we use
        # the current time here. That shouldn't be a problem since we don't
        # care about that for our tests anyway.
        self.start_time = time.time()
        self.status = response.getStatus()
        # When streaming files (see lib/zope/publisher/httpresults.txt)
        # the 'Content-Length' header is missing. When it happens we set
        # 'bytes_written' to an obviously invalid value. This variable is
        # used for logging purposes, see webapp/servers.py.
        content_length = response.getHeader('Content-Length')
        if content_length is not None:
            self.bytes_written = int(content_length)
        else:
            self.bytes_written = -1
        self.request_data.headers = self.request.headers
        self.request_data.first_line = first_line

    def getCGIEnvironment(self):
        return self.request._orig_env


class PageTestLayer(LaunchpadFunctionalLayer):
    """Environment for page tests.
    """
    @classmethod
    @profiled
    def resetBetweenTests(cls, flag):
        LibrarianLayer._reset_between_tests = flag
        DatabaseLayer._reset_between_tests = flag

    @classmethod
    @profiled
    def setUp(cls):
        if os.environ.get('PROFILE_PAGETESTS_REQUESTS'):
            PageTestLayer.profiler = Profile()
        else:
            PageTestLayer.profiler = None
        file_handler = logging.FileHandler('pagetests-access.log', 'w')
        file_handler.setFormatter(logging.Formatter())
        logger = PythonLogger('pagetests-access')
        logger.logger.addHandler(file_handler)
        logger.logger.setLevel(logging.INFO)
        access_logger = LaunchpadAccessLogger(logger)
        def my__call__(obj, request_string, handle_errors=True, form=None):
            """Call HTTPCaller.__call__ and log the page hit."""
            if PageTestLayer.profiler:
                response = PageTestLayer.profiler.runcall(
                    orig__call__, obj, request_string,
                    handle_errors=handle_errors, form=form)
            else:
                response = orig__call__(
                    obj, request_string, handle_errors=handle_errors,
                    form=form)
            first_line = request_string.strip().splitlines()[0]
            access_logger.log(MockHTTPTask(response._response, first_line))
            return response

        PageTestLayer.orig__call__ = (
                zope.app.testing.functional.HTTPCaller.__call__)
        zope.app.testing.functional.HTTPCaller.__call__ = my__call__
        PageTestLayer.resetBetweenTests(True)

    @classmethod
    @profiled
    def tearDown(cls):
        PageTestLayer.resetBetweenTests(True)
        zope.app.testing.functional.HTTPCaller.__call__ = (
                PageTestLayer.orig__call__)
        if PageTestLayer.profiler:
            PageTestLayer.profiler.dump_stats(
                os.environ.get('PROFILE_PAGETESTS_REQUESTS'))


    @classmethod
    @profiled
    def startStory(cls):
        DatabaseLayer.testSetUp()
        LibrarianLayer.testSetUp()
        LaunchpadLayer.resetSessionDb()
        PageTestLayer.resetBetweenTests(False)

    @classmethod
    @profiled
    def endStory(cls):
        PageTestLayer.resetBetweenTests(True)
        LibrarianLayer.testTearDown()
        DatabaseLayer.testTearDown()

    @classmethod
    @profiled
    def testSetUp(cls):
        pass

    @classmethod
    @profiled
    def testTearDown(cls):
        pass


class TwistedLaunchpadZopelessLayer(TwistedLayer, LaunchpadZopelessLayer):
    """A layer for cleaning up the Twisted thread pool."""

    @classmethod
    @profiled
    def setUp(cls):
        pass

    @classmethod
    @profiled
    def tearDown(cls):
        pass

    @classmethod
    @profiled
    def testSetUp(cls):
        pass

    @classmethod
    @profiled
    def testTearDown(cls):
        # XXX 2008-06-11 jamesh bug=239086:
        # Due to bugs in the transaction module's thread local
        # storage, transactions may be reused by new threads in future
        # tests.  Therefore we do some cleanup before the pool is
        # destroyed by TwistedLayer.testTearDown().
        from twisted.internet import interfaces, reactor
        if interfaces.IReactorThreads.providedBy(reactor):
            pool = getattr(reactor, 'threadpool', None)
            if pool is not None and pool.workers > 0:
                def cleanup_thread_stores(event):
                    disconnect_stores()
                    # Don't exit until the event fires.  This ensures
                    # that our thread doesn't get added to
                    # pool.waiters until all threads are processed.
                    event.wait()
                event = threading.Event()
                # Ensure that the pool doesn't grow, and issue one
                # cleanup job for each thread in the pool.
                pool.adjustPoolsize(0, pool.workers)
                for i in range(pool.workers):
                    pool.callInThread(cleanup_thread_stores, event)
                event.set()


class LayerProcessController:
    """Controller for starting and stopping subprocesses.

    Layers which need to start and stop a child process appserver or smtp
    server should call the methods in this class, but should NOT inherit from
    this class.
    """

    # Holds the Popen instance of the spawned app server.
    appserver = None

    # The config used by the spawned app server.
    appserver_config = CanonicalConfig('testrunner-appserver', 'runlaunchpad')

    # The SMTP server for layer tests.  See
    # configs/testrunner-appserver/mail-configure.zcml
    smtp_controller = None

    @classmethod
    @profiled
    def startSMTPServer(cls):
        """Start the SMTP server if it hasn't already been started."""
        if cls.smtp_controller is not None:
            raise LayerInvariantError('SMTP server already running')
        # Ensure that the SMTP server does proper logging.
        log = logging.getLogger('lazr.smtptest')
        log_file = os.path.join(config.mailman.build_var_dir, 'logs', 'smtpd')
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(
            fmt='%(asctime)s (%(process)d) %(message)s',
            datefmt='%b %d %H:%M:%S %Y')
        handler.setFormatter(formatter)
        log.setLevel(logging.DEBUG)
        log.addHandler(handler)
        log.propagate = False
        cls.smtp_controller = SMTPController('localhost', 9025)
        cls.smtp_controller.start()
        # Make sure that the smtp server is killed even if tearDown() is
        # skipped, which can happen if FunctionalLayer is in the mix.
        atexit.register(cls.stopSMTPServer)

    @classmethod
    @profiled
    def startAppServer(cls):
        """Start the app server if it hasn't already been started."""
        if cls.appserver is not None:
            raise LayerInvariantError('App server already running')
        cls._cleanUpStaleAppServer()
        cls._runAppServer()
        cls._waitUntilAppServerIsReady()
        # Make sure that the app server is killed even if tearDown() is
        # skipped.
        atexit.register(cls.stopAppServer)

    @classmethod
    @profiled
    def stopSMTPServer(cls):
        """Kill the SMTP server and wait until it's exited."""
        if cls.smtp_controller is not None:
            cls.smtp_controller.reset()
            cls.smtp_controller.stop()
            cls.smtp_controller = None

    @classmethod
    def _kill(cls, sig):
        """Kill the appserver with `sig`.

        :param sig: the signal to kill with
        :type sig: int
        :return: True if the signal was delivered, otherwise False.
        :rtype: bool
        """
        try:
            os.kill(cls.appserver.pid, sig)
        except OSError, error:
            if error.errno == errno.ESRCH:
                # The child process doesn't exist.  Maybe it went away by the
                # time we got here.
                cls.appserver = None
                return False
            else:
                # Something else went wrong.
                raise
        else:
            return True

    @classmethod
    @profiled
    def stopAppServer(cls):
        """Kill the appserver and wait until it's exited."""
        if cls.appserver is not None:
            # Unfortunately, Popen.wait() does not support a timeout, so poll
            # for a little while, then SIGKILL the process if it refuses to
            # exit.  test_on_merge.py will barf if we hang here for too long.
            until = datetime.datetime.now() + WAIT_INTERVAL
            last_chance = False
            if not cls._kill(signal.SIGTERM):
                # The process is already gone.
                return
            while True:
                # Sleep and poll for process exit.
                if cls.appserver.poll() is not None:
                    break
                time.sleep(0.5)
                # If we slept long enough, send a harder kill and wait again.
                # If we already had our last chance, raise an exception.
                if datetime.datetime.now() > until:
                    if last_chance:
                        raise RuntimeError("The appserver just wouldn't die")
                    last_chance = True
                    if not cls._kill(signal.SIGKILL):
                        # The process is already gone.
                        return
                    until = datetime.datetime.now() + WAIT_INTERVAL
            cls.appserver = None

    @classmethod
    @profiled
    def postTestInvariants(cls):
        """Enforce some invariants after each test.

        Must be called in your layer class's `testTearDown()`.
        """
        if cls.appserver.poll() is not None:
            raise LayerIsolationError(
                "App server died in this test (status=%s):\n%s" % (
                    cls.appserver.returncode, cls.appserver.stdout.read()))
        DatabaseLayer.force_dirty_database()

    @classmethod
    def _cleanUpStaleAppServer(cls):
        """Kill any stale app server or pid file."""
        pid = pidfile.get_pid('launchpad', cls.appserver_config)
        if pid is not None:
            # Don't worry if the process no longer exists.
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError, error:
                if error.errno != errno.ESRCH:
                    raise
            pidfile.remove_pidfile('launchpad', cls.appserver_config)

    @classmethod
    def _runAppServer(cls):
        """Start the app server using runlaunchpad.py"""
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        # The database must be available for the app server to start.
        LaunchpadTestSetup().setUp()
        # The app server will not start at all if the database hasn't been
        # correctly patched.
        confirm_dbrevision(cursor())
        _config = cls.appserver_config
        cmd = [
            os.path.join(_config.root, 'bin', 'run'),
            '-C', 'configs/%s/launchpad.conf' % _config.instance_name]
        environ = dict(os.environ)
        environ['LPCONFIG'] = _config.instance_name
        cls.appserver = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=environ, cwd=_config.root)

    @classmethod
    def _waitUntilAppServerIsReady(cls):
        """Wait until the app server accepts connection."""
        assert cls.appserver is not None, "App server isn't started."
        root_url = cls.appserver_config.vhost.mainsite.rooturl
        until = datetime.datetime.now() + WAIT_INTERVAL
        while until > datetime.datetime.now():
            try:
                connection = urlopen(root_url)
                connection.read()
            except IOError, error:
                # We are interested in a wrapped socket.error.
                # urlopen() really sucks here.
                if len(error.args) <= 1:
                    raise
                if not isinstance(error.args[1], socket.error):
                    raise
                if error.args[1].args[0] != errno.ECONNREFUSED:
                    raise
                returncode = cls.appserver.poll()
                if returncode is not None:
                    raise RuntimeError(
                        'App server failed to start (status=%d):\n%s' % (
                            returncode, cls.appserver.stdout.read()))
                time.sleep(0.5)
            else:
                connection.close()
                break
        else:
            os.kill(cls.appserver.pid, signal.SIGTERM)
            cls.appserver = None
            # Go no further.
            raise AssertionError('App server startup timed out.')


class AppServerLayer(LaunchpadFunctionalLayer):
    """Layer for tests that run in the webapp environment with an app server.
    """

    @classmethod
    @profiled
    def setUp(cls):
        LayerProcessController.startSMTPServer()
        LayerProcessController.startAppServer()

    @classmethod
    @profiled
    def tearDown(cls):
        LayerProcessController.stopAppServer()
        LayerProcessController.stopSMTPServer()

    @classmethod
    @profiled
    def testSetUp(cls):
        LaunchpadLayer.resetSessionDb()

    @classmethod
    @profiled
    def testTearDown(cls):
        LayerProcessController.postTestInvariants()


class ZopelessAppServerLayer(LaunchpadZopelessLayer):
    """Layer for tests that run in the zopeless environment with an appserver.
    """

    @classmethod
    @profiled
    def setUp(cls):
        LayerProcessController.startSMTPServer()
        LayerProcessController.startAppServer()

    @classmethod
    @profiled
    def tearDown(cls):
        LayerProcessController.stopAppServer()
        LayerProcessController.stopSMTPServer()

    @classmethod
    @profiled
    def testSetUp(cls):
        LaunchpadLayer.resetSessionDb()

    @classmethod
    @profiled
    def testTearDown(cls):
        LayerProcessController.postTestInvariants()


class TwistedAppServerLayer(TwistedLaunchpadZopelessLayer):
    """Layer for twisted-using zopeless tests that need a running app server.
    """

    @classmethod
    @profiled
    def setUp(cls):
        LayerProcessController.startSMTPServer()
        LayerProcessController.startAppServer()

    @classmethod
    @profiled
    def tearDown(cls):
        LayerProcessController.stopAppServer()
        LayerProcessController.stopSMTPServer()

    @classmethod
    @profiled
    def testSetUp(cls):
        LaunchpadLayer.resetSessionDb()

    @classmethod
    @profiled
    def testTearDown(cls):
        LayerProcessController.postTestInvariants()


class BaseWindmillLayer(AppServerLayer):
    """Layer for Windmill tests.

    This layer shouldn't be used directly. A subclass needs to be
    created specifying which base URL to use (e.g.
    http://bugs.launchpad.dev:8085/).
    """

    base_url = None
    shell_objects = None
    config_file = None

    @classmethod
    @profiled
    def setUp(cls):
        if cls.base_url is None:
            # Only do the setup if we're in a subclass that defines
            # base_url. With no base_url, we can't create the config
            # file windmill needs.
            return
        # Windmill needs a config file on disk.
        config_text = dedent("""\
            START_FIREFOX = True
            TEST_URL = '%s'
            """ % cls.base_url)
        cls.config_file = tempfile.NamedTemporaryFile(suffix='.py')
        cls.config_file.write(config_text)
        # Flush the file so that windmill can read it.
        cls.config_file.flush()
        os.environ['WINDMILL_CONFIG_FILE'] = cls.config_file.name
        cls.shell_objects = start_windmill()

    @classmethod
    @profiled
    def tearDown(cls):
        if cls.shell_objects is not None:
            windmill_teardown(cls.shell_objects)
        if cls.config_file is not None:
            # Close the file so that it gets deleted.
            cls.config_file.close()

    @classmethod
    @profiled
    def testSetUp(cls):
        # Left-over threads should be harmless, since they should all
        # belong to Windmill, which will be cleaned up on layer
        # tear down.
        BaseLayer.disable_thread_check = True
