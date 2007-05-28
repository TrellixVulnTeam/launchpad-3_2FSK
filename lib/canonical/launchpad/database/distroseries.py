# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Database classes for a distribution series."""

__metaclass__ = type

__all__ = [
    'DistroSeries',
    'DistroSeriesSet',
    ]

import logging
import time
from cStringIO import StringIO

from zope.interface import implements
from zope.component import getUtility

from sqlobject import (
    BoolCol, StringCol, ForeignKey, SQLMultipleJoin, IntCol,
    SQLObjectNotFound, SQLRelatedJoin)

from canonical.cachedproperty import cachedproperty

from canonical.database import postgresql
from canonical.database.sqlbase import (cursor, flush_database_caches,
    flush_database_updates, quote_like, quote, quoteIdentifier, SQLBase,
    sqlvalues)
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol

from canonical.lp.dbschema import (
    PackagePublishingStatus, DistroSeriesStatus,
    PackageUploadStatus, PackagePublishingPocket, SpecificationSort,
    SpecificationGoalStatus, SpecificationFilter, RosettaImportStatus)

from canonical.launchpad.interfaces import (
    IDistroSeries, IDistroSeriesSet, ISourcePackageName,
    IPublishedPackageSet, IHasBuildRecords, NotFoundError,
    IBinaryPackageName, ILibraryFileAliasSet, IBuildSet,
    ISourcePackage, ISourcePackageNameSet,
    IHasQueueItems, IPublishing, IHasTranslationImports)

from canonical.launchpad.database.bugtarget import BugTargetBase
from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.launchpad.database.binarypackagename import (
    BinaryPackageName)
from canonical.launchpad.database.bug import (
    get_bug_tags, get_bug_tags_open_count)
from canonical.launchpad.database.distroseriesbinarypackage import (
    DistroSeriesBinaryPackage)
from canonical.launchpad.database.distroseriessourcepackagerelease import (
    DistroSeriesSourcePackageRelease)
from canonical.launchpad.database.distroseriespackagecache import (
    DistroSeriesPackageCache)
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.publishing import (
    BinaryPackagePublishingHistory, SourcePackagePublishingHistory)
from canonical.launchpad.database.distroarchseries import DistroArchSeries
from canonical.launchpad.database.potemplate import POTemplate
from canonical.launchpad.database.language import Language
from canonical.launchpad.database.distroserieslanguage import (
    DistroSeriesLanguage, DummyDistroSeriesLanguage)
from canonical.launchpad.database.sourcepackage import SourcePackage
from canonical.launchpad.database.sourcepackagename import SourcePackageName
from canonical.launchpad.database.packaging import Packaging
from canonical.launchpad.database.bugtask import BugTaskSet
from canonical.launchpad.database.binarypackagerelease import (
        BinaryPackageRelease)
from canonical.launchpad.database.component import Component
from canonical.launchpad.database.section import Section
from canonical.launchpad.database.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.database.specification import (
    HasSpecificationsMixin, Specification)
from canonical.launchpad.database.queue import (
    PackageUpload, PackageUploadQueue)
from canonical.launchpad.database.translationimportqueue import (
    TranslationImportQueueEntry)
from canonical.launchpad.database.pofile import POFile
from canonical.launchpad.helpers import shortlist


class DistroSeries(SQLBase, BugTargetBase, HasSpecificationsMixin):
    """A particular series of a distribution."""
    implements(IDistroSeries, IHasBuildRecords, IHasQueueItems, IPublishing,
               IHasTranslationImports)

    _table = 'DistroRelease'
    _defaultOrder = ['distribution', 'version']

    distribution = ForeignKey(dbName='distribution',
                              foreignKey='Distribution', notNull=True)
    name = StringCol(notNull=True)
    displayname = StringCol(notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    description = StringCol(notNull=True)
    version = StringCol(notNull=True)
    status = EnumCol(
        dbName='releasestatus', notNull=True, schema=DistroSeriesStatus)
    date_created = UtcDateTimeCol(notNull=False, default=UTC_NOW)
    datereleased = UtcDateTimeCol(notNull=False, default=None)
    parentseries =  ForeignKey(
        dbName='parentrelease', foreignKey='DistroSeries', notNull=False)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person', notNull=True)
    driver = ForeignKey(
        foreignKey="Person", dbName="driver", notNull=False, default=None)
    lucilleconfig = StringCol(notNull=False, default=None)
    changeslist = StringCol(notNull=False, default=None)
    nominatedarchindep = ForeignKey(
        dbName='nominatedarchindep',foreignKey='DistroArchSeries',
        notNull=False, default=None)
    datelastlangpack = UtcDateTimeCol(dbName='datelastlangpack', notNull=False,
        default=None)
    messagecount = IntCol(notNull=True, default=0)
    binarycount = IntCol(notNull=True, default=DEFAULT)
    sourcecount = IntCol(notNull=True, default=DEFAULT)
    defer_translation_imports = BoolCol(notNull=True, default=True)
    hide_all_translations = BoolCol(notNull=True, default=True)

    architectures = SQLMultipleJoin(
        'DistroArchSeries', joinColumn='distroseries',
        orderBy='architecturetag')
    binary_package_caches = SQLMultipleJoin('DistroSeriesPackageCache',
        joinColumn='distroseries', orderBy='name')
    components = SQLRelatedJoin(
        'Component', joinColumn='distrorelease', otherColumn='component',
        intermediateTable='ComponentSelection')
    sections = SQLRelatedJoin(
        'Section', joinColumn='distrorelease', otherColumn='section',
        intermediateTable='SectionSelection')

    @property
    def all_milestones(self):
        """See IDistroSeries."""
        return Milestone.selectBy(
            distroseries=self, orderBy=['dateexpected', 'name'])

    @property
    def milestones(self):
        """See IDistroSeries."""
        return Milestone.selectBy(
            distroseries=self, visible=True, orderBy=['dateexpected', 'name'])

    @property
    def drivers(self):
        """See IDistroSeries."""
        drivers = set()
        drivers.add(self.driver)
        drivers = drivers.union(self.distribution.drivers)
        drivers.discard(None)
        return sorted(drivers, key=lambda driver: driver.browsername)

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

    @property
    def packagings(self):
        # We join through sourcepackagename to be able to ORDER BY it,
        # and this code also uses prejoins to avoid fetching data later
        # on.
        packagings = Packaging.select(
            "Packaging.sourcepackagename = SourcePackageName.id "
            "AND DistroRelease.id = Packaging.distrorelease "
            "AND DistroRelease.id = %d" % self.id,
            prejoinClauseTables=["SourcePackageName", ],
            clauseTables=["SourcePackageName", "DistroRelease"],
            prejoins=["productseries", "productseries.product"],
            orderBy=["SourcePackageName.name"]
            )
        return packagings

    @property
    def distroserieslanguages(self):
        result = DistroSeriesLanguage.select(
            "DistroReleaseLanguage.language = Language.id AND "
            "DistroReleaseLanguage.distrorelease = %d AND "
            "Language.visible = TRUE" % self.id,
            prejoinClauseTables=["Language"],
            clauseTables=["Language"],
            prejoins=["distroseries"],
            orderBy=["Language.englishname"])
        return result

    @cachedproperty('_previous_serieses_cached')
    def previous_serieses(self):
        """See IDistroSeries."""
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
    def parent(self):
        """See IDistroSeries."""
        if self.parentseries:
            return self.parentseries.title
        return ''

    def canUploadToPocket(self, pocket):
        """See IDistroSeries."""
        # frozen/released states
        released_states = [
            DistroSeriesStatus.SUPPORTED,
            DistroSeriesStatus.CURRENT
            ]

        # deny uploads for released RELEASE pockets
        if (pocket == PackagePublishingPocket.RELEASE and
            self.status in released_states):
            return False

        # deny uploads for non-RELEASE unreleased pockets
        if (pocket != PackagePublishingPocket.RELEASE and
            self.status not in released_states):
            return False

        # allow anything else
        return True

    def updatePackageCount(self):
        """See IDistroSeries."""

        # first update the source package count
        query = """
            SourcePackagePublishingHistory.distrorelease = %s AND
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.status = %s AND
            SourcePackagePublishingHistory.pocket = %s AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename =
                SourcePackageName.id
            """ % sqlvalues(self, self.main_archive,
                            PackagePublishingStatus.PUBLISHED,
                            PackagePublishingPocket.RELEASE)
        self.sourcecount = SourcePackageName.select(
            query, distinct=True,
            clauseTables=['SourcePackageRelease',
                          'SourcePackagePublishingHistory']).count()


        # next update the binary count
        clauseTables = ['DistroArchRelease', 'BinaryPackagePublishingHistory',
                        'BinaryPackageRelease']
        query = """
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id AND
            BinaryPackagePublishingHistory.status = %s AND
            BinaryPackagePublishingHistory.pocket = %s AND
            BinaryPackagePublishingHistory.distroarchrelease =
                DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s AND
            BinaryPackagePublishingHistory.archive = %s
            """ % sqlvalues(
                PackagePublishingStatus.PUBLISHED,
                PackagePublishingPocket.RELEASE,
                self, self.main_archive)
        ret = BinaryPackageName.select(
            query, distinct=True, clauseTables=clauseTables).count()
        self.binarycount = ret

    @property
    def architecturecount(self):
        """See IDistroSeries."""
        return self.architectures.count()

    # XXX: this is expensive and shouldn't be a property
    #   -- kiko, 2006-06-14
    @property
    def potemplates(self):
        result = POTemplate.selectBy(distroseries=self)
        result = result.prejoin(['potemplatename'])
        return sorted(result,
            key=lambda x: (-x.priority, x.potemplatename.name))

    # XXX: this is expensive and shouldn't be a property
    #   -- kiko, 2006-06-14
    @property
    def currentpotemplates(self):
        result = POTemplate.selectBy(distroseries=self, iscurrent=True)
        result = result.prejoin(['potemplatename'])
        return sorted(result,
            key=lambda x: (-x.priority, x.potemplatename.name))

    @property
    def fullseriesname(self):
        return "%s %s" % (
            self.distribution.name.capitalize(), self.name.capitalize())

    @property
    def bugtargetname(self):
        """See IBugTarget."""
        return self.fullseriesname

    def searchTasks(self, search_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        search_params.setDistroSeries(self)
        return BugTaskSet().search(search_params)

    def getUsedBugTags(self):
        """See IBugTarget."""
        return get_bug_tags("BugTask.distrorelease = %s" % sqlvalues(self))

    def getUsedBugTagsWithOpenCounts(self, user):
        """See IBugTarget."""
        return get_bug_tags_open_count(
            "BugTask.distrorelease = %s" % sqlvalues(self), user)

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    def specifications(self, sort=None, quantity=None, filter=None):
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
            order = ['-priority', 'Specification.status', 'Specification.name']
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
        base = 'Specification.distrorelease = %s' % self.id
        query = base
        # look for informational specs
        if SpecificationFilter.INFORMATIONAL in filter:
            query += ' AND Specification.informational IS TRUE'

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

        # now do the query, and remember to prejoin to people
        results = Specification.select(query, orderBy=order, limit=quantity)
        return results.prejoin(['assignee', 'approver', 'drafter'])

    def getSpecification(self, name):
        """See ISpecificationTarget."""
        return self.distribution.getSpecification(name)

    def getDistroSeriesLanguage(self, language):
        """See IDistroSeries."""
        return DistroSeriesLanguage.selectOneBy(
            distroseries=self, language=language)

    def getDistroSeriesLanguageOrDummy(self, language):
        """See IDistroSeries."""
        drl = self.getDistroSeriesLanguage(language)
        if drl is not None:
            return drl
        return DummyDistroSeriesLanguage(self, language)

    def updateStatistics(self, ztm):
        """See IDistroSeries."""
        # first find the set of all languages for which we have pofiles in
        # the distribution
        langidset = set(
            language.id for language in Language.select('''
                Language.visible = TRUE AND
                Language.id = POFile.language AND
                POFile.potemplate = POTemplate.id AND
                POTemplate.distrorelease = %s AND
                POTemplate.iscurrent = TRUE
                ''' % sqlvalues(self.id),
                orderBy=['code'],
                distinct=True,
                clauseTables=['POFile', 'POTemplate'])
            )
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
        for potemplate in self.currentpotemplates:
            messagecount += potemplate.messageCount()
        self.messagecount = messagecount
        ztm.commit()

    def getSourcePackage(self, name):
        """See IDistroSeries."""
        if not ISourcePackageName.providedBy(name):
            try:
                name = SourcePackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return SourcePackage(sourcepackagename=name, distroseries=self)

    def getBinaryPackage(self, name):
        """See IDistroSeries."""
        if not IBinaryPackageName.providedBy(name):
            try:
                name = BinaryPackageName.byName(name)
            except SQLObjectNotFound:
                return None
        return DistroSeriesBinaryPackage(self, name)

    def getSourcePackageRelease(self, sourcepackagerelease):
        """See IDistroSeries."""
        return DistroSeriesSourcePackageRelease(self, sourcepackagerelease)

    def __getitem__(self, archtag):
        """See IDistroSeries."""
        item = DistroArchSeries.selectOneBy(
            distroseries=self, architecturetag=archtag)
        if item is None:
            raise NotFoundError('Unknown architecture %s for %s %s' % (
                archtag, self.distribution.name, self.name))
        return item

    def getTranslatableSourcePackages(self):
        """See IDistroSeries."""
        query = """
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.iscurrent = TRUE AND
            POTemplate.distrorelease = %s""" % sqlvalues(self.id)
        result = SourcePackageName.select(query, clauseTables=['POTemplate'],
            orderBy=['name'], distinct=True)
        return [SourcePackage(sourcepackagename=spn, distroseries=self) for
            spn in result]

    def getUnlinkedTranslatableSourcePackages(self):
        """See IDistroSeries."""
        # Note that both unlinked packages and
        # linked-with-no-productseries packages are considered to be
        # "unlinked translatables".
        query = """
            SourcePackageName.id NOT IN (SELECT DISTINCT
             sourcepackagename FROM Packaging WHERE distrorelease = %s) AND
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.distrorelease = %s""" % sqlvalues(self.id, self.id)
        unlinked = SourcePackageName.select(query, clauseTables=['POTemplate'],
              orderBy=['name'])
        query = """
            Packaging.sourcepackagename = SourcePackageName.id AND
            Packaging.productseries = NULL AND
            POTemplate.sourcepackagename = SourcePackageName.id AND
            POTemplate.distrorelease = %s""" % sqlvalues(self.id)
        linked_but_no_productseries = SourcePackageName.select(query,
            clauseTables=['POTemplate', 'Packaging'], orderBy=['name'])
        result = unlinked.union(linked_but_no_productseries)
        return [SourcePackage(sourcepackagename=spn, distroseries=self) for
            spn in result]

    def getPublishedReleases(self, sourcepackage_or_name, version=None,
                             pocket=None, include_pending=False,
                             exclude_pocket=None, archive=None):
        """See IDistroSeries."""
        # XXX cprov 20060213: we need a standard and easy API, no need
        # to support multiple type arguments, only string name should be
        # the best choice in here, the call site will be clearer.
        # bug # 31317
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
        distrorelease=%s
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

        if archive is None:
            archive = self.main_archive
        queries.append("archive=%s" % sqlvalues(archive))

        published = SourcePackagePublishingHistory.select(
            " AND ".join(queries),
            clauseTables = ['SourcePackageRelease'])

        return shortlist(published)

    def isUnstable(self):
        """See IDistroSeries."""
        return self.status in [
            DistroSeriesStatus.FROZEN,
            DistroSeriesStatus.DEVELOPMENT,
            DistroSeriesStatus.EXPERIMENTAL,
        ]

    def getSourcesPublishedForAllArchives(self):
        """See IDistroSeries."""
        queries = ['distrorelease=%s AND status=%s AND archive=%s' %
                   sqlvalues(self, PackagePublishingStatus.PUBLISHED,
                             self.main_archive)]
        if not self.isUnstable():
            queries.append(
                'pocket != %s' % sqlvalues(PackagePublishingPocket.RELEASE))

        main_sources = SourcePackagePublishingHistory.select(
            " AND ".join(queries), orderBy="id")

        query = """
        distrorelease=%s AND status=%s AND archive <> %s
        """ % sqlvalues(self, PackagePublishingStatus.PUBLISHED,
                        self.main_archive)
        ppa_sources = SourcePackagePublishingHistory.select(query, orderBy="id")

        return main_sources.union(ppa_sources)

    def getSourcePackagePublishing(self, status, pocket, component=None,
                                   archive=None):
        """See IDistroSeries."""
        if archive is None:
            archive = self.main_archive

        clause = """
            SourcePackagePublishingHistory.sourcepackagerelease=
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename=
                SourcePackageName.id AND
            SourcePackagePublishingHistory.distrorelease=%s AND
            SourcePackagePublishingHistory.archive = %s AND
            SourcePackagePublishingHistory.status=%s AND
            SourcePackagePublishingHistory.pocket=%s
            """ %  sqlvalues(self, archive, status, pocket)

        if component:
            clause += (
                " AND SourcePackagePublishingHistory.component=%s" %
                sqlvalues(component)
                )

        orderBy = ['SourcePackageName.name']
        clauseTables = ['SourcePackageRelease', 'SourcePackageName']

        return SourcePackagePublishingHistory.select(
            clause, orderBy=orderBy, clauseTables=clauseTables)

    def getBinaryPackagePublishing(
        self, name=None, version=None, archtag=None, sourcename=None,
        orderBy=None, pocket=None, component=None, archive=None):
        """See IDistroSeries."""
        if archive is None:
            archive = self.main_archive

        query = ["""
        BinaryPackagePublishingHistory.binarypackagerelease =
            BinaryPackageRelease.id AND
        BinaryPackagePublishingHistory.distroarchrelease =
            DistroArchRelease.id AND
        BinaryPackageRelease.binarypackagename =
            BinaryPackageName.id AND
        BinaryPackageRelease.build =
            Build.id AND
        Build.sourcepackagerelease =
            SourcePackageRelease.id AND
        SourcePackageRelease.sourcepackagename =
            SourcePackageName.id AND
        DistroArchRelease.distrorelease = %s AND
        BinaryPackagePublishingHistory.archive = %s AND
        BinaryPackagePublishingHistory.status = %s
        """ % sqlvalues(self, archive, PackagePublishingStatus.PUBLISHED)]

        if name:
            query.append('BinaryPackageName.name = %s' % sqlvalues(name))

        if version:
            query.append('BinaryPackageRelease.version = %s'
                      % sqlvalues(version))

        if archtag:
            query.append('DistroArchRelease.architecturetag = %s'
                      % sqlvalues(archtag))

        if sourcename:
            query.append('SourcePackageName.name = %s' % sqlvalues(sourcename))

        if pocket:
            query.append(
                'BinaryPackagePublishingHistory.pocket = %s'
                % sqlvalues(pocket))

        if component:
            query.append(
                'BinaryPackagePublishingHistory.component = %s'
                % sqlvalues(component))

        query = " AND ".join(query)

        clauseTables = ['BinaryPackagePublishingHistory', 'DistroArchRelease',
                        'BinaryPackageRelease', 'BinaryPackageName', 'Build',
                        'SourcePackageRelease', 'SourcePackageName' ]

        result = BinaryPackagePublishingHistory.select(
            query, distinct=False, clauseTables=clauseTables, orderBy=orderBy)

        return result

    def publishedBinaryPackages(self, component=None):
        """See IDistroSeries."""
        # XXX sabdfl 04/07/05 this can become a utility when that works
        # this is used by the debbugs import process, mkdebwatches
        pubpkgset = getUtility(IPublishedPackageSet)
        result = pubpkgset.query(distroseries=self, component=component)
        return [BinaryPackageRelease.get(pubrecord.binarypackagerelease)
                for pubrecord in result]

    def getBuildRecords(self, status=None, name=None, pocket=None):
        """See IHasBuildRecords"""
        # find out the distroarchseries in question
        arch_ids = [arch.id for arch in self.architectures]
        # use facility provided by IBuildSet to retrieve the records
        return getUtility(IBuildSet).getBuildsByArchIds(
            arch_ids, status, name, pocket)

    def createUploadedSourcePackageRelease(
        self, sourcepackagename, version, maintainer, builddepends,
        builddependsindep, architecturehintlist, component, creator,
        urgency, changelog, dsc, dscsigningkey, section, manifest,
        dsc_maintainer_rfc822, dsc_standards_version, dsc_format,
        dsc_binaries, archive, dateuploaded=DEFAULT):
        """See IDistroSeries."""
        return SourcePackageRelease(
            uploaddistroseries=self, sourcepackagename=sourcepackagename,
            version=version, maintainer=maintainer, dateuploaded=dateuploaded,
            builddepends=builddepends, builddependsindep=builddependsindep,
            architecturehintlist=architecturehintlist, component=component,
            creator=creator, urgency=urgency, changelog=changelog, dsc=dsc,
            dscsigningkey=dscsigningkey, section=section, manifest=manifest,
            dsc_maintainer_rfc822=dsc_maintainer_rfc822, dsc_format=dsc_format,
            dsc_standards_version=dsc_standards_version,
            dsc_binaries=dsc_binaries, upload_archive=archive)

    def getComponentByName(self, name):
        """See IDistroSeries."""
        comp = Component.byName(name)
        if comp is None:
            raise NotFoundError(name)
        permitted = set(self.components)
        if comp in permitted:
            return comp
        raise NotFoundError(name)

    def getSectionByName(self, name):
        """See IDistroSeries."""
        section = Section.byName(name)
        if section is None:
            raise NotFoundError(name)
        permitted = set(self.sections)
        if section in permitted:
            return section
        raise NotFoundError(name)

    def removeOldCacheItems(self, log):
        """See IDistroSeries."""

        # get the set of package names that should be there
        bpns = set(BinaryPackageName.select("""
            BinaryPackagePublishingHistory.distroarchrelease =
                DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s AND
            BinaryPackagePublishingHistory.archive = %s AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id AND
            BinaryPackagePublishingHistory.status != %s
            """ % sqlvalues(self, self.main_archive,
                            PackagePublishingStatus.REMOVED),
            distinct=True,
            clauseTables=['BinaryPackagePublishingHistory',
                          'DistroArchRelease',
                          'BinaryPackageRelease']))

        # remove the cache entries for binary packages we no longer want
        for cache in self.binary_package_caches:
            if cache.binarypackagename not in bpns:
                log.debug(
                    "Removing binary cache for '%s' (%s)"
                    % (cache.name, cache.id))
                cache.destroySelf()

    def updateCompletePackageCache(self, log, ztm):
        """See IDistroSeries."""

        # get the set of package names to deal with
        bpns = list(BinaryPackageName.select("""
            BinaryPackagePublishingHistory.distroarchrelease =
                DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s AND
            BinaryPackagePublishingHistory.archive = %s AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename =
                BinaryPackageName.id AND
            BinaryPackagePublishingHistory.status != %s
            """ % sqlvalues(self, self.main_archive,
                            PackagePublishingStatus.REMOVED),
            distinct=True,
            clauseTables=['BinaryPackagePublishingHistory',
                          'DistroArchSeries',
                          'BinaryPackageRelease']))

        # now ask each of them to update themselves. commit every 100
        # packages
        counter = 0
        for bpn in bpns:
            log.debug("Considering binary '%s'" % bpn.name)
            self.updatePackageCache(bpn, log)
            counter += 1
            if counter > 99:
                counter = 0
                if ztm is not None:
                    log.debug("Committing")
                    ztm.commit()


    def updatePackageCache(self, binarypackagename, log):
        """See IDistroSeries."""

        # get the set of published binarypackagereleases
        bprs = BinaryPackageRelease.select("""
            BinaryPackageRelease.binarypackagename = %s AND
            BinaryPackageRelease.id =
                BinaryPackagePublishingHistory.binarypackagerelease AND
            BinaryPackagePublishingHistory.distroarchrelease =
                DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s AND
            BinaryPackagePublishingHistory.archive = %s AND
            BinaryPackagePublishingHistory.status != %s
            """ % sqlvalues(binarypackagename, self, self.main_archive,
                            PackagePublishingStatus.REMOVED),
            orderBy='-datecreated',
            clauseTables=['BinaryPackagePublishingHistory',
                          'DistroArchRelease'],
            distinct=True)
        if bprs.count() == 0:
            log.debug("No binary releases found.")
            return

        # find or create the cache entry
        cache = DistroSeriesPackageCache.selectOne("""
            distrorelease = %s AND
            binarypackagename = %s
            """ % sqlvalues(self.id, binarypackagename.id))
        if cache is None:
            log.debug("Creating new binary cache entry.")
            cache = DistroSeriesPackageCache(
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
        """See IDistroSeries."""
        drpcaches = DistroSeriesPackageCache.select("""
            distrorelease = %s AND (
            fti @@ ftq(%s) OR
            DistroSeriesPackageCache.name ILIKE '%%' || %s || '%%')
            """ % (quote(self.id), quote(text), quote_like(text)),
            selectAlso='rank(fti, ftq(%s)) AS rank' % sqlvalues(text),
            orderBy=['-rank'],
            prejoins=['binarypackagename'],
            distinct=True)
        return [DistroSeriesBinaryPackage(
            distroseries=self,
            binarypackagename=drpc.binarypackagename) for drpc in drpcaches]

    def newArch(self, architecturetag, processorfamily, official, owner):
        """See IDistroSeries."""
        dar = DistroArchSeries(architecturetag=architecturetag,
            processorfamily=processorfamily, official=official,
            distroseries=self, owner=owner)
        return dar

    def newMilestone(self, name, dateexpected=None):
        """See IDistroSeries."""
        return Milestone(name=name, dateexpected=dateexpected,
            distribution=self.distribution, distroseries=self)

    def getLastUploads(self):
        """See IDistroSeries."""
        query = """
        sourcepackagerelease.id=packageuploadsource.sourcepackagerelease
        AND sourcepackagerelease.sourcepackagename=sourcepackagename.id
        AND packageuploadsource.packageupload=packageupload.id
        AND packageupload.status=%s
        AND packageupload.distrorelease=%s
        """ % sqlvalues(PackageUploadStatus.DONE, self)

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
        """See IDistroSeries."""
        # We store the changes file in the librarian to avoid having to
        # deal with broken encodings in these files; this will allow us
        # to regenerate these files as necessary.
        #
        # The use of StringIO here should be safe: we do not encoding of
        # the content in the changes file (as doing so would be guessing
        # at best, causing unpredictable corruption), and simply pass it
        # off to the librarian.
        changes_file = getUtility(ILibraryFileAliasSet).create(
            changesfilename, len(changesfilecontent),
            StringIO(changesfilecontent), 'text/plain')

        return PackageUpload(
            distroseries=self, status=PackageUploadStatus.NEW,
            pocket=pocket, archive=archive,
            changesfile=changes_file, signing_key=signing_key)

    def getPackageUploadQueue(self, state):
        """See IDistroSeries."""
        return PackageUploadQueue(self, state)

    def getQueueItems(self, status=None, name=None, version=None,
                      exact_match=False, pocket=None, archive=None):
        """See IDistroSeries."""

        default_clauses = ["""
            packageupload.distrorelease = %s""" % sqlvalues(self)]

        # restrict result to a given archive
        if archive is None:
            archive = self.main_archive

        default_clauses.append("""
        packageupload.archive = %s""" % sqlvalues(archive))

        # restrict result to a given pocket
        if pocket is not None:
            if not isinstance(pocket, list):
                pocket = [pocket]
            default_clauses.append("""
            packageupload.pocket IN %s""" % sqlvalues(pocket))

        # XXX cprov 20060606: We may reorganise this code, creating
        # some new methods provided by IPackageUploadSet, as:
        # getByStatus and getByName.
        if not status:
            assert not version and not exact_match
            return PackageUpload.select(
                " AND ".join(default_clauses),
                orderBy=['-id'])

        if not isinstance(status, list):
            status = [status]

        default_clauses.append("""
        packageupload.status IN %s""" % sqlvalues(status))

        if not name:
            assert not version and not exact_match
            return PackageUpload.select(
                " AND ".join(default_clauses),
                orderBy=['-id'])

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
            source_where_clauses.append("sourcepackagename.name = '%s'" % name)
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
        # targetted to be fixed in that series, which is rarely the case for a
        # brand new bug report.
        raise NotImplementedError(
            "A new bug cannot be filed directly on a distribution series, "
            "because series are meant for \"targeting\" a fix to a specific "
            "release. It's possible that we may change this behaviour to "
            "allow filing a bug on a distribution series in the "
            "not-too-distant future. For now, you probably meant to file "
            "the bug on the distribution instead.")

    def _getBugTaskContextClause(self):
        """See BugTargetBase."""
        return 'BugTask.distrorelease = %s' % sqlvalues(self)

    def initialiseFromParent(self):
        """See IDistroSeries."""
        archive = self.main_archive
        assert self.parentseries is not None, "Parent series must be present"
        assert SourcePackagePublishingHistory.selectBy(
            distroseries=self, archive=archive).count() == 0, \
            "Source Publishing must be empty"
        for arch in self.architectures:
            assert BinaryPackagePublishingHistory.selectBy(
                distroarchseries=arch, archive=archive).count() == 0, \
                "Binary Publishing must be empty"
            try:
                parent_arch = self.parentseries[arch.architecturetag]
                assert parent_arch.processorfamily == arch.processorfamily, \
                       "The arch tags must match the processor families."
            except KeyError:
                raise AssertionError("Parent series lacks %s" % (
                    arch.architecturetag))
        assert self.nominatedarchindep is not None, \
               "Must have a nominated archindep architecture."
        assert self.components.count() == 0, \
               "Component selections must be empty."
        assert self.sections.count() == 0, \
               "Section selections must be empty."

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
        self._copy_component_and_section_selections(cur)
        self._copy_source_publishing_records(cur)
        for arch in self.architectures:
            parent_arch = self.parentseries[arch.architecturetag]
            self._copy_binary_publishing_records(cur, arch, parent_arch)
        self._copy_lucille_config(cur)

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
            ''' % sqlvalues(self.parentseries.id, self.id))

    def _copy_binary_publishing_records(self, cur, arch, parent_arch):
        """Copy the binary publishing records from the parent arch series
        to the given arch series in ourselves.

        We copy all PENDING and PUBLISHED records as PENDING into our own
        publishing records.

        We copy only the RELEASE pocket.
        """
        cur.execute('''
            INSERT INTO SecureBinaryPackagePublishingHistory (
                binarypackagerelease, distroarchrelease, status,
                component, section, priority, archive, datecreated,
                datepublished, pocket, embargo)
            SELECT bpph.binarypackagerelease, %s as distroarchrelease,
                   bpph.status, bpph.component, bpph.section, bpph.priority,
                   %s as archive, %s as datecreated, %s as datepublished,
                   %s as pocket, false as embargo
            FROM BinaryPackagePublishingHistory AS bpph
            WHERE bpph.distroarchrelease = %s AND bpph.status in (%s, %s) AND
                  bpph.pocket = %s and bpph.archive = %s
            ''' % sqlvalues(arch.id, self.main_archive, UTC_NOW, UTC_NOW,
                            PackagePublishingPocket.RELEASE,
                            parent_arch.id,
                            PackagePublishingStatus.PENDING,
                            PackagePublishingStatus.PUBLISHED,
                            PackagePublishingPocket.RELEASE,
                            self.parentseries.main_archive))

    def _copy_source_publishing_records(self, cur):
        """Copy the source publishing records from our parent distro series.

        We copy all PENDING and PUBLISHED records as PENDING into our own
        publishing records.

        We copy only the RELEASE pocket.
        """
        cur.execute('''
            INSERT INTO SecureSourcePackagePublishingHistory (
                sourcepackagerelease, distrorelease, status, component,
                section, archive, datecreated, datepublished, pocket, embargo)
            SELECT spph.sourcepackagerelease, %s as distrorelease,
                   spph.status, spph.component, spph.section, %s as archive,
                   %s as datecreated, %s as datepublished,
                   %s as pocket, false as embargo
            FROM SourcePackagePublishingHistory AS spph
            WHERE spph.distrorelease = %s AND spph.status in (%s, %s) AND
                  spph.pocket = %s and spph.archive = %s
            ''' % sqlvalues(self.id, self.main_archive, UTC_NOW, UTC_NOW,
                            PackagePublishingPocket.RELEASE,
                            self.parentseries.id,
                            PackagePublishingStatus.PENDING,
                            PackagePublishingStatus.PUBLISHED,
                            PackagePublishingPocket.RELEASE,
                            self.parentseries.main_archive))

    def _copy_component_and_section_selections(self, cur):
        """Copy the section and component selections from the parent distro
        series into this one.
        """
        # Copy the component selections
        cur.execute('''
            INSERT INTO ComponentSelection (distroseries, component)
            SELECT %s AS distrorelease, cs.component AS component
            FROM ComponentSelection AS cs WHERE cs.distrorelease = %s
            ''' % sqlvalues(self.id, self.parentseries.id))
        # Copy the section selections
        cur.execute('''
            INSERT INTO SectionSelection (distrorelease, section)
            SELECT %s as distrorelease, ss.section AS section
            FROM SectionSelection AS ss WHERE ss.distrorelease = %s
            ''' % sqlvalues(self.id, self.parentseries.id))


    def _getRawHoldingTableName(self, tablename, suffix=''):
        """Name for a holding table, but without quotes.  Use with care."""
        if suffix:
            suffix = '_%s' % suffix
        return "temp_%s_holding_%s%s" % (
            str(tablename), str(self.name), suffix)

    def _getHoldingTableName(self, tablename, suffix=''):
        """Name for a holding table to hold data being copied in tablename.

        This name is used in copying translation data from the parent
        distroseries to self.  To reduce locking on the database, applicable
        data is first copied to these holding tables, then modified there, and
        finally moved back into the original table "tablename."

        Return value is properly quoted for use as an SQL identifier.
        """
        return str(
            quoteIdentifier(self._getRawHoldingTableName(tablename, suffix)))


    def _extractToHoldingTable(self,
            ztm,
            logger,
            source_table,
            joins=None,
            where_clause=None,
            id_sequence=None):
        """Extract (selected) rows from source_table into a holding table.

        This method is used to copy a distroseries's current translation
        elements to a new distroseries.  The idea is that all translation
        data can be copied into holding tables first (without starving other
        users of database service through excessive locking), and provided
        with new row ids so they can be directly re-inserted into the original
        tables.

        A new table is created and filled with any records from source_table
        that match filtering criteria passed in where_clause.  The new table's
        name is constructed as self._getHoldingTableName(source_table).  If a
        table of that name already existed, it is dropped first.

        The new table gets an additional new_id column with identifiers in the
        seqid sequence; the name seqid defaults to the original table name in
        lower case, with "_seq_id" appended.  Apart from this extra column,
        indexes, and constraints, the holding table is schematically identical
        to source_table.  A unique index is created for the original id
        column.

        There is a special facility for redirecting foreign keys to other
        tables copied in the same way.  If the joins argument is a nonempty
        list, the selection used in creating the new table  will be joined
        with each of the tables named in joins, on foreign keys in the current
        table.  The foreign keys in the holding table will point to the
        new_ids of the copied rows, rather than the original ids.  Rows in
        source_table will only be copied to their holding table if all rows
        they are joined with in those other tables were also copied to holding
        tables of their own.

        The foreign keys are assumed to have the same names as the tables
        they refer to, but written in lower-case letters.

        When joining, the added tables' columns are not included in the
        holding table, but where_clause may select on them.
        """
        if id_sequence is None:
            id_sequence = "%s_id_seq" % source_table.lower()

        if joins is None:
            joins = []

        holding_table = self._getHoldingTableName(source_table)

        logger.info('Extracting from %s into %s...' % (
            source_table,holding_table))

        starttime = time.time()

        # Selection clauses for our foreign keys
        new_fks = [
            "%s.new_id AS new_%s" % (self._getHoldingTableName(j), j.lower())
            for j in joins
        ]

        # Combined "where" clauses
        where = [
            "%s = %s.id" % (j.lower(), self._getHoldingTableName(j))
            for j in joins
        ]
        if where_clause is not None:
            where.append('(%s)' % where_clause)

        cur = cursor()

        # We use a regular, persistent table rather than a temp table for
        # this so that we get a chance to resume interrupted copies, and
        # analyse failures.  If we used temp tables, they'd be gone by the
        # time we knew something went wrong.
        # For each row we append at the end any new foreign key values, and
        # finally a "new_id" holding its future id field.  This new_id value
        # is allocated from the original table's id sequence, so it will be
        # unique in the original table.
        fk_list = ', '.join(['%s.*' % source_table] + new_fks)
        from_list = ', '.join([source_table] +
                              ['%s' % self._getHoldingTableName(j)
                               for j in joins])
        cur.execute('''
            CREATE TABLE %s AS
            SELECT %s, nextval('%s'::regclass) AS new_id
            FROM %s
            WHERE %s ''' % (holding_table,
                            fk_list,
                            id_sequence,
                            from_list,
                            ' AND '.join(where)))

        if len(joins) > 0:
            # Replace foreign keys with their "new_" variants, then drop those
            # "new_" columns we added.
            fkupdates = [
                "%s = new_%s" % (j.lower(),j.lower()) for j in joins
            ]
            updatestr = ', '.join(fkupdates)
            logger.info("Redirecting foreign keys: %s" % updatestr)
            cur.execute('''
                UPDATE %s
                SET %s
            ''' % (holding_table, updatestr))
            for j in joins:
                column = j.lower()
                logger.info("Dropping foreign-key column %s" % column)
                cur.execute('''
                    ALTER TABLE %s DROP COLUMN new_%s''' % (holding_table,
                                                            column))

        # Now that our new holding table is in a stable state, index its id
        logger.info("Indexing %s" % holding_table)
        cur.execute('''
            CREATE UNIQUE INDEX %s
            ON %s (id)
        ''' % (self._getHoldingTableName(source_table, 'id'), holding_table))
        logger.info('...Extracted in %.3f seconds' % (time.time()-starttime))


    # These are the tables that need data to be copied when a new
    # distroseries is opened for translation.  The order matters to several
    # methods.
    # Ordering of this list is significant for two reasons:
    # 1. To maintain referential integrity while pouring--we can't insert
    #    a row into a source table if it has a foreign key matched up with
    #    another row in another table that hasn't been poured yet.
    # 2. The _hasRecoverableHoldingTables() method must know what the first
    #    and last tables in this list are, so it can correctly detect the
    #    state of any previous pouring run that may have been interrupted.
    _translation_tables = [
        'POTemplate', 'POTMsgSet', 'POMsgIDSighting', 'POFile',
        'POMsgSet', 'POSubmission'
        ]

    def _hasRecoverableHoldingTables(self, logger):
        """Do we have holding tables with recoverable data from previous run?
        """
        # The tables named here are the first and last tables in the list that
        # _pourHoldingTables() goes through.  Keep it that way, or this will
        # return incorrect information!

        cur = cursor()

        # If there are any holding tables to be poured into their source
        # tables, there must at least be one for the last table that
        # _pourHoldingTables() processes.
        if not postgresql.have_table(cur,
                self._getRawHoldingTableName(self._translation_tables[-1])):
            return False

        # If the first table in our list also still exists, and it still has
        # its new_id column, then the pouring process had not begun yet.
        # Assume the data was not ready for pouring.
        if postgresql.table_has_column(cur,
                self._getRawHoldingTableName(self._translation_tables[0]),
                'new_id'):
            logger.info(
                "Previous run aborted too early for recovery; redo all")
            return False

        logger.info("Recoverable data found")
        return True


    def _pourHoldingTables(self, logger, ztm):
        """Attempt to pour translation holding tables back into source tables.

        ztm is committed and re-opened at the beginning of each run.  This is
        done so the caller still has a chance to play atomically with the
        holding table's data.
        """
        if ztm is not None:
            commitstart = time.time()
            ztm.commit()
            logger.info("Committed in %.3f seconds" % (
                time.time()-commitstart))
            ztm.begin()

        cur = cursor()

        # Main loop: for each of the source tables involved in copying
        # translations from our parent distroseries, see if there's a
        # matching holding table; prepare it, pour it back into the source
        # table, and drop.
        for table in self._translation_tables:
            holding_table = self._getHoldingTableName(table)
            holding_table_unquoted = self._getRawHoldingTableName(table)

            if not postgresql.have_table(cur, holding_table_unquoted):
                # We know we're in a suitable state for pouring.  If this
                # table does not exist, it must be because it's been poured
                # out completely and dropped in an earlier instance of this
                # loop, before the failure we're apparently recovering from.
                continue

            # XXX: JeroenVermeulen 2007-05-02, Lock holding table maybe, to
            # protect against accidental concurrent runs?  Insouciant as it
            # may seem not to do that, all but one run would fail anyway
            # because of the unique index on id.  But a lock would give us a
            # more helpful error message.
            logger.info("Pouring %s back into %s..." % (holding_table,table))

            tablestarttime = time.time()

            if postgresql.table_has_column(cur, holding_table_unquoted,
                                           'new_id'):
                # Update ids in holding table from originals to copies.
                # (If this is where we got interrupted by a failure in a
                # previous run, no harm in doing it again)
                cur.execute("UPDATE %s SET id=new_id" % holding_table)
                # Restore table to original schema
                cur.execute("ALTER TABLE %s DROP COLUMN new_id" %
                    holding_table)
                logger.info("...rearranged ids in %.3f seconds..." %
                    (time.time()-tablestarttime))

            # Workaround: force postgres to keep using the id index on our
            # holding table, even after we've deleted lots of rows.
            cur.execute("SET enable_seqscan=false")

            # Now pour holding table's data into its source table.  This is
            # where we start writing to tables that other clients will be
            # reading, so row locks are a concern.  Break the writes up in
            # batches of a few thousand rows.  The goal is to have these
            # transactions running no longer than five seconds or so each.

            # We batch simply by breaking the range of ids in our table down
            # into fixed-size intervals.  Some of those fixed-size intervals
            # may not have any rows in them, or very few.  That's not likely
            # to be a problem though since we allocated all these ids in one
            # single SQL statement.  No time for gaps to form.
            cur.execute("SELECT min(id), max(id) FROM %s" % holding_table)
            lowest_id, highest_id = cur.fetchall()[0]
            total_rows = highest_id + 1 - lowest_id
            logger.info("Up to %d rows in holding table" % total_rows)

            if ztm is not None:
                precommitstart = time.time()
                ztm.commit()
                logger.info("...pre-commit in %.3f seconds..." % (
                    time.time() - precommitstart))
                ztm.begin()
                cur = cursor()

            # Minimum batch size.  We never process fewer rows than this in
            # one batch because at that level, we expect to be running into
            # more or less constant transaction costs.  Reducing batch size
            # any further is not likely to help much, but will make the
            # overall procedure take much longer.
            min_batch_size = 1000

            # The number of seconds we want each transaction to take.  The
            # batching algorithm tries to approximate this batch time by
            # varying actual batch_size.
            time_goal = 4

            # When's the last time we re-generated statistics on our id
            # column?  When that information stales, performance degrades very
            # suddenly and very dramatically.

            batch_size = min_batch_size
            while lowest_id <= highest_id:
                # Step through ids backwards.  This appears to be faster,
                # possibly because we're removing records from the end of the
                # table instead of from the beginning, or perhaps it makes
                # rebalancing the index a bit easier.
                next = highest_id - batch_size
                logger.info("Moving %d ids: %d-%d..." % (
                    highest_id - next, next, highest_id))
                batchstarttime = time.time()

                cur.execute('''
                    INSERT INTO %s (
                        SELECT *
                        FROM %s
                        WHERE id >= %d
                    )''' % (table, holding_table, next))
                cur.execute('''
                    DELETE FROM %s
                    WHERE id >= %d
                ''' % (holding_table, next))

                if ztm is not None:
                    ztm.commit()
                    ztm.begin()
                    cur = cursor()

                highest_id = next

                time_taken = time.time() - batchstarttime
                logger.info("...batch done in %.3f seconds (%d%%)." % (
                    time_taken,
                    100*(total_rows + lowest_id - highest_id)/total_rows))


                # Adjust batch_size to approximate time_goal.  The new
                # batch_size is the average of two values: the previous value
                # for batch_size, and an estimate of how many rows would take
                # us to exactly time_goal seconds.  The estimate is very
                # simple: rows per second on the last commit.
                # The weight in this estimate of any given historic datum
                # decays exponentially with an exponent of 1/2.  This softens
                # the blows from spikes and dips in processing time.
                # Set a reasonable minimum for time_taken, just in case we get
                # weird values for whatever reason and destabilize the
                # algorithm.
                time_taken = max(time_goal/10, time_taken)
                batch_size = batch_size*(1 + time_goal/time_taken)/2
                batch_size = max(batch_size, min_batch_size)

            logger.info(
                "Pouring %s took %.3f seconds." %
                    (holding_table, time.time()-tablestarttime))

            dropstart = time.time()
            cur.execute("DROP TABLE %s" % holding_table)
            logger.info("Dropped %s in %.3f seconds" % (
                holding_table, time.time() - dropstart))


    def _copyActiveTranslationsToNewRelease(self, logger, ztm):
        """We're a new series; inherit translations from parent.

        Translation data for the new series (self) is first copied into
        "holding tables" with names like "temp_POTemplate_holding_feisty" and
        processed there.  Then, at the end of the procedure, these tables are
        all copied back to their originals.

        If this procedure fails, it may leave holding tables behind.  This was
        done deliberately to leave some forensics information for failures,
        and also to allow admins to see what data has and has not been copied.

        The holding tables have names like "temp_POTemplate_holding_feisty"
        (for source table POTemplate and series feisty, in this case).

        If a holding table left behind by an abortive run has a column called
        new_id at the end, it contains unfinished data and may as well be
        dropped.  If it does not have that column, the holding table was
        already in the process of being copied back to its origin table.  In
        that case the sensible thing to do is probably to continue copying it.
        """

        # This method was extracted as one of two cases from a huge
        # _copy_active_translations() method.  Because it only deals with the
        # case where "self" is a new series without any existing translations
        # attached, it can afford to be much more cavalier with ACID
        # considerations than the other case can.  Still, it may be possible
        # in the future to optimize _copyActiveTranslationsAsUpdate() (the
        # other of the two cases) using a similar trick.

        # Copying happens in two phases:
        #
        # 1. Extraction phase--for every table involved (which we'll call a
        # "source table" here), we create a "holding table."  We fill that with
        # all rows from the source table that we want to copy from the parent
        # series.  We make some changes to the copied rows, such as making
        # them belong to ourselves instead of our parent series.
        #
        # The first phase does not modify any tables that other clients may
        # want to use, avoiding locking problems.
        #
        # 2. Pouring phase.  From each holding table we pour all rows back
        # into the source table, deleting them from the holding table as we
        # go.  The holding table is dropped once empty.
        #
        # The second phase is "batched," moving only a small number of rows at
        # a time, then performing an intermediate commit.  This avoids holding
        # too many locks for too long and disrupting regular database service.

        if not self.hide_all_translations:
            raise AssertionError("""
_copyActiveTranslationsToNewRelease: hide_all_translations not set!

Attempted to populate translations for new distroseries while its
translations are visible.  That would allow users to see and modify incomplete
translation state.
""")

        if not self.defer_translation_imports:
            raise AssertionError("""
_copyActiveTranslationsToNewRelease: defer_translation_imports not set!

Attempted to populate translations for new distroseries while translation
import queue is enabled. That would corrupt our translation data mixing
new imports with the information being copied.
""")

        # Clean up any remains from a previous run.  If we got here, that
        # means those remains are not salvagable.

        postgresql.drop_tables(cursor(),
            [self._getHoldingTableName(t) for t in self._translation_tables])

        # Copy relevant POTemplates from existing series into a holding
        # table, complete with their original id fields.
        self._extractToHoldingTable(ztm,
            logger,
            'POTemplate',
            [],
            'distrorelease=%s AND iscurrent' % quote(self.parentseries))

        # Now that we have the data "in private," where nobody else can see
        # it, we're free to play with it.  No risk of locking other processes
        # out of the database.
        # Update series names in the holding table (right now they all bear
        # our parent's name) to our own name, and set creation dates to now.
        cursor().execute('''
            UPDATE %s
            SET
                distrorelease = %s,
                datecreated =
                    timezone('UTC'::text,
                        ('now'::text)::timestamp(6) with time zone)
        ''' % (self._getHoldingTableName('POTemplate'), quote(self)))


        # Copy each POTMsgSet whose template we copied, and replace each
        # potemplate reference with a reference to our copy of the original
        # POTMsgSet's potemplate.
        self._extractToHoldingTable(ztm,
            logger,
            'POTMsgSet',
            ['POTemplate'],
            'POTMsgSet.sequence > 0')

        # Copy POMsgIDSightings, substituting their potmsgset foreign
        # keys with references to our own, copied POTMsgSets
        self._extractToHoldingTable(ztm,
            logger,
            'POMsgIDSighting',
            ['POTMsgSet'])

        # Copy POFiles, making them refer to our copied POTemplates
        self._extractToHoldingTable(ztm,
            logger,
            'POFile',
            ['POTemplate'])

        # Same for POMsgSet, but a bit more complicated since it refers to
        # both POFile and POTMsgSet.
        self._extractToHoldingTable(ztm,
            logger,
            'POMsgSet',
            ['POFile', 'POTMsgSet'])

        # And for POSubmission
        self._extractToHoldingTable(ztm,
            logger,
            'POSubmission',
            ['POMsgSet'],
            'active OR published')

        # Now pour the holding tables back into the originals
        self._pourHoldingTables(logger, ztm)


    def _copyActiveTranslationsAsUpdate(self, logger):
        """Receive active, updated translations from parent series.
        """

        # This method was extracted as one of two cases from a huge
        # _copy_active_translations() method.  It's likely to cause problems
        # to other users while running, locking them out of the database
        # during its potentially huge updates.  We should see if we can batch
        # it into smaller chunks in order to reduce lock pressure.

        # XXX: JeroenVermeulen 2007-05-03, This method should become
        # unnecessary once the "translation multicast" spec is implemented:
        # https://launchpad.canonical.com/MulticastTranslations

        # The left outer join that obtains pf2 ensures that we only do the
        # copying for POFiles whose POTemplates don't have any POFiles yet.

        # XXX: JeroenVermeulen 2007-04-27, We must be careful when batching
        # this statement.  After one POFile is copied, pt2 will have a POFile
        # attached and its other POFiles will no longer qualify for copying.

        logger.info('Filling POFile table...')
        cur = cursor()
        cur.execute('''
            INSERT INTO POFile (
                potemplate, language, description, topcomment, header,
                fuzzyheader, lasttranslator, currentcount, updatescount,
                rosettacount, lastparsed, owner, variant, path, exportfile,
                exporttime, datecreated, last_touched_pomsgset,
                from_sourcepackagename)
            SELECT
                pt2.id AS potemplate,
                pf1.language AS language,
                pf1.description AS description,
                pf1.topcomment AS topcomment,
                pf1.header AS header,
                pf1.fuzzyheader AS fuzzyheader,
                pf1.lasttranslator AS lasttranslator,
                pf1.currentcount AS currentcount,
                pf1.updatescount AS updatescount,
                pf1.rosettacount AS rosettacount,
                pf1.lastparsed AS lastparsed,
                pf1.owner AS owner,
                pf1.variant AS variant,
                pf1.path AS path,
                pf1.exportfile AS exportfile,
                pf1.exporttime AS exporttime,
                pf1.datecreated AS datecreated,
                pf1.last_touched_pomsgset AS last_touched_pomsgset,
                pf1.from_sourcepackagename AS from_sourcepackagename
            FROM
                POTemplate AS pt1
                JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                JOIN POTemplate AS pt2 ON
                    pt2.potemplatename = pt1.potemplatename AND
                    pt2.sourcepackagename = pt1.sourcepackagename AND
                    pt2.distrorelease = %s
                LEFT OUTER JOIN POFile AS pf2 ON
                    pf2.potemplate = pt2.id AND
                    pf2.language = pf1.language AND
                    (pf2.variant = pf1.variant OR
                     (pf2.variant IS NULL AND pf1.variant IS NULL))
            WHERE
                pt1.distrorelease = %s AND
                pf2.id IS NULL''' % sqlvalues(self, self.parentseries))

        logger.info('Updating POMsgSet table...')
        cur.execute('''
            UPDATE POMsgSet SET
                iscomplete = pms1.iscomplete, isfuzzy = pms1.isfuzzy,
                isupdated = pms1.isupdated,
                reviewer = pms1.reviewer,
                date_reviewed = pms1.date_reviewed
            FROM
                POTemplate AS pt1
                JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                JOIN POTemplate AS pt2 ON
                    pt2.potemplatename = pt1.potemplatename AND
                    pt2.sourcepackagename = pt1.sourcepackagename AND
                    pt2.distrorelease = %s
                JOIN POFile AS pf2 ON
                    pf2.potemplate = pt2.id AND
                    pf2.language = pf1.language AND
                    (pf2.variant = pf1.variant OR
                     (pf2.variant IS NULL AND pf1.variant IS NULL))
                JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                JOIN POMsgSet AS pms1 ON
                    pms1.potmsgset = ptms1.id AND
                    pms1.pofile = pf1.id
                JOIN POTMsgSet AS ptms2 ON
                    ptms2.potemplate = pt2.id AND
                    ptms2.primemsgid = ptms1.primemsgid
            WHERE
                pt1.distrorelease = %s AND
                POMsgSet.potmsgset = ptms2.id AND
                POMsgSet.pofile = pf2.id AND
                POMsgSet.iscomplete = FALSE AND
                pms1.iscomplete = TRUE
                ''' % sqlvalues(self, self.parentseries))

        logger.info('Filling POMsgSet table...')
        cur.execute('''
            INSERT INTO POMsgSet (
                sequence, pofile, iscomplete, obsolete, isfuzzy, commenttext,
                potmsgset, publishedfuzzy, publishedcomplete, isupdated)
            SELECT
                pms1.sequence AS sequence,
                pf2.id AS pofile,
                pms1.iscomplete AS iscomplete,
                pms1.obsolete AS obsolete,
                pms1.isfuzzy AS isfuzzy,
                pms1.commenttext AS commenttext,
                ptms2.id AS potmsgset,
                pms1.publishedfuzzy AS publishedfuzzy,
                pms1.publishedcomplete AS publishedcomplete,
                pms1.isupdated AS isupdated
            FROM
                POTemplate AS pt1
                JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                JOIN POTemplate AS pt2 ON
                    pt2.potemplatename = pt1.potemplatename AND
                    pt2.sourcepackagename = pt1.sourcepackagename AND
                    pt2.distrorelease = %s
                JOIN POFile AS pf2 ON
                    pf2.potemplate = pt2.id AND
                    pf2.language = pf1.language AND
                    (pf2.variant = pf1.variant OR
                     (pf2.variant IS NULL AND pf1.variant IS NULL))
                JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                JOIN POMsgSet AS pms1 ON
                    pms1.potmsgset = ptms1.id AND
                    pms1.pofile = pf1.id
                JOIN POTMsgSet AS ptms2 ON
                    ptms2.potemplate = pt2.id AND
                    ptms2.primemsgid = ptms1.primemsgid
                LEFT OUTER JOIN POMsgSet AS pms2 ON
                    pms2.potmsgset = ptms2.id AND
                    pms2.pofile = pf2.id
            WHERE
                pt1.distrorelease = %s AND
                pms2.id IS NULL''' % sqlvalues(self, self.parentseries))

        # At this point, we need to know the list of POFiles that we are
        # going to modify so we can recalculate later its statistics. We
        # do this before copying POSubmission table entries because
        # otherwise we will not know exactly which one are being updated.
        logger.info('Getting the list of POFiles with changes...')
        cur.execute('''
            SELECT
                DISTINCT pf2.id
            FROM
                POTemplate AS pt1
                JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                JOIN POTemplate AS pt2 ON
                    pt2.potemplatename = pt1.potemplatename AND
                    pt2.sourcepackagename = pt1.sourcepackagename AND
                    pt2.distrorelease = %s
                JOIN POFile AS pf2 ON
                    pf2.potemplate = pt2.id AND
                    pf2.language = pf1.language AND
                    (pf2.variant = pf1.variant OR
                     (pf2.variant IS NULL AND pf1.variant IS NULL))
                JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                JOIN POMsgSet AS pms1 ON
                    pms1.potmsgset = ptms1.id AND
                    pms1.pofile = pf1.id
                JOIN POTMsgSet AS ptms2 ON
                    ptms2.potemplate = pt2.id AND
                    ptms2.primemsgid = ptms1.primemsgid
                JOIN POMsgSet AS pms2 ON
                    pms2.potmsgset = ptms2.id AND
                    pms2.pofile = pf2.id
                JOIN POSubmission AS ps1 ON
                    ps1.pomsgset = pms1.id AND
                    ps1.active
                LEFT OUTER JOIN POSubmission AS ps2 ON
                    ps2.pomsgset = pms2.id AND
                    ps2.pluralform = ps1.pluralform AND
                    ps2.potranslation = ps1.potranslation AND
                    ((ps2.published AND ps2.active) OR ps2.active = FALSE)
            WHERE
                pt1.distrorelease = %s AND ps2.id IS NULL
                ''' % sqlvalues(self, self.parentseries))

        pofile_rows = cur.fetchall()
        pofile_ids = [row[0] for row in pofile_rows]

        replacements = sqlvalues(
            series=self, parentseries=self.parentseries)

        logger.info( 'Filling POSubmission table with active rows...')
        replacements['published'] = u'FALSE'
        replacements['active'] = u'FALSE'

        cur.execute('''
            INSERT INTO POSubmission (
                pomsgset, pluralform, potranslation, origin, datecreated,
                person, validationstatus, active, published)
            SELECT
                pms2.id AS pomsgset,
                ps1.pluralform AS pluralform,
                ps1.potranslation AS potranslation,
                ps1.origin AS origin,
                ps1.datecreated AS datecreated,
                ps1.person AS person,
                ps1.validationstatus AS validationstatus,
                %(active)s,
                %(published)s
            FROM
                POTemplate AS pt1
                JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                JOIN POTemplate AS pt2 ON
                    pt2.potemplatename = pt1.potemplatename AND
                    pt2.sourcepackagename = pt1.sourcepackagename AND
                    pt2.distrorelease = %(series)s
                JOIN POFile AS pf2 ON
                    pf2.potemplate = pt2.id AND
                    pf2.language = pf1.language AND
                    (pf2.variant = pf1.variant OR
                     (pf2.variant IS NULL AND pf1.variant IS NULL))
                JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                JOIN POMsgSet AS pms1 ON
                    pms1.potmsgset = ptms1.id AND
                    pms1.pofile = pf1.id
                JOIN POTMsgSet AS ptms2 ON
                    ptms2.potemplate = pt2.id AND
                    ptms2.primemsgid = ptms1.primemsgid
                JOIN POMsgSet AS pms2 ON
                    pms2.potmsgset = ptms2.id AND
                    pms2.pofile = pf2.id
                JOIN POSubmission AS ps1 ON
                    ps1.pomsgset = pms1.id AND
                    (ps1.active OR %(published)s)
                LEFT OUTER JOIN POSubmission AS ps2 ON
                    ps2.pomsgset = pms2.id AND
                    ps2.pluralform = ps1.pluralform AND
                    ps2.potranslation = ps1.potranslation
            WHERE
                pt1.distrorelease = %(parentseries)s AND ps2.id IS NULL
            ''' % replacements)

        # This query will be only useful if when we already have some
        # initial translations before this method call, because is the
        # only situation when we could have POSubmission rows to update.
        logger.info(
            'Updating previous existing POSubmission rows...')
        cur.execute('''
            UPDATE POSubmission
                SET active = FALSE
                FROM
                    POTemplate AS pt1
                    JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                    JOIN POTemplate AS pt2 ON
                        pt2.potemplatename = pt1.potemplatename AND
                        pt2.sourcepackagename = pt1.sourcepackagename AND
                        pt2.distrorelease = %s
                    JOIN POFile AS pf2 ON
                        pf2.potemplate = pt2.id AND
                        pf2.language = pf1.language AND
                        (pf2.variant = pf1.variant OR
                         (pf2.variant IS NULL AND pf1.variant IS NULL))
                    JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                    JOIN POMsgSet AS pms1 ON
                        pms1.potmsgset = ptms1.id AND
                        pms1.pofile = pf1.id AND
                        pms1.iscomplete = TRUE
                    JOIN POTMsgSet AS ptms2 ON
                        ptms2.potemplate = pt2.id AND
                        ptms2.primemsgid = ptms1.primemsgid
                    JOIN POMsgSet AS pms2 ON
                        pms2.potmsgset = ptms2.id AND
                        pms2.pofile = pf2.id
                    JOIN POSubmission AS ps1 ON
                        ps1.pomsgset = pms1.id AND
                        ps1.active
                    LEFT JOIN POSubmission AS newactive_ps2 ON
                        newactive_ps2.pomsgset = pms2.id AND
                        newactive_ps2.pluralform = ps1.pluralform AND
                        newactive_ps2.potranslation = ps1.potranslation
                WHERE
                    pt1.distrorelease = %s AND
                    POSubmission.pomsgset = pms2.id AND
                    POSubmission.pluralform = ps1.pluralform AND
                    POSubmission.potranslation <> ps1.potranslation AND
                    POSubmission.active AND POSubmission.published AND
                    newactive_ps2 IS NOT NULL
                ''' % sqlvalues(self, self.parentseries))

        cur.execute('''
            UPDATE POSubmission
                SET active = TRUE
                FROM
                    POTemplate AS pt1
                    JOIN POFile AS pf1 ON pf1.potemplate = pt1.id
                    JOIN POTemplate AS pt2 ON
                        pt2.potemplatename = pt1.potemplatename AND
                        pt2.sourcepackagename = pt1.sourcepackagename AND
                        pt2.distrorelease = %s
                    JOIN POFile AS pf2 ON
                        pf2.potemplate = pt2.id AND
                        pf2.language = pf1.language AND
                        (pf2.variant = pf1.variant OR
                         (pf2.variant IS NULL AND pf1.variant IS NULL))
                    JOIN POTMsgSet AS ptms1 ON ptms1.potemplate = pt1.id
                    JOIN POMsgSet AS pms1 ON
                        pms1.potmsgset = ptms1.id AND
                        pms1.pofile = pf1.id AND
                        pms1.iscomplete = TRUE
                    JOIN POTMsgSet AS ptms2 ON
                        ptms2.potemplate = pt2.id AND
                        ptms2.primemsgid = ptms1.primemsgid
                    JOIN POMsgSet AS pms2 ON
                        pms2.potmsgset = ptms2.id AND
                        pms2.pofile = pf2.id
                    JOIN POSubmission AS ps1 ON
                        ps1.pomsgset = pms1.id AND
                        ps1.active
                    LEFT JOIN POSubmission AS active_ps2 ON
                        active_ps2.pomsgset = pms2.id AND
                        active_ps2.pluralform = ps1.pluralform AND
                        active_ps2.active
                WHERE
                    pt1.distrorelease = %s AND
                    POSubmission.pomsgset = pms2.id AND
                    POSubmission.pluralform = ps1.pluralform AND
                    POSubmission.potranslation = ps1.potranslation AND
                    NOT POSubmission.active AND
                    active_ps2 IS NULL
                ''' % sqlvalues(self, self.parentseries))

        # Update the statistics cache for every POFile we touched.
        logger.info("Updating POFile's statistics")
        for pofile_id in pofile_ids:
            pofile = POFile.get(pofile_id)
            pofile.updateStatistics()


    def _copy_active_translations(self, ztm):
        """Copy active translations from the parent into this one.

        This method is used in two scenarios: when a new distribution series
        is opened for translation, and during periodic updates as new
        translations from the parent series are ported to newer series that
        haven't provided translations of their own for the same strings yet.
        In the former scenario a full copy is drawn from the parent series.

        If this distroseries doesn't have any translatable resource, this
        method will clone all of the parent's current translatable resources;
        otherwise, only the translations that are in the parent but lacking in
        this one will be copied.

        If there is a status change but no translation is changed for a given
        message, we don't have a way to figure whether the change was done in
        the parent or this distroseries, so we don't migrate that.
        """
        if self.parent is None:
            # We don't have a parent from where we could copy translations.
            return

        logger = logging.getLogger('initialise')

        if len(self.potemplates) == 0:
            # We're a new distroseries; copy from scratch
            self._copyActiveTranslationsToNewRelease(logger, ztm)
        elif self._hasRecoverableHoldingTables(logger):
            # Recover data from previous, abortive run
            self._pourHoldingTables(logger, ztm)
        else:
            # Incremental copy of updates from parent distroseries
            self._copyActiveTranslationsAsUpdate(logger)


    def copyMissingTranslationsFromParent(self, ztm=None):
        """See IDistroSeries."""
        flush_database_updates()
        flush_database_caches()
        # Request the translation copy.
        self._copy_active_translations(ztm)

    def getPendingPublications(self, archive, pocket, is_careful):
        """See IPublishing."""
        queries = ['distrorelease = %s' % sqlvalues(self)]

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
        # We allow RELEASE uploads for PPAs.
        if not self.isUnstable() and self.main_archive == archive:
            queries.append(
            'pocket != %s' % sqlvalues(PackagePublishingPocket.RELEASE))

        publications = SourcePackagePublishingHistory.select(
            " AND ".join(queries), orderBy="-id")

        return publications

    def publish(self, diskpool, log, archive, pocket, is_careful=False):
        """See IPublishing."""
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
            more_dirt = dar.publish(diskpool, log, archive, pocket, is_careful)
            dirty_pockets.update(more_dirt)

        return dirty_pockets

    def checkLegalPocket(self, publication, is_careful, log):
        """Check if the publication can happen in the archive."""
        # careful re-publishes everything:
        if is_careful:
            return True
        # PPA allows everything (aka Hotel California).
        if publication.archive != self.main_archive:
            return True
        # If we're not republishing, we want to make sure that
        # we're not publishing packages into the wrong pocket.
        # Unfortunately for careful mode that can't hold true
        # because we indeed need to republish everything.
        if (self.isUnstable() and
            publication.pocket != PackagePublishingPocket.RELEASE):
            log.error("Tried to publish %s (%s) into a non-release "
                      "pocket on unstable series %s, skipping" %
                      (publication.displayname, publication.id,
                       self.displayname))
            return False
        if (not self.isUnstable() and
            publication.pocket == PackagePublishingPocket.RELEASE):
            log.error("Tried to publish %s (%s) into release pocket "
                      "on stable series %s, skipping" %
                      (publication.displayname, publication.id,
                       self.displayname))
            return False

        return True

    @property
    def main_archive(self):
        return self.distribution.main_archive


    def getFirstEntryToImport(self):
        """See IHasTranslationImports."""
        if self.defer_translation_imports:
            return None
        else:
            return TranslationImportQueueEntry.selectFirstBy(
                status=RosettaImportStatus.APPROVED,
                distroseries=self,
                orderBy=['dateimported'])



class DistroSeriesSet:
    implements(IDistroSeriesSet)

    def get(self, distroseriesid):
        """See IDistroSeriesSet."""
        return DistroSeries.get(distroseriesid)

    def translatables(self):
        """See IDistroSeriesSet."""
        return DistroSeries.select(
            "POTemplate.distrorelease=DistroRelease.id",
            clauseTables=['POTemplate'], distinct=True)

    def findByName(self, name):
        """See IDistroSeriesSet."""
        return DistroSeries.selectBy(name=name)

    def queryByName(self, distribution, name):
        """See IDistroSeriesSet."""
        return DistroSeries.selectOneBy(distribution=distribution, name=name)

    def findByVersion(self, version):
        """See IDistroSeriesSet."""
        return DistroSeries.selectBy(version=version)

    def search(self, distribution=None, isreleased=None, orderBy=None):
        """See IDistroSeriesSet."""
        where_clause = ""
        if distribution is not None:
            where_clause += "distribution = %s" % sqlvalues(distribution.id)
        if isreleased is not None:
            if where_clause:
                where_clause += " AND "
            if isreleased:
                # The query is filtered on released releases.
                where_clause += "releasestatus in (%s, %s)" % sqlvalues(
                    DistroSeriesStatus.CURRENT,
                    DistroSeriesStatus.SUPPORTED)
            else:
                # The query is filtered on unreleased releases.
                where_clause += "releasestatus in (%s, %s, %s)" % sqlvalues(
                    DistroSeriesStatus.EXPERIMENTAL,
                    DistroSeriesStatus.DEVELOPMENT,
                    DistroSeriesStatus.FROZEN)
        if orderBy is not None:
            return DistroSeries.select(where_clause, orderBy=orderBy)
        else:
            return DistroSeries.select(where_clause)

    def new(self, distribution, name, displayname, title, summary, description,
            version, parentseries, owner):
        """See IDistroSeriesSet."""
        return DistroSeries(
            distribution=distribution,
            name=name,
            displayname=displayname,
            title=title,
            summary=summary,
            description=description,
            version=version,
            status=DistroSeriesStatus.EXPERIMENTAL,
            parentseries=parentseries,
            owner=owner)
