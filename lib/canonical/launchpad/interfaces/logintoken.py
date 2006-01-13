# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Login token interfaces."""

__metaclass__ = type

__all__ = [
    'ILoginToken',
    'ILoginTokenSet',
    ]

from zope.schema import Datetime, Int, Text
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory

_ = MessageIDFactory('launchpad')


class ILoginToken(Interface):
    """The object that stores one time tokens used for validating email
    addresses and other tasks that require verifying if an email address is
    valid such as password recovery, account merging and registration of new
    accounts. All LoginTokens must be deleted once they are "consumed"."""
    id = Int(
        title=_('ID'), required=True, readonly=True,
        )
    email = Text(
        title=_('The email address that this request was sent to.'),
        required=True,
        )
    requester = Int(
        title=_('The Person that made this request.'), required=True,
        )
    requesteremail = Text(
        title=_('The email address that was used to login when making this '
                'request.'),
        required=False,
        )
    redirection_url = Text(
        title=_('The URL to where we should redirect the user after processing '
                'his request'),
        required=False,
        )
    created = Datetime(
        title=_('The timestamp that this request was made.'), required=True,
        )
    tokentype = Text(
        title=_('The type of request, as per dbschema.TokenType.'),
                required=True,
        )
    token = Text(
        title=_('The token (not the URL) emailed used to uniquely identify '
                'this request.'),
        required=True,
        )
    fingerprint = Text(
        title=_('OpenPGP key fingerprint used to retrive key information when necessary.'),
        required=False,
        )

    # used for launchpad page layout
    title = Attribute('Title')

    # Quick fix for Bug #2481
    password = Attribute('Password')

    def destroySelf():
        """Remove this LoginToken from the database.

        We need this because once the token is used (either when registering a
        new user, validating an email address or reseting a password), we have
        to delete it so nobody can use that token again.
        """

    def sendEmailValidationRequest(appurl):
        """Send an email message with a magic URL to validate self.email."""

    def sendGPGValidationRequest(appurl, key):
        """Send an email message with a magic URL to confirm the OpenPGP key.
        If fingerprint is set, send the message encrypted.
        """

    def sendPasswordResetEmail(self, appurl):
        """Send an email message to the requester with a magic URL that allows 
        him to reset his password."""

    def sendNewUserEmail(self, appurl):
        """Send an email message to the requester with a magic URL that allows 
        him to finish the Launchpad registration process."""


class ILoginTokenSet(Interface):
    """The set of LoginTokens."""

    title = Attribute('Title')

    def get(id, default=None):
        """Return the LoginToken object with the given id.

        Return the default value if there's no such LoginToken.
        """

    def searchByEmailAndRequester(email, requester):
        """Return all LoginTokens for the given email and requester."""

    def deleteByEmailAndRequester(email, requester):
        """Delete all LoginToken entries with the given email and requester."""

    def searchByFingerprintAndRequester(fingerprint, requester):
        """Return all LoginTokens for the given fingerprint and requester."""

    def deleteByFingerprintAndRequester(fingerprint, requester):
        """Delete all LoginToken entries with the given fingerprint
        and requester.
        """

    def getPendingGPGKeys(self, requesterid=None):
        """Return tokens for OpenPGP keys pending validation, optionally for
        a single user.
        """

    def new(requester, requesteremail, email, tokentype, fingerprint=None,
            redirection_url=None):
        """Create a new LoginToken object. Parameters must be:
        requester: a Person object or None (in case of a new account)

        requesteremail: the email address used to login on the system. Can
                        also be None in case of a new account

        email: the email address that this request will be sent to.
        It should be previosly validated by valid_email() 

        tokentype: the type of the request, according to
        dbschema.LoginTokenType
        
        fingerprint: The OpenPGP key fingerprint used to retrieve key
        information from the key server if necessary. This can be None if
        not required to process the 'request' in question.  
        """

    def __getitem__(id):
        """Returns the LoginToken with the given id.

        Raises KeyError if there is no such LoginToken.
        """

    def get(id, default=None):
        """Returns the LoginToken with the given id.

        Returns the default value if there is no such LoginToken.
        """

