# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Product release interfaces."""

__metaclass__ = type

__all__ = [
    'IProductReleaseSet',
    'IProductRelease',
    'IProductReleaseFile',
    'IProductReleaseFileAddForm',
    'UpstreamFileType',
    ]

from zope.schema import Bytes, Choice, Datetime, Int, Object, Text, TextLine
from zope.interface import Interface, Attribute
from zope.component import getUtility

from canonical.launchpad import _
from canonical.launchpad.validators.version import sane_version
from canonical.launchpad.validators.productrelease import (
    productrelease_file_size_constraint,
    productrelease_signature_size_constraint)
from canonical.launchpad.fields import ContentNameField
from canonical.launchpad.interfaces.person import IPerson

from canonical.lazr.enum import DBEnumeratedType, DBItem
from canonical.lazr.fields import CollectionField, Reference, ReferenceChoice
from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, exported)


class UpstreamFileType(DBEnumeratedType):
    """Upstream File Type

    When upstream open source project release a product they will
    include several files in the release. All of these files are
    stored in Launchpad (we throw nothing away ;-). This schema
    gives the type of files that we know about.
    """

    CODETARBALL = DBItem(1, """
        Code Release Tarball

        This file contains code in a compressed package like
        a tar.gz or tar.bz or .zip file.
        """)

    README = DBItem(2, """
        README File

        This is a README associated with the upstream
        release. It might be in .txt or .html format, the
        filename would be an indicator.
        """)

    RELEASENOTES = DBItem(3, """
        Release Notes

        This file contains the release notes of the new
        upstream release. Again this could be in .txt or
        in .html format.
        """)

    CHANGELOG = DBItem(4, """
        ChangeLog File

        This file contains information about changes in this
        release from the previous release in the series. This
        is usually not a detailed changelog, but a high-level
        summary of major new features and fixes.
        """)

    INSTALLER = DBItem(5, """
        Installer file

        This file contains an installer for a product.  It may
        be a Debian package, an RPM file, an OS X disk image, a
        Windows installer, or some other type of installer.
        """)


class ProductReleaseVersionField(ContentNameField):

    errormessage = _(
        "%s is already in use by another version in this release series.")

    @property
    def _content_iface(self):
        return IProductRelease

    def _getByName(self, version):
        """Return the content object for the specified version.

        The version is specified either by the context directly or by the
        context's referenced productseries.  Overridden from
        `ContentFieldName`.
        """
        # Import locally to avoid circular imports.
        from canonical.launchpad.interfaces.productseries import (
            IProductSeries)
        if IProductSeries.providedBy(self.context):
            productseries = self.context
        else:
            productseries = self.context.productseries
        releaseset = getUtility(IProductReleaseSet)
        return releaseset.getBySeriesAndVersion(productseries, version)


class IProductReleaseFile(Interface):
    """A file associated with a ProductRelease."""
    export_as_webservice_entry("project_release_file")

    id = Int(title=_('ID'), required=True, readonly=True)
    productrelease = exported(
        ReferenceChoice(title=_('Project release'),
                        description=_("The parent product release."),
                        schema=Interface, # Defined later.
                        required=True,
                        vocabulary='ProductRelease'),
        exported_as='project_release')
    libraryfile = exported(
        Bytes(title=_("File"),
              description=_("The file contents."),
              readonly=True,
              required=True),
        exported_as='file')
    signature = exported(
        Bytes(title=_("File signature"),
              description=_("The file signature."),
              readonly=True,
              required=False))
    filetype = exported(
        Choice(title=_("Upstream file type"), required=True,
               vocabulary=UpstreamFileType,
               default=UpstreamFileType.CODETARBALL),
        exported_as='file_type')
    description = exported(
        Text(title=_("Description"), required=False,
             description=_('A detailed description of the file contents')))
    date_uploaded = exported(
        Datetime(title=_('Upload date'),
                 description=_('The date this file was uploaded'),
                 required=True, readonly=True))


class IProductRelease(Interface):
    """A specific release (i.e. has a version) of a product. For example,
    Mozilla 1.7.2 or Apache 2.0.48."""
    export_as_webservice_entry('project_release')

    id = Int(title=_('ID'), required=True, readonly=True)

    datereleased = exported(
        Datetime(
            title=_('Date Released'), required=True,
            readonly=False,
            description=_('The date this release was published. Before '
                          'release, this should have an estimated '
                          'release date.')),
        exported_as="date_released"
        )

    version = exported(
        ProductReleaseVersionField(
            title=_('Version'),
            description= u'The specific version number assigned to this '
            'release. Letters and numbers are acceptable, for releases like '
            '"1.2rc3".',
            readonly=True, constraint=sane_version)
        )

    owner = exported(
            Object(title=u"The owner of this release.",
                   schema=IPerson, required=True)
            )

    productseries = exported(
        Choice(
            title=_('Release series'), readonly=True,
            vocabulary='FilteredProductSeries'),
        exported_as='project_series')

    codename = exported(
        TextLine(title=u'Code name', required=False,
                 description=u'The release code-name. Famously, one Gnome '
                 'release was code-named "that, and a pair of testicles", but '
                 "you don't have to be as brave with your own release "
                 'codenames.'),
        exported_as='code_name')

    summary = exported(
        Text(
            title=_("Summary"), required=False,
            description=_('A brief summary of the release highlights, to '
                          'be shown at the top of the release page, and in '
                          'listings.'))
        )

    description = exported(
        Text(
            title=_("Description"), required=False,
            description=_('A detailed description of the new features '
                          '(though the changelog below might repeat some of '
                          'this information). The description here will be '
                          'shown on the project release home page.'))
        )

    changelog = exported(
        Text(
            title=_('Changelog'), required=False)
        )

    datecreated = exported(
        Datetime(title=_('Date Created'),
                 description=_("The date this project release was created in "
                               "Launchpad."),
                 required=True, readonly=True),
        exported_as="date_created")

    displayname = exported(
        Text(title=u'Constructed display name for a project release.',
             readonly=True),
        exported_as="display_name")

    title = exported(
        Text(title=u'Constructed title for a project release.')
        )

    product = exported(
        Object(title=u'The upstream project of this release.',
               schema=Interface),
         exported_as="project")

    files = exported(
        CollectionField(
            title=_('Project release files'),
            description=_('A list of files for this release.'),
            readonly=True,
            value_type=Reference(schema=IProductReleaseFile)))

    def addFileAlias(alias, signature,
                     uploader,
                     file_type=UpstreamFileType.CODETARBALL,
                     description=None):
        """Add a link between this product and a library file alias."""

    def deleteFileAlias(alias):
        """Delete the link between this product and a library file alias."""

    def getFileAliasByName(name):
        """Return the `LibraryFileAlias` by file name.

        Raises a NotFoundError if no matching ProductReleaseFile exists.
        """

    def getProductReleaseFileByName(name):
        """Return the `ProductReleaseFile` by file name.

        Raises a NotFoundError if no matching ProductReleaseFile exists.
        """

# Set the schema for IProductReleaseFile now that IProductRelease is defined.
IProductReleaseFile['productrelease'].schema = IProductRelease


class IProductReleaseFileAddForm(Interface):
    """Schema for adding ProductReleaseFiles to a project."""
    description = Text(title=_("Description"), required=True,
        description=_('A short description of the file contents'))

    filecontent = Bytes(
        title=u"File", required=True,
        constraint=productrelease_file_size_constraint)

    signature = Bytes(
        title=u"GPG signature (recommended)", required=False,
        constraint=productrelease_signature_size_constraint)

    contenttype = Choice(title=_("File content type"), required=True,
                         vocabulary=UpstreamFileType,
                         default=UpstreamFileType.CODETARBALL)

class IProductReleaseSet(Interface):
    """Auxiliary class for ProductRelease handling."""

    def new(version, owner, productseries, codename=None, shortdesc=None,
            description=None, changelog=None):
        """Create a new ProductRelease"""

    def getBySeriesAndVersion(productseries, version, default=None):
        """Get a release by its version and productseries.

        If no release is found, default will be returned.
        """

    def getReleasesForSerieses(serieses):
        """Get all releases for the serieses."""

    def getFilesForReleases(releases):
        """Get all files for the releases."""
