# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212
"""Database classes for implementing distribution items."""

__metaclass__ = type
__all__ = ['Distribution', 'DistributionSet']

from zope.interface import implements
from zope.component import getUtility

from sqlobject import (
    BoolCol, ForeignKey, SQLRelatedJoin, StringCol, SQLObjectNotFound)
from sqlobject.sqlbuilder import SQLConstant
from storm.locals import SQL, Join
from storm.store import Store

from canonical.archivepublisher.debversion import Version
from canonical.cachedproperty import cachedproperty
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    quote, quote_like, SQLBase, sqlvalues, cursor)
from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet)
from canonical.launchpad.database.announcement import MakesAnnouncements
from canonical.launchpad.database.archive import Archive
from canonical.launchpad.database.binarypackagename import BinaryPackageName
from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.bug import (
    BugSet, get_bug_tags, get_bug_tags_open_count)
from canonical.launchpad.database.bugtarget import BugTargetBase
from canonical.launchpad.database.bugtask import BugTask
from canonical.launchpad.database.customlanguagecode import CustomLanguageCode
from canonical.launchpad.database.distributionbounty import DistributionBounty
from canonical.launchpad.database.distributionmirror import DistributionMirror
from canonical.launchpad.database.distributionsourcepackage import (
    DistributionSourcePackage)
from canonical.launchpad.database.distributionsourcepackagecache import (
    DistributionSourcePackageCache)
from canonical.launchpad.database.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease)
from canonical.launchpad.database.distroseries import DistroSeries
from canonical.launchpad.database.faq import FAQ, FAQSearch
from canonical.launchpad.database.karma import KarmaContextMixin
from canonical.launchpad.database.mentoringoffer import MentoringOffer
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.pillar import HasAliasMixin
from canonical.launchpad.database.publishedpackage import PublishedPackage
from canonical.launchpad.database.publishing import (
    SourcePackageFilePublishing, BinaryPackageFilePublishing,
    SourcePackagePublishingHistory)
from canonical.launchpad.database.question import (
    QuestionTargetSearch, QuestionTargetMixin)
from canonical.launchpad.database.specification import (
    HasSpecificationsMixin, Specification)
from canonical.launchpad.database.sprint import HasSprintsMixin
from canonical.launchpad.database.sourcepackagename import SourcePackageName
from canonical.launchpad.database.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.database.structuralsubscription import (
    StructuralSubscriptionTargetMixin)
from canonical.launchpad.database.translationimportqueue import (
    HasTranslationImportsMixin)
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.archive import (
    ArchivePurpose, IArchiveSet, MAIN_ARCHIVE_PURPOSES)
from canonical.launchpad.interfaces.archivepermission import (
    IArchivePermissionSet)
from canonical.launchpad.interfaces.bugsupervisor import IHasBugSupervisor
from canonical.launchpad.interfaces.bugtask import (
    BugTaskStatus, UNRESOLVED_BUGTASK_STATUSES)
from canonical.launchpad.interfaces.build import IBuildSet, IHasBuildRecords
from canonical.launchpad.interfaces.distribution import (
    IDistribution, IDistributionSet)
from canonical.launchpad.interfaces.distributionmirror import (
    MirrorContent, MirrorStatus)
from canonical.launchpad.interfaces.distroseries import DistroSeriesStatus
from canonical.launchpad.interfaces.faqtarget import IFAQTarget
from canonical.launchpad.interfaces.launchpad import (
    IHasIcon, IHasLogo, IHasMugshot, ILaunchpadCelebrities, ILaunchpadUsage)
from canonical.launchpad.interfaces.package import PackageUploadStatus
from canonical.launchpad.interfaces.packaging import PackagingType
from canonical.launchpad.interfaces.pillar import IPillarNameSet
from canonical.launchpad.interfaces.publishing import (
    active_publishing_status, PackagePublishingStatus)
from canonical.launchpad.interfaces.questioncollection import (
    QUESTION_STATUS_DEFAULT_SEARCH)
from canonical.launchpad.interfaces.questiontarget import IQuestionTarget
from canonical.launchpad.interfaces.sourcepackagename import (
    ISourcePackageName)
from canonical.launchpad.interfaces.specification import (
    SpecificationDefinitionStatus, SpecificationFilter,
    SpecificationImplementationStatus, SpecificationSort)
from canonical.launchpad.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget)
from canonical.launchpad.interfaces.translationgroup import (
    TranslationPermission)
from canonical.launchpad.validators.name import sanitize_name, valid_name
from canonical.launchpad.webapp.interfaces import NotFoundError
from canonical.launchpad.validators.person import validate_public_person
from canonical.launchpad.webapp.url import urlparse


class Distribution(SQLBase, BugTargetBase, MakesAnnouncements,
                   HasSpecificationsMixin, HasSprintsMixin, HasAliasMixin,
                   HasTranslationImportsMixin, KarmaContextMixin,
                   QuestionTargetMixin, StructuralSubscriptionTargetMixin):
    """A distribution of an operating system, e.g. Debian GNU/Linux."""
    implements(
        IDistribution, IFAQTarget, IHasBugSupervisor, IHasBuildRecords,
        IHasIcon, IHasLogo, IHasMugshot, ILaunchpadUsage,
        IQuestionTarget, IStructuralSubscriptionTarget)

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
        storm_validator=validate_public_person, notNull=False, default=None)
    bug_reporting_guidelines = StringCol(default=None)
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
    bounties = SQLRelatedJoin(
        'Bounty', joinColumn='distribution', otherColumn='bounty',
        intermediateTable='DistributionBounty')
    official_answers = BoolCol(dbName='official_answers', notNull=True,
        default=False)
    official_blueprints = BoolCol(dbName='official_blueprints', notNull=True,
        default=False)
    active = True # Required by IPillar interface.

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

    @property
    def official_codehosting(self):
        # XXX: Aaron Bentley 2008-01-22
        # At this stage, we can't directly associate branches with source
        # packages or anything else resulting in a distribution, so saying
        # that a distribution supports codehosting at this stage makes
        # absolutely no sense at all.
        return False

    official_malone = BoolCol(dbName='official_malone', notNull=True,
        default=False)
    official_rosetta = BoolCol(dbName='official_rosetta', notNull=True,
        default=False)

    @property
    def official_anything(self):
        return True in (self.official_malone, self.official_rosetta,
                        self.official_blueprints, self.official_answers)

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
        return Archive.selectOneBy(distribution=self,
                                   purpose=ArchivePurpose.PRIMARY)

    @cachedproperty
    def all_distro_archives(self):
        """See `IDistribution`."""
        return Archive.select("""
            Distribution = %s AND
            Purpose IN %s""" % sqlvalues(self.id, MAIN_ARCHIVE_PURPOSES)
            )

    @cachedproperty
    def all_distro_archive_ids(self):
        """See `IDistribution`."""
        return [archive.id for archive in self.all_distro_archives]

    def getArchiveIDList(self, archive=None):
        """See `IDistribution`."""
        if archive is None:
            return self.all_distro_archive_ids
        else:
            return [archive.id]

    @property
    def all_milestones(self):
        """See `IDistribution`."""
        return Milestone.selectBy(
            distribution=self, orderBy=['-dateexpected', 'name'])

    @property
    def milestones(self):
        """See `IDistribution`."""
        return Milestone.selectBy(
            distribution=self, visible=True,
            orderBy=['-dateexpected', 'name'])

    @property
    def archive_mirrors(self):
        """See `IDistribution`."""
        return DistributionMirror.selectBy(
            distribution=self, content=MirrorContent.ARCHIVE, enabled=True,
            status=MirrorStatus.OFFICIAL, official_candidate=True)

    @property
    def cdimage_mirrors(self):
        """See `IDistribution`."""
        return DistributionMirror.selectBy(
            distribution=self, content=MirrorContent.RELEASE, enabled=True,
            status=MirrorStatus.OFFICIAL, official_candidate=True)

    @property
    def disabled_mirrors(self):
        """See `IDistribution`."""
        return DistributionMirror.selectBy(
            distribution=self, status=MirrorStatus.OFFICIAL,
            official_candidate=True, enabled=False)

    @property
    def unofficial_mirrors(self):
        """See `IDistribution`."""
        return DistributionMirror.selectBy(
            distribution=self, status=MirrorStatus.UNOFFICIAL)

    @property
    def pending_review_mirrors(self):
        """See `IDistribution`."""
        return DistributionMirror.selectBy(
            distribution=self, status=MirrorStatus.PENDING_REVIEW,
            official_candidate=True)

    @property
    def full_functionality(self):
        """See `IDistribution`."""
        if self == getUtility(ILaunchpadCelebrities).ubuntu:
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
    def is_read_only(self):
        """See `IDistribution`."""
        return self.name in ['debian', 'redhat', 'gentoo']

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

    # XXX: 2008-01-29 kiko: This is used in a number of places and given it's
    # already listified, why not spare the trouble of regenerating this as a
    # cachedproperty? Answer: because it breaks tests.
    @property
    def serieses(self):
        """See `IDistribution`."""
        ret = DistroSeries.selectBy(distribution=self)
        return sorted(ret, key=lambda a: Version(a.version), reverse=True)

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
        return DistributionMirror.selectOneBy(distribution=self, name=name)

    def newMirror(self, owner, speed, country, content, displayname=None,
                  description=None, http_base_url=None, ftp_base_url=None,
                  rsync_base_url=None, official_candidate=False,
                  enabled=False):
        """See `IDistribution`."""
        # NB this functionality is only available to distributions that have
        # the full functionality of Launchpad enabled. This is Ubuntu and
        # commercial derivatives that have been specifically given this
        # ability
        if not self.full_functionality:
            return None

        url = http_base_url or ftp_base_url
        assert url is not None, (
            "A mirror must provide either an HTTP or FTP URL (or both).")
        dummy, host, dummy, dummy, dummy, dummy = urlparse(url)
        name = sanitize_name('%s-%s' % (host, content.name.lower()))

        orig_name = name
        count = 1
        while DistributionMirror.selectOneBy(name=name) is not None:
            count += 1
            name = '%s%s' % (orig_name, count)

        return DistributionMirror(
            distribution=self, owner=owner, name=name, speed=speed,
            country=country, content=content, displayname=displayname,
            description=description, http_base_url=http_base_url,
            ftp_base_url=ftp_base_url, rsync_base_url=rsync_base_url,
            official_candidate=official_candidate, enabled=enabled)

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

        serieses = self.serieses
        # If we have a frozen one, return that.
        for series in serieses:
            if series.status == DistroSeriesStatus.FROZEN:
                return series
        # If we have one in development, return that.
        for series in serieses:
            if series.status == DistroSeriesStatus.DEVELOPMENT:
                return series
        # If we have a stable one, return that.
        for series in serieses:
            if series.status == DistroSeriesStatus.CURRENT:
                return series
        # If we have ANY, return the first one.
        if len(serieses) > 0:
            return serieses[0]
        return None

    def __getitem__(self, name):
        for series in self.serieses:
            if series.name == name:
                return series
        raise NotFoundError(name)

    def __iter__(self):
        return iter(self.serieses)

    @property
    def bugCounter(self):
        """See `IDistribution`."""
        counts = []

        severities = [BugTaskStatus.NEW,
                      BugTaskStatus.CONFIRMED,
                      BugTaskStatus.INVALID,
                      BugTaskStatus.FIXRELEASED]

        querystr = ("BugTask.distribution = %s AND "
                 "BugTask.status = %s")

        for severity in severities:
            query = querystr % sqlvalues(self.id, severity.value)
            count = BugTask.select(query).count()
            counts.append(count)

        return counts

    def getSeries(self, name_or_version):
        """See `IDistribution`."""
        distroseries = DistroSeries.selectOneBy(
            distribution=self, name=name_or_version)
        if distroseries is None:
            distroseries = DistroSeries.selectOneBy(
                distribution=self, version=name_or_version)
            if distroseries is None:
                raise NotFoundError(name_or_version)
        return distroseries

    def getDevelopmentSerieses(self):
        """See `IDistribution`."""
        return DistroSeries.selectBy(
            distribution=self,
            status=DistroSeriesStatus.DEVELOPMENT)

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
        completeness =  Specification.completeness_clause

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

    def ensureRelatedBounty(self, bounty):
        """See `IDistribution`."""
        for curr_bounty in self.bounties:
            if bounty.id == curr_bounty.id:
                return None
        DistributionBounty(distribution=self, bounty=bounty)

    def getDistroSeriesAndPocket(self, distroseries_name):
        """See `IDistribution`."""
        from canonical.archivepublisher.publishing import suffixpocket

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
                        user=None):
        """See `IHasBuildRecords`"""
        # Ignore "user", since it would not make any difference to the
        # records returned here (private builds are only in PPA right
        # now).

        # Find out the distroarchseries in question.
        arch_ids = []
        # Concatenate architectures list since they are distinct.
        for series in self.serieses:
            arch_ids += [arch.id for arch in series.architectures]

        # Use the facility provided by IBuildSet to retrieve the records.
        return getUtility(IBuildSet).getBuildsByArchIds(
            arch_ids, build_state, name, pocket)

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
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id AND
            SourcePackagePublishingHistory.dateremoved is NULL
            """ % sqlvalues(self, archive),
            distinct=True,
            clauseTables=['SourcePackagePublishingHistory', 'DistroSeries',
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
                BinaryPackageRelease.build = Build.id AND
                Build.sourcepackagerelease = %s
                """ % sqlvalues(spr.id),
                clauseTables=['Build'])
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

    def searchSourcePackages(self, text):
        """See `IDistribution`."""
        # The query below tries exact matching on the source package
        # name as well; this is because source package names are
        # notoriously bad for fti matching -- they can contain dots, or
        # be short like "at", both things which users do search for.
        store = Store.of(self)
        find_spec = (
            DistributionSourcePackageCache,
            SourcePackageName,
            SQL('rank(fti, ftq(%s)) AS rank' % sqlvalues(text))
            )
        origin = [
            DistributionSourcePackageCache,
            Join(
                SourcePackageName,
                DistributionSourcePackageCache.sourcepackagename ==
                    SourcePackageName.id
                )
            ]

        # Note: When attempting to convert the query below into straight
        # Storm expressions, a 'tuple index out-of-range' error was always
        # raised.
        dsp_caches = store.using(*origin).find(
            find_spec,
            """distribution = %s AND
            archive IN %s AND
            (fti @@ ftq(%s) OR
             DistributionSourcePackageCache.name ILIKE '%%' || %s || '%%')
            """ % (quote(self), quote(self.all_distro_archive_ids),
                   quote(text), quote_like(text))
            ).order_by('rank DESC')

        # Create a function that will decorate the results, converting
        # them from the find_spec above into DSPs:
        def result_to_dsp((cache, source_package_name, rank)):
            return DistributionSourcePackage(
                self,
                source_package_name
                )

        # Return the decorated result set so the consumer of these
        # results will only see DSPs
        return DecoratedResultSet(dsp_caches, result_to_dsp)

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
                publishedpackage = PublishedPackage.selectFirst('''
                    PublishedPackage.sourcepackagename = %s AND
                    PublishedPackage.binarypackagename = %s AND
                    PublishedPackage.distribution = %s AND
                    PublishedPackage.archive IN %s
                    ''' % sqlvalues(sourcepackagename.name,
                                    sourcepackagename.name,
                                    self,
                                    self.all_distro_archive_ids),
                    orderBy=['-id'])
                if publishedpackage is not None:
                    binarypackagename = BinaryPackageName.byName(
                        publishedpackage.binarypackagename)
                    return (sourcepackagename, binarypackagename)
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
            publishing = PublishedPackage.selectFirst('''
                PublishedPackage.binarypackagename = %s AND
                PublishedPackage.distribution = %s AND
                PublishedPackage.archive IN %s
                ''' % sqlvalues(binarypackagename.name,
                                self,
                                self.all_distro_archive_ids),
                orderBy=['-id'])
            if publishing is not None:
                sourcepackagename = SourcePackageName.byName(
                                        publishing.sourcepackagename)
                return (sourcepackagename, binarypackagename)

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
        return Archive.selectBy(
            purpose=ArchivePurpose.PPA, distribution=self, orderBy=['id'])

    def searchPPAs(self, text=None, show_inactive=False, user=None):
        """See `IDistribution`."""
        clauses = ["""
        Archive.purpose = %s AND
        Archive.distribution = %s AND
        Person.id = Archive.owner
        """ % sqlvalues(ArchivePurpose.PPA, self)]

        clauseTables = ['Person']
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
                (Archive.private = FALSE OR
                 Archive.owner = %s OR
                 %s IN (SELECT TeamParticipation.person
                        FROM TeamParticipation
                        WHERE TeamParticipation.person = %s AND
                              TeamParticipation.team = Archive.owner)
                )
                """ % sqlvalues(user, user, user))
        else:
            clauses.append("Archive.private = FALSE")


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

        return src_archives.union(bin_archives)

    def getArchiveByComponent(self, component_name):
        """See `IDistribution`."""
        # XXX Julian 2007-08-16
        # These component names should be Soyuz-wide constants.
        componentMapToArchivePurpose = {
            'main' : ArchivePurpose.PRIMARY,
            'restricted' : ArchivePurpose.PRIMARY,
            'universe' : ArchivePurpose.PRIMARY,
            'multiverse' : ArchivePurpose.PRIMARY,
            'partner' : ArchivePurpose.PARTNER,
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
            excluded_packages = [
                'apport',
                'casper',
                'displayconfig-gtk',
                'gnome-app-install',
                'software-properties',
                'synaptic',
                'ubiquity',
                'ubuntu-meta',
                'update-manager',
                'usplash',
                ]
        else:
            excluded_packages = []

        return excluded_packages

    def getPackagesAndPublicUpstreamBugCounts(self, limit=50,
                                              exclude_packages=None):
        """See `IDistribution`."""
        from canonical.launchpad.database.product import Product

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
                  RelatedBugTask.bug END) AS bugs_with_upstream_bugwatch
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
                           "development_focus.user_branch",
                           "development_focus.import_branch"]))

        # Okay, we have all the information good to go, so assemble it
        # in a reasonable data structure.
        results = []
        for (spn_id, spn_name, open_bugs, bugs_triaged,
             bugs_affecting_upstream, bugs_with_upstream_bugwatch) in counts:
            sourcepackagename = SourcePackageName.get(spn_id)
            dsp = self.getSourcePackage(sourcepackagename)
            if spn_id in sources_to_products:
                product_id = sources_to_products[spn_id]
                product = Product.get(product_id)
            else:
                product = None
            results.append(
                (dsp, product, open_bugs, bugs_triaged,
                 bugs_affecting_upstream, bugs_with_upstream_bugwatch))
        return results

    def getCustomLanguageCode(self, sourcepackagename, language_code):
        """See `IDistribution`."""
        return CustomLanguageCode.selectOneBy(
            distribution=self, sourcepackagename=sourcepackagename,
            language_code=language_code)

    def setBugSupervisor(self, bug_supervisor, user):
        """See `IHasBugSupervisor`."""
        self.bug_supervisor = bug_supervisor
        if bug_supervisor is not None:
            subscription = self.addBugSubscription(bug_supervisor, user)

    def userCanEdit(self, user):
        """See `IDistribution`."""
        if user is None:
            return False
        admins = getUtility(ILaunchpadCelebrities).admin
        return user.inTeam(self.owner) or user.inTeam(admins)

    def newSeries(self, name, displayname, title, summary,
                  description, version, parent_series, owner):
        """See `IDistribution`."""
        return DistroSeries(
            distribution=self,
            name=name,
            displayname=displayname,
            title=title,
            summary=summary,
            description=description,
            version=version,
            status=DistroSeriesStatus.EXPERIMENTAL,
            parent_series=parent_series,
            owner=owner)


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
        archive = getUtility(IArchiveSet).new(distribution=distro,
            owner=owner, purpose=ArchivePurpose.PRIMARY)
        return distro
