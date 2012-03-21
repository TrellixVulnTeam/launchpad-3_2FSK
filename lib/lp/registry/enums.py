# Copyright 2010-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enums for the Registry app."""

__metaclass__ = type
__all__ = [
    'DistroSeriesDifferenceStatus',
    'DistroSeriesDifferenceType',
    'InformationType',
    'PersonTransferJobType',
    'PRIVATE_INFORMATION_TYPES',
    'SECURITY_INFORMATION_TYPES',
    'SharingPermission',
    ]

from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )


class InformationType(DBEnumeratedType):
    """Information Type.

    The types used to control which users and teams can see various
    Launchpad artifacts, including bugs and branches.
    """

    PUBLIC = DBItem(1, """
        Public

        Everyone can see this information.
        """)

    UNEMBARGOEDSECURITY = DBItem(2, """
        Unembargoed Security

        Everyone can see this information pertaining to a resolved security
        related bug.
        """)

    EMBARGOEDSECURITY = DBItem(3, """
        Embargoed Security

        Only users with permission to see the project's security related
        artifacts can see this information.
        """)

    USERDATA = DBItem(4, """
        User Data

        Only users with permission to see the project's artifacts containing
        user data can see this information.
        """)

    PROPRIETARY = DBItem(5, """
        Proprietary

        Only users with permission to see the project's artifacts containing
        proprietary data can see this information.
        """)


PRIVATE_INFORMATION_TYPES = (
    InformationType.EMBARGOEDSECURITY, InformationType.USERDATA,
    InformationType.PROPRIETARY)


SECURITY_INFORMATION_TYPES = (
    InformationType.UNEMBARGOEDSECURITY, InformationType.EMBARGOEDSECURITY)


class SharingPermission(DBEnumeratedType):
    """Sharing permission.

    The level of access granted for a particular access policy.
    """

    NOTHING = DBItem(1, """
        Nothing

        Revoke all bug and branch subscriptions.
        """)

    ALL = DBItem(2, """
        All

        Share all bugs and branches.
        """)

    SOME = DBItem(3, """
        Some

        Share bug and branch subscriptions.
        """)


class DistroSeriesDifferenceStatus(DBEnumeratedType):
    """Distribution series difference status.

    The status of a package difference between two DistroSeries.
    """

    NEEDS_ATTENTION = DBItem(1, """
        Needs attention

        This difference is current and needs attention.
        """)

    BLACKLISTED_CURRENT = DBItem(2, """
        Blacklisted current version

        This difference is being ignored until a new package is uploaded
        or the status is manually updated.
        """)

    BLACKLISTED_ALWAYS = DBItem(3, """
        Blacklisted always

        This difference should always be ignored.
        """)

    RESOLVED = DBItem(4, """
        Resolved

        This difference has been resolved and versions are now equal.
        """)


class DistroSeriesDifferenceType(DBEnumeratedType):
    """Distribution series difference type."""

    UNIQUE_TO_DERIVED_SERIES = DBItem(1, """
        Unique to derived series

        This package is present in the derived series but not the parent
        series.
        """)

    MISSING_FROM_DERIVED_SERIES = DBItem(2, """
        Missing from derived series

        This package is present in the parent series but missing from the
        derived series.
        """)

    DIFFERENT_VERSIONS = DBItem(3, """
        Different versions

        This package is present in both series with different versions.
        """)


class PersonTransferJobType(DBEnumeratedType):
    """Values that IPersonTransferJob.job_type can take."""

    MEMBERSHIP_NOTIFICATION = DBItem(0, """
        Add-member notification

        Notify affected users of new team membership.
        """)

    MERGE = DBItem(1, """
        Person merge

        Merge one person or team into another person or team.
        """)
