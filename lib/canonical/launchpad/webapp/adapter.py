# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import os
import sys
import threading
import traceback
import time
import warnings

from zope.interface import implements
from zope.app.rdb import ZopeConnection
from zope.app.rdb.interfaces import DatabaseException

from psycopgda.adapter import PsycopgAdapter, PsycopgConnection, PsycopgCursor
import psycopg

from canonical.config import config
from canonical.database.interfaces import IRequestExpired
from canonical.database.sqlbase import connect, READ_COMMITTED_ISOLATION
from canonical.launchpad.webapp.interfaces import ILaunchpadDatabaseAdapter
import canonical.lp

__all__ = [
    'LaunchpadDatabaseAdapter',
    'SessionDatabaseAdapter',
    'RequestExpired',
    'set_request_started',
    'clear_request_started',
    'get_request_statements',
    'get_request_duration',
    'hard_timeout_expired',
    'soft_timeout_expired',
    ]

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


class SessionDatabaseAdapter(PsycopgAdapter):
    """A subclass of PsycopgAdapter that stores its connection information
    in the central launchpad configuration
    """
    
    def __init__(self, dsn=None):
        """Ignore dsn"""
        dbuser = config.launchpad.session.dbuser
        dbhost = config.launchpad.session.dbhost or ''
        dbname = config.launchpad.session.dbname
        PsycopgAdapter.__init__(
                self, 'dbi://%(dbuser)s:@%(dbhost)s/%(dbname)s' % vars()
                )

    def connect(self):
        if not self.isConnected():
            flags = _get_dirty_commit_flags()
            super(SessionDatabaseAdapter, self).connect()
            _reset_dirty_commit_flags(*flags)

    def _connection_factory(self):
        con = super(SessionDatabaseAdapter, self)._connection_factory()
        con.set_isolation_level(READ_COMMITTED_ISOLATION)
        con.cursor().execute("SET client_encoding TO UNICODE")
        return con


class LaunchpadDatabaseAdapter(PsycopgAdapter):
    """A subclass of PsycopgAdapter that performs some additional
    connection setup.
    """
    implements(ILaunchpadDatabaseAdapter)

    def __init__(self, dsn=None):
        """Ignore dsn"""
        super(LaunchpadDatabaseAdapter, self).__init__('dbi://')

    def connect(self, _dbuser=None):
        """See zope.app.rdb.interfaces.IZopeDatabaseAdapter

        We pass the database user through to avoid having to keep state
        using a thread local.
        """
        if not self.isConnected():
            try:
                self._v_connection = PsycopgConnection(
                    self._connection_factory(_dbuser=_dbuser), self
                    )
            except psycopg.Error, error:
                raise DatabaseException, str(error)

    def _connection_factory(self, _dbuser=None):
        """Override method provided by PsycopgAdapter to pull
        connection settings from the config file
        """
        self.setDSN('dbi://%s@%s/%s' % (
            _dbuser or config.launchpad.dbuser,
            config.dbhost or '',
            config.dbname
            ))

        flags = _get_dirty_commit_flags()
        connection = PsycopgAdapter._connection_factory(self)

        if config.launchpad.db_statement_timeout is not None:
            cursor = connection.cursor()
            cursor.execute('SET statement_timeout TO %d' %
                           config.launchpad.db_statement_timeout)
            connection.commit()

        _reset_dirty_commit_flags(*flags)
        return ConnectionWrapper(connection)

    def readonly(self):
        """See ILaunchpadDatabaseAdapter"""
        cursor = self._v_connection.cursor()
        cursor.execute('SET TRANSACTION READ ONLY')

    def switchUser(self, dbuser=None):
        """See ILaunchpadDatabaseAdapter"""
        # We have to disconnect and reconnect as we may not be running
        # as a user with privileges to issue 'SET SESSION AUTHORIZATION'
        # commands.
        self.disconnect()
        self.connect(_dbuser=dbuser)


_local = threading.local()


def set_request_started(starttime=None):
    """Set the start time for the request being served by the current
    thread.

    If the argument is given, it is used as the start time for the
    request, as returned by time.time().  If it is not given, the
    current time is used.
    """
    if getattr(_local, 'request_start_time', None) is not None:
        warnings.warn('set_request_started() called before previous request '
                      'finished', stacklevel=1)

    if starttime is None:
        starttime = time.time()
    _local.request_start_time = starttime
    _local.request_statements = []


def clear_request_started():
    """Clear the request timer.  This function should be called when
    the request completes.
    """
    if getattr(_local, 'request_start_time', None) is None:
        warnings.warn('clear_request_started() called outside of a request')

    _local.request_start_time = None
    _local.request_statements = []


def get_request_statements():
    """Get the list of executed statements in the request.

    The list is composed of (starttime, endtime, statement) tuples.
    Times are given in milliseconds since the start of the request.
    """
    return getattr(_local, 'request_statements', [])


def get_request_duration(now=None):
    """Get the duration of the current request in seconds.

    """
    starttime = getattr(_local, 'request_start_time', None)
    if starttime is None:
        return -1

    if now is None:
        now = time.time()
    return now - starttime


def _log_statement(starttime, endtime, connection_wrapper, statement):
    """Log that a database statement was executed."""
    request_starttime = getattr(_local, 'request_start_time', None)
    if request_starttime is None:
        return

    # convert times to integer millisecond values
    starttime = int((starttime - request_starttime) * 1000)
    endtime = int((endtime - request_starttime) * 1000)
    _local.request_statements.append((
        starttime, endtime,
        '/*%s*/ %s' % (id(connection_wrapper), statement)
        ))

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

    requesttime = (time.time() - starttime) * 1000
    return requesttime > timeout


def hard_timeout_expired():
    """Returns True if the hard request timeout been reached."""
    return _check_expired(config.launchpad.db_statement_timeout)


def soft_timeout_expired():
    """Returns True if the soft request timeout been reached."""
    return _check_expired(config.launchpad.soft_request_timeout)


class RequestExpired(RuntimeError):
    """Request has timed out."""
    implements(IRequestExpired)


class RequestStatementTimedOut(RequestExpired):
    """A statement that was part of a request timed out."""


class ConnectionWrapper:
    """A simple wrapper around a DB-API connection object.

    Overrides the cursor() method to return CursorWrapper objects.
    """
    
    def __init__(self, connection):
        self.__dict__['_conn'] = connection

    def cursor(self):
        return CursorWrapper(self, self._conn.cursor())

    def __getattr__(self, attr):
        return getattr(self._conn, attr)

    def __setattr__(self, attr, value):
        setattr(self._conn, attr, value)

    def commit(self):
        starttime = time.time()
        try:
            self._conn.commit()
        finally:
            _log_statement(starttime, time.time(), self, 'COMMIT')

    def rollback(self):
        starttime = time.time()
        try:
            self._conn.rollback()
        finally:
            _log_statement(starttime, time.time(), self, 'ROLLBACK')


class CursorWrapper:
    """A simple wrapper for a DB-API cursor object.

    Overrides the execute() method to check whether the current
    request has expired.
    """

    def __init__(self, connection_wrapper, cursor):
        self.__dict__['_cur'] = cursor
        self.__dict__['_connection_wrapper'] = connection_wrapper

    def execute(self, statement, *args, **kwargs):
        """Execute an SQL query, provided that the current request hasn't
        timed out.

        If the request has timed out, the current transaction will be
        doomed (but not completed -- further queries will fail til the
        transaction completes) and the RequestExpired exception will
        be raised.
        """
        if hard_timeout_expired():
            # make sure the current transaction can not be committed by
            # sending a broken SQL statement to the database
            try:
                self._cur.execute('break this transaction')
            except psycopg.DatabaseError:
                pass
            raise RequestExpired(statement)
        try:
            starttime = time.time()
            if os.environ.get("LP_DEBUG_SQL_EXTRA"):
                sys.stderr.write("-" * 70 + "\n")
                traceback.print_stack()
                sys.stderr.write("." * 70 + "\n")
            if (os.environ.get("LP_DEBUG_SQL_EXTRA") or 
                os.environ.get("LP_DEBUG_SQL")):
                sys.stderr.write(statement + "\n")
            try:
                return self._cur.execute(
                    '/*%s*/ %s' % (id(self._connection_wrapper), statement),
                    *args, **kwargs)
            finally:
                _log_statement(
                        starttime, time.time(),
                        self._connection_wrapper, statement
                        )
        except psycopg.ProgrammingError, error:
            if len(error.args):
                errorstr = error.args[0]
                if (errorstr.startswith(
                    'ERROR:  canceling query due to user request') or
                    errorstr.startswith(
                    'ERROR:  canceling statement due to statement timeout')):
                    raise RequestStatementTimedOut(statement)
            raise

    def __getattr__(self, attr):
        return getattr(self._cur, attr)

    def __setattr__(self, attr, value):
        setattr(self._cur, attr, value)
