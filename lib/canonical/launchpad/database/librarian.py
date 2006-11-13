# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['LibraryFileContent', 'LibraryFileAlias', 'LibraryFileAliasSet']

from zope.component import getUtility
from zope.interface import implements

from canonical.launchpad.interfaces import (
    ILibraryFileContent, ILibraryFileAlias, ILibraryFileAliasSet)
from canonical.librarian.interfaces import ILibrarianClient
from canonical.database.sqlbase import SQLBase
from canonical.database.constants import UTC_NOW, DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from sqlobject import StringCol, ForeignKey, IntCol, SQLRelatedJoin, BoolCol


class LibraryFileContent(SQLBase):
    """A pointer to file content in the librarian."""

    implements(ILibraryFileContent)

    _table = 'LibraryFileContent'

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    datemirrored = UtcDateTimeCol(default=None)
    filesize = IntCol(notNull=True)
    sha1 = StringCol(notNull=True)
    md5 = StringCol()
    deleted = BoolCol(notNull=True, default=False)


class LibraryFileAlias(SQLBase):
    """A filename and mimetype that we can serve some given content with."""

    implements(ILibraryFileAlias)

    _table = 'LibraryFileAlias'

    content = ForeignKey(
            foreignKey='LibraryFileContent', dbName='content', notNull=True,
            )
    filename = StringCol(notNull=True)
    mimetype = StringCol(notNull=True)
    expires = UtcDateTimeCol(notNull=False, default=None)
    last_accessed = UtcDateTimeCol(notNull=True, default=DEFAULT)

    products = SQLRelatedJoin('ProductRelease', joinColumn='libraryfile',
                           otherColumn='productrelease',
                           intermediateTable='ProductReleaseFile')

    sourcepackages = SQLRelatedJoin('SourcePackageRelease',
                                 joinColumn='libraryfile',
                                 otherColumn='sourcepackagerelease',
                                 intermediateTable='SourcePackageReleaseFile')

    @property
    def url(self):
        """See ILibraryFileAlias.url"""
        return getUtility(ILibrarianClient).getURLForAlias(self.id)

    @property
    def secure_url(self):
        """See ILibraryFileAlias.secure_url"""
        if not self.url:
            return None
        return self.url.replace('http', 'https', 1)

    _datafile = None

    def open(self):
        client = getUtility(ILibrarianClient)
        self._datafile = client.getFileByAlias(self.id)

    def read(self, chunksize=None):
        """See ILibraryFileAlias.read"""
        if not self._datafile:
            if chunksize is not None:
                raise RuntimeError("Can't combine autoopen with chunksize")
            self.open()
            autoopen = True
        else:
            autoopen = False

        if chunksize is None:
            rv = self._datafile.read()
            if autoopen:
                self.close()
            return rv
        else:
            return self._datafile.read(chunksize)

    def close(self):
        self._datafile.close()
        self._datafile = None


class LibraryFileAliasSet(object):
    """Create and find LibraryFileAliases."""

    implements(ILibraryFileAliasSet)

    def create(self, name, size, file, contentType, expires=None, debugID=None):
        """See ILibraryFileAliasSet.create"""
        client = getUtility(ILibrarianClient)
        fid = client.addFile(name, size, file, contentType, expires, debugID)
        return LibraryFileAlias.get(fid)

    def __getitem__(self, key):
        """See ILibraryFileAliasSet.__getitem__"""
        return LibraryFileAlias.get(key)

    def findBySHA1(self, sha1):
        """See ILibraryFileAliasSet."""
        return LibraryFileAlias.select("""
            content = LibraryFileContent.id
            AND LibraryFileContent.sha1 = '%s'
            """ % sha1, clauseTables=['LibraryFileContent'])

