# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from lp.testing import TestCase

from canonical.config import config, dbconfig

from canonical.launchpad.readonly import (
    read_only_file_exists, _remove_read_only_file, _touch_read_only_file)


class TestDatabaseConfig(TestCase):

    def test_overlay(self):
        # The dbconfig option overlays the database configurations of a
        # chosen config section over the base section.
        self.assertRaises(
            AttributeError, getattr, config.database, 'dbuser')
        self.assertRaises(
            AttributeError, getattr, config.launchpad, 'main_master')
        self.assertEquals('launchpad_main', config.launchpad.dbuser)
        self.assertEquals('librarian', config.librarian.dbuser)

        dbconfig.setConfigSection('librarian')
        self.assertEquals('dbname=launchpad_ftest', dbconfig.rw_main_master)
        self.assertEquals('librarian', dbconfig.dbuser)

        dbconfig.setConfigSection('launchpad')
        self.assertEquals('dbname=launchpad_ftest', dbconfig.rw_main_master)
        self.assertEquals('launchpad_main', dbconfig.dbuser)

    def test_required_values(self):
        # Some variables are required to have a value, such as dbuser.  So we
        # get a ValueError if they are not set.
        self.assertRaises(
            AttributeError, getattr, config.codehosting, 'dbuser')
        dbconfig.setConfigSection('codehosting')
        self.assertRaises(ValueError, getattr, dbconfig, 'dbuser')
        dbconfig.setConfigSection('launchpad')

    def test_main_master_and_main_slave(self):
        # DatabaseConfig provides two extra properties: main_master and
        # main_slave property, which return the value of either
        # rw_main_master/rw_main_slave or ro_main_master/ro_main_slave,
        # depending on whether or not we're in read-only mode.
        self.assertFalse(read_only_file_exists())
        self.assertEquals(dbconfig.rw_main_master, dbconfig.main_master)
        self.assertEquals(dbconfig.rw_main_slave, dbconfig.main_slave)

        _touch_read_only_file()
        try:
            self.assertTrue(read_only_file_exists())
            self.assertEquals(
                dbconfig.ro_main_master, dbconfig.main_master)
            self.assertEquals(
                dbconfig.ro_main_slave, dbconfig.main_slave)
        finally:
            _remove_read_only_file()
