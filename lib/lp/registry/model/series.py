# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common implementations for a series."""

__metaclass__ = type

from sqlobject import StringCol

from zope.interface import implements

from lp.registry.interfaces.distroseries import ISeriesMixin
from lp.registry.interfaces.series import SeriesStatus


class SeriesMixin:
    """See `ISeriesMixin`."""

    implements(ISeriesMixin)

    summary = StringCol(notNull=True)

    @property
    def active(self):
        return self.status in [
            SeriesStatus.DEVELOPMENT,
            SeriesStatus.FROZEN,
            SeriesStatus.CURRENT,
            SeriesStatus.SUPPORTED,
            ]

    @property
    def bug_supervisor(self):
        """See `ISeriesMixin`."""
        return self.parent.bug_supervisor

    @property
    def security_contact(self):
        """See `ISeriesMixin`."""
        return self.parent.security_contact

    @property
    def drivers(self):
        """See `ISeriesMixin`."""
        drivers = set()
        drivers.add(self.driver)
        drivers = drivers.union(self.parent.drivers)
        drivers.discard(None)
        return sorted(drivers, key=lambda driver: driver.displayname)
