# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from StringIO import StringIO
import unittest

import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestCase
from canonical.launchpad.ftests import login
from canonical.launchpad.mail import stub

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.interfaces import (
    IDistributionSet, IDistributionMirrorSet, ILibraryFileAliasSet)
from canonical.lp.dbschema import PackagePublishingPocket, MirrorStatus


class TestDistributionMirror(LaunchpadFunctionalTestCase):

    def setUp(self):
        LaunchpadFunctionalTestCase.setUp(self)
        login('test@canonical.com')
        mirrorset = getUtility(IDistributionMirrorSet)
        self.release_mirror = getUtility(IDistributionMirrorSet).getByName(
            'releases-mirror')
        self.archive_mirror = getUtility(IDistributionMirrorSet).getByName(
            'archive-mirror')
        self.hoary = getUtility(IDistributionSet)['ubuntu']['hoary']
        self.hoary_i386 = self.hoary['i386']

    def _create_source_mirror(self, distrorelease, pocket, component, status):
        source_mirror1 = self.archive_mirror.ensureMirrorDistroReleaseSource(
            distrorelease, pocket, component)
        removeSecurityProxy(source_mirror1).status = status

    def _create_bin_mirror(self, archrelease, pocket, component, status):
        bin_mirror = self.archive_mirror.ensureMirrorDistroArchRelease(
            archrelease, pocket, component)
        removeSecurityProxy(bin_mirror).status = status
        return bin_mirror

    def test_archive_mirror_without_content_should_be_disabled(self):
        self.failUnless(self.archive_mirror.shouldDisable())

    def test_archive_mirror_with_any_content_should_not_be_disabled(self):
        src_mirror1 = self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorStatus.UP)
        flush_database_updates()
        self.failIf(self.archive_mirror.shouldDisable())

    def test_release_mirror_not_missing_content_should_not_be_disabled(self):
        expected_file_count = 1
        mirror = self.release_mirror.ensureMirrorCDImageRelease(
            self.hoary, flavour='ubuntu')
        self.failIf(self.release_mirror.shouldDisable(expected_file_count))

    def test_release_mirror_missing_content_should_be_disabled(self):
        expected_file_count = 1
        self.failUnless(self.release_mirror.shouldDisable(expected_file_count))

    def test_delete_all_mirror_cdimage_releases(self):
        mirror = self.release_mirror.ensureMirrorCDImageRelease(
            self.hoary, flavour='ubuntu')
        mirror = self.release_mirror.ensureMirrorCDImageRelease(
            self.hoary, flavour='edubuntu')
        self.failUnless(self.release_mirror.cdimage_releases.count() == 2)
        self.release_mirror.deleteAllMirrorCDImageReleases()
        self.failUnless(self.release_mirror.cdimage_releases.count() == 0)

    def test_archive_mirror_without_content_status(self):
        self.failIf(self.archive_mirror.source_releases or
                    self.archive_mirror.arch_releases)
        self.failUnless(
            self.archive_mirror.getOverallStatus() == MirrorStatus.UNKNOWN)

    def test_archive_mirror_with_source_content_status(self):
        src_mirror1 = self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorStatus.UP)
        src_mirror2 = self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorStatus.TWODAYSBEHIND)
        flush_database_updates()
        self.failUnless(
            self.archive_mirror.getOverallStatus() == MirrorStatus.TWODAYSBEHIND)

    def test_archive_mirror_with_binary_content_status(self):
        bin_mirror1 = self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorStatus.UP)
        bin_mirror2 = self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorStatus.ONEHOURBEHIND)
        flush_database_updates()
        self.failUnless(
            self.archive_mirror.getOverallStatus() == MirrorStatus.ONEHOURBEHIND)

    def test_archive_mirror_with_binary_and_source_content_status(self):
        bin_mirror1 = self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorStatus.UP)
        bin_mirror2 = self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorStatus.ONEHOURBEHIND)

        src_mirror1 = self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorStatus.UP)
        src_mirror2 = self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorStatus.TWODAYSBEHIND)
        flush_database_updates()

        self.failUnless(
            self.archive_mirror.getOverallStatus() == MirrorStatus.TWODAYSBEHIND)

    def _create_probe_record(self, mirror):
        log_file = StringIO()
        log_file.write("Fake probe, nothing useful here.")
        log_file.seek(0)
        library_alias = getUtility(ILibraryFileAliasSet).create(
            name='foo', size=len(log_file.getvalue()),
            file=log_file, contentType='text/plain')
        proberecord = mirror.newProbeRecord(library_alias)

    def test_disabling_mirror_and_notifying_owner(self):
        LibrarianTestSetup().setUp()
        login('karl@canonical.com')

        mirror = self.release_mirror
        # If a mirror has been probed only once, the owner will always be
        # notified when it's disabled --it doesn't matter whether it was
        # previously enabled or disabled.
        self._create_probe_record(mirror)
        self.failUnless(mirror.enabled)
        mirror.disableAndNotifyOwner()
        # A notification was sent to the owner and other to the mirror admins.
        transaction.commit()
        self.failUnless(len(stub.test_emails) == 2)
        stub.test_emails = []

        mirror.disableAndNotifyOwner()
        # Again, a notification was sent to the owner and other to the mirror
        # admins.
        transaction.commit()
        self.failUnless(len(stub.test_emails) == 2)
        stub.test_emails = []

        # For mirrors that have been probed more than once, we'll only notify
        # the owner if the mirror was previously enabled.
        self._create_probe_record(mirror)
        mirror.enabled = True
        mirror.disableAndNotifyOwner()
        # A notification was sent to the owner and other to the mirror admins.
        transaction.commit()
        self.failUnless(len(stub.test_emails) == 2)
        stub.test_emails = []

        mirror.enabled = False
        mirror.disableAndNotifyOwner()
        # No notifications were sent this time
        transaction.commit()
        self.failUnless(len(stub.test_emails) == 0)
        stub.test_emails = []

        LibrarianTestSetup().tearDown()

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

