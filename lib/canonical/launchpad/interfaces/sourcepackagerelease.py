# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Source package release interfaces."""

__metaclass__ = type

__all__ = ['ISourcePackageRelease']

from zope.schema import TextLine
from zope.interface import Interface, Attribute

from canonical.launchpad import _
from canonical.launchpad.validators.version import valid_debian_version

from canonical.lp.dbschema import (
    BuildStatus, PackagePublishingPocket)

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
    changelog = Attribute("Source Package Change Log")
    builddepends = Attribute(
        "A comma-separated list of packages on which this package "
        "depends to build")
    builddependsindep = Attribute(
        "Same as builddepends, but the list is of arch-independent packages")
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
    builds = Attribute("Builds for this sourcepackagerelease")
    files = Attribute("IBinaryPackageFile entries for this "
        "sourcepackagerelease")
    sourcepackagename = Attribute("SourcePackageName table reference")
    uploaddistroseries = Attribute("The distroseries in which this package "
        "was first uploaded in Launchpad")
    manifest = Attribute("Manifest of branches imported for this release")
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
    needs_building = Attribute("A boolean that indicates whether this package "
        "still needs to be built (on any architecture)")

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
    upload_archive = Attribute(
        "The archive for which this package was first uploaded in Launchpad")


    # XXX: What do the following methods and attributes do?
    #      These were missing from the interfaces, but being used
    #      in application code.
    #      -- Steve Alexander, Fri Dec 10 14:28:41 UTC 2004
    architecturesReleased = Attribute("XXX")

    def addFile(file):
        """Add the provided library file alias (file) to the list of files
        in this package.
        """

    def createBuild(distroarchseries, pocket, archive, processor=None,
                    status=BuildStatus.NEEDSBUILD):
        """Create a build for a given distroarchseries/pocket/archive

        If the processor isn't given, guess it from the distroarchseries.
        If the status isn't given, use NEEDSBUILD.

        Return the just created IBuild.
        """

    def getBuildByArch(distroarchseries, archive):
        """Return build for the given distroarchseries/archive.

        This will look first for published builds in the given
        distroarchseries. It uses the publishing tables to return a build,
        even if the build is from another distroarchseries, so long as the
        binaries are published in the distroarchseries given.

        If no published build is located, it will then look for a build in
        any state registered directly against this distroarchseries.

        Return None if not found.
        """

    def override(component=None, section=None, urgency=None):
        """Uniform method to override sourcepackagerelease attribute.

        All arguments are optional and can be set individually. A non-passed
        argument remains untouched.
        """

    def countOpenBugsInUploadedDistro(user):
        """Return the number of open bugs targeted to the sourcepackagename
        and distribution to which this release was uploaded.
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
