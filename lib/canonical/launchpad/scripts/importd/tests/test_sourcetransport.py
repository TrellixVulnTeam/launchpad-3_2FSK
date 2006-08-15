# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Test canonical.launchpad.scripts.importd.sourcetransport
"""

__metaclass__ = type

__all__ = ['test_suite']


import os
import unittest
import shutil
import subprocess

from canonical.config import config
from canonical.launchpad.scripts.importd.tests.sourcetransport_helpers import (
    ImportdSourceTarballTestCase, ImportdSourceTransportTestCase)


class TestImportdSourceTransportScripts(ImportdSourceTransportTestCase):
    """Test that the script front-ends for ImportdSourceTransport work."""

    def runScript(self, command):
        """Run the named script, fail if it exits with a non-zero status."""
        script = os.path.join(config.root, 'scripts', command)
        process = subprocess.Popen(
            [script, '-q', self.local_source, self.remote_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=open('/dev/null'))
        output, error = process.communicate()
        status = process.returncode
        self.assertEqual(status, 0,
            '%s existed with status=%d\n'
            '>>>stdout<<<\n%s\n>>>stderr<<<\n%s'
            % (command, status, output, error))

    def test_importdPutSource(self):
        # Check that the importd-put-source.py script runs and does something
        # that looks right. That ensures there is no trivial bug in the script.
        os.mkdir(self.local_source)
        assert not os.path.exists(self.remote_tarball)
        self.runScript('importd-put-source.py')
        self.assertTrue(os.path.isfile(self.remote_tarball))

    def setUpTarball(self):
        """Create an appropriate tarball in remote_dir.

        It must have a name based on local_source and it must contain a single
        directory whose name is the basename of local_source.
        """
        source = self.local_source
        assert not os.path.exists(source)
        os.mkdir(source)
        source_parent, source_name = os.path.split(self.local_source)
        retcode = subprocess.call(
            ['tar', 'czf',
             self.remote_tarball, source_name, '-C', source_parent])
        assert retcode == 0
        shutil.rmtree(source)

    def test_importdGetSource(self):
        # Check that the importd-get-source.py script runs and does something
        # that looks right. That ensures there is no trivial bug in the script.
        self.setUpTarball()
        assert not os.path.exists(self.local_source)
        self.runScript('importd-get-source.py')
        self.assertTrue(os.path.isdir(self.local_source))


class TestPutImportdSourceTarball(ImportdSourceTarballTestCase):
    """Tests for putImportdSource that care about tarball contents."""

    def testPutImportdSource(self):
        # Check that putImportdSource creates a tarball at the expected
        # location with the contents of the source tree.
        self.setUpLocalSource()
        self.transport.putImportdSource()
        self.assertTarballMatchesSource(self.remote_tarball)

    def testCreateTarball(self):
        # Check that _createTarball creates a tarball with the contents of the
        # source tree.
        self.setUpLocalSource()
        self.transport._createTarball()
        self.assertTarballMatchesSource(self.local_tarball)

    def testOverwriteTarball(self):
        # Check that _createTarball overwrites any existing file using the name
        # of the tarball.
        self.setUpLocalSource()
        # We create a non-tarball file in place of the tarball, so if it is not
        # entirely overwritten, either the creation or the verification of the
        # tarball will fail.
        not_tarball = open(self.local_tarball, 'w')
        not_tarball.write("invalid content\n")
        not_tarball.close()
        # Now, _createTarball must still create the content we expect.
        self.transport._createTarball()
        self.assertTarballMatchesSource(self.local_tarball)


class TestPutImportdSourceUploadTarball(ImportdSourceTransportTestCase):

    def setUpRemoteDir(self):
        """Do nothing. Delegate to individual test methods."""

    def setUpTransport(self):
        """Do nothing. Delegate to individual test methods."""

    def testUploadTarball(self):
        # Check that _uploadTarball sends the tarball data to the remote_dir,
        # in a swap file. We use a temporary swap file so failed uploads do not
        # erase the existing tarball. The remote transport might already
        # provide this guarantee, but it would be hard for us to test.
        ImportdSourceTransportTestCase.setUpRemoteDir(self)
        ImportdSourceTransportTestCase.setUpTransport(self)
        assert os.path.exists(self.remote_dir)
        # We use the nice default fixture where remote_dir exists.
        self.writeDistinctiveData(self.local_tarball)
        self.transport._uploadTarball()
        self.assertDistinctiveData(self.remote_tarball_swap)

    def testCreateRemoteDir(self):
        # Check that _uploadTarball creates the remote directory if needed.
        # Setup a non-existing remote_dir whose parent exists.
        self.remote_dir = self.sandbox.join('remote', 'subdir')
        os.mkdir(os.path.dirname(self.remote_dir))
        self.remote_tarball_swap = os.path.join(
            self.remote_dir, 'fooworking.tgz.swp')
        ImportdSourceTransportTestCase.setUpTransport(self)
        # Make sure we actually have the right setup
        assert not os.path.exists(self.remote_dir)
        assert os.path.isdir(os.path.dirname(self.remote_dir))
        # _uploadTarball must create the remote_dir and upload the file
        self.writeDistinctiveData(self.local_tarball)
        self.transport._uploadTarball()
        self.assertTrue(os.path.isdir(self.remote_dir))
        self.assertDistinctiveData(self.remote_tarball_swap)

    def testFinalizeUpload(self):
        # Check that _finalizeUpload renames the remote swap file to the remote
        # tarball name even if the remote tarball is already present.
        ImportdSourceTransportTestCase.setUpRemoteDir(self)
        ImportdSourceTransportTestCase.setUpTransport(self)
        self.writeDistinctiveData(self.remote_tarball_swap)
        self.writeData(self.remote_tarball, "Bad data\n")
        self.transport._finalizeUpload()
        self.assertFalse(os.path.exists(self.remote_tarball_swap))
        self.assertDistinctiveData(self.remote_tarball)

    def testCleanUpRemoteDir(self):
        # _cleanUpRemoteDir deletes any file present in remote_dir, except the
        # final tarball that it must leave untouched. Deleting unknown files is
        # needed because the bzrlib transport may use random temporary names
        # during the upload, and we do not want to let failed uploads
        # accumulate cruft.
        ImportdSourceTransportTestCase.setUpRemoteDir(self)
        ImportdSourceTransportTestCase.setUpTransport(self)
        self.writeDistinctiveData(self.remote_tarball)
        self.writeData(self.remote_tarball_swap, "Swap data\n")
        random_path = os.path.join(self.remote_dir, 'random')
        self.writeData(random_path, "Random data\n")
        # Make sure we have created the files in the same place.
        remote_names = os.listdir(self.remote_dir)
        expected_names = [os.path.basename(path) for path in
            [self.remote_tarball_swap, self.remote_tarball, random_path]]
        assert sorted(remote_names) == sorted(expected_names)
        # Run _cleanupRemoteDir and check that only the tarball is left, and
        # that it was untouched.
        self.transport._cleanUpRemoteDir()
        remote_names = os.listdir(self.remote_dir)
        self.assertEqual(remote_names, [os.path.basename(self.remote_tarball)])
        self.assertDistinctiveData(self.remote_tarball)

    def testCleanupRemoteDirMissing(self):
        # _cleanUpRemoteDir must work even if the remote_dir does not exist,
        # because it is run before trying to upload the tarball.
        self.remote_dir = self.sandbox.join('remote')
        ImportdSourceTransportTestCase.setUpTransport(self)
        # Make sure the remote_dir does not exist.
        assert not os.path.exists(self.remote_dir)
        # call _cleanUpRemoteDir, it should do nothing.
        self.transport._cleanUpRemoteDir()


class TestGetImportdSourceTarball(ImportdSourceTarballTestCase):
    """Test for getImportdSource that care about tarball contents."""

    def testGetImportdSource(self):
        # Check that getImportdSource creates a source tree provided the remote
        # tarball is present.
        self.setUpRemoteTarball()
        # Make sure local_source was not left behind by setUpRemoteTarball.
        assert not os.path.exists(self.local_source)
        self.transport.getImportdSource()
        self.assertGoodSourcePresent(self.sandbox.path)

    def testExtractTarball(self):
        # Check that _extractTarball extracts the contents of localTarball in
        # the right place.
        self.setUpRemoteTarball()
        # Make sure local_source was not left behind by setUpRemoteTarball.
        assert not os.path.exists(self.local_source)
        os.rename(self.remote_tarball, self.local_tarball)
        self.transport._extractTarball()
        self.assertGoodSourcePresent(self.sandbox.path)


class TestPutImportdSource(ImportdSourceTransportTestCase):

    def testCleanUpLocalDir(self):
        # _cleanUpLocalDir deletes the local tarball and source tree if they
        # are present.
        self.writeDistinctiveData(self.local_tarball)
        # Create a file in local_source to test recursive delete
        os.mkdir(self.local_source)
        source_file = os.path.join(self.local_source, 'a_file')
        self.writeDistinctiveData(source_file)
        # At this point we have a file as local_tarball, and a non-empty
        # directory as local_source.
        self.transport._cleanUpLocalDir()
        self.assertFalse(os.path.exists(self.local_source))
        self.assertFalse(os.path.exists(self.local_tarball))

    def testCleanUpLocalDirNoop(self):
        # In the beginning, there was nothing. But _cleanUpLocalDir should
        # still not fail, but should do nothing.
        assert not os.path.exists(self.local_source)
        assert not os.path.exists(self.local_tarball)
        self.transport._cleanUpLocalDir()

    def testDownloadTarball(self):
        # _downloadTarball must copy remote_tarball to local_tarball
        self.writeDistinctiveData(self.remote_tarball)
        assert not os.path.exists(self.local_tarball)
        self.transport._downloadTarball()
        self.assertDistinctiveData(self.local_tarball)


# TODO: feature test transition: getImportdSource does putImportdSource if the
# remote tarball is missing and there is a local source tree.

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
