# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Logic for bulk copying of source/binary publishing history data."""

__metaclass__ = type

__all__ = [
    'build_package_location',
    'PackageLocation',
    'PackageLocationError',
    ]


from zope.component import getUtility

from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.soyuz.interfaces.archive import ArchivePurpose, IArchiveSet
from lp.registry.interfaces.distribution import IDistributionSet
from lp.soyuz.interfaces.publishing import PackagePublishingPocket


class PackageLocation:
    """Object used to model locations when copying publications.

    It groups distribution, distroseries and pocket in a way they
    can be easily manipulated and compared.
    """
    archive = None
    distribution = None
    distroseries = None
    pocket = None
    component = None

    def __init__(self, archive, distribution, distroseries, pocket,
                 component=None):
        """Initialize the PackageLocation from the given parameters."""
        self.archive = archive
        self.distribution = distribution
        self.distroseries = distroseries
        self.pocket = pocket
        self.component = component

    def __eq__(self, other):
        if (self.distribution == other.distribution and
            self.archive == other.archive and
            self.distroseries == other.distroseries and
            self.component == other.component and
            self.pocket == other.pocket):
            return True
        return False

    def __str__(self):
        # Use ASCII-only for copy archive and PPA titles, owner names can
        # contain unicode.
        if self.archive.is_ppa:
            title = self.archive.owner.name
        elif self.archive.is_copy:
            title = "%s/%s" % (self.archive.owner.name, self.archive.name)
        else:
            title = self.archive.displayname

        result = '%s: %s-%s' % (
            title, self.distroseries.name, self.pocket.name)

        if self.component is not None:
            result += ' (%s)' % self.component.name

        return result


class PackageLocationError(Exception):
    """Raised when something went wrong when building PackageLocation."""


def build_package_location(distribution_name, suite=None, purpose=None,
                           person_name=None, archive_name=None):
    """Convenience function to build PackageLocation objects."""

    # XXX kiko 2007-10-24:
    # We need a way to specify exactly what location we want
    # through strings in the command line. Until we do, we will end up
    # with this horrible set of self-excluding options that make sense
    # to nobody. Perhaps:
    #   - ppa.launchpad.net/cprov/ubuntu/warty
    #   - archive.ubuntu.com/ubuntu-security/hoary
    #   - security.ubuntu.com/ubuntu/hoary
    #   - archive.canonical.com/gutsy

    try:
        distribution = getUtility(IDistributionSet)[distribution_name]
    except NotFoundError, err:
        raise PackageLocationError(
            "Could not find distribution %s" % err)

    if purpose == ArchivePurpose.PPA:
        assert person_name is not None and archive_name is not None, (
            "person_name and archive_name should be passed for PPA archives.")
        archive = getUtility(IArchiveSet).getPPAByDistributionAndOwnerName(
            distribution, person_name, archive_name)
        if archive is None:
            raise PackageLocationError(
                "Could not find a PPA for %s named %s"
                % (person_name, archive_name))
        if distribution != archive.distribution:
            raise PackageLocationError(
                "The specified archive is not for distribution %s"
                % distribution_name)
    elif purpose == ArchivePurpose.PARTNER:
        assert person_name is None and archive_name is None, (
            "person_name and archive_name shoudn't be passed for "
            "PARTNER archive.")
        archive = getUtility(IArchiveSet).getByDistroPurpose(
            distribution, purpose)
        if archive is None:
            raise PackageLocationError(
                "Could not find %s archive for %s" % (
                purpose.title, distribution_name))
    elif purpose == ArchivePurpose.COPY:
        assert archive_name is not None, (
            "archive_name should be passed for COPY archives")
        archive = getUtility(IArchiveSet).getByDistroPurpose(
            distribution, purpose, name=archive_name)
        if archive is None:
            raise PackageLocationError(
                "Could not find %s archive with the name '%s' for %s" % (
                    purpose.title, archive_name, distribution.name))
    else:
        assert person_name is None and archive_name is None, (
            "person_name and archive_name shoudn't be passed when purpose "
            "is omitted.")
        archive = distribution.main_archive

    if suite is not None:
        try:
            distroseries, pocket = distribution.getDistroSeriesAndPocket(
                suite)
        except NotFoundError, err:
            raise PackageLocationError(
                "Could not find suite %s" % err)
    else:
        distroseries = distribution.currentseries
        pocket = PackagePublishingPocket.RELEASE

    return PackageLocation(archive, distribution, distroseries, pocket)
