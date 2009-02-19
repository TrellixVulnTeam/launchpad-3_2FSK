# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# We use global in this module.
# pylint: disable-msg=W0602

__metaclass__ = type

import os
import sys
import thread
import threading
import traceback
from time import time
import warnings

from psycopg2.extensions import (
    ISOLATION_LEVEL_AUTOCOMMIT, ISOLATION_LEVEL_READ_COMMITTED,
    ISOLATION_LEVEL_SERIALIZABLE, QueryCanceledError)

from storm.database import register_scheme
from storm.databases.postgres import Postgres, PostgresTimeoutTracer
from storm.exceptions import TimeoutError
from storm.store import Store
from storm.tracer import install_tracer
from storm.zope.interfaces import IZStorm

import transaction
from zope.component import getUtility
from zope.interface import (
    classImplements, classProvides, alsoProvides,
    implementer, implements, Interface)
from zope.security.proxy import ProxyFactory, removeSecurityProxy

from canonical.config import config, dbconfig
from canonical.database.interfaces import IRequestExpired
from canonical.lazr.utils import safe_hasattr
from canonical.launchpad.interfaces import (
    IMasterDBObject, IMasterStore, ISlaveStore, IStore)
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, AUTH_STORE, DEFAULT_FLAVOR, MAIN_STORE,
    MASTER_FLAVOR, SLAVE_FLAVOR)
from canonical.launchpad.webapp.opstats import OpStats


__all__ = [
    'DisconnectionError',
    'RequestExpired',
    'set_request_started',
    'clear_request_started',
    'get_request_statements',
    'get_request_start_time',
    'get_request_duration',
    'get_store_name',
    'hard_timeout_expired',
    'soft_timeout_expired',
    'StoreSelector',
    ]


classImplements(TimeoutError, IRequestExpired)


def _get_dirty_commit_flags():
    """Return the current dirty commit status"""
    from canonical.ftests.pgsql import ConnectionWrapper
    return (ConnectionWrapper.committed, ConnectionWrapper.dirty)

def _reset_dirty_commit_flags(previous_committed, previous_dirty):
    """Set the dirty commit status to False unless previous is True"""
    from canonical.ftests.pgsql import ConnectionWrapper
    if not previous_committed:
        ConnectionWrapper.committed = False
    if not previous_dirty:
        ConnectionWrapper.dirty = False


_local = threading.local()

def set_request_started(starttime=None):
    """Set the start time for the request being served by the current
    thread.

    If the argument is given, it is used as the start time for the
    request, as returned by time().  If it is not given, the
    current time is used.
    """
    if getattr(_local, 'request_start_time', None) is not None:
        warnings.warn('set_request_started() called before previous request '
                      'finished', stacklevel=1)

    if starttime is None:
        starttime = time()
    _local.request_start_time = starttime
    _local.request_statements = []
    _local.current_statement_timeout = None


def clear_request_started():
    """Clear the request timer.  This function should be called when
    the request completes.
    """
    if getattr(_local, 'request_start_time', None) is None:
        warnings.warn('clear_request_started() called outside of a request')

    _local.request_start_time = None
    _local.request_statements = []


def summarize_requests():
    """Produce human-readable summary of requests issued so far."""
    secs = get_request_duration()
    statements = getattr(_local, 'request_statements', [])
    log = "%s queries issued in %.2f seconds" % (len(statements), secs)
    return log


def store_sql_statements_and_request_duration(event):
    event.request.setInWSGIEnvironment(
        'launchpad.sqlstatements', len(get_request_statements()))
    event.request.setInWSGIEnvironment(
        'launchpad.requestduration', get_request_duration())


def get_request_statements():
    """Get the list of executed statements in the request.

    The list is composed of (starttime, endtime, statement) tuples.
    Times are given in milliseconds since the start of the request.
    """
    return getattr(_local, 'request_statements', [])


def get_request_start_time():
    """Get the time at which the request started."""
    return getattr(_local, 'request_start_time', None)


def get_request_duration(now=None):
    """Get the duration of the current request in seconds."""
    starttime = getattr(_local, 'request_start_time', None)
    if starttime is None:
        return -1

    if now is None:
        now = time()
    return now - starttime


def _log_statement(starttime, endtime, connection_wrapper, statement):
    """Log that a database statement was executed."""
    request_starttime = getattr(_local, 'request_start_time', None)
    if request_starttime is None:
        return

    # convert times to integer millisecond values
    starttime = int((starttime - request_starttime) * 1000)
    endtime = int((endtime - request_starttime) * 1000)
    _local.request_statements.append((starttime, endtime, statement))

    # store the last executed statement as an attribute on the current
    # thread
    threading.currentThread().lp_last_sql_statement = statement


def _check_expired(timeout):
    """Checks whether the current request has passed the given timeout."""
    if timeout is None:
        return False # no timeout configured

    starttime = getattr(_local, 'request_start_time', None)
    if starttime is None:
        return False # no current request

    requesttime = (time() - starttime) * 1000
    return requesttime > timeout


def hard_timeout_expired():
    """Returns True if the hard request timeout been reached."""
    return _check_expired(config.database.db_statement_timeout)


def soft_timeout_expired():
    """Returns True if the soft request timeout been reached."""
    return _check_expired(config.database.soft_request_timeout)


class RequestExpired(RuntimeError):
    """Request has timed out."""
    implements(IRequestExpired)


# ---- Prevent database access in the main thread of the app server

class StormAccessFromMainThread(Exception):
    """The main thread must not access the database via Storm.

    Occurs only if the appserver is running. Other code, such as the test
    suite, can do what it likes.
    """

_main_thread_id = None

def break_main_thread_db_access(*ignored):
    """Ensure that Storm connections are not made in the main thread.

    When the app server is running, we want ensure we don't use the
    connection cache from the main thread as this would only be done
    on process startup and would leave an open connection dangling,
    wasting resources.

    This method is invoked by an IProcessStartingEvent - it would be
    easier to do on module load, but the test suite has legitimate uses
    for using connections from the main thread.
    """
    # Record the ID of the main thread.
    # pylint: disable-msg=W0603
    global _main_thread_id
    _main_thread_id = thread.get_ident()

    try:
        getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
    except StormAccessFromMainThread:
        # LaunchpadDatabase correctly refused to create a connection
        pass
    else:
        # We can't specify the order event handlers are called, so
        # this means some other code has used storm before this
        # handler.
        raise StormAccessFromMainThread()


# ---- Storm database classes

isolation_level_map = {
    'autocommit': ISOLATION_LEVEL_AUTOCOMMIT,
    'read_committed': ISOLATION_LEVEL_READ_COMMITTED,
    'serializable': ISOLATION_LEVEL_SERIALIZABLE,
    }


class LaunchpadDatabase(Postgres):

    def __init__(self, uri):
        # The uri is just a property name in the config, such as main_master
        # or auth_slave.
        # We don't invoke the superclass constructor as it has a very limited
        # opinion on what uri is.
        # pylint: disable-msg=W0231
        self._uri = uri

    def raw_connect(self):
        # Prevent database connections from the main thread if
        # break_main_thread_db_access() has been run.
        if (_main_thread_id is not None and
            _main_thread_id == thread.get_ident()):
            raise StormAccessFromMainThread()

        try:
            realm, flavor = self._uri.database.split('-')
        except ValueError:
            assert False, (
                'DB connection uri %s does not match realm-flavor format'
                % repr(self._uri.database))

        assert realm in ('main', 'auth'), 'Unknown realm %s' % realm
        assert flavor in ('master', 'slave'), 'Unknown flavor %s' % flavor

        # We set self._dsn here rather than in __init__ so when the Store
        # is reconnected it pays attention to any config changes.
        config_entry = '%s_%s' % (realm, flavor)
        connection_string = getattr(dbconfig, config_entry)
        assert 'user=' not in connection_string, (
                "Database username should not be specified in "
                "connection string (%s)." % connection_string)

        # Try to lookup dbuser using the $realm_dbuser key. If this fails,
        # fallback to the dbuser key.
        dbuser = getattr(dbconfig, '%s_dbuser' % realm, dbconfig.dbuser)

        self._dsn = "%s user=%s" % (connection_string, dbuser)

        flags = _get_dirty_commit_flags()
        raw_connection = super(LaunchpadDatabase, self).raw_connect()

        if dbconfig.isolation_level is None:
            isolation_level = ISOLATION_LEVEL_SERIALIZABLE
        else:
            isolation_level = isolation_level_map[dbconfig.isolation_level]
        raw_connection.set_isolation_level(isolation_level)

        # Set read only mode for the session.
        # An alternative would be to use the _ro users generated by
        # security.py, but this would needlessly double the number
        # of database users we need to maintain ACLs for on production.
        if config_entry.endswith('_slave'):
            raw_connection.cursor().execute(
                'SET DEFAULT_TRANSACTION_READ_ONLY TO TRUE')
            # Make the altered session setting stick.
            raw_connection.commit()
        else:
            assert config_entry.endswith('_master'), (
                'DB connection URL %s does not meet naming convention.')

        _reset_dirty_commit_flags(*flags)
        return raw_connection


class LaunchpadSessionDatabase(Postgres):

    def raw_connect(self):
        self._dsn = 'dbname=%s user=%s' % (config.launchpad_session.dbname,
                                           config.launchpad_session.dbuser)
        if config.launchpad_session.dbhost:
            self._dsn += ' host=%s' % config.launchpad_session.dbhost

        flags = _get_dirty_commit_flags()
        raw_connection = super(LaunchpadSessionDatabase, self).raw_connect()
        if safe_hasattr(raw_connection, 'auto_close'):
            raw_connection.auto_close = False
        raw_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        _reset_dirty_commit_flags(*flags)
        return raw_connection


register_scheme('launchpad', LaunchpadDatabase)
register_scheme('launchpad-session', LaunchpadSessionDatabase)


class LaunchpadTimeoutTracer(PostgresTimeoutTracer):
    """Storm tracer class to keep statement execution time bounded."""

    def __init__(self):
        # pylint: disable-msg=W0231
        # The parent class __init__ just sets the granularity
        # attribute, which we are handling with a property.
        pass

    @property
    def granularity(self):
        return dbconfig.db_statement_timeout_precision / 1000.0

    def connection_raw_execute(self, connection, raw_cursor,
                               statement, params):
        """See `TimeoutTracer`"""
        # Only perform timeout handling on LaunchpadDatabase
        # connections.
        if not isinstance(connection._database, LaunchpadDatabase):
            return
        # If we are outside of a request, don't do timeout adjustment.
        if self.get_remaining_time() is None:
            return
        try:
            super(LaunchpadTimeoutTracer, self).connection_raw_execute(
                connection, raw_cursor, statement, params)
        except TimeoutError:
            info = sys.exc_info()
            transaction.doom()
            OpStats.stats['timeouts'] += 1
            try:
                raise info[0], info[1], info[2]
            finally:
                info = None

    def connection_raw_execute_error(self, connection, raw_cursor,
                                     statement, params, error):
        """See `TimeoutTracer`"""
        # Only perform timeout handling on LaunchpadDatabase
        # connections.
        if not isinstance(connection._database, LaunchpadDatabase):
            return
        if isinstance(error, QueryCanceledError):
            OpStats.stats['timeouts'] += 1
            raise TimeoutError(statement, params)

    def get_remaining_time(self):
        """See `TimeoutTracer`"""
        if not dbconfig.db_statement_timeout:
            return None
        start_time = getattr(_local, 'request_start_time', None)
        if start_time is None:
            return None
        now = time()
        ellapsed = now - start_time
        return  dbconfig.db_statement_timeout / 1000.0 - ellapsed


class LaunchpadStatementTracer:
    """Storm tracer class to log executed statements."""

    def __init__(self):
        self._debug_sql = bool(os.environ.get('LP_DEBUG_SQL'))
        self._debug_sql_extra = bool(os.environ.get('LP_DEBUG_SQL_EXTRA'))

    def connection_raw_execute(self, connection, raw_cursor,
                               statement, params):
        if self._debug_sql_extra:
            traceback.print_stack()
            sys.stderr.write("." * 70 + "\n")
        if self._debug_sql or self._debug_sql_extra:
            sys.stderr.write(statement + "\n")
            sys.stderr.write("-" * 70 + "\n")

        now = time()
        connection._lp_statement_start_time = now

    def connection_raw_execute_success(self, connection, raw_cursor,
                                       statement, params):
        end = time()
        start = getattr(connection, '_lp_statement_start_time', end)
        _log_statement(start, end, connection, statement)

    def connection_raw_execute_error(self, connection, raw_cursor,
                                     statement, params, error):
        # Since we are just logging durations, we execute the same
        # hook code for errors as successes.
        self.connection_raw_execute_success(
            connection, raw_cursor, statement, params)


install_tracer(LaunchpadTimeoutTracer())
install_tracer(LaunchpadStatementTracer())


class StoreSelector:
    classProvides(IStoreSelector)

    @staticmethod
    def getDefaultFlavor():
        """Return the DEFAULT_FLAVOR for the current thread."""
        return getattr(_local, 'default_store_flavor', DEFAULT_FLAVOR)

    @staticmethod
    def setDefaultFlavor(flavor):
        """Change what the DEFAULT_FLAVOR is for the current thread."""
        _local.default_store_flavor = flavor

    @staticmethod
    def get(name, flavor):
        """See `IStoreSelector`."""
        assert flavor in (MASTER_FLAVOR, SLAVE_FLAVOR, DEFAULT_FLAVOR), (
            'Invalid flavor %s' % flavor)

        if flavor == DEFAULT_FLAVOR:
            flavor = StoreSelector.getDefaultFlavor()
            if flavor == DEFAULT_FLAVOR:
                # None set, use MASTER by default.
                flavor = MASTER_FLAVOR
        store = getUtility(IZStorm).get(
            '%s-%s' % (name, flavor),
            'launchpad:%s-%s' % (name, flavor))

        # Attach our marker interfaces
        if flavor == MASTER_FLAVOR:
            alsoProvides(store, IMasterStore)
        else:
            alsoProvides(store, ISlaveStore)

        return store



# There are not many tables outside of the main replication set, so we
# can just maintain a hardcoded list of what isn't in there for now.
_auth_store_tables = frozenset([
    'Account', 'AccountPassword', 'AuthToken', 'EmailAddress',
    'OpenIDRPSummary', 'OpenIDAuthorization'])

# We want to be able to adapt a Storm class to an IStore, IMasterStore or
# ISlaveStore. Unfortunately, the component architecture provides no
# way for us to declare that a class, and all its subclasses, provides
# a given interface. This means we need to use an global adapter.

def get_store(storm_class, flavor=DEFAULT_FLAVOR):
    """Return a flavored Store for the given database class."""
    table = getattr(removeSecurityProxy(storm_class), '__storm_table__', None)
    if table in _auth_store_tables:
        return getUtility(IStoreSelector).get(AUTH_STORE, flavor)
    elif table is not None:
        return getUtility(IStoreSelector).get(MAIN_STORE, flavor)
    else:
        return None


def get_master_store(storm_class):
    """Return the master Store for the given database class."""
    return get_store(storm_class, MASTER_FLAVOR)


def get_slave_store(storm_class):
    """Return the master Store for the given database class."""
    return get_store(storm_class, SLAVE_FLAVOR)


def get_object_from_master_store(obj):
    """Return a copy of the given object retrieved from its master Store.

    Returns the object if it already comes from the relevant master Store.

    XXX: This adapter is broken! If obj is a security proxied object,
    the return value is not proxied. I've had no success getting this
    method to return an security proxied object that rejects access to
    all attributes.
    """
    naked_obj = removeSecurityProxy(obj)
    is_wrapped = naked_obj is not obj
    master_store = IMasterStore(naked_obj)
    if master_store is not Store.of(naked_obj):
        naked_obj = master_store.get(naked_obj.__class__, naked_obj.id)
        if naked_obj is None:
            return None
    alsoProvides(naked_obj, IMasterDBObject)
    if is_wrapped:
        return ProxyFactory(naked_obj)
    else:
        return naked_obj


def get_store_name(store):
    """Helper to retrieve the store name for a ZStorm Store."""
    getUtility(IZStorm)._name_index.get(store, None)
