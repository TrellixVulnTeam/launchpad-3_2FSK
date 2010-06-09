# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import warnings
from datetime import datetime
import re
from textwrap import dedent
import psycopg2
from psycopg2.extensions import (
    ISOLATION_LEVEL_AUTOCOMMIT, ISOLATION_LEVEL_READ_COMMITTED,
    ISOLATION_LEVEL_SERIALIZABLE)
import pytz
import storm
from storm.databases.postgres import compile as postgres_compile
from storm.expr import State
from storm.expr import compile as storm_compile
from storm.locals import Storm, Store
from storm.zope.interfaces import IZStorm

from sqlobject.sqlbuilder import sqlrepr
import transaction

from twisted.python.util import mergeFunctionMetadata

from zope.component import getUtility
from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from canonical.config import config, dbconfig
from canonical.database.interfaces import ISQLBase


__all__ = [
    'alreadyInstalledMsg',
    'begin',
    'block_implicit_flushes',
    'clear_current_connection_cache',
    'commit',
    'ConflictingTransactionManagerError',
    'connect',
    'convert_storm_clause_to_string',
    'cursor',
    'expire_from_cache',
    'flush_database_caches',
    'flush_database_updates',
    'get_transaction_timestamp',
    'ISOLATION_LEVEL_AUTOCOMMIT',
    'ISOLATION_LEVEL_DEFAULT',
    'ISOLATION_LEVEL_READ_COMMITTED',
    'ISOLATION_LEVEL_SERIALIZABLE',
    'quote',
    'quote_like',
    'quoteIdentifier',
    'quote_identifier',
    'RandomiseOrderDescriptor',
    'reset_store',
    'rollback',
    'SQLBase',
    'sqlvalues',
    'StupidCache',
    'ZopelessTransactionManager',]

# Default we want for scripts, and the PostgreSQL default. Note psycopg1 will
# use SERIALIZABLE unless we override, but psycopg2 will not.
ISOLATION_LEVEL_DEFAULT = ISOLATION_LEVEL_READ_COMMITTED


# XXX 20080313 jamesh:
# When quoting names in SQL statements, PostgreSQL treats them as case
# sensitive.  Storm includes a list of reserved words that it
# automatically quotes, which includes a few of our table names.  We
# remove them here due to case mismatches between the DB and Launchpad
# code.
postgres_compile.remove_reserved_words(['language', 'section'])


class StupidCache:
    """A Storm cache that never evicts objects except on clear().

    This class is basically equivalent to Storm's standard Cache class
    with a very large size but without the overhead of maintaining the
    LRU list.

    This provides caching behaviour equivalent to what we were using
    under SQLObject.
    """

    def __init__(self, size):
        self._cache = {}

    def clear(self):
        self._cache.clear()

    def add(self, obj_info):
        if obj_info not in self._cache:
            self._cache[obj_info] = obj_info.get_obj()

    def remove(self, obj_info):
        if obj_info in self._cache:
            del self._cache[obj_info]
            return True
        return False

    def set_size(self, size):
        pass

    def get_cached(self):
        return self._cache.keys()


def _get_sqlobject_store():
    """Return the store used by the SQLObject compatibility layer."""
    # XXX: Stuart Bishop 20080725 bug=253542: The import is here to work
    # around a particularly convoluted circular import.
    from canonical.launchpad.webapp.interfaces import (
            IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)
    return getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)


class LaunchpadStyle(storm.sqlobject.SQLObjectStyle):
    """A SQLObject style for launchpad.

    Python attributes and database columns are lowercase.
    Class names and database tables are MixedCase. Using this style should
    simplify SQLBase class definitions since more defaults will be correct.
    """

    def pythonAttrToDBColumn(self, attr):
        return attr

    def dbColumnToPythonAttr(self, col):
        return col

    def pythonClassToDBTable(self, className):
        return className

    def dbTableToPythonClass(self, table):
        return table

    def idForTable(self, table):
        return 'id'

    def pythonClassToAttr(self, className):
        return className.lower()

    # dsilvers: 20050322: If you take this method out; then RelativeJoin
    # instances in our SQLObject classes cause the following error:
    # AttributeError: 'LaunchpadStyle' object has no attribute
    # 'tableReference'
    def tableReference(self, table):
        """Return the tablename mapped for use in RelativeJoin statements."""
        return table.__str__()


class SQLBase(storm.sqlobject.SQLObjectBase):
    """Base class emulating SQLObject for legacy database classes.
    """
    implements(ISQLBase)
    _style = LaunchpadStyle()

    # Silence warnings in linter script, which complains about all
    # SQLBase-derived objects missing an id.
    id = None

    def __init__(self, *args, **kwargs):
        """Extended version of the SQLObjectBase constructor.

        We we force use of the the master Store.

        We refetch any parameters from different stores from the
        correct master Store.
        """
        from canonical.launchpad.interfaces.lpstorm import IMasterStore
        store = IMasterStore(self.__class__)

        # The constructor will fail if objects from a different Store
        # are passed in. We need to refetch these objects from the correct
        # master Store if necessary so the foreign key references can be
        # constructed.
        # XXX StuartBishop 2009-03-02 bug=336867: We probably want to remove
        # this code - there are enough other places developers have to be
        # aware of the replication # set boundaries. Why should
        # Person(..., account=an_account) work but
        # some_person.account = an_account fail?
        for key, argument in kwargs.items():
            argument = removeSecurityProxy(argument)
            if not isinstance(argument, Storm):
                continue
            argument_store = Store.of(argument)
            if argument_store is not store:
                new_argument = store.find(
                    argument.__class__, id=argument.id).one()
                assert new_argument is not None, (
                    '%s not yet synced to this store' % repr(argument))
                kwargs[key] = new_argument

        store.add(self)
        try:
            self._create(None, **kwargs)
        except:
            store.remove(self)
            raise

    @classmethod
    def _get_store(cls):
        from canonical.launchpad.interfaces.lpstorm import IStore
        return IStore(cls)

    def __repr__(self):
        # XXX jamesh 2008-05-09:
        # This matches the repr() output for the sqlos.SQLOS class.
        # A number of the doctests rely on this formatting.
        return '<%s at 0x%x>' % (self.__class__.__name__, id(self))

    def destroySelf(self):
        from canonical.launchpad.interfaces.lpstorm import IMasterObject
        my_master = IMasterObject(self)
        if self is my_master:
            super(SQLBase, self).destroySelf()
        else:
            my_master.destroySelf()

    def __eq__(self, other):
        """Equality operator.

        Objects compare equal if:
            - They are the same instance, or
            - They have the same class and id, and the id is not None.

        These rules allows objects retrieved from different stores to
        compare equal. The 'is' comparison is to support newly created
        objects that don't yet have an id (and by definition only exist
        in the Master store).
        """
        naked_self = removeSecurityProxy(self)
        naked_other = removeSecurityProxy(other)
        return (
            (naked_self is naked_other)
            or (naked_self.__class__ == naked_other.__class__
                and naked_self.id is not None
                and naked_self.id == naked_other.id))

    def __ne__(self, other):
        """Inverse of __eq__."""
        return not (self == other)

alreadyInstalledMsg = ("A ZopelessTransactionManager with these settings is "
"already installed.  This is probably caused by calling initZopeless twice.")


class ConflictingTransactionManagerError(Exception):
    pass


class ZopelessTransactionManager(object):
    """Compatibility shim for initZopeless()"""

    _installed = None
    _CONFIG_OVERLAY_NAME = 'initZopeless config overlay'

    def __init__(self):
        raise AssertionError("ZopelessTransactionManager should not be "
                             "directly instantiated.")

    @classmethod
    def _get_zopeless_connection_config(self, dbname, dbhost):
        # This method exists for testability.

        # This is only used by scripts, so we must connect to the read-write
        # DB here -- that's why we use rw_main_master directly.
        main_connection_string = dbconfig.rw_main_master

        # Override dbname and dbhost in the connection string if they
        # have been passed in.
        if dbname is not None:
            main_connection_string = re.sub(
                r'dbname=\S*', r'dbname=%s' % dbname, main_connection_string)
        else:
            match = re.search(r'dbname=(\S*)', main_connection_string)
            if match is not None:
                dbname = match.group(1)

        if dbhost is not None:
            main_connection_string = re.sub(
                    r'host=\S*', r'host=%s' % dbhost, main_connection_string)
        else:
            match = re.search(r'host=(\S*)', main_connection_string)
            if match is not None:
                dbhost = match.group(1)
        return main_connection_string, dbname, dbhost

    @classmethod
    def initZopeless(cls, dbname=None, dbhost=None, dbuser=None,
                     isolation=ISOLATION_LEVEL_DEFAULT):
        # Connect to the auth master store as well, as some scripts might need
        # to create EmailAddresses and Accounts.

        main_connection_string, dbname, dbhost = (
            cls._get_zopeless_connection_config(dbname, dbhost))

        assert dbuser is not None, '''
            dbuser is now required. All scripts must connect as unique
            database users.
            '''

        isolation_level = {
            ISOLATION_LEVEL_AUTOCOMMIT: 'autocommit',
            ISOLATION_LEVEL_READ_COMMITTED: 'read_committed',
            ISOLATION_LEVEL_SERIALIZABLE: 'serializable'}[isolation]

        # Construct a config fragment:
        overlay = dedent("""\
            [database]
            rw_main_master: %(main_connection_string)s
            isolation_level: %(isolation_level)s
            """ % vars())

        if dbuser:
            # XXX 2009-05-07 stub bug=373252: Scripts should not be connecting
            # as the launchpad_auth database user.
            overlay += dedent("""\
                [launchpad]
                dbuser: %(dbuser)s
                auth_dbuser: launchpad_auth
                """ % vars())

        if cls._installed is not None:
            if cls._config_overlay != overlay:
                raise ConflictingTransactionManagerError(
                        "A ZopelessTransactionManager with different "
                        "settings is already installed")
            # There's an identical ZopelessTransactionManager already
            # installed, so return that one, but also emit a warning.
            warnings.warn(alreadyInstalledMsg, stacklevel=3)
        else:
            config.push(cls._CONFIG_OVERLAY_NAME, overlay)
            cls._config_overlay = overlay
            cls._dbname = dbname
            cls._dbhost = dbhost
            cls._dbuser = dbuser
            cls._isolation = isolation
            cls._reset_stores()
            cls._installed = cls
        return cls._installed

    @staticmethod
    def _reset_stores():
        """Reset the active stores.

        This is required for connection setting changes to be made visible.
        """
        for name, store in getUtility(IZStorm).iterstores():
            connection = store._connection
            if connection._state == storm.database.STATE_CONNECTED:
                if connection._raw_connection is not None:
                    connection._raw_connection.close()

                # This method assumes that calling transaction.abort() will
                # call rollback() on the store, but this is no longer the
                # case as of jamesh's fix for bug 230977; Stores are not
                # registered with the transaction manager until they are
                # used. While storm doesn't provide an API which does what
                # we want, we'll go under the covers and emit the
                # register-transaction event ourselves. This method is
                # only called by the test suite to kill the existing
                # connections so the Store's reconnect with updated
                # connection settings.
                store._event.emit('register-transaction')

                connection._raw_connection = None
                connection._state = storm.database.STATE_DISCONNECTED
        transaction.abort()

    @classmethod
    def uninstall(cls):
        """Uninstall the ZopelessTransactionManager.

        This entails removing the config overlay and resetting the store.
        """
        assert cls._installed is not None, (
            "ZopelessTransactionManager not installed")
        config.pop(cls._CONFIG_OVERLAY_NAME)
        cls._reset_stores()
        cls._installed = None

    @classmethod
    def set_isolation_level(cls, isolation):
        """Set the transaction isolation level.

        Level can be one of ISOLATION_LEVEL_AUTOCOMMIT,
        ISOLATION_LEVEL_READ_COMMITTED or
        ISOLATION_LEVEL_SERIALIZABLE. As changing the isolation level
        must be done before any other queries are issued in the
        current transaction, this method automatically issues a
        rollback to ensure this is the case.
        """
        assert cls._installed is not None, (
            "ZopelessTransactionManager not installed")
        cls.uninstall()
        cls.initZopeless(cls._dbname, cls._dbhost, cls._dbuser, isolation)

    @staticmethod
    def conn():
        store = _get_sqlobject_store()
        # Use of the raw connection will not be coherent with Storm's
        # cache.
        connection = store._connection
        connection._ensure_connected()
        return connection._raw_connection

    @staticmethod
    def begin():
        """Begin a transaction."""
        transaction.begin()

    @staticmethod
    def commit():
        """Commit the current transaction."""
        transaction.commit()

    @staticmethod
    def abort():
        """Abort the current transaction."""
        transaction.abort()

    @staticmethod
    def registerSynch(synch):
        """Register an ISynchronizer."""
        transaction.manager.registerSynch(synch)

    @staticmethod
    def unregisterSynch(synch):
        """Unregister an ISynchronizer."""
        transaction.manager.unregisterSynch(synch)


def clear_current_connection_cache():
    """Clear SQLObject's object cache. SQLObject compatibility - DEPRECATED.
    """
    _get_sqlobject_store().invalidate()


def expire_from_cache(obj):
    """Expires a single object from the SQLObject cache.
    SQLObject compatibility - DEPRECATED."""
    _get_sqlobject_store().invalidate(obj)


def get_transaction_timestamp():
    """Get the timestamp for the current transaction on the MAIN DEFAULT
    store. DEPRECATED - if needed it should become a method on the store.
    """
    timestamp = _get_sqlobject_store().execute(
        "SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'").get_one()[0]
    return timestamp.replace(tzinfo=pytz.timezone('UTC'))


def quote(x):
    r"""Quote a variable ready for inclusion into an SQL statement.
    Note that you should use quote_like to create a LIKE comparison.

    Basic SQL quoting works

    >>> quote(1)
    '1'
    >>> quote(1.0)
    '1.0'
    >>> quote("hello")
    "'hello'"
    >>> quote("'hello'")
    "'''hello'''"
    >>> quote(r"\'hello")
    "'\\\\''hello'"

    Note that we need to receive a Unicode string back, because our
    query will be a Unicode string (the entire query will be encoded
    before sending across the wire to the database).

    >>> quote(u"\N{TRADE MARK SIGN}")
    u"'\u2122'"

    Timezone handling is not implemented, since all timestamps should
    be UTC anyway.

    >>> from datetime import datetime, date, time
    >>> quote(datetime(2003, 12, 4, 13, 45, 50))
    "'2003-12-04 13:45:50'"
    >>> quote(date(2003, 12, 4))
    "'2003-12-04'"
    >>> quote(time(13, 45, 50))
    "'13:45:50'"

    This function special cases datetime objects, due to a bug that has
    since been fixed in SQLOS (it installed an SQLObject converter that
    stripped the time component from the value).  By itself, the sqlrepr
    function has the following output:

    >>> sqlrepr(datetime(2003, 12, 4, 13, 45, 50), 'postgres')
    "'2003-12-04T13:45:50'"

    This function also special cases set objects, which SQLObject's
    sqlrepr() doesn't know how to handle.

    >>> quote(set([1,2,3]))
    '(1, 2, 3)'
    """
    if isinstance(x, datetime):
        return "'%s'" % x
    elif ISQLBase(x, None) is not None:
        return str(x.id)
    elif isinstance(x, set):
        # SQLObject can't cope with sets, so convert to a list, which it
        # /does/ know how to handle.
        x = list(x)
    return sqlrepr(x, 'postgres')


def quote_like(x):
    r"""Quote a variable ready for inclusion in a SQL statement's LIKE clause

    XXX: StuartBishop 2004-11-24:
    Including the single quotes was a stupid decision.

    To correctly generate a SELECT using a LIKE comparision, we need
    to make use of the SQL string concatination operator '||' and the
    quote_like method to ensure that any characters with special meaning
    to the LIKE operator are correctly escaped.

    >>> "SELECT * FROM mytable WHERE mycol LIKE '%%' || %s || '%%'" \
    ...     % quote_like('%')
    "SELECT * FROM mytable WHERE mycol LIKE '%' || '\\\\%' || '%'"

    Note that we need 2 backslashes to quote, as per the docs on
    the LIKE operator. This is because, unless overridden, the LIKE
    operator uses the same escape character as the SQL parser.

    >>> quote_like('100%')
    "'100\\\\%'"
    >>> quote_like('foobar_alpha1')
    "'foobar\\\\_alpha1'"
    >>> quote_like('hello')
    "'hello'"

    Only strings are supported by this method.

    >>> quote_like(1)
    Traceback (most recent call last):
        [...]
    TypeError: Not a string (<type 'int'>)

    """
    if not isinstance(x, basestring):
        raise TypeError, 'Not a string (%s)' % type(x)
    return quote(x).replace('%', r'\\%').replace('_', r'\\_')


def sqlvalues(*values, **kwvalues):
    """Return a tuple of converted sql values for each value in some_tuple.

    This safely quotes strings, or gives representations of dbschema items,
    for example.

    Use it when constructing a string for use in a SELECT.  Always use
    %s as the replacement marker.

      ('SELECT foo from Foo where bar = %s and baz = %s'
       % sqlvalues(BugTaskSeverity.CRITICAL, 'foo'))

    >>> sqlvalues()
    Traceback (most recent call last):
    ...
    TypeError: Use either positional or keyword values with sqlvalue.
    >>> sqlvalues(1)
    ('1',)
    >>> sqlvalues(1, "bad ' string")
    ('1', "'bad '' string'")

    You can also use it when using dict-style substitution.

    >>> sqlvalues(foo=23)
    {'foo': '23'}

    However, you cannot mix the styles.

    >>> sqlvalues(14, foo=23)
    Traceback (most recent call last):
    ...
    TypeError: Use either positional or keyword values with sqlvalue.

    """ # ' <- fix syntax highlighting
    if (values and kwvalues) or (not values and not kwvalues):
        raise TypeError(
            "Use either positional or keyword values with sqlvalue.")
    if values:
        return tuple(quote(item) for item in values)
    elif kwvalues:
        return dict((key, quote(value)) for key, value in kwvalues.items())


def quote_identifier(identifier):
    r'''Quote an identifier, such as a table name.

    In SQL, identifiers are quoted using " rather than ' which is reserved
    for strings.

    >>> print quoteIdentifier('hello')
    "hello"
    >>> print quoteIdentifier("'")
    "'"
    >>> print quoteIdentifier('"')
    """"
    >>> print quoteIdentifier("\\")
    "\"
    >>> print quoteIdentifier('\\"')
    "\"""
    '''
    return '"%s"' % identifier.replace('"','""')


quoteIdentifier = quote_identifier # Backwards compatibility for now.


def convert_storm_clause_to_string(storm_clause):
    """Convert a Storm expression into a plain string.

    :param storm_clause: A Storm expression

    A helper function allowing to use a Storm expressions in old-style
    code which builds for example WHERE expressions as plain strings.

    >>> from lp.bugs.model.bug import Bug
    >>> from lp.bugs.model.bugtask import BugTask
    >>> from lp.bugs.interfaces.bugtask import BugTaskImportance
    >>> from storm.expr import And, Or

    >>> print convert_storm_clause_to_string(BugTask)
    BugTask

    >>> print convert_storm_clause_to_string(BugTask.id == 16)
    BugTask.id = 16

    >>> print convert_storm_clause_to_string(
    ...     BugTask.importance == BugTaskImportance.UNKNOWN)
    BugTask.importance = 999

    >>> print convert_storm_clause_to_string(Bug.title == "foo'bar'")
    Bug.title = 'foo''bar'''

    >>> print convert_storm_clause_to_string(
    ...     Or(BugTask.importance == BugTaskImportance.UNKNOWN,
    ...        BugTask.importance == BugTaskImportance.HIGH))
    BugTask.importance = 999 OR BugTask.importance = 40

    >>> print convert_storm_clause_to_string(
    ...    And(Bug.title == 'foo', BugTask.bug == Bug.id,
    ...        Or(BugTask.importance == BugTaskImportance.UNKNOWN,
    ...           BugTask.importance == BugTaskImportance.HIGH)))
    Bug.title = 'foo' AND BugTask.bug = Bug.id AND
    (BugTask.importance = 999 OR BugTask.importance = 40)
    """
    state = State()
    clause = storm_compile(storm_clause, state)
    if len(state.parameters):
        parameters = [param.get(to_db=True) for param in state.parameters]
        clause = clause.replace('?', '%s') % sqlvalues(*parameters)
    return clause

def flush_database_updates():
    """Flushes all pending database updates.

    When SQLObject's _lazyUpdate flag is set, then it's possible to have
    changes written to objects that aren't flushed to the database, leading to
    inconsistencies when doing e.g.::

        # Assuming the Beer table already has a 'Victoria Bitter' row...
        assert Beer.select("name LIKE 'Vic%'").count() == 1  # This will pass
        beer = Beer.byName('Victoria Bitter')
        beer.name = 'VB'
        assert Beer.select("name LIKE 'Vic%'").count() == 0  # This will fail

    To avoid this problem, use this function::

        # Assuming the Beer table already has a 'Victoria Bitter' row...
        assert Beer.select("name LIKE 'Vic%'").count() == 1  # This will pass
        beer = Beer.byName('Victoria Bitter')
        beer.name = 'VB'
        flush_database_updates()
        assert Beer.select("name LIKE 'Vic%'").count() == 0  # This will pass

    """
    zstorm = getUtility(IZStorm)
    for name, store in zstorm.iterstores():
        store.flush()


def flush_database_caches():
    """Flush all database caches.

    SQLObject caches field values from the database in SQLObject
    instances.  If SQL statements are issued that change the state of
    the database behind SQLObject's back, these cached values will be
    invalid.

    This function iterates through all the objects in the SQLObject
    connection's cache, and synchronises them with the database.  This
    ensures that they all reflect the values in the database.
    """
    zstorm = getUtility(IZStorm)
    for name, store in zstorm.iterstores():
        store.flush()
        store.invalidate()


def block_implicit_flushes(func):
    """A decorator that blocks implicit flushes on the main store."""
    def block_implicit_flushes_decorator(*args, **kwargs):
        from canonical.launchpad.webapp.interfaces import DisallowedStore
        try:
            store = _get_sqlobject_store()
        except DisallowedStore:
            return func(*args, **kwargs)
        store.block_implicit_flushes()
        try:
            return func(*args, **kwargs)
        finally:
            store.unblock_implicit_flushes()
    return mergeFunctionMetadata(func, block_implicit_flushes_decorator)


def reset_store(func):
    """Function decorator that resets the main store."""
    def reset_store_decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            _get_sqlobject_store().reset()
    return mergeFunctionMetadata(func, reset_store_decorator)


# Some helpers intended for use with initZopeless.  These allow you to avoid
# passing the transaction manager all through your code.

def begin():
    """Begins a transaction."""
    transaction.begin()


def rollback():
    transaction.abort()


def commit():
    transaction.commit()


def connect(user, dbname=None, isolation=ISOLATION_LEVEL_DEFAULT):
    """Return a fresh DB-API connection to the MAIN MASTER database.

    DEPRECATED - if needed, this should become a method on the Store.

    Use None for the user to connect as the default PostgreSQL user.
    This is not the default because the option should be rarely used.

    Default database name is the one specified in the main configuration file.
    """
    con = psycopg2.connect(connect_string(user, dbname))
    con.set_isolation_level(isolation)
    return con


def connect_string(user, dbname=None):
    """Return a PostgreSQL connection string.

    Allows you to pass the generated connection details to external
    programs like pg_dump or embed in slonik scripts.
    """
    from canonical import lp
    # We start with the config string from the config file, and overwrite
    # with the passed in dbname or modifications made by db_options()
    # command line arguments. This will do until db_options gets an overhaul.
    con_str_overrides = []
    # We must connect to the read-write DB here, so we use rw_main_master
    # directly.
    con_str = dbconfig.rw_main_master
    assert 'user=' not in con_str, (
            'Connection string already contains username')
    if user is not None:
        con_str_overrides.append('user=%s' % user)
    if lp.dbhost is not None:
        con_str = re.sub(r'host=\S*', '', con_str) # Remove stanza if exists.
        con_str_overrides.append('host=%s' % lp.dbhost)
    if dbname is None:
        dbname = lp.dbname # Note that lp.dbname may be None.
    if dbname is not None:
        con_str = re.sub(r'dbname=\S*', '', con_str) # Remove if exists.
        con_str_overrides.append('dbname=%s' % dbname)

    con_str = ' '.join([con_str] + con_str_overrides)
    return con_str


class cursor:
    """A DB-API cursor-like object for the Storm connection.

    DEPRECATED - use of this class is deprecated in favour of using
    Store.execute().
    """
    def __init__(self):
        self._connection = _get_sqlobject_store()._connection
        self._result = None

    def execute(self, query, params=None):
        self.close()
        if isinstance(params, dict):
            query = query % sqlvalues(**params)
        elif params is not None:
            query = query % sqlvalues(*params)
        self._result = self._connection.execute(query)

    @property
    def rowcount(self):
        return self._result._raw_cursor.rowcount

    def fetchone(self):
        assert self._result is not None, "No results to fetch"
        return self._result.get_one()

    def fetchall(self):
        assert self._result is not None, "No results to fetch"
        return self._result.get_all()

    def close(self):
        if self._result is not None:
            self._result.close()
            self._result = None
