# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Permissions for uploading a package to an archive."""

__metaclass__ = type
__all__ = [
    'CannotUploadToArchive',
    'CannotUploadToPPA',
    'components_valid_for',
    'verify_upload',
    ]

from zope.component import getUtility

from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet


class CannotUploadToArchive(Exception):
    """Raised when a person cannot upload to archive."""

    _fmt = '%(person)s has no upload rights to %(archive)s.'

    def __init__(self, person, archive):
        """Construct a `CannotUploadToArchive`.

        :param person: The person trying to get at the archive.
        :param archive: The archive.
        """
        Exception.__init__(
            self, self._fmt % {'person': person, 'archive': archive})


class CannotUploadToPPA(CannotUploadToArchive):
    """Raised when a person cannot upload to a PPA."""

    _fmt = 'Signer has no upload rights to this PPA.'


def components_valid_for(archive, person):
    """Return the components that 'person' can upload to 'archive'.

    :param archive: The `IArchive` than 'person' wishes to upload to.
    :param person: An `IPerson` wishing to upload to an archive.
    :return: A `set` of `IComponent`s that 'person' can upload to.
    """
    permission_set = getUtility(IArchivePermissionSet)
    permissions = permission_set.componentsForUploader(archive, person)
    return set(permission.component for permission in permissions)


def verify_upload(person, sourcepackagename, archive, component,
                  strict_component=True):
    """Can 'person' upload 'suite_sourcepackage' to 'archive'?

    :param person: The `IPerson` trying to upload to the package.
    :param archive: The `IArchive` being uploaded to.
    :param strict_component: True if access to the specific component for the
        package is needed to upload to it. If False, then access to any
        package will do.
    :raise CannotUploadToArchive: If 'person' cannot upload to the archive.
    :return: Nothing of interest.
    """
    # For PPAs...
    if archive.purpose == ArchivePurpose.PPA:
        if not archive.canUpload(person):
            raise CannotUploadToPPA(person, archive)
        else:
            return True

    # For any other archive...
    ap_set = getUtility(IArchivePermissionSet)
    if sourcepackagename is not None and (
        archive.canUpload(person, sourcepackagename)
        or ap_set.isSourceUploadAllowed(archive, sourcepackagename, person)):
        return

    if component is not None:
        if strict_component:
            if archive.canUpload(person, component):
                return
        else:
            if len(components_valid_for(archive, person)) != 0:
                return
    raise CannotUploadToArchive(person, archive)
