# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'OAuthAccessToken',
    'OAuthConsumer',
    'OAuthConsumerSet',
    'OAuthNonce',
    'OAuthRequestToken',
    'OAuthRequestTokenSet']

import random
import pytz
import time
from datetime import datetime, timedelta

from zope.component import getUtility
from zope.interface import implements

from sqlobject import BoolCol, ForeignKey, StringCol

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase

from canonical.launchpad.interfaces.distribution import IDistribution
from canonical.launchpad.interfaces.product import IProduct
from canonical.launchpad.interfaces.project import IProject
from canonical.launchpad.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage)
from canonical.launchpad.interfaces import (
    IOAuthAccessToken, IOAuthConsumer, IOAuthConsumerSet, IOAuthNonce,
    IOAuthRequestToken, IOAuthRequestTokenSet, NonceAlreadyUsed)
from canonical.launchpad.webapp.interfaces import (
    AccessLevel, OAuthPermission, IStoreSelector, MAIN_STORE, MASTER_FLAVOR)


# How many hours should a request token be valid for?
REQUEST_TOKEN_VALIDITY = 12
# The OAuth Core 1.0 spec says that a nonce shall be "unique for all requests
# with that timestamp", but this is likely to cause problems if the
# client does request pipelining, so we use a time window (relative to
# the timestamp of the existing OAuthNonce) to check if the nonce can be used.
# As suggested by Robert, we use a window which is at least twice the size of
# our hard time out. This is a safe bet since no requests should take more 
# than one hard time out.
NONCE_TIME_WINDOW = 60 # seconds


class OAuthBase(SQLBase):
    """Base class for all OAuth database classes."""

    @staticmethod
    def _get_store():
        """See `SQLBase`.

        We want all OAuth classes to be retrieved from the master flavour.  If
        they are retrieved from the slave, there will be problems in the
        authorization exchange, since it will be done across applications that
        won't share the session cookies.
        """
        return getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)


class OAuthConsumer(OAuthBase):
    """See `IOAuthConsumer`."""
    implements(IOAuthConsumer)

    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    disabled = BoolCol(notNull=True, default=False)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    def newRequestToken(self):
        """See `IOAuthConsumer`."""
        key, secret = create_token_key_and_secret(table=OAuthRequestToken)
        date_expires = (datetime.now(pytz.timezone('UTC'))
                        + timedelta(hours=REQUEST_TOKEN_VALIDITY))
        return OAuthRequestToken(
            consumer=self, key=key, secret=secret, date_expires=date_expires)

    def getAccessToken(self, key):
        """See `IOAuthConsumer`."""
        return OAuthAccessToken.selectOneBy(key=key, consumer=self)

    def getRequestToken(self, key):
        """See `IOAuthConsumer`."""
        return OAuthRequestToken.selectOneBy(key=key, consumer=self)


class OAuthConsumerSet:
    """See `IOAuthConsumerSet`."""
    implements(IOAuthConsumerSet)

    def new(self, key, secret=''):
        """See `IOAuthConsumerSet`."""
        assert self.getByKey(key) is None, (
            "The key '%s' is already in use by another consumer." % key)
        return OAuthConsumer(key=key, secret=secret)

    def getByKey(self, key):
        """See `IOAuthConsumerSet`."""
        return OAuthConsumer.selectOneBy(key=key)


class OAuthAccessToken(OAuthBase):
    """See `IOAuthAccessToken`."""
    implements(IOAuthAccessToken)

    consumer = ForeignKey(
        dbName='consumer', foreignKey='OAuthConsumer', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person', notNull=False, default=None)
    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    date_expires = UtcDateTimeCol(notNull=False, default=None)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    permission = EnumCol(enum=AccessLevel, notNull=True)

    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    project = ForeignKey(
        dbName='project', foreignKey='Project', notNull=False, default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution',
        notNull=False, default=None)

    @property
    def context(self):
        """See `IOAuthToken`."""
        if self.product:
            return self.product
        elif self.project:
            return self.project
        elif self.distribution:
            if self.sourcepackagename:
                return self.distribution.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distribution
        else:
            return None

    def ensureNonce(self, nonce, timestamp):
        """See `IOAuthAccessToken`."""
        timestamp = float(timestamp)
        oauth_nonce = OAuthNonce.selectOneBy(access_token=self, nonce=nonce)
        if oauth_nonce is not None:
            # timetuple() returns the datetime as local time, so we need to
            # subtract time.altzone from the result of time.mktime().
            stored_timestamp = time.mktime(
                oauth_nonce.request_timestamp.timetuple()) - time.altzone
            if abs(stored_timestamp - timestamp) > NONCE_TIME_WINDOW:
                raise NonceAlreadyUsed('This nonce has been used already.')
            return oauth_nonce
        else:
            date = datetime.fromtimestamp(timestamp, pytz.timezone('UTC'))
            return OAuthNonce(
                access_token=self, nonce=nonce, request_timestamp=date)


class OAuthRequestToken(OAuthBase):
    """See `IOAuthRequestToken`."""
    implements(IOAuthRequestToken)

    consumer = ForeignKey(
        dbName='consumer', foreignKey='OAuthConsumer', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person', notNull=False, default=None)
    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    date_expires = UtcDateTimeCol(notNull=False, default=None)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    permission = EnumCol(enum=OAuthPermission, notNull=False, default=None)
    date_reviewed = UtcDateTimeCol(default=None, notNull=False)

    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    project = ForeignKey(
        dbName='project', foreignKey='Project', notNull=False, default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution',
        notNull=False, default=None)

    @property
    def context(self):
        """See `IOAuthToken`."""
        if self.product:
            return self.product
        elif self.project:
            return self.project
        elif self.distribution:
            if self.sourcepackagename:
                return self.distribution.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distribution
        else:
            return None

    def review(self, user, permission, context=None):
        """See `IOAuthRequestToken`."""
        assert not self.is_reviewed, (
            "Request tokens can be reviewed only once.")
        self.date_reviewed = datetime.now(pytz.timezone('UTC'))
        self.person = user
        self.permission = permission
        if IProduct.providedBy(context):
            self.product = context
        elif IProject.providedBy(context):
            self.project = context
        elif IDistribution.providedBy(context):
            self.distribution = context
        elif IDistributionSourcePackage.providedBy(context):
            self.sourcepackagename = context.sourcepackagename
            self.distribution = context.distribution
        else:
            assert context is None, ("Unknown context type: %r." % context)

    def createAccessToken(self):
        """See `IOAuthRequestToken`."""
        assert self.is_reviewed, (
            'Cannot create an access token from an unreviewed request token.')
        assert self.permission != OAuthPermission.UNAUTHORIZED, (
            'The user did not grant access to this consumer.')
        key, secret = create_token_key_and_secret(table=OAuthAccessToken)
        access_level = AccessLevel.items[self.permission.name]
        access_token = OAuthAccessToken(
            consumer=self.consumer, person=self.person, key=key,
            secret=secret, permission=access_level, product=self.product,
            project=self.project, distribution=self.distribution,
            sourcepackagename=self.sourcepackagename)
        self.destroySelf()
        return access_token

    @property
    def is_reviewed(self):
        """See `IOAuthRequestToken`."""
        return self.date_reviewed is not None


class OAuthRequestTokenSet:
    """See `IOAuthRequestTokenSet`."""
    implements(IOAuthRequestTokenSet)

    def getByKey(self, key):
        """See `IOAuthRequestTokenSet`."""
        return OAuthRequestToken.selectOneBy(key=key)


class OAuthNonce(OAuthBase):
    """See `IOAuthNonce`."""
    implements(IOAuthNonce)

    access_token = ForeignKey(
        dbName='access_token', foreignKey='OAuthAccessToken', notNull=True)
    request_timestamp = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    nonce = StringCol(notNull=True)


def create_token_key_and_secret(table):
    """Create a key and secret for an OAuth token.

    :table: The table in which the key/secret are going to be used. Must be
        one of OAuthAccessToken or OAuthRequestToken.

    The key will have a length of 20 and we'll make sure it's not yet in the
    given table.  The secret will have a length of 80.
    """
    characters = '0123456789bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ'
    key_length = 20
    key = ''.join(
        random.choice(characters) for count in range(key_length))
    while table.selectOneBy(key=key) is not None:
        key = ''.join(
            random.choice(characters) for count in range(key_length))
    secret_length = 80
    secret = ''.join(
        random.choice(characters) for count in range(secret_length))
    return key, secret
