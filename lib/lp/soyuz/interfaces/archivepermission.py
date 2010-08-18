# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0213

"""ArchivePermission interface."""

__metaclass__ = type

__all__ = [
    'ArchivePermissionType',
    'IArchivePermission',
    'IArchivePermissionSet',
    'IArchiveUploader',
    'IArchiveQueueAdmin',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, TextLine
from lazr.enum import DBEnumeratedType, DBItem

from canonical.launchpad import _
from lp.services.fields import PublicPersonChoice
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.component import IComponent
from lp.soyuz.interfaces.packageset import IPackageset
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageName)
from lazr.restful.fields import Reference
from lazr.restful.declarations import (
    export_as_webservice_entry, exported)


class ArchivePermissionType(DBEnumeratedType):
    """Archive Permission Type.

    The permission being granted, such as upload rights, or queue
    manipulation rights.
    """

    UPLOAD = DBItem(1, """
        Archive Upload Rights

        This permission allows a user to upload.
        """)

    QUEUE_ADMIN = DBItem(2, """
        Queue Administration Rights

        This permission allows a user to administer the distroseries
        upload queue.
        """)


class IArchivePermission(Interface):
    """The interface for `ArchivePermission`."""
    export_as_webservice_entry()

    id = Attribute("The archive permission ID.")

    date_created = exported(
        Datetime(
            title=_('Date Created'), required=False, readonly=False,
            description=_("The timestamp when the permission was created.")))

    archive = exported(
        Reference(
            IArchive,
            title=_("Archive"),
            description=_("The archive that this permission is for.")))

    permission = exported(
        Choice(
            title=_("The permission type being granted."),
            values=ArchivePermissionType, readonly=False, required=True))

    person = exported(
        PublicPersonChoice(
            title=_("Person"),
            description=_("The person or team being granted the permission."),
            required=True, vocabulary="ValidPersonOrTeam"))

    component = Reference(
        IComponent,
        title=_("Component"),
        description=_("The component that this permission is related to."))

    sourcepackagename = Reference(
        ISourcePackageName,
        title=_("Source Package Name"),
        description=_("The source package name that this permission is "
                      "related to."))

    # This is the *text* component name, as opposed to `component` above
    # which is the `IComponent` and we don't want to export that.
    component_name = exported(
        TextLine(
            title=_("Component Name"),
            required=True))

    # This is the *text* package name, as opposed to `sourcepackagename`
    # which is the `ISourcePackageName` and we don't want to export
    # that.
    source_package_name = exported(
        TextLine(
            title=_("Source Package Name"),
            required=True))

    packageset = Reference(
            IPackageset,
            title=_("Packageset"),
            description=_("The package set that this permission is for."))

    explicit = exported(
        Bool(
            title=_("Explicit"),
            description=_(
                "Set this flag for package sets with high-profile packages "
                "requiring specialist skills for proper handling.")))

    package_set_name = exported(
        TextLine(
            title=_("Package set name"),
            required=True))

    distro_series_name = exported(
        TextLine(
            title=_(
                "The name of the distro series associated with the "
                "package set."),
            required=True))


class IArchiveUploader(IArchivePermission):
    """Marker interface for URL traversal of uploader permissions."""


class IArchiveQueueAdmin(IArchivePermission):
    """Marker interface for URL traversal of queue admin permissions."""


class IArchivePermissionSet(Interface):
    """The interface for `ArchivePermissionSet`."""

    def checkAuthenticated(person, archive, permission, item):
        """The `ArchivePermission` records that authenticate the person.

        :param person: An `IPerson` whom should be checked for authentication.
        :param archive: The context `IArchive` for the permission check.
        :param permission: The `ArchivePermissionType` to check.
        :param item: The context `IComponent` or `ISourcePackageName` for the
            permission check.

        :return: all the `ArchivePermission` records that match the parameters
        supplied.  If none are returned, it means the person is not
        authenticated in that context.
        """

    def permissionsForPerson(person, archive):
        """All `ArchivePermission` records for the person.

        :param person: An `IPerson`
        :param archive: An `IArchive`
        """

    def uploadersForComponent(archive, component=None):
        """The `ArchivePermission` records for authorised component uploaders.

        :param archive: The context `IArchive` for the permission check.
        :param component: Optional `IComponent`, if specified will only
            return records for uploaders to that component, otherwise
            all components are considered.  You can also supply a string
            component name instead.
        :raises ComponentNotFound: if the named component does not exist.

        :return: `ArchivePermission` records for all the uploaders who
            are authorised for the supplied component.
        """

    def componentsForUploader(archive, person):
        """The `ArchivePermission` records for the person's upload components.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to find out which
            components he has access to.

        :return: `ArchivePermission` records for all the components that
            'person' is allowed to upload to.
        """

    def packagesForUploader(archive, person):
        """The `ArchivePermission` records for the person's upload packages.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to find out which
            packages he has access to.

        :return: `ArchivePermission` records for all the packages that
            'person' is allowed to upload to.
        """

    def uploadersForPackage(archive, sourcepackagename):
        """The `ArchivePermission` records for authorised package uploaders.

        :param archive: The context `IArchive` for the permission check.
        :param sourcepackagename: An `ISourcePackageName` or a string
            package name.
        :raises SourceNotFound: if the string package name does not exist.

        :return: `ArchivePermission` records for all the uploaders who are
            authorised to upload the named source package.
        """

    def packagesetsForUploader(archive, person):
        """The `ArchivePermission` records for the person's package sets.

        :param archive: The archive the permission applies to.
        :param person: An `IPerson` for whom you want to find out which
            package sets he has access to.

        :return: `ArchivePermission` records for all the package sets that
            'person' is allowed to upload to.
        """

    def packagesetsForSourceUploader(archive, sourcepackagename, person):
        """The package set based permissions for a given source and uploader.

        Return the `IArchivePermission` records that
            * apply to the given `archive`
            * relate to
                - package sets that include the given source package name
                - the given `person`

        :param archive: The archive the permission applies to.
        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param person: An `IPerson` for whom you want to find out which
            package sets he has access to.

        :raises SourceNotFound: if a source package with the given
            name could not be found.
        :return: `ArchivePermission` records for the package sets that
            include the given source package name and to which the given
            person may upload.
        """

    def packagesetsForSource(
        archive, sourcepackagename, direct_permissions=True):
        """All package set based permissions for the given archive and source.

        This method is meant to aid the process of "debugging" package set
        based archive permission since It allows the listing of permissions
        for the given source package irrespective of a person.

        :param archive: The archive the permission applies to.
        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param direct_permissions: If set, only package sets that directly
            include the given source will be considered.

        :raises SourceNotFound: if a source package with the given
            name could not be found.
        :return: `ArchivePermission` records for the package sets that
            include the given source package name and apply to the
            archive in question.
        """

    def isSourceUploadAllowed(
        archive, sourcepackagename, person, distroseries=None):
        """True if the person is allowed to upload the given source package.

        Return True if there exists a permission that combines
            * the given `archive`
            * a package set that includes the given source package name
            * the given person or a team he is a member of

        If the source package name is included by *any* package set with
        an explicit permission then only such explicit permissions will
        be considered.

        :param archive: The archive the permission applies to.
        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param person: An `IPerson` for whom you want to find out which
            package sets he has access to.
        :param distroseries: The `IDistroSeries` for which to check
            permissions. If none is supplied then `currentseries` in
            Ubuntu is assumed.

        :raises SourceNotFound: if a source package with the given
            name could not be found.
        :return: True if the person is allowed to upload the source package.
        """

    def uploadersForPackageset(archive, packageset, direct_permissions=True):
        """The `ArchivePermission` records for uploaders to the package set.

        Please note: if a package set *name* is passed the respective
                     package set in the current distro series will be used.

        :param archive: The archive the permission applies to.
        :param packageset: An `IPackageset` or a string package set name.
        :param direct_permissions: If True only consider permissions granted
            directly for the package set at hand. Otherwise, include any
            uploaders for package sets that include this one.
        :raises NotFoundError: if no package set exists with the given name.

        :return: `ArchivePermission` records for all the uploaders who are
            authorized to upload to the named source package set.
        """

    def queueAdminsForComponent(archive, component):
        """The `ArchivePermission` records for authorised queue admins.

        :param archive: The context `IArchive` for the permission check.
        :param component: The context `IComponent` for the permission check.
            You can also supply a string component name instead.

        :return: `ArchivePermission` records for all the person who are
            allowed to administer the distroseries upload queue.
        """

    def componentsForQueueAdmin(archive, person):
        """Return `ArchivePermission` for the person's queue admin components.

        :param archive: The context `IArchive` for the permission check, or
            an iterable of `IArchive`s.
        :param person: An `IPerson` for whom you want to find out which
            components he has access to.

        :return: `ArchivePermission` records for all the components that
            'person' is allowed to administer the queue for.
        """

    def newPackageUploader(archive, person, sourcepackagename):
        """Create and return a new `ArchivePermission` for an uploader.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to add permission.
        :param sourcepackagename: An `ISourcePackageName` or a string
            package name.

        :return: The new `ArchivePermission`, or the existing one if it
            already exists.
        """

    def newPackagesetUploader(archive, person, packageset, explicit=False):
        """Create and return a new `ArchivePermission` for an uploader.

        Please note: if a package set *name* is passed the respective
                     package set in the current distro series will be used.

        :param archive: The archive the permission applies to.
        :param person: An `IPerson` for whom you want to add permission.
        :param packageset: An `IPackageset` or a string package set name.
        :param explicit: True if the permissions granted by this package set
            exclude permissions granted by non-explicit package sets.
        :raises ValueError: if an `ArchivePermission` record for this
            person and packageset already exists *but* with a different
            'explicit' flag value.

        :return: The new `ArchivePermission`, or the existing one if it
            already exists.
        """

    def newComponentUploader(archive, person, component):
        """Create and return a new `ArchivePermission` for an uploader.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to add permission.
        :param component: An `IComponent` or a string package name.

        :return: The new `ArchivePermission`, or the existing one if it
            already exists.
        """

    def newQueueAdmin(archive, person, component):
        """Create and return a new `ArchivePermission` for a queue admin.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to add permission.
        :param component: An `IComponent` or a string package name.

        :return: The new `ArchivePermission`, or the existing one if it
            already exists.
        """

    def deletePackageUploader(archive, person, sourcepackagename):
        """Revoke upload permissions for a person.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to revoke permission.
        :param sourcepackagename: An `ISourcePackageName` or a string
            package name.
        """

    def deletePackagesetUploader(archive, person, packageset, explicit=False):
        """Revoke upload permissions for a person.

        Please note: if a package set *name* is passed the respective
                     package set in the current distro series will be used.

        :param archive: The archive the permission applies to.
        :param person: An `IPerson` for whom you want to revoke permission.
        :param packageset: An `IPackageset` or a string package set name.
        :param explicit: The value of the 'explicit' flag for the permission
            to be revoked.
        """

    def deleteComponentUploader(archive, person, component):
        """Revoke upload permissions for a person.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to revoke permission.
        :param component: An `IComponent` or a string package name.
        """

    def deleteQueueAdmin(self, archive, person, component):
        """Revoke queue admin permissions for a person.

        :param archive: The context `IArchive` for the permission check.
        :param person: An `IPerson` for whom you want to revoke permission.
        :param component: An `IComponent` or a string package name.
        """
