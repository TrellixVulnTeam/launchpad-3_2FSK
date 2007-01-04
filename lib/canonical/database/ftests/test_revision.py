# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Tests for the revision module."""

__metaclass__ = type
__all__ = []

from glob import glob
import os
import os.path
import re
import unittest

from canonical.config import config
from canonical.database.sqlbase import cursor
from canonical.database.revision import *
from canonical.testing import LaunchpadZopelessLayer

class TestRevision(unittest.TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        schema_dir = os.path.join(config.root, 'database', 'schema')
        baseline = glob(os.path.join(schema_dir, 'launchpad-??-00-0.sql'))[0]
        match = re.search('launchpad-(\d\d)-00-0.sql', baseline)
        self.major = int(match.group(1))

    def test_confirm_dbrevision(self):
        # Function should not raise an exception with a fresh Launchpad
        # database. This test will fail if the test database is old and
        # needs to be rebuilt.
        confirm_dbrevision()

    def test_confirm_dbrevision2(self):
        # Create a fake database patch on the file system and confirm
        # an exception is raised
        path = os.path.join(
                config.root, 'database', 'schema',
                'patch-%02d-96-0.sql' % self.major
                )
        self.failIf(
                os.path.exists(path),
                '%s already exists but it is reserved for this test' % path
                )
        open(path, 'w').close()
        try:
            self.failUnlessRaises(InvalidDatabaseRevision, confirm_dbrevision)
        finally:
            os.remove(path)

    def test_confirm_dbrevision3(self):
        # Create a record of a fake database patch that does not exist on the
        # filesystem and onfirm an exception is raised
        cur = cursor()
        cur.execute(
                "INSERT INTO LaunchpadDatabaseRevision VALUES (%s, 96, 0)",
                (self.major,)
                )
        self.failUnlessRaises(InvalidDatabaseRevision, confirm_dbrevision)

    def test_confirm_dbrevision4(self):
        # Create a record of a fake database patch of the sort that is
        # applied to the live systems (non zero 'patch' number). It
        # should not raise an exeption in this case.
        cur = cursor()
        cur.execute(
                "INSERT INTO LaunchpadDatabaseRevision VALUES (%s, 96, 1)",
                (self.major,)
                )
        confirm_dbrevision()

    def test_confirm_dbrevision5(self):
        # Records of earlier 'major' patches stored in the database are
        # ignored.
        cur = cursor()
        cur.execute(
                "INSERT INTO LaunchpadDatabaseRevision VALUES (%s, 96, 0)",
                (self.major-1,)
                )
        confirm_dbrevision()

    def test_confirm_dbrevision6(self):
        # Records of later 'major' patches stored in the database are
        # not ignored.
        cur = cursor()
        cur.execute(
                "INSERT INTO LaunchpadDatabaseRevision VALUES (%s, 96, 0)",
                (self.major+1,)
                )
        self.failUnlessRaises(InvalidDatabaseRevision, confirm_dbrevision)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestRevision))
    return suite

