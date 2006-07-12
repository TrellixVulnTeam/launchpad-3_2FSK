# Copyright 2006 Canonical Ltd.  All rights reserved.
""" Test layers

Note that many tests are performed at run time in the layers themselves
to confirm that the environment hasn't been corrupted by tests
"""
__metaclass__ = type

from cStringIO import StringIO
import psycopg
from urllib import urlopen
import unittest

from zope.component import getUtility, ComponentLookupError

from canonical.config import config
from canonical.librarian.client import LibrarianClient, UploadFailed
from canonical.librarian.interfaces import ILibrarianClient
from canonical.testing.layers import (
        Base, Librarian, Database, Functional, Zopeless,
        Launchpad, LaunchpadFunctional, LaunchpadZopeless
        )

class BaseTestCase(unittest.TestCase):
    """Both the Base layer tests, as well as the base Test Case
    for all the other Layer tests.
    """
    layer = Base

    # These flags will be overridden in subclasses to describe the
    # environment they expect to have available.
    want_component_architecture = False
    want_librarian_running = False
    want_launchpad_database = False
    want_functional_flag = False
    want_zopeless_flag = False

    def testBaseIsSetUpFlag(self):
        self.failUnlessEqual(Base.isSetUp, True)

    def testFunctionalIsSetUp(self):
        self.failUnlessEqual(Functional.isSetUp, self.want_functional_flag)

    def testZopelessIsSetUp(self):
        self.failUnlessEqual(Zopeless.isSetUp, self.want_zopeless_flag)

    def testComponentArchitecture(self):
        try:
            getUtility(ILibrarianClient)
        except ComponentLookupError:
            self.failIf(
                    self.want_component_architecture,
                    'Component Architecture should be available.'
                    )
        else:
            self.failUnless(
                    self.want_component_architecture,
                    'Component Architecture should not be available.'
                    )

    def testLibrarianRunning(self):
        # Check that the librarian is running. Note that even if the
        # librarian is running, it may not be able to actually store
        # or retrieve files if, for example, the Launchpad database is
        # not currently available.
        try:
            urlopen(config.librarian.download_url).read()
            self.failUnless(
                    self.want_librarian_running,
                    'Librarian should not be running.'
                    )
        except IOError:
            self.failIf(
                    self.want_librarian_running,
                    'Librarian should be running.'
                    )

    def testLibrarianWorking(self):
        # Check that the librian is actually working. This means at
        # a minimum the Librarian service is running and is connected
        # to the Launchpad database.
        want_librarian_working = (
                self.want_librarian_running and self.want_launchpad_database
                and self.want_component_architecture
                )
        client = LibrarianClient()
        data = 'Whatever'
        try:
            file_alias_id = client.addFile(
                    'foo.txt', len(data), StringIO(data), 'text/plain'
                    )
        except UploadFailed:
            self.failIf(
                    want_librarian_working,
                    'Librarian should be fully operational'
                    )
        except AttributeError:
            self.failIf(
                    want_librarian_working,
                    'Librarian not operational as component architecture '
                    'not loaded'
                    )
        else:
            self.failUnless(
                    want_librarian_working,
                    'Librarian should not be operational'
                    )

    def testLaunchpadDbAvailable(self):
        try:
            con = Database.connect()
            cur = con.cursor()
            cur.execute("SELECT id FROM Person LIMIT 1")
            if cur.fetchone() is not None:
                self.failUnless(
                        self.want_launchpad_database,
                        'Launchpad database should not be available.'
                        )
                return
        except psycopg.Error:
            pass
        self.failIf(
                self.want_launchpad_database,
                'Launchpad database should be available but is not.'
                )


class LibrarianTestCase(BaseTestCase):
    layer = Librarian

    want_librarian_running = True

    def testUploadsFail(self):
        # This layer is not particularly useful by itself, as the Librarian
        # cannot function correctly as there is no database setup.
        # We can test this using remoteAddFile (it does not need the CA loaded)
        client = LibrarianClient()
        data = 'This is a test'
        self.failUnlessRaises(
                UploadFailed, client.remoteAddFile,
                'foo.txt', len(data), StringIO(data), 'text/plain'
                )


class LibrarianNoResetTestCase(unittest.TestCase):
    """Our page tests need to run multple tests without destroying
    the librarian database in between.
    """
    layer = Launchpad

    sample_data = 'This is a test'

    def testNoReset1(self):
        # Inform the librarian not to reset the library until we say
        # otherwise
        Librarian._reset_between_tests = False

        # Add a file for testNoReset2. We use remoteAddFile because
        # it does not need the CA loaded to work.
        client = LibrarianClient()
        LibrarianTestCase.url = client.remoteAddFile(
                self.sample_data, len(self.sample_data),
                StringIO(self.sample_data), 'text/plain'
                )
        self.failUnlessEqual(
                urlopen(LibrarianTestCase.url).read(), self.sample_data
                )

    def testNoReset2(self):
        # The file added by testNoReset1 should be there
        self.failUnlessEqual(
                urlopen(LibrarianTestCase.url).read(), self.sample_data
                )
        # Restore this - keeping state is our responsibility
        Librarian._reset_between_tests = True

    def testNoReset3(self):
        # The file added by testNoReset1 should be gone
        # XXX: We should get a DownloadFailed exception here, as per
        # Bug #51370 -- StuartBishop 20060630
        data = urlopen(LibrarianTestCase.url).read()
        self.failIfEqual(data, self.sample_data)


class DatabaseTestCase(BaseTestCase):
    layer = Database

    want_launchpad_database = True

    def testConnect(self):
        Database.connect()

    def getWikinameCount(self, con):
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM Wikiname")
        num = cur.fetchone()[0]
        return num

    def testNoReset1(self):
        # Ensure that we can switch off database resets between tests
        # if necessary, such as used by the page tests
        Database._reset_between_tests = False
        con = Database.connect()
        cur = con.cursor()
        cur.execute("DELETE FROM Wikiname")
        self.failUnlessEqual(self.getWikinameCount(con), 0)
        con.commit()

    def testNoReset2(self):
        # Wikiname table was emptied by testNoReset1 and should still
        # contain nothing.
        con = Database.connect()
        self.failUnlessEqual(self.getWikinameCount(con), 0)
        # Note we don't need to commit, but we do need to force
        # a reset!
        Database._reset_between_tests = True
        Database.force_dirty_database()

    def testNoReset3(self):
        # Wikiname table should contain data again
        con = Database.connect()
        self.failIfEqual(self.getWikinameCount(con), 0)


class LaunchpadTestCase(BaseTestCase):
    layer = Launchpad

    want_launchpad_database = True
    want_librarian_running = True


class FunctionalTestCase(BaseTestCase):
    layer = Functional

    want_component_architecture = True
    want_functional_flag = True


class ZopelessTestCase(BaseTestCase):
    layer = Zopeless

    want_component_architecture = True
    want_launchpad_database = True
    want_librarian_running = True
    want_zopeless_flag = True


class LaunchpadFunctionalTestCase(BaseTestCase):
    layer = LaunchpadFunctional

    want_component_architecture = True
    want_launchpad_database = True
    want_librarian_running = True
    want_functional_flag = True


class LaunchpadZopeless(BaseTestCase):
    layer = LaunchpadZopeless

    want_component_architecture = True
    want_launchpad_database = True
    want_librarian_running = True
    want_zopeless_flag = True


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
    
