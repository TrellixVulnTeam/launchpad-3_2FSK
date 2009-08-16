# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

__metaclass__ = type
__all__ = [
    'PackagePublishingPocket',
    'pocketsuffix',
    ]

from lazr.enum import DBEnumeratedType, DBItem


class PackagePublishingPocket(DBEnumeratedType):
    """Package Publishing Pocket

    A single distroseries can at its heart be more than one logical
    distroseries as the tools would see it. For example there may be a
    distroseries called 'hoary' and a SECURITY pocket subset of that would
    be referred to as 'hoary-security' by the publisher and the distro side
    tools.
    """

    RELEASE = DBItem(0, """
        Release

        The package versions that were published
        when the distribution release was made.
        For releases that are still under development,
        packages are published here only.
        """)

    SECURITY = DBItem(10, """
        Security

        Package versions containing security fixes for the released
        distribution.
        It is a good idea to have security updates turned on for your system.
        """)

    UPDATES = DBItem(20, """
        Updates

        Package versions including new features after the distribution
        release has been made.
        Updates are usually turned on by default after a fresh install.
        """)

    PROPOSED = DBItem(30, """
        Proposed

        Package versions including new functions that should be widely
        tested, but that are not yet part of a default installation.
        People who "live on the edge" will test these packages before they
        are accepted for use in "Updates".
        """)

    BACKPORTS = DBItem(40, """
        Backports

        Backported packages.
        """)


pocketsuffix = {
    PackagePublishingPocket.RELEASE: "",
    PackagePublishingPocket.SECURITY: "-security",
    PackagePublishingPocket.UPDATES: "-updates",
    PackagePublishingPocket.PROPOSED: "-proposed",
    PackagePublishingPocket.BACKPORTS: "-backports",
}
