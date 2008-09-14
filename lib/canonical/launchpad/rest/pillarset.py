# Copyright 2008 Canonical Ltd.  All rights reserved.

"""A class for the top-level link to the pillar set."""

__metaclass__ = type
__all__ = [
    'IPillarSetLink',
    'PillarSetLink',
    ]

from zope.component import getUtility
from zope.interface import implements

from canonical.launchpad.interfaces import IPillarNameSet
from canonical.launchpad.webapp.interfaces import ICanonicalUrlData

from canonical.lazr.interfaces.rest import (
    IServiceRootResource, ITopLevelEntryLink)


class IPillarSetLink(ITopLevelEntryLink, ICanonicalUrlData):
    """A marker interface."""


class PillarSetLink:
    """The top-level link to the pillar set."""
    implements(IPillarSetLink)

    link_name = 'pillars'
    entry_type = IPillarNameSet

    inside = None
    path = 'pillars'
    rootsite = 'api'

