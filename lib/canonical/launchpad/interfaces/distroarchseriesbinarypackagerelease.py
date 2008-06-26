# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Binary package release in Distribution Architecture Release interfaces."""

__metaclass__ = type

__all__ = [
    'IDistroArchSeriesBinaryPackageRelease',
    ]

from zope.interface import Attribute

from canonical.launchpad.interfaces import IBinaryPackageRelease


class IDistroArchSeriesBinaryPackageRelease(IBinaryPackageRelease):
    """This is a BinaryPackageRelease-In-A-DistroArchSeries. It represents
    a real binary package release that has been uploaded to a distroseries
    and published for that specific architecture.
    """

    distroarchseries = Attribute("The distro architecture series.")
    binarypackagerelease = Attribute("The source package release.")

    name = Attribute("The binary package name as text")
    version = Attribute("The binary package version as text")
    displayname = Attribute("Display name for this package.")
    title = Attribute("Title for this package.")
    distribution = Attribute("The distribution.")
    distroseries = Attribute("The distro series.")

    distributionsourcepackagerelease = Attribute("The source package in "
        "this distribution from which this package was built.")

    distroarchseriesbinarypackage = Attribute(
        "The object representing all binary package versions with the "
        "same name in the same DistroArchSeries, its parent object.")

    pocket = Attribute("The pocket in which this release is published, "
        "or None if it is not currently published.")

    status = Attribute("The current publishing status of this release "
        "of the binary package, in this distroarchseries.")

    priority = Attribute("The current publishing priority of this release "
        "of the binary package, in this distroarchseries.")

    section = Attribute("The section in which this package is published "
        "or None if it is not currently published.")

    component = Attribute("The component in which this package is "
        "published or None if it is not currently published.")

    publishing_history = Attribute("Return a list of publishing "
        "records for this binary package release in this series "
        "and this architecture, of the distribution.")

    current_publishing_record = Attribute("The current PUBLISHED record "
        "of this binary package release in this distro arch release, or "
        "None if there is not one.")
