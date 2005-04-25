# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

# Python Imports
from sets import Set

# Zope Imports
from zope.interface import implements

# SQL Imports
from sqlobject import MultipleJoin
from sqlobject import StringCol, ForeignKey, MultipleJoin, DateTimeCol, \
     RelatedJoin
from canonical.database.sqlbase import SQLBase, quote

# Launchpad Imports
from canonical.lp.dbschema import EnumCol, \
        SourcePackageFormat, BugTaskStatus, BugSeverity, \
        PackagePublishingStatus, ImportStatus, PackagingType

from canonical.launchpad.interfaces import ISourcePackage, ISourcePackageSet
from canonical.launchpad.database.bugtask import BugTask
from canonical.launchpad.database.packaging import Packaging
from canonical.launchpad.database.vsourcepackagereleasepublishing import \
    VSourcePackageReleasePublishing
from canonical.launchpad.database.sourcepackageindistro import \
    SourcePackageInDistro
from canonical.launchpad.database.sourcepackagerelease import \
    SourcePackageRelease
from canonical.launchpad.database.sourcepackagename import \
    SourcePackageName
from canonical.launchpad.database.potemplate import POTemplate

from sourcerer.deb.version import Version

class SourcePackage(object):
    """A source package, e.g. apache2, in a distribution or distrorelease.
    This object implements the MagicSourcePackage specification. It is not a
    true database object, but rather attempts to represent the concept of a
    source package in a distribution, with links to the relevant dataase
    objects.
    
    Note that the Magic SourcePackage can be initialised with EITHER a
    distrorelease OR a distribution. This means you can specify either
    "package foo in ubuntu" or "package foo in warty", and then methods
    should work as expected.
    """

    implements(ISourcePackage)

    def __init__(self, sourcepackagename, distrorelease=None,
                 distribution=None):
        """SourcePackage requires a SourcePackageName and a
        DistroRelease or Distribution. These must be Launchpad
        database objects. If you give it a Distribution, it will try to find
        and use the Distribution.currentrelease, failing if that is not
        possible."""
        if distribution and distrorelease:
            raise TypeError, 'Cannot initialise SourcePackage with both distro and distrorelease'
        self.sourcepackagename = sourcepackagename
        self.distrorelease = distrorelease
        if distribution:
            self.distrorelease = distribution.currentrelease
            if not self.distrorelease:
                raise ValueError, "Distro '%s' has no current release" % distribution.name
        # set self.currentrelease based on current published sourcepackage
        # with this name in the distrorelease. if none is published, leave
        # self.currentrelease as None
        try:
            r = SourcePackageInDistro.selectBy(
                    sourcepackagenameID=sourcepackagename.id,
                    distroreleaseID = self.distrorelease.id)[0]
            self.currentrelease = SourcePackageRelease.get(r.id)
        except IndexError:
            # there is no published package in that distrorelease with this
            # name
            self.currentrelease = None

    def displayname(self):
        dn = ' the ' + self.sourcepackagename.name + ' source package in '
        dn += self.distrorelease.displayname
        return dn
    displayname = property(displayname)

    def title(self):
        titlestr = self.sourcepackagename.name
        titlestr += ' in ' + self.distribution.displayname
        titlestr += ' ' + self.distrorelease.displayname
        return titlestr
    title = property(title)

    def distribution(self):
        return self.distrorelease.distribution
    distribution = property(distribution)

    def distro(self):
        return self.distribution
    distro = property(distro)

    def format(self):
        return self.currentrelease.format
    format = property(format)

    def changelog(self):
        return self.currentrelease.changelog
    changelog = property(changelog)

    def manifest(self):
        """For the moment, the manifest of a SourcePackage is defined as the
        manifest of the .currentrelease of that SourcePackage in the
        distrorelease. In future, we might have a separate table for the
        current working copy of the manifest for a source package."""
        return self.currentrelease.manifest
    manifest = property(manifest)

    def maintainer(self):
        querystr = "distribution = %i AND sourcepackagename = %i"
        querystr %= (self.distribution, self.sourcepackagename)
        return Maintainership.select(querystr)
    maintainer = property(maintainer)

    def releases(self):
        """For the moment, we will return all releases with the same name.
        Clearly, this is wrong, because it will mix different flavors of a
        sourcepackage as well as releases of entirely different
        sourcepackages (say, from RedHat and Ubuntu) that have the same
        name. Later, we want to use the PublishingMorgue spec to get a
        proper set of sourcepackage releases specific to this
        distrorelease. Please update this when PublishingMorgue is
        implemented. Note that the releases are sorted by debian
        version number sorting."""
        # use a Set because we have no DISTINCT capability
        ret = SourcePackageRelease.select(
                      "sourcepackagename = %d" % self.sourcepackagename.id,
                      orderBy=["version"],
                      distinct=True)
        # sort by debian version number
        L = [(Version(item.version), item) for item in ret]
        L.sort()
        ret = [item for sortkey, item in L]
        return ret
    releases = property(releases)

    def releasehistory(self):
        """This is just like .releases but it spans ALL the distroreleases
        for this distribution. So it is a full history of all the releases
        ever published in this distribution. Again, it needs to be fixed
        when PublishingMorgue is implemented."""
        # use a Set because we have no DISTINCT capability
        ret = Set(SourcePackageRelease.select(
                      "sourcepackagename = %d" % self.sourcepackagename.id,
                      orderBy=["version"]))
        # sort by debian version number
        L = [(Version(item.version), item) for item in ret]
        L.sort()
        ret = [item for sortkey, item in L]
        return ret
    releasehistory = property(releasehistory)

    # Properties
    def name(self):
        return self.sourcepackagename.name
    name = property(name)

    def bugtasks(self):
        querystr = "distribution = %i AND sourcepackagename = %i"
        querystr %= (self.distribution, self.sourcepackagename)
        return BugTask.select(querystr)
    bugtasks = property(bugtasks)

    def potemplates(self):
        return POTemplate.selectBy(
                    distroreleaseID=self.distrorelease.id,
                    sourcepackagenameID=self.sourcepackagename.id)
    potemplates = property(potemplates)

    def potemplatecount(self):
        return self.potemplates.count()
    potemplatecount = property(potemplatecount)

    def product(self):
        # we have moved to focusing on productseries as the linker
        from warnings import warn
        warn('SourcePackage.product is deprecated, use .productseries',
             DeprecationWarning, stacklevel=2)
        ps = self.productseries
        if ps is not None:
            return ps.product
        return None
    product = property(product)

    def productseries(self):
        # First we look to see if there is packaging data for this
        # distrorelease and sourcepackagename. If not, we look up through
        # parent distroreleases, and when we hit Ubuntu, we look backwards in
        # time through Ubuntu releases till we find packaging information or
        # blow past the Warty Warthog.

        # get any packagings matching this sourcepackage
        packagings = Packaging.selectBy(
                        sourcepackagenameID=self.sourcepackagename.id,
                        distroreleaseID=self.distrorelease.id)
        # now, return any Primary Packaging's found
        for pkging in packagings:
            if pkging.packaging == PackagingType.PRIME:
                return pkging.productseries
        # ok, we're scraping the bottom of the barrel, send the first
        # packaging we have
        if packagings.count() > 0:
            return packagings[0].productseries
        # if we are an ubuntu sourcepackage, try the previous release of
        # ubuntu
        if self.distribution.name == 'ubuntu':
            datereleased = self.distrorelease.datereleased
            # if this one is unreleased, use the last released one
            if not datereleased:
                datereleased = 'NOW'
            from canonical.launchpad.database.distrorelease import \
                    DistroRelease
            ubuntureleases = DistroRelease.select(
                "distribution = %d AND "
                "datereleased < %s " % ( self.distribution.id,
                                         quote(datereleased) ),
                orderBy=['-datereleased'])
            if ubuntureleases.count() > 0:
                previous_ubuntu_release = ubuntureleases[0]
                sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                                   distrorelease=previous_ubuntu_release)
                return sp.productseries
        # if we have a parent distrorelease, try that
        if self.distrorelease.parentrelease is not None:
            sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                               distrorelease=self.distrorelease.parentrelease)
            return sp.productseries
        # capitulate
        return None
    productseries = property(productseries)

    def shouldimport(self):
        """Note that this initial implementation of the method knows that we
        are only interested in importing hoary and breezy packages
        initially. Also, it knows that we should only import packages where
        the upstream revision control is in place and working.
        """
        if self.distrorelease.name <> "hoary":
            return False
        if self.product is None:
            return False
        for series in self.product.serieslist:
            if series.branch is not None:
                return True
        return False
    shouldimport = property(shouldimport)

    def bugsCounter(self):
        from canonical.launchpad.database.bugtask import BugTask

        ret = [len(self.bugs)]
        severities = [
            BugSeverity.CRITICAL,
            BugSeverity.MAJOR,
            BugSeverity.NORMAL,
            BugSeverity.MINOR,
            BugSeverity.WISHLIST,
            BugTaskStatus.FIXED,
            BugTaskStatus.ACCEPTED,
        ]
        for severity in severities:
            n = BugTask.selectBy(severity=int(severity),
                                 sourcepackagenameID=self.sourcepackagename.id,
                                 distributionID=self.distribution.id).count()
            ret.append(n)
        return ret

    def getVersion(self, version):
        """This will look for a sourcepackage release with the given version
        in the distribution of this sourcepackage, NOT just the
        distrorelease of the sourcepackage. NB - this assumes that a given
        sourcepackagerelease version is UNIQUE in a distribution. This is
        true of Ubuntu, RedHat and similar distros, but might not be
        universally true. Please update when PublishingMorgue spec is
        implemented to use the full publishing history."""
        ret = VSourcePackageReleasePublishing.selectBy(
                        sourcepackagename=self.sourcepackagename,
                        distribution=self.distribution,
                        version=version)
        if ret.count() == 0:
            return None
        # we assume that there is only ever one source package release with
        # a given version published in the distro, across all
        # distroreleases.
        assert ret.count() < 2
        return ret[0]

    def pendingrelease(self):
        ret = VSourcePackageReleasePublishing.selectBy(
                sourcepackagenameID=self.sourcepackagename.id,
                publishingstatus=PackagePublishingStatus.PENDING,
                distroreleaseID = self.distrorelease.id)
        if ret.count() == 0:
            return None
        return SourcePackageRelease.get(r[0].id)
    pendingrelease = property(pendingrelease)

    def publishedreleases(self):
        ret = VSourcePackageReleasePublishing.selectBy(
                sourcepackagenameID=self.sourcepackagename.id,
                publishingstatus=[PackagePublishingStatus.PUBLISHED,
                                  PackagePublishingStatus.SUPERSEDED],
                distroreleaseID = self.distrorelease.id)
        if ret.count() == 0:
            return None
        return list(ret)
    publishedreleases = property(publishedreleases)



class SourcePackageSet(object):
    """A set of Magic SourcePackage objects."""

    implements(ISourcePackageSet)

    def __init__(self, distribution=None, distrorelease=None):
        if distribution is not None and distrorelease is not None:
            if distrorelease.distribution is not distribution:
                raise TypeError, 'Must instantiate SourcePackageSet with distribution or distrorelease, not both'
        if distribution:
            self.distribution = distribution
            self.distrorelease = distribution.currentrelease
            self.title = distribution.title
        elif distrorelease:
            self.distribution = distrorelease.distribution
            self.distrorelease = distrorelease
            self.title = distrorelease.title
        else:
            self.title = ""
        self.title += " Source Packages"

    def __getitem__(self, name):
        try:
            spname = SourcePackageName.byName(name)
        except IndexError:
            raise KeyError, 'No source package name %s' % name
        return SourcePackage(sourcepackagename=spname,
                             distrorelease=self.distrorelease)

    def __iter__(self, text=None):
        querystr = self._querystr(text)
        for row in VSourcePackageReleasePublishing.select(querystr):
            yield row

    def _querystr(self, text=None):
        querystr = ''
        if self.distrorelease:
            querystr += 'distrorelease = %d' %  self.distrorelease 
        if text:
            if len(querystr):
                querystr += ' AND '
            querystr += "name ILIKE " + quote('%%' + text + '%%') 
        return querystr

    def query(self, text=None):
        querystr = self._querystr(text)
        for row in VSourcePackageReleasePublishing.select(querystr):
            yield SourcePackage(sourcepackagename=row.sourcepackagename,
                                distrorelease=row.distrorelease)

    def withBugs(self):
        pkgset = Set()
        results = BugTask.select(
            "distribution = %d AND sourcepackagename IS NOT NULL" % (
                self.distribution ) )
        for task in results:
            pkgset.add(task.sourcepackagename)

        return [SourcePackage(sourcepackagename=sourcepackagename,
                              distribution=self.distribution)
                    for sourcepackagename in pkgset]


