# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212
"""Database classes that implement SourcePacakge items."""

__metaclass__ = type

__all__ = [
    'SourcePackage',
    'SourcePackageQuestionTargetMixin',
    ]

from operator import attrgetter
from sqlobject.sqlbuilder import SQLConstant
from zope.interface import classProvides, implements
from zope.component import getUtility

from storm.locals import And, Desc, In, Select, SQL, Store

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import flush_database_updates, sqlvalues
from canonical.lazr.utils import smartquote
from lp.code.model.branch import Branch
from lp.code.model.hasbranches import HasBranchesMixin, HasMergeProposalsMixin
from lp.bugs.model.bug import get_bug_tags_open_count
from lp.bugs.model.bugtarget import BugTargetBase
from lp.bugs.model.bugtask import BugTask
from lp.soyuz.interfaces.archive import IArchiveSet, ArchivePurpose
from lp.soyuz.model.build import Build, BuildSet
from lp.soyuz.model.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease)
from lp.soyuz.model.distroseriessourcepackagerelease import (
    DistroSeriesSourcePackageRelease)
from lp.registry.model.packaging import Packaging
from lp.translations.model.potemplate import (
    HasTranslationTemplatesMixin,
    POTemplate)
from canonical.launchpad.interfaces.lpstorm import IStore
from lp.soyuz.model.publishing import (
    SourcePackagePublishingHistory)
from lp.answers.model.question import (
    QuestionTargetMixin, QuestionTargetSearch)
from lp.code.model.seriessourcepackagebranch import (
    SeriesSourcePackageBranch)
from lp.soyuz.model.sourcepackagerelease import (
    SourcePackageRelease)
from lp.translations.model.translationimportqueue import (
    HasTranslationImportsMixin)
from canonical.launchpad.helpers import shortlist
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.registry.interfaces.packaging import PackagingType
from lp.translations.interfaces.potemplate import IHasTranslationTemplates
from lp.registry.interfaces.distribution import NoPartnerArchive
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.interfaces.queue import PackageUploadCustomFormat
from lp.answers.interfaces.questioncollection import (
    QUESTION_STATUS_DEFAULT_SEARCH)
from lp.answers.interfaces.questiontarget import IQuestionTarget
from lp.code.interfaces.seriessourcepackagebranch import (
    IMakeOfficialBranchLinks)
from lp.registry.interfaces.sourcepackage import (
    ISourcePackage, ISourcePackageFactory)
from lp.registry.model.suitesourcepackage import SuiteSourcePackage


class SourcePackageQuestionTargetMixin(QuestionTargetMixin):
    """Implementation of IQuestionTarget for SourcePackage."""

    def getTargetTypes(self):
        """See `QuestionTargetMixin`.

        Defines distribution and sourcepackagename as this object's
        distribution and sourcepackagename.
        """
        return {'distribution': self.distribution,
                'sourcepackagename': self.sourcepackagename}

    def questionIsForTarget(self, question):
        """See `QuestionTargetMixin`.

        Return True when the question's distribution and sourcepackagename
        are this object's distribution and sourcepackagename.
        """
        if question.distribution is not self.distribution:
            return False
        if question.sourcepackagename is not self.sourcepackagename:
            return False
        return True

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
            distribution=self.distribution,
            sourcepackagename=self.sourcepackagename,
            search_text=search_text, status=status,
            language=language, sort=sort, owner=owner,
            needs_attention_from=needs_attention_from,
            unsupported_target=unsupported_target).getResults()

    def getAnswerContactsForLanguage(self, language):
        """See `IQuestionTarget`."""
        # Sourcepackages are supported by their distribtions too.
        persons = self.distribution.getAnswerContactsForLanguage(language)
        persons.update(QuestionTargetMixin.getAnswerContactsForLanguage(
            self, language))
        return sorted(
            [person for person in persons], key=attrgetter('displayname'))

    def getAnswerContactRecipients(self, language):
        """See `IQuestionTarget`."""
        # We need to special case the source package case because some are
        # contacts for the distro while others are only registered for the
        # package. And we also want the name of the package in context in
        # the header.
        recipients = self.distribution.getAnswerContactRecipients(language)
        recipients.update(QuestionTargetMixin.getAnswerContactRecipients(
            self, language))
        return recipients

    @property
    def _store(self):
        return Store.of(self.sourcepackagename)

    @property
    def answer_contacts(self):
        """See `IQuestionTarget`."""
        answer_contacts = set()
        answer_contacts.update(self.direct_answer_contacts)
        answer_contacts.update(self.distribution.answer_contacts)
        return sorted(answer_contacts, key=attrgetter('displayname'))

    @property
    def answer_contacts_with_languages(self):
        """Answer contacts with their languages pre-filled.

        Same as answer_contacts but with each answer contact having its
        languages pre-filled so that we don't need to hit the DB again to get
        them.
        """
        answer_contacts = set()
        answer_contacts.update(self.direct_answer_contacts_with_languages)
        answer_contacts.update(
            self.distribution.answer_contacts_with_languages)
        return sorted(answer_contacts, key=attrgetter('displayname'))


class SourcePackage(BugTargetBase, SourcePackageQuestionTargetMixin,
                    HasTranslationImportsMixin, HasTranslationTemplatesMixin,
                    HasBranchesMixin, HasMergeProposalsMixin):
    """A source package, e.g. apache2, in a distroseries.

    This object is not a true database object, but rather attempts to
    represent the concept of a source package in a distro series, with links
    to the relevant database objects.
    """

    implements(
        ISourcePackage, IHasBuildRecords, IHasTranslationTemplates,
        IQuestionTarget)

    classProvides(ISourcePackageFactory)

    def __init__(self, sourcepackagename, distroseries):
        self.sourcepackagename = sourcepackagename
        self.distroseries = distroseries

    @classmethod
    def new(cls, sourcepackagename, distroseries):
        """See `ISourcePackageFactory`."""
        return cls(sourcepackagename, distroseries)

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.path)

    def _get_ubuntu(self):
        # XXX: kiko 2006-03-20: Ideally, it would be possible to just do
        # ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        # and not need this method. However, importd currently depends
        # on SourcePackage methods that require the ubuntu celebrity,
        # and given it does not execute_zcml_for_scripts, we are forced
        # here to do this hack instead of using components. Ideally,
        # imports is rewritten to not use SourcePackage, or it
        # initializes the component architecture correctly.
        from lp.registry.model.distribution import Distribution
        return Distribution.byName("ubuntu")

    def _getPublishingHistory(self, version=None, include_status=None,
                              exclude_status=None, order_by=None):
        """Build a query and return a list of SourcePackagePublishingHistory.

        This is mainly a helper function for this class so that code is
        not duplicated. include_status and exclude_status must be a sequence.
        """
        clauses = []
        clauses.append(
                """SourcePackagePublishingHistory.sourcepackagerelease =
                   SourcePackageRelease.id AND
                   SourcePackageRelease.sourcepackagename = %s AND
                   SourcePackagePublishingHistory.distroseries = %s AND
                   SourcePackagePublishingHistory.archive IN %s
                """ % sqlvalues(
                        self.sourcepackagename,
                        self.distroseries,
                        self.distribution.all_distro_archive_ids))
        if version:
            clauses.append(
                "SourcePackageRelease.version = %s" % sqlvalues(version))

        if include_status:
            if not isinstance(include_status, list):
                include_status = list(include_status)
            clauses.append("SourcePackagePublishingHistory.status IN %s"
                       % sqlvalues(include_status))

        if exclude_status:
            if not isinstance(exclude_status, list):
                exclude_status = list(exclude_status)
            clauses.append("SourcePackagePublishingHistory.status NOT IN %s"
                       % sqlvalues(exclude_status))

        query = " AND ".join(clauses)

        if not order_by:
            order_by = '-datepublished'

        return SourcePackagePublishingHistory.select(
            query, orderBy=order_by, clauseTables=['SourcePackageRelease'],
            prejoinClauseTables=['SourcePackageRelease'])

    def _getFirstPublishingHistory(self, version=None, include_status=None,
                                   exclude_status=None, order_by=None):
        """As _getPublishingHistory, but just returns the first item."""
        try:
            package = self._getPublishingHistory(
                version, include_status, exclude_status, order_by)[0]
        except IndexError:
            return None
        else:
            return package

    @property
    def currentrelease(self):
        releases = self.distroseries.getCurrentSourceReleases(
            [self.sourcepackagename])
        return releases.get(self)

    def __getitem__(self, version):
        """See `ISourcePackage`."""
        latest_package = self._getFirstPublishingHistory(version=version)
        if latest_package:
            return DistroSeriesSourcePackageRelease(
                    self.distroseries, latest_package.sourcepackagerelease)
        else:
            return None

    @property
    def path(self):
        """See `ISourcePackage`."""
        return '/'.join([
            self.distribution.name,
            self.distroseries.name,
            self.sourcepackagename.name])

    @property
    def displayname(self):
        return "%s in %s %s" % (
            self.sourcepackagename.name, self.distribution.displayname,
            self.distroseries.displayname)

    @property
    def bugtargetdisplayname(self):
        """See IBugTarget."""
        return "%s (%s)" % (self.name, self.distroseries.fullseriesname)

    @property
    def bugtargetname(self):
        """See `IBugTarget`."""
        return "%s (%s)" % (self.name, self.distroseries.fullseriesname)

    @property
    def title(self):
        """See `ISourcePackage`."""
        return smartquote('"%s" source package in %s') % (
            self.sourcepackagename.name, self.distroseries.displayname)

    @property
    def distribution(self):
        return self.distroseries.distribution

    @property
    def format(self):
        if not self.currentrelease:
            return None
        return self.currentrelease.format

    @property
    def releases(self):
        """See `ISourcePackage`."""
        order_const = "debversion_sort_key(SourcePackageRelease.version)"
        packages = self._getPublishingHistory(
            order_by=[SQLConstant(order_const),
                      "SourcePackagePublishingHistory.datepublished"])

        return [DistributionSourcePackageRelease(
                distribution=self.distribution,
                sourcepackagerelease=package.sourcepackagerelease)
                   for package in packages]

    @property
    def distinctreleases(self):
        """Return all distinct `SourcePackageReleases` for this sourcepackage.

        The results are ordered by descending version.
        """
        subselect = Select(
            SourcePackageRelease.id, And(
                SourcePackagePublishingHistory.distroseries ==
                    self.distroseries,
                SourcePackagePublishingHistory.sourcepackagereleaseID ==
                    SourcePackageRelease.id,
                SourcePackageRelease.sourcepackagename ==
                    self.sourcepackagename,
                In(SourcePackagePublishingHistory.archiveID,
                    self.distribution.all_distro_archive_ids)))

        return IStore(SourcePackageRelease).find(
            SourcePackageRelease,
            In(SourcePackageRelease.id, subselect)).order_by(Desc(
                SQL("debversion_sort_key(SourcePackageRelease.version)")))

    @property
    def name(self):
        return self.sourcepackagename.name

    @property
    def productseries(self):
        # See if we can find a relevant packaging record
        packaging = self.direct_packaging
        if packaging is None:
            return None
        return packaging.productseries

    @property
    def direct_packaging(self):
        """See `ISourcePackage`."""
        store = Store.of(self.sourcepackagename)
        return store.find(
            Packaging,
            sourcepackagename=self.sourcepackagename,
            distroseries=self.distroseries).one()

    @property
    def packaging(self):
        """See `ISourcePackage`"""
        # First we look to see if there is packaging data for this
        # distroseries and sourcepackagename. If not, we look up through
        # parent distroseries, and when we hit Ubuntu, we look backwards in
        # time through Ubuntu series till we find packaging information or
        # blow past the Warty Warthog.

        # see if there is a direct packaging
        result = self.direct_packaging
        if result is not None:
            return result

        ubuntu = self._get_ubuntu()
        # if we are an ubuntu sourcepackage, try the previous series of
        # ubuntu
        if self.distribution == ubuntu:
            ubuntuseries = self.distroseries.previous_series
            if ubuntuseries:
                previous_ubuntu_series = ubuntuseries[0]
                sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                                   distroseries=previous_ubuntu_series)
                return sp.packaging
        # if we have a parent distroseries, try that
        if self.distroseries.parent_series is not None:
            sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                               distroseries=self.distroseries.parent_series)
            return sp.packaging
        # capitulate
        return None

    @property
    def published_by_pocket(self):
        """See `ISourcePackage`."""
        result = self._getPublishingHistory(
            include_status=[PackagePublishingStatus.PUBLISHED])
        # create the dictionary with the set of pockets as keys
        thedict = {}
        for pocket in PackagePublishingPocket.items:
            thedict[pocket] = []
        # add all the sourcepackagereleases in the right place
        for spr in result:
            thedict[spr.pocket].append(DistroSeriesSourcePackageRelease(
                spr.distroseries, spr.sourcepackagerelease))
        return thedict

    @property
    def development_version(self):
        """See `ISourcePackage`."""
        return self.__class__(
            self.sourcepackagename, self.distribution.currentseries)

    @property
    def distribution_sourcepackage(self):
        """See `ISourcePackage`."""
        return self.distribution.getSourcePackage(self.sourcepackagename)

    @property
    def bug_reporting_guidelines(self):
        """See `IBugTarget`."""
        return self.distribution.bug_reporting_guidelines

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for this source package."""
        search_params.setSourcePackage(self)

    @property
    def official_bug_tags(self):
        """See `IHasBugs`."""
        return self.distroseries.official_bug_tags

    def getUsedBugTags(self):
        """See `IBugTarget`."""
        return self.distroseries.getUsedBugTags()

    def getUsedBugTagsWithOpenCounts(self, user):
        """See `IBugTarget`."""
        return get_bug_tags_open_count(
            And(BugTask.distroseries == self.distroseries,
                BugTask.sourcepackagename == self.sourcepackagename),
            user)

    @property
    def max_bug_heat(self):
        """See `IHasBugs`."""
        return self.distribution_sourcepackage.max_bug_heat

    def createBug(self, bug_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        # We don't currently support opening a new bug directly on an
        # ISourcePackage, because internally ISourcePackage bugs mean bugs
        # targeted to be fixed in a specific distroseries + sourcepackage.
        raise NotImplementedError(
            "A new bug cannot be filed directly on a source package in a "
            "specific distribution series, because series are meant for "
            "\"targeting\" a fix to a specific series. It's possible that "
            "we may change this behaviour to allow filing a bug on a "
            "distribution series source package in the not-too-distant "
            "future. For now, you probably meant to file the bug on the "
            "distro-wide (i.e. not series-specific) source package.")

    def _getBugTaskContextClause(self):
        """See BugTargetBase."""
        return (
            'BugTask.distroseries = %s AND BugTask.sourcepackagename = %s' %
                sqlvalues(self.distroseries, self.sourcepackagename))

    def setPackaging(self, productseries, user):
        target = self.direct_packaging
        if target is not None:
            # we should update the current packaging
            target.productseries = productseries
            target.owner = user
            target.datecreated = UTC_NOW
        else:
            # ok, we need to create a new one
            Packaging(distroseries=self.distroseries,
            sourcepackagename=self.sourcepackagename,
            productseries=productseries, owner=user,
            packaging=PackagingType.PRIME)
        # and make sure this change is immediately available
        flush_database_updates()

    def __hash__(self):
        """See `ISourcePackage`."""
        return hash(self.distroseries.id) ^ hash(self.sourcepackagename.id)

    def __eq__(self, other):
        """See `ISourcePackage`."""
        return (
            (ISourcePackage.providedBy(other)) and
            (self.distroseries.id == other.distroseries.id) and
            (self.sourcepackagename.id == other.sourcepackagename.id))

    def __ne__(self, other):
        """See `ISourcePackage`."""
        return not self.__eq__(other)

    def getBuildRecords(self, build_state=None, name=None, pocket=None,
                        arch_tag=None, user=None):
        # Ignore "user", since it would not make any difference to the
        # records returned here (private builds are only in PPA right
        # now and this method only returns records for SPRs in a
        # distribution).
        # We also ignore the name parameter (required as part of the
        # IHasBuildRecords interface) and use our own name.

        """See `IHasBuildRecords`"""
        clauseTables = ['SourcePackageRelease',
                        'SourcePackagePublishingHistory']

        condition_clauses = ["""
        Build.sourcepackagerelease = SourcePackageRelease.id AND
        SourcePackageRelease.sourcepackagename = %s AND
        SourcePackagePublishingHistory.distroseries = %s AND
        SourcePackagePublishingHistory.archive IN %s AND
        SourcePackagePublishingHistory.sourcepackagerelease =
            SourcePackageRelease.id AND
        SourcePackagePublishingHistory.archive = Build.archive
        """ % sqlvalues(self.sourcepackagename,
                        self.distroseries,
                        self.distribution.all_distro_archive_ids)]

        # We re-use the optional-parameter handling provided by BuildSet
        # here, but pass None for the name argument as we've already
        # matched on exact source package name.
        BuildSet().handleOptionalParamsForBuildQueries(
            condition_clauses, clauseTables, build_state, name=None,
            pocket=pocket, arch_tag=arch_tag)

        # exclude gina-generated and security (dak-made) builds
        # buildstate == FULLYBUILT && datebuilt == null
        condition_clauses.append(
            "NOT (Build.buildstate=%s AND Build.datebuilt is NULL)"
            % sqlvalues(BuildStatus.FULLYBUILT))

        # Ordering according status
        # * NEEDSBUILD & BUILDING by -lastscore
        # * SUPERSEDED by -datecreated
        # * FULLYBUILT & FAILURES by -datebuilt
        # It should present the builds in a more natural order.
        if build_state in [BuildStatus.NEEDSBUILD, BuildStatus.BUILDING]:
            orderBy = ["-BuildQueue.lastscore"]
            clauseTables.append('BuildPackageJob')
            condition_clauses.append('BuildPackageJob.build = Build.id')
            clauseTables.append('BuildQueue')
            condition_clauses.append('BuildQueue.job = BuildPackageJob.job')
        elif build_state == BuildStatus.SUPERSEDED or build_state is None:
            orderBy = ["-Build.datecreated"]
        else:
            orderBy = ["-Build.datebuilt"]

        # Fallback to ordering by -id as a tie-breaker.
        orderBy.append("-id")

        # End of duplication (see XXX cprov 2006-09-25 above).

        return Build.select(' AND '.join(condition_clauses),
                            clauseTables=clauseTables, orderBy=orderBy)

    @property
    def latest_published_component(self):
        """See `ISourcePackage`."""
        latest_publishing = self._getFirstPublishingHistory(
            include_status=[PackagePublishingStatus.PUBLISHED])
        if latest_publishing is not None:
            return latest_publishing.component
        else:
            return None

    def get_default_archive(self, component=None):
        """See `ISourcePackage`."""
        if component is None:
            component = self.latest_published_component
        distribution = self.distribution
        if component is not None and component.name == 'partner':
            archive = getUtility(IArchiveSet).getByDistroPurpose(
                distribution, ArchivePurpose.PARTNER)
            if archive is None:
                raise NoPartnerArchive(distribution)
            else:
                return archive
        else:
            return distribution.main_archive

    def getTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.selectBy(
            distroseries=self.distroseries,
            sourcepackagename=self.sourcepackagename)
        return shortlist(result.orderBy(['-priority', 'name']), 300)

    def getCurrentTranslationTemplates(self, just_ids=False):
        """See `IHasTranslationTemplates`."""
        store = Store.of(self.sourcepackagename)
        if just_ids:
            looking_for = POTemplate.id
        else:
            looking_for = POTemplate

        result = store.find(looking_for, And(
            POTemplate.iscurrent == True,
            POTemplate.distroseries == self.distroseries,
            POTemplate.sourcepackagename == self.sourcepackagename,
            self.distroseries.distribution.official_rosetta == True))
        return result.order_by(['-POTemplate.priority', 'POTemplate.name'])

    def getObsoleteTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.select('''
            distroseries = %s AND
            sourcepackagename = %s AND
            distroseries = DistroSeries.id AND
            DistroSeries.distribution = Distribution.id AND
            (iscurrent IS FALSE OR Distribution.official_rosetta IS FALSE)
            ''' % sqlvalues(self.distroseries, self.sourcepackagename),
            clauseTables = ['DistroSeries', 'Distribution'])
        return shortlist(result.orderBy(['-priority', 'name']), 300)

    def getBranch(self, pocket):
        """See `ISourcePackage`."""
        store = Store.of(self.sourcepackagename)
        return store.find(
            Branch,
            SeriesSourcePackageBranch.distroseries == self.distroseries.id,
            (SeriesSourcePackageBranch.sourcepackagename
             == self.sourcepackagename.id),
            SeriesSourcePackageBranch.pocket == pocket,
            SeriesSourcePackageBranch.branch == Branch.id).one()

    def setBranch(self, pocket, branch, registrant):
        """See `ISourcePackage`."""
        series_set = getUtility(IMakeOfficialBranchLinks)
        series_set.delete(self, pocket)
        if branch is not None:
            series_set.new(
                self.distroseries, pocket, self.sourcepackagename, branch,
                registrant)

    @property
    def linked_branches(self):
        """See `ISourcePackage`."""
        store = Store.of(self.sourcepackagename)
        return store.find(
            (SeriesSourcePackageBranch.pocket, Branch),
            SeriesSourcePackageBranch.distroseries == self.distroseries.id,
            (SeriesSourcePackageBranch.sourcepackagename
             == self.sourcepackagename.id),
            SeriesSourcePackageBranch.branch == Branch.id).order_by(
                SeriesSourcePackageBranch.pocket)

    def getSuiteSourcePackage(self, pocket):
        """See `ISourcePackage`."""
        return SuiteSourcePackage(
            self.distroseries, pocket, self.sourcepackagename)

    def getPocketPath(self, pocket):
        """See `ISourcePackage`."""
        return '%s/%s/%s' % (
            self.distribution.name,
            self.distroseries.getSuite(pocket),
            self.name)

    def getLatestTranslationsUploads(self):
        """See `ISourcePackage`."""
        our_format = PackageUploadCustomFormat.ROSETTA_TRANSLATIONS

        packagename = self.sourcepackagename.name
        displayname = self.displayname
        distro = self.distroseries.distribution

        histories = distro.main_archive.getPublishedSources(
            name=packagename, distroseries=self.distroseries,
            status=PackagePublishingStatus.PUBLISHED, exact_match=True)
        histories = list(histories)

        builds = []
        for history in histories:
            builds += list(history.getBuilds())

        uploads = [
            build.package_upload
            for build in builds
            if build.package_upload]
        custom_files = []
        for upload in uploads:
            custom_files += [
                custom for custom in upload.customfiles
                if custom.customformat == our_format]

        custom_files.sort(key=attrgetter('id'))
        return [custom.libraryfilealias for custom in custom_files]

    def linkedBranches(self):
        """See `ISourcePackage`."""
        return dict((p.name, b) for (p, b) in self.linked_branches)
