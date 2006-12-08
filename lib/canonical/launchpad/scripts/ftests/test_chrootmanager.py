# Copyright 2006 Canonical Ltd.  All rights reserved.
"""ChrootManager facilities tests."""

__metaclass__ = type

from unittest import TestCase, TestLoader
import os
import sys
import tempfile

from zope.component import getUtility

from canonical.config import config
from canonical.database.sqlbase import commit
from canonical.launchpad.interfaces import IDistributionSet
from canonical.launchpad.scripts.ftpmaster import (
    ChrootManager, ChrootManagerError)
from canonical.lp.dbschema import PackagePublishingPocket
from canonical.testing import LaunchpadZopelessLayer

class TestChrootManager(TestCase):
    layer = LaunchpadZopelessLayer
    dbuser = 'lucille'

    def setUp(self):
        """Setup the test environment and retrieve useful instances."""
        self.files_to_delete = []
        self.distribution = getUtility(IDistributionSet)['ubuntu']
        self.distroarchrelease = self.distribution.currentrelease['i386']
        self.pocket = PackagePublishingPocket.SECURITY

    def tearDown(self):
        """Clean up test environment and remove the test archive."""
        self._remove_files()

    def _create_file(self, filename, content=None):
        """Create a file in the system temporary directory.

        Annotate the path for posterior removal (see _remove_files)
        """
        filepath = os.path.join(tempfile.gettempdir(), filename)
        if content is not None:
            fd = open(filepath, "w")
            fd.write(content)
            fd.close()

        self.files_to_delete.append(filepath)
        return filepath

    def _remove_files(self):
        """Remove files during this test."""
        for filepath in self.files_to_delete:
            os.remove(filepath)

        self.files_to_delete = []

    def test_initialize(self):
        """Chroot Manager initialization"""
        chroot_manager = ChrootManager(self.distroarchrelease, self.pocket)

        self.assertEqual(self.distroarchrelease,
                         chroot_manager.distroarchrelease)
        self.assertEqual(self.pocket, chroot_manager.pocket)
        self.assertEqual([], chroot_manager._messages)

    def test_add_and_get(self):
        """Adding new chroot and then retrive it."""
        chrootfilepath = self._create_file('chroot.test', content="UHMMM")
        chrootfilename = os.path.basename(chrootfilepath)

        chroot_manager = ChrootManager(
            self.distroarchrelease, self.pocket, filepath=chrootfilepath)

        chroot_manager.add()
        self.assertEqual(
            ["LibraryFileAlias: 57, 5 bytes, 5088e6471ab02d4268002f529a02621c",
             "PocketChroot for 'The Hoary Hedgehog Release for i386 (x86)'"
             "/SECURITY (1) added."], chroot_manager._messages)

        pocket_chroot = self.distroarchrelease.getPocketChroot(self.pocket)
        self.assertEqual(chrootfilename, pocket_chroot.chroot.filename)

        # required to turn librarian results visible.
        commit()

        dest = self._create_file('chroot.gotten')

        chroot_manager = ChrootManager(
            self.distroarchrelease, self.pocket, filepath=dest)

        chroot_manager.get()
        self.assertEqual(
            ["PocketChroot for 'The Hoary Hedgehog Release for i386 (x86)'/"
             "SECURITY (1) retrieved.",
             "Writing to '/tmp/chroot.gotten'."], chroot_manager._messages)

        self.assertEqual(True, os.path.exists(dest))

    def test_update_and_remove(self):
        """Update existent chroot then remove it."""
        chrootfilepath = self._create_file('chroot.update', content="DUHHHH")
        chrootfilename = os.path.basename(chrootfilepath)

        chroot_manager = ChrootManager(
            self.distroarchrelease, self.pocket, filepath=chrootfilepath)

        chroot_manager.update()
        self.assertEqual(
            ["LibraryFileAlias: 57, 6 bytes, a4cd43e083161afcdf26f4324024d8ef",
             "PocketChroot for 'The Hoary Hedgehog Release for i386 (x86)'/"
             "SECURITY (1) updated."], chroot_manager._messages)

        pocket_chroot = self.distroarchrelease.getPocketChroot(self.pocket)
        self.assertEqual(chrootfilename, pocket_chroot.chroot.filename)

        # required to turn librarian results visible.
        commit()

        chroot_manager = ChrootManager(
            self.distroarchrelease, self.pocket)

        chroot_manager.remove()
        self.assertEqual(
            ["PocketChroot for 'The Hoary Hedgehog Release for i386 (x86)'/"
             "SECURITY (1) retrieved.",
             "PocketChroot for 'The Hoary Hedgehog Release for i386 (x86)'/"
             "SECURITY (1) removed."], chroot_manager._messages)

        pocket_chroot = self.distroarchrelease.getPocketChroot(self.pocket)
        self.assertEqual(None, pocket_chroot.chroot)

    def test_remove_fail(self):
        """Attempt to remove inexistent chroot fail."""
        chroot_manager = ChrootManager(
            self.distroarchrelease, PackagePublishingPocket.RELEASE)

        self.assertRaises(
            ChrootManagerError, chroot_manager.remove)

    def test_add_fail(self):
        """Attempt to add inexistent local chroot fail."""
        chroot_manager = ChrootManager(
            self.distroarchrelease, PackagePublishingPocket.UPDATES,
            filepath='foo-bar')

        self.assertRaises(
            ChrootManagerError, chroot_manager.add)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
