# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Class that implements the IPersonRoles interface."""

__metaclass__ = type
__all__ = ['PersonRoles']

from zope.interface import implements
from zope.component import adapts, getUtility
from canonical.launchpad.interfaces import (
    ILaunchpadCelebrities, IPersonRoles)

from lp.registry.interfaces.person import IPerson


class PersonRoles:
    implements(IPersonRoles)
    adapts(IPerson)

    def __init__(self, person):
        self.person = person
        self._celebrities = getUtility(ILaunchpadCelebrities)
        self.inTeam = self.person.inTeam

    def __getattr__(self, name):
        """Handle all in_* attributes."""
        prefix = 'in_'
        if not name.startswith(prefix):
            raise AttributeError
        attribute = name[len(prefix):]
        return self.person.inTeam(getattr(self._celebrities, attribute))

    def isOwner(self, obj):
        """See IPersonRoles."""
        return self.person.inTeam(obj.owner)

    def isDriver(self, obj):
        """See IPersonRoles."""
        drivers = getattr(obj, 'drivers', None)
        if drivers is None:
            return self.person.inTeam(obj.driver)
        for driver in drivers:
            if self.person.inTeam(driver):
                return True
        return False

    def isOneOf(self, obj, attributes):
        """See IPersonRoles."""
        for attr in attributes:
            role = getattr(obj, attr)
            if self.person.inTeam(role):
                return True
        return False

