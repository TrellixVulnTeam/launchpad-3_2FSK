# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Build', 'BuildSet']

from datetime import datetime
import xmlrpclib
from urllib2 import URLError

from zope.interface import implements
from zope.exceptions import NotFoundError
from zope.component import getUtility

# SQLObject/SQLBase
from sqlobject import (
    StringCol, ForeignKey, BoolCol, IntCol, IntervalCol)

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import (
    IBuild, IBuildSet)

from canonical.librarian.interfaces import ILibrarianClient

from canonical.lp.dbschema import EnumCol, BuildStatus


class Build(SQLBase):
    implements(IBuild)
    _table = 'Build'

    datecreated = UtcDateTimeCol(dbName='datecreated', notNull=True,
                                 default=UTC_NOW)

    processor = ForeignKey(dbName='processor', foreignKey='Processor', 
                           notNull=True)

    distroarchrelease = ForeignKey(dbName='distroarchrelease', 
                                   foreignKey='DistroArchRelease', 
                                   notNull=True)

    buildstate = EnumCol(dbName='buildstate', notNull=True, schema=BuildStatus)

    sourcepackagerelease = ForeignKey(dbName='sourcepackagerelease',
                                      foreignKey='SourcePackageRelease', 
                                      notNull=True)

    datebuilt = UtcDateTimeCol(dbName='datebuilt', notNull=False, default=None)

    buildduration = IntervalCol(dbName='buildduration', notNull=False,
                                default=None)

    buildlog = ForeignKey(dbName='buildlog', foreignKey='LibraryFileAlias',
                          notNull=False, default=None)

    builder = ForeignKey(dbName='builder', foreignKey='Builder',
                         notNull=False, default=None)

    gpgsigningkey = ForeignKey(dbName='gpgsigningkey', foreignKey='GPGKey',
                               notNull=False, default=None)

    changes = StringCol(dbName='changes', notNull=False, default=None)

    @property
    def distrorelease(self):
        """See IBuild"""
        return self.distroarchrelease.distrorelease

    @property
    def title(self):
        return '%s-%s' % (self.sourcepackagerelease.name,
                          self.sourcepackagerelease.version)
    @property
    def buildlogURL(self):
        downloader = getUtility(ILibrarianClient)
        try:
            url = downloader.getURLForAlias(self.buildlog.id)
        except URLError:
            # Librarian not running or file not available.
            pass
        else:
            return url


class BuildSet:
    implements(IBuildSet)

    def getBuildBySRAndArchtag(self, sourcepackagereleaseID, archtag):
        """See IBuilderSet"""
        clauseTables = ['DistroArchRelease']
        query = ('Build.sourcepackagerelease = %s '
                 'AND Build.distroarchrelease = DistroArchRelease.id '
                 'AND DistroArchRelease.architecturetag = %s'
                 % sqlvalues(sourcepackagereleaseID, archtag)
                 )

        return Build.select(query, clauseTables=clauseTables)

    def getBuiltForDistroRelease(self, distrorelease, size=10):
        """See IBuilderSet"""
        
        arch_ids = ''.join(['%d,' % arch.id for arch in
                            distrorelease.architectures])[:-1]
        
        return Build.select("distroarchrelease IN (%s)" % arch_ids)
    
