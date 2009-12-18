# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functional tests for uploadprocessor.py."""

__metaclass__ = type
__all__ = [
    "MockOptions",
    "MockLogger",
    ]

import os
import shutil
import sys
from StringIO import StringIO
import tempfile
import traceback
import unittest

from email import message_from_string

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.archiveuploader.uploadpolicy import AbstractUploadPolicy
from lp.archiveuploader.uploadprocessor import UploadProcessor
from canonical.config import config
from canonical.database.constants import UTC_NOW
from lp.soyuz.model.archivepermission import ArchivePermission
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import (
    BinaryPackageRelease)
from lp.soyuz.model.component import Component
from lp.soyuz.model.publishing import (
    SourcePackagePublishingHistory, BinaryPackagePublishingHistory)
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.soyuz.model.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.ftests import import_public_test_keys
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.distroseries import DistroSeriesStatus
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.sourcepackage import SourcePackageFileType
from lp.soyuz.interfaces.archive import ArchivePurpose, IArchiveSet
from lp.soyuz.interfaces.queue import PackageUploadStatus
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.interfaces.queue import QueueInconsistentStateError
from canonical.launchpad.interfaces import ILibraryFileAliasSet
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.archivepermission import (
    ArchivePermissionType, IArchivePermissionSet)
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.sourcepackageformat import (
    ISourcePackageFormatSelectionSet, SourcePackageFormat)
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageNameSet)
from lp.services.mail import stub
from canonical.launchpad.testing.fakepackager import FakePackager
from lp.testing import TestCaseWithFactory
from lp.testing.mail_helpers import pop_notifications
from canonical.launchpad.webapp.errorlog import ErrorReportingUtility
from canonical.testing import LaunchpadZopelessLayer


class MockOptions:
    """Use in place of an options object, adding more attributes if needed."""
    keep = False
    dryrun = False


class MockLogger:
    """Pass as a log object. Record debug calls for later checking."""
    def __init__(self):
        self.lines = []

    def debug(self, s, exc_info=False):
        self.lines.append(s)
        if exc_info:
            for err_msg in traceback.format_exception(*sys.exc_info()):
                self.lines.append(err_msg)

    info = debug
    warn = debug
    error = debug

    def exception(self, s):
        self.debug(s, exc_info=True)


class BrokenUploadPolicy(AbstractUploadPolicy):
    """A broken upload policy, to test error handling."""

    def __init__(self):
        AbstractUploadPolicy.__init__(self)
        self.name = "broken"
        self.unsigned_changes_ok = True
        self.unsigned_dsc_ok = True

    def checkUpload(self, upload):
        """Raise an exception upload processing is not expecting."""
        raise Exception("Exception raised by BrokenUploadPolicy for testing.")


class TestUploadProcessorBase(TestCaseWithFactory):
    """Base class for functional tests over uploadprocessor.py."""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)

        self.queue_folder = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.queue_folder, "incoming"))

        self.test_files_dir = os.path.join(config.root,
            "lib/lp/archiveuploader/tests/data/suite")

        import_public_test_keys()

        self.options = MockOptions()
        self.options.base_fsroot = self.queue_folder
        self.options.leafname = None
        self.options.distro = "ubuntu"
        self.options.distroseries = None
        self.options.nomails = False
        self.options.context = 'insecure'

        # common recipients
        self.kinnison_recipient = (
            "Daniel Silverstone <daniel.silverstone@canonical.com>")
        self.name16_recipient = "Foo Bar <foo.bar@canonical.com>"

        self.log = MockLogger()

    def tearDown(self):
        shutil.rmtree(self.queue_folder)

    def assertLogContains(self, line):
        """Assert if a given line is present in the log messages."""
        self.assertTrue(line in self.log.lines,
                        "'%s' is not in logged output\n\n%s"
                        % (line, '\n'.join(self.log.lines)))

    def assertRaisesAndReturnError(self, excClass, callableObj, *args,
                                   **kwargs):
        """See `TestCase.assertRaises`.

        Unlike `TestCase.assertRaises`, this method returns the exception
        object when it is raised.  Callsites can then easily check the
        exception contents.
        """
        try:
            callableObj(*args, **kwargs)
        except excClass, error:
            return error
        else:
            if getattr(excClass, '__name__', None) is not None:
                excName = excClass.__name__
            else:
                excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def setupBreezy(self, name="breezy", permitted_formats=None):
        """Create a fresh distroseries in ubuntu.

        Use *initialiseFromParent* procedure to create 'breezy'
        on ubuntu based on the last 'breezy-autotest'.

        Also sets 'changeslist' and 'nominatedarchindep' properly and
        creates a chroot for breezy-autotest/i386 distroarchseries.

        :param name: supply the name of the distroseries if you don't want
            it to be called "breezy"
        :param permitted_formats: list of SourcePackageFormats to allow
            in the new distroseries. Only permits '1.0' by default.
        """
        self.ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        bat = self.ubuntu['breezy-autotest']
        self.breezy = self.ubuntu.newSeries(
            name, 'Breezy Badger',
            'The Breezy Badger', 'Black and White', 'Someone',
            '5.10', bat, bat.owner)
        breezy_i386 = self.breezy.newArch(
            'i386', bat['i386'].processorfamily, True, self.breezy.owner)
        self.breezy.nominatedarchindep = breezy_i386

        fake_chroot = self.addMockFile('fake_chroot.tar.gz')
        breezy_i386.addOrUpdateChroot(fake_chroot)

        self.breezy.changeslist = 'breezy-changes@ubuntu.com'
        self.breezy.initialiseFromParent()

        if permitted_formats is None:
            permitted_formats = [SourcePackageFormat.FORMAT_1_0]

        for format in permitted_formats:
            if not self.breezy.isSourcePackageFormatPermitted(format):
                getUtility(ISourcePackageFormatSelectionSet).add(
                    self.breezy, format)

    def addMockFile(self, filename, content="anything"):
        """Return a librarian file."""
        return getUtility(ILibraryFileAliasSet).create(
            filename, len(content), StringIO(content),
            'application/x-gtar')

    def queueUpload(self, upload_name, relative_path="", test_files_dir=None):
        """Queue one of our test uploads.

        upload_name is the name of the test upload directory. It is also
        the name of the queue entry directory we create.
        relative_path is the path to create inside the upload, eg
        ubuntu/~malcc/default. If not specified, defaults to "".

        Return the path to the upload queue entry directory created.
        """
        target_path = os.path.join(
            self.queue_folder, "incoming", upload_name, relative_path)
        if test_files_dir is None:
            test_files_dir = self.test_files_dir
        upload_dir = os.path.join(test_files_dir, upload_name)
        if relative_path:
            os.makedirs(os.path.dirname(target_path))
        shutil.copytree(upload_dir, target_path)
        return os.path.join(self.queue_folder, "incoming", upload_name)

    def processUpload(self, processor, upload_dir):
        """Process an upload queue entry directory.

        There is some duplication here with logic in UploadProcessor,
        but we need to be able to do this without error handling here,
        so that we can debug failing tests effectively.
        """
        results = []
        changes_files = processor.locateChangesFiles(upload_dir)
        for changes_file in changes_files:
            result = processor.processChangesFile(upload_dir, changes_file)
            results.append(result)
        return results

    def setupBreezyAndGetUploadProcessor(self, policy=None):
        """Setup Breezy and return an upload processor for it."""
        self.setupBreezy()
        self.layer.txn.commit()
        if policy is not None:
            self.options.context = policy
        return UploadProcessor(
            self.options, self.layer.txn, self.log)

    def assertEmail(self, contents=None, recipients=None):
        """Check last email content and recipients.

        :param contents: A list of lines; assert that each is in the email.
        :param recipients: A list of recipients that must be on the email.
                           Supply an empty list if you don't want them
                           checked.  Default action is to check that the
                           recipient is foo.bar@canonical.com, which is the
                           signer on most of the test data uploads.
        """
        if recipients is None:
            recipients = [self.name16_recipient]
        if contents is None:
            contents = []

        self.assertEqual(
            len(stub.test_emails), 1,
            'Unexpected number of emails sent: %s' % len(stub.test_emails))

        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        msg = message_from_string(raw_msg)
        # This is now a MIMEMultipart message.
        body = msg.get_payload(0)
        body = body.get_payload(decode=True)

        # Only check recipients if callsite didn't provide an empty list.
        if recipients != []:
            clean_recipients = [r.strip() for r in to_addrs]
            for recipient in list(recipients):
                self.assertTrue(
                    recipient in clean_recipients,
                    "%s not found in %s" % (recipients, clean_recipients))
            self.assertEqual(
                len(recipients), len(clean_recipients),
                "Email recipients do not match exactly. Expected %s, got %s" %
                    (recipients, clean_recipients))

        subject = "Subject: %s\n" % msg['Subject']
        body = subject + body

        for content in list(contents):
            self.assertTrue(
                content in body,
                "Expect: '%s'\nGot:\n%s" % (content, body))


class TestUploadProcessor(TestUploadProcessorBase):
    """Basic tests on uploadprocessor class.

    * Check if the rejection message is send even when an unexpected
      exception occur when processing the upload.
    * Check if known uploads targeted to a FROZEN distroseries
      end up in UNAPPROVED queue.

    This test case is able to setup a fresh distroseries in Ubuntu.
    """

    def _checkPartnerUploadEmailSuccess(self):
        """Ensure partner uploads generate the right email."""
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        foo_bar = "Foo Bar <foo.bar@canonical.com>"
        self.assertEqual([e.strip() for e in to_addrs], [foo_bar])
        self.assertTrue(
            "rejected" not in raw_msg,
            "Expected acceptance email not rejection. Actually Got:\n%s"
                % raw_msg)

    def _publishPackage(self, packagename, version, source=True,
                        archive=None):
        """Publish a single package that is currently NEW in the queue."""
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.NEW, name=packagename,
            version=version, exact_match=True, archive=archive)
        self.assertEqual(queue_items.count(), 1)
        queue_item = queue_items[0]
        queue_item.setAccepted()
        if source:
            pubrec = queue_item.sources[0].publish(self.log)
        else:
            pubrec = queue_item.builds[0].publish(self.log)
        return pubrec

    def testInstantiate(self):
        """UploadProcessor should instantiate"""
        up = UploadProcessor(self.options, None, self.log)

    def testLocateDirectories(self):
        """Return a sorted list of subdirs in a directory.

        We don't test that we block on the lockfile, as this is trivial
        code but tricky to test.
        """
        testdir = tempfile.mkdtemp()
        try:
            os.mkdir("%s/dir3" % testdir)
            os.mkdir("%s/dir1" % testdir)
            os.mkdir("%s/dir2" % testdir)

            up = UploadProcessor(self.options, None, self.log)
            located_dirs = up.locateDirectories(testdir)
            self.assertEqual(located_dirs, ['dir1', 'dir2', 'dir3'])
        finally:
            shutil.rmtree(testdir)

    def testLocateChangesFiles(self):
        """locateChangesFiles should return the .changes files in a folder.

        'source' changesfiles come first. Files that are not named as
        changesfiles are ignored.
        """
        testdir = tempfile.mkdtemp()
        try:
            open("%s/1.changes" % testdir, "w").close()
            open("%s/2_source.changes" % testdir, "w").close()
            open("%s/3.not_changes" % testdir, "w").close()

            up = UploadProcessor(self.options, None, self.log)
            located_files = up.locateChangesFiles(testdir)
            self.assertEqual(
                located_files, ["2_source.changes", "1.changes"])
        finally:
            shutil.rmtree(testdir)

    def testMoveUpload(self):
        """moveUpload should move the upload directory and .distro file."""
        testdir = tempfile.mkdtemp()
        try:
            # Create an upload, a .distro and a target to move it to.
            upload = tempfile.mkdtemp(dir=testdir)
            upload_name = os.path.basename(upload)
            distro = upload + ".distro"
            f = open(distro, mode="w")
            f.write("foo")
            f.close()
            target = tempfile.mkdtemp(dir=testdir)
            target_name = os.path.basename(target)

            # Move it
            self.options.base_fsroot = testdir
            up = UploadProcessor(self.options, None, self.log)
            up.moveUpload(upload, target_name)

            # Check it moved
            self.assertTrue(os.path.exists(os.path.join(target, upload_name)))
            self.assertTrue(os.path.exists(os.path.join(
                target, upload_name + ".distro")))
            self.assertFalse(os.path.exists(upload))
            self.assertFalse(os.path.exists(distro))
        finally:
            shutil.rmtree(testdir)

    def testOrderFilenames(self):
        """orderFilenames sorts _source.changes ahead of other files."""
        up = UploadProcessor(self.options, None, self.log)

        self.assertEqual(["d_source.changes", "a", "b", "c"],
            up.orderFilenames(["b", "a", "d_source.changes", "c"]))

    def testRejectionEmailForUnhandledException(self):
        """Test there's a rejection email when nascentupload breaks.

        If a developer makes an upload which finds a bug in nascentupload,
        and an unhandled exception occurs, we should try to send a
        rejection email. We'll test that this works, in a case where we
        will have the right information to send the email before the
        error occurs.

        If we haven't extracted enough information to send a rejection
        email when things break, trying to send one will raise a new
        exception, and the upload will fail silently as before. We don't
        test this case.

        See bug 35965.
        """
        # Register our broken upload policy
        AbstractUploadPolicy._registerPolicy(BrokenUploadPolicy)
        self.options.context = 'broken'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload a package to Breezy.
        upload_dir = self.queueUpload("baz_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        # Check the mailer stub has a rejection email for Daniel
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        # This is now a MIMEMultipart message.
        msg = message_from_string(raw_msg)
        body = msg.get_payload(0)
        body = body.get_payload(decode=True)

        daniel = "Daniel Silverstone <daniel.silverstone@canonical.com>"
        self.assertEqual(to_addrs, [daniel])
        self.assertTrue("Unhandled exception processing upload: Exception "
                        "raised by BrokenUploadPolicy for testing."
                        in body)

    def testUploadToFrozenDistro(self):
        """Uploads to a frozen distroseries should work, but be unapproved.

        The rule for a frozen distroseries is that uploads should still
        be permitted, but that the usual rule for auto-accepting uploads
        of existing packages should be suspended. New packages will still
        go into NEW, but new versions will be UNAPPROVED, rather than
        ACCEPTED.

        To test this, we will upload two versions of the same package,
        accepting and publishing the first, and freezing the distroseries
        before the second. If all is well, the second upload should go
        through ok, but end up in status UNAPPROVED, and with the
        appropriate email contents.

        See bug 58187.
        """
        # Set up the uploadprocessor with appropriate options and logger
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        # Check it went ok to the NEW queue and all is going well so far.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        foo_bar = "Foo Bar <foo.bar@canonical.com>"
        daniel = "Daniel Silverstone <daniel.silverstone@canonical.com>"
        self.assertEqual([e.strip() for e in to_addrs], [foo_bar, daniel])
        self.assertTrue(
            "NEW" in raw_msg, "Expected email containing 'NEW', got:\n%s"
            % raw_msg)

        # Accept and publish the upload.
        # This is required so that the next upload of a later version of
        # the same package will work correctly.
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.NEW, name="bar",
            version="1.0-1", exact_match=True)
        self.assertEqual(queue_items.count(), 1)
        queue_item = queue_items[0]

        queue_item.setAccepted()
        pubrec = queue_item.sources[0].publish(self.log)
        pubrec.secure_record.status = PackagePublishingStatus.PUBLISHED
        pubrec.secure_record.datepublished = UTC_NOW

        # Make ubuntu/breezy a frozen distro, so a source upload for an
        # existing package will be allowed, but unapproved.
        self.breezy.status = DistroSeriesStatus.FROZEN
        self.layer.txn.commit()

        # Upload a newer version of bar.
        upload_dir = self.queueUpload("bar_1.0-2")
        self.processUpload(uploadprocessor, upload_dir)

        # Verify we get an email talking about awaiting approval.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        daniel = "Daniel Silverstone <daniel.silverstone@canonical.com>"
        foo_bar = "Foo Bar <foo.bar@canonical.com>"
        self.assertEqual([e.strip() for e in to_addrs], [foo_bar, daniel])
        self.assertTrue("Waiting for approval" in raw_msg,
                        "Expected an 'upload awaits approval' email.\n"
                        "Got:\n%s" % raw_msg)

        # And verify that the queue item is in the unapproved state.
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.UNAPPROVED, name="bar",
            version="1.0-2", exact_match=True)
        self.assertEqual(queue_items.count(), 1)
        queue_item = queue_items[0]
        self.assertEqual(
            queue_item.status, PackageUploadStatus.UNAPPROVED,
            "Expected queue item to be in UNAPPROVED status.")

    def _checkCopyArchiveUploadToDistro(self, pocket_to_check,
                                        status_to_check):
        """Check binary copy archive uploads for given pocket and status.

        This helper method tests that buildd binary uploads to copy
        archives work when the
            * destination pocket is `pocket_to_check`
            * associated distroseries is in state `status_to_check`.

        See bug 369512.
        """
        # Set up the uploadprocessor with appropriate options and logger
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()

        # Upload 'bar-1.0-1' source and binary to ubuntu/breezy.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)
        bar_source_pub = self._publishPackage('bar', '1.0-1')
        [bar_original_build] = bar_source_pub.createMissingBuilds()

        # Create a COPY archive for building in non-virtual builds.
        uploader = getUtility(IPersonSet).getByName('name16')
        copy_archive = getUtility(IArchiveSet).new(
            owner=uploader, purpose=ArchivePurpose.COPY,
            distribution=self.ubuntu, name='the-copy-archive')
        copy_archive.require_virtualized = False

        # Copy 'bar-1.0-1' source to the COPY archive.
        bar_copied_source = bar_source_pub.copyTo(
            bar_source_pub.distroseries, pocket_to_check, copy_archive)
        [bar_copied_build] = bar_copied_source.createMissingBuilds()

        # Make ubuntu/breezy the current distro.
        self.breezy.status = status_to_check
        self.layer.txn.commit()

        shutil.rmtree(upload_dir)
        self.options.context = 'buildd'
        self.options.buildid = bar_copied_build.id
        upload_dir = self.queueUpload(
            "bar_1.0-1_binary", "%s/ubuntu" % copy_archive.id)
        self.processUpload(uploadprocessor, upload_dir)

        # Make sure the upload succeeded.
        self.assertEqual(
            uploadprocessor.last_processed_upload.is_rejected, False)

    def testCopyArchiveUploadToCurrentDistro(self):
        """Check binary copy archive uploads to RELEASE pockets.

        Buildd binary uploads to COPY archives (resulting from successful
        builds) should be allowed to go to the RELEASE pocket even though
        the distro series has a CURRENT status.

        See bug 369512.
        """
        self._checkCopyArchiveUploadToDistro(
            PackagePublishingPocket.RELEASE, DistroSeriesStatus.CURRENT)

    def testCopyArchiveUploadToSupportedDistro(self):
        """Check binary copy archive uploads to RELEASE pockets.

        Buildd binary uploads to COPY archives (resulting from successful
        builds) should be allowed to go to the RELEASE pocket even though
        the distro series has a SUPPORTED status.

        See bug 369512.
        """
        self._checkCopyArchiveUploadToDistro(
            PackagePublishingPocket.RELEASE, DistroSeriesStatus.SUPPORTED)

    def testDuplicatedBinaryUploadGetsRejected(self):
        """The upload processor rejects duplicated binary uploads.

        Duplicated binary uploads should be rejected, because they can't
        be published on disk, since it will be introducing different contents
        to the same filename in the archive.

        Such situation happens when a source gets copied to another suite in
        the same archive. The binary rebuild will have the same (name, version)
        of the original binary and will certainly have a different content
        (at least, the ar-compressed timestamps) making it impossible to be
        published in the archive.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()

        # Upload 'bar-1.0-1' source and binary to ubuntu/breezy.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)
        bar_source_pub = self._publishPackage('bar', '1.0-1')
        [bar_original_build] = bar_source_pub.createMissingBuilds()

        self.options.context = 'buildd'
        self.options.buildid = bar_original_build.id
        upload_dir = self.queueUpload("bar_1.0-1_binary")
        self.processUpload(uploadprocessor, upload_dir)
        [bar_binary_pub] = self._publishPackage("bar", "1.0-1", source=False)

        # Prepare ubuntu/breezy-autotest to build sources in i386.
        breezy_autotest = self.ubuntu['breezy-autotest']
        breezy_autotest_i386 = breezy_autotest['i386']
        breezy_autotest.nominatedarchindep = breezy_autotest_i386
        fake_chroot = self.addMockFile('fake_chroot.tar.gz')
        breezy_autotest_i386.addOrUpdateChroot(fake_chroot)
        self.layer.txn.commit()

        # Copy 'bar-1.0-1' source from breezy to breezy-autotest.
        bar_copied_source = bar_source_pub.copyTo(
            breezy_autotest, PackagePublishingPocket.RELEASE,
            self.ubuntu.main_archive)
        [bar_copied_build] = bar_copied_source.createMissingBuilds()

        # Re-upload the same 'bar-1.0-1' binary as if it was rebuilt
        # in breezy-autotest context.
        shutil.rmtree(upload_dir)
        self.options.buildid = bar_copied_build.id
        self.options.distroseries = breezy_autotest.name
        upload_dir = self.queueUpload("bar_1.0-1_binary")
        self.processUpload(uploadprocessor, upload_dir)
        [duplicated_binary_upload] = breezy_autotest.getQueueItems(
            status=PackageUploadStatus.NEW, name='bar',
            version='1.0-1', exact_match=True)

        # The just uploaded binary cannot be accepted because its
        # filename 'bar_1.0-1_i386.deb' is already published in the
        # archive.
        error = self.assertRaisesAndReturnError(
            QueueInconsistentStateError,
            duplicated_binary_upload.setAccepted)
        self.assertEqual(
            str(error),
            "The following files are already published in Primary "
            "Archive for Ubuntu Linux:\nbar_1.0-1_i386.deb")

    def testBinaryUploadToCopyArchive(self):
        """Copy archive binaries are not checked against the primary archive.

        When a buildd binary upload to a copy archive is performed the
        version should not be checked against the primary archive but
        against the copy archive in question.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()

        # Upload 'bar-1.0-1' source and binary to ubuntu/breezy.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)
        bar_source_old = self._publishPackage('bar', '1.0-1')

        # Upload 'bar-1.0-1' source and binary to ubuntu/breezy.
        upload_dir = self.queueUpload("bar_1.0-2")
        self.processUpload(uploadprocessor, upload_dir)
        [bar_source_pub] = self.ubuntu.main_archive.getPublishedSources(
            name='bar', version='1.0-2', exact_match=True)
        [bar_original_build] = bar_source_pub.getBuilds()

        self.options.context = 'buildd'
        self.options.buildid = bar_original_build.id
        upload_dir = self.queueUpload("bar_1.0-2_binary")
        self.processUpload(uploadprocessor, upload_dir)
        [bar_binary_pub] = self._publishPackage("bar", "1.0-2", source=False)

        # Create a COPY archive for building in non-virtual builds.
        uploader = getUtility(IPersonSet).getByName('name16')
        copy_archive = getUtility(IArchiveSet).new(
            owner=uploader, purpose=ArchivePurpose.COPY,
            distribution=self.ubuntu, name='no-source-uploads')
        copy_archive.require_virtualized = False

        # Copy 'bar-1.0-1' source to the COPY archive.
        bar_copied_source = bar_source_old.copyTo(
            bar_source_pub.distroseries, bar_source_pub.pocket,
            copy_archive)
        [bar_copied_build] = bar_copied_source.createMissingBuilds()

        shutil.rmtree(upload_dir)
        self.options.buildid = bar_copied_build.id
        upload_dir = self.queueUpload(
            "bar_1.0-1_binary", "%s/ubuntu" % copy_archive.id)
        self.processUpload(uploadprocessor, upload_dir)

        # The binary just uploaded is accepted because it's destined for a
        # copy archive and the PRIMARY and the COPY archives are isolated
        # from each other.
        self.assertEqual(
            uploadprocessor.last_processed_upload.is_rejected, False)

    def testPartnerArchiveMissingForPartnerUploadFails(self):
        """A missing partner archive should produce a rejection email.

        If the partner archive is missing (i.e. there is a data problem)
        when a partner package is uploaded to it, a sensible rejection
        error email should be generated.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor(
            policy='anything')

        # Fudge the partner archive in the sample data temporarily so that
        # it's now a PPA instead.
        archive = getUtility(IArchiveSet).getByDistroPurpose(
            distribution=self.ubuntu, purpose=ArchivePurpose.PARTNER)
        removeSecurityProxy(archive).purpose = ArchivePurpose.PPA

        self.layer.txn.commit()

        # Upload a package.
        upload_dir = self.queueUpload("foocomm_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        # Check that it was rejected appropriately.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "Partner archive for distro '%s' not found" % self.ubuntu.name
                in raw_msg)

    def testMixedPartnerUploadFails(self):
        """Uploads with partner and non-partner files are rejected.

        Test that a package that has partner and non-partner files in it
        is rejected.  Partner uploads should be entirely partner.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor(
            policy='anything')

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1-illegal-component-mix")
        self.processUpload(uploadprocessor, upload_dir)

        # Check that it was rejected.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        foo_bar = "Foo Bar <foo.bar@canonical.com>"
        self.assertEqual([e.strip() for e in to_addrs], [foo_bar])
        self.assertTrue(
            "Cannot mix partner files with non-partner." in raw_msg,
            "Expected email containing 'Cannot mix partner files with "
            "non-partner.', got:\n%s" % raw_msg)

    def testPartnerReusingOrigFromPartner(self):
        """Partner uploads reuse 'orig.tar.gz' from the partner archive."""
        # Make the official bar orig.tar.gz available in the system.
        uploadprocessor = self.setupBreezyAndGetUploadProcessor(
            policy='absolutely-anything')

        upload_dir = self.queueUpload("foocomm_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        self.assertEqual(
            uploadprocessor.last_processed_upload.queue_root.status,
            PackageUploadStatus.NEW)

        [queue_item] = self.breezy.getQueueItems(
            status=PackageUploadStatus.NEW, name="foocomm",
            version="1.0-1", exact_match=True)
        queue_item.setAccepted()
        queue_item.realiseUpload()
        self.layer.commit()

        archive = getUtility(IArchiveSet).getByDistroPurpose(
            distribution=self.ubuntu, purpose=ArchivePurpose.PARTNER)
        try:
            self.ubuntu.getFileByName(
                'foocomm_1.0.orig.tar.gz', archive=archive, source=True,
                binary=False)
        except NotFoundError:
            self.fail('foocomm_1.0.orig.tar.gz is not yet published.')

        # Please note: this upload goes to the Ubuntu main archive.
        upload_dir = self.queueUpload("foocomm_1.0-3")
        self.processUpload(uploadprocessor, upload_dir)
        # Discard the announcement email and check the acceptance message
        # content.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        msg = message_from_string(raw_msg)
        # This is now a MIMEMultipart message.
        body = msg.get_payload(0)
        body = body.get_payload(decode=True)

        self.assertEqual(
            '[ubuntu/breezy] foocomm 1.0-3 (Accepted)', msg['Subject'])
        self.assertFalse(
            'Unable to find foocomm_1.0.orig.tar.gz in upload or '
            'distribution.' in body,
            'Unable to find foocomm_1.0.orig.tar.gz')

    def testPartnerUpload(self):
        """Partner packages should be uploaded to the partner archive.

        Packages that have files in the 'partner' component should be
        uploaded to a separate IArchive that has a purpose of
        ArchivePurpose.PARTNER.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor(
            policy='anything')

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        # Check it went ok to the NEW queue and all is going well so far.
        self._checkPartnerUploadEmailSuccess()

        # Find the sourcepackagerelease and check its component.
        foocomm_name = SourcePackageName.selectOneBy(name="foocomm")
        foocomm_spr = SourcePackageRelease.selectOneBy(
           sourcepackagename=foocomm_name)
        self.assertEqual(foocomm_spr.component.name, 'partner')

        # Check that the right archive was picked.
        self.assertEqual(foocomm_spr.upload_archive.description,
            'Partner archive')

        # Accept and publish the upload.
        partner_archive = getUtility(IArchiveSet).getByDistroPurpose(
            self.ubuntu, ArchivePurpose.PARTNER)
        self.assertTrue(partner_archive)
        self._publishPackage("foocomm", "1.0-1", archive=partner_archive)

        # Check the publishing record's archive and component.
        foocomm_spph = SourcePackagePublishingHistory.selectOneBy(
            sourcepackagerelease=foocomm_spr)
        self.assertEqual(foocomm_spph.archive.description,
            'Partner archive')
        self.assertEqual(foocomm_spph.component.name,
            'partner')

        # Fudge a build for foocomm so that it's not in the partner archive.
        # We can then test that uploading a binary package must match the
        # build's archive.
        foocomm_build = foocomm_spr.createBuild(
            self.breezy['i386'], PackagePublishingPocket.RELEASE,
            self.ubuntu.main_archive)
        self.layer.txn.commit()
        self.options.buildid = foocomm_build.id
        upload_dir = self.queueUpload("foocomm_1.0-1_binary")
        self.processUpload(uploadprocessor, upload_dir)

        contents = [
            "Subject: foocomm_1.0-1_i386.changes rejected",
            "Attempt to upload binaries specifying build 31, "
            "where they don't fit."]
        self.assertEmail(contents)

        # Reset upload queue directory for a new upload and the
        # uploadprocessor buildid option.
        shutil.rmtree(upload_dir)
        self.options.buildid = None

        # Now upload a binary package of 'foocomm', letting a new build record
        # with appropriate data be created by the uploadprocessor.
        upload_dir = self.queueUpload("foocomm_1.0-1_binary")
        self.processUpload(uploadprocessor, upload_dir)

        # Find the binarypackagerelease and check its component.
        foocomm_binname = BinaryPackageName.selectOneBy(name="foocomm")
        foocomm_bpr = BinaryPackageRelease.selectOneBy(
            binarypackagename=foocomm_binname)
        self.assertEqual(foocomm_bpr.component.name, 'partner')

        # Publish the upload so we can check the publishing record.
        self._publishPackage("foocomm", "1.0-1", source=False)

        # Check the publishing record's archive and component.
        foocomm_bpph = BinaryPackagePublishingHistory.selectOneBy(
            binarypackagerelease=foocomm_bpr)
        self.assertEqual(foocomm_bpph.archive.description,
            'Partner archive')
        self.assertEqual(foocomm_bpph.component.name,
            'partner')

    def testUploadAncestry(self):
        """Check that an upload correctly finds any file ancestors.

        When uploading a package, any previous versions will have
        ancestor files which affects whether this upload is NEW or not.
        In particular, when an upload's archive has been overridden,
        we must make sure that the ancestry check looks in all the
        distro archives.  This can be done by two partner package
        uploads, as partner packages have their archive overridden.
        """
        # Use the 'absolutely-anything' policy which allows unsigned
        # DSC and changes files.
        uploadprocessor = self.setupBreezyAndGetUploadProcessor(
            policy='absolutely-anything')

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        # Check it went ok to the NEW queue and all is going well so far.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "NEW" in raw_msg,
            "Expected email containing 'NEW', got:\n%s"
            % raw_msg)

        # Accept and publish the upload.
        partner_archive = getUtility(IArchiveSet).getByDistroPurpose(
            self.ubuntu, ArchivePurpose.PARTNER)
        self._publishPackage("foocomm", "1.0-1", archive=partner_archive)

        # Now do the same thing with a binary package.
        upload_dir = self.queueUpload("foocomm_1.0-1_binary")
        self.processUpload(uploadprocessor, upload_dir)

        # Accept and publish the upload.
        self._publishPackage("foocomm", "1.0-1", source=False,
                             archive=partner_archive)

        # Upload the next source version of the package.
        upload_dir = self.queueUpload("foocomm_1.0-2")
        self.processUpload(uploadprocessor, upload_dir)

        # Check the upload is in the DONE queue since single source uploads
        # with ancestry (previously uploaded) will skip the ACCEPTED state.
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.DONE,
            version="1.0-2",
            name="foocomm")
        self.assertEqual(queue_items.count(), 1)

        # Single source uploads also get their corrsponding builds created
        # at upload-time. 'foocomm' only builds in 'i386', thus only one
        # build gets created.
        [foocomm_source] = partner_archive.getPublishedSources(
            name='foocomm', version='1.0-2')
        [build] = foocomm_source.sourcepackagerelease.builds
        self.assertEqual(
            build.title,
            'i386 build of foocomm 1.0-2 in ubuntu breezy RELEASE')
        self.assertEqual(build.buildstate.name, 'NEEDSBUILD')
        self.assertTrue(build.buildqueue_record.lastscore is not None)

        # Upload the next binary version of the package.
        upload_dir = self.queueUpload("foocomm_1.0-2_binary")
        self.processUpload(uploadprocessor, upload_dir)

        # Check that the binary upload was accepted:
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.ACCEPTED,
            version="1.0-2",
            name="foocomm")
        self.assertEqual(queue_items.count(), 1)

    def testPartnerUploadToProposedPocket(self):
        """Upload a partner package to the proposed pocket."""
        self.setupBreezy()
        self.breezy.status = DistroSeriesStatus.CURRENT
        self.layer.txn.commit()
        self.options.context = 'insecure'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1_proposed")
        self.processUpload(uploadprocessor, upload_dir)

        self._checkPartnerUploadEmailSuccess()

    def testPartnerUploadToReleasePocketInStableDistroseries(self):
        """Partner package upload to release pocket in stable distroseries.

        Uploading a partner package to the release pocket in a stable
        distroseries is allowed.
        """
        self.setupBreezy()
        self.breezy.status = DistroSeriesStatus.CURRENT
        self.layer.txn.commit()
        self.options.context = 'insecure'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)

        self._checkPartnerUploadEmailSuccess()

    def _uploadPartnerToNonReleasePocketAndCheckFail(self):
        """Upload partner package to non-release pocket.

        Helper function to upload a partner package to a non-release
        pocket and ensure it fails."""
        # Set up the uploadprocessor with appropriate options and logger.
        self.options.context = 'insecure'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload a package for Breezy.
        upload_dir = self.queueUpload("foocomm_1.0-1_updates")
        self.processUpload(uploadprocessor, upload_dir)

        # Check it is rejected.
        expect_msg = ("Partner uploads must be for the RELEASE or "
                      "PROPOSED pocket.")
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            expect_msg in raw_msg,
            "Expected email with %s, got:\n%s" % (expect_msg, raw_msg))

        # Housekeeping so the next test won't fail.
        shutil.rmtree(upload_dir)

    def testPartnerUploadToNonReleaseOrProposedPocket(self):
        """Test partner upload pockets.

        Partner uploads must be targeted to the RELEASE pocket only,
        """
        self.setupBreezy()

        # Check unstable states:

        self.breezy.status = DistroSeriesStatus.DEVELOPMENT
        self.layer.txn.commit()
        self._uploadPartnerToNonReleasePocketAndCheckFail()

        self.breezy.status = DistroSeriesStatus.EXPERIMENTAL
        self.layer.txn.commit()
        self._uploadPartnerToNonReleasePocketAndCheckFail()

        # Check stable states:

        self.breezy.status = DistroSeriesStatus.CURRENT
        self.layer.txn.commit()
        self._uploadPartnerToNonReleasePocketAndCheckFail()

        self.breezy.status = DistroSeriesStatus.SUPPORTED
        self.layer.txn.commit()
        self._uploadPartnerToNonReleasePocketAndCheckFail()

    def testUploadWithUnknownSectionIsRejected(self):
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()
        upload_dir = self.queueUpload("bar_1.0-1_bad_section")
        self.processUpload(uploadprocessor, upload_dir)
        self.assertEqual(
            uploadprocessor.last_processed_upload.rejection_message,
            "bar_1.0-1.dsc: Unknown section 'badsection'\n"
            "bar_1.0.orig.tar.gz: Unknown section 'badsection'\n"
            "bar_1.0-1.diff.gz: Unknown section 'badsection'\n"
            "Further error processing not possible because of a "
            "critical previous error.")

    def testUploadWithUnknownComponentIsRejected(self):
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()
        upload_dir = self.queueUpload("bar_1.0-1_contrib_component")
        self.processUpload(uploadprocessor, upload_dir)
        self.assertEqual(
            uploadprocessor.last_processed_upload.rejection_message,
            "bar_1.0-1.dsc: Unknown component 'contrib'\n"
            "bar_1.0.orig.tar.gz: Unknown component 'contrib'\n"
            "bar_1.0-1.diff.gz: Unknown component 'contrib'\n"
            "Further error processing not possible because of a "
            "critical previous error.")

    def testSourceUploadToBuilddPath(self):
        """Source uploads to buildd upload paths are not permitted."""
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        primary = ubuntu.main_archive

        uploadprocessor = self.setupBreezyAndGetUploadProcessor()
        upload_dir = self.queueUpload("bar_1.0-1", "%s/ubuntu" % primary.id)
        self.processUpload(uploadprocessor, upload_dir)

        # Check that the sourceful upload to the copy archive is rejected.
        contents = [
            "Invalid upload path (1/ubuntu) for this policy (insecure)"
            ]
        self.assertEmail(contents=contents, recipients=[])

    # Uploads that are new should have the component overridden
    # such that:
    #   'contrib' -> 'multiverse'
    #   'non-free' -> 'multiverse'
    #   everything else -> 'universe'
    #
    # This is to relieve the archive admins of some work where this is
    # the default action taken anyway.
    #
    # The following three tests check this.

    def checkComponentOverride(self, upload_dir_name,
                               expected_component_name):
        """Helper function to check overridden component names.

        Upload a 'bar' package from upload_dir_name, then
        inspect the package 'bar' in the NEW queue and ensure its
        overridden component matches expected_component_name.

        The original component comes from the source package contained
        in upload_dir_name.
        """
        uploadprocessor = self.setupBreezyAndGetUploadProcessor()
        upload_dir = self.queueUpload(upload_dir_name)
        self.processUpload(uploadprocessor, upload_dir)

        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.NEW, name="bar",
            version="1.0-1", exact_match=True)
        [queue_item] = queue_items
        self.assertEqual(
            queue_item.sourcepackagerelease.component.name,
            expected_component_name)

    def testUploadContribComponentOverride(self):
        """Test the overriding of the contrib component on uploads."""
        # The component contrib does not exist in the sample data, so
        # add it here.
        Component(name='contrib')

        # Test it.
        self.checkComponentOverride(
            "bar_1.0-1_contrib_component", "multiverse")

    def testUploadNonfreeComponentOverride(self):
        """Test the overriding of the non-free component on uploads."""
        # The component non-free does not exist in the sample data, so
        # add it here.
        Component(name='non-free')

        # Test it.
        self.checkComponentOverride(
            "bar_1.0-1_nonfree_component", "multiverse")

    def testUploadDefaultComponentOverride(self):
        """Test the overriding of the component on uploads.

        Components other than non-free and contrib should override to
        universe.
        """
        self.checkComponentOverride("bar_1.0-1", "universe")

    def testOopsCreation(self):
        """Test the the creation of an OOPS upon upload processing failure.

        In order to trigger the exception needed a bogus changes file will be
        used.
        That exception will then initiate the creation of an OOPS report.
        """
        processor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        upload_dir = self.queueUpload("foocomm_1.0-1_proposed")
        bogus_changesfile_data = '''
        Ubuntu is a community developed, Linux-based operating system that is
        perfect for laptops, desktops and servers. It contains all the
        applications you need - a web browser, presentation, document and
        spreadsheet software, instant messaging and much more.
        '''
        file_handle = open(
            '%s/%s' % (upload_dir, 'bogus.changes'), 'w')
        file_handle.write(bogus_changesfile_data)
        file_handle.close()

        processor.processUploadQueue()

        error_utility = ErrorReportingUtility()
        error_report = error_utility.getLastOopsReport()
        fp = StringIO()
        error_report.write(fp)
        error_text = fp.getvalue()
        self.failUnless(
            error_text.find('Exception-Type: FatalUploadError') >= 0,
            'Expected Exception type not found in OOPS report:\n%s'
            % error_text)

        expected_explanation = (
            "Unable to find mandatory field 'files' in the changes file.")
        self.failUnless(
            error_text.find(expected_explanation) >= 0,
            'Expected Exception text not found in OOPS report:\n%s'
            % error_text)

    def testLZMADebUpload(self):
        """Make sure that data files compressed with lzma in Debs work.

        Each Deb contains a data.tar.xxx file where xxx is one of gz, bz2
        or lzma.  Here we make sure that lzma works.
        """
        # Setup the test.
        self.setupBreezy()
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the source first to enable the binary later:
        upload_dir = self.queueUpload("bar_1.0-1_lzma")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it went ok:
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "rejected" not in raw_msg,
            "Failed to upload bar source:\n%s" % raw_msg)
        self._publishPackage("bar", "1.0-1")
        # Clear out emails generated during upload.
        ignore = pop_notifications()

        # Upload a binary lzma-compressed package.
        upload_dir = self.queueUpload("bar_1.0-1_lzma_binary")
        self.processUpload(uploadprocessor, upload_dir)

        # Successful binary uploads won't generate any email.
        if len(stub.test_emails) != 0:
            from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertEqual(
            len(stub.test_emails), 0,
            "Expected no emails!  Actually got:\n%s" % raw_msg)

        # Check in the queue to see if it really made it:
        queue_items = self.breezy.getQueueItems(
            status=PackageUploadStatus.NEW, name="bar",
            version="1.0-1", exact_match=True)
        self.assertEqual(
            queue_items.count(), 1,
            "Expected one 'bar' item in the queue, actually got %d."
                % queue_items.count())

    def testUploadResultingInNoBuilds(self):
        """Source uploads resulting in no builds.

        Source uploads building only in unsupported architectures are
        accepted in primary archives.

        If a new source upload results in no builds, it can be accepted
        from queue.

        If a auto-accepted source upload results in no builds, like a
        known ubuntu or a PPA upload, it will made its way to the
        repository.

        This scenario usually happens for sources targeted to
        architectures not yet supported in ubuntu, but for which we
        have plans to support soon.

        Once a chroot is available for the architecture being prepared,
        a `queue-builder` run will be required to create the missing
        builds.
        """
        self.setupBreezy()

        # New 'biscuit' source building in 'm68k' only can't be accepted.
        # The archive-admin will be forced to reject it manually.
        packager = FakePackager(
            'biscuit', '1.0', 'foo.bar@canonical.com-passwordless.sec')
        packager.buildUpstream(suite=self.breezy.name, arch="m68k")
        packager.buildSource()
        upload = packager.uploadSourceVersion(
            '1.0-1', auto_accept=False)
        upload.do_accept(notify=False)

        # Let's commit because acceptFromQueue needs to access the
        # just-uploaded changesfile from librarian.
        self.layer.txn.commit()

        upload.queue_root.acceptFromQueue('announce@ubuntu.com')

        # 'biscuit_1.0-2' building on i386 get accepted and published.
        packager.buildVersion('1.0-2', suite=self.breezy.name, arch="i386")
        packager.buildSource()
        biscuit_pub = packager.uploadSourceVersion('1.0-2')
        self.assertEqual(biscuit_pub.status, PackagePublishingStatus.PENDING)

        # A auto-accepted version building only in m68k, which also doesn't
        # exist in breezy gets rejected yet in upload time (meaning, the
        # uploader will receive a rejection email).
        packager.buildVersion('1.0-3', suite=self.breezy.name, arch="m68k")
        packager.buildSource()
        upload = packager.uploadSourceVersion('1.0-3', auto_accept=False)

        upload.storeObjectsInDatabase()

    def testPackageUploadPermissions(self):
        """Test package-specific upload permissions.

        Someone who has upload permissions to a component, but also
        has permission to a specific package in a different component
        should be able to upload that package. (Bug #250618)
        """
        self.setupBreezy()
        # Remove our favourite uploader from the team that has
        # permissions to all components at upload time.
        uploader = getUtility(IPersonSet).getByName('name16')
        distro_team = getUtility(IPersonSet).getByName('ubuntu-team')
        uploader.leave(distro_team)

        # Now give name16 specific permissions to "restricted" only.
        restricted = getUtility(IComponentSet)["restricted"]
        ArchivePermission(
            archive=self.ubuntu.main_archive,
            permission=ArchivePermissionType.UPLOAD, person=uploader,
            component=restricted)

        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the first version and accept it to make it known in
        # Ubuntu.  The uploader has rights to upload NEW packages to
        # components that he does not have direct rights to.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)
        bar_source_pub = self._publishPackage('bar', '1.0-1')
        # Clear out emails generated during upload.
        ignore = pop_notifications()

        # Now upload the next version.
        upload_dir = self.queueUpload("bar_1.0-2")
        self.processUpload(uploadprocessor, upload_dir)

        # Make sure it failed.
        self.assertEqual(
            uploadprocessor.last_processed_upload.rejection_message,
            u"Signer is not permitted to upload to the component 'universe'.")

        # Now add permission to upload "bar" for name16.
        bar_package = getUtility(ISourcePackageNameSet).queryByName("bar")
        ArchivePermission(
            archive=self.ubuntu.main_archive,
            permission=ArchivePermissionType.UPLOAD, person=uploader,
            sourcepackagename=bar_package)

        # Upload the package again.
        self.processUpload(uploadprocessor, upload_dir)

        # Check that it worked,
        status = uploadprocessor.last_processed_upload.queue_root.status
        self.assertEqual(
            status, PackageUploadStatus.DONE,
            "Expected NEW status, got %s" % status.value)

    def testPackagesetUploadPermissions(self):
        """Test package set based upload permissions."""
        self.setupBreezy()
        # Remove our favourite uploader from the team that has
        # permissions to all components at upload time.
        uploader = getUtility(IPersonSet).getByName('name16')
        distro_team = getUtility(IPersonSet).getByName('ubuntu-team')
        uploader.leave(distro_team)

        # Now give name16 specific permissions to "restricted" only.
        restricted = getUtility(IComponentSet)["restricted"]
        ArchivePermission(
            archive=self.ubuntu.main_archive,
            permission=ArchivePermissionType.UPLOAD, person=uploader,
            component=restricted)

        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the first version and accept it to make it known in
        # Ubuntu.  The uploader has rights to upload NEW packages to
        # components that he does not have direct rights to.
        upload_dir = self.queueUpload("bar_1.0-1")
        self.processUpload(uploadprocessor, upload_dir)
        bar_source_pub = self._publishPackage('bar', '1.0-1')
        # Clear out emails generated during upload.
        ignore = pop_notifications()

        # Now upload the next version.
        upload_dir = self.queueUpload("bar_1.0-2")
        self.processUpload(uploadprocessor, upload_dir)

        # Make sure it failed.
        self.assertEqual(
            uploadprocessor.last_processed_upload.rejection_message,
            "Signer is not permitted to upload to the component 'universe'.")

        # Now put in place a package set, add 'bar' to it and define a
        # permission for the former.
        bar_package = getUtility(ISourcePackageNameSet).queryByName("bar")
        ap_set = getUtility(IArchivePermissionSet)
        ps_set = getUtility(IPackagesetSet)
        foo_ps = ps_set.new(
            u'foo-pkg-set', u'Packages that require special care.', uploader,
            distroseries=self.ubuntu['grumpy'])
        self.layer.txn.commit()

        foo_ps.add((bar_package,))
        ap_set.newPackagesetUploader(
            self.ubuntu.main_archive, uploader, foo_ps)

        # The uploader now does have a package set based upload permissions
        # to 'bar' in 'grumpy' but not in 'breezy'.
        self.assertTrue(
            ap_set.isSourceUploadAllowed(
                self.ubuntu.main_archive, 'bar', uploader,
                self.ubuntu['grumpy']))
        self.assertFalse(
            ap_set.isSourceUploadAllowed(
                self.ubuntu.main_archive, 'bar', uploader, self.breezy))

        # Upload the package again.
        self.processUpload(uploadprocessor, upload_dir)

        # Check that it failed (permissions were granted for wrong series).
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        msg = message_from_string(raw_msg)
        self.assertEqual(
            msg['Subject'], 'bar_1.0-2_source.changes rejected')

        # Grant the permissions in the proper series.
        breezy_ps = ps_set.new(
            u'foo-pkg-set-breezy', u'Packages that require special care.',
            uploader, distroseries=self.breezy)
        breezy_ps.add((bar_package,))
        ap_set.newPackagesetUploader(
            self.ubuntu.main_archive, uploader, breezy_ps)
        # The uploader now does have a package set based upload permission
        # to 'bar' in 'breezy'.
        self.assertTrue(
            ap_set.isSourceUploadAllowed(
                self.ubuntu.main_archive, 'bar', uploader, self.breezy))
        # Upload the package again.
        self.processUpload(uploadprocessor, upload_dir)
        # Check that it worked.
        status = uploadprocessor.last_processed_upload.queue_root.status
        self.assertEqual(
            status, PackageUploadStatus.DONE,
            "Expected DONE status, got %s" % status.value)

    def testUploadPathErrorIntendedForHumans(self):
        # Distribution upload path errors are augmented with a hint
        # to fix the current dput/dupload configuration.
        # This information gets included in the rejection email along
        # with pointer to the Soyuz questions in Launchpad and the
        # reason why the message was sent to the current recipients.
        self.setupBreezy()
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        upload_dir = self.queueUpload("bar_1.0-1", "boing")
        self.processUpload(uploadprocessor, upload_dir)
        rejection_message = (
            uploadprocessor.last_processed_upload.rejection_message)
        self.assertEqual(
            ["Launchpad failed to process the upload path 'boing':",
             '',
             "Could not find distribution 'boing'.",
             '',
             'It is likely that you have a configuration problem with '
                'dput/dupload.',
             'Please update your dput/dupload configuration and then '
                're-upload.',
             '',
             'Further error processing not possible because of a critical '
                'previous error.',
             ],
            rejection_message.splitlines())

        contents = [
            "Subject: bar_1.0-1_source.changes rejected",
            "Could not find distribution 'boing'",
            "If you don't understand why your files were rejected",
            "http://answers.launchpad.net/soyuz",
            "You are receiving this email because you are the "
               "uploader, maintainer or",
            "signer of the above package.",
            ]
        recipients = [
            'Foo Bar <foo.bar@canonical.com>',
            'Daniel Silverstone <daniel.silverstone@canonical.com>',
            ]
        self.assertEmail(contents, recipients=recipients)

    def test30QuiltUploadToUnsupportingSeriesIsRejected(self):
        """Ensure that uploads to series without format support are rejected.

        Series can restrict the source formats that they accept. Uploads
        should be rejected if an unsupported format is uploaded.
        """
        self.setupBreezy()
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the source.
        upload_dir = self.queueUpload("bar_1.0-1_3.0-quilt")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it was rejected.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "bar_1.0-1.dsc: format '3.0 (quilt)' is not permitted in "
            "breezy." in raw_msg,
            "Source was not rejected properly:\n%s" % raw_msg)

    def test30QuiltUpload(self):
        """Ensure that 3.0 (quilt) uploads work properly. """
        self.setupBreezy(
            permitted_formats=[SourcePackageFormat.FORMAT_3_0_QUILT])
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the source.
        upload_dir = self.queueUpload("bar_1.0-1_3.0-quilt")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it went ok:
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "rejected" not in raw_msg,
            "Failed to upload bar source:\n%s" % raw_msg)
        spph = self._publishPackage("bar", "1.0-1")

        self.assertEquals(
            sorted((sprf.libraryfile.filename, sprf.filetype)
                   for sprf in spph.sourcepackagerelease.files),
            [('bar_1.0-1.debian.tar.bz2',
              SourcePackageFileType.DEBIAN_TARBALL),
             ('bar_1.0-1.dsc',
              SourcePackageFileType.DSC),
             ('bar_1.0.orig-comp1.tar.gz',
              SourcePackageFileType.COMPONENT_ORIG_TARBALL),
             ('bar_1.0.orig-comp2.tar.bz2',
              SourcePackageFileType.COMPONENT_ORIG_TARBALL),
             ('bar_1.0.orig.tar.gz',
              SourcePackageFileType.ORIG_TARBALL)])

    def test30QuiltUploadWithSameComponentOrig(self):
        """Ensure that 3.0 (quilt) uploads with shared component origs work.
        """
        self.setupBreezy(
            permitted_formats=[SourcePackageFormat.FORMAT_3_0_QUILT])
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the first source.
        upload_dir = self.queueUpload("bar_1.0-1_3.0-quilt")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it went ok:
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "rejected" not in raw_msg,
            "Failed to upload bar source:\n%s" % raw_msg)
        spph = self._publishPackage("bar", "1.0-1")

        # Upload another source sharing the same (component) orig.
        upload_dir = self.queueUpload("bar_1.0-2_3.0-quilt_without_orig")
        self.assertEquals(
            self.processUpload(uploadprocessor, upload_dir), ['accepted'])

        queue_item = uploadprocessor.last_processed_upload.queue_root
        self.assertEquals(
            sorted((sprf.libraryfile.filename, sprf.filetype) for sprf
                   in queue_item.sources[0].sourcepackagerelease.files),
            [('bar_1.0-2.debian.tar.bz2',
              SourcePackageFileType.DEBIAN_TARBALL),
             ('bar_1.0-2.dsc',
              SourcePackageFileType.DSC),
             ('bar_1.0.orig-comp1.tar.gz',
              SourcePackageFileType.COMPONENT_ORIG_TARBALL),
             ('bar_1.0.orig-comp2.tar.bz2',
              SourcePackageFileType.COMPONENT_ORIG_TARBALL),
             ('bar_1.0.orig.tar.gz',
              SourcePackageFileType.ORIG_TARBALL)])

    def test30NativeUpload(self):
        """Ensure that 3.0 (native) uploads work properly. """
        self.setupBreezy(
            permitted_formats=[SourcePackageFormat.FORMAT_3_0_NATIVE])
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the source.
        upload_dir = self.queueUpload("bar_1.0_3.0-native")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it went ok:
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "rejected" not in raw_msg,
            "Failed to upload bar source:\n%s" % raw_msg)
        spph = self._publishPackage("bar", "1.0")

        self.assertEquals(
            sorted((sprf.libraryfile.filename, sprf.filetype)
                   for sprf in spph.sourcepackagerelease.files),
            [('bar_1.0.dsc',
              SourcePackageFileType.DSC),
             ('bar_1.0.tar.bz2',
              SourcePackageFileType.NATIVE_TARBALL)])

    def test10Bzip2UploadIsRejected(self):
        """Ensure that 1.0 sources with bzip2 compression are rejected."""
        self.setupBreezy()
        self.layer.txn.commit()
        self.options.context = 'absolutely-anything'
        uploadprocessor = UploadProcessor(
            self.options, self.layer.txn, self.log)

        # Upload the source.
        upload_dir = self.queueUpload("bar_1.0-1_1.0-bzip2")
        self.processUpload(uploadprocessor, upload_dir)
        # Make sure it was rejected.
        from_addr, to_addrs, raw_msg = stub.test_emails.pop()
        self.assertTrue(
            "bar_1.0-1.dsc: is format 1.0 but uses bzip2 compression."
            in raw_msg,
            "Source was not rejected properly:\n%s" % raw_msg)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)


