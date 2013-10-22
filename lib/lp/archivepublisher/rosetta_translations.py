# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The processing of Rosetta translations tarballs.

ROSETTA-TRANSLATIONS is a custom format upload supported by Launchpad
infrastructure to enable developers to publish translations.
"""

__metaclass__ = type

__all__ = [
    'RosettaTranslationsUpload',
    'process_rosetta_translations',
    ]

from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.customupload import CustomUpload
from lp.archivepublisher.debversion import Version
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.archive import MAIN_ARCHIVE_PURPOSES
from lp.soyuz.interfaces.packagetranslationsuploadjob import (
    IPackageTranslationsUploadJobSource,
    )


class RosettaTranslationsUpload(CustomUpload):
    """Rosetta Translations tarball upload.

    All other CustomUploads extract and copy files when processed,
    RosettaTranslationsUpload is a special case that involves more than
    copying the files, so it triggers a job that processes them accordingly.
    For this reason, all methods from CustomUpload that deal with files are
    bypassed.
    """
    custom_type = "rosetta-translations"

    package_name = None

    def process(self, packageupload, libraryfilealias):
        if packageupload.package_name is None:
            self.setComponents(libraryfilealias.filename)
        else:
            self.package_name = packageupload.package_name

        # Ignore translations not with main distribution purposes.
        if packageupload.archive.purpose not in MAIN_ARCHIVE_PURPOSES:
            if self.logger is not None:
                self.logger.debug(
                    "Skipping translations since its purpose is not "
                    "in MAIN_ARCHIVE_PURPOSES.")
            return

        # If the distroseries is 11.10 (oneiric) or later, the valid names
        # check is not required.  (See bug 788685.)
        distroseries = packageupload.distroseries
        do_names_check = Version(distroseries.version) < Version('11.10')

        latest_publication = self._findSourcePublication(packageupload)
        component_name = latest_publication.component.name
        spr = latest_publication.sourcepackagerelease

        valid_pockets = (
            PackagePublishingPocket.RELEASE, PackagePublishingPocket.SECURITY,
            PackagePublishingPocket.UPDATES, PackagePublishingPocket.PROPOSED)
        valid_components = ('main', 'restricted')
        if (packageupload.pocket not in valid_pockets or
            (do_names_check and
                component_name not in valid_components)):
            # XXX: CarlosPerelloMarin 2006-02-16 bug=31665:
            # This should be implemented using a more general rule to accept
            # different policies depending on the distribution.
            # Ubuntu's MOTU told us that they are not able to handle
            # translations like we do in main. We are going to import only
            # packages in main.
            return

        blamee = packageupload.findPersonToNotify()
        if blamee is None:
            blamee = getUtility(ILaunchpadCelebrities).rosetta_experts
        getUtility(IPackageTranslationsUploadJobSource).create(
            distroseries, libraryfilealias, spr.sourcepackagename, blamee)

    @staticmethod
    def parsePath(tarfile_name):
        """Parses the lfa filename."""
        bits = tarfile_name.split("_")
        if len(bits) != 4:
            raise ValueError(
                "%s is not NAME_VERSION_ARCH_translations.tar.gz" %
                tarfile_name)
        return tuple(bits)

    def setComponents(self, tarfile_name):
        """Sets the package name parsed from the lfa filename."""
        self.package_name = self.parsePath(tarfile_name)[0]

    def setTargetDirectory(self, pubconf, tarfile_path, distroseries):
        pass

    @classmethod
    def getSeriesKey(cls, tarfile_path):
        pass

    def shouldInstall(self, filename):
        pass

    def _findSourcePublication(self, packageupload):
        """Find destination source publishing record of the packageupload."""
        if self.package_name is None:
            # If package_name is None, the query below will return the latest
            # publication for any package. We don't want that.
            raise AssertionError("package_name should not be None.")
        return packageupload.archive.getPublishedSources(
            name=self.package_name, exact_match=True,
            distroseries=packageupload.distroseries,
            pocket=packageupload.pocket).first()


def process_rosetta_translations(packageupload, libraryfilealias, logger=None):
    """Process a Rosetta translation upload."""
    upload = RosettaTranslationsUpload(logger)
    upload.process(packageupload, libraryfilealias)
