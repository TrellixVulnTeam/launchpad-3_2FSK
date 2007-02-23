# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""The processing of debian installer tarballs."""

# This code is mostly owned by Colin Watson and is partly refactored by
# Daniel Silverstone who should be the first point of contact for it.

__metaclass__ = type

__all__ = ['process_debian_installer', 'DebianInstallerError']

import os
import tarfile
import stat
import shutil

from canonical.archivepublisher.custom_upload import (
    CustomUpload, CustomUploadError)
from sourcerer.deb.version import Version as make_version


class DebianInstallerAlreadyExists(CustomUploadError):
    """A build for this type, architecture, and version already exists."""
    def __init__(self, build_type, arch, version):
        message = ('%s build %s for architecture %s already exists' %
                   (build_type, arch, version))
        DebianInstallerError.__init__(self, message)


class DebianInstallerUpload(CustomUpload):

    def __init__(self, archive_root, tarfile_path, distrorelease):
        CustomUpload.__init__(self, archive_root, tarfile_path, distrorelease)

        tarfile_base = os.path.basename(tarfile_path)
        components = tarfile_base.split('_')
        self.version = components[1]
        self.arch = components[2].split('.')[0]

        # Is this a full build or a daily build?
        if '.0.' not in self.version:
            build_type = 'installer'
        else:
            build_type = 'daily-installer'

        self.targetdir = os.path.join(
            archive_root, 'dists', distrorelease, 'main',
            '%s-%s' % (build_type, self.arch))

        if os.path.exists(os.path.join(self.targetdir, self.version)):
            raise DebianInstallerAlreadyExists(build_type, self.arch,
                                               self.version)

    def extract(self):
        CustomUpload.extract(self)
        # We now have a valid unpacked installer directory, but it's one level
        # deeper than it should be. Move it up and remove the debris.
        unpack_dir = 'installer-%s' % self.arch
        os.rename(os.path.join(self.tmpdir, unpack_dir, self.version),
                  os.path.join(self.tmpdir, self.version))
        shutil.rmtree(os.path.join(self.tmpdir, unpack_dir))

    def shouldInstall(self, filename):
        return filename.startswith('%s/' % self.version)


def process_debian_installer(archive_root, tarfile_path, distrorelease):
    """Process a raw-installer tarfile.

    Unpacking it into the given archive for the given distrorelease.
    Raises CustomUploadError (or some subclass thereof) if anything goes
    wrong.
    """
    upload = DebianInstallerUpload(archive_root, tarfile_path, distrorelease)
    upload.process()
