# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the ppa-add-missing-builds.py script. """

import os
import subprocess
import sys

from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.scripts.ppa_add_missing_builds import PPAMissingBuilds
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory

from canonical.config import config
from canonical.database.sqlbase import (
    flush_database_updates, clear_current_connection_cache)
from canonical.launchpad.scripts import QuietFakeLogger
from canonical.testing.layers import LaunchpadZopelessLayer


class TestPPAAddMissingBuilds(TestCaseWithFactory):
    """Test the ppa-add-missing-builds.py script. """

    layer = LaunchpadZopelessLayer
    dbuser = config.builddmaster.dbuser

    def setUp(self):
        """Make a PPA and publish some sources that need builds."""
        TestCaseWithFactory.setUp(self)
        self.stp = SoyuzTestPublisher()
        self.stp.prepareBreezyAutotest()

        # i386 and hppa are enabled by STP but we need to mark hppa as
        # PPA-enabled.
        self.stp.breezy_autotest_hppa.supports_virtualized = True

        # Create an arch-any and an arch-all source in a PPA.
        self.ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.all = self.stp.getPubSource(
            sourcename="all", architecturehintlist="all", archive=self.ppa,
            status=PackagePublishingStatus.PUBLISHED)
        self.any = self.stp.getPubSource(
            sourcename="any", architecturehintlist="any", archive=self.ppa,
            status=PackagePublishingStatus.PUBLISHED)
        self.required_arches = [
            self.stp.breezy_autotest_hppa,
            self.stp.breezy_autotest_i386]

    def runScript(self, test_args=None):
        """Run the script itself, returning the result and output.

        Return a tuple of the process's return code, stdout output and
        stderr output.
        """
        if test_args is None:
            test_args = []
        script = os.path.join(
            config.root, "scripts", "ppa-add-missing-builds.py")
        args = [sys.executable, script]
        args.extend(test_args)
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return (process.returncode, stdout, stderr)

    def getScript(self):
        """Return an instance of the script object."""
        script = PPAMissingBuilds("test", test_args=[])
        script.logger = QuietFakeLogger()
        return script

    def getBuilds(self):
        """Helper to return build records."""
        any_build_i386 = self.any.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_i386, self.ppa)
        any_build_hppa = self.any.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_hppa, self.ppa)
        all_build_i386 = self.all.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_i386, self.ppa)
        all_build_hppa = self.all.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_hppa, self.ppa)
        return (
            any_build_i386, any_build_hppa, all_build_i386, all_build_hppa)

    def assertBuildsForAny(self):
        """Helper to assert that builds were created for the 'Any' package."""
        (
            any_build_i386, any_build_hppa, all_build_i386,
            all_build_hppa
            ) = self.getBuilds()
        self.assertIsNot(any_build_i386, None)
        self.assertIsNot(any_build_hppa, None)

    def assertNoBuilds(self):
        """Helper to assert that no builds were created."""
        (
            any_build_i386, any_build_hppa, all_build_i386,
            all_build_hppa
            ) = self.getBuilds()
        self.assertIs(any_build_i386, None)
        self.assertIs(any_build_hppa, None)
        self.assertIs(all_build_i386, None)
        self.assertIs(all_build_hppa, None)

    def testSimpleRun(self):
        """Try a simple script run.

        This test ensures that the script starts up and runs.
        It should create some missing builds.
        """
        # Commit the changes made in setUp()
        self.layer.txn.commit()

        args = [
            "-d", "ubuntutest",
            "-s", "breezy-autotest",
            "-a", "i386",
            "-a", "hppa",
            "--owner", "%s" % self.ppa.owner.name,
            ]
        code, stdout, stderr = self.runScript(args)
        self.assertEqual(
            code, 0,
            "The script returned with a non zero exit code: %s\n%s\n%s"  % (
                code, stdout, stderr))

        # Sync database changes made in the external process.
        flush_database_updates()
        clear_current_connection_cache()

        # The arch-any package will get builds for all architectures.
        self.assertBuildsForAny()

        # The arch-all package is architecture-independent, so it will
        # only get a build for i386 which is the nominated architecture-
        # independent build arch.
        all_build_i386 = self.all.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_i386, self.ppa)
        all_build_hppa = self.all.sourcepackagerelease.getBuildByArch(
            self.stp.breezy_autotest_hppa, self.ppa)
        self.assertIsNot(all_build_i386, None)
        self.assertIs(all_build_hppa, None)

    def testNoActionForNoSources(self):
        """Test that if nothing is published, no builds are created."""
        self.all.requestDeletion(self.ppa.owner)
        self.any.requestDeletion(self.ppa.owner)

        script = self.getScript()
        script.add_missing_ppa_builds(
            self.ppa, self.required_arches, self.stp.breezy_autotest)
        self.assertNoBuilds()
