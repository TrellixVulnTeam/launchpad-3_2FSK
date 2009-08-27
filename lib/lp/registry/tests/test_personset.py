# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for PersonSet."""

__metaclass__ = type

from unittest import TestCase, TestLoader

from lp.registry.model.person import PersonSet
from canonical.launchpad.ftests import login, logout, ANONYMOUS
from lp.testing.factory import LaunchpadObjectFactory
from canonical.launchpad.testing.databasehelpers import (
    remove_all_sample_data_branches)
from canonical.testing import LaunchpadFunctionalLayer


class TestPersonSetBranchCounts(TestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        login(ANONYMOUS)
        remove_all_sample_data_branches()
        self.factory = LaunchpadObjectFactory()

    def tearDown(self):
        logout()
        TestCase.tearDown(self)

    def test_no_branches(self):
        """Initially there should be no branches."""
        self.assertEqual(0, PersonSet().getPeopleWithBranches().count())

    def test_five_branches(self):
        branches = [self.factory.makeAnyBranch() for x in range(5)]
        # Each branch has a different product, so any individual product
        # will return one branch.
        self.assertEqual(5, PersonSet().getPeopleWithBranches().count())
        self.assertEqual(1, PersonSet().getPeopleWithBranches(
                branches[0].product).count())


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
