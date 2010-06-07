# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Interfaces including and related to IDistroSeries."""

__metaclass__ = type

__all__ = [
    'IDistroSeries',
    'IDistroSeriesEditRestricted',
    'IDistroSeriesPublic',
    'IDistroSeriesSet',
    'NoSuchDistroSeries',
    ]

from zope.component import getUtility
from zope.interface import Interface, Attribute
from zope.schema import Bool, Datetime, Choice, Object, TextLine

from lazr.enum import DBEnumeratedType
from lazr.restful.declarations import (
    LAZR_WEBSERVICE_EXPORTED, export_as_webservice_entry,
    export_factory_operation, export_read_operation, exported,
    operation_parameters, operation_returns_collection_of,
    operation_returns_entry, rename_parameters_as, webservice_error)
from lazr.restful.fields import Reference, ReferenceChoice

from canonical.launchpad import _
from canonical.launchpad.fields import (
    ContentNameField, Description, PublicPersonChoice, Title,
    UniqueField)
from canonical.launchpad.interfaces.launchpad import IHasAppointedDriver
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.email import email_validator
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.validators.version import sane_version
from canonical.launchpad.webapp.interfaces import NameLookupFailed

from lp.blueprints.interfaces.specificationtarget import (
    ISpecificationGoal)
from lp.bugs.interfaces.bugtarget import (
    IBugTarget, IHasBugs, IHasOfficialBugTags)
from lp.registry.interfaces.milestone import IHasMilestones, IMilestone
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.series import ISeriesMixin, SeriesStatus
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.registry.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget)
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.translations.interfaces.languagepack import ILanguagePack
from lp.translations.interfaces.potemplate import IHasTranslationTemplates


class DistroSeriesNameField(ContentNameField):
    """A class to ensure `IDistroSeries` has unique names."""
    errormessage = _("%s is already in use by another series.")

    @property
    def _content_iface(self):
        """See `IField`."""
        return IDistroSeries

    def _getByName(self, name):
        """See `IField`."""
        try:
            if self._content_iface.providedBy(self.context):
                return self.context.distribution.getSeries(name)
            else:
                return self.context.getSeries(name)
        except NoSuchDistroSeries:
            # The name is available for the new series.
            return None


class DistroSeriesVersionField(UniqueField):
    """A class to ensure `IDistroSeries` has unique versions."""
    errormessage = _(
        "%s is already in use by another version in this distribution.")
    attribute = 'version'

    @property
    def _content_iface(self):
        return IDistroSeries

    @property
    def _distribution(self):
        if self._content_iface.providedBy(self.context):
            return self.context.distribution
        else:
            return self.context

    def _getByName(self, version):
        """Return the `IDistroSeries` for the specified distribution version.

        The distribution is the context's distribution (which may
        the context itself); A version is unique to a distribution.
        """
        found_series = None
        for series in getUtility(IDistroSeriesSet).findByVersion(version):
            if (series.distribution == self._distribution
                and series != self.context):
                # A version is unique to a distribution, but a distroseries
                # may edit itself.
                found_series = series
                break
        return found_series

    def _getByAttribute(self, version):
        """Return the content object with the given attribute."""
        return self._getByName(version)

    def _validate(self, version):
        """See `UniqueField`."""
        super(DistroSeriesVersionField, self)._validate(version)
        if not sane_version(version):
            raise LaunchpadValidationError(
                "%s is not a valid version" % version)
        # Avoid circular import hell.
        from lp.archivepublisher.debversion import Version, VersionError
        try:
            # XXX sinzui 2009-07-25 bug=404613: DistributionMirror and buildd
            # have stricter version rules than the schema. The version must
            # be a debversion.
            Version(version)
        except VersionError, error:
            raise LaunchpadValidationError(
                "'%s': %s" % (version, error[0]))


class IDistroSeriesEditRestricted(Interface):
    """IDistroSeries properties which require launchpad.Edit."""

    @rename_parameters_as(dateexpected='date_targeted')
    @export_factory_operation(
        IMilestone, ['name', 'dateexpected', 'summary', 'code_name'])
    def newMilestone(name, dateexpected=None, summary=None, code_name=None):
        """Create a new milestone for this DistroSeries."""


class IDistroSeriesPublic(
    ISeriesMixin, IHasAppointedDriver, IHasOwner, IBugTarget,
    ISpecificationGoal, IHasMilestones, IHasOfficialBugTags,
    IHasBuildRecords, IHasTranslationTemplates):
    """Public IDistroSeries properties."""

    id = Attribute("The distroseries's unique number.")
    name = exported(
        DistroSeriesNameField(
            title=_("Name"), required=True,
            description=_("The name of this series."),
            constraint=name_validator))
    displayname = exported(
        TextLine(
            title=_("Display name"), required=True,
            description=_("The series displayname.")))
    fullseriesname = exported(
        TextLine(
            title=_("Series full name"), required=False,
            description=_("The series full name, e.g. Ubuntu Warty")))
    title = exported(
        Title(
            title=_("Title"), required=True,
            description=_(
                "The title of this series. It should be distinctive "
                "and designed to look good at the top of a page.")))
    description = exported(
        Description(title=_("Description"), required=True,
            description=_("A detailed description of this series, with "
                          "information on the architectures covered, the "
                          "availability of security updates and any other "
                          "relevant information.")))
    version = exported(
        DistroSeriesVersionField(
            title=_("Version"), required=True,
            description=_("The version string for this series.")))
    distribution = exported(
        Reference(
            Interface, # Really IDistribution, see circular import fix below.
            title=_("Distribution"), required=True,
            description=_("The distribution for which this is a series.")))
    named_version = Attribute('The combined display name and version.')
    parent = Attribute('The structural parent of this series - the distro')
    components = Attribute("The series components.")
    upload_components = Attribute("The series components that can be "
                                  "uploaded to.")
    sections = Attribute("The series sections.")
    status = exported(
        Choice(
            title=_("Status"), required=True,
            vocabulary=SeriesStatus))
    datereleased = exported(
        Datetime(title=_("Date released")))
    parent_series = exported(
        ReferenceChoice(
            title=_("Parent series"),
            description=_("The series from which this one was branched."),
            required=True, schema=Interface, # Really IDistroSeries, see below
            vocabulary='DistroSeries'))
    owner = exported(
        PublicPersonChoice(title=_("Owner"), vocabulary='ValidOwner'))
    date_created = exported(
        Datetime(title=_("The date this series was registered.")))
    driver = exported(
        ReferenceChoice(
            title=_("Driver"),
            description=_(
                "The person or team responsible for decisions about features "
                "and bugs that will be targeted to this series of the "
                "distribution."),
            required=False, vocabulary='ValidPersonOrTeam', schema=IPerson))
    changeslist = exported(
        TextLine(
            title=_("E-mail changes to"), required=True,
            description=_("The mailing list or other e-mail address that "
                          "Launchpad should notify about new uploads."),
            constraint=email_validator))
    lucilleconfig = Attribute("Lucille Configuration Field")
    sourcecount = Attribute("Source Packages Counter")
    defer_translation_imports = Bool(
        title=_("Defer translation imports"),
        description=_("Suspends any translation imports for this series"),
        default=True,
        required=True,
        )
    binarycount = Attribute("Binary Packages Counter")

    architecturecount = Attribute("The number of architectures in this "
        "series.")
    nominatedarchindep = Attribute(
        "DistroArchSeries designed to build architecture-independent "
        "packages whithin this distroseries context.")
    messagecount = Attribute("The total number of translatable items in "
        "this series.")
    distroserieslanguages = Attribute("The set of dr-languages in this "
        "series.")

    hide_all_translations = Bool(
        title=u'Hide translations for this release', required=True,
        description=(
            u"You may hide all translation for this distribution series so"
             " that only Launchpad administrators will be able to see them."
             " For example, you should hide these translations while they are"
             " being imported from a previous series so that translators"
             " will not be confused by imports that are in progress."),
        default=True)

    language_pack_base = Choice(
        title=_('Language pack base'), required=False,
        description=_('''
            Language pack with the export of all translations
            available for this distribution series when it was generated. The
            subsequent update exports will be generated based on this one.
            '''), vocabulary='FilteredFullLanguagePack')

    language_pack_delta = Choice(
        title=_('Language pack update'), required=False,
        description=_('''
            Language pack with the export of all translation updates
            available for this distribution series since the language pack
            base was generated.
            '''), vocabulary='FilteredDeltaLanguagePack')

    language_pack_proposed = Choice(
        title=_('Proposed language pack update'), required=False,
        description=_('''
            Base or update language pack export that is being tested and
            proposed to be used as the new language pack base or
            language pack update for this distribution series.
            '''), vocabulary='FilteredLanguagePack')

    language_pack_full_export_requested = Bool(
        title=_('Request a full language pack export'), required=True,
        description=_('''
            Whether next language pack generation will be a full export. This
            information is useful when update packs are too big and want to
            merge all those changes in the base pack.
            '''))

    last_full_language_pack_exported = Object(
        title=_('Latest exported language pack with all translation files.'),
        required=False, readonly=True, schema=ILanguagePack)

    last_delta_language_pack_exported = Object(
        title=_(
            'Lastest exported language pack with updated translation files.'),
        required=False, readonly=True, schema=ILanguagePack)

    # related joins
    packagings = Attribute("All of the Packaging entries for this "
        "distroseries.")
    specifications = Attribute("The specifications targeted to this "
        "series.")

    language_packs = Attribute(
        "All language packs associated with this distribution series.")

    # other properties
    previous_series = Attribute("Previous series from the same "
        "distribution.")

    main_archive = exported(
        Reference(
            Interface, # Really IArchive, see below for circular import fix.
            title=_('Distribution Main Archive')))

    supported = exported(
        Bool(
            title=_("Supported"),
            description=_(
                "Whether or not this series is currently supported.")))

    def isUnstable():
        """Whether or not a distroseries is unstable.

        The distribution is "unstable" until it is released; after that
        point, all development on the Release pocket is stopped and
        development moves on to the other pockets.
        """

    def canUploadToPocket(pocket):
        """Decides whether or not allow uploads for a given pocket.

        Only allow uploads for RELEASE pocket in unreleased
        distroseries and the opposite, only allow uploads for
        non-RELEASE pockets in released distroseries.
        For instance, in edgy time :

                warty         -> DENY
                edgy          -> ALLOW
                warty-updates -> ALLOW
                edgy-security -> DENY

        Note that FROZEN is not considered either 'stable' or 'unstable'
        state.  Uploads to a FROZEN distroseries will end up in the
        UNAPPROVED queue.

        Return True if the upload is allowed and False if denied.
        """

    def getLatestUploads():
        """Return the latest five source uploads for this DistroSeries.

        It returns a list containing up to five elements as
        IDistroSeriesSourcePackageRelease instances
        """

    # DistroArchSeries lookup properties/methods.
    architectures = Attribute("All architectures in this series.")

    virtualized_architectures = Attribute(
        "All architectures in this series where PPA is supported.")

    enabled_architectures = Attribute(
        "All architectures in this series with available chroot tarball.")

    def __getitem__(archtag):
        """Return the distroarchseries for this distroseries with the
        given architecturetag.
        """

    def getDistroArchSeriesByProcessor(processor):
        """Return the distroarchseries for this distroseries with the
        given architecturetag from a `IProcessor`.

        :param processor: An `IProcessor`
        :return: An `IDistroArchSeries` or None when none was found.
        """

    @operation_parameters(
        archtag=TextLine(
            title=_("The architecture tag"), required=True))
    @operation_returns_entry(Interface)
    @export_read_operation()
    def getDistroArchSeries(archtag):
        """Return the distroarchseries for this distroseries with the
        given architecturetag.
        """
    # End of DistroArchSeries lookup methods.

    def updateStatistics(ztm):
        """Update all the Rosetta stats for this distro series."""

    def updatePackageCount():
        """Update the binary and source package counts for this distro
        series."""

    @operation_parameters(
        name=TextLine(
            title=_("The name of the source package"), required=True))
    @operation_returns_entry(ISourcePackage)
    @export_read_operation()
    def getSourcePackage(name):
        """Return a source package in this distro series by name.

        The name given may be a string or an ISourcePackageName-providing
        object. The source package may not be published in the distro series.
        """

    def getTranslatableSourcePackages():
        """Return a list of Source packages in this distribution series
        that can be translated.
        """

    def getPrioritizedUnlinkedSourcePackages():
        """Return a list of package summaries that need packaging links.

        A summary is a dict of package (`ISourcePackage`), total_bugs,
        and total_messages (translatable messages).
        """

    def getPrioritizedlPackagings():
        """Return a list of packagings that need more upstream information."""

    def getMostRecentlyLinkedPackagings():
        """Return a list of packagings that are the most recently linked.

        At most five packages are returned of those most recently linked to an
        upstream.
        """

    @operation_parameters(
        created_since_date=Datetime(
            title=_("Created Since Timestamp"),
            description=_(
                "Return items that are more recent than this timestamp."),
            required=False),
        status=Choice(
            # Really PackageUploadCustomFormat, patched in
            # _schema_circular_imports.py
            vocabulary=DBEnumeratedType,
            title=_("Package Upload Status"),
            description=_("Return only items that have this status."),
            required=False),
        archive=Reference(
            # Really IArchive, patched in _schema_circular_imports.py
            schema=Interface,
            title=_("Archive"),
            description=_("Return only items for this archive."),
            required=False),
        pocket=Choice(
            # Really PackagePublishingPocket, patched in
            # _schema_circular_imports.py
            vocabulary=DBEnumeratedType,
            title=_("Pocket"),
            description=_("Return only items targeted to this pocket"),
            required=False),
        custom_type=Choice(
            # Really PackageUploadCustomFormat, patched in
            # _schema_circular_imports.py
            vocabulary=DBEnumeratedType,
            title=_("Custom Type"),
            description=_("Return only items with custom files of this "
                          "type."),
            required=False),
        )
    # Really IPackageUpload, patched in _schema_circular_imports.py
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    def getPackageUploads(created_since_date, status, archive, pocket,
                          custom_type):
        """Get package upload records for this distribution series.

        :param created_since_date: If specified, only returns items uploaded
            since the timestamp supplied.
        :param status: Filter results by this `PackageUploadStatus`
        :param archive: Filter results for this `IArchive`
        :param pocket: Filter results by this `PackagePublishingPocket`
        :param custom_type: Filter results by this `PackageUploadCustomFormat`
        :return: A result set containing `IPackageUpload`
        """

    def getUnlinkedTranslatableSourcePackages():
        """Return a list of source packages that can be translated in
        this distribution series but which lack Packaging links.
        """

    def getBinaryPackage(name):
        """Return a DistroSeriesBinaryPackage for this name.

        The name given may be an IBinaryPackageName or a string.  The
        binary package may not be published in the distro series.
        """

    def getSourcePackageRelease(sourcepackagerelease):
        """Return a IDistroSeriesSourcePackageRelease

        sourcepackagerelease is an ISourcePackageRelease.
        """

    def getCurrentSourceReleases(source_package_names):
        """Get the current release of a list of source packages.

        :param source_package_names: a list of `ISourcePackageName`
            instances.

        :return: a dict where the key is a `ISourcePackage`
            and the value is a `IDistroSeriesSourcePackageRelease`.
        """

    def getPublishedReleases(sourcepackage_or_name, pocket=None, version=None,
                             include_pending=False, exclude_pocket=None,
                             archive=None):
        """Return the SourcePackagePublishingHistory(s)

        Given a ISourcePackageName or name.

        If pocket is not specified, we look in all pockets.

        If version is not specified, return packages with any version.

        if exclude_pocket is specified we exclude results matching that pocket.

        If 'include_pending' is True, we return also the pending publication
        records, those packages that will get published in the next publisher
        run (it's only useful when we need to know if a given package is
        known during a publisher run, mostly in pre-upload checks)

        If 'archive' is not specified consider publication in the main_archive,
        otherwise respect the given value.
        """

    def getAllPublishedSources():
        """Return all currently published sources for the distroseries.

        Return publications in the main archives only.
        """

    def getAllPublishedBinaries():
        """Return all currently published binaries for the distroseries.

        Return publications in the main archives only.
        """

    def getSourcesPublishedForAllArchives():
        """Return all sourcepackages published across all the archives.

        It's only used in the buildmaster/master.py context for calculating
        the publication that are still missing build records.

        It will consider all publishing records in PENDING or PUBLISHED status
        as part of the 'build-unpublished-source' specification.

        For 'main_archive' candidates it will automatically exclude RELEASE
        pocket records of released distroseries (ensuring that we won't waste
        time with records that can't be accepted).

        Return a SelectResult of SourcePackagePublishingHistory.
        """

    def publishedBinaryPackages(component=None):
        """Given an optional component name, return a list of the binary
        packages that are currently published in this distroseries in the
        given component, or in any component if no component name was given.
        """

    def getDistroSeriesLanguage(language):
        """Return the DistroSeriesLanguage for this distroseries and the
        given language, or None if there's no DistroSeriesLanguage for this
        distribution and the given language.
        """

    def getDistroSeriesLanguageOrDummy(language):
        """Return the DistroSeriesLanguage for this distroseries and the
        given language, or a DummyDistroSeriesLanguage.
        """

    def createUploadedSourcePackageRelease(
        sourcepackagename, version, maintainer, builddepends,
        builddependsindep, architecturehintlist, component, creator, urgency,
        changelog, changelog_entry, dsc, dscsigningkey, section,
        dsc_maintainer_rfc822, dsc_standards_version, dsc_format,
        dsc_binaries, archive, copyright, build_conflicts,
        build_conflicts_indep, dateuploaded=None,
        source_package_recipe_build=None):
        """Create an uploads `SourcePackageRelease`.

        Set this distroseries set to be the uploadeddistroseries.

        All arguments are mandatory, they are extracted/built when
        processing and uploaded source package:

         :param dateuploaded: timestamp, if not provided will be UTC_NOW
         :param sourcepackagename: `ISourcePackageName`
         :param version: string, a debian valid version
         :param maintainer: IPerson designed as package maintainer
         :param creator: IPerson, package uploader
         :param component: IComponent
         :param section: ISection
         :param urgency: dbschema.SourcePackageUrgency
         :param dscsigningkey: IGPGKey used to sign the DSC file
         :param dsc: string, original content of the dsc file
         :param copyright: string, the original debian/copyright content
         :param changelog: LFA ID of the debian/changelog file in librarian
         :param changelog_entry: string, changelog extracted from the
                                 changesfile
         :param architecturehintlist: string, DSC architectures
         :param builddepends: string, DSC build dependencies
         :param builddependsindep: string, DSC architecture independent build
                                   dependencies.
         :param build_conflicts: string, DSC Build-Conflicts content
         :param build_conflicts_indep: string, DSC Build-Conflicts-Indep
                                       content
         :param dsc_maintainer_rfc822: string, DSC maintainer field
         :param dsc_standards_version: string, DSC standards version field
         :param dsc_format: string, DSC format version field
         :param dsc_binaries:  string, DSC binaries field
         :param archive: IArchive to where the upload was targeted
         :param dateuploaded: optional datetime, if omitted assumed nowUTC
         :param source_package_recipe_build: optional SourcePackageRecipeBuild
         :return: the just creates `SourcePackageRelease`
        """

    def getComponentByName(name):
        """Get the named component.

        Raise NotFoundError if the component is not in the permitted component
        list for this distroseries.
        """

    def getSectionByName(name):
        """Get the named section.

        Raise NotFoundError if the section is not in the permitted section
        list for this distroseries.
        """

    def addSection(section):
        """SQLObject provided method to fill a related join key section."""

    def getBinaryPackagePublishing(
        name=None, version=None, archtag=None, sourcename=None, orderBy=None,
        pocket=None, component=None, archive=None):
        """Get BinaryPackagePublishings in a DistroSeries.

        Can optionally restrict the results by name, version,
        architecturetag, pocket and/or component.

        If sourcename is passed, only packages that are built from
        source packages by that name will be returned.
        If archive is passed, restricted the results to the given archive,
        if it is suppressed the results will be restricted to the distribtion
        'main_archive'.
        """

    def getSourcePackagePublishing(status, pocket, component=None,
                                   archive=None):
        """Return a selectResult of ISourcePackagePublishingHistory.

        According status and pocket.
        If archive is passed, restricted the results to the given archive,
        if it is suppressed the results will be restricted to the distribtion
        'main_archive'.
        """

    def getBinaryPackageCaches(archive=None):
        """All of the cached binary package records for this distroseries.

        If 'archive' is not given it will return all caches stored for the
        distroseries main archives (PRIMARY and PARTNER).
        """

    def removeOldCacheItems(archive, log):
        """Delete any records that are no longer applicable.

        Consider all binarypackages marked as REMOVED.

        Also purges all existing cache records for disabled archives.

        :param archive: target `IArchive`.
        :param log: the context logger object able to print DEBUG level
            messages.
        """

    def updateCompletePackageCache(archive, log, ztm, commit_chunk=500):
        """Update the binary package cache

        Consider all binary package names published in this distro series
        and entirely skips updates for disabled archives

        :param archive: target `IArchive`;
        :param log: logger object for printing debug level information;
        :param ztm:  transaction used for partial commits, every chunk of
            'commit_chunk' updates is committed;
        :param commit_chunk: number of updates before commit, defaults to 500.

        :return the number of packages updated.
        """

    def updatePackageCache(binarypackagename, archive, log):
        """Update the package cache for a given IBinaryPackageName

        'log' is required, it should be a logger object able to print
        DEBUG level messages.
        'ztm' is the current trasaction manager used for partial commits
        (in full batches of 100 elements)
        """

    def searchPackages(text):
        """Search through the packge cache for this distroseries and return
        DistroSeriesBinaryPackage objects that match the given text.
        """

    def createQueueEntry(pocket, changesfilename, changesfilecontent,
                         archive, signingkey=None):
        """Create a queue item attached to this distroseries.

        Create a new records respecting the given pocket and archive.

        The default state is NEW, sorted sqlobject declaration, any
        modification should be performed via Queue state-machine.

        The changesfile argument should be the text of the .changes for this
        upload. The contents of this may be used later.

        'signingkey' is the IGPGKey used to sign the changesfile or None if
        the changesfile is unsigned.
        """

    def newArch(architecturetag, processorfamily, official, owner,
                supports_virtualized=False):
        """Create a new port or DistroArchSeries for this DistroSeries."""

    def initialiseFromParent():
        """Copy in all of the parent distroseries's configuration. This
        includes all configuration for distroseries and distroarchseries
        publishing and all publishing records for sources and binaries.

        Preconditions:
          The distroseries must have been set up with its distroarchseriess
          as needed. It should have its nominated arch-indep set up along
          with all other basic requirements for the structure of the
          distroseries. This distroseries and all its distroarchseriess
          must have empty publishing sets. Section and component selections
          must be empty.

        Outcome:
          The publishing structure will be copied from the parent. All
          PUBLISHED and PENDING packages in the parent will be created in
          this distroseries and its distroarchseriess. The lucille config
          will be copied in, all component and section selections will be
          duplicated as will any permission-related structures.

        Note:
          This method will assert all of its preconditions where possible.
          After this is run, you still need to construct chroots for building,
          you need to add anything missing wrt. ports etc. This method is
          only meant to give you a basic copy of a parent series in order
          to assist you in preparing a new series of a distribution or
          in the initialisation of a derivative.
        """

    def copyTranslationsFromParent(ztm):
        """Copy any translation done in parent that we lack.

        If there is another translation already added to this one, we ignore
        the one from parent.

        The supplied transaction manager will be used for intermediate
        commits to break up large copying jobs into palatable smaller
        chunks.

        This method starts and commits transactions, so don't rely on `self`
        or any other database object remaining valid across this call!
        """

    def getPOFileContributorsByLanguage(language):
        """People who translated strings to the given language.

        The people that translated only IPOTemplate objects that are not
        current will not appear in the returned list.
        """

    def getSuite(pocket):
        """Return the suite for this distro series and the given pocket.

        :param pocket: A `DBItem` of `PackagePublishingPocket`.
        :return: A string.
        """

    def isSourcePackageFormatPermitted(format):
        """Check if the specified source format is allowed in this series.

        :param format: The SourcePackageFormat to check.
        """


class IDistroSeries(IDistroSeriesEditRestricted, IDistroSeriesPublic,
                    IStructuralSubscriptionTarget):
    """A series of an operating system distribution."""
    export_as_webservice_entry()


# We assign the schema for an `IHasBugs` method argument here
# in order to avoid circular dependencies.
IHasBugs['searchTasks'].queryTaggedValue(LAZR_WEBSERVICE_EXPORTED)[
    'params']['nominated_for'].schema = IDistroSeries


class IDistroSeriesSet(Interface):
    """The set of distro seriess."""

    def get(distroseriesid):
        """Retrieve the distro series with the given distroseriesid."""

    def translatables():
        """Return a set of distroseriess that can be translated in
        rosetta."""

    def findByName(name):
        """Find a DistroSeries by name.

        Returns a list of matching distributions, which may be empty.
        """

    def queryByName(distribution, name):
        """Query a DistroSeries by name.

        :distribution: An IDistribution.
        :name: A string.

        Returns the matching DistroSeries, or None if not found.
        """

    def findByVersion(version):
        """Find a DistroSeries by version.

        Returns a list of matching distributions, which may be empty.
        """

    def fromSuite(distribution, suite):
        """Return the distroseries and pocket for 'suite' of 'distribution'.

        :param distribution: An `IDistribution`.
        :param suite: A string that forms the name of a suite.
        :return: (`IDistroSeries`, `DBItem`) where the item is from
            `PackagePublishingPocket`.
        """

    def search(distribution=None, released=None, orderBy=None):
        """Search the set of distro seriess.

        released == True will filter results to only include
        IDistroSeries with status CURRENT or SUPPORTED.

        released == False will filter results to only include
        IDistroSeriess with status EXPERIMENTAL, DEVELOPMENT,
        FROZEN.

        released == None will do no filtering on status.
        """


class NoSuchDistroSeries(NameLookupFailed):
    """Raised when we try to find a DistroSeries that doesn't exist."""
    webservice_error(400) #Bad request.
    _message_prefix = "No such distribution series"


# Monkey patch for circular import avoidance done in
# _schema_circular_imports.py
