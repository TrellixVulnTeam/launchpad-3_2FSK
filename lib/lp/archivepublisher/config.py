# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
#
# This is the python package that defines the
# 'lp.archivepublisher.config' package. This package is related
# to managing the archive publisher's configuration as stored in the
# distribution and distroseries tables

import os

from zope.component import getUtility

from canonical.config import config
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.soyuz.enums import ArchivePurpose


APT_FTPARCHIVE_PURPOSES = (ArchivePurpose.PRIMARY, ArchivePurpose.COPY)


def getPubConfig(archive):
    """Return an overridden Publisher Configuration instance.

    The original publisher configuration based on the distribution is
    modified according local context, it basically fixes the archive
    paths to cope with non-primary and PPA archives publication workflow.
    """
    pubconf = Config()
    ppa_config = config.personalpackagearchive
    db_pubconf = getUtility(
        IPublisherConfigSet).getByDistribution(archive.distribution)

    pubconf.temproot = os.path.join(
        db_pubconf.root_dir, '%s-temp' % archive.distribution.name)

    if archive.is_ppa:
        if archive.private:
            pubconf.distroroot = ppa_config.private_root
            pubconf.htaccessroot = os.path.join(
                pubconf.distroroot, archive.owner.name, archive.name)
        else:
            pubconf.distroroot = ppa_config.root
            pubconf.htaccessroot = None
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot, archive.owner.name, archive.name,
            archive.distribution.name)
    elif archive.is_main:
        pubconf.distroroot = db_pubconf.root_dir
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot, archive.distribution.name)
        if archive.purpose == ArchivePurpose.PARTNER:
            pubconf.archiveroot += '-partner'
        elif archive.purpose == ArchivePurpose.DEBUG:
            pubconf.archiveroot += '-debug'
    elif archive.is_copy:
        pubconf.distroroot = db_pubconf.root_dir
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot,
            archive.distribution.name + '-' + archive.name,
            archive.distribution.name)
    else:
        raise AssertionError(
            "Unknown archive purpose %s when getting publisher config.",
            archive.purpose)

    # There can be multiple copy archives, so the temp dir needs to be
    # within the archive.
    if archive.is_copy:
        pubconf.temproot = pubconf.archiveroot + '-temp'

    if archive.purpose in APT_FTPARCHIVE_PURPOSES:
        pubconf.overrideroot = pubconf.archiveroot + '-overrides'
        pubconf.cacheroot = pubconf.archiveroot + '-cache'
        pubconf.miscroot = pubconf.archiveroot + '-misc'
    else:
        pubconf.overrideroot = None
        pubconf.cacheroot = None
        pubconf.miscroot = None

    pubconf.poolroot = os.path.join(pubconf.archiveroot, 'pool')
    pubconf.distsroot = os.path.join(pubconf.archiveroot, 'dists')

    meta_root = os.path.join(
        pubconf.distroroot, archive.owner.name)
    pubconf.metaroot = os.path.join(
        meta_root, "meta", archive.name)

    return pubconf


class Config(object):
    """Manage a publisher configuration from the database. (Read Only)
    This class provides a useful abstraction so that if we change
    how the database stores configuration then the publisher will not
    need to be re-coded to cope"""

    def setupArchiveDirs(self):
        """Create missing required directories in archive."""
        required_directories = [
            self.distroroot,
            self.poolroot,
            self.distsroot,
            self.archiveroot,
            self.cacheroot,
            self.overrideroot,
            self.miscroot,
            self.temproot,
            ]

        for directory in required_directories:
            if directory is None:
                continue
            if not os.path.exists(directory):
                os.makedirs(directory, 0755)
