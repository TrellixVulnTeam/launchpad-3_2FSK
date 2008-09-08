# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['ProductRelease', 'ProductReleaseSet', 'ProductReleaseFile']

from StringIO import StringIO

from zope.interface import implements
from zope.component import getUtility

from sqlobject import ForeignKey, StringCol, SQLMultipleJoin, AND

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol

from canonical.launchpad.interfaces import (
    IProductRelease, IProductReleaseFile, IProductReleaseSet,
    NotFoundError, UpstreamFileType)
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.validators.person import validate_public_person


class ProductRelease(SQLBase):
    """A release of a product."""
    implements(IProductRelease)
    _table = 'ProductRelease'
    _defaultOrder = ['-datereleased']

    datereleased = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    version = StringCol(notNull=True)
    codename = StringCol(notNull=False, default=None)
    summary = StringCol(notNull=False, default=None)
    description = StringCol(notNull=False, default=None)
    changelog = StringCol(notNull=False, default=None)
    datecreated = UtcDateTimeCol(
        dbName='datecreated', notNull=True, default=UTC_NOW)
    owner = ForeignKey(
        dbName="owner", foreignKey="Person",
        storm_validator=validate_public_person, notNull=True)
    productseries = ForeignKey(dbName='productseries',
                               foreignKey='ProductSeries', notNull=True)

    files = SQLMultipleJoin('ProductReleaseFile', joinColumn='productrelease',
                            orderBy='-date_uploaded')

    # properties
    @property
    def product(self):
        return self.productseries.product

    @property
    def displayname(self):
        return self.productseries.product.displayname + ' ' + self.version

    @property
    def title(self):
        """See `IProductRelease`."""
        thetitle = self.displayname
        if self.codename:
            thetitle += ' "' + self.codename + '"'
        return thetitle

    def normalizeFilename(self, filename):
        # Replace slashes in the filename with less problematic dashes.
        return filename.replace('/', '-')

    def addReleaseFile(self, filename, file_content, content_type,
                       signature_filename, signature_content, uploader,
                       file_type=UpstreamFileType.CODETARBALL,
                       description=None):
        """See `IProductRelease`."""
        # Create the alias for the file.
        filename = self.normalizeFilename(filename)
        alias = getUtility(ILibraryFileAliasSet).create(
            name=filename,
            size=len(file_content),
            file=StringIO(file_content),
            contentType=content_type)
        if signature_filename is not None and signature_content is not None:
            signature_filename = self.normalizeFilename(
                signature_filename)
            signature_alias = getUtility(ILibraryFileAliasSet).create(
                name=signature_filename,
                size=len(signature_content),
                file=StringIO(signature_content),
                contentType='application/pgp-signature')
        else:
            signature_alias = None
        return ProductReleaseFile(productrelease=self,
                                  libraryfile=alias,
                                  signature=signature_alias,
                                  filetype=file_type,
                                  description=description,
                                  uploader=uploader)

    def getFileAliasByName(self, name):
        """See `IProductRelease`."""
        for file_ in self.files:
            if file_.libraryfile.filename == name:
                return file_.libraryfile
            elif file_.signature and file_.signature.filename == name:
                return file_.signature
        raise NotFoundError(name)


class ProductReleaseFile(SQLBase):
    """A file of a product release."""
    implements(IProductReleaseFile)

    _table = 'ProductReleaseFile'

    productrelease = ForeignKey(dbName='productrelease',
                                foreignKey='ProductRelease', notNull=True)

    libraryfile = ForeignKey(dbName='libraryfile',
                             foreignKey='LibraryFileAlias', notNull=True)

    signature = ForeignKey(dbName='signature',
                           foreignKey='LibraryFileAlias')

    filetype = EnumCol(dbName='filetype', enum=UpstreamFileType,
                       notNull=True, default=UpstreamFileType.CODETARBALL)

    description = StringCol(notNull=False, default=None)

    uploader = ForeignKey(
        dbName="uploader", foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)

    date_uploaded = UtcDateTimeCol(notNull=True, default=UTC_NOW)


class ProductReleaseSet(object):
    """See `IProductReleaseSet`."""
    implements(IProductReleaseSet)

    def getBySeriesAndVersion(self, productseries, version, default=None):
        """See `IProductReleaseSet`."""
        query = AND(ProductRelease.q.version==version,
                    ProductRelease.q.productseriesID==productseries.id)
        productrelease = ProductRelease.selectOne(query)
        if productrelease is None:
            return default
        return productrelease

    def getReleasesForSerieses(self, serieses):
        """See `IProductReleaseSet`."""
        if len(list(serieses)) == 0:
            return ProductRelease.select('1 = 2')
        return ProductRelease.select("""
            ProductRelease.productseries IN %s
            """ % sqlvalues([series.id for series in serieses]),
            orderBy='-datereleased')

    def getFilesForReleases(self, releases):
        """See `IProductReleaseSet`."""
        if len(list(releases)) == 0:
            return ProductReleaseFile.select('1 = 2')
        return ProductReleaseFile.select(
            """ProductReleaseFile.productrelease IN %s""" % (
            sqlvalues([release.id for release in releases])),
            orderBy='-date_uploaded',
            prejoins=['libraryfile'])
