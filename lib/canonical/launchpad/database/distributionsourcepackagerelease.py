# Copyright 2005-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Classes to represent source package releases in a distribution."""

__metaclass__ = type

__all__ = [
    'DistributionSourcePackageRelease',
    ]

from zope.component import getUtility
from zope.interface import implements

from canonical.launchpad.interfaces import(
    IDistributionSourcePackageRelease, ISourcePackageRelease)

from canonical.database.sqlbase import sqlvalues

from canonical.launchpad.database.archive import Archive
from canonical.launchpad.database.binarypackagename import BinaryPackageName
from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.distroseriesbinarypackage import (
    DistroSeriesBinaryPackage)
from canonical.launchpad.database.publishing import (
    BinaryPackagePublishingHistory)
from canonical.launchpad.database.build import Build
from canonical.launchpad.database.publishing import \
    SourcePackagePublishingHistory
from canonical.launchpad.interfaces.archive import MAIN_ARCHIVE_PURPOSES
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)

from lazr.delegates import delegates


class DistributionSourcePackageRelease:
    """This is a "Magic Distribution Source Package Release". It is not an
    SQLObject, but it represents the concept of a specific source package
    release in the distribution. You can then query it for useful
    information.
    """

    implements(IDistributionSourcePackageRelease)
    delegates(ISourcePackageRelease, context='sourcepackagerelease')

    def __init__(self, distribution, sourcepackagerelease):
        self.distribution = distribution
        self.sourcepackagerelease = sourcepackagerelease

    @property
    def sourcepackage(self):
        """See IDistributionSourcePackageRelease"""
        return self.distribution.getSourcePackage(
            self.sourcepackagerelease.sourcepackagename)

    @property
    def displayname(self):
        """See IDistributionSourcePackageRelease."""
        return '%s in %s' % (self.name, self.distribution.name)

    @property
    def title(self):
        """See IDistributionSourcePackageRelease."""
        return '%s %s (source) in %s' % (
            self.name, self.version, self.distribution.displayname)

    @property
    def publishing_history(self):
        """See IDistributionSourcePackageRelease."""
        return SourcePackagePublishingHistory.select("""
            DistroSeries.distribution = %s AND
            SourcePackagePublishingHistory.distroseries =
                DistroSeries.id AND
            SourcePackagePublishingHistory.archive IN %s AND
            SourcePackagePublishingHistory.sourcepackagerelease = %s
            """ % sqlvalues(self.distribution,
                            self.distribution.all_distro_archive_ids,
                            self.sourcepackagerelease),
            clauseTables=['DistroSeries'],
            orderBy='-datecreated')

    @property
    def builds(self):
        """See IDistributionSourcePackageRelease."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)

        # Import DistroArchSeries here to avoid circular imports.
        from canonical.launchpad.database.distroarchseries import (
            DistroArchSeries)
        from lp.registry.model.distroseries import DistroSeries

        # The builds are joined with their publishing histories to
        # restrict the results to only those builds that have been published
        # in a main archive. So a PPA build won't be included unless it
        # was also published in a main archive.
        builds_published_in_main_archives = store.find(
            Build,

            # First the expressions to get the builds in this
            # Distribution:
            Build.sourcepackagerelease == self.sourcepackagerelease,
            Build.distroarchseries == DistroArchSeries.id,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == self.distribution,

            # Then narrow it down to only those builds with binaries
            # published in main archives:
            BinaryPackageRelease.build == Build.id,
            BinaryPackagePublishingHistory.binarypackagerelease ==
                BinaryPackageRelease.id,
            BinaryPackagePublishingHistory.archive == Archive.id,
            Archive.purpose.is_in(MAIN_ARCHIVE_PURPOSES))

        return builds_published_in_main_archives.config(
            distinct=True).order_by('datecreated DESC', 'id DESC')

    @property
    def binary_package_names(self):
        """See IDistributionSourcePackageRelease."""
        return BinaryPackageName.select("""
            BinaryPackageName.id =
                BinaryPackageRelease.binarypackagename AND
            BinaryPackageRelease.build = Build.id AND
            Build.sourcepackagerelease = %s
            """ % sqlvalues(self.sourcepackagerelease.id),
            clauseTables=['BinaryPackageRelease', 'Build'],
            orderBy='name',
            distinct=True)

    @property
    def sample_binary_packages(self):
        """See IDistributionSourcePackageRelease."""
        all_published = BinaryPackagePublishingHistory.select("""
            BinaryPackagePublishingHistory.distroarchseries =
                DistroArchSeries.id AND
            DistroArchSeries.distroseries = DistroSeries.id AND
            DistroSeries.distribution = %s AND
            BinaryPackagePublishingHistory.archive IN %s AND
            BinaryPackagePublishingHistory.binarypackagerelease =
                BinaryPackageRelease.id AND
            BinaryPackageRelease.binarypackagename = BinaryPackageName.id AND
            BinaryPackageRelease.build = Build.id AND
            Build.sourcepackagerelease = %s
            """ % sqlvalues(self.distribution,
                            self.distribution.all_distro_archive_ids,
                            self.sourcepackagerelease),
            distinct=True,
            orderBy=['-datecreated'],
            clauseTables=['DistroArchSeries', 'DistroSeries',
                          'BinaryPackageRelease', 'BinaryPackageName',
                          'Build'],
            prejoinClauseTables=['BinaryPackageRelease', 'BinaryPackageName'])
        samples = []
        names = set()
        for publishing in all_published:
            if publishing.binarypackagerelease.binarypackagename not in names:
                names.add(publishing.binarypackagerelease.binarypackagename)
                samples.append(
                    DistroSeriesBinaryPackage(
                        publishing.distroarchseries.distroseries,
                        publishing.binarypackagerelease.binarypackagename))
        return samples
