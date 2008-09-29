# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Launchpad Pillars share a namespace.

Pillars are currently Product, Project and Distribution.
"""

__metaclass__ = type

import warnings

from zope.component import getUtility
from zope.interface import implements

from storm.expr import LeftJoin, NamedFunc, Select
from storm.locals import SQL
from sqlobject import ForeignKey, StringCol, BoolCol

from canonical.config import config
from canonical.database.sqlbase import cursor, SQLBase, sqlvalues
from canonical.launchpad.database.featuredproject import FeaturedProject
from canonical.launchpad.database.productlicense import ProductLicense
from canonical.launchpad.interfaces import (
    IDistribution, IDistributionSet, IPillarName, IPillarNameSet, IProduct,
    IProductSet, IProjectSet, License, NotFoundError)
from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)

__all__ = [
    'pillar_sort_key',
    'PillarNameSet',
    'PillarName',
    ]


def pillar_sort_key(pillar):
    """A sort key for a set of pillars. We want:

          - products first, alphabetically
          - distributions, with ubuntu first and the rest alphabetically
    """
    product_name = None
    distribution_name = None
    if IProduct.providedBy(pillar):
        product_name = pillar.name
    elif IDistribution.providedBy(pillar):
        distribution_name = pillar.name
    # Move ubuntu to the top.
    if distribution_name == 'ubuntu':
        distribution_name = '-'

    return (distribution_name, product_name)


class PillarNameSet:
    implements(IPillarNameSet)

    def __contains__(self, name):
        """See `IPillarNameSet`."""
        # XXX flacoste 2007-10-09 bug=90983: Workaround.
        name = name.encode('ASCII')
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        result = store.execute("""
            SELECT TRUE
            FROM PillarName
            WHERE name=? AND active IS TRUE
            """, [name])
        return result.get_one() is not None

    def __getitem__(self, name):
        """See `IPillarNameSet`."""
        # XXX flacoste 2007-10-09 bug=90983: Workaround.
        name = name.encode('ASCII')
        pillar = self.getByName(name, ignore_inactive=True)
        if pillar is None:
            raise NotFoundError(name)
        return pillar

    def getByName(self, name, ignore_inactive=False):
        """Return the pillar with the given name.

        If ignore_inactive is True, then only active pillars are considered.

        If no pillar is found, None is returned.
        """
        # We could attempt to do this in a single database query, but I
        # expect that doing two queries will be faster that OUTER JOINing
        # the Project, Product and Distribution tables (and this approach
        # works better with SQLObject too.

        # XXX flacoste 2007-10-09 bug=90983: Workaround.
        name = name.encode('ASCII')

        # Retrieve information out of the PillarName table.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        cur = cursor()
        query = """
            SELECT id, product, project, distribution
            FROM PillarName
            WHERE name=?
            """
        if ignore_inactive:
            query += " AND active IS TRUE"
        result = store.execute(query, [name])
        row = result.get_one()
        if row is None:
            return None

        assert len([column for column in row[1:] if column is None]) == 2, """
                One (and only one) of project, project or distribution may
                be NOT NULL
                """

        id, product, project, distribution = row

        if product is not None:
            return getUtility(IProductSet).get(product)
        elif project is not None:
            return getUtility(IProjectSet).get(project)
        else:
            return getUtility(IDistributionSet).get(distribution)

    def build_search_query(self, text, extra_columns=()):
        """Query parameters shared by search() and count_search_matches().

        :returns: Storm ResultSet object
        """
        # These classes are imported in this method to prevent an import loop.
        from canonical.launchpad.database.product import Product
        from canonical.launchpad.database.project import Project
        from canonical.launchpad.database.distribution import Distribution
        origin = [
            PillarName,
            LeftJoin(Product, PillarName.product == Product.id),
            LeftJoin(Project, PillarName.project == Project.id),
            LeftJoin(Distribution,
                     PillarName.distribution == Distribution.id),
            ]
        conditions = SQL('''
            PillarName.active = TRUE
            AND (
                 Product.fti @@ ftq(%(text)s) OR
                 Product.name = lower(%(text)s) OR
                 lower(Product.title) = lower(%(text)s) OR

                 Project.fti @@ ftq(%(text)s) OR
                 Project.name = lower(%(text)s) OR
                 lower(Project.title) = lower(%(text)s) OR

                 Distribution.fti @@ ftq(%(text)s) OR
                 Distribution.name = lower(%(text)s) OR
                 lower(Distribution.title) = lower(%(text)s)
                )
            ''' % sqlvalues(text=text))
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        columns = [PillarName, Product, Project, Distribution]
        for column in extra_columns:
            columns.append(column)
        return store.using(*origin).find(tuple(columns), conditions)

    def count_search_matches(self, text):
        result = self.build_search_query(text)
        return result.count()

    def search(self, text, limit):
        """See `IPillarSet`."""
        # These classes are imported in this method to prevent an import loop.
        from canonical.launchpad.database.product import (
            Product, ProductWithLicenses)
        if limit is None:
            limit = config.launchpad.default_batch_size

        class Array(NamedFunc):
            """Storm representation of the array() PostgreSQL function."""
            name = 'array'

        # Pull out the licenses as a subselect which is converted
        # into a PostgreSQL array so that multiple licenses per product
        # can be retrieved in a single row for each product.
        extra_column = Array(
            Select(columns=[ProductLicense.license],
                   where=(ProductLicense.product == Product.id),
                   tables=[ProductLicense]))
        result = self.build_search_query(text, [extra_column])

        # If the search text matches the name or title of the
        # Product, Project, or Distribution exactly, then this
        # row should get the highest search rank (9999999).
        # Each row in the PillarName table will join with only one
        # of either the Product, Project, or Distribution tables,
        # so the coalesce() is necessary to find the rank() which
        # is not null.
        result.order_by(SQL('''
            (CASE WHEN Product.name = lower(%(text)s)
                      OR lower(Product.title) = lower(%(text)s)
                      OR Project.name = lower(%(text)s)
                      OR lower(Project.title) = lower(%(text)s)
                      OR Distribution.name = lower(%(text)s)
                      OR lower(Distribution.title) = lower(%(text)s)
                THEN 9999999
                ELSE coalesce(rank(Product.fti, ftq(%(text)s)),
                              rank(Project.fti, ftq(%(text)s)),
                              rank(Distribution.fti, ftq(%(text)s)))
            END) DESC, PillarName.name
            ''' % sqlvalues(text=text)))
        # People shouldn't be calling this method with too big limits
        longest_expected = 2 * config.launchpad.default_batch_size
        if limit > longest_expected:
            warnings.warn(
                "The search limit (%s) was greater "
                "than the longest expected size (%s)"
                % (limit, longest_expected),
                stacklevel=2)
        pillars = []
        # Prefill pillar.product.licenses.
        for pillar_name, product, project, distro, license_ids in (
            result[:limit]):
            if pillar_name.product is None:
                pillars.append(pillar_name.pillar)
            else:
                licenses = [
                    License.items[license_id]
                    for license_id in license_ids]
                product_with_licenses = ProductWithLicenses(
                    pillar_name.product, tuple(sorted(licenses)))
                pillars.append(product_with_licenses)
        return pillars

    def add_featured_project(self, project):
        """See `IPillarSet`."""
        query = """
            PillarName.name = %s
            AND PillarName.id = FeaturedProject.pillar_name
            """ % sqlvalues(project.name)
        existing = FeaturedProject.selectOne(
            query, clauseTables=['PillarName'])
        if existing is None:
            pillar_name = PillarName.selectOneBy(name=project.name)
            return FeaturedProject(pillar_name=pillar_name.id)

    def remove_featured_project(self, project):
        """See `IPillarSet`."""
        query = """
            PillarName.name = %s
            AND PillarName.id = FeaturedProject.pillar_name
            """ % sqlvalues(project.name)
        existing = FeaturedProject.selectOne(
            query, clauseTables=['PillarName'])
        if existing is not None:
            existing.destroySelf()

    @property
    def featured_projects(self):
        """See `IPillarSet`."""

        query = "PillarName.id = FeaturedProject.pillar_name"
        return [pillar_name.pillar for pillar_name in PillarName.select(
                    query, clauseTables=['FeaturedProject'])]


class PillarName(SQLBase):
    implements(IPillarName)

    _table = 'PillarName'
    _defaultOrder = 'name'

    name = StringCol(
        dbName='name', notNull=True, unique=True, alternateID=True)
    product = ForeignKey(
        foreignKey='Product', dbName='product')
    project = ForeignKey(
        foreignKey='Project', dbName='project')
    distribution = ForeignKey(
        foreignKey='Distribution', dbName='distribution')
    active = BoolCol(dbName='active', notNull=True, default=True)

    @property
    def pillar(self):
        if self.distribution is not None:
            return self.distribution
        elif self.project is not None:
            return self.project
        elif self.product is not None:
            return self.product
        else:
            raise AssertionError("Unknown pillar type: %s" % self.name)
