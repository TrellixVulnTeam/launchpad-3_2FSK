# Copyright 2008-2009 Canonical Ltd.  All rights reserved.

"""OpenID adapters and helpers."""

__metaclass__ = type

__all__ = [
    'CurrentOpenIDEndPoint',
    'OpenIDPersistentIdentity',
    ]

from zope.component import adapter, adapts
from zope.interface import implementer, implements
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.account import IAccount
from canonical.launchpad.webapp.vhosts import allvhosts
from lp.services.openid.interfaces.openid import IOpenIDPersistentIdentity
from lp.registry.interfaces.person import IPerson


class CurrentOpenIDEndPoint:
    """A utility for working with multiple OpenID End Points."""

    @classmethod
    def getServiceURL(cls):
        """The OpenID server URL (/+openid) for the current request."""
        return allvhosts.configs['openid'].rooturl + '+openid'

    @classmethod
    def supportsURL(cls, identity_url):
        """Does the OpenID current vhost support the identity_url?"""
        root_url = allvhosts.configs['openid'].rooturl
        return identity_url.startswith(root_url + '+id')


class OpenIDPersistentIdentity:
    """A persistent OpenID identifier for a user."""

    adapts(IAccount)
    implements(IOpenIDPersistentIdentity)

    def __init__(self, account):
        self.account = account

    @property
    def openid_identity_url(self):
        """See `IOpenIDPersistentIdentity`."""
        identity_root_url = allvhosts.configs['openid'].rooturl
        return identity_root_url + self.openid_identifier.encode('ascii')

    @property
    def openid_identifier(self):
        """See `IOpenIDPersistentIdentity`."""
        # The account is very restricted.
        token = removeSecurityProxy(self.account).openid_identifier
        if token is None:
            return None
        return '+id/' + token


@adapter(IPerson)
@implementer(IOpenIDPersistentIdentity)
def person_to_openidpersistentidentity(person):
    """Adapts an `IPerson` into an `IOpenIDPersistentIdentity`."""
    return OpenIDPersistentIdentity(person.account)
