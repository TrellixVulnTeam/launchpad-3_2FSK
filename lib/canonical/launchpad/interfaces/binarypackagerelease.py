# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Binary package release interfaces."""

__metaclass__ = type

__all__ = [
    'IBinaryPackageRelease',
    'IBinaryPackageReleaseSet',
    ]

from zope.schema import Bool, Int, Text, TextLine, Datetime
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory

from canonical.launchpad import _

from canonical.launchpad.validators.version import valid_debian_version


class IBinaryPackageRelease(Interface):
    id = Int(title=_('ID'), required=True)
    binarypackagename = Int(required=True)
    version = TextLine(required=True, constraint=valid_debian_version)
    summary = Text(required=True)
    description = Text(required=True)
    build = Int(required=True)
    binpackageformat = Int(required=True)
    component = Int(required=True)
    section = Int(required=True)
    priority = Int(required=False)
    shlibdeps = Text(required=False)
    depends = Text(required=False)
    recommends = Text(required=False)
    suggests = Text(required=False)
    conflicts = Text(required=False)
    replaces = Text(required=False)
    provides = Text(required=False)
    essential = Bool(required=False)
    installedsize = Int(required=False)
    copyright = Text(required=False)
    licence = Text(required=False)
    architecturespecific = Bool(required=True)
    datecreated = Datetime(required=True, readonly=True)

    files = Attribute("Related list of IBinaryPackageFile entries")

    title = TextLine(required=True, readonly=True)
    name = Attribute("Binary Package Name")

    # properties
    distributionsourcepackagerelease = Attribute("The sourcepackage "
        "release in this distribution from which this binary was "
        "built.")

    def current(distroRelease):
        """Get the current BinaryPackage in a distrorelease"""

    def lastversions():
        """Return the SUPERSEDED BinaryPackages in a DistroRelease
           that comes from the same SourcePackage"""

    def addFile(file):
        """Create a BinaryPackageFile record referencing this build
        and attach the provided library file alias (file).
        """

    def publish(priority, status, pocket, embargo, distroarchrelease=None):
        """Publish this BinaryPackageRelease according the given parameters.

        The optional distroarchrelease argument defaults to the one choosen
        originally for the build record (helps on derivative procedures).
        """

class IBinaryPackageReleaseSet(Interface):
    """A set of binary packages"""
    
    def findByNameInDistroRelease(distroreleaseID, pattern,
                                  archtag=None, fti=False):
        """Returns a set of binarypackagereleases that matchs pattern
        inside a distrorelease"""

    def getByNameInDistroRelease(distroreleaseID, name):
        """Get an BinaryPackageRelease in a DistroRelease by its name"""

    def getDistroReleasePackages(distroreleaseID):
        """Get a set of BinaryPackageReleases in a distrorelease"""
    
    def getByNameVersion(distroreleaseID, name, version):
        """Get a set of BinaryPackageReleases in a
        DistroRelease by its name and version"""

    def getByArchtag(distroreleaseID, name, version, archtag):
        """Get a BinaryPackageRelease in a DistroRelease
        by its name, version and archtag"""

    def getBySourceName(DistroRelease, sourcepackagename):
        """Get a set of BinaryPackageRelease generated by the current
        SourcePackageRelease with an SourcePackageName inside a
        DistroRelease context.
        """
