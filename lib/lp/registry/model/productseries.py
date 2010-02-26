# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212
"""Models for `IProductSeries`."""

__metaclass__ = type

__all__ = [
    'ProductSeries',
    'ProductSeriesSet',
    ]

import datetime

from sqlobject import (
    ForeignKey, StringCol, SQLMultipleJoin, SQLObjectNotFound)
from storm.expr import Sum, Max
from zope.component import getUtility
from zope.interface import implements
from storm.locals import And, Desc
from storm.store import Store

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    SQLBase, quote, sqlvalues)
from lp.bugs.model.bugtarget import BugTargetBase
from lp.bugs.model.bug import (
    get_bug_tags, get_bug_tags_open_count)
from lp.bugs.model.bugtask import BugTask
from lp.services.worlddata.model.language import Language
from lp.registry.model.milestone import (
    HasMilestonesMixin, Milestone)
from lp.registry.model.packaging import Packaging
from lp.registry.interfaces.person import (
    validate_person_not_private_membership)
from lp.translations.model.pofile import POFile
from lp.translations.model.potemplate import (
    HasTranslationTemplatesMixin,
    POTemplate)
from lp.registry.model.productrelease import ProductRelease
from lp.translations.model.productserieslanguage import (
    ProductSeriesLanguage)
from lp.blueprints.model.specification import (
    HasSpecificationsMixin, Specification)
from lp.translations.model.translationimportqueue import (
    HasTranslationImportsMixin)
from lp.registry.model.structuralsubscription import (
    StructuralSubscriptionTargetMixin)
from canonical.launchpad.helpers import shortlist
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.distroseries import SeriesMixin
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.packaging import PackagingType
from lp.translations.interfaces.potemplate import IHasTranslationTemplates
from lp.blueprints.interfaces.specification import (
    SpecificationDefinitionStatus, SpecificationFilter,
    SpecificationGoalStatus, SpecificationImplementationStatus,
    SpecificationSort)
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.registry.interfaces.productseries import (
    IProductSeries, IProductSeriesSet)
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode)
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.sorting import sorted_dotted_numbers


def landmark_key(landmark):
    """Sorts landmarks by date and name."""
    if landmark['date'] is None:
        # Null dates are assumed to be in the future.
        date = '9999-99-99'
    else:
        date = landmark['date']
    return date + landmark['name']


class ProductSeries(SQLBase, BugTargetBase, HasMilestonesMixin,
                    HasSpecificationsMixin, HasTranslationImportsMixin,
                    HasTranslationTemplatesMixin,
                    StructuralSubscriptionTargetMixin, SeriesMixin):
    """A series of product releases."""
    implements(IProductSeries, IHasTranslationTemplates)

    _table = 'ProductSeries'

    product = ForeignKey(dbName='product', foreignKey='Product', notNull=True)
    status = EnumCol(
        notNull=True, schema=SeriesStatus,
        default=SeriesStatus.DEVELOPMENT)
    name = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    owner = ForeignKey(
        dbName="owner", foreignKey="Person",
        storm_validator=validate_person_not_private_membership,
        notNull=True)
    driver = ForeignKey(
        dbName="driver", foreignKey="Person",
        storm_validator=validate_person_not_private_membership,
        notNull=False, default=None)
    branch = ForeignKey(foreignKey='Branch', dbName='branch',
                             default=None)
    translations_autoimport_mode = EnumCol(
        dbName='translations_autoimport_mode',
        notNull=True,
        schema=TranslationsBranchImportMode,
        default=TranslationsBranchImportMode.NO_IMPORT)
    translations_branch = ForeignKey(
        dbName='translations_branch', foreignKey='Branch', notNull=False,
        default=None)
    # where are the tarballs released from this branch placed?
    releasefileglob = StringCol(default=None)
    releaseverstyle = StringCol(default=None)

    packagings = SQLMultipleJoin('Packaging', joinColumn='productseries',
                            orderBy=['-id'])

    def _getMilestoneCondition(self):
        """See `HasMilestonesMixin`."""
        return (Milestone.productseries == self)

    @property
    def releases(self):
        """See `IProductSeries`."""
        store = Store.of(self)
        result = store.find(
            ProductRelease,
            And(Milestone.productseries == self,
                ProductRelease.milestone == Milestone.id))
        return result.order_by(Desc('datereleased'))

    @property
    def release_files(self):
        """See `IProductSeries`."""
        files = set()
        for release in self.releases:
            files = files.union(release.files)
        return files

    @property
    def displayname(self):
        return self.name

    @property
    def parent(self):
        """See IProductSeries."""
        return self.product

    @property
    def bugtargetdisplayname(self):
        """See IBugTarget."""
        return "%s %s" % (self.product.displayname, self.name)

    @property
    def bugtargetname(self):
        """See IBugTarget."""
        return "%s/%s" % (self.product.name, self.name)

    @property
    def drivers(self):
        """See IProductSeries."""
        drivers = set()
        drivers.add(self.driver)
        drivers = drivers.union(self.product.drivers)
        drivers.discard(None)
        return sorted(drivers, key=lambda x: x.displayname)

    @property
    def bug_supervisor(self):
        """See IProductSeries."""
        return self.product.bug_supervisor

    @property
    def security_contact(self):
        """See IProductSeries."""
        return self.product.security_contact

    def getPOTemplate(self, name):
        """See IProductSeries."""
        return POTemplate.selectOne(
            "productseries = %s AND name = %s" % sqlvalues(self.id, name))

    @property
    def title(self):
        return '%s %s series' % (self.product.displayname, self.displayname)

    @property
    def bug_reporting_guidelines(self):
        """See `IBugTarget`."""
        return self.product.bug_reporting_guidelines

    @property
    def sourcepackages(self):
        """See IProductSeries"""
        from lp.registry.model.sourcepackage import SourcePackage
        ret = self.packagings
        ret = [SourcePackage(sourcepackagename=r.sourcepackagename,
                             distroseries=r.distroseries)
                    for r in ret]
        ret.sort(key=lambda a: a.distribution.name + a.distroseries.version
                 + a.sourcepackagename.name)
        return ret

    @property
    def has_any_specifications(self):
        """See IHasSpecifications."""
        return self.all_specifications.count()

    @property
    def all_specifications(self):
        return self.specifications(filter=[SpecificationFilter.ALL])

    @property
    def valid_specifications(self):
        return self.specifications(filter=[SpecificationFilter.VALID])

    @property
    def is_development_focus(self):
        """See `IProductSeries`."""
        return self == self.product.development_focus

    def specifications(self, sort=None, quantity=None, filter=None,
                       prejoin_people=True):
        """See IHasSpecifications.

        The rules for filtering are that there are three areas where you can
        apply a filter:

          - acceptance, which defaults to ACCEPTED if nothing is said,
          - completeness, which defaults to showing BOTH if nothing is said
          - informational, which defaults to showing BOTH if nothing is said

        """

        # Make a new list of the filter, so that we do not mutate what we
        # were passed as a filter
        if not filter:
            # filter could be None or [] then we decide the default
            # which for a productseries is to show everything accepted
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
            order = ['-priority', 'definition_status', 'name']
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
        # productseries, we need to be able to filter on the basis of:
        #
        #  - completeness. by default, only incomplete specs shown
        #  - goal status. by default, only accepted specs shown
        #  - informational.
        #
        base = 'Specification.productseries = %s' % self.id
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

        # Filter for validity. If we want valid specs only then we should
        # exclude all OBSOLETE or SUPERSEDED specs
        if SpecificationFilter.VALID in filter:
            query += (
                ' AND Specification.definition_status NOT IN ( %s, %s ) '
                % sqlvalues(SpecificationDefinitionStatus.OBSOLETE,
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

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for this product series."""
        search_params.setProductSeries(self)

    @property
    def official_bug_tags(self):
        """See `IHasBugs`."""
        return self.product.official_bug_tags

    def getUsedBugTags(self):
        """See IBugTarget."""
        return get_bug_tags("BugTask.productseries = %s" % sqlvalues(self))

    def getUsedBugTagsWithOpenCounts(self, user):
        """See IBugTarget."""
        return get_bug_tags_open_count(BugTask.productseries == self, user)

    def createBug(self, bug_params):
        """See IBugTarget."""
        raise NotImplementedError('Cannot file a bug against a productseries')

    def _getBugTaskContextClause(self):
        """See BugTargetBase."""
        return 'BugTask.productseries = %s' % sqlvalues(self)

    def getSpecification(self, name):
        """See ISpecificationTarget."""
        return self.product.getSpecification(name)

    def getRelease(self, version):
        for release in self.releases:
            if release.version == version:
                return release
        return None

    def getPackage(self, distroseries):
        """See IProductSeries."""
        for pkg in self.sourcepackages:
            if pkg.distroseries == distroseries:
                return pkg
        # XXX sabdfl 2005-06-23: This needs to search through the ancestry of
        # the distroseries to try to find a relevant packaging record
        raise NotFoundError(distroseries)

    def setPackaging(self, distroseries, sourcepackagename, owner):
        """See IProductSeries."""
        for pkg in self.packagings:
            if pkg.distroseries == distroseries:
                # we have found a matching Packaging record
                if pkg.sourcepackagename == sourcepackagename:
                    # and it has the same source package name
                    return pkg
                # ok, we need to update this pkging record
                pkg.sourcepackagename = sourcepackagename
                pkg.owner = owner
                pkg.datecreated = UTC_NOW
                pkg.sync()  # convert UTC_NOW to actual datetime
                return pkg

        # ok, we didn't find a packaging record that matches, let's go ahead
        # and create one
        pkg = Packaging(
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
            productseries=self,
            packaging=PackagingType.PRIME,
            owner=owner)
        pkg.sync()  # convert UTC_NOW to actual datetime
        return pkg

    def getPackagingInDistribution(self, distribution):
        """See IProductSeries."""
        history = []
        for pkging in self.packagings:
            if pkging.distroseries.distribution == distribution:
                history.append(pkging)
        return history

    def newMilestone(self, name, dateexpected=None, summary=None,
                     code_name=None):
        """See IProductSeries."""
        return Milestone(
            name=name, dateexpected=dateexpected, summary=summary,
            product=self.product, productseries=self, code_name=code_name)

    def getTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.selectBy(productseries=self,
                                     orderBy=['-priority','name'])
        return shortlist(result, 300)

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
            self.product.official_rosetta == True,
            POTemplate.iscurrent == True,
            POTemplate.productseries == self))
        return result.order_by(['-POTemplate.priority', 'POTemplate.name'])

    @property
    def potemplate_count(self):
        """See `IProductSeries`."""
        return self.getCurrentTranslationTemplates().count()

    def getObsoleteTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        result = POTemplate.select('''
            productseries = %s AND
            productseries = ProductSeries.id AND
            ProductSeries.product = Product.id AND
            (iscurrent IS FALSE OR Product.official_rosetta IS FALSE)
            ''' % sqlvalues(self),
            orderBy=['-priority','name'],
            clauseTables = ['ProductSeries', 'Product'])
        return shortlist(result, 300)

    @property
    def productserieslanguages(self):
        """See `IProductSeries`."""
        store = Store.of(self)

        english = getUtility(ILaunchpadCelebrities).english

        results = []
        if self.potemplate_count == 1:
            # If there is only one POTemplate in a ProductSeries, fetch
            # Languages and corresponding POFiles with one query, along
            # with their stats, and put them into ProductSeriesLanguage
            # objects.
            origin = [Language, POFile, POTemplate]
            query = store.using(*origin).find(
                (Language, POFile),
                POFile.language==Language.id,
                POFile.variant==None,
                Language.visible==True,
                POFile.potemplate==POTemplate.id,
                POTemplate.productseries==self,
                POTemplate.iscurrent==True,
                Language.id!=english.id)

            ordered_results = query.order_by(['Language.englishname'])

            for language, pofile in ordered_results:
                psl = ProductSeriesLanguage(self, language, pofile=pofile)
                psl.setCounts(pofile.potemplate.messageCount(),
                              pofile.currentCount(),
                              pofile.updatesCount(),
                              pofile.rosettaCount(),
                              pofile.unreviewedCount(),
                              pofile.date_changed)
                results.append(psl)
        else:
            # If there is more than one template, do a single
            # query to count total messages in all templates.
            query = store.find(Sum(POTemplate.messagecount),
                                POTemplate.productseries==self,
                                POTemplate.iscurrent==True)
            total, = query
            # And another query to fetch all Languages with translations
            # in this ProductSeries, along with their cumulative stats
            # for imported, changed, rosetta-provided and unreviewed
            # translations.
            query = store.find(
                (Language,
                 Sum(POFile.currentcount),
                 Sum(POFile.updatescount),
                 Sum(POFile.rosettacount),
                 Sum(POFile.unreviewed_count),
                 Max(POFile.date_changed)),
                POFile.language==Language.id,
                POFile.variant==None,
                Language.visible==True,
                POFile.potemplate==POTemplate.id,
                POTemplate.productseries==self,
                POTemplate.iscurrent==True,
                Language.id!=english.id).group_by(Language)

            # XXX: Ursinha 2009-11-02: The Max(POFile.date_changed) result
            # here is a naive datetime. My guess is that it happens
            # because UTC awareness is attibuted to the field in the POFile
            # model class, and in this case the Max function deals directly
            # with the value returned from the database without
            # instantiating it.
            # This seems to be irrelevant to what we're trying to achieve
            # here, but making a note either way.

            ordered_results = query.order_by(['Language.englishname'])

            for (language, imported, changed, new, unreviewed,
                last_changed) in ordered_results:
                psl = ProductSeriesLanguage(self, language)
                psl.setCounts(
                    total, imported, changed, new, unreviewed, last_changed)
                results.append(psl)

        return results

    def getTimeline(self, include_inactive=False):
        landmarks = []
        for milestone in self.all_milestones:
            if milestone.product_release is None:
                # Skip inactive milestones, but include releases,
                # even if include_inactive is False.
                if not include_inactive and not milestone.active:
                    continue
                node_type = 'milestone'
                date = milestone.dateexpected
                uri = canonical_url(milestone, path_only_if_possible=True)
            else:
                node_type = 'release'
                date = milestone.product_release.datereleased
                uri = canonical_url(
                    milestone.product_release, path_only_if_possible=True)

            if isinstance(date, datetime.datetime):
                date = date.date().isoformat()
            elif isinstance(date, datetime.date):
                date = date.isoformat()

            entry = dict(
                name=milestone.name,
                code_name=milestone.code_name,
                type=node_type,
                date=date,
                uri=uri)
            landmarks.append(entry)

        landmarks = sorted_dotted_numbers(landmarks, key=landmark_key)
        landmarks.reverse()
        return dict(
            name=self.name,
            is_development_focus=self.is_development_focus,
            status=self.status.title,
            uri=canonical_url(self, path_only_if_possible=True),
            landmarks=landmarks)


class ProductSeriesSet:
    """See IProductSeriesSet."""

    implements(IProductSeriesSet)

    def __getitem__(self, series_id):
        """See IProductSeriesSet."""
        series = self.get(series_id)
        if series is None:
            raise NotFoundError(series_id)
        return series

    def get(self, series_id, default=None):
        """See IProductSeriesSet."""
        try:
            return ProductSeries.get(series_id)
        except SQLObjectNotFound:
            return default
