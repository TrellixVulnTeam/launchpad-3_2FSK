# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""Classes to represent source package releases in a distribution."""

__metaclass__ = type

__all__ = [
    'DistributionSourcePackageRelease',
    ]

from zope.component import getUtility
from zope.interface import implements

from storm.expr import Desc

from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease)
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease
from canonical.database.sqlbase import sqlvalues

from lp.soyuz.model.archive import Archive
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import (
    BinaryPackageRelease)
from lp.soyuz.model.distroseriesbinarypackage import (
    DistroSeriesBinaryPackage)
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory)
from lp.soyuz.model.build import Build
from lp.soyuz.model.publishing import \
    SourcePackagePublishingHistory
from lp.soyuz.interfaces.archive import MAIN_ARCHIVE_PURPOSES
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
        return '"%s" %s source package in %s' % (
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
        from lp.soyuz.model.distroarchseries import (
            DistroArchSeries)
        from lp.registry.model.distroseries import DistroSeries

        # We want to return all the builds for this distribution that
        # were built for a main archive together with the builds for this
        # distribution that were built for a PPA but have been published
        # in a main archive.
        builds_for_distro_exprs = (
            Build.sourcepackagerelease == self.sourcepackagerelease,
            Build.distroarchseries == DistroArchSeries.id,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == self.distribution,
            )

        # First, get all the builds built in a main archive (this will
        # include new and failed builds.)
        builds_built_in_main_archives = store.find(
            Build,
            builds_for_distro_exprs,
            Build.archive == Archive.id,
            Archive.purpose.is_in(MAIN_ARCHIVE_PURPOSES))

        # Next get all the builds that have a binary published in the
        # main archive... this will include many of those in the above
        # query, but not the new/failed ones. It will also include
        # ppa builds that have been published in main archives.
        builds_published_in_main_archives = store.find(
            Build,
            builds_for_distro_exprs,
            BinaryPackageRelease.build == Build.id,
            BinaryPackagePublishingHistory.binarypackagerelease ==
                BinaryPackageRelease.id,
            BinaryPackagePublishingHistory.archive == Archive.id,
            Archive.purpose.is_in(MAIN_ARCHIVE_PURPOSES)).config(
                distinct=True)

        return builds_built_in_main_archives.union(
            builds_published_in_main_archives).order_by(
                Desc(Build.datecreated), Desc(Build.id))

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
            orderBy=['BinaryPackageName.name'],
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
