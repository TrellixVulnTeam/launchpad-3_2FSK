# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class to implement the Launchpad security policy."""

__metaclass__ = type

__all__ = [
    'AnonymousAuthorization',
    'AuthorizationBase',
    ]

from zope.component import getAdapter
from zope.interface import implements
from zope.security.permission import (
    checkPermission as check_permission_is_registered,
    )

from canonical.launchpad.interfaces.launchpad import IPersonRoles
from lp.app.interfaces.security import IAuthorization
from lp.registry.interfaces.person import IPerson


class AuthorizationBase:
    implements(IAuthorization)
    permission = None
    usedfor = None

    def __init__(self, obj):
        self.obj = obj

    def checkUnauthenticated(self):
        """See `IAuthorization.checkUnauthenticated`.

        :return: True or False.
        """
        return False

    def checkAuthenticated(self, user):
        """Return True if the given person has the given permission.

        This method is implemented by security adapters that have not
        been updated to work in terms of IAccount.

        :return: True or False.
        """
        return False

    def forwardCheckAuthenticated(self, user,
                                  obj=None, permission=None):
        """Forward request to another security adapter.

        Find a matching adapter and call checkAuthenticated on it. Intended
        to be used in checkAuthenticated.

        :param user: The IRolesPerson object that was passed in.
        :param obj: The object to check the permission for. If None, use
            the same object as this adapter.
        :param permission: The permission to check. If None, use the same
            permission as this adapter.
        :return: True or False.
        """
        if obj is None:
            obj = self.obj
        if permission is None:
            permission = self.permission
        else:
            # This will raise ValueError if the permission doesn't exist.
            check_permission_is_registered(obj, permission)
        next_adapter = getAdapter(obj, IAuthorization, permission)
        return next_adapter.checkAuthenticated(user)

    def checkAccountAuthenticated(self, account):
        """See `IAuthorization.checkAccountAuthenticated`.

        :return: True or False.
        """
        # For backward compatibility, delegate to one of
        # checkAuthenticated() or checkUnauthenticated().
        person = IPerson(account, None)
        if person is None:
            return self.checkUnauthenticated()
        else:
            return self.checkAuthenticated(IPersonRoles(person))


class AnonymousAuthorization(AuthorizationBase):
    """Allow any authenticated and unauthenticated user access."""
    permission = 'launchpad.View'

    def checkUnauthenticated(self):
        """Any unauthorized user can see this object."""
        return True

    def checkAuthenticated(self, user):
        """Any authorized user can see this object."""
        return True
