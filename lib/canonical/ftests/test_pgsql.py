import unittest
from canonical.ftests.pgsql import PgTestCase, PgTestSetup, ConnectionWrapper
import psycopg

class TestPgTestCase(PgTestCase):

    def testRollback(self):
        # This test creates a table. We run the same test twice,
        # which will fail if database changes are not rolled back
        con = self.connect()
        cur = con.cursor()
        cur.execute('CREATE TABLE foo (x int)')
        cur.execute('INSERT INTO foo VALUES (1)')
        cur.execute('SELECT x FROM foo')
        res = list(cur.fetchall())
        self.failUnless(len(res) == 1)
        self.failUnless(res[0][0] == 1)
        con.commit()

    testRollback2 = testRollback

class TestOptimization(unittest.TestCase):
    def testOptimization(self):
        # Test to ensure that the database is destroyed only when necessary

        # Make a change to a database
        PgTestSetup().setUp()
        try:
            con = PgTestSetup().connect()
            cur = con.cursor()
            cur.execute('CREATE TABLE foo (x int)')
            con.commit()
            # Fake it so the harness doesn't know a change has been made
            ConnectionWrapper.committed = False
        finally:
            PgTestSetup().tearDown()

        # Now check to ensure that the table we just created is still there
        PgTestSetup().setUp()
        try:
            con = PgTestSetup().connect()
            cur = con.cursor()
            # This tests that the table still exists, as well as modifying the
            # db 
            cur.execute('INSERT INTO foo VALUES (1)')
            con.commit()
        finally:
            PgTestSetup().tearDown()

        # Now ensure that the table is gone
        PgTestSetup().setUp()
        try:
            con = PgTestSetup().connect()
            cur = con.cursor()
            cur.execute('CREATE TABLE foo (x int)')
            con.commit()
            ConnectionWrapper.committed = False # Leave the table
        finally:
            PgTestSetup().tearDown()

        # The database should *always* be recreated if the template
        # changes.
        PgTestSetup._last_db = ('whatever', 'launchpad_ftest')
        PgTestSetup().setUp()
        try:
            con = PgTestSetup().connect()
            cur = con.cursor()
            cur.execute('CREATE TABLE foo (x int)')
            con.commit()
        finally:
            PgTestSetup().tearDown()


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestPgTestCase))
    suite.addTest(unittest.makeSuite(TestOptimization))
    return suite

if __name__ == '__main__':
    unittest.main()

