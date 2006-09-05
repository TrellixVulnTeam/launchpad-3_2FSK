# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'ProductSeries',
    'ProductSeriesSet',
    'ProductSeriesSourceSet',
    ]


import datetime
import sets
from warnings import warn

from zope.interface import implements
from sqlobject import (
    IntervalCol, ForeignKey, StringCol, SQLMultipleJoin, SQLObjectNotFound)

from canonical.database.sqlbase import flush_database_updates
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.components.bugtarget import BugTargetBase
from canonical.launchpad.interfaces import (
    IProductSeries, IProductSeriesSet, IProductSeriesSource,
    IProductSeriesSourceAdmin, IProductSeriesSourceSet, NotFoundError)

from canonical.launchpad.database.bug import (
    get_bug_tags, get_bug_tags_open_count)
from canonical.launchpad.database.bugtask import BugTaskSet
from canonical.launchpad.database.milestone import Milestone
from canonical.launchpad.database.packaging import Packaging
from canonical.launchpad.database.potemplate import POTemplate
from canonical.launchpad.database.specification import Specification
from canonical.database.sqlbase import (
    SQLBase, quote, sqlvalues)

from canonical.lp.dbschema import (
    EnumCol, ImportStatus, PackagingType, RevisionControlSystems,
    SpecificationSort, SpecificationGoalStatus, SpecificationFilter,
    SpecificationStatus)


class ProductSeries(SQLBase, BugTargetBase):
    """A series of product releases."""
    implements(IProductSeries, IProductSeriesSource, IProductSeriesSourceAdmin)
    _table = 'ProductSeries'

    product = ForeignKey(dbName='product', foreignKey='Product', notNull=True)
    name = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    owner = ForeignKey(
        foreignKey="Person", dbName="owner", notNull=True)
    driver = ForeignKey(
        foreignKey="Person", dbName="driver", notNull=False, default=None)
    import_branch = ForeignKey(foreignKey='Branch', dbName='import_branch',
                               default=None)
    user_branch = ForeignKey(foreignKey='Branch', dbName='user_branch',
                             default=None)
    importstatus = EnumCol(dbName='importstatus', notNull=False,
        schema=ImportStatus, default=None)
    datelastsynced = UtcDateTimeCol(default=None)
    syncinterval = IntervalCol(default=None)
    rcstype = EnumCol(dbName='rcstype', schema=RevisionControlSystems,
        notNull=False, default=None)
    cvsroot = StringCol(default=None)
    cvsmodule = StringCol(default=None)
    cvsbranch = StringCol(default=None)
    # where are the tarballs released from this branch placed?
    cvstarfileurl = StringCol(default=None)
    svnrepository = StringCol(default=None)
    # XXX bkrepository is in the data model but not here
    #   -- matsubara, 2005-10-06
    releaseroot = StringCol(default=None)
    releasefileglob = StringCol(default=None)
    releaseverstyle = StringCol(default=None)
    # these fields tell us where to publish upstream as bazaar branch
    targetarcharchive = StringCol(default=None)
    targetarchcategory = StringCol(default=None)
    targetarchbranch = StringCol(default=None)
    targetarchversion = StringCol(default=None)
    # key dates on the road to import happiness
    dateautotested = UtcDateTimeCol(default=None)
    datestarted = UtcDateTimeCol(default=None)
    datefinished = UtcDateTimeCol(default=None)
    dateprocessapproved = UtcDateTimeCol(default=None)
    datesyncapproved = UtcDateTimeCol(default=None)

    releases = SQLMultipleJoin('ProductRelease', joinColumn='productseries',
                            orderBy=['-datereleased'])
    milestones = SQLMultipleJoin('Milestone', joinColumn = 'productseries',
                            orderBy=['dateexpected', 'name'])
    packagings = SQLMultipleJoin('Packaging', joinColumn='productseries',
                            orderBy=['-id'])

    @property
    def displayname(self):
        return self.name

    @property
    def bugtargetname(self):
        """See IBug."""
        return "%s %s (upstream)" % (self.product.name, self.name)

    @property
    def drivers(self):
        """See IProductSeries.drivers."""
        drivers = set()
        drivers.add(self.driver)
        drivers = drivers.union(self.product.drivers)
        drivers.discard(None)
        return sorted(drivers, key=lambda x: x.browsername)

    @property
    def series_branch(self):
        """See IProductSeries.series_branch."""
        if self.user_branch is not None:
            return self.user_branch
        return self.import_branch

    @property
    def potemplates(self):
        result = POTemplate.selectBy(productseries=self)
        result = list(result)
        return sorted(result, key=lambda x: x.potemplatename.name)

    @property
    def currentpotemplates(self):
        result = POTemplate.selectBy(productseries=self, iscurrent=True)
        result = list(result)
        return sorted(result, key=lambda x: x.potemplatename.name)

    def getPOTemplate(self, name):
        """See IProductSeries."""
        return POTemplate.selectOne(
            "POTemplate.productseries = %s AND "
            "POTemplate.potemplatename = POTemplateName.id AND "
            "POTemplateName.name = %s" % sqlvalues(self.id, name),
            clauseTables=['POTemplateName'])

    @property
    def title(self):
        return self.product.displayname + ' Series: ' + self.displayname

    def shortdesc(self):
        warn('ProductSeries.shortdesc should be ProductSeries.summary',
             DeprecationWarning)
        return self.summary
    shortdesc = property(shortdesc)

    @property
    def sourcepackages(self):
        """See IProductSeries"""
        from canonical.launchpad.database.sourcepackage import SourcePackage
        ret = Packaging.selectBy(productseries=self)
        ret = [SourcePackage(sourcepackagename=r.sourcepackagename,
                             distrorelease=r.distrorelease)
                    for r in ret]
        ret.sort(key=lambda a: a.distribution.name + a.distrorelease.version
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

    def specifications(self, sort=None, quantity=None, filter=None):
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
            order = ['-priority', 'status', 'name']
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

        # Filter for validity. If we want valid specs only then we should
        # exclude all OBSOLETE or SUPERSEDED specs
        if SpecificationFilter.VALID in filter:
            query += ' AND Specification.status NOT IN ( %s, %s ) ' % \
                sqlvalues(SpecificationStatus.OBSOLETE,
                          SpecificationStatus.SUPERSEDED)

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

    def searchTasks(self, search_params):
        """See IBugTarget."""
        search_params.setProductSeries(self)
        return BugTaskSet().search(search_params)

    def getUsedBugTags(self):
        """See IBugTarget."""
        return get_bug_tags("BugTask.productseries = %s" % sqlvalues(self))

    def getUsedBugTagsWithOpenCounts(self, user):
        """See IBugTarget."""
        return get_bug_tags_open_count(
            "BugTask.productseries = %s" % sqlvalues(self), user)

    def createBug(self, bug_params):
        """See IBugTarget."""
        raise NotImplementedError('Cannot file a bug against a productseries')

    def getSpecification(self, name):
        """See ISpecificationTarget."""
        return self.product.getSpecification(name)

    def getRelease(self, version):
        for release in self.releases:
            if release.version == version:
                return release
        return None

    def getPackage(self, distrorelease):
        """See IProductSeries."""
        for pkg in self.sourcepackages:
            if pkg.distrorelease == distrorelease:
                return pkg
        # XXX sabdfl 23/06/05 this needs to search through the ancestry of
        # the distrorelease to try to find a relevant packaging record
        raise NotFoundError(distrorelease)

    def setPackaging(self, distrorelease, sourcepackagename, owner):
        """See IProductSeries."""
        for pkg in self.packagings:
            if pkg.distrorelease == distrorelease:
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
        pkg = Packaging(distrorelease=distrorelease,
            sourcepackagename=sourcepackagename, productseries=self,
            packaging=PackagingType.PRIME,
            owner=owner)
        pkg.sync()  # convert UTC_NOW to actual datetime
        return pkg

    def getPackagingInDistribution(self, distribution):
        """See IProductSeries."""
        history = []
        for pkging in self.packagings:
            if pkging.distrorelease.distribution == distribution:
                history.append(pkging)
        return history

    def certifyForSync(self):
        """Enable the sync for processing."""
        self.dateprocessapproved = UTC_NOW
        self.syncinterval = datetime.timedelta(1)
        self.importstatus = ImportStatus.PROCESSING

    def syncCertified(self):
        """Return true or false indicating if the sync is enabled"""
        return self.dateprocessapproved is not None

    def autoSyncEnabled(self):
        """Is the sync automatically scheduling?"""
        return self.importstatus == ImportStatus.SYNCING

    def enableAutoSync(self):
        """Enable autosyncing?"""
        self.datesyncapproved = UTC_NOW
        self.importstatus = ImportStatus.SYNCING

    def autoTestFailed(self):
        """Has the series source failed automatic testing by roomba?"""
        return self.importstatus == ImportStatus.TESTFAILED

    def newMilestone(self, name, dateexpected=None):
        """See IProductSeries."""
        return Milestone(name=name, dateexpected=dateexpected,
                         product=self.product, productseries=self)


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


# XXX matsubara, 2005-11-30: This class should be merged with ProductSeriesSet
# https://launchpad.net/products/launchpad-bazaar/+bug/5247
class ProductSeriesSourceSet:
    """See IProductSeriesSourceSet"""
    implements(IProductSeriesSourceSet)
    def search(self, ready=None, text=None, forimport=None, importstatus=None,
               start=None, length=None):
        query, clauseTables = self._querystr(
            ready, text, forimport, importstatus)
        return ProductSeries.select(query, distinct=True,
                   clauseTables=clauseTables)[start:length]

    def importcount(self, status=None):
        return self.search(forimport=True, importstatus=status).count()

    def _querystr(self, ready=None, text=None,
                  forimport=None, importstatus=None):
        """Return a querystring and clauseTables for use in a search or a
        get or a query. Arguments:
          ready - boolean indicator of whether or not to limit the search
                  to products and projects that have been reviewed and are
                  active.
          text - text to search for in the product and project titles and
                 descriptions
          forimport - whether or not to limit the search to series which
                      have RCS data on file
          importstatus - limit the list to series which have the given
                         import status.
        """
        queries = []
        clauseTables = sets.Set()
        # deal with the cases which require project and product
        if ( ready is not None ) or text:
            if text:
                queries.append('Product.fti @@ ftq(%s)' % quote(text))
            if ready is not None:
                queries.append('Product.active IS TRUE')
                queries.append('Product.reviewed IS TRUE')
            queries.append("ProductSeries.product = Product.id")

            # The subquery restricts the query to a project that matches
            # the text supplied.
            subqueries = []
            subqueries.append('Product.project = Project.id')
            if text:
                subqueries.append('Project.fti @@ ftq(%s) ' % quote(text))
            if ready is not None:
                subqueries.append('Project.active IS TRUE')
                subqueries.append('Project.reviewed IS TRUE')
            queries.append('(Product.project IS NULL OR (%s))' % 
                           " AND ".join(subqueries))

            clauseTables.add('Project')
            clauseTables.add('Product')

        # now just add filters on import status
        if forimport or importstatus:
            queries.append('ProductSeries.importstatus IS NOT NULL')
        if importstatus:
            queries.append('ProductSeries.importstatus = %d' % importstatus)

        query = " AND ".join(queries)
        return query, clauseTables

    def getByCVSDetails(self, cvsroot, cvsmodule, cvsbranch, default=None):
        """See IProductSeriesSourceSet."""
        result = ProductSeries.selectOneBy(
            cvsroot=cvsroot, cvsmodule=cvsmodule, cvsbranch=cvsbranch)
        if result is None:
            return default
        return result

    def getBySVNDetails(self, svnrepository, default=None):
        """See IProductSeriesSourceSet."""
        result = ProductSeries.selectOneBy(svnrepository=svnrepository)
        if result is None:
            return default
        return result
