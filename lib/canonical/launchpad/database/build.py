# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Build', 'BuildSet']

from urllib2 import URLError

from zope.interface import implements
from zope.component import getUtility

# SQLObject/SQLBase
from sqlobject import (
    StringCol, ForeignKey, IntervalCol)

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

    datecreated = UtcDateTimeCol(dbName='datecreated', default=UTC_NOW)

    processor = ForeignKey(dbName='processor', foreignKey='Processor', 
                           notNull=True)

    distroarchrelease = ForeignKey(dbName='distroarchrelease', 
                                   foreignKey='DistroArchRelease', 
                                   notNull=True)

    buildstate = EnumCol(dbName='buildstate', notNull=True, schema=BuildStatus)

    sourcepackagerelease = ForeignKey(dbName='sourcepackagerelease',
                                      foreignKey='SourcePackageRelease', 
                                      notNull=True)

    datebuilt = UtcDateTimeCol(dbName='datebuilt', default=None)

    buildduration = IntervalCol(dbName='buildduration', default=None)

    buildlog = ForeignKey(dbName='buildlog', foreignKey='LibraryFileAlias',
                          default=None)

    builder = ForeignKey(dbName='builder', foreignKey='Builder',
                         default=None)

    gpgsigningkey = ForeignKey(dbName='gpgsigningkey', foreignKey='GPGKey',
                               default=None)

    changes = StringCol(dbName='changes', default=None)

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
        """See IBuildSet"""
        clauseTables = ['DistroArchRelease']
        query = ('Build.sourcepackagerelease = %s '
                 'AND Build.distroarchrelease = DistroArchRelease.id '
                 'AND DistroArchRelease.architecturetag = %s'
                 % sqlvalues(sourcepackagereleaseID, archtag)
                 )

        return Build.select(query, clauseTables=clauseTables)

    def getBuiltForDistroRelease(self, distrorelease, limit=10):
        """See IBuildSet"""
        arch_ids = ''.join(['%d,' % arch.id for arch in
                            distrorelease.architectures])[:-1]

        return Build.select("distroarchrelease IN (%s)" % arch_ids,
                            limit=limit, orderBy="-datebuilt")

    def getBuiltForDistroArchRelease(self, distroarchrelease, limit=10):
        """See IBuildSet"""
        return Build.select(
            "distroarchrelease=%s" % sqlvalues(distroarchrelease.id),
            limit=limit, orderBy="-datebuilt"
            )

    def getBuildsForDistribution(self, distro, state=None):
        """See IBuilderSet."""
        # XXX: stevea: 20051004: Once sqlvalues() can take a proxied
        # value, change this back to distro from distro.id
        # https://launchpad.net/products/launchpad/+bug/2836
        clause = ("build.sourcepackagerelease = sourcepackagerelease.id AND "
                  "sourcepackagepublishing.sourcepackagerelease=sourcepackagerelease.id AND "
                  "sourcepackagepublishing.distrorelease = distrorelease.id "
                  "AND distrorelease.distribution = %s" % sqlvalues(distro.id))
        if state is not None:
            clause += " AND build.buildstate = %s" % sqlvalues(state)
        return Build.select(clause, clauseTables=['SourcePackageRelease',
                                                  'SourcePackagePublishing',
                                                  'DistroRelease'])
