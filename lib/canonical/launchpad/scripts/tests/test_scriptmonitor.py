# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Test scriptmonitor.py."""

import unittest

from canonical import lp
from canonical.database.sqlbase import connect
from canonical.launchpad.scripts.scriptmonitor import check_script
from canonical.launchpad.scripts import logger
from canonical.testing import DatabaseLayer


class CheckScriptTestCase(unittest.TestCase):
    """Test script activity."""
    layer = DatabaseLayer

    def setUp(self):
        self.con = connect(lp.dbuser)
        self.log = logger()

    def tearDown(self):
        self.con.close()

    def test_scriptfound(self):
        self.assertEqual(
            check_script(self.con, self.log, 'localhost', 'test-script',
                '2007-05-23 00:30:00', '2007-05-23 01:30:00'), None)

    def test_scriptnotfound_timing(self):
        output = ("The script 'test-script' didn't run on "
            "'localhost' between 2007-05-23 01:30:00 and "
            "2007-05-23 02:30:00 (last seen 2007-05-23 01:00:00)")
        self.assertEqual(
            check_script(self.con, self.log, 'localhost', 'test-script',
                '2007-05-23 01:30:00', '2007-05-23 02:30:00'), output)

    def test_scriptnotfound_hostname(self):
        output = ("The script 'test-script' didn't run on "
            "'notlocalhost' between 2007-05-23 00:30:00 and "
            "2007-05-23 01:30:00")
        self.assertEqual(
            check_script(self.con, self.log, 'notlocalhost', 'test-script',
                '2007-05-23 00:30:00', '2007-05-23 01:30:00'), output)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
