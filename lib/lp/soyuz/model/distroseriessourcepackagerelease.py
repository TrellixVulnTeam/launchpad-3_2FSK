# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""Classes to represent source package releases in a distribution series."""

__metaclass__ = type

__all__ = [
    'DistroSeriesSourcePackageRelease',
    ]

from operator import attrgetter

from lazr.delegates import delegates
from zope.interface import implements

from canonical.database.sqlbase import sqlvalues
from lp.soyuz.interfaces.distroseriessourcepackagerelease import (
    IDistroSeriesSourcePackageRelease,
    )
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.publishing import SourcePackagePublishingHistory


class DistroSeriesSourcePackageRelease:
    """This is a "Magic SourcePackageRelease in Distro Release". It is not
    an SQLObject but instead it describes the behaviour of a specific
    release of the package in the distroseries."""

    implements(IDistroSeriesSourcePackageRelease)

    delegates(ISourcePackageRelease, context='sourcepackagerelease')

    def __init__(self, distroseries, sourcepackagerelease):
        self.distroseries = distroseries
        self.sourcepackagerelease = sourcepackagerelease

    @property
    def distribution(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return self.distroseries.distribution

    @property
    def sourcepackage(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return self.distroseries.getSourcePackage(self.sourcepackagename)

    @property
    def displayname(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return '%s %s' % (self.name, self.version)

    @property
    def title(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return '"%s" %s source package in %s' % (
            self.name, self.version, self.distroseries.title)

    @property
    def version(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return self.sourcepackagerelease.version

    @property
    def pocket(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.pocket

    @property
    def section(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.section

    @property
    def component(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.component

# XXX cprov 20071026: heavy queries should be moved near to the related
# content classes in order to be better maintained.
    @property
    def builds(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        # Find all the builds for the distribution and then filter them
        # for the current distroseries. We do this rather than separate
        # storm query because DSSPR will be removed later as part of the
        # planned package refactor.

        # Import DistributionSourcePackageRelease here to avoid circular
        # imports (and imported directly from database to avoid long line)
        from lp.soyuz.model.distributionsourcepackagerelease import (
            DistributionSourcePackageRelease)

        distro_builds = DistributionSourcePackageRelease(
            self.distroseries.distribution,
            self.sourcepackagerelease).builds

        return (
            [build for build in distro_builds
                if build.distro_arch_series.distroseries == self.distroseries])

    @property
    def files(self):
        """See `ISourcePackageRelease`."""
        return self.sourcepackagerelease.files

    @property
    def binaries(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        clauseTables = [
            'BinaryPackageRelease',
            'DistroArchSeries',
            'BinaryPackageBuild',
            'BinaryPackagePublishingHistory'
        ]

        query = """
        BinaryPackageRelease.build=BinaryPackageBuild.id AND
        DistroArchSeries.id =
            BinaryPackagePublishingHistory.distroarchseries AND
        BinaryPackagePublishingHistory.binarypackagerelease=
            BinaryPackageRelease.id AND
        DistroArchSeries.distroseries=%s AND
        BinaryPackagePublishingHistory.archive IN %s AND
        BinaryPackageBuild.source_package_release=%s
        """ % sqlvalues(self.distroseries,
                        self.distroseries.distribution.all_distro_archive_ids,
                        self.sourcepackagerelease)

        return BinaryPackageRelease.select(
                query, prejoinClauseTables=['BinaryPackageBuild'],
                orderBy=['-id'], clauseTables=clauseTables,
                distinct=True)

    @property
    def changesfile(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        return self.sourcepackagerelease.upload_changesfile

    @property
    def published_binaries(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        target_binaries = []

        # Get the binary packages in each distroarchseries and store them
        # in target_binaries for returning.  We are looking for *published*
        # binarypackagereleases in all arches for the 'source' and its
        # location.
        for binary in self.binaries:
            if binary.architecturespecific:
                considered_arches = [binary.build.distro_arch_series]
            else:
                considered_arches = self.distroseries.architectures

            for distroarchseries in considered_arches:
                dasbpr = distroarchseries.getBinaryPackage(
                    binary.name)[binary.version]
                # Only include objects with published binaries.
                if dasbpr is None or dasbpr.current_publishing_record is None:
                    continue
                target_binaries.append(dasbpr)

        return target_binaries

#
# Publishing lookup methods.
#

    @property
    def publishing_history(self):
        """See `IDistroSeriesSourcePackage`."""
        return SourcePackagePublishingHistory.select("""
            distroseries = %s AND
            archive IN %s AND
            sourcepackagerelease = %s
            """ % sqlvalues(
                    self.distroseries,
                    self.distroseries.distribution.all_distro_archive_ids,
                    self.sourcepackagerelease),
            orderBy='-datecreated')

    @property
    def current_publishing_record(self):
        """An internal property used by methods of this class to know where
        this release is or was published.
        """
        pub_hist = self.publishing_history
        try:
            return pub_hist[0]
        except IndexError:
            return None

    @property
    def current_published(self):
        """See `IDistroArchSeriesSourcePackage`."""
        # Retrieve current publishing info
        published_status = [
            PackagePublishingStatus.PENDING,
            PackagePublishingStatus.PUBLISHED]
        current = SourcePackagePublishingHistory.selectFirst("""
        distroseries = %s AND
        archive IN %s AND
        sourcepackagerelease = %s AND
        status IN %s
        """ % sqlvalues(self.distroseries,
                        self.distroseries.distribution.all_distro_archive_ids,
                        self.sourcepackagerelease,
                        published_status),
            orderBy=['-datecreated', '-id'])

        return current
