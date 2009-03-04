# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Database class for table ArchiveAuthToken."""

__metaclass__ = type

__all__ = [
    'ArchiveAuthToken',
    ]

import pytz

from storm.locals import DateTime, Int, Reference, Storm, Unicode

from zope.component import getUtility
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.launchpad.interfaces.archiveauthtoken import (
    IArchiveAuthToken, IArchiveAuthTokenSet)
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)


class ArchiveAuthToken(Storm):
    """See `IArchiveAuthToken`."""
    implements(IArchiveAuthToken)
    __storm_table__ = 'ArchiveAuthToken'

    id = Int(primary=True)

    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

    person_id = Int(name='person', allow_none=False)
    person = Reference(person_id, 'Person.id')

    date_created = DateTime(
        name='date_created', allow_none=False, tzinfo=pytz.UTC)

    date_deactivated = DateTime(
        name='date_deactivated', allow_none=True, tzinfo=pytz.UTC)

    token = Unicode(name='token', allow_none=False)

    def deactivate(self):
        """See `IArchiveAuthTokenSet`."""
        self.date_deactivated = UTC_NOW

    @property
    def archive_url(self):
        """Return a custom archive url for basic authentication."""
        normal_url = self.archive.archive_url
        return normal_url.replace('//', '//%s:%s@' %(
            self.person.name, self.token))

class ArchiveAuthTokenSet:
    """See `IArchiveAuthTokenSet`."""
    implements(IArchiveAuthTokenSet)
    title = "Archive Tokens in Launchpad"

    def get(self, token_id):
        """See `IArchiveAuthTokenSet`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        return store.get(ArchiveAuthToken, token_id)

    def getByToken(self, token):
        """See `IArchiveAuthTokenSet`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        return store.find(
            ArchiveAuthToken,
            ArchiveAuthToken.token == token).one()

    def getActiveTokenForArchiveAndPerson(self, archive, person):
        """See `IArchiveAuthTokenSet`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        return store.find(
            ArchiveAuthToken,
            ArchiveAuthToken.archive == archive,
            ArchiveAuthToken.person == person,
            ArchiveAuthToken.date_deactivated == None).one()
