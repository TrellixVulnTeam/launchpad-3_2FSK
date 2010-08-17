# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Class that implements the IPersonRoles interface."""

__metaclass__ = type
__all__ = ['PersonRoles']

from zope.interface import implements
from zope.component import adapts, getUtility
from canonical.launchpad.interfaces import (
    IHasDrivers, ILaunchpadCelebrities, IPersonRoles)

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
        errortext = "'PersonRoles' object has no attribute '%s'" % name
        if not name.startswith(prefix):
            raise AttributeError(errortext)
        attribute = name[len(prefix):]
        try:
            return self.person.inTeam(getattr(self._celebrities, attribute))
        except AttributeError:
            raise AttributeError(errortext)

    @property
    def id(self):
        return self.person.id

    def isOwner(self, obj):
        """See IPersonRoles."""
        return self.person.inTeam(obj.owner)

    def isDriver(self, obj):
        """See IPersonRoles."""
        return self.person.inTeam(obj.driver)

    def isOneOfDrivers(self, obj):
        """See IPersonRoles."""
        if not IHasDrivers.providedBy(obj):
            return self.isDriver(obj)
        for driver in obj.drivers:
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

