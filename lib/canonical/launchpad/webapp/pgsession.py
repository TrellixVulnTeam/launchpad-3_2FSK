# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""PostgreSQL server side session storage for Zope3."""

__metaclass__ = type

import time
import psycopg
import cPickle as pickle
from UserDict import DictMixin
from random import random
from datetime import datetime, timedelta

from zope.component import getUtility
from zope.interface import implements
from zope.app.rdb.interfaces import IZopeDatabaseAdapter
from zope.app.session.interfaces import (
        ISessionDataContainer, ISessionData, ISessionPkgData
        )
from psycopgda.adapter import PG_ENCODING

SECONDS = 1
MINUTES = 60 * SECONDS
HOURS = 60 * MINUTES
DAYS = 24 * HOURS

class PGSessionDataContainer:
    """An ISessionDataContainer that stores data in PostgreSQL
    
    PostgreSQL Schema:

    CREATE TABLE SessionData (
        client_id     text PRIMARY KEY,
        last_accessed timestamp with time zone
            NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    CREATE INDEX sessiondata_last_accessed_idx ON SessionData(last_accessed);
    CREATE TABLE SessionPkgData (
        client_id  text NOT NULL
            REFERENCES SessionData(client_id) ON DELETE CASCADE,
        product_id text NOT NULL,
        key        text NOT NULL,
        pickle     bytea NOT NULL,
        CONSTRAINT sessiondata_key UNIQUE (client_id, product_id, key)
        );
    """
    implements(ISessionDataContainer)

    timeout = 60 * DAYS
    # If we have a low enough resolution, we can determine active users
    # using the session data.
    resolution = 9 * MINUTES

    session_data_table_name = 'SessionData'
    session_pkg_data_table_name = 'SessionPkgData'
    database_adapter_name = 'session'

    @property
    def cursor(self):
        da = getUtility(IZopeDatabaseAdapter, self.database_adapter_name)
        return da().cursor()

    def __getitem__(self, client_id):
        """See zope.app.session.interfaces.ISessionDataContainer"""
        cursor = self.cursor
        self._sweep(cursor)
        # Ensure the row in session_data_table_name exists in the database.
        # __setitem__ handles this for us.
        self[client_id] = 'ignored'
        return PGSessionData(self, client_id)

    def __setitem__(self, client_id, session_data):
        """See zope.app.session.interfaces.ISessionDataContainer"""
        query = """
            INSERT INTO %s (client_id)
                SELECT %%(client_id)s WHERE NOT EXISTS (
                    SELECT TRUE FROM %s WHERE client_id=%%(client_id)s
                    )
            """ % (self.session_data_table_name, self.session_data_table_name)
        self.cursor.execute(query, vars())

    _last_sweep = datetime.utcnow()
    fuzz = 10 # Our sweeps may occur +- this many seconds to minimize races.

    def _sweep(self, cursor):
        interval = timedelta(
                seconds=self.resolution - self.fuzz + 2 * self.fuzz * random()
                )
        now = datetime.utcnow()
        if self._last_sweep + interval > now:
            return
        self._last_sweep = now
        query = """
            DELETE FROM SessionData WHERE last_accessed
                < CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - '%d seconds'::interval
            """ % self.timeout
        cursor = self.cursor
        cursor.execute(query)


class PGSessionData:
    implements(ISessionData)

    session_data_container = None

    lastAccessTime = None

    def __init__(self, session_data_container, client_id):
        self.session_data_container = session_data_container
        self.client_id = client_id
        self.lastAccessTime = time.time()

        # Update the last access time in the db if it is out of date
        table_name = session_data_container.session_data_table_name
        query = """
            UPDATE %s SET last_accessed = CURRENT_TIMESTAMP
            WHERE client_id = %%s
            AND last_accessed < CURRENT_TIMESTAMP - '%d seconds'::interval
            """ % (table_name, session_data_container.resolution)
        self.cursor.execute(query, [client_id.encode(PG_ENCODING)])

    @property
    def cursor(self):
        return self.session_data_container.cursor

    def __getitem__(self, product_id):
        """Return an ISessionPkgData"""
        return PGSessionPkgData(self, product_id)

    def __setitem__(self, product_id, session_pkg_data):
        """See zope.app.session.interfaces.ISessionData
        
        This is a noop in the RDBMS implementation.
        """
        pass


class PGSessionPkgData(DictMixin):
    implements(ISessionPkgData)

    @property
    def cursor(self):
        return self.session_data.cursor

    def __init__(self, session_data, product_id):
        self.session_data = session_data
        self.product_id = product_id
        self.table_name = \
                session_data.session_data_container.session_pkg_data_table_name
        self._populate()

    _data_cache = None

    def _populate(self):
        self._data_cache = {}
        query = """
            SELECT key, pickle FROM %s WHERE client_id = %%(client_id)s
                AND product_id = %%(product_id)s
            """ % self.table_name
        client_id = self.session_data.client_id.encode(PG_ENCODING)
        product_id = self.product_id.encode(PG_ENCODING)
        cursor = self.cursor
        cursor.execute(query, vars())
        for key, pickled_value in cursor.fetchall():
            key = key.decode(PG_ENCODING)
            value = pickle.loads(pickled_value)
            self._data_cache[key] = value

    def __getitem__(self, key):
        return self._data_cache[key]

    def __setitem__(self, key, value):
        pickled_value = psycopg.Binary(
                pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
                )
        cursor = self.cursor

        org_key = key

        key = key.encode(PG_ENCODING)
        client_id = self.session_data.client_id.encode(PG_ENCODING)
        product_id = self.product_id.encode(PG_ENCODING)
        table = self.table_name

        # Insert a new row into table_name if one does not already exist
        query = """
            INSERT INTO %(table)s (client_id, product_id, key, pickle) SELECT
                %%(client_id)s, %%(product_id)s, %%(key)s, %%(pickled_value)s
                WHERE NOT EXISTS (
                    SELECT TRUE FROM %(table)s WHERE client_id = %%(client_id)s
                        AND product_id = %%(product_id)s AND key = %%(key)s
                    )
            """ % vars()
        cursor.execute(query, vars())

        # Update any existing row in table_name if it has changed
        query = """
            UPDATE %(table)s SET pickle = %%(pickled_value)s
                WHERE client_id = %%(client_id)s
                    AND product_id = %%(product_id)s AND key = %%(key)s
                    AND pickle <> %%(pickled_value)s
            """ % vars()
        cursor.execute(query, vars())

        # Store the value in the cache too
        self._data_cache[org_key] = value

    def __delitem__(self, key):
        """Delete an item.
        
        Note that this will never fail in order to avoid
        race conditions in code using the session machinery
        """
        try:
            del self._data_cache[key]
        except KeyError:
            # Not in the cache, then it won't be in the DB. Or if it is,
            # another process has inserted it and we should keep our grubby
            # fingers out of it.
            return
        query = """
            DELETE FROM %s WHERE client_id = %%(client_id)s
                AND product_id = %%(product_id)s AND key = %%(key)s
            """ % self.table_name
        client_id = self.session_data.client_id.encode(PG_ENCODING)
        product_id = self.product_id.encode(PG_ENCODING)
        key = key.encode(PG_ENCODING)
        cursor = self.cursor
        cursor.execute(query, vars())

    def keys(self):
        return self._data_cache.keys()


data_container = PGSessionDataContainer()
