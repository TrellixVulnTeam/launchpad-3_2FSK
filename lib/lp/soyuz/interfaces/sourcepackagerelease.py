# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Source package release interfaces."""

__metaclass__ = type

__all__ = [
    'ISourcePackageRelease',
    'PackageDiffAlreadyRequestedError',
    ]


from lazr.restful.fields import Reference
from zope.schema import TextLine
from zope.interface import Interface, Attribute

from canonical.launchpad import _


class ISourcePackageRelease(Interface):
    """A source package release, e.g. apache-utils 2.0.48-3"""

    id = Attribute("SourcePackageRelease identifier")
    creator = Attribute("Person that created this release")
    maintainer = Attribute("The person in general responsible for this "
        "release")
    version = Attribute("A version string")
    dateuploaded = Attribute("Date of Upload")
    urgency = Attribute("Source Package Urgency")
    dscsigningkey = Attribute("DSC Signing Key")
    component = Attribute("Source Package Component")
    format = Attribute("The Source Package Format")
    changelog_entry = Attribute("Source Package Change Log Entry")
    change_summary = Attribute(
        "The message on the latest change in this release. This is usually "
        "a snippet from the changelog")
    builddepends = TextLine(
        title=_("DSC build depends"),
        description=_("A comma-separated list of packages on which this "
                      "package depends to build"),
        required=False)
    builddependsindep = TextLine(
        title=_("DSC build depends"),
        description=_("Same as builddepends, but the list is of "
                      "arch-independent packages"),
        required=False)
    build_conflicts = TextLine(
        title=_("DSC build conflicts"),
        description=_("Binaries that will conflict when building this "
                      "source."),
        required=False)
    build_conflicts_indep = TextLine(
        title=_("DSC arch-independent build conflicts"),
        description=_("Same as build-conflicts but only lists "
                      "arch-independent binaries."),
        required=False)
    architecturehintlist = TextLine(
        title=_("Architecture Hint List"),
        description=_(
        "Architectures where this packages is supposed to be built"),
        required=True)
    dsc_maintainer_rfc822 = TextLine(
        title=_("DSC maintainers identification in RFC-822"),
        description=_(
        "Original maintainer line contained in the DSC file."),
        required=True)
    dsc_standards_version = TextLine(
        title=_("DSC Standards version"),
        description=_(
        "DSC standards version used to build this source."),
        required=True)
    dsc_format = TextLine(
        title=_("DSC format"),
        description=_(
        "DSC file format used to upload this source"),
        required=True)
    dsc_binaries = TextLine(
        title=_("DSC proposed binaries"),
        description=_(
        "Binaries claimed to be generated by this source."),
        required=True)
    dsc = Attribute("The DSC file for this SourcePackageRelease")
    copyright = Attribute(
        "Copyright information for this SourcePackageRelease, if available.")
    section = Attribute("Section this Source Package Release belongs to")
    builds = Attribute("Builds for this sourcepackagerelease excluding PPA "
        "archives.")
    files = Attribute("IBinaryPackageFile entries for this "
        "sourcepackagerelease")
    sourcepackagename = Attribute("SourcePackageName table reference")
    upload_distroseries = Attribute("The distroseries in which this package "
        "was first uploaded in Launchpad")
    publishings = Attribute("MultipleJoin on SourcepackagePublishing")



    # read-only properties
    name = Attribute('The sourcepackagename for this release, as text')
    title = Attribute('The title of this sourcepackagerelease')
    age = Attribute('Time passed since the source package release '
                    'is present in Launchpad')
    latest_build = Attribute("The latest build of this source package "
        "release, or None")
    failed_builds = Attribute("A (potentially empty) list of build "
        "failures that happened for this source package " "release, or None")
    needs_building = Attribute(
        "A boolean that indicates whether this package still needs to be "
        "built (on any architecture)")

    sourcepackage = Attribute(
        "The magic SourcePackage for the sourcepackagename and "
        "distroseries of this object.")
    distrosourcepackage = Attribute(
        "The magic DistroSourcePackage for the sourcepackagename and "
        "distribution of this object.")
    productrelease = Attribute("The best guess we have as to the Launchpad "
        "ProductRelease associated with this SourcePackageRelease.")

    current_publishings = Attribute("A list of the current places where "
        "this source package is published, in the form of a list of "
        "DistroSeriesSourcePackageReleases.")
    published_archives = Attribute("A set of all the archives that this "
        "source package is published in.")
    upload_archive = Attribute(
        "The archive for which this package was first uploaded in Launchpad")

    upload_changesfile = Attribute(
        "The `LibraryFileAlias` object containing the changes file which "
        "was originally uploaded with this source package release. It's "
        "'None' if it is a source imported by Gina.")

    package_upload = Attribute(
        "The `PackageUpload` record corresponding to original upload of "
        "this source package release. It's 'None' if it is a source "
        "imported by Gina.")

    # Really ISourcePackageRecipeBuild -- see _schema_circular_imports.
    source_package_recipe_build = Reference(
        schema=Interface,
        description=_("The `SourcePackageRecipeBuild` which produced this "
            "source package release, or None if it was created from a "
            "traditional upload."),
        title=_("Source package recipe build"),
        required=False, readonly=True)

    def addFile(file):
        """Add the provided library file alias (file) to the list of files
        in this package.
        """

    def createBuild(distroarchseries, pocket, archive, processor=None,
                    status=None):
        """Create a build for a given distroarchseries/pocket/archive

        If the processor isn't given, guess it from the distroarchseries.
        If the status isn't given, use NEEDSBUILD.

        Return the just created IBuild.
        """

    def getBuildByArch(distroarchseries, archive):
        """Return build for the given distroarchseries/archive.

        It looks for a build in any state registered *directly* for the
        given distroarchseries and archive.

        Returns None if a suitable build could not be found.
        """

    def override(component=None, section=None, urgency=None):
        """Uniform method to override sourcepackagerelease attribute.

        All arguments are optional and can be set individually. A non-passed
        argument remains untouched.
        """

    def attachTranslationFiles(tarball_alias, is_published, importer=None):
        """Attach a tarball with translations to be imported into Rosetta.

        :tarball_alias: is a Librarian alias that references to a tarball with
            translations.
        :is_published: indicates if the imported files are already published by
            upstream.
        :importer: is the person that did the import.

        raise DownloadFailed if we are not able to fetch the file from
            :tarball_alias:.
        """

    package_diffs = Attribute(
        "All `IPackageDiff` generated from this context.")

    def getDiffTo(to_sourcepackagerelease):
        """Return an `IPackageDiff` to a given `ISourcePackageRelease`.

        Return None if it was not yet requested.
        """

    def requestDiffTo(requester, to_sourcepackagerelease):
        """Request a package diff from the context source to a given source.

        :param: requester: it's the diff requester, any valid `IPerson`;
        :param: to_source: it's the `ISourcePackageRelease` to diff against.
        :raise `PackageDiffAlreadyRequested`: when there is already a
            `PackageDiff` record matching the request being made.

        :return: the corresponding `IPackageDiff` record.
        """

    def getPackageSize():
        """Get the size total (in KB) of files comprising this package.

        Please note: empty packages (i.e. ones with no files or with
        files that are all empty) have a size of zero.

        :return: total size (in KB) of this package
        """


class PackageDiffAlreadyRequestedError(Exception):
    """Raised when an `IPackageDiff` request already exists."""
