# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['LoginToken', 'LoginTokenSet']

import random

from zope.interface import implements
from zope.component import getUtility

from sqlobject import ForeignKey, StringCol, SQLObjectNotFound, AND

from canonical.config import config
from canonical.database.sqlbase import SQLBase
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.helpers import get_email_template
from canonical.launchpad.mail import simple_sendmail, format_address
from canonical.launchpad.interfaces import (
    ILoginToken, ILoginTokenSet, IGPGHandler, NotFoundError
    )
from canonical.lp.dbschema import LoginTokenType, EnumCol
from canonical.launchpad.validators.email import valid_email


class LoginToken(SQLBase):
    implements(ILoginToken)
    _table = 'LoginToken'

    redirection_url = StringCol(default=None)
    requester = ForeignKey(dbName='requester', foreignKey='Person')
    requesteremail = StringCol(dbName='requesteremail', notNull=False,
                               default=None)
    email = StringCol(dbName='email', notNull=True)
    token = StringCol(dbName='token', unique=True)
    tokentype = EnumCol(dbName='tokentype', notNull=True,
                        schema=LoginTokenType)
    created = UtcDateTimeCol(dbName='created', notNull=True)
    fingerprint = StringCol(dbName='fingerprint', notNull=False,
                            default=None)
    password = '' # Quick fix for Bug #2481

    title = 'Launchpad Email Verification'

    def sendEmailValidationRequest(self, appurl):
        """See ILoginToken."""
        template = get_email_template('validate-email.txt')
        fromaddress = format_address(
            "Launchpad Email Validator", config.noreply_from_address)

        replacements = {'longstring': self.token,
                        'requester': self.requester.browsername,
                        'requesteremail': self.requesteremail,
                        'toaddress': self.email,
                        'appurl': appurl}
        message = template % replacements

        subject = "Launchpad: Validate your email address"
        simple_sendmail(fromaddress, str(self.email), subject, message)

    def sendGPGValidationRequest(self, appurl, key):
        """See ILoginToken."""
        formatted_uids = ''
        for email in key.emails:
            formatted_uids += '\t%s\n' % email

        assert self.tokentype in (LoginTokenType.VALIDATEGPG,
                                  LoginTokenType.VALIDATESIGNONLYGPG)

        template = get_email_template('validate-gpg.txt')
        fromaddress = format_address("Launchpad OpenPGP Key Confirmation",
                                     config.noreply_from_address)
        replacements = {'longstring': self.token,
                        'requester': self.requester.browsername,
                        'requesteremail': self.requesteremail,
                        'displayname': key.displayname, 
                        'fingerprint': key.fingerprint,
                        'uids': formatted_uids,
                        'appurl': appurl}
        message = template % replacements

        # encrypt message if requested
        if key.can_encrypt:
            gpghandler = getUtility(IGPGHandler)
            message = gpghandler.encryptContent(message.encode('utf-8'),
                                                key.fingerprint)

        subject = "Launchpad: Confirm your OpenPGP Key"
        simple_sendmail(fromaddress, str(self.email), subject, message)

    def sendPasswordResetEmail(self, appurl):
        """See ILoginToken."""
        template = get_email_template('forgottenpassword.txt')
        fromaddress = format_address("Launchpad", config.noreply_from_address)
        replacements = {'longstring': self.token,
                        'toaddress': self.email, 
                        'appurl': appurl}
        message = template % replacements

        subject = "Launchpad: Forgotten Password"
        simple_sendmail(fromaddress, str(self.email), subject, message)

    def sendNewUserEmail(self, appurl):
        """See ILoginToken."""
        template = get_email_template('newuser-email.txt')
        replacements = {'longstring': self.token, 'appurl': appurl}
        message = template % replacements

        fromaddress = format_address("Launchpad", config.noreply_from_address)
        subject = "Finish your Launchpad registration"
        simple_sendmail(fromaddress, str(self.email), subject, message)


class LoginTokenSet:
    implements(ILoginTokenSet)

    def __init__(self):
        self.title = 'Launchpad e-mail address confirmation'

    def get(self, id, default=None):
        """See ILoginTokenSet."""
        try:
            return LoginToken.get(id)
        except SQLObjectNotFound:
            return default

    def searchByEmailAndRequester(self, email, requester):
        """See ILoginTokenSet."""
        requester_id = None
        if requester is not None:
            requester_id = requester.id
        return LoginToken.select(AND(LoginToken.q.email==email,
                                     LoginToken.q.requesterID==requester_id))

    def deleteByEmailAndRequester(self, email, requester):
        """See ILoginTokenSet."""
        for token in self.searchByEmailAndRequester(email, requester):
            token.destroySelf()

    def searchByFingerprintAndRequester(self, fingerprint, requester):
        """See ILoginTokenSet."""
        return LoginToken.select(AND(LoginToken.q.fingerprint==fingerprint,
                                     LoginToken.q.requesterID==requester.id))

    def getPendingGPGKeys(self, requesterid=None):
        """See ILoginTokenSet."""
        query = 'tokentype=%s ' % LoginTokenType.VALIDATEGPG.value

        if requesterid:
            query += 'AND requester=%s' % requesterid

        return LoginToken.select(query)

    def deleteByFingerprintAndRequester(self, fingerprint, requester):
        for token in self.searchByFingerprintAndRequester(fingerprint,
                                                          requester):
            token.destroySelf()

    def new(self, requester, requesteremail, email, tokentype,
            fingerprint=None, redirection_url=None):
        """See ILoginTokenSet."""
        assert valid_email(email)
        if tokentype not in LoginTokenType.items:
            # XXX: Aha! According to our policy, we shouldn't raise ValueError.
            # -- Guilherme Salgado, 2005-12-09
            raise ValueError(
                "tokentype is not an item of LoginTokenType: %s" % tokentype)

        characters = '0123456789bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ'
        length = 20
        token = ''.join([random.choice(characters) for count in range(length)])
        reqid = getattr(requester, 'id', None)
        return LoginToken(requesterID=reqid, requesteremail=requesteremail,
                          email=email, token=token, tokentype=tokentype,
                          created=UTC_NOW, fingerprint=fingerprint,
                          redirection_url=redirection_url)

    def __getitem__(self, tokentext):
        """See ILoginTokenSet."""
        token = LoginToken.selectOneBy(token=tokentext)
        if token is None:
            raise NotFoundError(tokentext)
        return token
