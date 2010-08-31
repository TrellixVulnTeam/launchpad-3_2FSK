# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212
"""Database classes for implementing distribution items."""

__metaclass__ = type
__all__ = [
    'Distribution',
    'DistributionSet',
    ]


from sqlobject import (
    BoolCol,
    ForeignKey,
    SQLObjectNotFound,
    StringCol,
    )
from sqlobject.sqlbuilder import SQLConstant
from storm.locals import (
    Desc,
    In,
    Int,
    Join,
    Or,
    SQL,
    )
from storm.store import Store
from zope.component import getUtility
from zope.interface import (
    alsoProvides,
    implements,
    )

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    cursor,
    quote,
    quote_like,
    SQLBase,
    sqlvalues,
    )
from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet,
    )
from canonical.launchpad.components.storm_operators import (
    FTQ,
    Match,
    RANK,
    )
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.launchpad import (
    IHasIcon,
    IHasLogo,
    IHasMugshot,
    ILaunchpadCelebrities,
    )
from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.launchpad.validators.name import (
    sanitize_name,
    valid_name,
    )
from canonical.launchpad.webapp.url import urlparse
from lp.answers.interfaces.faqtarget import IFAQTarget
from lp.answers.interfaces.questioncollection import (
    QUESTION_STATUS_DEFAULT_SEARCH,
    )
from lp.answers.interfaces.questiontarget import IQuestionTarget
from lp.answers.model.faq import (
    FAQ,
    FAQSearch,
    )
from lp.answers.model.question import (
    QuestionTargetMixin,
    QuestionTargetSearch,
    )
from lp.app.enums import ServiceUsage
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import (
    ILaunchpadUsage,
    IServiceUsage,
    )
from lp.archivepublisher.debversion import Version
from lp.blueprints.interfaces.specification import (
    SpecificationDefinitionStatus,
    SpecificationFilter,
    SpecificationImplementationStatus,
    SpecificationSort,
    )
from lp.blueprints.model.specification import (
    HasSpecificationsMixin,
    Specification,
    )
from lp.blueprints.model.sprint import HasSprintsMixin
from lp.bugs.interfaces.bugsupervisor import IHasBugSupervisor
from lp.bugs.interfaces.bugtarget import IHasBugHeat
from lp.bugs.interfaces.bugtask import (
    BugTaskStatus,
    UNRESOLVED_BUGTASK_STATUSES,
    )
from lp.bugs.model.bug import (
    BugSet,
    get_bug_tags,
    get_bug_tags_open_count,
    )
from lp.bugs.model.bugtarget import (
    BugTargetBase,
    HasBugHeatMixin,
    OfficialBugTagTargetMixin,
    )
from lp.bugs.model.bugtask import BugTask
from lp.registry.interfaces.distribution import (
    IBaseDistribution,
    IDerivativeDistribution,
    IDistribution,
    IDistributionSet,
    )
from lp.registry.interfaces.distributionmirror import (
    IDistributionMirror,
    MirrorContent,
    MirrorStatus,
    )
from lp.registry.interfaces.distroseries import NoSuchDistroSeries
from lp.registry.interfaces.packaging import PackagingType
from lp.registry.interfaces.person import (
    validate_person,
    validate_public_person,
    )
from lp.registry.interfaces.pillar import IPillarNameSet
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackagename import ISourcePackageName
from lp.registry.model.announcement import MakesAnnouncements
from lp.registry.model.distributionmirror import DistributionMirror
from lp.registry.model.distributionsourcepackage import (
    DistributionSourcePackage,
    )
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.karma import KarmaContextMixin
from lp.registry.model.mentoringoffer import MentoringOffer
from lp.registry.model.milestone import (
    HasMilestonesMixin,
    Milestone,
    )
from lp.registry.model.pillar import HasAliasMixin
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.registry.model.structuralsubscription import (
    StructuralSubscriptionTargetMixin,
    )
from lp.services.propertycache import (
    cachedproperty,
    IPropertyCache,
    )
from lp.soyuz.enums import (
    ArchivePurpose,
    ArchiveStatus,
    PackagePublishingStatus,
    PackageUploadStatus,
    )
from lp.soyuz.interfaces.archive import (
    IArchiveSet,
    MAIN_ARCHIVE_PURPOSES,
    )
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.distributionsourcepackagecache import (
    DistributionSourcePackageCache,
    )
from lp.soyuz.model.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease,
    )
from lp.soyuz.model.distroarchseries import (
    DistroArchSeries,
    DistroArchSeriesSet,
    )
from lp.soyuz.model.distroseriespackagecache import DistroSeriesPackageCache
from lp.soyuz.model.publishing import (
    BinaryPackageFilePublishing,
    BinaryPackagePublishingHistory,
    SourcePackageFilePublishing,
    SourcePackagePublishingHistory,
    )
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease
from lp.translations.interfaces.translationgroup import TranslationPermission
from lp.translations.model.translationimportqueue import (
    HasTranslationImportsMixin,
    )


class Distribution(SQLBase, BugTargetBase, MakesAnnouncements,
                   HasSpecificationsMixin, HasSprintsMixin, HasAliasMixin,
                   HasTranslationImportsMixin, KarmaContextMixin,
                   OfficialBugTagTargetMixin, QuestionTargetMixin,
                   StructuralSubscriptionTargetMixin, HasMilestonesMixin,
                   HasBugHeatMixin):
    """A distribution of an operating system, e.g. Debian GNU/Linux."""
    implements(
        IDistribution, IFAQTarget, IHasBugHeat, IHasBugSupervisor,
        IHasBuildRecords, IHasIcon, IHasLogo, IHasMugshot, ILaunchpadUsage,
        IQuestionTarget, IServiceUsage)

    _table = 'Distribution'
    _defaultOrder = 'name'

    name = StringCol(notNull=True, alternateID=True, unique=True)
    displayname = StringCol(notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    description = StringCol(notNull=True)
    homepage_content = StringCol(default=None)
    icon = ForeignKey(
        dbName='icon', foreignKey='LibraryFileAlias', default=None)
    logo = ForeignKey(
        dbName='logo', foreignKey='LibraryFileAlias', default=None)
    mugshot = ForeignKey(
        dbName='mugshot', foreignKey='LibraryFileAlias', default=None)
    domainname = StringCol(notNull=True)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    bug_supervisor = ForeignKey(
        dbName='bug_supervisor', foreignKey='Person',
        storm_validator=validate_person,
        notNull=False,
        default=None)
    bug_reporting_guidelines = StringCol(default=None)
    bug_reported_acknowledgement = StringCol(default=None)
    security_contact = ForeignKey(
        dbName='security_contact', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False,
        default=None)
    driver = ForeignKey(
        dbName="driver", foreignKey="Person",
        storm_validator=validate_public_person, notNull=False, default=None)
    members = ForeignKey(
        dbName='members', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    mirror_admin = ForeignKey(
        dbName='mirror_admin', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    translationgroup = ForeignKey(
        dbName='translationgroup', foreignKey='TranslationGroup',
        notNull=False, default=None)
    translationpermission = EnumCol(
        dbName='translationpermission', notNull=True,
        schema=TranslationPermission, default=TranslationPermission.OPEN)
    lucilleconfig = StringCol(
        dbName='lucilleconfig', notNull=False, default=None)
    active = True # Required by IPillar interface.
    max_bug_heat = Int()

    def __repr__(self):
        displayname = self.displayname.encode('ASCII', 'backslashreplace')
        return "<%s '%s' (%s)>" % (
            self.__class__.__name__, displayname, self.name)

    def _init(self, *args, **kw):
        """Initialize an `IBaseDistribution` or `IDerivativeDistribution`."""
        SQLBase._init(self, *args, **kw)
        # Add a marker interface to set permissions for this kind
        # of distribution.
        if self == getUtility(ILaunchpadCelebrities).ubuntu:
            alsoProvides(self, IBaseDistribution)
        else:
            alsoProvides(self, IDerivativeDistribution)

    @property
    def uploaders(self):
        """See `IDistribution`."""
        # Get all the distribution archives and find out the uploaders
        # for each.
        distro_uploaders = []
        permission_set = getUtility(IArchivePermissionSet)
        for archive in self.all_distro_archives:
            uploaders = permission_set.uploadersForComponent(archive)
            distro_uploaders.extend(uploaders)

        return distro_uploaders

    official_answers = BoolCol(dbName='official_answers', notNull=True,
        default=False)
    official_blueprints = BoolCol(dbName='official_blueprints', notNull=True,
        default=False)
    official_malone = BoolCol(dbName='official_malone', notNull=True,
        default=False)
    official_rosetta = BoolCol(dbName='official_rosetta', notNull=True,
        default=False)

    @property
    def official_codehosting(self):
        # XXX: Aaron Bentley 2008-01-22
        # At this stage, we can't directly associate branches with source
        # packages or anything else resulting in a distribution, so saying
        # that a distribution supports codehosting at this stage makes
        # absolutely no sense at all.
        return False

    @property
    def official_anything(self):
        return True in (self.official_malone, self.official_rosetta,
                        self.official_blueprints, self.official_answers)

    _answers_usage = EnumCol(
        dbName="answers_usage", notNull=True,
        schema=ServiceUsage,
        default=ServiceUsage.UNKNOWN)

    def _get_answers_usage(self):
        if self._answers_usage != ServiceUsage.UNKNOWN:
            # If someone has set something with the enum, use it.
            return self._answers_usage
        elif self.official_answers:
            return ServiceUsage.LAUNCHPAD
        return self._answers_usage

    def _set_answers_usage(self, val):
        self._answers_usage = val
        if val == ServiceUsage.LAUNCHPAD:
            self.official_answers = True
        else:
            self.official_answers = False

    answers_usage = property(
        _get_answers_usage,
        _set_answers_usage,
        doc="Indicates if the product uses the answers service.")

    _blueprints_usage = EnumCol(
        dbName="blueprints_usage", notNull=True,
        schema=ServiceUsage,
        default=ServiceUsage.UNKNOWN)

    def _get_blueprints_usage(self):
        if self._blueprints_usage != ServiceUsage.UNKNOWN:
            # If someone has set something with the enum, use it.
            return self._blueprints_usage
        elif self.official_blueprints:
            return ServiceUsage.LAUNCHPAD
        return self._blueprints_usage

    def _set_blueprints_usage(self, val):
        self._blueprints_usage = val
        if val == ServiceUsage.LAUNCHPAD:
            self.official_blueprints = True
        else:
            self.official_blueprints = False

    blueprints_usage = property(
        _get_blueprints_usage,
        _set_blueprints_usage,
        doc="Indicates if the product uses the blueprints service.")

    _translations_usage = EnumCol(
        dbName="translations_usage", notNull=True,
        schema=ServiceUsage,
        default=ServiceUsage.UNKNOWN)

    def _get_translations_usage(self):
        if self._translations_usage != ServiceUsage.UNKNOWN:
            # If someone has set something with the enum, use it.
            return self._translations_usage
        elif self.official_rosetta:
            return ServiceUsage.LAUNCHPAD
        return self._translations_usage

    def _set_translations_usage(self, val):
        self._translations_usage = val
        if val == ServiceUsage.LAUNCHPAD:
            self.official_rosetta = True
        else:
            self.official_rosetta = False

    translations_usage = property(
        _get_translations_usage,
        _set_translations_usage,
        doc="Indicates if the product uses the translations service.")

    @property
    def codehosting_usage(self):
        return ServiceUsage.NOT_APPLICABLE

    @property
    def bug_tracking_usage(self):
        if not self.official_malone:
            return ServiceUsage.UNKNOWN
        else:
            return ServiceUsage.LAUNCHPAD

    @property
    def uses_launchpad(self):
        """Does this distribution actually use Launchpad?"""
        return self.official_anything

    enable_bug_expiration = BoolCol(dbName='enable_bug_expiration',
        notNull=True, default=False)
    translation_focus = ForeignKey(dbName='translation_focus',
        foreignKey='DistroSeries', notNull=False, default=None)
    date_created = UtcDateTimeCol(notNull=False, default=UTC_NOW)
    language_pack_admin = ForeignKey(
        dbName='language_pack_admin', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False, default=None)

    @cachedproperty
    def main_archive(self):
        """See `IDistribution`."""
        return Store.of(self).find(Archive, distribution=self,
            purpose=ArchivePurpose.PRIMARY).one()

    @cachedproperty
    def all_distro_archives(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            Archive,
            Archive.distribution == self,
            Archive.purpose.is_in(MAIN_ARCHIVE_PURPOSES))

    @cachedproperty
    def all_distro_archive_ids(self):
        """See `IDistribution`."""
        return [archive.id for archive in self.all_distro_archives]

    def _getMilestoneCondition(self):
        """See `HasMilestonesMixin`."""
        return (Milestone.distribution == self)

    def getArchiveIDList(self, archive=None):
        """See `IDistribution`."""
        if archive is None:
            return self.all_distro_archive_ids
        else:
            return [archive.id]

    @property
    def archive_mirrors(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            content=MirrorContent.ARCHIVE,
            enabled=True,
            status=MirrorStatus.OFFICIAL,
            official_candidate=True)

    @property
    def cdimage_mirrors(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            content=MirrorContent.RELEASE,
            enabled=True,
            status=MirrorStatus.OFFICIAL,
            official_candidate=True)

    @property
    def disabled_mirrors(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            enabled=False,
            status=MirrorStatus.OFFICIAL,
            official_candidate=True)

    @property
    def unofficial_mirrors(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            status=MirrorStatus.UNOFFICIAL)

    @property
    def pending_review_mirrors(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            status=MirrorStatus.PENDING_REVIEW,
            official_candidate=True)

    @property
    def full_functionality(self):
        """See `IDistribution`."""
        if IBaseDistribution.providedBy(self):
            return True
        return False

    @property
    def drivers(self):
        """See `IDistribution`."""
        if self.driver is not None:
            return [self.driver]
        else:
            return [self.owner]

    @property
    def _sort_key(self):
        """Return something that can be used to sort distributions,
        putting Ubuntu and its major derivatives first.

        This is used to ensure that the list of distributions displayed in
        Soyuz generally puts Ubuntu at the top.
        """
        if self.name == 'ubuntu':
            return (0, 'ubuntu')
        if self.name in ['kubuntu', 'xubuntu', 'edubuntu']:
            return (1, self.name)
        if 'buntu' in self.name:
            return (2, self.name)
        return (3, self.name)

    @cachedproperty
    def series(self):
        """See `IDistribution`."""
        ret = Store.of(self).find(
            DistroSeries,
            distribution=self)
        return sorted(ret, key=lambda a: Version(a.version), reverse=True)

    @property
    def architectures(self):
        """See `IDistribution`."""
        architectures = []

        # Concatenate architectures list since they are distinct.
        for series in self.series:
            architectures += series.architectures

        return architectures

    @property
    def mentoring_offers(self):
        """See `IDistribution`"""
        via_specs = MentoringOffer.select("""
            Specification.distribution = %s AND
            Specification.id = MentoringOffer.specification
            """ % sqlvalues(self.id) + """ AND NOT (
            """ + Specification.completeness_clause + ")",
            clauseTables=['Specification'],
            distinct=True)
        via_bugs = MentoringOffer.select("""
            BugTask.distribution = %s AND
            BugTask.bug = MentoringOffer.bug AND
            BugTask.bug = Bug.id AND
            Bug.private IS FALSE
            """ % sqlvalues(self.id) + """ AND NOT (
            """ + BugTask.completeness_clause +")",
            clauseTables=['BugTask', 'Bug'],
            distinct=True)
        return via_specs.union(via_bugs, orderBy=['-date_created', '-id'])

    @property
    def bugtargetdisplayname(self):
        """See IBugTarget."""
        return self.displayname

    @property
    def bugtargetname(self):
        """See `IBugTarget`."""
        return self.name

    def _getBugTaskContextWhereClause(self):
        """See BugTargetBase."""
        return "BugTask.distribution = %d" % self.id

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for this distribution."""
        search_params.setDistribution(self)

    def getUsedBugTags(self):
        """See `IBugTarget`."""
        return get_bug_tags("BugTask.distribution = %s" % sqlvalues(self))

    def getUsedBugTagsWithOpenCounts(self, user):
        """See `IBugTarget`."""
        return get_bug_tags_open_count(BugTask.distribution == self, user)

    def getMirrorByName(self, name):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            name=name).one()

    def getCountryMirror(self, country, mirror_type):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistributionMirror,
            distribution=self,
            country=country,
            content=mirror_type,
            country_dns_mirror=True).one()

    def newMirror(self, owner, speed, country, content, displayname=None,
                  description=None, http_base_url=None,
                  ftp_base_url=None, rsync_base_url=None,
                  official_candidate=False, enabled=False,
                  whiteboard=None):
        """See `IDistribution`."""
        # NB this functionality is only available to distributions that have
        # the full functionality of Launchpad enabled. This is Ubuntu and
        # commercial derivatives that have been specifically given this
        # ability
        if not self.full_functionality:
            return None

        urls = {'http_base_url': http_base_url,
                'ftp_base_url': ftp_base_url,
                'rsync_base_url': rsync_base_url}
        for name, value in urls.items():
            if value is not None:
                urls[name] = IDistributionMirror[name].normalize(value)

        url = urls['http_base_url'] or urls['ftp_base_url']
        assert url is not None, (
            "A mirror must provide either an HTTP or FTP URL (or both).")
        dummy, host, dummy, dummy, dummy, dummy = urlparse(url)
        name = sanitize_name('%s-%s' % (host, content.name.lower()))

        orig_name = name
        count = 1
        while self.getMirrorByName(name=name) is not None:
            count += 1
            name = '%s%s' % (orig_name, count)

        return DistributionMirror(
            distribution=self, owner=owner, name=name, speed=speed,
            country=country, content=content, displayname=displayname,
            description=description, http_base_url=urls['http_base_url'],
            ftp_base_url=urls['ftp_base_url'],
            rsync_base_url=urls['rsync_base_url'],
            official_candidate=official_candidate, enabled=enabled,
            whiteboard=whiteboard)

    def createBug(self, bug_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        bug_params.setBugTarget(distribution=self)
        return BugSet().createBug(bug_params)

    def _getBugTaskContextClause(self):
        """See BugTargetBase."""
        return 'BugTask.distribution = %s' % sqlvalues(self)

    @property
    def currentseries(self):
        """See `IDistribution`."""
        # XXX kiko 2006-03-18:
        # This should be just a selectFirst with a case in its
        # order by clause.

        # If we have a frozen one, return that.
        for series in self.series:
            if series.status == SeriesStatus.FROZEN:
                return series
        # If we have one in development, return that.
        for series in self.series:
            if series.status == SeriesStatus.DEVELOPMENT:
                return series
        # If we have a stable one, return that.
        for series in self.series:
            if series.status == SeriesStatus.CURRENT:
                return series
        # If we have ANY, return the first one.
        if len(self.series) > 0:
            return self.series[0]
        return None

    def __getitem__(self, name):
        for series in self.series:
            if series.name == name:
                return series
        raise NotFoundError(name)

    def __iter__(self):
        return iter(self.series)

    def getArchive(self, name):
        """See `IDistribution.`"""
        return getUtility(
            IArchiveSet).getByDistroAndName(self, name)

    def getSeries(self, name_or_version):
        """See `IDistribution`."""
        distroseries = Store.of(self).find(DistroSeries,
               Or(DistroSeries.name == name_or_version,
               DistroSeries.version == name_or_version),
            DistroSeries.distribution == self).one()
        if not distroseries:
            raise NoSuchDistroSeries(name_or_version)
        return distroseries

    def getDevelopmentSeries(self):
        """See `IDistribution`."""
        return Store.of(self).find(
            DistroSeries,
            distribution=self,
            status=SeriesStatus.DEVELOPMENT)

    def getMilestone(self, name):
        """See `IDistribution`."""
        return Milestone.selectOne("""
            distribution = %s AND
            name = %s
            """ % sqlvalues(self.id, name))

    def getSourcePackage(self, name):
        """See `IDistribution`."""
        if ISourcePackageName.providedBy(name):
            sourcepackagename = name
        else:
            try:
                sourcepackagename = SourcePackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return DistributionSourcePackage(self, sourcepackagename)

    def getSourcePackageRelease(self, sourcepackagerelease):
        """See `IDistribution`."""
        return DistributionSourcePackageRelease(self, sourcepackagerelease)

    def getCurrentSourceReleases(self, source_package_names):
        """See `IDistribution`."""
        source_package_ids = [
            package_name.id for package_name in source_package_names]
        releases = SourcePackageRelease.select("""
            SourcePackageName.id IN %s AND
            SourcePackageRelease.id =
                SourcePackagePublishingHistory.sourcepackagerelease AND
            SourcePackagePublishingHistory.id = (
                SELECT max(spph.id)
                FROM SourcePackagePublishingHistory spph,
                     SourcePackageRelease spr, SourcePackageName spn,
                     DistroSeries ds
                WHERE
                    spn.id = SourcePackageName.id AND
                    spr.sourcepackagename = spn.id AND
                    spph.sourcepackagerelease = spr.id AND
                    spph.archive IN %s AND
                    spph.status IN %s AND
                    spph.distroseries = ds.id AND
                    ds.distribution = %s)
            """ % sqlvalues(
                source_package_ids, self.all_distro_archive_ids,
                active_publishing_status, self),
            clauseTables=[
                'SourcePackageName', 'SourcePackagePublishingHistory'])
        return dict(
            (self.getSourcePackage(release.sourcepackagename),
             DistributionSourcePackageRelease(self, release))
            for release in releases)

    @property
    def has_any_specifications(self):
        """See `IHasSpecifications`."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        """See `IHasSpecifications`."""
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None,
                       prejoin_people=True):
        """See `IHasSpecifications`.

        In the case of distributions, there are two kinds of filtering,
        based on:

          - completeness: we want to show INCOMPLETE if nothing is said
          - informationalness: we will show ANY if nothing is said

        """

        # Make a new list of the filter, so that we do not mutate what we
        # were passed as a filter
        if not filter:
            # it could be None or it could be []
            filter = [SpecificationFilter.INCOMPLETE]

        # now look at the filter and fill in the unsaid bits

        # defaults for completeness: if nothing is said about completeness
        # then we want to show INCOMPLETE
        completeness = False
        for option in [
            SpecificationFilter.COMPLETE,
            SpecificationFilter.INCOMPLETE]:
            if option in filter:
                completeness = True
        if completeness is False:
            filter.append(SpecificationFilter.INCOMPLETE)

        # defaults for acceptance: in this case we have nothing to do
        # because specs are not accepted/declined against a distro

        # defaults for informationalness: we don't have to do anything
        # because the default if nothing is said is ANY

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = (
                ['-priority', 'Specification.definition_status',
                 'Specification.name'])
        elif sort == SpecificationSort.DATE:
            order = ['-Specification.datecreated', 'Specification.id']

        # figure out what set of specifications we are interested in. for
        # distributions, we need to be able to filter on the basis of:
        #
        #  - completeness. by default, only incomplete specs shown
        #  - informational.
        #
        base = 'Specification.distribution = %s' % self.id
        query = base
        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += (' AND Specification.implementation_status = %s ' %
                quote(SpecificationImplementationStatus.INFORMATIONAL))

        # filter based on completion. see the implementation of
        # Specification.is_complete() for more details
        completeness = Specification.completeness_clause

        if SpecificationFilter.COMPLETE in filter:
            query += ' AND ( %s ) ' % completeness
        elif SpecificationFilter.INCOMPLETE in filter:
            query += ' AND NOT ( %s ) ' % completeness

        # Filter for validity. If we want valid specs only then we should
        # exclude all OBSOLETE or SUPERSEDED specs
        if SpecificationFilter.VALID in filter:
            query += (' AND Specification.definition_status NOT IN '
                '( %s, %s ) ' % sqlvalues(
                    SpecificationDefinitionStatus.OBSOLETE,
                    SpecificationDefinitionStatus.SUPERSEDED))

        # ALL is the trump card
        if SpecificationFilter.ALL in filter:
            query = base

        # Filter for specification text
        for constraint in filter:
            if isinstance(constraint, basestring):
                # a string in the filter is a text search filter
                query += ' AND Specification.fti @@ ftq(%s) ' % quote(
                    constraint)

        results = Specification.select(query, orderBy=order, limit=quantity)
        if prejoin_people:
            results = results.prejoin(['assignee', 'approver', 'drafter'])
        return results

    def getSpecification(self, name):
        """See `ISpecificationTarget`."""
        return Specification.selectOneBy(distribution=self, name=name)

    def searchQuestions(self, search_text=None,
                        status=QUESTION_STATUS_DEFAULT_SEARCH,
                        language=None, sort=None, owner=None,
                        needs_attention_from=None, unsupported=False):
        """See `IQuestionCollection`."""
        if unsupported:
            unsupported_target = self
        else:
            unsupported_target = None

        return QuestionTargetSearch(
            distribution=self,
            search_text=search_text, status=status,
            language=language, sort=sort, owner=owner,
            needs_attention_from=needs_attention_from,
            unsupported_target=unsupported_target).getResults()

    def getTargetTypes(self):
        """See `QuestionTargetMixin`.

        Defines distribution as self and sourcepackagename as None.
        """
        return {'distribution': self,
                'sourcepackagename': None}

    def questionIsForTarget(self, question):
        """See `QuestionTargetMixin`.

        Return True when the Question's distribution is self.
        """
        if question.distribution is not self:
            return False
        return True

    def newFAQ(self, owner, title, content, keywords=None, date_created=None):
        """See `IFAQTarget`."""
        return FAQ.new(
            owner=owner, title=title, content=content, keywords=keywords,
            date_created=date_created, distribution=self)

    def findSimilarFAQs(self, summary):
        """See `IFAQTarget`."""
        return FAQ.findSimilar(summary, distribution=self)

    def getFAQ(self, id):
        """See `IFAQCollection`."""
        return FAQ.getForTarget(id, self)

    def searchFAQs(self, search_text=None, owner=None, sort=None):
        """See `IFAQCollection`."""
        return FAQSearch(
            search_text=search_text, owner=owner, sort=sort,
            distribution=self).getResults()

    def getDistroSeriesAndPocket(self, distroseries_name):
        """See `IDistribution`."""
        from lp.archivepublisher.publishing import suffixpocket

        # Get the list of suffixes.
        suffixes = [suffix for suffix, ignored in suffixpocket.items()]
        # Sort it longest string first.
        suffixes.sort(key=len, reverse=True)

        for suffix in suffixes:
            if distroseries_name.endswith(suffix):
                try:
                    left_size = len(distroseries_name) - len(suffix)
                    return (self[distroseries_name[:left_size]],
                            suffixpocket[suffix])
                except KeyError:
                    # Swallow KeyError to continue round the loop.
                    pass

        raise NotFoundError(distroseries_name)

    def getSeriesByStatus(self, status):
        """See `IDistribution`."""
        return Store.of(self).find(DistroSeries,
            DistroSeries.distribution == self,
            DistroSeries.status == status)

    def getFileByName(self, filename, archive=None, source=True, binary=True):
        """See `IDistribution`."""
        assert (source or binary), "searching in an explicitly empty " \
               "space is pointless"
        if archive is None:
            archive = self.main_archive

        if source:
            candidate = SourcePackageFilePublishing.selectFirstBy(
                distribution=self, libraryfilealiasfilename=filename,
                archive=archive, orderBy=['id'])

        if binary:
            candidate = BinaryPackageFilePublishing.selectFirstBy(
                distribution=self,
                libraryfilealiasfilename=filename,
                archive=archive, orderBy=["-id"])

        if candidate is not None:
            return candidate.libraryfilealias

        raise NotFoundError(filename)

    def getBuildRecords(self, build_state=None, name=None, pocket=None,
                        arch_tag=None, user=None, binary_only=True):
        """See `IHasBuildRecords`"""
        # Ignore "user", since it would not make any difference to the
        # records returned here (private builds are only in PPA right
        # now).
        # The "binary_only" option is not yet supported for
        # IDistribution.

        # Find out the distroarchseries in question.
        arch_ids = DistroArchSeriesSet().getIdsForArchitectures(
            self.architectures, arch_tag)

        # Use the facility provided by IBinaryPackageBuildSet to
        # retrieve the records.
        return getUtility(IBinaryPackageBuildSet).getBuildsByArchIds(
            self, arch_ids, build_state, name, pocket)

    def getSourcePackageCaches(self, archive=None):
        """See `IDistribution`."""
        if archive is not None:
            archives = [archive.id]
        else:
            archives = self.all_distro_archive_ids

        caches = DistributionSourcePackageCache.select("""
            distribution = %s AND
            archive IN %s
        """ % sqlvalues(self, archives),
        orderBy="name",
        prejoins=['sourcepackagename'])

        return caches

    def removeOldCacheItems(self, archive, log):
        """See `IDistribution`."""

        # Get the set of source package names to deal with.
        spns = set(SourcePackageName.select("""
            SourcePackagePublishingHistory.distroseries =
                DistroSeries.id AND
            DistroSeries.distribution = %s AND
            Archive.id = %s AND
            SourcePackagePublishingHistory.archive = Archive.id AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id AND
            SourcePackagePublishingHistory.dateremoved is NULL AND
            Archive.enabled = TRUE
            """ % sqlvalues(self, archive),
            distinct=True,
            clauseTables=[
                'Archive',
                'DistroSeries',
                'SourcePackagePublishingHistory',
                'SourcePackageRelease']))

        # Remove the cache entries for packages we no longer publish.
        for cache in self.getSourcePackageCaches(archive):
            if cache.sourcepackagename not in spns:
                log.debug(
                    "Removing source cache for '%s' (%s)"
                    % (cache.name, cache.id))
                cache.destroySelf()

    def updateCompleteSourcePackageCache(self, archive, log, ztm,
                                         commit_chunk=500):
        """See `IDistribution`."""
        # Do not create cache entries for disabled archives.
        if not archive.enabled:
            return

        # Get the set of source package names to deal with.
        spns = list(SourcePackageName.select("""
            SourcePackagePublishingHistory.distroseries =
                DistroSeries.id AND
            DistroSeries.distribution = %s AND
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id AND
            SourcePackagePublishingHistory.dateremoved is NULL
            """ % sqlvalues(self, archive),
            distinct=True,
            orderBy="name",
            clauseTables=['SourcePackagePublishingHistory', 'DistroSeries',
                'SourcePackageRelease']))

        number_of_updates = 0
        chunk_size = 0
        for spn in spns:
            log.debug("Considering source '%s'" % spn.name)
            self.updateSourcePackageCache(spn, archive, log)
            chunk_size += 1
            number_of_updates += 1
            if chunk_size == commit_chunk:
                chunk_size = 0
                log.debug("Committing")
                ztm.commit()

        return number_of_updates

    def updateSourcePackageCache(self, sourcepackagename, archive, log):
        """See `IDistribution`."""

        # Get the set of published sourcepackage releases.
        sprs = list(SourcePackageRelease.select("""
            SourcePackageRelease.sourcepackagename = %s AND
            SourcePackageRelease.id =
                SourcePackagePublishingHistory.sourcepackagerelease AND
            SourcePackagePublishingHistory.distroseries =
                DistroSeries.id AND
            DistroSeries.distribution = %s AND
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.dateremoved is NULL
            """ % sqlvalues(sourcepackagename, self, archive),
            orderBy='id',
            clauseTables=['SourcePackagePublishingHistory', 'DistroSeries'],
            distinct=True))

        if len(sprs) == 0:
            log.debug("No sources releases found.")
            return

        # Find or create the cache entry.
        cache = DistributionSourcePackageCache.selectOne("""
            distribution = %s AND
            archive = %s AND
            sourcepackagename = %s
            """ % sqlvalues(self, archive, sourcepackagename))
        if cache is None:
            log.debug("Creating new source cache entry.")
            cache = DistributionSourcePackageCache(
                archive=archive,
                distribution=self,
                sourcepackagename=sourcepackagename)

        # Make sure the name is correct.
        cache.name = sourcepackagename.name

        # Get the sets of binary package names, summaries, descriptions.

        # XXX Julian 2007-04-03:
        # This bit of code needs fixing up, it is doing stuff that
        # really needs to be done in SQL, such as sorting and uniqueness.
        # This would also improve the performance.
        binpkgnames = set()
        binpkgsummaries = set()
        binpkgdescriptions = set()
        sprchangelog = set()
        for spr in sprs:
            log.debug("Considering source version %s" % spr.version)
            # changelog may be empty, in which case we don't want to add it
            # to the set as the join would fail below.
            if spr.changelog_entry is not None:
                sprchangelog.add(spr.changelog_entry)
            binpkgs = BinaryPackageRelease.select("""
                BinaryPackageRelease.build = BinaryPackageBuild.id AND
                BinaryPackageBuild.source_package_release = %s
                """ % sqlvalues(spr.id),
                clauseTables=['BinaryPackageBuild'])
            for binpkg in binpkgs:
                log.debug("Considering binary '%s'" % binpkg.name)
                binpkgnames.add(binpkg.name)
                binpkgsummaries.add(binpkg.summary)
                binpkgdescriptions.add(binpkg.description)

        # Update the caches.
        cache.binpkgnames = ' '.join(sorted(binpkgnames))
        cache.binpkgsummaries = ' '.join(sorted(binpkgsummaries))
        cache.binpkgdescriptions = ' '.join(sorted(binpkgdescriptions))
        cache.changelog = ' '.join(sorted(sprchangelog))

    def searchSourcePackageCaches(
        self, text, has_packaging=None, publishing_distroseries=None):
        """See `IDistribution`."""
        # The query below tries exact matching on the source package
        # name as well; this is because source package names are
        # notoriously bad for fti matching -- they can contain dots, or
        # be short like "at", both things which users do search for.
        store = Store.of(self)
        find_spec = (
            DistributionSourcePackageCache,
            SourcePackageName,
            SQL('rank(fti, ftq(%s)) AS rank' % sqlvalues(text)),
            )
        origin = [
            DistributionSourcePackageCache,
            Join(
                SourcePackageName,
                DistributionSourcePackageCache.sourcepackagename ==
                    SourcePackageName.id,
                ),
            ]

        publishing_condition = ''
        if publishing_distroseries is not None:
            publishing_condition = """
                AND EXISTS (
                    SELECT 1
                    FROM SourcePackageRelease spr
                        JOIN SourcePackagePublishingHistory spph
                            ON spph.sourcepackagerelease = spr.id
                    WHERE spr.sourcepackagename = SourcePackageName.id
                        AND spph.distroseries = %d
                    )""" % (
                publishing_distroseries.id)

        packaging_query = """
            SELECT 1
            FROM Packaging
            WHERE Packaging.sourcepackagename = SourcePackageName.id
            """
        has_packaging_condition = ''
        if has_packaging is True:
            has_packaging_condition = 'AND EXISTS (%s)' % packaging_query
        elif has_packaging is False:
            has_packaging_condition = 'AND NOT EXISTS (%s)' % packaging_query

        # Note: When attempting to convert the query below into straight
        # Storm expressions, a 'tuple index out-of-range' error was always
        # raised.
        condition = """
            DistributionSourcePackageCache.distribution = %s AND
            DistributionSourcePackageCache.archive IN %s AND
            (DistributionSourcePackageCache.fti @@ ftq(%s) OR
             DistributionSourcePackageCache.name ILIKE '%%' || %s || '%%')
            %s
            %s
            """ % (quote(self), quote(self.all_distro_archive_ids),
                   quote(text), quote_like(text), has_packaging_condition,
                   publishing_condition)
        dsp_caches_with_ranks = store.using(*origin).find(
            find_spec, condition).order_by('rank DESC')

        return dsp_caches_with_ranks

    def searchSourcePackages(
        self, text, has_packaging=None, publishing_distroseries=None):
        """See `IDistribution`."""

        dsp_caches_with_ranks = self.searchSourcePackageCaches(
            text, has_packaging=has_packaging,
            publishing_distroseries=publishing_distroseries)

        # Create a function that will decorate the resulting
        # DistributionSourcePackageCaches, converting
        # them from the find_spec above into DSPs:
        def result_to_dsp(result):
            cache, source_package_name, rank = result
            return DistributionSourcePackage(
                self,
                source_package_name)

        # Return the decorated result set so the consumer of these
        # results will only see DSPs
        return DecoratedResultSet(dsp_caches_with_ranks, result_to_dsp)

    @property
    def _binaryPackageSearchClause(self):
        """Return a Storm match clause for binary package searches."""
        # This matches all DistributionSourcePackageCache rows that have
        # a source package that generated the BinaryPackageName that
        # we're searching for.
        return (
            DistroSeries.distribution == self,
            DistroSeries.status != SeriesStatus.OBSOLETE,
            BinaryPackageRelease.binarypackagename == BinaryPackageName.id,
            DistroArchSeries.distroseries == DistroSeries.id,
            BinaryPackageBuild.distro_arch_series == DistroArchSeries.id,
            BinaryPackageRelease.build == BinaryPackageBuild.id,
            (BinaryPackageBuild.source_package_release ==
                SourcePackageRelease.id),
            SourcePackageRelease.sourcepackagename == SourcePackageName.id,
            DistributionSourcePackageCache.sourcepackagename ==
                SourcePackageName.id,
            In(
                DistributionSourcePackageCache.archiveID,
                self.all_distro_archive_ids))

    def searchBinaryPackages(self, package_name, exact_match=False):
        """See `IDistribution`."""
        store = Store.of(self)

        select_spec = (DistributionSourcePackageCache,)

        if exact_match:
            find_spec = self._binaryPackageSearchClause
            match_clause = (BinaryPackageName.name == package_name,)
        else:
            # In this case we can use a simplified find-spec as the
            # binary package names are present on the
            # DistributionSourcePackageCache records.
            find_spec = (
                DistributionSourcePackageCache.distribution == self,
                In(
                    DistributionSourcePackageCache.archiveID,
                    self.all_distro_archive_ids))
            match_clause = (
                DistributionSourcePackageCache.binpkgnames.like(
                    "%%%s%%" % package_name.lower()),)

        result_set = store.find(
            *(select_spec + find_spec + match_clause)).config(distinct=True)

        return result_set.order_by(DistributionSourcePackageCache.name)

    def searchBinaryPackagesFTI(self, package_name):
        """See `IDistribution`."""
        search_vector_column = DistroSeriesPackageCache.fti
        query_function = FTQ(package_name)
        rank = RANK(search_vector_column, query_function)

        extra_clauses = (
            BinaryPackageRelease.binarypackagenameID ==
                DistroSeriesPackageCache.binarypackagenameID,
            Match(search_vector_column, query_function),
            )
        where_spec = (self._binaryPackageSearchClause + extra_clauses)

        select_spec = (DistributionSourcePackageCache, rank)
        store = Store.of(self)
        results = store.find(select_spec, where_spec)
        results.order_by(Desc(rank)).config(distinct=True)

        def result_to_dspc(result):
            cache, rank = result
            return cache

        # Return the decorated result set so the consumer of these
        # results will only see DSPCs
        return DecoratedResultSet(results, result_to_dspc)

    def guessPackageNames(self, pkgname):
        """See `IDistribution`"""
        assert isinstance(pkgname, basestring), (
            "Expected string. Got: %r" % pkgname)

        pkgname = pkgname.strip().lower()
        if not valid_name(pkgname):
            raise NotFoundError('Invalid package name: %s' % pkgname)

        if self.currentseries is None:
            # Distribution with no series can't have anything
            # published in it.
            raise NotFoundError('%s has no series; %r was never '
                                'published in it'
                                % (self.displayname, pkgname))

        # The way this method works is that is tries to locate a pair
        # of packages related to that name. If it locates a source
        # package it then tries to see if it has been published at any
        # point, and gets the binary package from the publishing
        # record.
        #
        # If that fails (no source package by that name, or not
        # published) then it'll search binary packages, then find the
        # source package most recently associated with it, first in
        # the current distroseries and then across the whole
        # distribution.
        #
        # XXX kiko 2006-07-28:
        # Note that the strategy of falling back to previous
        # distribution series might be revisited in the future; for
        # instance, when people file bugs, it might actually be bad for
        # us to allow them to be associated with obsolete packages.

        bpph_location_clauses = [
            DistroSeries.distribution == self,
            DistroArchSeries.distroseriesID == DistroSeries.id,
            BinaryPackagePublishingHistory.distroarchseriesID ==
                DistroArchSeries.id,
            BinaryPackagePublishingHistory.archiveID.is_in(
                self.all_distro_archive_ids),
            BinaryPackagePublishingHistory.dateremoved == None,
            BinaryPackageRelease.id ==
                BinaryPackagePublishingHistory.binarypackagereleaseID,
            ]

        sourcepackagename = SourcePackageName.selectOneBy(name=pkgname)
        if sourcepackagename:
            # Note that in the source package case, we don't restrict
            # the search to the distribution release, making a best
            # effort to find a package.
            publishing = SourcePackagePublishingHistory.selectFirst('''
                SourcePackagePublishingHistory.distroseries =
                    DistroSeries.id AND
                DistroSeries.distribution = %s AND
                SourcePackagePublishingHistory.archive IN %s AND
                SourcePackagePublishingHistory.sourcepackagerelease =
                    SourcePackageRelease.id AND
                SourcePackageRelease.sourcepackagename = %s AND
                SourcePackagePublishingHistory.status IN %s
                ''' % sqlvalues(self,
                                self.all_distro_archive_ids,
                                sourcepackagename,
                                (PackagePublishingStatus.PUBLISHED,
                                 PackagePublishingStatus.PENDING)),
                clauseTables=['SourcePackageRelease', 'DistroSeries'],
                distinct=True,
                orderBy="id")
            if publishing is not None:
                # Attempt to find a published binary package of the
                # same name.
                bpph = IStore(BinaryPackagePublishingHistory).find(
                    BinaryPackagePublishingHistory,
                    BinaryPackageRelease.binarypackagename ==
                        BinaryPackageName.id,
                    BinaryPackageName.name == sourcepackagename.name,
                    BinaryPackageBuild.id == BinaryPackageRelease.buildID,
                    SourcePackageRelease.id ==
                        BinaryPackageBuild.source_package_release_id,
                    SourcePackageRelease.sourcepackagename ==
                        sourcepackagename,
                    *bpph_location_clauses).any()
                if bpph is not None:
                    bpr = bpph.binarypackagerelease
                    return (sourcepackagename, bpr.binarypackagename)
                # No binary with a similar name, so just return None
                # rather than returning some arbitrary binary package.
                return (sourcepackagename, None)

        # At this point we don't have a published source package by
        # that name, so let's try to find a binary package and work
        # back from there.
        binarypackagename = BinaryPackageName.selectOneBy(name=pkgname)
        if binarypackagename:
            # Ok, so we have a binarypackage with that name. Grab its
            # latest publication in the distribution (this may be an old
            # package name the end-user is groping for) -- and then get
            # the sourcepackagename from that.
            bpph = IStore(BinaryPackagePublishingHistory).find(
                BinaryPackagePublishingHistory,
                BinaryPackageRelease.binarypackagename == binarypackagename,
                *bpph_location_clauses).order_by(
                    Desc(BinaryPackagePublishingHistory.id)).first()
            if bpph is not None:
                spr = bpph.binarypackagerelease.build.source_package_release
                return (spr.sourcepackagename, binarypackagename)

        # We got nothing so signal an error.
        if sourcepackagename is None:
            # Not a binary package name, not a source package name,
            # game over!
            if binarypackagename:
                raise NotFoundError('Binary package %s not published in %s'
                                    % (pkgname, self.displayname))
            else:
                raise NotFoundError('Unknown package: %s' % pkgname)
        else:
            raise NotFoundError('Package %s not published in %s'
                                % (pkgname, self.displayname))

    # XXX cprov 20071024:  move this API to IArchiveSet, Distribution is
    # already too long and complicated.
    def getAllPPAs(self):
        """See `IDistribution`"""
        return Store.of(self).find(
            Archive,
            distribution=self,
            purpose=ArchivePurpose.PPA).order_by('id')

    def getCommercialPPAs(self):
        """See `IDistribution`."""
        # If we ever see non-Ubuntu PPAs, this will return more than
        # just the PPAs for the Ubuntu context.
        return getUtility(IArchiveSet).getCommercialPPAs()

    def searchPPAs(self, text=None, show_inactive=False, user=None):
        """See `IDistribution`."""
        clauses = ["""
        Archive.purpose = %s AND
        Archive.distribution = %s AND
        Person.id = Archive.owner AND
        Person.id = ValidPersonOrTeamCache.id
        """ % sqlvalues(ArchivePurpose.PPA, self)]

        clauseTables = ['Person', 'ValidPersonOrTeamCache']
        orderBy = ['Person.name']

        if not show_inactive:
            active_statuses = (PackagePublishingStatus.PUBLISHED,
                               PackagePublishingStatus.PENDING)
            clauses.append("""
            Archive.id IN (
                SELECT DISTINCT archive FROM SourcepackagePublishingHistory
                WHERE status IN %s)
            """ % sqlvalues(active_statuses))

        if text:
            orderBy.insert(
                0, SQLConstant(
                    'rank(Archive.fti, ftq(%s)) DESC' % quote(text)))

            clauses.append("""
                Archive.fti @@ ftq(%s)
            """ % sqlvalues(text))

        if user is not None:
            if not user.inTeam(getUtility(ILaunchpadCelebrities).admin):
                clauses.append("""
                ((Archive.private = FALSE AND Archive.enabled = TRUE) OR
                 Archive.owner = %s OR
                 %s IN (SELECT TeamParticipation.person
                        FROM TeamParticipation
                        WHERE TeamParticipation.person = %s AND
                              TeamParticipation.team = Archive.owner)
                )
                """ % sqlvalues(user, user, user))
        else:
            clauses.append(
                "Archive.private = FALSE AND Archive.enabled = TRUE")


        query = ' AND '.join(clauses)
        return Archive.select(
            query, orderBy=orderBy, clauseTables=clauseTables)

    def getPendingAcceptancePPAs(self):
        """See `IDistribution`."""
        query = """
        Archive.purpose = %s AND
        Archive.distribution = %s AND
        PackageUpload.archive = Archive.id AND
        PackageUpload.status = %s
        """ % sqlvalues(ArchivePurpose.PPA, self,
                        PackageUploadStatus.ACCEPTED)

        return Archive.select(
            query, clauseTables=['PackageUpload'],
            orderBy=['archive.id'], distinct=True)

    def getPendingPublicationPPAs(self):
        """See `IDistribution`."""
        src_query = """
        Archive.purpose = %s AND
        Archive.distribution = %s AND
        SourcePackagePublishingHistory.archive = archive.id AND
        SourcePackagePublishingHistory.scheduleddeletiondate is null AND
        SourcePackagePublishingHistory.status IN (%s, %s)
         """ % sqlvalues(ArchivePurpose.PPA, self,
                         PackagePublishingStatus.PENDING,
                         PackagePublishingStatus.DELETED)

        src_archives = Archive.select(
            src_query, clauseTables=['SourcePackagePublishingHistory'],
            orderBy=['archive.id'], distinct=True)

        bin_query = """
        Archive.purpose = %s AND
        Archive.distribution = %s AND
        BinaryPackagePublishingHistory.archive = archive.id AND
        BinaryPackagePublishingHistory.scheduleddeletiondate is null AND
        BinaryPackagePublishingHistory.status IN (%s, %s)
        """ % sqlvalues(ArchivePurpose.PPA, self,
                        PackagePublishingStatus.PENDING,
                        PackagePublishingStatus.DELETED)

        bin_archives = Archive.select(
            bin_query, clauseTables=['BinaryPackagePublishingHistory'],
            orderBy=['archive.id'], distinct=True)

        deleting_archives = Archive.selectBy(
            status=ArchiveStatus.DELETING).orderBy(['archive.id'])

        return src_archives.union(bin_archives).union(deleting_archives)

    def getArchiveByComponent(self, component_name):
        """See `IDistribution`."""
        # XXX Julian 2007-08-16
        # These component names should be Soyuz-wide constants.
        componentMapToArchivePurpose = {
            'main': ArchivePurpose.PRIMARY,
            'restricted': ArchivePurpose.PRIMARY,
            'universe': ArchivePurpose.PRIMARY,
            'multiverse': ArchivePurpose.PRIMARY,
            'partner': ArchivePurpose.PARTNER,
            'contrib': ArchivePurpose.PRIMARY,
            'non-free': ArchivePurpose.PRIMARY,
            }

        try:
            # Map known components.
            return getUtility(IArchiveSet).getByDistroPurpose(self,
                componentMapToArchivePurpose[component_name])
        except KeyError:
            # Otherwise we defer to the caller.
            return None

    @property
    def upstream_report_excluded_packages(self):
        """See `IDistribution`."""
        # If the current distribution is Ubuntu, return a specific set
        # of excluded packages. Otherwise return an empty list.
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        if self == ubuntu:
            #XXX gmb 2009-02-02: bug 324298
            #    This needs to be managed in a nicer, non-hardcoded
            #    fashion.
            excluded_packages = [
                'apport',
                'casper',
                'displayconfig-gtk',
                'flashplugin-nonfree',
                'gnome-app-install',
                'nvidia-graphics-drivers-177',
                'software-properties',
                'sun-java6',
                'synaptic',
                'ubiquity',
                'ubuntu-meta',
                'update-manager',
                'update-notifier',
                'usb-creator',
                'usplash',
                ]
        else:
            excluded_packages = []

        return excluded_packages

    def getPackagesAndPublicUpstreamBugCounts(self, limit=50,
                                              exclude_packages=None):
        """See `IDistribution`."""
        from lp.registry.model.product import Product

        if exclude_packages is None or len(exclude_packages) == 0:
            # If exclude_packages is None or an empty list we set it to
            # be a list containing a single empty string. This is so
            # that we can quote() it properly for the query below ('NOT
            # IN ()' is not valid SQL).
            exclude_packages = ['']
        else:
            # Otherwise, listify exclude_packages so that we're not
            # trying to quote() a security proxy object.
            exclude_packages = list(exclude_packages)

        # This method collects three open bug counts for
        # sourcepackagenames in this distribution first, and then caches
        # product information before rendering everything into a list of
        # tuples.
        cur = cursor()
        cur.execute("""
            SELECT SPN.id, SPN.name,
            COUNT(DISTINCT Bugtask.bug) AS open_bugs,
            COUNT(DISTINCT CASE WHEN Bugtask.status = %(triaged)s THEN
                  Bugtask.bug END) AS bugs_triaged,
            COUNT(DISTINCT CASE WHEN Bugtask.status IN %(unresolved)s THEN
                  RelatedBugTask.bug END) AS bugs_affecting_upstream,
            COUNT(DISTINCT CASE WHEN Bugtask.status in %(unresolved)s AND
                  (RelatedBugTask.bugwatch IS NOT NULL OR
                  RelatedProduct.official_malone IS TRUE) THEN
                  RelatedBugTask.bug END) AS bugs_with_upstream_bugwatch,
            COUNT(DISTINCT CASE WHEN Bugtask.status in %(unresolved)s AND
                  RelatedBugTask.bugwatch IS NULL AND
                  RelatedProduct.official_malone IS FALSE AND
                  Bug.latest_patch_uploaded IS NOT NULL
                  THEN
                  RelatedBugTask.bug END)
                  AS bugs_with_upstream_patches
            FROM
                SourcePackageName AS SPN
                JOIN Bugtask ON SPN.id = Bugtask.sourcepackagename
                JOIN Bug ON Bug.id = Bugtask.bug
                LEFT OUTER JOIN Bugtask AS RelatedBugtask ON (
                    RelatedBugtask.bug = Bugtask.bug
                    AND RelatedBugtask.id != Bugtask.id
                    AND RelatedBugtask.product IS NOT NULL
                    AND RelatedBugtask.status != %(invalid)s
                    )
                LEFT OUTER JOIN Product AS RelatedProduct ON (
                    RelatedBugtask.product = RelatedProduct.id
                )
            WHERE
                Bugtask.distribution = %(distro)s
                AND Bugtask.sourcepackagename = spn.id
                AND Bugtask.distroseries IS NULL
                AND Bugtask.status IN %(unresolved)s
                AND Bug.private = 'F'
                AND Bug.duplicateof IS NULL
                AND spn.name NOT IN %(excluded_packages)s
            GROUP BY SPN.id, SPN.name
            HAVING COUNT(DISTINCT Bugtask.bug) > 0
            ORDER BY open_bugs DESC, SPN.name LIMIT %(limit)s
        """ % {'invalid': quote(BugTaskStatus.INVALID),
               'triaged': quote(BugTaskStatus.TRIAGED),
               'limit': limit,
               'distro': self.id,
               'unresolved': quote(UNRESOLVED_BUGTASK_STATUSES),
               'excluded_packages': quote(exclude_packages),
                })
        counts = cur.fetchall()
        cur.close()
        if not counts:
            # If no counts are returned it means that there are no
            # source package names in the database -- because the counts
            # would just return zero if no bugs existed. And if there
            # are no packages are in the database, all bets are off.
            return []

        # Next step is to extract which IDs actually show up in the
        # output we generate, and cache them.
        spn_ids = [item[0] for item in counts]
        list(SourcePackageName.select("SourcePackageName.id IN %s"
             % sqlvalues(spn_ids)))

        # Finally find out what products are attached to these source
        # packages (if any) and cache them too. The ordering of the
        # query by Packaging.id ensures that the dictionary holds the
        # latest entries for situations where we have multiple entries.
        cur = cursor()
        cur.execute("""
            SELECT Packaging.sourcepackagename, Product.id
              FROM Product, Packaging, ProductSeries, DistroSeries
             WHERE ProductSeries.product = Product.id AND
                   DistroSeries.distribution = %s AND
                   Packaging.distroseries = DistroSeries.id AND
                   Packaging.productseries = ProductSeries.id AND
                   Packaging.sourcepackagename IN %s AND
                   Packaging.packaging = %s AND
                   Product.active IS TRUE
                   ORDER BY Packaging.id
        """ % sqlvalues(self.id, spn_ids, PackagingType.PRIME))
        sources_to_products = dict(cur.fetchall())
        cur.close()
        if sources_to_products:
            # Cache some more information to avoid us having to hit the
            # database hard for each product rendered.
            list(Product.select("Product.id IN %s" %
                 sqlvalues(sources_to_products.values()),
                 prejoins=["bug_supervisor", "bugtracker", "project",
                           "development_focus.branch"]))

        # Okay, we have all the information good to go, so assemble it
        # in a reasonable data structure.
        results = []
        for (spn_id, spn_name, open_bugs, bugs_triaged,
             bugs_affecting_upstream, bugs_with_upstream_bugwatch,
             bugs_with_upstream_patches) in counts:
            sourcepackagename = SourcePackageName.get(spn_id)
            dsp = self.getSourcePackage(sourcepackagename)
            if spn_id in sources_to_products:
                product_id = sources_to_products[spn_id]
                product = Product.get(product_id)
            else:
                product = None
            results.append(
                (dsp, product, open_bugs, bugs_triaged,
                 bugs_affecting_upstream, bugs_with_upstream_bugwatch,
                 bugs_with_upstream_patches))
        return results

    def setBugSupervisor(self, bug_supervisor, user):
        """See `IHasBugSupervisor`."""
        self.bug_supervisor = bug_supervisor
        if bug_supervisor is not None:
            self.addBugSubscription(bug_supervisor, user)

    def userCanEdit(self, user):
        """See `IDistribution`."""
        if user is None:
            return False
        admins = getUtility(ILaunchpadCelebrities).admin
        return user.inTeam(self.owner) or user.inTeam(admins)

    def newSeries(self, name, displayname, title, summary,
                  description, version, parent_series, owner):
        """See `IDistribution`."""
        series = DistroSeries(
            distribution=self,
            name=name,
            displayname=displayname,
            title=title,
            summary=summary,
            description=description,
            version=version,
            status=SeriesStatus.EXPERIMENTAL,
            parent_series=parent_series,
            owner=owner)
        if owner.inTeam(self.driver) and not owner.inTeam(self.owner):
            # This driver is a release manager.
            series.driver = owner

        # May wish to add this to the series rather than clearing the cache --
        # RBC 20100816.
        del IPropertyCache(self).series

        return series

    @property
    def has_published_binaries(self):
        """See `IDistribution`."""
        store = Store.of(self)
        results = store.find(
            BinaryPackagePublishingHistory,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == self,
            BinaryPackagePublishingHistory.distroarchseries ==
                DistroArchSeries.id,
            BinaryPackagePublishingHistory.status ==
                PackagePublishingStatus.PUBLISHED).config(limit=1)

        # XXX 2009-02-19 Julian
        # Storm is not very useful for bool checking on the results,
        # see: https://bugs.launchpad.net/soyuz/+bug/246200
        return results.any() != None


class DistributionSet:
    """This class is to deal with Distribution related stuff"""

    implements(IDistributionSet)
    title = "Registered Distributions"

    def __iter__(self):
        """See `IDistributionSet`."""
        return iter(self.getDistros())

    def __getitem__(self, name):
        """See `IDistributionSet`."""
        distribution = self.getByName(name)
        if distribution is None:
            raise NotFoundError(name)
        return distribution

    def get(self, distributionid):
        """See canonical.launchpad.interfaces.IDistributionSet."""
        return Distribution.get(distributionid)

    def count(self):
        """See `IDistributionSet`."""
        return Distribution.select().count()

    def getDistros(self):
        """See `IDistributionSet`."""
        distros = Distribution.select()
        return sorted(
            shortlist(distros, 100), key=lambda distro: distro._sort_key)

    def getByName(self, name):
        """See `IDistributionSet`."""
        pillar = getUtility(IPillarNameSet).getByName(name)
        if not IDistribution.providedBy(pillar):
            return None
        return pillar

    def new(self, name, displayname, title, description, summary, domainname,
            members, owner, mugshot=None, logo=None, icon=None):
        """See `IDistributionSet`."""
        distro = Distribution(
            name=name,
            displayname=displayname,
            title=title,
            description=description,
            summary=summary,
            domainname=domainname,
            members=members,
            mirror_admin=owner,
            owner=owner,
            mugshot=mugshot,
            logo=logo,
            icon=icon)
        getUtility(IArchiveSet).new(distribution=distro,
            owner=owner, purpose=ArchivePurpose.PRIMARY)
        return distro
