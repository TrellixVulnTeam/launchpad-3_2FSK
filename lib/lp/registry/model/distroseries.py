# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""Database classes for a distribution series."""

__metaclass__ = type

__all__ = [
    'DistroSeries',
    'DistroSeriesSet',
    'SeriesMixin',
    ]

import logging
from cStringIO import StringIO

from sqlobject import (
    BoolCol, StringCol, ForeignKey, SQLMultipleJoin, IntCol,
    SQLObjectNotFound, SQLRelatedJoin)

from storm.locals import And, Desc, Int, Join, SQL
from storm.store import Store

from zope.component import getUtility
from zope.interface import implements

from canonical.cachedproperty import cachedproperty

from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    cursor, flush_database_caches, flush_database_updates, quote_like,
    quote, SQLBase, sqlvalues)
from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet)
from lp.translations.model.pofiletranslator import (
    POFileTranslator)
from lp.translations.model.pofile import POFile
from canonical.launchpad.interfaces.lpstorm import IStore
from lp.soyuz.adapters.packagelocation import PackageLocation
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import (
        BinaryPackageRelease)
from lp.bugs.model.bug import (
    get_bug_tags, get_bug_tags_open_count)
from lp.bugs.model.bugtarget import BugTargetBase
from lp.bugs.model.bugtask import BugTask
from lp.bugs.interfaces.bugtask import UNRESOLVED_BUGTASK_STATUSES
from lp.soyuz.model.component import Component
from lp.soyuz.model.distroarchseries import (
    DistroArchSeries, DistroArchSeriesSet, PocketChroot)
from lp.soyuz.model.distroseriesbinarypackage import (
    DistroSeriesBinaryPackage)
from lp.translations.model.distroserieslanguage import (
    DistroSeriesLanguage, DummyDistroSeriesLanguage)
from lp.soyuz.model.distroseriespackagecache import (
    DistroSeriesPackageCache)
from lp.soyuz.model.distroseriessourcepackagerelease import (
    DistroSeriesSourcePackageRelease)
from lp.translations.model.distroseries_translations_copy import (
    copy_active_translations)
from lp.services.worlddata.model.language import Language
from lp.translations.model.languagepack import LanguagePack
from lp.registry.model.milestone import (
    HasMilestonesMixin, Milestone)
from lp.soyuz.model.packagecloner import clone_packages
from lp.registry.model.packaging import Packaging
from lp.registry.model.person import Person
from canonical.launchpad.database.librarian import LibraryFileAlias
from lp.translations.model.potemplate import (
    HasTranslationTemplatesMixin,
    POTemplate)
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory, SourcePackagePublishingHistory)
from lp.soyuz.model.queue import PackageUpload, PackageUploadQueue
from lp.soyuz.model.section import Section
from lp.registry.interfaces.pocket import (
    PackagePublishingPocket, pocketsuffix)
from lp.registry.model.sourcepackage import SourcePackage
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.soyuz.model.sourcepackagerelease import (
    SourcePackageRelease)
from lp.blueprints.model.specification import (
    HasSpecificationsMixin, Specification)
from lp.translations.model.translationimportqueue import (
    HasTranslationImportsMixin)
from lp.registry.model.structuralsubscription import (
    StructuralSubscriptionTargetMixin)
from canonical.launchpad.helpers import shortlist
from lp.soyuz.interfaces.archive import (
    ALLOW_RELEASE_BUILDS, ArchivePurpose, IArchiveSet, MAIN_ARCHIVE_PURPOSES)
from lp.soyuz.interfaces.build import IBuildSet
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.soyuz.interfaces.binarypackagename import (
    IBinaryPackageName)
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.distroseries import (
    IDistroSeries, IDistroSeriesSet, ISeriesMixin)
from lp.translations.interfaces.languagepack import LanguagePackType
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from lp.soyuz.interfaces.queue import PackageUploadStatus
from lp.translations.interfaces.potemplate import IHasTranslationTemplates
from lp.soyuz.interfaces.publishedpackage import (
    IPublishedPackageSet)
from lp.soyuz.interfaces.publishing import (
    active_publishing_status, ICanPublishPackages, PackagePublishingStatus)
from lp.soyuz.interfaces.queue import IHasQueueItems, IPackageUploadSet
from lp.registry.interfaces.sourcepackage import (
    ISourcePackage, ISourcePackageFactory)
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageName, ISourcePackageNameSet)
from lp.blueprints.interfaces.specification import (
    SpecificationFilter, SpecificationGoalStatus,
    SpecificationImplementationStatus, SpecificationSort)
from canonical.launchpad.mail import signed_message_from_string
from lp.registry.interfaces.person import validate_public_person
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, NotFoundError, SLAVE_FLAVOR,
    TranslationUnavailable)
from lp.soyuz.interfaces.sourcepackageformat import (
    ISourcePackageFormatSelectionSet)


class SeriesMixin:
    """See `ISeriesMixin`."""
    implements(ISeriesMixin)

    @property
    def active(self):
        return self.status in [
            SeriesStatus.DEVELOPMENT,
            SeriesStatus.FROZEN,
            SeriesStatus.CURRENT,
            SeriesStatus.SUPPORTED
            ]


class DistroSeries(SQLBase, BugTargetBase, HasSpecificationsMixin,
                   HasTranslationImportsMixin, HasTranslationTemplatesMixin,
                   HasMilestonesMixin, SeriesMixin,
                   StructuralSubscriptionTargetMixin):
    """A particular series of a distribution."""
    implements(
        ICanPublishPackages, IDistroSeries, IHasBuildRecords, IHasQueueItems,
        IHasTranslationTemplates)

    _table = 'DistroSeries'
    _defaultOrder = ['distribution', 'version']

    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=True)
    name = StringCol(notNull=True)
    displayname = StringCol(notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    description = StringCol(notNull=True)
    version = StringCol(notNull=True)
    status = EnumCol(
        dbName='releasestatus', notNull=True, schema=SeriesStatus)
    date_created = UtcDateTimeCol(notNull=False, default=UTC_NOW)
    datereleased = UtcDateTimeCol(notNull=False, default=None)
    parent_series =  ForeignKey(
        dbName='parent_series', foreignKey='DistroSeries', notNull=False)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    driver = ForeignKey(
        dbName="driver", foreignKey="Person",
        storm_validator=validate_public_person, notNull=False, default=None)
    lucilleconfig = StringCol(notNull=False, default=None)
    changeslist = StringCol(notNull=False, default=None)
    nominatedarchindep = ForeignKey(
        dbName='nominatedarchindep',foreignKey='DistroArchSeries',
        notNull=False, default=None)
    messagecount = IntCol(notNull=True, default=0)
    binarycount = IntCol(notNull=True, default=DEFAULT)
    sourcecount = IntCol(notNull=True, default=DEFAULT)
    defer_translation_imports = BoolCol(notNull=True, default=True)
    hide_all_translations = BoolCol(notNull=True, default=True)
    language_pack_base = ForeignKey(
        foreignKey="LanguagePack", dbName="language_pack_base", notNull=False,
        default=None)
    language_pack_delta = ForeignKey(
        foreignKey="LanguagePack", dbName="language_pack_delta",
        notNull=False, default=None)
    language_pack_proposed = ForeignKey(
        foreignKey="LanguagePack", dbName="language_pack_proposed",
        notNull=False, default=None)
    language_pack_full_export_requested = BoolCol(notNull=True, default=False)

    language_packs = SQLMultipleJoin(
        'LanguagePack', joinColumn='distroseries', orderBy='-date_exported')
    sections = SQLRelatedJoin(
        'Section', joinColumn='distroseries', otherColumn='section',
        intermediateTable='SectionSelection')
    max_heat = Int(allow_none=False, default=0)

    @property
    def named_version(self):
        return '%s (%s)' % (self.displayname, self.version)

    @property
    def upload_components(self):
        """See `IDistroSeries`."""
        return Component.select("""
            ComponentSelection.distroseries = %s AND
            Component.id = ComponentSelection.component
            """ % self.id,
            clauseTables=["ComponentSelection"])

    @property
    def components(self):
        """See `IDistroSeries`."""
        # XXX julian 2007-06-25
        # This is filtering out the partner component for now, until
        # the second stage of the partner repo arrives in 1.1.8.
        return Component.select("""
            ComponentSelection.distroseries = %s AND
            Component.id = ComponentSelection.component AND
            Component.name != 'partner'
            """ % self.id,
            clauseTables=["ComponentSelection"])

    # DistroArchSeries lookup properties/methods.
    architectures = SQLMultipleJoin(
        'DistroArchSeries', joinColumn='distroseries',
        orderBy='architecturetag')

    def __getitem__(self, archtag):
        """See `IDistroSeries`."""
        return self.getDistroArchSeries(archtag)

    def getDistroArchSeries(self, archtag):
        """See `IDistroSeries`."""
        item = DistroArchSeries.selectOneBy(
            distroseries=self, architecturetag=archtag)
        if item is None:
            raise NotFoundError('Unknown architecture %s for %s %s' % (
                archtag, self.distribution.name, self.name))
        return item

    def getDistroArchSeriesByProcessor(self, processor):
        """See `IDistroSeries`."""
        # XXX: JRV 2010-01-14: This should ideally use storm to find the
        # distroarchseries rather than iterating over all of them, but
        # I couldn't figure out how to do that - and a trivial for loop
        # isn't expensive given there's generally less than a dozen
        # architectures.
        for architecture in self.architectures:
            if architecture.processorfamily == processor.family:
                return architecture
        return None

    @property
    def enabled_architectures(self):
        store = Store.of(self)
        origin = [
            DistroArchSeries,
            Join(PocketChroot,
                 PocketChroot.distroarchseries == DistroArchSeries.id),
            Join(LibraryFileAlias,
                 PocketChroot.chroot == LibraryFileAlias.id),
            ]
        results = store.using(*origin).find(
            DistroArchSeries,
            DistroArchSeries.distroseries == self)
        return results.order_by(DistroArchSeries.architecturetag)

    @property
    def virtualized_architectures(self):
        store = Store.of(self)
        results = store.find(
            DistroArchSeries,
            DistroArchSeries.distroseries == self,
            DistroArchSeries.supports_virtualized == True)
        return results.order_by(DistroArchSeries.architecturetag)
    # End of DistroArchSeries lookup methods

    @property
    def parent(self):
        """See `IDistroSeries`."""
        return self.distribution

    @property
    def drivers(self):
        """See `IDistroSeries`."""
        drivers = set()
        drivers.add(self.driver)
        drivers = drivers.union(self.distribution.drivers)
        drivers.discard(None)
        return sorted(drivers, key=lambda driver: driver.displayname)

    @property
    def bug_supervisor(self):
        """See `IDistroSeries`."""
        return self.distribution.bug_supervisor

    @property
    def security_contact(self):
        """See `IDistroSeries`."""
        return self.distribution.security_contact

    @property
    def sortkey(self):
        """A string to be used for sorting distro seriess.

        This is designed to sort alphabetically by distro and series name,
        except that Ubuntu will be at the top of the listing.
        """
        result = ''
        if self.distribution.name == 'ubuntu':
            result += '-'
        result += self.distribution.name + self.name
        return result

    @cachedproperty
    def _all_packagings(self):
        """Get an unordered list of all packagings."""
        # We join to SourcePackageName, ProductSeries, and Product to cache
        # the objects that are implicitly needed to work with a
        # Packaging object.
        # Avoid circular import failures.
        from lp.registry.model.product import Product
        from lp.registry.model.productseries import ProductSeries
        find_spec = (Packaging, SourcePackageName, ProductSeries, Product)
        origin = [
            Packaging,
            Join(
                SourcePackageName,
                Packaging.sourcepackagename == SourcePackageName.id),
            Join(
                ProductSeries,
                Packaging.productseries == ProductSeries.id),
            Join(
                Product,
                ProductSeries.product == Product.id)]
        condition = Packaging.distroseries == self.id
        results = IStore(self).using(*origin).find(find_spec, condition)
        return results

    @property
    def packagings(self):
        """See `IDistroSeries`."""
        results = self._all_packagings
        results = results.order_by(SourcePackageName.name)
        return [
            packaging
            for (packaging, spn, product_series, product) in results]

    def getPrioritizedUnlinkedSourcePackages(self):
        """See `IDistroSeries`.

        The prioritization is a heuristic rule using bug heat,
        translatable messages, and the source package release's component.
        """
        find_spec = (
            SourcePackageName,
            SQL("""
                coalesce(total_heat, 0) + coalesce(po_messages, 0) +
                CASE WHEN spr.component = 1 THEN 1000 ELSE 0 END AS score"""),
            SQL("coalesce(total_bugs, 0) AS total_bugs"),
            SQL("coalesce(total_messages, 0) AS total_messages"))
        joins, conditions = self._current_sourcepackage_joins_and_conditions
        origin = SQL(joins)
        condition = SQL(conditions + "AND packaging.id IS NULL")
        results = IStore(self).using(origin).find(find_spec, condition)
        results = results.order_by('score DESC')
        return [{
                 'package': SourcePackage(
                    sourcepackagename=spn, distroseries=self),
                 'total_bugs': total_bugs,
                 'total_messages': total_messages}
                for (spn, score, total_bugs, total_messages) in results]

    def getPrioritizedlPackagings(self):
        """See `IDistroSeries`.

        The prioritization is a heuristic rule using the branch, bug heat,
        translatable messages, and the source package release's component.
        """
        # We join to SourcePackageName, ProductSeries, and Product to cache
        # the objects that are implcitly needed to work with a
        # Packaging object.
        # Avoid circular import failures.
        from lp.registry.model.product import Product
        from lp.registry.model.productseries import ProductSeries
        find_spec = (
            Packaging, SourcePackageName, ProductSeries, Product,
            SQL("""
                CASE WHEN spr.component = 1 THEN 1000 ELSE 0 END +
                    CASE WHEN Product.bugtracker IS NULL
                        THEN coalesce(total_heat, 10) ELSE 0 END +
                    CASE WHEN ProductSeries.translations_autoimport_mode = 1
                        THEN coalesce(po_messages, 10) ELSE 0 END +
                    CASE WHEN ProductSeries.branch IS NULL THEN 500
                        ELSE 0 END AS score"""))
        joins, conditions = self._current_sourcepackage_joins_and_conditions
        origin = SQL(joins + """
            JOIN ProductSeries
                ON Packaging.productseries = ProductSeries.id
            JOIN Product
                ON ProductSeries.product = Product.id
            """)
        condition = SQL(conditions + "AND packaging.id IS NOT NULL")
        results = IStore(self).using(origin).find(find_spec, condition)
        results = results.order_by('score DESC')
        return [packaging
                for (packaging, spn, series, product, score) in results]

    @property
    def _current_sourcepackage_joins_and_conditions(self):
        """The SQL joins and conditions to prioritize source packages."""
        heat_score = ("""
            LEFT JOIN (
                SELECT
                    BugTask.sourcepackagename,
                    sum(Bug.heat) AS total_heat,
                    count(Bug.id) AS total_bugs
                FROM BugTask
                    JOIN Bug
                        ON bugtask.bug = Bug.id
                WHERE
                    BugTask.sourcepackagename is not NULL
                    AND BugTask.distribution = %(distribution)s
                    AND BugTask.status in %(statuses)s
                GROUP BY BugTask.sourcepackagename
                ) bugs
                ON SourcePackageName.id = bugs.sourcepackagename
            """ % sqlvalues(
                distribution=self.distribution,
                statuses=UNRESOLVED_BUGTASK_STATUSES))
        message_score = ("""
            LEFT JOIN (
                SELECT
                    POTemplate.sourcepackagename,
                    POTemplate.distroseries,
                    SUM(POTemplate.messagecount) / 2 AS po_messages,
                    SUM(POTemplate.messagecount) AS total_messages
                FROM POTemplate
                WHERE
                    POTemplate.sourcepackagename is not NULL
                    AND POTemplate.distroseries = %(distroseries)s
                GROUP BY
                    POTemplate.sourcepackagename,
                    POTemplate.distroseries
                ) messages
                ON SourcePackageName.id = messages.sourcepackagename
                AND DistroSeries.id = messages.distroseries
            """ % sqlvalues(distroseries=self))
        joins = ("""
            SourcePackageName
            JOIN SourcePackageRelease spr
                ON SourcePackageName.id = spr.sourcepackagename
            JOIN SourcePackagePublishingHistory spph
                ON spr.id = spph.sourcepackagerelease
            JOIN archive
                ON spph.archive = Archive.id
            JOIN DistroSeries
                ON spph.distroseries = DistroSeries.id
            LEFT JOIN Packaging
                ON SourcePackageName.id = Packaging.sourcepackagename
                AND Packaging.distroseries = DistroSeries.id
            """ + heat_score + message_score)
        conditions = ("""
            DistroSeries.id = %(distroseries)s
            AND spph.status IN %(active_status)s
            AND archive.purpose = %(primary)s
            """ % sqlvalues(
                distroseries=self,
                active_status=active_publishing_status,
                primary=ArchivePurpose.PRIMARY))
        return (joins, conditions)

    def getMostRecentlyLinkedPackagings(self):
        """See `IDistroSeries`."""
        results = self._all_packagings
        # Order by creation date with a secondary ordering by sourcepackage
        # name to ensure the ordering for test data where many packagings have
        # identical creation dates.
        results = results.order_by(Desc(Packaging.datecreated),
                                   SourcePackageName.name)[:5]
        return [
            packaging
            for (packaging, spn, product_series, product) in results]

    @property
    def supported(self):
        return self.status in [
            SeriesStatus.CURRENT,
            SeriesStatus.SUPPORTED,
            ]

    @property
    def distroserieslanguages(self):
        result = DistroSeriesLanguage.select(
            "DistroSeriesLanguage.language = Language.id AND "
            "DistroSeriesLanguage.distroseries = %d AND "
            "Language.visible = TRUE" % self.id,
            prejoinClauseTables=["Language"],
            clauseTables=["Language"],
            prejoins=["distroseries"],
            orderBy=["Language.englishname"])
        return result

    @cachedproperty('_previous_series_cached')
    def previous_series(self):
        """See `IDistroSeries`."""
        # This property is cached because it is used intensely inside
        # sourcepackage.py; avoiding regeneration reduces a lot of
        # count(*) queries.
        datereleased = self.datereleased
        # if this one is unreleased, use the last released one
        if not datereleased:
            datereleased = 'NOW'
        results = DistroSeries.select('''
                distribution = %s AND
                datereleased < %s
                ''' % sqlvalues(self.distribution.id, datereleased),
                orderBy=['-datereleased'])
        return list(results)

    @property
    def bug_reporting_guidelines(self):
        """See `IBugTarget`."""
        return self.distribution.bug_reporting_guidelines

    def _getMilestoneCondition(self):
        """See `HasMilestonesMixin`."""
        return (Milestone.distroseries == self)

    def canUploadToPocket(self, pocket):
        """See `IDistroSeries`."""
        # Allow everything for distroseries in FROZEN state.
        if self.status == SeriesStatus.FROZEN:
            return True

        # Define stable/released states.
        stable_states = (SeriesStatus.SUPPORTED,
                         SeriesStatus.CURRENT)

        # Deny uploads for RELEASE pocket in stable states.
        if (pocket == PackagePublishingPocket.RELEASE and
            self.status in stable_states):
            return False

        # Deny uploads for post-release pockets in unstable states.
        if (pocket != PackagePublishingPocket.RELEASE and
            self.status not in stable_states):
            return False

        # Allow anything else.
        return True

    def updatePackageCount(self):
        """See `IDistroSeries`."""

        # first update the source package count
        query = """
            SourcePackagePublishingHistory.distroseries = %s AND
            SourcePackagePublishingHistory.archive IN %s AND
            SourcePackagePublishingHistory.status IN %s AND
            SourcePackagePublishingHistory.pocket = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
            """ % sqlvalues(
                    self,
                    self.distribution.all_distro_archive_ids,
                    active_publishing_status,
                    PackagePublishingPocket.RELEASE)
        self.sourcecount = SourcePackageName.select(
            query, distinct=True,
            clauseTables=['SourcePackageRelease',
                          'SourcePackagePublishingHistory']).count()


        # next update the binary count
        clauseTables = ['DistroArchSeries', 'BinaryPackagePublishingHistory',
                        'BinaryPackageRelease']
        query = """
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id AND
            BinaryPackagePublishingHistory.status IN %s AND
            BinaryPackagePublishingHistory.pocket = %s AND
            BinaryPackagePublishingHistory.distroarchseries =
                DistroArchSeries.id AND
            DistroArchSeries.distroseries = %s AND
            BinaryPackagePublishingHistory.archive IN %s
            """ % sqlvalues(
                    active_publishing_status,
                    PackagePublishingPocket.RELEASE,
                    self,
                    self.distribution.all_distro_archive_ids)
        ret = BinaryPackageName.select(
            query, distinct=True, clauseTables=clauseTables).count()
        self.binarycount = ret

    @property
    def architecturecount(self):
        """See `IDistroSeries`."""
        return self.architectures.count()

    @property
    def fullseriesname(self):
        return "%s %s" % (
            self.distribution.name.capitalize(), self.name.capitalize())

    @property
    def bugtargetname(self):
        """See IBugTarget."""
        return self.fullseriesname
        # XXX mpt 2007-07-10 bugs 113258, 113262:
        # The distribution's and series' names should be used instead
        # of fullseriesname.

    @property
    def bugtargetdisplayname(self):
        """See IBugTarget."""
        return self.fullseriesname

    @property
    def last_full_language_pack_exported(self):
        return LanguagePack.selectFirstBy(
            distroseries=self, type=LanguagePackType.FULL,
            orderBy='-date_exported')

    @property
    def last_delta_language_pack_exported(self):
        return LanguagePack.selectFirstBy(
            distroseries=self, type=LanguagePackType.DELTA,
            updates=self.language_pack_base, orderBy='-date_exported')

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for this distribution series."""
        search_params.setDistroSeries(self)

    @property
    def official_bug_tags(self):
        """See `IHasBugs`."""
        return self.distribution.official_bug_tags

    def getUsedBugTags(self):
        """See `IHasBugs`."""
        return get_bug_tags("BugTask.distroseries = %s" % sqlvalues(self))

    def getUsedBugTagsWithOpenCounts(self, user):
        """See `IHasBugs`."""
        return get_bug_tags_open_count(BugTask.distroseries == self, user)

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None,
                       prejoin_people=True):
        """See IHasSpecifications.

        In this case the rules for the default behaviour cover three things:

          - acceptance: if nothing is said, ACCEPTED only
          - completeness: if nothing is said, ANY
          - informationalness: if nothing is said, ANY

        """

        # Make a new list of the filter, so that we do not mutate what we
        # were passed as a filter
        if not filter:
            # filter could be None or [] then we decide the default
            # which for a distroseries is to show everything approved
            filter = [SpecificationFilter.ACCEPTED]

        # defaults for completeness: in this case we don't actually need to
        # do anything, because the default is ANY

        # defaults for acceptance: in this case, if nothing is said about
        # acceptance, we want to show only accepted specs
        acceptance = False
        for option in [
            SpecificationFilter.ACCEPTED,
            SpecificationFilter.DECLINED,
            SpecificationFilter.PROPOSED]:
            if option in filter:
                acceptance = True
        if acceptance is False:
            filter.append(SpecificationFilter.ACCEPTED)

        # defaults for informationalness: we don't have to do anything
        # because the default if nothing is said is ANY

        # sort by priority descending, by default
        if sort is None or sort == SpecificationSort.PRIORITY:
            order = ['-priority', 'Specification.definition_status',
                     'Specification.name']
        elif sort == SpecificationSort.DATE:
            # we are showing specs for a GOAL, so under some circumstances
            # we care about the order in which the specs were nominated for
            # the goal, and in others we care about the order in which the
            # decision was made.

            # we need to establish if the listing will show specs that have
            # been decided only, or will include proposed specs.
            show_proposed = set([
                SpecificationFilter.ALL,
                SpecificationFilter.PROPOSED,
                ])
            if len(show_proposed.intersection(set(filter))) > 0:
                # we are showing proposed specs so use the date proposed
                # because not all specs will have a date decided.
                order = ['-Specification.datecreated', 'Specification.id']
            else:
                # this will show only decided specs so use the date the spec
                # was accepted or declined for the sprint
                order = ['-Specification.date_goal_decided',
                         '-Specification.datecreated',
                         'Specification.id']

        # figure out what set of specifications we are interested in. for
        # distroseries, we need to be able to filter on the basis of:
        #
        #  - completeness.
        #  - goal status.
        #  - informational.
        #
        base = 'Specification.distroseries = %s' % self.id
        query = base
        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += (' AND Specification.implementation_status = %s' %
              quote(SpecificationImplementationStatus.INFORMATIONAL))

        # filter based on completion. see the implementation of
        # Specification.is_complete() for more details
        completeness =  Specification.completeness_clause

        if SpecificationFilter.COMPLETE in filter:
            query += ' AND ( %s ) ' % completeness
        elif SpecificationFilter.INCOMPLETE in filter:
            query += ' AND NOT ( %s ) ' % completeness

        # look for specs that have a particular goalstatus (proposed,
        # accepted or declined)
        if SpecificationFilter.ACCEPTED in filter:
            query += ' AND Specification.goalstatus = %d' % (
                SpecificationGoalStatus.ACCEPTED.value)
        elif SpecificationFilter.PROPOSED in filter:
            query += ' AND Specification.goalstatus = %d' % (
                SpecificationGoalStatus.PROPOSED.value)
        elif SpecificationFilter.DECLINED in filter:
            query += ' AND Specification.goalstatus = %d' % (
                SpecificationGoalStatus.DECLINED.value)

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
        """See ISpecificationTarget."""
        return self.distribution.getSpecification(name)

    def getDistroSeriesLanguage(self, language):
        """See `IDistroSeries`."""
        return DistroSeriesLanguage.selectOneBy(
            distroseries=self, language=language)

    def getDistroSeriesLanguageOrDummy(self, language):
        """See `IDistroSeries`."""
        drl = self.getDistroSeriesLanguage(language)
        if drl is not None:
            return drl
        return DummyDistroSeriesLanguage(self, language)

    def updateStatistics(self, ztm):
        """See `IDistroSeries`."""
        # first find the set of all languages for which we have pofiles in
        # the distribution that are visible and not English
        langidset = set(IStore(Language).find(
            Language.id,
            Language.visible == True,
            Language.id == POFile.languageID,
            Language.code != 'en',
            POFile.potemplateID == POTemplate.id,
            POTemplate.distroseries == self,
            POTemplate.iscurrent == True).config(distinct=True))

        # now run through the existing DistroSeriesLanguages for the
        # distroseries, and update their stats, and remove them from the
        # list of languages we need to have stats for
        for distroserieslanguage in self.distroserieslanguages:
            distroserieslanguage.updateStatistics(ztm)
            langidset.discard(distroserieslanguage.language.id)
        # now we should have a set of languages for which we NEED
        # to have a DistroSeriesLanguage
        for langid in langidset:
            drl = DistroSeriesLanguage(distroseries=self, languageID=langid)
            drl.updateStatistics(ztm)
        # lastly, we need to update the message count for this distro
        # series itself
        messagecount = 0
        for potemplate in self.getCurrentTranslationTemplates():
            messagecount += potemplate.messageCount()
        self.messagecount = messagecount
        ztm.commit()

    def getSourcePackage(self, name):
        """See `IDistroSeries`."""
        if not ISourcePackageName.providedBy(name):
            try:
                name = SourcePackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return getUtility(ISourcePackageFactory).new(
            sourcepackagename=name, distroseries=self)

    def getBinaryPackage(self, name):
        """See `IDistroSeries`."""
        if not IBinaryPackageName.providedBy(name):
            try:
                name = BinaryPackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return DistroSeriesBinaryPackage(self, name)

    def getSourcePackageRelease(self, sourcepackagerelease):
        """See `IDistroSeries`."""
        return DistroSeriesSourcePackageRelease(self, sourcepackagerelease)

    def getCurrentSourceReleases(self, source_package_names):
        """See `IDistroSeries`."""
        source_package_ids = [
            package_name.id for package_name in source_package_names]
        releases = SourcePackageRelease.select("""
            SourcePackageName.id IN %s AND
            SourcePackageRelease.id =
                SourcePackagePublishingHistory.sourcepackagerelease AND
            SourcePackagePublishingHistory.id = (
                SELECT max(spph.id)
                FROM SourcePackagePublishingHistory spph,
                     SourcePackageRelease spr, SourcePackageName spn
                WHERE
                    spn.id = SourcePackageName.id AND
                    spr.sourcepackagename = spn.id AND
                    spph.sourcepackagerelease = spr.id AND
                    spph.archive IN %s AND
                    spph.status IN %s AND
                    spph.distroseries = %s)
            """ % sqlvalues(
                source_package_ids, self.distribution.all_distro_archive_ids,
                active_publishing_status, self),
            clauseTables=[
                'SourcePackageName', 'SourcePackagePublishingHistory'])
        return dict(
            (self.getSourcePackage(release.sourcepackagename),
             DistroSeriesSourcePackageRelease(self, release))
            for release in releases)

    def checkTranslationsViewable(self):
        """See `IDistroSeries`."""
        if not self.hide_all_translations:
            # Yup, viewable.
            return

        future = [
            SeriesStatus.EXPERIMENTAL,
            SeriesStatus.DEVELOPMENT,
            SeriesStatus.FUTURE,
            ]
        if self.status in future:
            raise TranslationUnavailable(
                "Translations for this release series are not available yet.")
        elif self.status == SeriesStatus.OBSOLETE:
            raise TranslationUnavailable(
                "This release series is obsolete.  Its translations are no "
                "longer available.")
        else:
            raise TranslationUnavailable(
                "Translations for this release series are not currently "
                "available.  Please come back soon.")

    def getTranslatableSourcePackages(self):
        """See `IDistroSeries`."""
        query = """
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.iscurrent = TRUE AND
            POTemplate.distroseries = %s""" % sqlvalues(self.id)
        result = SourcePackageName.select(query, clauseTables=['POTemplate'],
            orderBy=['name'], distinct=True)
        return [SourcePackage(sourcepackagename=spn, distroseries=self) for
            spn in result]

    def getUnlinkedTranslatableSourcePackages(self):
        """See `IDistroSeries`."""
        # Note that both unlinked packages and
        # linked-with-no-productseries packages are considered to be
        # "unlinked translatables".
        query = """
            SourcePackageName.id NOT IN (SELECT DISTINCT
             sourcepackagename FROM Packaging WHERE distroseries = %s) AND
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.distroseries = %s""" % sqlvalues(self.id, self.id)
        unlinked = SourcePackageName.select(
            query, clauseTables=['POTemplate'], orderBy=['name'])
        query = """
            Packaging.sourcepackagename = SourcePackageName.id AND
            Packaging.productseries = NULL AND
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.distroseries = %s""" % sqlvalues(self.id)
        linked_but_no_productseries = SourcePackageName.select(
            query, clauseTables=['POTemplate', 'Packaging'], orderBy=['name'])
        result = unlinked.union(linked_but_no_productseries)
        return [SourcePackage(sourcepackagename=spn, distroseries=self) for
            spn in result]

    def getPublishedReleases(self, sourcepackage_or_name, version=None,
                             pocket=None, include_pending=False,
                             exclude_pocket=None, archive=None):
        """See `IDistroSeries`."""
        # XXX cprov 2006-02-13 bug 31317:
        # We need a standard and easy API, no need
        # to support multiple type arguments, only string name should be
        # the best choice in here, the call site will be clearer.
        if ISourcePackage.providedBy(sourcepackage_or_name):
            spn = sourcepackage_or_name.name
        elif ISourcePackageName.providedBy(sourcepackage_or_name):
            spn = sourcepackage_or_name
        else:
            spns = getUtility(ISourcePackageNameSet)
            spn = spns.queryByName(sourcepackage_or_name)
            if spn is None:
                return []

        queries = ["""
        sourcepackagerelease=sourcepackagerelease.id AND
        sourcepackagerelease.sourcepackagename=%s AND
        distroseries=%s
        """ % sqlvalues(spn.id, self.id)]

        if pocket is not None:
            queries.append("pocket=%s" % sqlvalues(pocket.value))

        if version is not None:
            queries.append("version=%s" % sqlvalues(version))

        if exclude_pocket is not None:
            queries.append("pocket!=%s" % sqlvalues(exclude_pocket.value))

        if include_pending:
            queries.append("status in (%s, %s)" % sqlvalues(
                PackagePublishingStatus.PUBLISHED,
                PackagePublishingStatus.PENDING))
        else:
            queries.append("status=%s" % sqlvalues(
                PackagePublishingStatus.PUBLISHED))

        archives = self.distribution.getArchiveIDList(archive)
        queries.append("archive IN %s" % sqlvalues(archives))

        published = SourcePackagePublishingHistory.select(
            " AND ".join(queries), clauseTables = ['SourcePackageRelease'],
            orderBy=['-id'])

        return shortlist(published)

    def isUnstable(self):
        """See `IDistroSeries`."""
        return self.status in [
            SeriesStatus.FROZEN,
            SeriesStatus.DEVELOPMENT,
            SeriesStatus.EXPERIMENTAL,
        ]

    def getAllPublishedSources(self):
        """See `IDistroSeries`."""
        # Consider main archives only, and return all sources in
        # the PUBLISHED state.
        archives = self.distribution.getArchiveIDList()
        return SourcePackagePublishingHistory.select("""
            distroseries = %s AND
            status = %s AND
            archive in %s
            """ % sqlvalues(self, PackagePublishingStatus.PUBLISHED,
                            archives),
            orderBy="id")

    def getAllPublishedBinaries(self):
        """See `IDistroSeries`."""
        # Consider main archives only, and return all binaries in
        # the PUBLISHED state.
        archives = self.distribution.getArchiveIDList()
        return BinaryPackagePublishingHistory.select("""
            BinaryPackagePublishingHistory.distroarchseries =
                DistroArchSeries.id AND
            DistroArchSeries.distroseries = DistroSeries.id AND
            DistroSeries.id = %s AND
            BinaryPackagePublishingHistory.status = %s AND
            BinaryPackagePublishingHistory.archive in %s
            """ % sqlvalues(self, PackagePublishingStatus.PUBLISHED,
                            archives),
            clauseTables=["DistroArchSeries", "DistroSeries"],
            orderBy="BinaryPackagePublishingHistory.id")

    def getSourcesPublishedForAllArchives(self):
        """See `IDistroSeries`."""
        query = """
            SourcePackagePublishingHistory.distroseries = %s AND
            SourcePackagePublishingHistory.archive = Archive.id AND
            SourcePackagePublishingHistory.status in %s AND
            Archive.purpose != %s
         """ % sqlvalues(self, active_publishing_status, ArchivePurpose.COPY)

        if not self.isUnstable():
            # Stable distroseries don't allow builds for the release
            # pockets for the primary archives, but they do allow them for
            # the PPA and PARTNER archives.

            # XXX: Julian 2007-09-14: this should come from a single
            # location where this is specified, not sprinkled around the code.
            query += ("""AND (Archive.purpose in %s OR
                            SourcePackagePublishingHistory.pocket != %s)""" %
                      sqlvalues(ALLOW_RELEASE_BUILDS,
                                PackagePublishingPocket.RELEASE))

        return SourcePackagePublishingHistory.select(
            query, clauseTables=['Archive'], orderBy="id")

    def getSourcePackagePublishing(self, status, pocket, component=None,
                                   archive=None):
        """See `IDistroSeries`."""
        archives = self.distribution.getArchiveIDList(archive)

        clause = """
            SourcePackagePublishingHistory.sourcepackagerelease=
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename=
                SourcePackageName.id AND
            SourcePackagePublishingHistory.distroseries=%s AND
            SourcePackagePublishingHistory.archive IN %s AND
            SourcePackagePublishingHistory.status=%s AND
            SourcePackagePublishingHistory.pocket=%s
            """ %  sqlvalues(self, archives, status, pocket)

        if component:
            clause += (
                " AND SourcePackagePublishingHistory.component=%s"
                % sqlvalues(component)
                )

        orderBy = ['SourcePackageName.name']
        clauseTables = ['SourcePackageRelease', 'SourcePackageName']

        return SourcePackagePublishingHistory.select(
            clause, orderBy=orderBy, clauseTables=clauseTables)

    def getBinaryPackagePublishing(
        self, name=None, version=None, archtag=None, sourcename=None,
        orderBy=None, pocket=None, component=None, archive=None):
        """See `IDistroSeries`."""
        archives = self.distribution.getArchiveIDList(archive)

        query = ["""
        BinaryPackagePublishingHistory.binarypackagerelease =
            BinaryPackageRelease.id AND
        BinaryPackagePublishingHistory.distroarchseries =
            DistroArchSeries.id AND
        BinaryPackageRelease.binarypackagename =
            BinaryPackageName.id AND
        BinaryPackageRelease.build =
            Build.id AND
        Build.sourcepackagerelease =
            SourcePackageRelease.id AND
        SourcePackageRelease.sourcepackagename =
            SourcePackageName.id AND
        DistroArchSeries.distroseries = %s AND
        BinaryPackagePublishingHistory.archive IN %s AND
        BinaryPackagePublishingHistory.status = %s
        """ % sqlvalues(self, archives, PackagePublishingStatus.PUBLISHED)]

        if name:
            query.append('BinaryPackageName.name = %s' % sqlvalues(name))

        if version:
            query.append('BinaryPackageRelease.version = %s'
                      % sqlvalues(version))

        if archtag:
            query.append('DistroArchSeries.architecturetag = %s'
                      % sqlvalues(archtag))

        if sourcename:
            query.append(
                'SourcePackageName.name = %s' % sqlvalues(sourcename))

        if pocket:
            query.append(
                'BinaryPackagePublishingHistory.pocket = %s'
                % sqlvalues(pocket))

        if component:
            query.append(
                'BinaryPackagePublishingHistory.component = %s'
                % sqlvalues(component))

        query = " AND ".join(query)

        clauseTables = ['BinaryPackagePublishingHistory', 'DistroArchSeries',
                        'BinaryPackageRelease', 'BinaryPackageName', 'Build',
                        'SourcePackageRelease', 'SourcePackageName' ]

        result = BinaryPackagePublishingHistory.select(
            query, distinct=False, clauseTables=clauseTables, orderBy=orderBy)

        return result

    def publishedBinaryPackages(self, component=None):
        """See `IDistroSeries`."""
        # XXX sabdfl 2005-07-04: This can become a utility when that works
        # this is used by the debbugs import process, mkdebwatches
        pubpkgset = getUtility(IPublishedPackageSet)
        result = pubpkgset.query(distroseries=self, component=component)
        return [BinaryPackageRelease.get(pubrecord.binarypackagerelease)
                for pubrecord in result]

    def getBuildRecords(self, build_state=None, name=None, pocket=None,
                        arch_tag=None, user=None):
        """See IHasBuildRecords"""
        # Ignore "user", since it would not make any difference to the
        # records returned here (private builds are only in PPA right
        # now).

        # Find out the distroarchseries in question.
        arch_ids = DistroArchSeriesSet().getIdsForArchitectures(
            self.architectures, arch_tag)

        # Use the facility provided by IBuildSet to retrieve the records.
        return getUtility(IBuildSet).getBuildsByArchIds(
            arch_ids, build_state, name, pocket)

    def createUploadedSourcePackageRelease(
        self, sourcepackagename, version, maintainer, builddepends,
        builddependsindep, architecturehintlist, component, creator,
        urgency, changelog_entry, dsc, dscsigningkey, section,
        dsc_maintainer_rfc822, dsc_standards_version, dsc_format,
        dsc_binaries, archive, copyright, build_conflicts,
        build_conflicts_indep, dateuploaded=DEFAULT,
        source_package_recipe_build=None):
        """See `IDistroSeries`."""
        return SourcePackageRelease(
            upload_distroseries=self, sourcepackagename=sourcepackagename,
            version=version, maintainer=maintainer, dateuploaded=dateuploaded,
            builddepends=builddepends, builddependsindep=builddependsindep,
            architecturehintlist=architecturehintlist, component=component,
            creator=creator, urgency=urgency, changelog_entry=changelog_entry,
            dsc=dsc, dscsigningkey=dscsigningkey, section=section,
            copyright=copyright, upload_archive=archive,
            dsc_maintainer_rfc822=dsc_maintainer_rfc822,
            dsc_standards_version=dsc_standards_version,
            dsc_format=dsc_format, dsc_binaries=dsc_binaries,
            build_conflicts=build_conflicts,
            build_conflicts_indep=build_conflicts_indep,
            source_package_recipe_build=source_package_recipe_build)

    def getComponentByName(self, name):
        """See `IDistroSeries`."""
        comp = Component.byName(name)
        if comp is None:
            raise NotFoundError(name)
        permitted = set(self.components)
        if comp in permitted:
            return comp
        raise NotFoundError(name)

    def getSectionByName(self, name):
        """See `IDistroSeries`."""
        section = Section.byName(name)
        if section is None:
            raise NotFoundError(name)
        permitted = set(self.sections)
        if section in permitted:
            return section
        raise NotFoundError(name)

    def getBinaryPackageCaches(self, archive=None):
        """See `IDistroSeries`."""
        if archive is not None:
            archives = [archive.id]
        else:
            archives = self.distribution.all_distro_archive_ids

        caches = DistroSeriesPackageCache.select("""
            distroseries = %s AND
            archive IN %s
        """ % sqlvalues(self, archives),
        orderBy="name")

        return caches

    def removeOldCacheItems(self, archive, log):
        """See `IDistroSeries`."""

        # get the set of package names that should be there
        bpns = set(BinaryPackageName.select("""
            BinaryPackagePublishingHistory.distroarchseries =
                DistroArchSeries.id AND
            DistroArchSeries.distroseries = %s AND
            Archive.id = %s AND
            BinaryPackagePublishingHistory.archive = Archive.id AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id AND
            BinaryPackagePublishingHistory.dateremoved is NULL AND
            Archive.enabled = TRUE
            """ % sqlvalues(self, archive),
            distinct=True,
            clauseTables=[
                'Archive',
                'DistroArchSeries',
                'BinaryPackagePublishingHistory',
                'BinaryPackageRelease']))

        # remove the cache entries for binary packages we no longer want
        for cache in self.getBinaryPackageCaches(archive):
            if cache.binarypackagename not in bpns:
                log.debug(
                    "Removing binary cache for '%s' (%s)"
                    % (cache.name, cache.id))
                cache.destroySelf()

    def updateCompletePackageCache(self, archive, log, ztm, commit_chunk=500):
        """See `IDistroSeries`."""
        # Do not create cache entries for disabled archives.
        if not archive.enabled:
            return

        # Get the set of package names to deal with.
        bpns = IStore(BinaryPackageName).find(
            BinaryPackageName,
            DistroArchSeries.distroseries == self,
            BinaryPackagePublishingHistory.distroarchseriesID ==
                DistroArchSeries.id,
            BinaryPackagePublishingHistory.archive == archive,
            BinaryPackagePublishingHistory.binarypackagereleaseID ==
                BinaryPackageRelease.id,
            BinaryPackageRelease.binarypackagename == BinaryPackageName.id,
            BinaryPackagePublishingHistory.dateremoved == None).config(
                distinct=True)

        number_of_updates = 0
        chunk_size = 0
        for bpn in bpns:
            log.debug("Considering binary '%s'" % bpn.name)
            self.updatePackageCache(bpn, archive, log)
            number_of_updates += 1
            chunk_size += 1
            if chunk_size == commit_chunk:
                chunk_size = 0
                log.debug("Committing")
                ztm.commit()

        return number_of_updates

    def updatePackageCache(self, binarypackagename, archive, log):
        """See `IDistroSeries`."""

        # get the set of published binarypackagereleases
        bprs = IStore(BinaryPackageRelease).find(
            BinaryPackageRelease,
            BinaryPackageRelease.binarypackagename == binarypackagename,
            BinaryPackageRelease.id ==
                BinaryPackagePublishingHistory.binarypackagereleaseID,
            BinaryPackagePublishingHistory.distroarchseriesID ==
                DistroArchSeries.id,
            DistroArchSeries.distroseries == self,
            BinaryPackagePublishingHistory.archive == archive,
            BinaryPackagePublishingHistory.dateremoved == None)
        bprs = bprs.order_by(Desc(BinaryPackageRelease.datecreated))
        bprs = bprs.config(distinct=True)

        if bprs.count() == 0:
            log.debug("No binary releases found.")
            return

        # find or create the cache entry
        cache = DistroSeriesPackageCache.selectOne("""
            distroseries = %s AND
            archive = %s AND
            binarypackagename = %s
            """ % sqlvalues(self, archive, binarypackagename))
        if cache is None:
            log.debug("Creating new binary cache entry.")
            cache = DistroSeriesPackageCache(
                archive=archive,
                distroseries=self,
                binarypackagename=binarypackagename)

        # make sure the cached name, summary and description are correct
        cache.name = binarypackagename.name
        cache.summary = bprs[0].summary
        cache.description = bprs[0].description

        # get the sets of binary package summaries, descriptions. there is
        # likely only one, but just in case...

        summaries = set()
        descriptions = set()
        for bpr in bprs:
            log.debug("Considering binary version %s" % bpr.version)
            summaries.add(bpr.summary)
            descriptions.add(bpr.description)

        # and update the caches
        cache.summaries = ' '.join(sorted(summaries))
        cache.descriptions = ' '.join(sorted(descriptions))

    def searchPackages(self, text):
        """See `IDistroSeries`."""

        store = getUtility(IStoreSelector).get(MAIN_STORE, SLAVE_FLAVOR)
        find_spec = (
            DistroSeriesPackageCache,
            BinaryPackageName,
            SQL('rank(fti, ftq(%s)) AS rank' % sqlvalues(text))
            )
        origin = [
            DistroSeriesPackageCache,
            Join(
                BinaryPackageName,
                DistroSeriesPackageCache.binarypackagename ==
                    BinaryPackageName.id
                )
            ]

        # Note: When attempting to convert the query below into straight
        # Storm expressions, a 'tuple index out-of-range' error was always
        # raised.
        package_caches = store.using(*origin).find(
            find_spec,
            """DistroSeriesPackageCache.distroseries = %s AND
            DistroSeriesPackageCache.archive IN %s AND
            (fti @@ ftq(%s) OR
            DistroSeriesPackageCache.name ILIKE '%%' || %s || '%%')
            """ % (quote(self),
                   quote(self.distribution.all_distro_archive_ids),
                   quote(text), quote_like(text))
            ).config(distinct=True)

        # Create a function that will decorate the results, converting
        # them from the find_spec above into a DSBP:
        def result_to_dsbp((cache, binary_package_name, rank)):
            return DistroSeriesBinaryPackage(
                distroseries=cache.distroseries,
                binarypackagename=binary_package_name,
                cache=cache)

        # Return the decorated result set so the consumer of these
        # results will only see DSBPs
        return DecoratedResultSet(package_caches, result_to_dsbp)

    def newArch(self, architecturetag, processorfamily, official, owner,
                supports_virtualized=False):
        """See `IDistroSeries`."""
        distroarchseries = DistroArchSeries(
            architecturetag=architecturetag, processorfamily=processorfamily,
            official=official, distroseries=self, owner=owner,
            supports_virtualized=supports_virtualized)
        return distroarchseries

    def newMilestone(self, name, dateexpected=None, summary=None,
                     code_name=None):
        """See `IDistroSeries`."""
        return Milestone(
            name=name, code_name=code_name,
            dateexpected=dateexpected, summary=summary,
            distribution=self.distribution, distroseries=self)

    def getLatestUploads(self):
        """See `IDistroSeries`."""
        query = """
        sourcepackagerelease.id=packageuploadsource.sourcepackagerelease
        AND sourcepackagerelease.sourcepackagename=sourcepackagename.id
        AND packageuploadsource.packageupload=packageupload.id
        AND packageupload.status=%s
        AND packageupload.distroseries=%s
        AND packageupload.archive IN %s
        """ % sqlvalues(
                PackageUploadStatus.DONE,
                self,
                self.distribution.all_distro_archive_ids)

        last_uploads = SourcePackageRelease.select(
            query, limit=5, prejoins=['sourcepackagename'],
            clauseTables=['SourcePackageName', 'PackageUpload',
                          'PackageUploadSource'],
            orderBy=['-packageupload.id'])

        distro_sprs = [
            self.getSourcePackageRelease(spr) for spr in last_uploads]

        return distro_sprs

    def createQueueEntry(self, pocket, changesfilename, changesfilecontent,
                         archive, signing_key=None):
        """See `IDistroSeries`."""
        # We store the changes file in the librarian to avoid having to
        # deal with broken encodings in these files; this will allow us
        # to regenerate these files as necessary.
        #
        # The use of StringIO here should be safe: we do not encoding of
        # the content in the changes file (as doing so would be guessing
        # at best, causing unpredictable corruption), and simply pass it
        # off to the librarian.

        # The PGP signature is stripped from all changesfiles for PPAs
        # to avoid replay attacks (see bug 159304).
        if archive.is_ppa:
            signed_message = signed_message_from_string(changesfilecontent)
            if signed_message is not None:
                # Overwrite `changesfilecontent` with the text stripped
                # of the PGP signature.
                new_content = signed_message.signedContent
                if new_content is not None:
                    changesfilecontent = signed_message.signedContent

        changes_file = getUtility(ILibraryFileAliasSet).create(
            changesfilename, len(changesfilecontent),
            StringIO(changesfilecontent), 'text/plain',
            restricted=archive.private)

        return PackageUpload(
            distroseries=self, status=PackageUploadStatus.NEW,
            pocket=pocket, archive=archive,
            changesfile=changes_file, signing_key=signing_key)

    def getPackageUploadQueue(self, state):
        """See `IDistroSeries`."""
        return PackageUploadQueue(self, state)

    def getPackageUploads(self, created_since_date=None, status=None,
                          archive=None, pocket=None, custom_type=None):
        """See `IDistroSeries`."""
        return getUtility(IPackageUploadSet).getAll(
            self, created_since_date, status, archive, pocket, custom_type)

    def getQueueItems(self, status=None, name=None, version=None,
                      exact_match=False, pocket=None, archive=None):
        """See `IDistroSeries`."""
        # XXX Julian 2009-07-02 bug=394645
        # This method is partially deprecated by getPackageUploads(),
        # see the bug for more info.

        default_clauses = ["""
            packageupload.distroseries = %s""" % sqlvalues(self)]

        # Restrict result to given archives.
        archives = self.distribution.getArchiveIDList(archive)

        default_clauses.append("""
        packageupload.archive IN %s""" % sqlvalues(archives))

        # restrict result to a given pocket
        if pocket is not None:
            if not isinstance(pocket, list):
                pocket = [pocket]
            default_clauses.append("""
            packageupload.pocket IN %s""" % sqlvalues(pocket))

        # XXX cprov 2006-06-06:
        # We may reorganise this code, creating some new methods provided
        # by IPackageUploadSet, as: getByStatus and getByName.
        if not status:
            assert not version and not exact_match
            return PackageUpload.select(
                " AND ".join(default_clauses), orderBy=['-id'])

        if not isinstance(status, list):
            status = [status]

        default_clauses.append("""
        packageupload.status IN %s""" % sqlvalues(status))

        if not name:
            assert not version and not exact_match
            return PackageUpload.select(
                " AND ".join(default_clauses), orderBy=['-id'])

        source_where_clauses = default_clauses + ["""
            packageupload.id = packageuploadsource.packageupload
            """]

        build_where_clauses = default_clauses + ["""
            packageupload.id = packageuploadbuild.packageupload
            """]

        custom_where_clauses = default_clauses + ["""
            packageupload.id = packageuploadcustom.packageupload
            """]

        # modify source clause to lookup on sourcepackagerelease
        source_where_clauses.append("""
            packageuploadsource.sourcepackagerelease =
            sourcepackagerelease.id""")
        source_where_clauses.append(
            "sourcepackagerelease.sourcepackagename = sourcepackagename.id")

        # modify build clause to lookup on binarypackagerelease
        build_where_clauses.append(
            "packageuploadbuild.build = binarypackagerelease.build")
        build_where_clauses.append(
            "binarypackagerelease.binarypackagename = binarypackagename.id")

        # modify custom clause to lookup on libraryfilealias
        custom_where_clauses.append(
            "packageuploadcustom.libraryfilealias = "
            "libraryfilealias.id")

        # attempt to exact or similar names in builds, sources and custom
        if exact_match:
            source_where_clauses.append(
                "sourcepackagename.name = '%s'" % name)
            build_where_clauses.append("binarypackagename.name = '%s'" % name)
            custom_where_clauses.append(
                "libraryfilealias.filename='%s'" % name)
        else:
            source_where_clauses.append(
                "sourcepackagename.name LIKE '%%' || %s || '%%'"
                % quote_like(name))

            build_where_clauses.append(
                "binarypackagename.name LIKE '%%' || %s || '%%'"
                % quote_like(name))

            custom_where_clauses.append(
                "libraryfilealias.filename LIKE '%%' || %s || '%%'"
                % quote_like(name))

        # attempt for given version argument, except by custom
        if version:
            # exact or similar matches
            if exact_match:
                source_where_clauses.append(
                    "sourcepackagerelease.version = '%s'" % version)
                build_where_clauses.append(
                    "binarypackagerelease.version = '%s'" % version)
            else:
                source_where_clauses.append(
                    "sourcepackagerelease.version LIKE '%%' || %s || '%%'"
                    % quote_like(version))
                build_where_clauses.append(
                    "binarypackagerelease.version LIKE '%%' || %s || '%%'"
                    % quote_like(version))

        source_clauseTables = [
            'PackageUploadSource',
            'SourcePackageRelease',
            'SourcePackageName',
            ]
        source_orderBy = ['-sourcepackagerelease.dateuploaded']

        build_clauseTables = [
            'PackageUploadBuild',
            'BinaryPackageRelease',
            'BinaryPackageName',
            ]
        build_orderBy = ['-binarypackagerelease.datecreated']

        custom_clauseTables = [
            'PackageUploadCustom',
            'LibraryFileAlias',
            ]
        custom_orderBy = ['-LibraryFileAlias.id']

        source_where_clause = " AND ".join(source_where_clauses)
        source_results = PackageUpload.select(
            source_where_clause, clauseTables=source_clauseTables,
            orderBy=source_orderBy)

        build_where_clause = " AND ".join(build_where_clauses)
        build_results = PackageUpload.select(
            build_where_clause, clauseTables=build_clauseTables,
            orderBy=build_orderBy)

        custom_where_clause = " AND ".join(custom_where_clauses)
        custom_results = PackageUpload.select(
            custom_where_clause, clauseTables=custom_clauseTables,
            orderBy=custom_orderBy)

        return source_results.union(build_results.union(custom_results))

    def createBug(self, bug_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        # We don't currently support opening a new bug on an IDistroSeries,
        # because internally bugs are reported against IDistroSeries only when
        # targeted to be fixed in that series, which is rarely the case for a
        # brand new bug report.
        raise NotImplementedError(
            "A new bug cannot be filed directly on a distribution series, "
            "because series are meant for \"targeting\" a fix to a specific "
            "version. It's possible that we may change this behaviour to "
            "allow filing a bug on a distribution series in the "
            "not-too-distant future. For now, you probably meant to file "
            "the bug on the distribution instead.")

    def _getBugTaskContextClause(self):
        """See BugTargetBase."""
        return 'BugTask.distroseries = %s' % sqlvalues(self)

    def initialiseFromParent(self):
        """See `IDistroSeries`."""
        archives = self.distribution.all_distro_archive_ids
        assert self.parent_series is not None, "Parent series must be present"
        assert SourcePackagePublishingHistory.select("""
            Distroseries = %s AND
            Archive IN %s""" % sqlvalues(self.id, archives)).count() == 0, (
            "Source Publishing must be empty")
        for arch in self.architectures:
            assert BinaryPackagePublishingHistory.select("""
            DistroArchSeries = %s AND
            Archive IN %s""" % sqlvalues(arch, archives)).count() == 0, (
                "Binary Publishing must be empty")
            try:
                parent_arch = self.parent_series[arch.architecturetag]
                assert parent_arch.processorfamily == arch.processorfamily, (
                       "The arch tags must match the processor families.")
            except KeyError:
                raise AssertionError("Parent series lacks %s" % (
                    arch.architecturetag))
        assert self.nominatedarchindep is not None, (
               "Must have a nominated archindep architecture.")
        assert self.components.count() == 0, (
               "Component selections must be empty.")
        assert self.sections.count() == 0, (
               "Section selections must be empty.")

        # MAINTAINER: dsilvers: 20051031
        # Here we go underneath the SQLObject caching layers in order to
        # generate what will potentially be tens of thousands of rows
        # in various tables. Thus we flush pending updates from the SQLObject
        # layer, perform our work directly in the transaction and then throw
        # the rest of the SQLObject cache away to make sure it hasn't cached
        # anything that is no longer true.

        # Prepare for everything by flushing updates to the database.
        flush_database_updates()
        cur = cursor()

        # Perform the copies
        self._copy_component_section_and_format_selections(cur)

        # Prepare the list of distroarchseries for which binary packages
        # shall be copied.
        distroarchseries_list = []
        for arch in self.architectures:
            parent_arch = self.parent_series[arch.architecturetag]
            distroarchseries_list.append((parent_arch, arch))
        # Now copy source and binary packages.
        self._copy_publishing_records(distroarchseries_list)
        self._copy_lucille_config(cur)
        self._copy_packaging_links(cur)

        # Finally, flush the caches because we've altered stuff behind the
        # back of sqlobject.
        flush_database_caches()

    def _copy_lucille_config(self, cur):
        """Copy all lucille related configuration from our parent series."""
        cur.execute('''
            UPDATE DistroSeries SET lucilleconfig=(
                SELECT pdr.lucilleconfig FROM DistroSeries AS pdr
                WHERE pdr.id = %s)
            WHERE id = %s
            ''' % sqlvalues(self.parent_series.id, self.id))

    def _copy_publishing_records(self, distroarchseries_list):
        """Copy the publishing records from the parent arch series
        to the given arch series in ourselves.

        We copy all PENDING and PUBLISHED records as PENDING into our own
        publishing records.

        We copy only the RELEASE pocket in the PRIMARY and PARTNER
        archives.
        """
        archive_set = getUtility(IArchiveSet)

        for archive in self.parent_series.distribution.all_distro_archives:
            # We only want to copy PRIMARY and PARTNER archives.
            if archive.purpose not in MAIN_ARCHIVE_PURPOSES:
                continue

            # XXX cprov 20080612: Implicitly creating a PARTNER archive for
            # the destination distroseries is bad. Why are we copying
            # partner to a series in another distribution anyway ?
            # See bug #239807 for further information.
            target_archive = archive_set.getByDistroPurpose(
                self.distribution, archive.purpose)
            if target_archive is None:
                target_archive = archive_set.new(
                    distribution=self.distribution, purpose=archive.purpose,
                    owner=self.distribution.owner)

            origin = PackageLocation(
                archive, self.parent_series.distribution, self.parent_series,
                PackagePublishingPocket.RELEASE)
            destination = PackageLocation(
                target_archive, self.distribution, self,
                PackagePublishingPocket.RELEASE)
            clone_packages(origin, destination, distroarchseries_list)

    def _copy_component_section_and_format_selections(self, cur):
        """Copy the section, component and format selections from the parent
        distro series into this one.
        """
        # Copy the component selections
        cur.execute('''
            INSERT INTO ComponentSelection (distroseries, component)
            SELECT %s AS distroseries, cs.component AS component
            FROM ComponentSelection AS cs WHERE cs.distroseries = %s
            ''' % sqlvalues(self.id, self.parent_series.id))
        # Copy the section selections
        cur.execute('''
            INSERT INTO SectionSelection (distroseries, section)
            SELECT %s as distroseries, ss.section AS section
            FROM SectionSelection AS ss WHERE ss.distroseries = %s
            ''' % sqlvalues(self.id, self.parent_series.id))
        # Copy the source format selections
        cur.execute('''
            INSERT INTO SourcePackageFormatSelection (distroseries, format)
            SELECT %s as distroseries, spfs.format AS format
            FROM SourcePackageFormatSelection AS spfs
            WHERE spfs.distroseries = %s
            ''' % sqlvalues(self.id, self.parent_series.id))

    def _copy_packaging_links(self, cur):
        """Copy the packaging links from the parent series to this one."""
        cur.execute("""
            INSERT INTO
                Packaging(
                    distroseries, sourcepackagename, productseries,
                    packaging, owner)
            SELECT
                ChildSeries.id,
                Packaging.sourcepackagename,
                Packaging.productseries,
                Packaging.packaging,
                Packaging.owner
            FROM
                Packaging
                -- Joining the parent distroseries permits the query to build
                -- the data set for the series being updated, yet results are
                -- in fact the data from the original series.
                JOIN Distroseries ChildSeries
                    ON Packaging.distroseries = ChildSeries.parent_series
            WHERE
                -- Select only the packaging links that are in the parent
                -- that are not in the child.
                ChildSeries.id = %s
                AND Packaging.sourcepackagename in (
                    SELECT sourcepackagename
                    FROM Packaging
                    WHERE distroseries in (
                        SELECT id
                        FROM Distroseries
                        WHERE id = ChildSeries.parent_series
                        )
                    EXCEPT
                    SELECT sourcepackagename
                    FROM Packaging
                    WHERE distroseries in (
                        SELECT id
                        FROM Distroseries
                        WHERE id = ChildSeries.id
                        )
                    )
            """ % self.id)

    def copyTranslationsFromParent(self, transaction, logger=None):
        """See `IDistroSeries`."""
        if logger is None:
            logger = logging

        assert self.defer_translation_imports, (
            "defer_translation_imports not set!"
            " That would corrupt translation data mixing new imports"
            " with the information being copied.")

        assert self.hide_all_translations, (
            "hide_all_translations not set!"
            " That would allow users to see and modify incomplete"
            " translation state.")

        flush_database_updates()
        flush_database_caches()
        copy_active_translations(self, transaction, logger)

    def getPOFileContributorsByLanguage(self, language):
        """See `IDistroSeries`."""
        contributors = IStore(Person).find(
            Person,
            POFileTranslator.personID == Person.id,
            POFile.id == POFileTranslator.pofileID,
            POFile.language == language,
            POTemplate.id == POFile.potemplateID,
            POTemplate.distroseries == self,
            POTemplate.iscurrent == True)
        contributors = contributors.order_by(*Person._storm_sortingColumns)
        contributors = contributors.config(distinct=True)
        return contributors

    def getPendingPublications(self, archive, pocket, is_careful):
        """See ICanPublishPackages."""
        queries = ['distroseries = %s' % sqlvalues(self)]

        # Query main archive for this distroseries
        queries.append('archive=%s' % sqlvalues(archive))

        # Careful publishing should include all PUBLISHED rows, normal run
        # only includes PENDING ones.
        statuses = [PackagePublishingStatus.PENDING]
        if is_careful:
            statuses.append(PackagePublishingStatus.PUBLISHED)
        queries.append('status IN %s' % sqlvalues(statuses))

        # Restrict to a specific pocket.
        queries.append('pocket = %s' % sqlvalues(pocket))

        # Exclude RELEASE pocket if the distroseries was already released,
        # since it should not change for main archive.
        # We allow RELEASE publishing for PPAs.
        # We also allow RELEASE publishing for partner.
        if (not self.isUnstable() and
            not archive.allowUpdatesToReleasePocket()):
            queries.append(
            'pocket != %s' % sqlvalues(PackagePublishingPocket.RELEASE))

        publications = SourcePackagePublishingHistory.select(
            " AND ".join(queries), orderBy="-id")

        return publications

    def publish(self, diskpool, log, archive, pocket, is_careful=False):
        """See ICanPublishPackages."""
        log.debug("Publishing %s-%s" % (self.title, pocket.name))
        log.debug("Attempting to publish pending sources.")

        dirty_pockets = set()
        for spph in self.getPendingPublications(archive, pocket, is_careful):
            if not self.checkLegalPocket(spph, is_careful, log):
                continue
            spph.publish(diskpool, log)
            dirty_pockets.add((self.name, spph.pocket))

        # propagate publication request to each distroarchseries.
        for dar in self.architectures:
            more_dirt = dar.publish(
                diskpool, log, archive, pocket, is_careful)
            dirty_pockets.update(more_dirt)

        return dirty_pockets

    def checkLegalPocket(self, publication, is_careful, log):
        """Check if the publication can happen in the archive."""
        # 'careful' mode re-publishes everything:
        if is_careful:
            return True

        # PPA and PARTNER allow everything.
        if publication.archive.allowUpdatesToReleasePocket():
            return True

        # FROZEN state also allow all pockets to be published.
        if self.status == SeriesStatus.FROZEN:
            return True

        # If we're not republishing, we want to make sure that
        # we're not publishing packages into the wrong pocket.
        # Unfortunately for careful mode that can't hold true
        # because we indeed need to republish everything.
        if (self.isUnstable() and
            publication.pocket != PackagePublishingPocket.RELEASE):
            log.error("Tried to publish %s (%s) into a non-release "
                      "pocket on unstable series %s, skipping"
                      % (publication.displayname, publication.id,
                         self.displayname))
            return False
        if (not self.isUnstable() and
            publication.pocket == PackagePublishingPocket.RELEASE):
            log.error("Tried to publish %s (%s) into release pocket "
                      "on stable series %s, skipping"
                      % (publication.displayname, publication.id,
                         self.displayname))
            return False

        return True

    @property
    def main_archive(self):
        return self.distribution.main_archive

    def getTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.selectBy(distroseries=self,
                                     orderBy=['-priority', 'name'])
        return shortlist(result, 2000)

    def getCurrentTranslationTemplates(self, just_ids=False):
        """See `IHasTranslationTemplates`."""
        store = Store.of(self)
        if just_ids:
            looking_for = POTemplate.id
        else:
            looking_for = POTemplate

        # Select all current templates for this series, if the Product
        # actually uses Launchpad Translations.  Otherwise, return an
        # empty result.
        result = store.find(looking_for, And(
            self.distribution.official_rosetta == True,
            POTemplate.iscurrent == True,
            POTemplate.distroseries == self))
        return result.order_by(['-POTemplate.priority', 'POTemplate.name'])

    def getObsoleteTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.select('''
            distroseries = %s AND
            distroseries = DistroSeries.id AND
            DistroSeries.distribution = Distribution.id AND
            (iscurrent IS FALSE OR Distribution.official_rosetta IS FALSE)
            ''' % sqlvalues(self),
            clauseTables = ['DistroSeries', 'Distribution'],
            orderBy=['-priority', 'name'])
        return shortlist(result, 300)

    def getSuite(self, pocket):
        """See `IDistroSeries`."""
        if pocket == PackagePublishingPocket.RELEASE:
            return self.name
        else:
            return '%s%s' % (self.name, pocketsuffix[pocket])

    def isSourcePackageFormatPermitted(self, format):
        return getUtility(ISourcePackageFormatSelectionSet
            ).getBySeriesAndFormat(self, format) is not None


class DistroSeriesSet:
    implements(IDistroSeriesSet)

    def get(self, distroseriesid):
        """See `IDistroSeriesSet`."""
        return DistroSeries.get(distroseriesid)

    def translatables(self):
        """See `IDistroSeriesSet`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, SLAVE_FLAVOR)
        # Join POTemplate distinctly to only get entries with available
        # translations.
        result_set = store.using((DistroSeries, POTemplate)).find(
            DistroSeries,
            DistroSeries.hide_all_translations == False,
            DistroSeries.id == POTemplate.distroseriesID
            ).config(distinct=True)
        # XXX: henninge 2009-02-11 bug=217644: Convert to sequence right here
        # because ResultSet reports a wrong count() when using DISTINCT. Also
        # ResultSet does not implement __len__(), which would make it more
        # like a sequence.
        return list(result_set)

    def findByName(self, name):
        """See `IDistroSeriesSet`."""
        return DistroSeries.selectBy(name=name)

    def queryByName(self, distribution, name):
        """See `IDistroSeriesSet`."""
        return DistroSeries.selectOneBy(distribution=distribution, name=name)

    def findByVersion(self, version):
        """See `IDistroSeriesSet`."""
        return DistroSeries.selectBy(version=version)

    def _parseSuite(self, suite):
        """Parse 'suite' into a series name and a pocket."""
        tokens = suite.rsplit('-', 1)
        if len(tokens) == 1:
            return suite, PackagePublishingPocket.RELEASE
        series, pocket = tokens
        try:
            pocket = PackagePublishingPocket.items[pocket.upper()]
        except KeyError:
            # No such pocket. Probably trying to get a hyphenated series name.
            return suite, PackagePublishingPocket.RELEASE
        else:
            return series, pocket

    def fromSuite(self, distribution, suite):
        """See `IDistroSeriesSet`."""
        series_name, pocket = self._parseSuite(suite)
        series = distribution.getSeries(series_name)
        return series, pocket

    def search(self, distribution=None, isreleased=None, orderBy=None):
        """See `IDistroSeriesSet`."""
        where_clause = ""
        if distribution is not None:
            where_clause += "distribution = %s" % sqlvalues(distribution.id)
        if isreleased is not None:
            if where_clause:
                where_clause += " AND "
            if isreleased:
                # The query is filtered on released releases.
                where_clause += "releasestatus in (%s, %s)" % sqlvalues(
                    SeriesStatus.CURRENT,
                    SeriesStatus.SUPPORTED)
            else:
                # The query is filtered on unreleased releases.
                where_clause += "releasestatus in (%s, %s, %s)" % sqlvalues(
                    SeriesStatus.EXPERIMENTAL,
                    SeriesStatus.DEVELOPMENT,
                    SeriesStatus.FROZEN)
        if orderBy is not None:
            return DistroSeries.select(where_clause, orderBy=orderBy)
        else:
            return DistroSeries.select(where_clause)
