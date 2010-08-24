#!/usr/bin/python
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from lp.archiveuploader.uploadpolicy import AbstractUploadPolicy
from lp.testing import TestCase


class TestUploadPolicy_validateUploadType(TestCase):
    """Test what kind (sourceful/binaryful/mixed) of uploads are accepted."""

    def test_sourceful_accepted(self):
        policy = make_policy(can_upload_source=True)
        upload = make_fake_upload(sourceful=True)

        policy.validateUploadType(upload)

        self.assertEquals([], upload.rejections)

    def test_binaryful_accepted(self):
        policy = make_policy(can_upload_binaries=True)
        upload = make_fake_upload(binaryful=True)

        policy.validateUploadType(upload)

        self.assertEquals([], upload.rejections)

    def test_mixed_accepted(self):
        policy = make_policy(can_upload_mixed=True)
        upload = make_fake_upload(sourceful=True, binaryful=True)

        policy.validateUploadType(upload)

        self.assertEquals([], upload.rejections)

    def test_sourceful_not_accepted(self):
        policy = make_policy(can_upload_source=False)
        upload = make_fake_upload(sourceful=True)

        policy.validateUploadType(upload)

        self.assertIn(
            'Sourceful uploads are not accepted by this policy.',
            upload.rejections)

    def test_binaryful_not_accepted(self):
        policy = make_policy(can_upload_binaries=False)
        upload = make_fake_upload(binaryful=True)

        policy.validateUploadType(upload)

        self.assertTrue(len(upload.rejections) > 0)
        self.assertIn(
            'Upload rejected because it contains binary packages.',
            upload.rejections[0])

    def test_mixed_not_accepted(self):
        policy = make_policy(can_upload_mixed=False)
        upload = make_fake_upload(sourceful=True, binaryful=True)

        policy.validateUploadType(upload)

        self.assertIn(
            'Source/binary (i.e. mixed) uploads are not allowed.',
            upload.rejections)

    def test_sourceful_when_only_mixed_accepted(self):
        policy = make_policy(can_upload_mixed=True)
        upload = make_fake_upload(sourceful=True, binaryful=False)

        policy.validateUploadType(upload)

        self.assertIn(
            'Sourceful uploads are not accepted by this policy.',
            upload.rejections)

    def test_binaryful_when_only_mixed_accepted(self):
        policy = make_policy(can_upload_mixed=True)
        upload = make_fake_upload(sourceful=False, binaryful=True)

        policy.validateUploadType(upload)

        self.assertTrue(len(upload.rejections) > 0)
        self.assertIn(
            'Upload rejected because it contains binary packages.',
            upload.rejections[0])


class FakeNascentUpload:

    def __init__(self, sourceful, binaryful):
        self.sourceful = sourceful
        self.binaryful = binaryful
        self.is_ppa = False
        self.rejections = []

    def reject(self, msg):
        self.rejections.append(msg)


def make_fake_upload(sourceful=False, binaryful=False):
    return FakeNascentUpload(sourceful, binaryful)


def make_policy(can_upload_source=False, can_upload_binaries=False,
                can_upload_mixed=False):
    policy = AbstractUploadPolicy()
    policy.can_upload_mixed = can_upload_mixed
    policy.can_upload_binaries = can_upload_binaries
    policy.can_upload_source = can_upload_source
    return policy

