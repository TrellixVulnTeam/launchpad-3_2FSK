# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Implementation classes for Account and associates."""

__metaclass__ = type
__all__ = ['Account', 'AccountPassword', 'AccountSet']

from zope.component import getUtility
from zope.interface import implements

from sqlobject import ForeignKey, StringCol

from canonical.database.constants import UTC_NOW, DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.interfaces.account import (
        AccountCreationRationale, AccountStatus,
        IAccount, IAccountSet)
from canonical.launchpad.interfaces.launchpad import IPasswordEncryptor
from canonical.launchpad.webapp.vhosts import allvhosts


class Account(SQLBase):
    """An Account."""

    implements(IAccount)

    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    displayname = StringCol(dbName='displayname', notNull=True)

    creation_rationale = EnumCol(
            dbName='creation_rationale', schema=AccountCreationRationale,
            notNull=True)
    status = EnumCol(
            enum=AccountStatus, default=AccountStatus.NOACCOUNT,
            notNull=True)
    date_status_set = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    status_comment = StringCol(dbName='status_comment', default=None)

    openid_identifier = StringCol(
            dbName='openid_identifier', notNull=True, default=DEFAULT)


    # The password is actually stored in a seperate table for security
    # reasons, so use a property to hide this implementation detail.
    def _get_password(self):
        password = AccountPassword.selectOneBy(account=self)
        if password is None:
            return None
        else:
            return password.password

    def _set_password(self, value):
        password = AccountPassword.selectOneBy(account=self)

        if value is not None and password is None:
            # There is currently no AccountPassword record and we need one.
            AccountPassword(account=self, password=value)
        elif value is None and password is not None:
            # There is an AccountPassword record that needs removing.
            AccountPassword.delete(password.id)
        elif value is not None:
            # There is an AccountPassword record that needs updating.
            password.password = value
        elif value is None and password is None:
            # Nothing to do
            pass
        else:
            assert False, "This should not be reachable."

    password = property(_get_password, _set_password)

    @property
    def openid_identity_url(self):
        """see `IAccount`."""
        identity_url_prefix = (allvhosts.configs['openid'].rooturl + '+id/')
        return identity_url_prefix + self.openid_identifier.encode('ascii')


class AccountSet:
    implements(IAccountSet)

    def new(self, rationale, displayname,
            password=None, password_is_encrypted=False):
        """See `IAccountSet`."""

        account = Account(
                displayname=displayname, creation_rationale=rationale)

        # Create the password record
        if password is not None:
            if not password_is_encrypted:
                password = getUtility(IPasswordEncryptor).encrypt(password)
            AccountPassword(account=account, password=password)

        return account

    def getByEmail(self, email):
        """See `IAccountSet`."""
        return Account.selectOne('''
            EmailAddress.account = Account.id
            AND lower(EmailAddress.email) = lower(trim(%s))
            ''' % sqlvalues(email),
            clauseTables=['EmailAddress'])


class AccountPassword(SQLBase):
    """SQLObject wrapper to the AccountPassword table.

    Note that this class is not exported, as the existence of the
    AccountPassword table only needs to be known by this module.
    """
    account = ForeignKey(
            dbName='account', foreignKey='Account', alternateID=True)
    password = StringCol(dbName='password', notNull=True)

