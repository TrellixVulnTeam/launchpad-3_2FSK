# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Confirm nobody has broken sampledata.

By editing the sampledata manually, it is possible to corrupt the data
silently switching off some of our constraints. We can detect this by
doing a dump and restore - this will fail if the data is corrupt.
"""

__metaclass__ = type
__all__ = []

import subprocess
import unittest

from canonical.testing.layers import DatabaseLayer
from lp.testing import TestCase

class SampleDataTestCase(TestCase):
    layer = DatabaseLayer

    def tearDown(self):
        DatabaseLayer.force_dirty_database()
        super(SampleDataTestCase, self).tearDown()

    def test_testSampledata(self):
        """Test the sample data used by the test suite."""
        self.dump_and_restore('launchpad_ftest_template')

    def disabled_test_devSampledata(self):
        """Test the sample data used by developers for manual testing."""
        self.dump_and_restore('launchpad_dev_template')

    def dump_and_restore(self, source_dbname):
        cmd = (
            "pg_dump --format=c --compress=0 --no-privileges --no-owner"
            " --schema=public %s | pg_restore --clean --single-transaction"
            " --exit-on-error --dbname=launchpad_ftest" % source_dbname)
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE)
        (stdout, stderr) = proc.communicate()
        rv = proc.wait()
        self.failUnlessEqual(rv, 0, "Dump/Restore failed: %s" % stdout)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
