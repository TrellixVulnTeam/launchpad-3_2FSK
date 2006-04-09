# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['ProductRelease', 'ProductReleaseSet', 'ProductReleaseFile']

from zope.interface import implements

from sqlobject import ForeignKey, StringCol, SQLMultipleJoin, AND

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import IProductRelease
from canonical.launchpad.interfaces import IProductReleaseSet

from canonical.lp.dbschema import EnumCol, UpstreamFileType

class ProductRelease(SQLBase):
    """A release of a product."""
    implements(IProductRelease)
    _table = 'ProductRelease'

    datereleased = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    version = StringCol(notNull=True)
    codename = StringCol(notNull=False, default=None)
    summary = StringCol(notNull=False, default=None)
    description = StringCol(notNull=False, default=None)
    changelog = StringCol(notNull=False, default=None)
    datecreated = UtcDateTimeCol(
        dbName='datecreated', notNull=True, default=UTC_NOW)
    owner = ForeignKey(dbName="owner", foreignKey="Person", notNull=True)
    productseries = ForeignKey(dbName='productseries',
                               foreignKey='ProductSeries', notNull=True)
    manifest = ForeignKey(dbName='manifest', foreignKey='Manifest',
                          default=None)

    files = SQLMultipleJoin('ProductReleaseFile', joinColumn='productrelease')

    files = SQLMultipleJoin('ProductReleaseFile', joinColumn='productrelease')

    # properties
    @property
    def product(self):
        return self.productseries.product

    @property
    def displayname(self):
        return self.productseries.product.displayname + ' ' + self.version

    @property
    def title(self):
        """See IProductRelease."""
        thetitle = self.displayname
        if self.codename:
            thetitle += ' "' + self.codename + '"'
        return thetitle

    def addFileAlias(self, alias_id, file_type=UpstreamFileType.CODETARBALL):
        """See IProductRelease."""
        return ProductReleaseFile(productreleaseID=self.id,
                                  libraryfileID=alias_id,
                                  filetype=file_type)


class ProductReleaseFile(SQLBase):
    """A file of a product release."""

    _table = 'ProductReleaseFile'

    productrelease = ForeignKey(dbName='productrelease',
                                foreignKey='ProductRelease', notNull=True)
    libraryfile = ForeignKey(dbName='libraryfile',
                             foreignKey='LibraryFileAlias', notNull=True)

    filetype = EnumCol(dbName='filetype', schema=UpstreamFileType,
                       notNull=True, default=UpstreamFileType.CODETARBALL)


class ProductReleaseSet(object):
    """See IProductReleaseSet""" 
    implements(IProductReleaseSet)

    def new(self, version, productseries, owner, codename=None, summary=None,
            description=None, changelog=None):
        """See IProductReleaseSet"""
        return ProductRelease(version=version,
                              productseries=productseries,
                              owner=owner,
                              codename=codename,
                              summary=summary,
                              description=description,
                              changelog=changelog)


    def getBySeriesAndVersion(self, productseries, version, default=None):
        """See IProductReleaseSet"""
        query = AND(ProductRelease.q.version==version,
                    ProductRelease.q.productseriesID==productseries.id)
        productrelease = ProductRelease.selectOne(query)
        if productrelease is None:
            return default
        return productrelease

