# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'check_oauth_signature',
    'get_oauth_authorization',
    'LaunchpadLoginSource',
    'LaunchpadPrincipal',
    'OpenIDPrincipal',
    'PlacelessAuthUtility',
    'SSHADigestEncryptor',
    ]


import binascii
import random
import sha

from contrib.oauth import OAuthRequest

from zope.interface import implements
from zope.component import getUtility
from zope.event import notify

from zope.security.proxy import removeSecurityProxy

from zope.session.interfaces import ISession
from zope.app.security.interfaces import ILoginPassword
from zope.app.security.principalregistry import UnauthenticatedPrincipal

from canonical.config import config
from canonical.launchpad.interfaces.account import IAccountSet
from canonical.launchpad.interfaces.emailaddress import IEmailAddressSet
from canonical.launchpad.interfaces.launchpad import IPasswordEncryptor
from canonical.launchpad.interfaces.oauth import OAUTH_CHALLENGE
from canonical.launchpad.interfaces.person import IPerson, IPersonSet
from canonical.launchpad.webapp.interfaces import (
    AccessLevel, BasicAuthLoggedInEvent, CookieAuthPrincipalIdentifiedEvent,
    ILaunchpadPrincipal, IOpenIDPrincipal, IPlacelessAuthUtility,
    IPlacelessLoginSource)


class PlacelessAuthUtility:
    """An authentication service which holds no state aside from its
    ZCML configuration, implemented as a utility.
    """
    implements(IPlacelessAuthUtility)

    def __init__(self):
        self.nobody = UnauthenticatedPrincipal(
            'Anonymous', 'Anonymous', 'Anonymous User')
        self.nobody.__parent__ = self

    def _authenticateUsingBasicAuth(self, credentials, request):
        login = credentials.getLogin()
        if login is not None:
            login_src = getUtility(IPlacelessLoginSource)
            principal = login_src.getPrincipalByLogin(login)
            if principal is not None:
                person = getUtility(IPersonSet).get(principal.person.id)
                if person.is_valid_person:
                    password = credentials.getPassword()
                    if principal.validate(password):
                        # We send a LoggedInEvent here, when the
                        # cookie auth below sends a PrincipalIdentified,
                        # as the login form is never visited for BasicAuth.
                        # This we treat each request as a separate
                        # login/logout.
                        notify(BasicAuthLoggedInEvent(
                            request, login, principal
                            ))
                        return principal

    def _authenticateUsingCookieAuth(self, request):
        session = ISession(request)
        authdata = session['launchpad.authenticateduser']
        id = authdata.get('accountid')
        id_is_from_person = False
        if id is None:
            # XXX: salgado, 2009-02-17: This is for backwards compatibility,
            # when we used to store the person's ID in the session.
            id = authdata.get('personid')
            if id is None:
                return None
            id_is_from_person = True

        login_src = getUtility(IPlacelessLoginSource)
        principal = login_src.getPrincipal(
            id, id_is_from_person=id_is_from_person)
        person_set = getUtility(IPersonSet)
        # Note, not notifying a LoggedInEvent here as for session-based
        # auth the login occurs when the login form is submitted, not
        # on each request.
        if principal is None:
            # XXX Stuart Bishop 2006-05-26 bug=33427:
            # User is authenticated in session, but principal is not"
            # available in login source. This happens when account has
            # become invalid for some reason, such as being merged.
            return None
        elif (IOpenIDPrincipal.providedBy(principal)
              or person_set.get(principal.person.id).is_valid_person):
            login = authdata['login']
            assert login, 'login is %s!' % repr(login)
            notify(CookieAuthPrincipalIdentifiedEvent(
                principal, request, login))
            return principal
        else:
            return None

    def authenticate(self, request):
        """See IAuthenticationUtility."""
        # To avoid confusion (hopefully), basic auth trumps cookie auth
        # totally, and all the time.  If there is any basic auth at all,
        # then cookie auth won't even be considered.

        # XXX daniels 2004-12-14: allow authentication scheme to be put into
        #     a view; for now, use basic auth by specifying ILoginPassword.
        credentials = ILoginPassword(request, None)
        if credentials is not None and credentials.getLogin() is not None:
            return self._authenticateUsingBasicAuth(credentials, request)
        else:
            # Hack to make us not even think of using a session if there
            # isn't already a cookie in the request, or one waiting to be
            # set in the response.
            cookie_name = config.launchpad_session.cookie
            if (request.cookies.get(cookie_name) is not None or
                request.response.getCookie(cookie_name) is not None):
                return self._authenticateUsingCookieAuth(request)
            else:
                return None

    def unauthenticatedPrincipal(self):
        """See IAuthenticationUtility."""
        return self.nobody

    def unauthorized(self, id, request):
        """See IAuthenticationUtility."""
        a = ILoginPassword(request)
        # TODO maybe configure the realm from zconfigure.
        a.needLogin(realm="launchpad")

    # XXX: salgado, 2009-02-17: The id_is_from_person argument here is for
    # backwards compatibility, when we used to store the person's ID in the
    # session.
    def getPrincipal(self, id, id_is_from_person=False):
        """See IAuthenticationUtility."""
        utility = getUtility(IPlacelessLoginSource)
        return utility.getPrincipal(id, id_is_from_person=id_is_from_person)

    def getPrincipals(self, name):
        """See IAuthenticationUtility."""
        utility = getUtility(IPlacelessLoginSource)
        return utility.getPrincipals(name)

    def getPrincipalByLogin(self, login, want_password=True):
        """See IAuthenticationService."""
        utility = getUtility(IPlacelessLoginSource)
        return utility.getPrincipalByLogin(login, want_password=want_password)


class SSHADigestEncryptor:
    """SSHA is a modification of the SHA digest scheme with a salt
    starting at byte 20 of the base64-encoded string.
    """
    implements(IPasswordEncryptor)

    # Source: http://developer.netscape.com/docs/technote/ldap/pass_sha.html

    saltLength = 20

    def generate_salt(self):
        # Salt can be any length, but not more than about 37 characters
        # because of limitations of the binascii module.
        # All 256 characters are available.
        salt = ''
        for n in range(self.saltLength):
            salt += chr(random.randrange(256))
        return salt

    def encrypt(self, plaintext, salt=None):
        plaintext = str(plaintext)
        if salt is None:
            salt = self.generate_salt()
        v = binascii.b2a_base64(sha.new(plaintext + salt).digest() + salt)
        return v[:-1]

    def validate(self, plaintext, encrypted):
        encrypted = str(encrypted)
        plaintext = str(plaintext)
        try:
            ref = binascii.a2b_base64(encrypted)
        except binascii.Error:
            # Not valid base64.
            return False
        salt = ref[20:]
        v = binascii.b2a_base64(
            sha.new(plaintext + salt).digest() + salt)[:-1]
        pw1 = (v or '').strip()
        pw2 = (encrypted or '').strip()
        return pw1 == pw2


class LaunchpadLoginSource:
    """A login source that uses the launchpad SQL database to look up
    principal information.
    """
    implements(IPlacelessLoginSource)

    # XXX: salgado, 2009-02-17: The id_is_from_person argument here is for
    # backwards compatibility, when we used to store the person's ID in the
    # session.
    def getPrincipal(self, id, id_is_from_person=False,
                     access_level=AccessLevel.WRITE_PRIVATE, scope=None):
        """Return an `ILaunchpadPrincipal` for the account with the given id.

        Return None if there is no account with the given id.

        The `access_level` can be used for further restricting the capability
        of the principal.  By default, no further restriction is added.

        Similarly, when a `scope` is given, the principal's capabilities will
        apply only to things within that scope.  For everything else that is
        not private, the principal will have only read access.

        Note that we currently need to be able to retrieve principals for
        invalid People, as the login machinery needs the principal to
        validate the password against so it may then email a validation
        request to the user and inform them it has done so.
        """
        person = None
        if id_is_from_person:
            person = getUtility(IPersonSet).get(id)
        else:
            account = getUtility(IAccountSet).get(id)
            if account is not None:
                person = IPerson(account, None)
            else:
                return None

        # XXX: Dear reviewer. I can't use "person is None" here because zope
        # wraps the return of IPerson(account) above into a security proxy.
        if person:
            return self._getLaunchpadPrincipal(person, access_level, scope)
        else:
            # Our account has no person, so we return an OpenIDPrincipal.
            return self._getOpenIDPrincipal(account, access_level, scope)

    def getPrincipals(self, name):
        raise NotImplementedError

    def getPrincipalByLogin(self, login,
                            access_level=AccessLevel.WRITE_PRIVATE,
                            scope=None, want_password=True):
        """Return a principal based on the person with the email address
        signified by "login".

        :param want_password: If want_password is False, the pricipal
        will have None for a password. Use this when trying to retrieve a
        principal in contexts where we don't need the password and the
        database connection does not have access to the Account or
        AccountPassword tables.

        :return: None if there is no person with the given email address.

        The `access_level` can be used for further restricting the capability
        of the principal.  By default, no further restriction is added.

        Similarly, when a `scope` is given, the principal's capabilities will
        apply only to things within that scope.  For everything else that is
        not private, the principal will have only read access.


        Note that we currently need to be able to retrieve principals for
        invalid People, as the login machinery needs the principal to
        validate the password against so it may then email a validation
        request to the user and inform them it has done so.
        """
        email = getUtility(IEmailAddressSet).getByEmail(login)
        if email is None:
            return None
        elif email.person is not None:
            return self._getLaunchpadPrincipal(
                email.person, access_level, scope, want_password)
        else:
            assert email.account is not None
            return self._getOpenIDPrincipal(
                email.account, access_level, scope, want_password)

    def _getOpenIDPrincipal(self, account, access_level, scope,
                            want_password=True):
        """Return an OpenIDPrincipal for the given account.

        The OpenIDPrincipal will also have the given access level and scope.

        If want_password is True, the principal's password will be set to the
        account's password.  Otherwise it's set to None.
        """
        naked_account = removeSecurityProxy(account)
        if want_password:
            password = naked_account.password
        else:
            password = None
        principal = OpenIDPrincipal(
            naked_account.id, naked_account.displayname,
            naked_account.displayname, account, password,
            access_level=access_level, scope=scope)
        principal.__parent__ = self
        return principal

    def _getLaunchpadPrincipal(self, person, access_level, scope,
                               want_password=True):
        """Return a LaunchpadPrincipal for the given person.

        The LaunchpadPrincipal will also have the given access level and
        scope.

        If want_password is True, the principal's password will be set to the
        person's password.  Otherwise it's set to None.
        """
        naked_person = removeSecurityProxy(person)
        if want_password:
            password = naked_person.password
        else:
            password = None
        principal = LaunchpadPrincipal(
            naked_person.account.id, naked_person.displayname,
            naked_person.displayname, person, password,
            access_level=access_level, scope=scope)
        principal.__parent__ = self
        return principal


# Fake a containment hierarchy because Zope3 is on crack.
authService = PlacelessAuthUtility()
loginSource = LaunchpadLoginSource()
loginSource.__parent__ = authService


class BaseLaunchpadPrincipal:
    """Base class for Launchpad-specific IPrincipal classes.

    It defines an access level and a scope of access for the principal, as
    well as other attributes of IPrincipal.
    """

    def __init__(self, id, title, description, pwd=None,
                 access_level=AccessLevel.WRITE_PRIVATE, scope=None):
        self.id = id
        self.title = title
        self.description = description
        self.access_level = access_level
        self.scope = scope
        self.__pwd = pwd

    def getLogin(self):
        return self.title

    def validate(self, pw):
        encryptor = getUtility(IPasswordEncryptor)
        pw1 = (pw or '').strip()
        pw2 = (self.__pwd or '').strip()
        return encryptor.validate(pw1, pw2)


class LaunchpadPrincipal(BaseLaunchpadPrincipal):
    """See `ILaunchpadPrincipal`"""

    implements(ILaunchpadPrincipal)

    def __init__(self, id, title, description, person, pwd=None,
                 access_level=AccessLevel.WRITE_PRIVATE, scope=None):
        super(LaunchpadPrincipal, self).__init__(
            id, title, description, pwd=pwd, access_level=access_level,
            scope=scope)
        self.person = person


class OpenIDPrincipal(BaseLaunchpadPrincipal):
    """See `IOpenIDPrincipal`"""

    implements(IOpenIDPrincipal)

    def __init__(self, id, title, description, account, pwd=None,
                 access_level=AccessLevel.WRITE_PRIVATE, scope=None):
        super(OpenIDPrincipal, self).__init__(
            id, title, description, pwd=pwd, access_level=access_level,
            scope=scope)
        self.account = account


def get_oauth_authorization(request):
    """Retrieve OAuth authorization information from a request.

    The authorization information may be in the Authorization header,
    or it might be in the query string or entity-body.

    :return: a dictionary of authorization information.
    """
    header = request._auth
    if header is not None and header.startswith("OAuth "):
        return OAuthRequest._split_header(header)
    else:
        return request.form


def check_oauth_signature(request, consumer, token):
    """Check that the given OAuth request is correctly signed.

    If the signature is incorrect or its method is not supported, set the
    appropriate status in the request's response and return False.
    """
    authorization = get_oauth_authorization(request)

    if authorization.get('oauth_signature_method') != 'PLAINTEXT':
        # XXX: 2008-03-04, salgado: Only the PLAINTEXT method is supported
        # now. Others will be implemented later.
        request.response.setStatus(400)
        return False

    if token is not None:
        token_secret = token.secret
    else:
        token_secret = ''
    expected_signature = "&".join([consumer.secret, token_secret])
    if expected_signature != authorization.get('oauth_signature'):
        request.unauthorized(OAUTH_CHALLENGE)
        return False

    return True
