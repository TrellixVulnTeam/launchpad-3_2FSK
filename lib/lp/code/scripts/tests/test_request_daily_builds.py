#! /usr/bin/python2.5
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the request_daily_builds script"""

import unittest

import transaction

from canonical.launchpad.scripts.tests import run_script
from canonical.launchpad.webapp.errorlog import ErrorReportingUtility
from canonical.testing.layers import ZopelessAppServerLayer
from lp.soyuz.enums import ArchivePurpose
from lp.testing import TestCaseWithFactory


class TestRequestDailyBuilds(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def test_request_daily_builds(self):
        """Ensure the request_daily_builds script requests daily builds."""
        prod_branch = self.factory.makeProductBranch()
        prod_recipe = self.factory.makeSourcePackageRecipe(
            build_daily=True, is_stale=True, branches=[prod_branch])
        pack_branch = self.factory.makePackageBranch()
        pack_recipe = self.factory.makeSourcePackageRecipe(
            build_daily=True, is_stale=True, branches=[pack_branch])
        self.assertEqual(0, prod_recipe.getBuilds(True).count())
        self.assertEqual(0, pack_recipe.getBuilds(True).count())
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/request_daily_builds.py', [])
        self.assertIn('Requested 2 daily builds.', stderr)
        self.assertEqual(1, prod_recipe.getBuilds(True).count())
        self.assertEqual(1, pack_recipe.getBuilds(True).count())
        self.assertFalse(prod_recipe.is_stale)
        self.assertFalse(pack_recipe.is_stale)

    def test_request_daily_builds_oops(self):
        """Ensure errors are handled cleanly."""
        archive = self.factory.makeArchive(purpose=ArchivePurpose.COPY)
        recipe = self.factory.makeSourcePackageRecipe(
            daily_build_archive=archive, build_daily=True)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/request_daily_builds.py', [])
        self.assertEqual(0, recipe.getBuilds(True).count())
        self.assertIn('Requested 0 daily builds.', stderr)
        utility = ErrorReportingUtility()
        utility.configure('request_daily_builds')
        oops = utility.getLastOopsReport()
        self.assertIn('NonPPABuildRequest', oops.tb_text)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
