# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['PublishedPackage', 'PublishedPackageSet']

from zope.interface import implements

from sqlobject import StringCol, ForeignKey, IntCol

from canonical.database.sqlbase import SQLBase, quote, quote_like
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.interfaces import (
    IPublishedPackage, IPublishedPackageSet)
from canonical.lp.dbschema import EnumCol
from canonical.lp.dbschema import PackagePublishingStatus


class PublishedPackage(SQLBase):
    """See IPublishedPackage for details."""

    implements(IPublishedPackage)

    _table = 'PublishedPackageView'

    distribution = IntCol(immutable=True)
    distroarchrelease = ForeignKey(dbName='distroarchrelease',
                                   foreignKey='DistroArchRelease',
                                   immutable=True)
    distrorelease = IntCol(immutable=True)
    distroreleasename = StringCol(immutable=True)
    processorfamily = IntCol(immutable=True)
    processorfamilyname = StringCol(immutable=True)
    packagepublishingstatus = EnumCol(immutable=True,
                                      schema=PackagePublishingStatus)
    component = StringCol(immutable=True)
    section = StringCol(immutable=True)
    binarypackagerelease = IntCol(immutable=True)
    binarypackagename = StringCol(immutable=True)
    binarypackagesummary = StringCol(immutable=True)
    binarypackagedescription = StringCol(immutable=True)
    binarypackageversion = StringCol(immutable=True)
    build = ForeignKey(foreignKey='Build', dbName='build')
    datebuilt = UtcDateTimeCol(immutable=True)
    sourcepackagerelease = IntCol(immutable=True)
    sourcepackagereleaseversion = StringCol(immutable=True)
    sourcepackagename = StringCol(immutable=True)


class PublishedPackageSet:

    implements(IPublishedPackageSet)

    def __iter__(self):
        return iter(PublishedPackage.select())

    def query(self, name=None, text=None, distribution=None,
              distrorelease=None, distroarchrelease=None, component=None):
        queries = []
        if name:
            name = name.lower().strip().split()[0]
            queries.append("binarypackagename ILIKE '%%' || %s || '%%'"
                           % quote_like(name))
        if distribution:
            queries.append("distribution = %d" % distribution.id)
        if distrorelease:
            queries.append("distrorelease = %d" % distrorelease.id)
        if distroarchrelease:
            queries.append("distroarchrelease = %d" % distroarchrelease.id)
        if component:
            queries.append("component = %s" % quote(component))
        if text:
            text = text.lower().strip()
            queries.append("binarypackagefti @@ ftq(%s)" % quote(text))
        return PublishedPackage.select(" AND ".join(queries), orderBy=['-datebuilt',])

    def findDepCandidate(self, name, distroarchrelease):
        """See IPublishedSet."""
        return PublishedPackage.selectOneBy(
            binarypackagename=name, distroarchreleaseID=distroarchrelease.id
            )
