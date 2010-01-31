# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the expire-ppa-binaries.py script. """

import pytz
import unittest

from datetime import datetime, timedelta

from zope.component import getUtility

from canonical.config import config
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from canonical.launchpad.scripts import QuietFakeLogger
from lp.soyuz.scripts.expire_ppa_binaries import PPABinaryExpirer
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from canonical.testing.layers import LaunchpadZopelessLayer


class TestPPABinaryExpiry(unittest.TestCase):
    """Test the expire-ppa-binaries.py script."""

    layer = LaunchpadZopelessLayer
    dbuser = config.binaryfile_expire.dbuser

    # We need to test several cases are handled properly:
    #  - publications with no "dateremoved" are not expired
    #  - publications with dateremoved <= 30 days ago are not expired
    #  - publications with dateremoved > 30 days ago are expired
    #  - publications with dateremoved > 30 days ago but refer to a
    #     binary published elsewhere with no dateremoved are not
    #     expired
    #  - publications with dateremoved > 30 days ago but refer to a
    #    binary published elsewhere with dateremoved <= 30 days ago
    #    are not expired
    #  - publications with dateremoved > 30 days ago but refer to a
    #    binary published elsewhere with dateremoved > 30 days ago
    #    are expired.

    def setUp(self):
        """Set up some test publications."""
        # Configure the test publisher.
        self.layer.switchDbUser("launchpad")
        self.stp = SoyuzTestPublisher()
        self.stp.prepareBreezyAutotest()

        # Prepare some date properties for the tests to use.
        self.now = datetime.now(pytz.UTC)
        self.under_threshold_date = self.now - timedelta(days=29)
        self.over_threshold_date = self.now - timedelta(days=31)

        # Prepare two PPAs for the tests to use.
        cprov = getUtility(IPersonSet).getByName('cprov')
        self.ppa = cprov.archive
        mark = getUtility(IPersonSet).getByName('mark')
        self.ppa2 = mark.archive

    def getScript(self, test_args=None):
        """Return a PPABinaryExpirer instance."""
        if test_args is None:
            test_args = []
        test_args.extend(['--expire-after', '30'])
        script = PPABinaryExpirer("test expirer", test_args=test_args)
        script.logger = QuietFakeLogger()
        script.txn = self.layer.txn
        return script

    def runScript(self):
        """Run the expiry script and return."""
        script = self.getScript()
        self.layer.txn.commit()
        self.layer.switchDbUser(self.dbuser)
        script.main()

    def assertBinaryExpired(self, publication):
        self.assertNotEqual(
            publication.binarypackagerelease.files[0].libraryfile.expires,
            None,
            "lfa.expires should be set, but it's not.")

    def assertBinaryNotExpired(self, publication):
        self.assertEqual(
            publication.binarypackagerelease.files[0].libraryfile.expires,
            None,
            "lfa.expires should be None, but it's not.")

    def assertSourceExpired(self, publication):
        self.assertNotEqual(
            publication.sourcepackagerelease.files[0].libraryfile.expires,
            None,
            "lfa.expires should be set, but it's not.")

    def assertSourceNotExpired(self, publication):
        self.assertEqual(
            publication.sourcepackagerelease.files[0].libraryfile.expires,
            None,
            "lfa.expires should be None, but it's not.")

    def testNoExpirationWithNoDateremoved(self):
        """Test that no expiring happens if no dateremoved set."""
        pkg1 = self.stp.getPubSource(
            sourcename="pkg1", architecturehintlist="i386", archive=self.ppa,
            dateremoved=None)
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg1, dateremoved=None, archive=self.ppa)

        self.runScript()
        self.assertSourceNotExpired(pkg1)
        self.assertBinaryNotExpired(pub)

    def testNoExpirationWithDateUnderThreshold(self):
        """Test no expiring if dateremoved too recent."""
        pkg2 = self.stp.getPubSource(
            sourcename="pkg2", architecturehintlist="i386", archive=self.ppa,
            dateremoved=self.under_threshold_date)
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg2, dateremoved=self.under_threshold_date,
            archive=self.ppa)

        self.runScript()
        self.assertSourceNotExpired(pkg2)
        self.assertBinaryNotExpired(pub)

    def testExpirationWithDateOverThreshold(self):
        """Test expiring works if dateremoved old enough."""
        pkg3 = self.stp.getPubSource(
            sourcename="pkg3", architecturehintlist="i386", archive=self.ppa,
            dateremoved=self.over_threshold_date)
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg3, dateremoved=self.over_threshold_date,
            archive=self.ppa)

        self.runScript()
        self.assertSourceExpired(pkg3)
        self.assertBinaryExpired(pub)

    def testNoExpirationWithDateOverThresholdAndOtherValidPublication(self):
        """Test no expiry if dateremoved old enough but other publication."""
        pkg4 = self.stp.getPubSource(
            sourcename="pkg4", architecturehintlist="i386", archive=self.ppa,
            dateremoved=self.over_threshold_date)
        other_source = pkg4.copyTo(
            pkg4.distroseries, pkg4.pocket, self.ppa2)
        other_source.secure_record.dateremoved = None
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg4, dateremoved=self.over_threshold_date,
            archive=self.ppa)
        [other_binary] = pub.copyTo(
            pub.distroarchseries.distroseries, pub.pocket, self.ppa2)
        other_binary.dateremoved = None

        self.runScript()
        self.assertSourceNotExpired(pkg4)
        self.assertBinaryNotExpired(pub)

    def testNoExpirationWithDateOverThresholdAndOtherPubUnderThreshold(self):
        """Test no expiring.

        Test no expiring if dateremoved old enough but other publication
        not over date threshold.
        """
        pkg5 = self.stp.getPubSource(
            sourcename="pkg5", architecturehintlist="i386", archive=self.ppa,
            dateremoved=self.over_threshold_date)
        other_source = pkg5.copyTo(
            pkg5.distroseries, pkg5.pocket, self.ppa2)
        other_source.secure_record.dateremoved = self.under_threshold_date
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg5, dateremoved=self.over_threshold_date,
            archive=self.ppa)
        [other_binary] = pub.copyTo(
            pub.distroarchseries.distroseries, pub.pocket, self.ppa2)
        other_binary.dateremoved = self.under_threshold_date

        self.runScript()
        self.assertSourceNotExpired(pkg5)
        self.assertBinaryNotExpired(pub)

    def _setUpExpirablePublications(self, archive=None):
        """Helper to set up two publications that are both expirable."""
        if archive is None:
            archive = self.ppa
        pkg5 = self.stp.getPubSource(
            sourcename="pkg5", architecturehintlist="i386", archive=archive,
            dateremoved=self.over_threshold_date)
        other_source = pkg5.copyTo(
            pkg5.distroseries, pkg5.pocket, self.ppa2)
        other_source.secure_record.dateremoved = self.over_threshold_date
        [pub] = self.stp.getPubBinaries(
            pub_source=pkg5, dateremoved=self.over_threshold_date,
            archive=archive)
        [other_binary] = pub.copyTo(
            pub.distroarchseries.distroseries, pub.pocket, self.ppa2)
        other_binary.dateremoved = self.over_threshold_date
        return pkg5, pub

    def testNoExpirationWithDateOverThresholdAndOtherPubOverThreshold(self):
        """Test expiring works.

        Test expiring works if dateremoved old enough and other publication
        is over date threshold.
        """
        source, binary = self._setUpExpirablePublications()
        self.runScript()
        self.assertSourceExpired(source)
        self.assertBinaryExpired(binary)

    def testBlacklistingWorks(self):
        """Test that blacklisted PPAs are not expired."""
        source, binary = self._setUpExpirablePublications()
        script = self.getScript()
        script.blacklist = ["cprov",]
        self.layer.txn.commit()
        self.layer.switchDbUser(self.dbuser)
        script.main()
        self.assertSourceNotExpired(source)
        self.assertBinaryNotExpired(binary)

    def testPrivatePPAsNotExpired(self):
        """Test that private PPAs are not expired."""
        self.ppa.private = True
        self.ppa.buildd_secret = "foo"
        source, binary = self._setUpExpirablePublications()
        self.runScript()
        self.assertSourceNotExpired(source)
        self.assertBinaryNotExpired(binary)

    def testDryRun(self):
        """Test that when dryrun is specified, nothing is expired."""
        source, binary = self._setUpExpirablePublications()
        # We have to commit here otherwise when the script aborts it
        # will remove the test publications we just created.
        self.layer.txn.commit()
        script = self.getScript(['--dry-run'])
        self.layer.switchDbUser(self.dbuser)
        script.main()
        self.assertSourceNotExpired(source)
        self.assertBinaryNotExpired(binary)

    def testDoesNotAffectNonPPA(self):
        """Test that expiry does not happen for non-PPA publications."""
        ubuntu_archive = getUtility(IDistributionSet)['ubuntu'].main_archive
        source, binary = self._setUpExpirablePublications(ubuntu_archive)
        self.runScript()
        self.assertSourceNotExpired(source)
        self.assertBinaryNotExpired(binary)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
