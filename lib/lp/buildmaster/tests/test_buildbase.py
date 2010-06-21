# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import with_statement

"""Tests for `IBuildBase`.

   XXX 2010-04-26 michael.nelson bug=567922.
   These tests should be moved into test_packagebuild when buildbase is
   deleted. For the moment, test_packagebuild inherits these tests to
   ensure the new classes pass too.
"""
__metaclass__ = type

from datetime import datetime
import os
import shutil
import tempfile
import unittest
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.launchpad.scripts import BufferLogger
from canonical.database.constants import UTC_NOW
from canonical.testing.layers import LaunchpadZopelessLayer
from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.buildmaster.model.buildbase import BuildBase
from lp.soyuz.tests.soyuzbuilddhelpers import WaitingSlave
from lp.testing import TestCase
from lp.testing.fakemethod import FakeMethod


class TestBuildBaseMixin:
    """Tests for `IBuildBase`."""

    def test_getUploadDirLeaf(self):
        # getUploadDirLeaf returns the current time, followed by the build
        # cookie.
        now = datetime.now()
        build_cookie = self.factory.getUniqueString()
        upload_leaf = self.package_build.getUploadDirLeaf(
            build_cookie, now=now)
        self.assertEqual(
            '%s-%s' % (now.strftime("%Y%m%d-%H%M%S"), build_cookie),
            upload_leaf)

    def test_getUploadDir(self):
        # getUploadDir is the absolute path to the directory in which things
        # are uploaded to.
        build_cookie = self.factory.getUniqueInteger()
        upload_leaf = self.package_build.getUploadDirLeaf(build_cookie)
        upload_dir = self.package_build.getUploadDir(upload_leaf)
        self.assertEqual(
            os.path.join(config.builddmaster.root, 'incoming', upload_leaf),
            upload_dir)


class TestBuildBase(TestCase, TestBuildBaseMixin):

    def setUp(self):
        """Create the package build for testing."""
        super(TestBuildBase, self).setUp()
        self.package_build = BuildBase()


class TestGetUploadMethodsMixin:
    """Tests for `IBuildBase` that need objects from the rest of Launchpad."""

    layer = LaunchpadZopelessLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs.

        XXX michaeln 2010-06-03 bug=567922
        Until buildbase is removed, we need to ensure these tests
        run against new IPackageBuild builds (BinaryPackageBuild)
        and the IBuildBase builds (SPRecipeBuild). They assume the build
        is successfully built and check that incorrect upload paths will
        set the status to FAILEDTOUPLOAD.
        """
        raise NotImplemented

    def setUp(self):
        super(TestGetUploadMethodsMixin, self).setUp()
        self.build = self.makeBuild()

    def assertQueuePath(self, path):
        """Check if given path exists within the current queue_location."""
        probe_path = os.path.join(self.queue_location, path)
        self.assertTrue(
            os.path.exists(probe_path), "'%s' does not exist." % path)

    def testSimpleRun(self):
        """Try a simple process-upload run.

        Observe it creating the required directory tree for a given
        empty queue_location.
        """
        logger = BufferLogger()
        self.build.processUpload(self.leaf,
            self.queue_location, logger)

        # Directory tree in place.
        for directory in ['incoming', 'accepted', 'rejected', 'failed']:
            self.assertQueuePath(directory)

        # Just to check if local assertion is working as expect.
        self.assertRaises(AssertionError, self.assertQueuePath, 'foobar')


class TestHandleStatusMixin:
    """Tests for `IBuildBase`s handleStatus method.

    Note: these tests do *not* test the updating of the build
    status to FULLYBUILT as this happens during the upload which
    is stubbed out by a mock function.
    """

    layer = LaunchpadZopelessLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs.

        XXX michaeln 2010-06-03 bug=567922
        Until buildbase is removed, we need to ensure these tests
        run against new IPackageBuild builds (BinaryPackageBuild)
        and the IBuildBase builds (SPRecipeBuild). They assume the build
        is successfully built and check that incorrect upload paths will
        set the status to FAILEDTOUPLOAD.
        """
        raise NotImplementedError

    def setUp(self):
        super(TestHandleStatusMixin, self).setUp()
        self.build = self.makeBuild()
        # For the moment, we require a builder for the build so that
        # handleStatus_OK can get a reference to the slave.
        builder = self.factory.makeBuilder()
        self.build.buildqueue_record.builder = builder
        self.build.buildqueue_record.setDateStarted(UTC_NOW)
        self.slave = WaitingSlave('BuildStatus.OK')
        self.slave.valid_file_hashes.append('test_file_hash')
        builder.setSlaveForTesting(self.slave)

        # We overwrite the buildmaster root to use a temp directory.
        tmp_dir = self.makeTemporaryDirectory()
        tmp_builddmaster_root = """
        [builddmaster]
        root: %s
        """ % tmp_dir
        config.push('tmp_builddmaster_root', tmp_builddmaster_root)

        # We stub out our builds processUpload() method so
        # we can check whether it was called.
        self.build.processUpload = FakeMethod(
            result=None)

    def test_handleStatus_OK_normal_file(self):
        # A filemap with plain filenames should not cause a problem.
        # The call to handleStatus will attempt to get the file from
        # the slave resulting in a URL error in this test case.
        self.build.handleStatus('OK', None, {
                'filemap': { 'myfile.py': 'test_file_hash'},
                })

        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertEqual(1, self.build.processUpload.call_count)

    def test_handleStatus_OK_absolute_filepath(self):
        # A filemap that tries to write to files outside of
        # the upload directory will result in a failed upload.
        self.build.handleStatus('OK', None, {
            'filemap': { '/tmp/myfile.py': 'test_file_hash'},
            })
        self.assertEqual(BuildStatus.FAILEDTOUPLOAD, self.build.status)
        self.assertEqual(0, self.build.processUpload.call_count)

    def test_handleStatus_OK_relative_filepath(self):
        # A filemap that tries to write to files outside of
        # the upload directory will result in a failed upload.
        self.build.handleStatus('OK', None, {
            'filemap': { '../myfile.py': 'test_file_hash'},
            })
        self.assertEqual(BuildStatus.FAILEDTOUPLOAD, self.build.status)
        self.assertEqual(0, self.build.processUpload.call_count)

    def test_handleStatus_OK_sets_build_log(self):
        # The build log is set during handleStatus.
        removeSecurityProxy(self.build).log = None
        self.assertEqual(None, self.build.log)
        self.build.handleStatus('OK', None, {
                'filemap': { 'myfile.py': 'test_file_hash'},
                })
        self.assertNotEqual(None, self.build.log)

    def test_date_finished_set(self):
        # The date finished is updated during handleStatus_OK.
        removeSecurityProxy(self.build).date_finished = None
        self.assertEqual(None, self.build.date_finished)
        self.build.handleStatus('OK', None, {
                'filemap': { 'myfile.py': 'test_file_hash'},
                })
        self.assertNotEqual(None, self.build.date_finished)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
