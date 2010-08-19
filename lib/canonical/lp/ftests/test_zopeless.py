# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Tests to make sure that initZopeless works as expected.
"""

from doctest import DocTestSuite
from threading import Thread
import unittest
import warnings

import psycopg2
from sqlobject import StringCol, IntCol

from canonical.database.sqlbase import SQLBase, alreadyInstalledMsg, cursor
from canonical.ftests.pgsql import PgTestSetup
from canonical.lp import initZopeless
from canonical.testing import LaunchpadScriptLayer


class MoreBeer(SQLBase):
    '''Simple SQLObject class used for testing'''
    # test_sqlos defines a Beer SQLObject already, so we call this one
    # MoreBeer to avoid confusing SQLObject.
    name = StringCol(alternateID=True, notNull=True)
    rating = IntCol(default=None)


class TestInitZopeless(unittest.TestCase):
    layer = LaunchpadScriptLayer

    def test_initZopelessTwice(self):
        # Hook the warnings module, so we can verify that we get the expected
        # warning.  The warnings module has two key functions, warn and
        # warn_explicit, the first calling the second. You might, therefore,
        # think that we should hook the second, to catch all warnings in one
        # place.  However, from Python 2.6, both of these are replaced with
        # entries into a C extension if available, and the C implementation of
        # the first will not call a monkeypatched Python implementation of the
        # second.  Therefore, we hook warn, as is the one actually called by
        # the particular code we are interested in testing.
        original_warn = warnings.warn
        warnings.warn = self.warn_hooked
        self.warned = False
        try:
            # Calling initZopeless with the same arguments twice should return
            # the exact same object twice, but also emit a warning.
            try:
                tm1 = initZopeless(dbname=PgTestSetup().dbname, dbhost='',
                        dbuser='launchpad')
                tm2 = initZopeless(dbname=PgTestSetup().dbname, dbhost='',
                        dbuser='launchpad')
                self.failUnless(tm1 is tm2)
                self.failUnless(self.warned)
            finally:
                tm1.uninstall()
        finally:
            # Put the warnings module back the way we found it.
            warnings.warn = original_warn

    def warn_hooked(self, message, category=None, stacklevel=1):
        self.failUnlessEqual(alreadyInstalledMsg, str(message))
        self.warned = True


class TestZopeless(unittest.TestCase):
    layer = LaunchpadScriptLayer

    def setUp(self):
        self.tm = initZopeless(dbname=PgTestSetup().dbname,
                               dbuser='launchpad')

        c = cursor()
        c.execute("CREATE TABLE morebeer ("
                  "  id SERIAL PRIMARY KEY,"
                  "  name text NOT NULL UNIQUE,"
                  "  rating integer"
                  ")")
        self.tm.commit()

    def tearDown(self):
        self.tm.uninstall()

    def test_simple(self):
        # Create a few MoreBeers and make sure we can access them
        b = MoreBeer(name='Victoria Bitter')
        id1 = b.id
        b = MoreBeer(name='XXXX')
        id2 = b.id

        b = MoreBeer.get(id1)
        b.rating = 3
        b = MoreBeer.get(id2)
        b.rating = 2

        b = MoreBeer.get(id1)
        self.failUnlessEqual(b.rating, 3)

    def test_multipleTransactions(self):
        # Here we create a MoreBeer and make modifications in a number
        # of different transactions

        b = MoreBeer(name='Victoria Bitter')
        id = b.id
        self.tm.commit()

        b = MoreBeer.get(id)
        self.failUnlessEqual(b.name, 'Victoria Bitter')
        b.rating = 4
        self.tm.commit()

        b = MoreBeer.get(id)
        self.failUnlessEqual(b.rating, 4)
        b.rating = 5
        self.tm.commit()

        b = MoreBeer.get(id)
        self.failUnlessEqual(b.rating, 5)
        b.rating = 2
        self.tm.abort()

        b = MoreBeer.get(id)
        self.failUnlessEqual(b.rating, 5)
        b.rating = 4
        self.tm.commit()

        b = MoreBeer.get(id)
        self.failUnlessEqual(b.rating, 4)

    def test_threads(self):
        # Here we create a number of MoreBeers in seperate threads
        def doit():
            self.tm.begin()
            b = MoreBeer(name=beer_name)
            b.rating = beer_rating
            self.tm.commit()

        beer_name = 'Victoria Bitter'
        beer_rating = 4
        t = Thread(target=doit)
        t.start()
        t.join()

        beer_name = 'Singa'
        beer_rating = 6
        t = Thread(target=doit)
        t.start()
        t.join()

        # And make sure they are both seen
        beers = MoreBeer.select()
        self.failUnlessEqual(beers.count(), 2)
        self.tm.commit()

    def test_exception(self):

        # We have observed if a database transaction ends badly, it is
        # not reset for future transactions. To test this, we cause
        # a database exception
        beer1 = MoreBeer(name='Victoria Bitter')
        beer1.syncUpdate()
        try:
            beer2 = MoreBeer(name='Victoria Bitter')
            beer2.syncUpdate()
        except psycopg2.DatabaseError:
            pass
        else:
            self.fail('Unique constraint was not triggered')
        self.tm.abort()

        # Now start a new transaction and see if we can do anything
        self.tm.begin()
        beer3 = MoreBeer(name='Singa')
        beer3.syncUpdate()

    def test_externalChange(self):
        # Make a change
        MoreBeer(name='Victoria Bitter')

        # Commit our local change
        self.tm.commit()

        # Make another change from a non-SQLObject connection, and commit that
        conn = psycopg2.connect('dbname=' + PgTestSetup().dbname)
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION;")
        cur.execute("UPDATE MoreBeer SET rating=4 "
                    "WHERE name='Victoria Bitter';")
        cur.execute("COMMIT TRANSACTION;")
        cur.close()
        conn.close()

        # We should now be able to see the external change in our connection
        self.failUnlessEqual(4, MoreBeer.byName('Victoria Bitter').rating)


def test_isZopeless():
    """
    >>> from canonical.lp import isZopeless

    >>> isZopeless()
    False

    >>> tm = initZopeless(dbname=PgTestSetup().dbname,
    ...     dbhost='', dbuser='launchpad')
    >>> isZopeless()
    True

    >>> tm.uninstall()
    >>> isZopeless()
    False

    """

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestZopeless))
    suite.addTest(unittest.makeSuite(TestInitZopeless))
    doctests = DocTestSuite()
    doctests.layer = LaunchpadScriptLayer
    suite.addTest(doctests)
    return suite
