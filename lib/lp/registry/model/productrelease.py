# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['ProductRelease', 'ProductReleaseSet', 'ProductReleaseFile']

from StringIO import StringIO

from zope.interface import implements
from zope.component import getUtility

from sqlobject import ForeignKey, StringCol, SQLMultipleJoin, AND
from storm.expr import And, Desc
from storm.store import EmptyResultSet

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol

from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.registry.interfaces.productrelease import (
    IProductRelease, IProductReleaseFile, IProductReleaseSet, UpstreamFileType)
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from lp.registry.interfaces.person import validate_public_person
from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR, IStoreSelector, MAIN_STORE)


SEEK_END = 2                    # Python2.4 has no definition for SEEK_END.


class ProductRelease(SQLBase):
    """A release of a product."""
    implements(IProductRelease)
    _table = 'ProductRelease'
    _defaultOrder = ['-datereleased']

    datereleased = UtcDateTimeCol(notNull=True)
    release_notes = StringCol(notNull=False, default=None)
    changelog = StringCol(notNull=False, default=None)
    datecreated = UtcDateTimeCol(
        dbName='datecreated', notNull=True, default=UTC_NOW)
    owner = ForeignKey(
        dbName="owner", foreignKey="Person",
        storm_validator=validate_public_person, notNull=True)
    milestone = ForeignKey(dbName='milestone', foreignKey='Milestone')

    files = SQLMultipleJoin('ProductReleaseFile', joinColumn='productrelease',
                            orderBy='-date_uploaded')

    # properties
    @property
    def codename(self):
        """Backwards compatible codename attribute.

        This attribute was moved to the Milestone."""
        # XXX EdwinGrubbs 2009-02-02 bug=324394: Remove obsolete attributes.
        return self.milestone.code_name

    @property
    def version(self):
        """Backwards compatible version attribute.

        This attribute was replaced by the Milestone.name."""
        # XXX EdwinGrubbs 2009-02-02 bug=324394: Remove obsolete attributes.
        return self.milestone.name

    @property
    def summary(self):
        """Backwards compatible summary attribute.

        This attribute was replaced by the Milestone.summary."""
        # XXX EdwinGrubbs 2009-02-02 bug=324394: Remove obsolete attributes.
        return self.milestone.summary

    @property
    def productseries(self):
        """Backwards compatible summary attribute.

        This attribute was replaced by the Milestone.productseries."""
        # XXX EdwinGrubbs 2009-02-02 bug=324394: Remove obsolete attributes.
        return self.milestone.productseries

    @property
    def product(self):
        """Backwards compatible summary attribute.

        This attribute was replaced by the Milestone.productseries.product."""
        # XXX EdwinGrubbs 2009-02-02 bug=324394: Remove obsolete attributes.
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

    @staticmethod
    def normalizeFilename(filename):
        # Replace slashes in the filename with less problematic dashes.
        return filename.replace('/', '-')

    def destroySelf(self):
        """See `IProductRelease`."""
        assert self.files.count() == 0, (
            "You can't delete a product release which has files associated "
            "with it.")
        SQLBase.destroySelf(self)

    def _getFileObjectAndSize(self, file_or_data):
        """Return an object and length for file_or_data.

        :param file_or_data: A string or a file object or StringIO object.
        :return: file object or StringIO object and size.
        """
        if isinstance(file_or_data, basestring):
            file_size = len(file_or_data)
            file_obj = StringIO(file_or_data)
        else:
            assert isinstance(file_or_data, (file, StringIO)), (
                "file_or_data is not an expected type")
            file_obj = file_or_data
            start = file_obj.tell()
            file_obj.seek(0, SEEK_END)
            file_size = file_obj.tell()
            file_obj.seek(start)
        return file_obj, file_size

    def addReleaseFile(self, filename, file_content, content_type,
                       uploader, signature_filename=None,
                       signature_content=None,
                       file_type=UpstreamFileType.CODETARBALL,
                       description=None):
        """See `IProductRelease`."""
        # Create the alias for the file.
        filename = self.normalizeFilename(filename)
        file_obj, file_size = self._getFileObjectAndSize(file_content)

        alias = getUtility(ILibraryFileAliasSet).create(
            name=filename,
            size=file_size,
            file=file_obj,
            contentType=content_type)
        if signature_filename is not None and signature_content is not None:
            signature_obj, signature_size = self._getFileObjectAndSize(
                signature_content)
            signature_filename = self.normalizeFilename(
                signature_filename)
            signature_alias = getUtility(ILibraryFileAliasSet).create(
                name=signature_filename,
                size=signature_size,
                file=signature_obj,
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

    def getProductReleaseFileByName(self, name):
        """See `IProductRelease`."""
        for file_ in self.files:
            if file_.libraryfile.filename == name:
                return file_
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
        # Local import of Milestone to avoid import loop.
        from lp.registry.model.milestone import Milestone
        if len(list(serieses)) == 0:
            return EmptyResultSet()
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        series_ids = [series.id for series in serieses]
        result = store.find(
            ProductRelease,
            And(ProductRelease.milestone == Milestone.id),
                Milestone.productseriesID.is_in(series_ids))
        return result.order_by(Desc(ProductRelease.datereleased))

    def getFilesForReleases(self, releases):
        """See `IProductReleaseSet`."""
        if len(list(releases)) == 0:
            return ProductReleaseFile.select('1 = 2')
        return ProductReleaseFile.select(
            """ProductReleaseFile.productrelease IN %s""" % (
            sqlvalues([release.id for release in releases])),
            orderBy='-date_uploaded',
            prejoins=['libraryfile'])
