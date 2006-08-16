# Copyright 2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'Karma',
    'KarmaAction',
    'KarmaActionSet',
    'KarmaCache',
    'KarmaPersonCategoryCacheView',
    'KarmaTotalCache',
    'KarmaCategory',
    'KarmaContextMixin',
    ]

# Zope interfaces
from zope.interface import implements

# SQLObject imports
from sqlobject import (
    DateTimeCol, ForeignKey, IntCol, StringCol, SQLObjectNotFound,
    SQLMultipleJoin)

from canonical.database.sqlbase import SQLBase, sqlvalues, cursor
from canonical.database.constants import UTC_NOW
from canonical.launchpad.interfaces import (
    IKarma, IKarmaAction, IKarmaActionSet, IKarmaCache, IKarmaCategory,
    IKarmaTotalCache, IKarmaPersonCategoryCacheView, IKarmaContext, IProduct,
    IDistribution)


class Karma(SQLBase):
    """See IKarma."""
    implements(IKarma)

    _table = 'Karma'
    _defaultOrder = ['action', 'id']

    person = ForeignKey(
        dbName='person', foreignKey='Person', notNull=True)
    action = ForeignKey(
        dbName='action', foreignKey='KarmaAction', notNull=True)
    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=False)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False)
    datecreated = DateTimeCol(
        dbName='datecreated', notNull=True, default=UTC_NOW)


class KarmaAction(SQLBase):
    """See IKarmaAction."""
    implements(IKarmaAction)

    _table = 'KarmaAction'
    sortingColumns = ['category', 'name']
    _defaultOrder = sortingColumns

    name = StringCol(notNull=True, alternateID=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    category = ForeignKey(dbName='category', foreignKey='KarmaCategory',
        notNull=True)
    points = IntCol(dbName='points', notNull=True)


class KarmaActionSet:
    """See IKarmaActionSet."""
    implements(IKarmaActionSet)

    def __iter__(self):
        return iter(KarmaAction.select())

    def getByName(self, name, default=None):
        """See IKarmaActionSet."""
        try:
            return KarmaAction.byName(name)
        except SQLObjectNotFound:
            return default

    def selectByCategory(self, category):
        """See IKarmaActionSet."""
        return KarmaAction.selectBy(category=category)

    def selectByCategoryAndPerson(self, category, person, orderBy=None):
        """See IKarmaActionSet."""
        if orderBy is None:
            orderBy = KarmaAction.sortingColumns
        query = ('KarmaAction.category = %s '
                 'AND Karma.action = KarmaAction.id '
                 'AND Karma.person = %s' % sqlvalues(category.id, person.id))
        return KarmaAction.select(
                query, clauseTables=['Karma'], distinct=True, orderBy=orderBy)


class KarmaCache(SQLBase):
    """See IKarmaCache."""
    implements(IKarmaCache)

    _table = 'KarmaCache'
    _defaultOrder = ['category', 'id']

    person = ForeignKey(
        dbName='person', notNull=True)
    category = ForeignKey(
        dbName='category', foreignKey='KarmaCategory', notNull=True)
    karmavalue = IntCol(
        dbName='karmavalue', notNull=True)
    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=False)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False)


class KarmaPersonCategoryCacheView(SQLBase):
    """See IKarmaPersonCategoryCacheView."""
    implements(IKarmaPersonCategoryCacheView)

    _table = 'KarmaPersonCategoryCacheView'
    _defaultOrder = ['category', 'id']

    person = ForeignKey(
        dbName='person', notNull=True)
    category = ForeignKey(
        dbName='category', foreignKey='KarmaCategory', notNull=True)
    karmavalue = IntCol(
        dbName='karmavalue', notNull=True)


class KarmaTotalCache(SQLBase):
    """A cached value of the total of a person's karma (all categories)."""
    implements(IKarmaTotalCache)

    _table = 'KarmaTotalCache'
    _defaultOrder = ['id']

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    karma_total = IntCol(dbName='karma_total', notNull=True)


class KarmaCategory(SQLBase):
    """See IKarmaCategory."""
    implements(IKarmaCategory)

    _defaultOrder = ['title', 'id']

    name = StringCol(notNull=True, alternateID=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)

    karmaactions = SQLMultipleJoin(
        'KarmaAction', joinColumn='category', orderBy='name')


class KarmaContextMixin:
    """A mixin to be used by classes implementing IKarmaContext.
    
    This would be better as an adapter for Product and Distribution, but a
    mixin should be okay for now.
    """

    implements(IKarmaContext)

    def getTopContributorsGroupedByCategory(self, limit=None):
        """See IKarmaContext."""
        contributors_by_category = {}
        for category in KarmaCategory.select():
            results = self.getTopContributors(category=category, limit=limit)
            if results:
                contributors_by_category[category] = results
        return contributors_by_category

    def getTopContributors(self, category=None, limit=None):
        """See IKarmaContext."""
        from canonical.launchpad.database.person import Person
        if IProduct.providedBy(self):
            context_name = 'product'
        elif IDistribution.providedBy(self):
            context_name = 'distribution'
        else:
            raise AssertionError(
                "Not a product nor a distribution: %r" % self)

        query = """
            SELECT person, SUM(karmavalue) AS sum_karmavalue
            FROM KarmaCache
            WHERE %s = %d
            """ % (context_name, self.id)
        if category is not None:
            query += " AND category = %s" % sqlvalues(category)
        query += " GROUP BY person ORDER BY sum_karmavalue DESC"
        if limit is not None:
            query += " LIMIT %d" % limit

        cur = cursor()
        cur.execute(query)
        return [(Person.get(person_id), karmavalue)
                for person_id, karmavalue in cur.fetchall()]

