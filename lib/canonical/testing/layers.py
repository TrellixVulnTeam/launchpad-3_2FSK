# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Layers used by Canonical tests.

Layers are the mechanism used by the Zope3 test runner to efficiently
provide environments for tests and are documented in the lib/zope/testing.

Note that every Layer should define all of setUp, tearDown, testSetUp
and testTearDown. If you don't do this, a base class' method will be called
instead probably breaking something.

TODO: Make the Zope3 test runner handle multiple layers per test instead
of one, forcing us to attempt to make some sort of layer tree.
-- StuartBishop 20060619
"""

__metaclass__ = type

__all__ = [
    'BaseLayer', 'DatabaseLayer', 'LibrarianLayer', 'FunctionalLayer',
    'LaunchpadLayer', 'ZopelessLayer', 'LaunchpadFunctionalLayer',
    'LaunchpadZopelessLayer', 'PageTestLayer',
    'LayerConsistencyError', 'LayerIsolationError',
    ]

import time
from urllib import urlopen

import psycopg
import transaction
from zope.component import getUtility, getGlobalSiteManager
from zope.component.interfaces import ComponentLookupError
from zope.security.management import getSecurityPolicy
from zope.security.simplepolicies import PermissiveSecurityPolicy

from canonical.config import config
from canonical.database.sqlbase import ZopelessTransactionManager
from canonical.launchpad.interfaces import IMailBox, IOpenLaunchBag
from canonical.launchpad.ftests import ANONYMOUS, login, logout, is_logged_in
import canonical.launchpad.mail.stub
from canonical.launchpad.mail.mailbox import TestMailBox
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.lp import initZopeless
from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.testing import reset_logging

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

    The test suite should abort as further test failures may well
    be spurious.
    """


def is_ca_available():
    """Returns true if the component architecture has been loaded"""
    try:
        getUtility(IOpenLaunchBag)
    except ComponentLookupError:
        return False
    else:
        return True


class BaseLayer:
    """Base layer.

    All out layers should subclass Base, as this is where we will put
    test isolation checks to ensure that tests to not leave global
    resources in a mess.

    XXX: Unit tests (tests with no layer) will not get this checks.
    The Z3 test runner should be updated so that a layer can be specified
    to use for unit tests. -- StuartBishop 20060712
    """
    # Set to True when we are running tests in this layer.
    isSetUp = False

    @classmethod
    def setUp(cls):
        cls.isSetUp = True

        # Kill any Librarian left running from a previous test run.
        LibrarianTestSetup().killTac()

        # Kill any database left lying around from a previous test run.
        try:
            DatabaseLayer.connect().close()
        except psycopg.Error:
            pass
        else:
            DatabaseLayer._dropDb()

    @classmethod
    def tearDown(cls):
        cls.isSetUp = False

    @classmethod
    def testSetUp(cls):
        cls.check()

    @classmethod
    def testTearDown(cls):
        reset_logging()
        del canonical.launchpad.mail.stub.test_emails[:]
        cls.check()

    @classmethod
    def check(cls):
        """Check that the environment is working as expected.

        We check here so we can detect tests that, for example,
        initialize the Zopeless or Functional environments and
        are using the incorrect layer.
        """
        if FunctionalLayer.isSetUp and ZopelessLayer.isSetUp:
            raise LayerInvariantError(
                "Both Zopefull and Zopeless CA environments setup"
                )

        # Detect a test that causes the component architecture to be loaded.
        # This breaks test isolation, as it cannot be torn down.
        if (is_ca_available() and not FunctionalLayer.isSetUp
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
                    "Zopeless environment was setup and not torn down."
                    )


class LibrarianLayer(BaseLayer):
    """Provides tests access to a Librarian instance.

    Calls to the Librarian will fail unless there is also a Launchpad
    database available.
    """
    _reset_between_tests = True

    @classmethod
    def setUp(cls):
        if not cls._reset_between_tests:
            raise LayerInvariantError(
                    "_reset_between_tests changed before LibrarianLayer "
                    "was actually used."
                    )
        LibrarianTestSetup().setUp()
        cls._check_and_reset()

    @classmethod
    def tearDown(cls):
        if not cls._reset_between_tests:
            raise LayerInvariantError(
                    "_reset_between_tests not reset before LibrarianLayer "
                    "shutdown"
                    )
        cls._check_and_reset()
        LibrarianTestSetup().tearDown()

    @classmethod
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
        if cls._reset_between_tests:
            LibrarianTestSetup().clear()

    @classmethod
    def testSetUp(cls):
        cls._check_and_reset()

    @classmethod
    def testTearDown(cls):
        if cls._hidden:
            cls.reveal()
        cls._check_and_reset()

    # The hide and reveal methods mess with the config. Store the
    # original values so things can be recovered.
    _orig_librarian_port = config.librarian.upload_port

    # Flag maintaining state of hide()/reveal() calls
    _hidden = False

    @classmethod
    def hide(cls):
        """Hide the Librarian so nothing can find it. We don't want to
        actually shut it down because starting it up again is expensive.

        We do this by altering the configuration so the Librarian client
        looks for the Librarian server on the wrong port.

        XXX: Untested -- StuartBishop 20060713
        """
        cls._hidden = True
        config.librarian.upload_port = 58091

    @classmethod
    def reveal(cls):
        """Reveal a hidden Librarian.

        This just involves restoring the config to the original value.

        XXX: Untested -- StuartBishop 20060713
        """
        cls._hidden = False
        config.librarian.upload_port = cls._orig_librarian_port


class DatabaseLayer(BaseLayer):
    """Provides tests access to the Launchpad sample database."""

    # If set to False, database will not be reset between tests. It is
    # your responsibility to set it back to True and call
    # Database.force_dirty_database() when you do so.
    _reset_between_tests = True

    @classmethod
    def setUp(cls):
        cls.force_dirty_database()
        if is_ca_available():
            raise LayerInvariantError(
                    "Component architecture should not be available"
                    )

    @classmethod
    def tearDown(cls):
        # Don't leave the DB lying around or it might break tests
        # that depend on it not being there on startup, such as found
        # in test_layers.py
        cls.force_dirty_database()
        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().tearDown()

    @classmethod
    def testSetUp(cls):
        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if cls._reset_between_tests:
            LaunchpadTestSetup().setUp()
        # Ensure that the database is connectable. Because we might have
        # just created it, keep trying for a few seconds incase PostgreSQL
        # is taking its time getting its house in order.
        for count in range(0,10):
            try:
                cls.connect().close()
            except psycopg.Error:
                if count == 9:
                    raise
                time.sleep(1)
            else:
                break

    @classmethod
    def testTearDown(cls):
        # Ensure that the database is connectable
        cls.connect().close()

        # Imported here to avoid circular import issues. This
        # functionality should be migrated into this module at some
        # point. -- StuartBishop 20060712
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        if cls._reset_between_tests:
            LaunchpadTestSetup().tearDown()

    @classmethod
    def force_dirty_database(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        LaunchpadTestSetup().force_dirty_database()

    @classmethod
    def connect(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        return LaunchpadTestSetup().connect()

    @classmethod
    def _dropDb(cls):
        from canonical.launchpad.ftests.harness import LaunchpadTestSetup
        return LaunchpadTestSetup().dropDb()


class SQLOSLayer(BaseLayer):
    """Maintains the SQLOS connection.

    This Layer is not useful by itself, but it intended to be used as
    a mixin to the Functional and Zopeless Layers.
    """
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        from canonical.launchpad.ftests.harness import _reconnect_sqlos
        _reconnect_sqlos()

    @classmethod
    def testTearDown(cls):
        from canonical.launchpad.ftests.harness import _disconnect_sqlos
        _disconnect_sqlos()


class LaunchpadLayer(DatabaseLayer, LibrarianLayer):
    """Provides access to the Launchpad database and daemons.

    We need to ensure that the database setup runs before the daemon
    setup, or the database setup will fail because the daemons are
    already connected to the database.

    This layer is mainly used by tests that call initZopeless() themselves.
    """
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass


class FunctionalLayer(BaseLayer):
    """Loads the Zope3 component architecture in appserver mode."""

    # Set to True if tests using the Functional layer are currently being run.
    isSetUp = False

    @classmethod
    def setUp(cls):
        cls.isSetUp = True
        from canonical.functional import FunctionalTestSetup
        FunctionalTestSetup().setUp()

        # Assert that FunctionalTestSetup did what it says it does
        if not is_ca_available():
            raise LayerInvariantError("Component architecture failed to load")

    @classmethod
    def tearDown(cls):
        cls.isSetUp = False
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        transaction.abort()
        transaction.begin()

        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )

    @classmethod
    def testTearDown(cls):
        # Should be impossible, as the CA cannot be unloaded. Something
        # mighty nasty has happened if this is triggered.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded or totally screwed"
                )

        transaction.abort()


class ZopelessLayer(LaunchpadLayer):
    """Layer for tests that need the Zopeless component architecture
    loaded using execute_zcml_for_scrips()
    """

    # Set to True if tests in the Zopeless layer are currently being run.
    isSetUp = False

    @classmethod
    def setUp(cls):
        cls.isSetUp = True
        execute_zcml_for_scripts()

        # Assert that execute_zcml_for_scripts did what it says it does.
        if not is_ca_available():
            raise LayerInvariantError(
                "Component architecture not loaded by execute_zcml_for_scripts"
                )

    @classmethod
    def tearDown(cls):
        cls.isSetUp = False
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
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


class LaunchpadFunctionalLayer(
        DatabaseLayer, LibrarianLayer, FunctionalLayer, SQLOSLayer
        ):
    """Provides the Launchpad Zope3 application server environment."""
    @classmethod
    def setUp(cls):
        pass

    @classmethod
    def tearDown(cls):
        pass

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        getUtility(IOpenLaunchBag).clear()

        # If tests forget to logout, we can do it for them.
        if is_logged_in():
            logout()


class LaunchpadZopelessLayer(
        ZopelessLayer, DatabaseLayer, LibrarianLayer, SQLOSLayer
        ):
    """Full Zopeless environment including Component Architecture and
    database connections initialized.
    """
    @classmethod
    def setUp(cls):
        # Make a TestMailBox available
        # This is registered via ZCML in the LaunchpadFunctionalLayer
        getGlobalSiteManager().provideUtility(IMailBox, TestMailBox())

    @classmethod
    def tearDown(cls):
        # Signal Layer cannot be torn down fully
        raise NotImplementedError

    @classmethod
    def testSetUp(cls):
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        if ZopelessTransactionManager._installed is not None:
            raise LayerIsolationError(
                "Last test using Zopeless failed to tearDown correctly"
                )
        cls.txn = initZopeless()
        LaunchpadZopelessTestSetup.txn = cls.txn

    @classmethod
    def testTearDown(cls):
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        LaunchpadZopelessTestSetup.txn.abort()
        LaunchpadZopelessTestSetup.txn.uninstall()
        if ZopelessTransactionManager._installed is not None:
            raise LayerInvariantError(
                "Failed to uninstall ZopelessTransactionManager"
                )

    @classmethod
    def commit(cls):
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        LaunchpadZopelessTestSetup.txn.commit()

    @classmethod
    def abort(cls):
        from canonical.launchpad.ftests.harness import (
                LaunchpadZopelessTestSetup
                )
        LaunchpadZopelessTestSetup.txn.abort()



class PageTestLayer(LaunchpadFunctionalLayer):
    """Environment for page tests.
    """
    @classmethod
    def resetBetweenTests(cls, flag):
        LibrarianLayer._reset_between_tests = flag
        DatabaseLayer._reset_between_tests = flag

    @classmethod
    def setUp(cls):
        cls.resetBetweenTests(True)

    @classmethod
    def tearDown(cls):
        cls.resetBetweenTests(True)

    @classmethod
    def startStory(cls):
        DatabaseLayer.testSetUp()
        LibrarianLayer.testSetUp()
        cls.resetBetweenTests(False)

    @classmethod
    def endStory(cls):
        cls.resetBetweenTests(True)
        LibrarianLayer.testTearDown()
        DatabaseLayer.testTearDown()

    @classmethod
    def testSetUp(cls):
        pass

    @classmethod
    def testTearDown(cls):
        pass

