# Copyright 2008 Canonical Ltd.  All rights reserved.

"""A class for the top-level link to the authenticated user's account."""

__metaclass__ = type
__all__ = [
    'IMeLink',
    'MeLink',
    ]

from zope.component import getUtility
from zope.interface import implements

from canonical.launchpad.webapp.interfaces import ICanonicalUrlData
from canonical.launchpad.interfaces import IPerson, IPersonSet

from canonical.lazr.interfaces.rest import (
    IJSONRequestCache, ITopLevelEntryLink)

class IMeLink(ITopLevelEntryLink, ICanonicalUrlData):
    """A marker interface."""


class MeLink:
    """The top-level link to the authenticated user's account."""
    implements(IMeLink)

    link_name = 'me'
    entry_type = IPerson

    @property
    def inside(self):
        """The +me link is beneath /people/."""
        return getUtility(IPersonSet)
    path = '+me'
    rootsite = 'api'


def cache_me_link_when_principal_identified(event):
    """Insert the current user into the JSON request cache.

    This ensures that the Javascript variable LP.client.links['me']
    will be set.
    """
    # XML-RPC requests and other non-browser requests don't have a
    # IJSONRequestCache, and this code shouldn't run from them.
    try:
        cache = IJSONRequestCache(event.request)
    except TypeError:
        cache = None
    if cache is not None:
        cache.links['me'] = IPerson(event.principal)
