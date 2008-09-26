# Copyright 2007 Canonical Ltd.  All rights reserved.

"""OpenID server."""

__metaclass__ = type
__all__ = [
    'OpenIDMixin',
    ]

import cgi
import logging
import pytz
from datetime import datetime, timedelta
from time import time

from BeautifulSoup import BeautifulSoup

from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.app.session.interfaces import ISession, IClientIdManager
from zope.component import getUtility
from zope.security.proxy import isinstance as zisinstance

from openid.message import registerNamespaceAlias
from openid.server.server import CheckIDRequest, ENCODE_URL, Server
from openid.server.trustroot import TrustRoot
from openid.extensions.sreg import (
    SRegRequest, SRegResponse, data_fields as sreg_data_fields)
from openid import oidutil

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.components.openidserver import (
    OpenIDPersistentIdentity, CurrentOpenIDEndPoint)
from canonical.launchpad.interfaces.person import (
    IPersonSet, PersonVisibility)
from canonical.launchpad.interfaces.logintoken import (
    ILoginTokenSet, LoginTokenType)
from canonical.launchpad.interfaces.openidserver import (
    ILaunchpadOpenIDStoreFactory, ILoginServiceAuthorizeForm,
    ILoginServiceLoginForm, IOpenIDAuthorizationSet, IOpenIDRPConfigSet,
    IOpenIDRPSummarySet)
from canonical.launchpad.validators.email import valid_email
from canonical.launchpad.webapp import (
    action, custom_widget, LaunchpadFormView, LaunchpadView)
from canonical.launchpad.webapp.interfaces import (
    IPlacelessLoginSource, UnexpectedFormData)
from canonical.launchpad.webapp.login import logInPerson, logoutPerson
from canonical.launchpad.webapp.menu import structured
from canonical.uuid import generate_uuid
from canonical.widgets.itemswidgets import LaunchpadRadioWidget


OPENID_REQUEST_TIMEOUT = 3600
SESSION_PKG_KEY = 'OpenID'
LAUNCHPAD_TEAMS_NS = 'http://ns.launchpad.net/2007/openid-teams'
registerNamespaceAlias(LAUNCHPAD_TEAMS_NS, 'lp')

# Shut up noisy OpenID library
def null_log(message, level=0):
    pass
oidutil.log = null_log


sreg_data_fields.update({
    'x_address1': 'Address line 1',
    'x_address2': 'Address line 2',
    'x_city': 'City',
    'x_province': 'Province',
    'x_phone': 'Phone number',
    'x_organization': 'Organization',
    })


sreg_data_fields_order = [
    'fullname', 'nickname', 'email', 'timezone',
    'x_address1', 'x_address2', 'x_city', 'x_province',
    'country', 'postcode', 'x_phone', 'x_organization',
    ]


class OpenIDMixin:

    openid_request = None

    def __init__(self, context, request):
        super(OpenIDMixin, self).__init__(context, request)
        store_factory = getUtility(ILaunchpadOpenIDStoreFactory)
        self.server_url = CurrentOpenIDEndPoint.getServiceURL()
        self.openid_server = Server(store_factory(), self.server_url)

    @property
    def user_identity_url(self):
        return OpenIDPersistentIdentity(self.user.account).openid_identity_url

    def isIdentityOwner(self):
        """Return True if the user can authenticate as the given ID."""
        assert self.user is not None, "user should be logged in by now."
        return (self.openid_request.idSelect() or
                self.openid_request.identity == self.user_identity_url)

    @cachedproperty('_openid_parameters')
    def openid_parameters(self):
        """A dictionary of OpenID query parameters from request."""
        query = {}
        for key, value in self.request.form.items():
            if key.startswith('openid.'):
                query[key.encode('US-ASCII')] = value.encode('US-ASCII')
        return query

    def getSession(self):
        return ISession(self.request)[SESSION_PKG_KEY]

    @staticmethod
    def _sweep(now, session):
        """Clean our Session of nonces older than 1 hour.

        The session argument is edited in place to remove the expired items:
          >>> now = 10000
          >>> session = {
          ...     'x': (9999, 'foo'),
          ...     'y': (11000, 'bar'),
          ...     'z': (100, 'baz')
          ...     }
          >>> OpenIDMixin._sweep(now, session)
          >>> for key in sorted(session):
          ...     print key, session[key]
          x (9999, 'foo')
          y (11000, 'bar')
        """
        to_delete = []
        for key, value in session.items():
            timestamp = value[0]
            if timestamp < now - OPENID_REQUEST_TIMEOUT:
                to_delete.append(key)
        for key in to_delete:
            del session[key]

    def restoreRequestFromSession(self, key):
        """Get the OpenIDRequest from our session using the given key."""
        session = self.getSession()
        try:
            timestamp, self._openid_parameters = session[key]
        except KeyError:
            raise UnexpectedFormData("Invalid or expired nonce")

        # Decode the request parameters and create the request object.
        self.openid_request = self.openid_server.decodeRequest(
            self.openid_parameters)
        assert zisinstance(self.openid_request, CheckIDRequest), (
            'Invalid OpenIDRequest in session')

    def saveRequestInSession(self, key):
        """Save the OpenIDRequest in our session using the given key."""
        query = self.openid_parameters
        assert query.get('openid.mode') == 'checkid_setup', (
            'Can only serialise checkid_setup OpenID requests')

        session = self.getSession()
        # We also store the time with the openid_request so we can clear
        # out old requests after some time, say 1 hour.
        now = time()
        self._sweep(now, session)
        session[key] = (now, query)

    def trashRequestInSession(self, key):
        """Remove the OpenIDRequest from the session using the given key."""
        session = self.getSession()
        try:
            del session[key]
        except KeyError:
            pass

    @property
    def sreg_field_names(self):
        """Return the list of sreg keys that will be provided to the RP."""
        sreg_request = SRegRequest.fromOpenIDRequest(self.openid_request)

        field_names = set(sreg_request.required + sreg_request.optional)
        # Now subset them based on what keys are allowed from the
        # RP config:
        rpconfig = getUtility(IOpenIDRPConfigSet).getByTrustRoot(
            self.openid_request.trust_root)
        if rpconfig is None:
            # The nickname field is permitted by default.
            field_names.intersection_update(['nickname'])
        else:
            field_names.intersection_update(rpconfig.allowed_sreg)

        # Sort the set of names according to our field order
        return [name for name in sreg_data_fields_order
                if name in field_names]

    @property
    def sreg_fields(self):
        """Return a list of the sreg (field, value) pairs for the RP.

        As this function returns user details, the user must be logged
        in before accessing this property.

        Shipping information is taken from the last shipped Shipit
        request.
        """
        assert self.user is not None, (
            'Must be logged in to calculate sreg items')
        # Collect registration values
        values = {}
        values['nickname'] = self.user.name
        values['fullname'] = self.user.displayname
        values['email'] = self.user.preferredemail.email
        if self.user.time_zone is not None:
            values['timezone'] = self.user.time_zone
        shipment = self.user.lastShippedRequest()
        if shipment is not None:
            values['x_address1'] = shipment.addressline1
            values['x_city'] = shipment.city
            values['country'] = shipment.country.name
            if shipment.addressline2 is not None:
                values['x_address2'] = shipment.addressline2
            if shipment.organization is not None:
                values['x_organization'] = shipment.organization
            if shipment.province is not None:
                values['x_province'] = shipment.province
            if shipment.postcode is not None:
                values['postcode'] = shipment.postcode
            if shipment.phone is not None:
                values['x_phone'] = shipment.phone
        return [(field, values[field])
                for field in self.sreg_field_names if field in values]

    def checkTeamMembership(self, openid_response):
        """Perform team membership checks.

        If any team membership checks have been requested as part of
        the OpenID request, annotate the response with the list of
        teams the user is actually a member of.
        """
        assert self.user is not None, (
            'Must be logged in to calculate team membership')
        args = self.openid_request.message.getArgs(LAUNCHPAD_TEAMS_NS)
        team_names = args.get('query_membership')
        if not team_names:
            return
        team_names = team_names.split(',')
        memberships = []
        person_set = getUtility(IPersonSet)
        for team_name in team_names:
            team = person_set.getByName(team_name)
            if team is None or not team.isTeam():
                continue
            # Control access to private teams
            if team.visibility != PersonVisibility.PUBLIC:
                # XXX jamesh 2008-02-14 bug=174076:

                # We should have fine grained control of which RPs can
                # query for which teams, but for now we will let any
                # RP with an OpenIDRPconfig perform such queries.
                rpconfig = getUtility(IOpenIDRPConfigSet).getByTrustRoot(
                    self.openid_request.trust_root)
                if rpconfig is None:
                    continue
            if self.user.inTeam(team):
                memberships.append(team_name)
        openid_response.fields.namespaces.addAlias(LAUNCHPAD_TEAMS_NS, 'lp')
        openid_response.fields.setArg(
            LAUNCHPAD_TEAMS_NS, 'is_member', ','.join(memberships))

    def renderOpenIDResponse(self, openid_response):
        webresponse = self.openid_server.encodeResponse(openid_response)
        response = self.request.response
        response.setStatus(webresponse.code)
        for header, value in webresponse.headers.items():
            response.setHeader(header, value)
        return webresponse.body

    def createPositiveResponse(self):
        """Create a positive assertion OpenIDResponse.

        This method should be called to create the response to
        successful checkid requests.

        If the trust root for the request is in openid_sreg_trustroots,
        then additional user information is included with the
        response.
        """
        assert self.user is not None, (
            'Must be logged in for positive OpenID response')
        assert self.openid_request is not None, (
            'No OpenID request to respond to.')

        if not self.isIdentityOwner():
            return self.createFailedResponse()

        if self.openid_request.idSelect():
            response = self.openid_request.answer(
                True, identity=self.user_identity_url)
        else:
            response = self.openid_request.answer(True)

        # Add sreg result data
        sreg_fields = self.sreg_fields
        if sreg_fields:
            sreg_request = SRegRequest.fromOpenIDRequest(self.openid_request)
            sreg_response = SRegResponse.extractResponse(
                sreg_request, dict(sreg_fields))
            response.addExtension(sreg_response)

        self.checkTeamMembership(response)

        rp_summary_set = getUtility(IOpenIDRPSummarySet)
        rp_summary_set.record(
            self.user.account, self.openid_request.trust_root)

        return response

    def createFailedResponse(self):
        """Create a failed assertion OpenIDResponse.

        This method should be called to create the response to
        unsuccessful checkid requests.
        """
        assert self.openid_request is not None, (
            'No OpenID request to respond to.')
        response = self.openid_request.answer(False, self.server_url)
        return response


class OpenIDView(OpenIDMixin, LaunchpadView):
    """An OpenID Provider endpoint for Launchpad.

    This class implemnts an OpenID endpoint using the python-openid
    library.  In addition to the normal modes of operation, it also
    implements the OpenID 2.0 identifier select mode.
    """

    default_template = ViewPageTemplateFile("../templates/openid-index.pt")
    invalid_identity_template = ViewPageTemplateFile(
        "../templates/openid-invalid-identity.pt")

    def render(self):
        """Handle all OpenID requests and form submissions

        Returns the page contents after setting all relevant headers in
        self.request.response
        """
        # NB: Will be None if there are no parameters in the request.
        self.openid_request = self.openid_server.decodeRequest(
            self.openid_parameters)

        # Not an OpenID request, so display a message explaining what this
        # is to nosy users.
        if self.openid_request is None:
            return self.default_template()

        # Handle checkid_immediate requests.
        if self.openid_request.mode == 'checkid_immediate':
            if self.isAuthorized():
                openid_response = self.createPositiveResponse()
            else:
                openid_response = self.createFailedResponse()

        # Handle checkid_setup requests.
        elif self.openid_request.mode == 'checkid_setup':
            # If we can not possibly handle this identity URL, show an
            # error page telling the user.
            if not self.canHandleIdentity():
                return self.invalid_identity_template()

            if self.user is None:
                return self.showLoginPage()
            if not self.isIdentityOwner():
                openid_response = self.createFailedResponse()
            elif self.isAuthorized():
                # User is logged in and the site is authorized.
                openid_response = self.createPositiveResponse()
            else:
                # We have an interactive id check request (checkid_setup).
                # Render a page allowing the user to choose how to proceed.
                return self.showDecidePage()

        else:
            openid_response = self.openid_server.handleRequest(
                    self.openid_request)

        # If the above code has not already returned or raised an exception,
        # openid_respose is filled out ready for the openid library to render.
        return self.renderOpenIDResponse(openid_response)

    def storeOpenIDRequestInSession(self):
        # To ensure that the user has seen this page and it was actually the
        # user that clicks the 'Accept' button, we generate a nonce and
        # use it to store the openid_request in the session. The nonce
        # is passed through by the form, but it is only meaningful if
        # it was used to store information in the actual users session,
        # rather than the session of a malicious connection attempting a
        # man-in-the-middle attack.
        nonce = generate_uuid()
        self.saveRequestInSession('nonce' + nonce)
        self.nonce = nonce

    def showLoginPage(self):
        """Render the login dialog.

        This should be done if the user has not yet authenticated to
        Launchpad.
        """
        self.storeOpenIDRequestInSession()
        return LoginServiceLoginView(
            self.context, self.request, self.nonce)()

    def showDecidePage(self):
        """Render the 'do you want to authenticate' page.

        An OpenID consumer has redirected the user here to be authenticated.
        We need to explain what they are doing here and ask them if they
        want to allow Launchpad to authenticate them with the OpenID consumer.
        """
        self.storeOpenIDRequestInSession()
        return LoginServiceAuthorizeView(
            self.context, self.request, self.nonce)()

    def canHandleIdentity(self):
        """Returns True if the identity URL is supported by the server."""
        identity = self.openid_request.identity
        return (self.openid_request.idSelect() or
                CurrentOpenIDEndPoint.supportsURL(identity))

    def isAuthorized(self):
        """Check if the identity is authorized for the trust_root"""
        # Can't be authorized if we are not logged in, or logged in as a
        # user other than the identity owner.
        if self.user is None or not self.isIdentityOwner():
            return False

        client_id = getUtility(IClientIdManager).getClientId(self.request)
        auth_set = getUtility(IOpenIDAuthorizationSet)

        return auth_set.isAuthorized(
                self.user, self.openid_request.trust_root, client_id)


class LoginServiceBaseView(OpenIDMixin, LaunchpadFormView):
    """Common functionality for the OpenID login and authorize forms."""

    def __init__(self, context, request, nonce=None):
        super(LoginServiceBaseView, self).__init__(context, request)
        self.nonce = nonce

    @property
    def initial_values(self):
        return {'nonce': self.nonce}

    def setUpWidgets(self):
        """Set up the widgets, and restore the OpenID request."""
        super(LoginServiceBaseView, self).setUpWidgets()

        # Restore the OpenID request.
        widget = self.widgets['nonce']
        if widget.hasValidInput():
            self.nonce = widget.getInputValue()
        if self.nonce is None:
            raise UnexpectedFormData("No OpenID request.")
        self.restoreRequestFromSession('nonce' + self.nonce)

    def trashRequest(self):
        """Remove the OpenID request from the session."""
        # XXX: jamesh 2007-06-22
        # Removing the OpenID request from the session leads to an
        # UnexpectedFormData exception if the user hits back and
        # submits the form again.  Not deleting the request allows
        # this behaviour (although a well designed RP will then
        # complain about an unexpected OpenID response ...).

        #self.trashRequestInSession('nonce' + self.nonce)

    @property
    def rpconfig(self):
        """Return a dictionary of information about the relying party.

        The dictionary contains 'title' and 'logo' entries.

        If the relying party is not known, the title will be the same
        as the trust root.
        """
        assert self.openid_request is not None, (
            'Could not find the OpenID request')
        return getUtility(IOpenIDRPConfigSet).getByTrustRoot(
            self.openid_request.trust_root)

    def isSaneTrustRoot(self):
        """Return True if the RP's trust root looks sane."""
        assert self.openid_request is not None, (
            'Could not find the OpenID request')
        trust_root = TrustRoot.parse(self.openid_request.trust_root)
        return trust_root.isSane()


class LoginServiceAuthorizeView(LoginServiceBaseView):

    schema = ILoginServiceAuthorizeForm
    template = ViewPageTemplateFile(
        "../templates/loginservice-authorize.pt")

    @action('Sign In', name='auth')
    def auth_action(self, action, data):
        # If the user is not logged in (e.g. if they used the back
        # button in their browser, send them to the login page).
        if self.user is None:
            return LoginServiceLoginView(
                self.context, self.request, self.nonce)()
        self.trashRequest()
        return self.renderOpenIDResponse(self.createPositiveResponse())

    @action("Not Now", name='deny')
    def deny_action(self, action, data):
        self.trashRequest()
        return self.renderOpenIDResponse(self.createFailedResponse())

    @action("I'm Someone Else", name='logout')
    # XXX mpt 2007-06-18: "I'm" should use a typographical apostrophe.
    # XXX mpt 2007-06-18: "Someone Else" should be "Not" then the
    # person's name.
    def logout_action(self, action, data):
        # Log the user out and render the login page again.
        logoutPerson(self.request)
        # Display the unauthenticated form
        return LoginServiceLoginView(
            self.context, self.request, self.nonce)()


class LoginServiceLoginView(LoginServiceBaseView):

    schema = ILoginServiceLoginForm
    template = ViewPageTemplateFile("../templates/loginservice-login.pt")
    custom_widget('action', LaunchpadRadioWidget)

    email_sent_template = ViewPageTemplateFile(
        "../templates/loginservice-email-sent.pt")

    @property
    def initial_values(self):
        values = super(LoginServiceLoginView, self).initial_values
        values['action'] = 'login'
        return values

    def setUpWidgets(self):
        super(LoginServiceLoginView, self).setUpWidgets()
        # Dissect the action radio button group into three buttons.
        soup = BeautifulSoup(self.widgets['action']())
        [login, createaccount, resetpassword] = soup.findAll('label')
        self.login_radio_button = str(login)
        self.createaccount_radio_button = str(createaccount)
        self.resetpassword_radio_button = str(resetpassword)

    def validate(self, data):
        email = data.get('email')
        action = data.get('action')
        password = data.get('password')
        if email is None or not valid_email(email):
            self.addError('Please enter a valid email address.')
            return

        person = getUtility(IPersonSet).getByEmail(email)
        if action == 'login':
            self.validateEmailAndPassword(email, password)
        elif action == 'resetpassword':
            if person is None:
                self.addError(_(
                    "Your account details have not been found. Please "
                    "check your subscription email address and try again."))
            elif person.isTeam():
                self.addError(
                    structured(_(
                    "The email address <strong>${email}</strong> can not be "
                    "used to log in as it belongs to a team.",
                    mapping=dict(email=email))))
        elif action == 'createaccount':
            if person is not None and person.is_valid_person:
                self.addError(_(
                    "Sorry, someone has already registered the ${email} "
                    "email address.  If this is you and you've forgotten "
                    "your password, just choose the 'I've forgotten my "
                    "password' option below and we'll allow you to "
                    "change it.",
                    mapping=dict(email=cgi.escape(email))))
            else:
                # This is either an email address we've never seen or it's
                # associated with an unvalidated profile, so we just move
                # on with the registration process as if we had never seen it.
                pass
        else:
            raise UnexpectedFormData("Unknown action")

    def validateEmailAndPassword(self, email, password):
        """Check that the email address and password are valid for login."""
        loginsource = getUtility(IPlacelessLoginSource)
        principal = loginsource.getPrincipalByLogin(email)
        if principal is not None and principal.validate(password):
            person = getUtility(IPersonSet).getByEmail(email)
            if person.preferredemail is None:
                self.addError(
                        _(
                    "The email address '${email}' has not yet been "
                    "confirmed. We sent an email to that address with "
                    "instructions on how to confirm that it belongs to you.",
                    mapping=dict(email=email)))
                self.token = getUtility(ILoginTokenSet).new(
                    person, email, email, LoginTokenType.VALIDATEEMAIL)
                self.token.sendEmailValidationRequest(
                    self.request.getApplicationURL())
                self.saveRequestInSession('token' + self.token.token)

            if not person.is_valid_person:
                # Normally invalid accounts will have a NULL password
                # so this will be rarely seen, if ever. An account with no
                # valid email addresses might end up in this situation,
                # such as having them flagged as OLD by a email bounce
                # processor or manual changes by the DBA.
                self.addError(_("This account cannot be used."))
        else:
            self.addError(_("Incorrect password for the provided "
                            "email address."))

    @action('Continue', name='continue')
    def continue_action(self, action, data):
        email = data['email']
        action = data['action']
        self.trashRequest()
        if action == 'login':
            password = data['password']
            loginsource = getUtility(IPlacelessLoginSource)
            principal = loginsource.getPrincipalByLogin(email)
            logInPerson(self.request, principal, email)
            return self.renderOpenIDResponse(self.createPositiveResponse())
        elif action == 'resetpassword':
            return self.process_password_recovery(email)
        elif action == 'createaccount':
            return self.process_registration(email)
        else:
            raise UnexpectedFormData("Unknown action.")

    def process_registration(self, email):
        logintokenset = getUtility(ILoginTokenSet)
        self.token = logintokenset.new(
            requester=None, requesteremail=None, email=email,
            tokentype=LoginTokenType.NEWACCOUNT)
        self.token.sendNewUserNeutralEmail()
        self.saveRequestInSession('token' + self.token.token)
        self.email_heading = 'Registration mail sent'
        self.email_reason = 'to confirm your address.'
        return self.email_sent_template()

    def process_password_recovery(self, email):
        person = getUtility(IPersonSet).getByEmail(email)
        logintokenset = getUtility(ILoginTokenSet)
        self.token = logintokenset.new(
            person, email, email, LoginTokenType.PASSWORDRECOVERY)
        self.token.sendPasswordResetNeutralEmail()
        self.saveRequestInSession('token' + self.token.token)
        self.email_heading = 'Forgotten your password?'
        self.email_reason = 'with instructions on resetting your password.'
        return self.email_sent_template()


class ProtocolErrorView(LaunchpadView):
    """Render a ProtocolError raised by the openid library."""
    def render(self):
        response = self.request.response
        if self.context.whichEncoding() == ENCODE_URL:
            url = self.context.encodeToURL()
            response.redirect(url)
        else:
            response.setStatus(200)
        response.setHeader('Content-Type', 'text/plain;charset=utf-8')
        return self.context.encodeToKVForm()


class PreAuthorizeRPView(LaunchpadView):
    """Pre-authorize an OpenID consumer.

    This page expects to find a 'trust_root' and a 'callback' query parameters
    and it raises an UnexpectedFormData if any of them is not found or empty.

    The pre-authorization is only allowed if the HTTP referer and the given
    trust_root are in config.launchpad.openid_preauthorization_acl
    """

    # Number of hours a pre-authorization is valid for.
    PRE_AUTHORIZATION_VALIDITY = 2

    def __call__(self):
        form = self.request.form
        trust_root = form.get('trust_root')
        if not trust_root:
            raise UnexpectedFormData("trust_root was not specified.")
        callback = form.get('callback')
        if not callback:
            raise UnexpectedFormData("callback was not specified.")
        http_referrer = self.request.getHeader('referer', '')
        acl_lines = []
        if config.launchpad.openid_preauthorization_acl is not None:
            acl_lines = config.launchpad.openid_preauthorization_acl.split(
                '\n')
        for line in acl_lines:
            referrer, acl_trust_root = line.strip().split(None, 1)
            if (not http_referrer.startswith(referrer)
                or trust_root != acl_trust_root):
                continue

            client_id = getUtility(IClientIdManager).getClientId(self.request)
            expires = (datetime.now(pytz.timezone('UTC'))
                       + timedelta(hours=self.PRE_AUTHORIZATION_VALIDITY))
            getUtility(IOpenIDAuthorizationSet).authorize(
                self.user, trust_root, expires, client_id)
            # Need to commit the transaction because this will always be
            # processing GET requests.
            import transaction
            transaction.commit()
            break
        else:
            logging.info(
                "Unauthorized trust root (%s) or referrer (%s).",
                trust_root, http_referrer)
        self.request.response.redirect(callback)
        return u''
