# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import warnings

from storm.zope.interfaces import IZStorm

from zope.interface import classProvides
from zope.component import getUtility, queryAdapter
from zope.component.interfaces import IView

from zope.security.interfaces import ISecurityPolicy
from zope.security.checker import CheckerPublic
from zope.security.proxy import removeSecurityProxy
from zope.security.simplepolicies import ParanoidSecurityPolicy
from zope.security.management import (
    system_user, checkPermission as zcheckPermission)
from zope.app.security.permission import (
    checkPermission as check_permission_is_registered)
from zope.app.security.principalregistry import UnauthenticatedPrincipal

from canonical.lazr.interfaces import IObjectPrivacy

from canonical.database.sqlbase import block_implicit_flushes
from canonical.launchpad.webapp.interfaces import (
    AccessLevel, ILaunchpadPrincipal, IAuthorization)

steveIsFixingThis = False


class LaunchpadSecurityPolicy(ParanoidSecurityPolicy):
    classProvides(ISecurityPolicy)

    def _checkRequiredAccessLevel(self, principal, permission, object):
        """Check that the principal has the level of access required.

        Each permission specifies the level of access it requires (read or
        write) and all LaunchpadPrincipals have an access_level attribute. If
        the principal's access_level is not sufficient for that permission,
        returns False.
        """
        # This doesn't work as a global import and it doesn't seem to be the
        # consequence of circular dependencies:
        # https://pastebin.canonical.com/3921/
        from canonical.launchpad.webapp.metazcml import ILaunchpadPermission
        lp_permission = getUtility(ILaunchpadPermission, permission)
        if lp_permission.access_level == "write":
            required_access_level = [
                AccessLevel.WRITE_PUBLIC, AccessLevel.WRITE_PRIVATE]
            if principal.access_level not in required_access_level:
                return False
        elif lp_permission.access_level == "read":
            # All principals have access to read data so there's nothing
            # to do here.
            pass
        else:
            raise AssertionError(
                "Unknown access level: %s" % lp_permission.access_level)
        return True

    def _checkPrivacy(self, principal, object):
        """If the object is private, check that the principal can access it.

        If the object is private and the principal's access level doesn't give
        access to private objects, return False.  Return True otherwise.
        """
        private_access_levels = [
            AccessLevel.READ_PRIVATE, AccessLevel.WRITE_PRIVATE]
        if principal.access_level in private_access_levels:
            # The user has access to private objects. Return early,
            # before checking whether the object is private, since
            # checking it might be expensive.
            return True
        return not IObjectPrivacy(object).is_private

    @block_implicit_flushes
    def checkPermission(self, permission, object):
        """Check the permission, object, user against the launchpad
        authorization policy.

        If the object is a view, then consider the object to be the view's
        context.

        Workflow:
        - If the principal is not None and its access level is not what is
          required by the permission, deny.
        - If the object to authorize is private and the principal has no
          access to private objects, deny.
        - If we have zope.Public, allow.  (We shouldn't ever get this, though.)
        - If we have launchpad.AnyPerson and the principal is an
          ILaunchpadPrincipal then allow.
        - If the object has an IAuthorization named adapter, named
          after the permission, use that to check the permission.
        - Otherwise, deny.
        """
        # If we have a view, get its context and use that to get an
        # authorization adapter.
        if IView.providedBy(object):
            objecttoauthorize = object.context
        else:
            objecttoauthorize = object
        if objecttoauthorize is None:
            # We will not be able to lookup an adapter for this, so we can
            # return False already.
            return False
        # Remove security proxies from object to authorize.
        objecttoauthorize = removeSecurityProxy(objecttoauthorize)

        principals = [participation.principal
                      for participation in self.participations
                          if participation.principal is not system_user]
        if len(principals) == 0:
            principal = None
        elif len(principals) > 1:
            raise RuntimeError("More than one principal participating.")
        else:
            principal = principals[0]

        if (principal is not None and
            not isinstance(principal, UnauthenticatedPrincipal)):
            if not self._checkRequiredAccessLevel(
                principal, permission, objecttoauthorize):
                return False
            if not self._checkPrivacy(principal, objecttoauthorize):
                return False

        # XXX kiko 2007-02-07:
        # webapp shouldn't be depending on launchpad interfaces..
        from canonical.launchpad.interfaces import IPerson

        # This check shouldn't be needed, strictly speaking.
        # However, it is here as a "belt and braces".

        # XXX Steve Alexander 2005-01-12: 
        # This warning should apply to the policy in zope3 also.
        if permission == 'zope.Public':
            if steveIsFixingThis:
                warnings.warn(
                    'zope.Public being used raw on object %r' % object)
            return True
        if permission is CheckerPublic:
            return True
        if (permission == 'launchpad.AnyPerson' and
            ILaunchpadPrincipal.providedBy(principal)):
            return True
        else:
            # Look for an IAuthorization adapter.  If there is no
            # IAuthorization adapter then the permission is not granted.
            #
            # The IAuthorization is a named adapter from objecttoauthorize,
            # providing IAuthorization, named after the permission.
            authorization = queryAdapter(
                objecttoauthorize, IAuthorization, permission)
            if authorization is None:
                return False
            else:
                user = IPerson(principal, None)
                if user is None:
                    result = authorization.checkUnauthenticated()
                else:
                    result = authorization.checkAuthenticated(user)
                if type(result) is not bool:
                    warnings.warn(
                        'authorization returning non-bool value: %r' %
                        authorization)
                return bool(result)


def check_permission(permission_name, context):
    """Like zope.security.management.checkPermission, but also ensures that
    permission_name is real permission.

    Raises ValueError if the permission doesn't exist.
    """
    # This will raise ValueError if the permission doesn't exist.
    check_permission_is_registered(context, permission_name)

    # Now call Zope's checkPermission.
    return zcheckPermission(permission_name, context)
