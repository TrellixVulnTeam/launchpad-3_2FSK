
# Python imports
from sets import Set
from datetime import datetime

# Zope imports
from zope.interface import implements

# SQLObject/SQLBase
from sqlobject import MultipleJoin, RelatedJoin, AND, LIKE
from sqlobject import StringCol, ForeignKey, IntCol, MultipleJoin, BoolCol, \
                      DateTimeCol
from sqlobject.sqlbuilder import func

from canonical.database.sqlbase import SQLBase, quote
from canonical.lp import dbschema

# interfaces and database 
from canonical.launchpad.interfaces import IDistributionRole
from canonical.launchpad.interfaces import IDistroReleaseRole
from canonical.launchpad.interfaces import IDistroArchRelease
from canonical.launchpad.interfaces import IDistroTools

from canonical.launchpad.database.distribution import Distribution
from canonical.launchpad.database.sourcepackage import SourcePackage
from canonical.launchpad.database.sourcepackage import SourcePackageInDistro
from canonical.launchpad.database.binarypackage import BinaryPackage
from canonical.launchpad.database.product import Product
from canonical.launchpad.database.project import Project

class DistroArchRelease(SQLBase):

    implements(IDistroArchRelease)
    
    _table = 'DistroArchRelease'

    distrorelease = ForeignKey(dbName='distrorelease',
                               foreignKey='DistroRelease',
                               notNull=True)
    processorfamily = ForeignKey(dbName='processorfamily',
                                 foreignKey='ProcessorFamily',
                                 notNull=True)
    architecturetag = StringCol(dbName='architecturetag',
                              notNull=True)
    owner = ForeignKey(dbName='owner',
                       foreignKey='Person',
                       notNull=True)

class DistributionRole(SQLBase):

    implements(IDistributionRole)

    _table = 'DistributionRole'
    _columns = [
        ForeignKey(name='person', dbName='person', foreignKey='Person',
                   notNull=True),
        ForeignKey(name='distribution', dbName='distribution',
                   foreignKey='Distribution', notNull=True),
        IntCol('role', dbName='role')
        ]

    def _rolename(self):
        for role in dbschema.DistributionRole.items:
            if role.value == self.role:
                return role.title
        return 'Unknown (%d)' %self.role
    
    rolename = property(_rolename)
        

class DistroReleaseRole(SQLBase):

    implements(IDistroReleaseRole)

    _table = 'DistroReleaseRole'
    _columns = [
        ForeignKey(name='person', dbName='person', foreignKey='Person',
                   notNull=True),
        ForeignKey(name='distrorelease', dbName='distrorelease',
                   foreignKey='DistroRelease',
                   notNull=True),
        IntCol('role', dbName='role')
        ]

    def _rolename(self):
        for role in dbschema.DistroReleaseRole.items:
            if role.value == self.role:
                return role.title
        return 'Unknown (%d)' %self.role

    rolename = property(_rolename)

class Component(SQLBase):
    """  Component table SQLObject """

    _table = 'Component'

    _columns = [
        StringCol('name', dbName='name', notNull=True),
        ]

class Section(SQLBase):
    """  Section table SQLObject """

    _table = 'Section'

    _columns = [
        StringCol('name', dbName='name', notNull=True),
        ]

class DistroTools(object):
    """Tools for help Distribution and DistroRelase Manipulation """

    implements(IDistroTools)

    def createDistro(self, owner, name, displayname,
                     title, summary, description, domain):
        """Create a Distribution """
        ##XXX: cprov 20041207
        ## Verify the name constraint as the postgresql does.
        ## What about domain ??? 
        distro = Distribution(name=name,
                              displayname=displayname,
                              title=title,
                              summary=summary,
                              description=description,
                              domainname=domain,
                              owner=owner)

        self.createDistributionRole(distro.id, owner,
                                    dbschema.DistributionRole.DM.value)

        return distro
        

    def createDistroRelease(self, owner, title, distribution, shortdesc,
                            description, version, parent):
        ##XXX: cprov 20041207
        ## Verify the name constraint as the postgresql does.
        name = title.lower()

        ## XXX: cprov 20041207
        ## Define missed fields

        release = DistroRelease(name=name,
                                distribution=distribution,
                                title=title,
                                shortdesc=shortdesc,
                                description=description,
                                version=version,
                                owner=owner,
                                parentrelease=int(parent),
                                datereleased=datetime.utcnow(),
                                components=1,
                                releasestate=1,
                                sections=1,
                                lucilleconfig='')

        self.createDistroReleaseRole(release.id, owner,
                                     dbschema.DistroReleaseRole.RM.value)

        return release
    
    def getDistroReleases(self):
        return DistroRelease.select()
    

    def createDistributionRole(self, container_id, person, role):
        return DistributionRole(distribution=container_id,
                                personID=person, role=role)

    def createDistroReleaseRole(self, container_id, person, role):
        return DistroReleaseRole(distrorelease=container_id,
                                 personID=person, role=role)

