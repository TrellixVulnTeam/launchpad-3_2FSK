# Copyright 2004 Canonical Ltd

__metaclass__ = type

__all__ = [
    'BugTrackerHandshakeView',
    'ClaimProfileView',
    'ClaimTeamView',
    'LoginTokenSetNavigation',
    'LoginTokenView',
    'MergePeopleView',
    'NewAccountView',
    'ResetPasswordView',
    'ValidateEmailView',
    'ValidateGPGKeyView',
    ]

from itertools import chain
import urllib
import pytz
import cgi

from zope.lifecycleevent import ObjectCreatedEvent
from zope.app.form.browser import TextAreaWidget
from zope.component import getUtility
from zope.event import notify
from zope.interface import alsoProvides, directlyProvides, Interface
from zope.security.proxy import removeSecurityProxy

from canonical.database.sqlbase import flush_database_updates
from canonical.widgets import LaunchpadRadioWidget, PasswordChangeWidget
from canonical.launchpad import _
from canonical.launchpad.interfaces.account import IAccountSet
from canonical.launchpad.webapp.interfaces import (
    IAlwaysSubmittedWidget, IPlacelessLoginSource)
from canonical.launchpad.webapp.login import logInPerson
from canonical.launchpad.webapp.menu import structured
from canonical.launchpad.webapp.vhosts import allvhosts
from canonical.launchpad.webapp import (
    action, canonical_url, custom_widget, GetitemNavigation,
    LaunchpadEditFormView, LaunchpadFormView, LaunchpadView)

from canonical.launchpad.browser.openidserver import OpenIDMixin
from canonical.launchpad.browser.team import HasRenewalPolicyMixin
from canonical.launchpad.interfaces import (
    EmailAddressStatus, GPGKeyAlgorithm, GPGKeyNotFoundError,
    GPGVerificationError, IEmailAddressSet, IGPGHandler, IGPGKeySet,
    IGPGKeyValidationForm, ILoginToken, ILoginTokenSet,
    INewPersonForm, IOpenIDRPConfigSet, IPerson, IPersonSet, ITeam,
    LoginTokenType, PersonCreationRationale, ShipItConstants,
    UnexpectedFormData)
from canonical.launchpad.interfaces.account import AccountStatus


UTC = pytz.UTC


class LoginTokenSetNavigation(GetitemNavigation):

    usedfor = ILoginTokenSet


class LoginTokenView(LaunchpadView):
    """The default view for LoginToken.

    This view will check the token type and then redirect to the specific view
    for that type of token, if it's not yet a consumed token. We use this view
    so we don't have to add "+validateemail", "+newaccount", etc, on URLs we
    send by email.

    If this is a consumed token, then we simply display a page explaining that
    they got this token because they tried to do something that required email
    address confirmation, but that confirmation is already concluded.
    """

    PAGES = {LoginTokenType.PASSWORDRECOVERY: '+resetpassword',
             LoginTokenType.ACCOUNTMERGE: '+accountmerge',
             LoginTokenType.NEWACCOUNT: '+newaccount',
             LoginTokenType.NEWPROFILE: '+newaccount',
             LoginTokenType.VALIDATEEMAIL: '+validateemail',
             LoginTokenType.VALIDATETEAMEMAIL: '+validateteamemail',
             LoginTokenType.VALIDATEGPG: '+validategpg',
             LoginTokenType.VALIDATESIGNONLYGPG: '+validatesignonlygpg',
             LoginTokenType.PROFILECLAIM: '+claimprofile',
             LoginTokenType.TEAMCLAIM: '+claimteam',
             LoginTokenType.BUGTRACKER: '+bugtracker-handshake',
             }

    def render(self):
        if self.context.date_consumed is None:
            url = urllib.basejoin(
                str(self.request.URL), self.PAGES[self.context.tokentype])
            self.request.response.redirect(url)
        else:
            return LaunchpadView.render(self)


class BaseLoginTokenView(OpenIDMixin):
    """A view class to be used by other LoginToken views."""

    expected_token_types = ()
    successfullyProcessed = False

    def redirectIfInvalidOrConsumedToken(self):
        """If this is a consumed or invalid token redirect to the LoginToken
        default view and return True.

        An invalid token is a token used for a purpose it wasn't generated for
        (i.e. create a new account with a VALIDATEEMAIL token).
        """
        assert self.expected_token_types
        if (self.context.date_consumed is not None
            or self.context.tokentype not in self.expected_token_types):
            self.request.response.redirect(canonical_url(self.context))
            return True
        else:
            return False

    def success(self, message):
        """Indicate to the user that the token was successfully processed.

        This involves adding a notification message, and redirecting the
        user to their Launchpad page.
        """
        self.successfullyProcessed = True
        self.request.response.addInfoNotification(message)

    def logInPersonByEmail(self, email):
        """Login the person with the given email address."""
        loginsource = getUtility(IPlacelessLoginSource)
        principal = loginsource.getPrincipalByLogin(email)
        logInPerson(self.request, principal, email)

    def maybeCompleteOpenIDRequest(self):
        """Respond to a pending OpenID request if one is found.

        The OpenIDRequest is looked up in the session based on the
        login token ID.  If a request exists, the rendered OpenID
        response is returned.

        If no OpenID request is found, None is returned.
        """
        try:
            self.restoreRequestFromSession('token' + self.context.token)
        except UnexpectedFormData:
            # There is no OpenIDRequest in the session
            return None
        self.next_url = None
        return self.renderOpenIDResponse(self.createPositiveResponse())

    def _cancel(self):
        """Consume the LoginToken and set self.next_url.

        next_url is set to the home page of this LoginToken's requester.
        """
        self.next_url = canonical_url(self.context.requester)
        self.context.consume()

    def accountWasSuspended(self, naked_person, reason):
        """Return True if the person's account was SUSPENDED, otherwise False.

        When the account was SUSPENDED, the Warning Notification with the
        reason is added to the request's response. The LoginToken is consumed.

        :param naked_person: An unproxied Person.
        :param reason: A sentence that explains why the SUSPENDED account
            cannot be used.
        """
        if naked_person.account.status != AccountStatus.SUSPENDED:
            return False
        suspended_account_mailto = (
            'mailto:feedback@launchpad.net?subject=SUSPENDED%20account')
        message = structured(
              '%s Contact a <a href="%s">Launchpad admin</a> '
              'about this issue.' % (reason, suspended_account_mailto))
        self.request.response.addWarningNotification(message)
        self.context.consume()
        return True


class ClaimProfileView(BaseLoginTokenView, LaunchpadFormView):

    schema = IPerson
    field_names = ['displayname', 'hide_email_addresses', 'password']
    custom_widget('password', PasswordChangeWidget)
    label = 'Claim Launchpad profile'

    expected_token_types = (LoginTokenType.PROFILECLAIM,)

    def initialize(self):
        if not self.redirectIfInvalidOrConsumedToken():
            self.claimed_profile = getUtility(IEmailAddressSet).getByEmail(
                self.context.email).person
        super(ClaimProfileView, self).initialize()

    @property
    def initial_values(self):
        return {'displayname': self.claimed_profile.displayname}

    @property
    def next_url(self):
        return canonical_url(self.claimed_profile)

    @action(_('Continue'), name='confirm')
    def confirm_action(self, action, data):
        email = getUtility(IEmailAddressSet).getByEmail(self.context.email)
        person = getUtility(IPersonSet).get(email.personID)
        # The user is not yet logged in, but we need to set some
        # things on his new account, so we need to remove the security
        # proxy from it.
        # XXX: Guilherme Salgado 2006-09-27 bug=62674:
        # We should be able to login with this person and set the
        # password, to avoid removing the security proxy, but it didn't
        # work, so I'm leaving this hack for now.
        naked_person = removeSecurityProxy(person)
        naked_person.displayname = data['displayname']
        naked_person.hide_email_addresses = data['hide_email_addresses']

        naked_email = removeSecurityProxy(email)

        naked_person.activateAccount(
            comment="Activated by claim profile.",
            password=data['password'],
            preferred_email=naked_email)
        self.context.consume()
        self.logInPersonByEmail(naked_email.email)
        self.request.response.addInfoNotification(_(
            "Profile claimed successfully"))


class ClaimTeamView(
    BaseLoginTokenView, HasRenewalPolicyMixin, LaunchpadEditFormView):

    schema = ITeam
    field_names = [
        'teamowner', 'displayname', 'teamdescription', 'subscriptionpolicy',
        'defaultmembershipperiod', 'renewal_policy', 'defaultrenewalperiod']
    label = 'Claim Launchpad team'
    custom_widget('teamdescription', TextAreaWidget, height=10, width=30)
    custom_widget(
        'renewal_policy', LaunchpadRadioWidget, orientation='vertical')
    custom_widget(
        'subscriptionpolicy', LaunchpadRadioWidget, orientation='vertical')

    expected_token_types = (LoginTokenType.TEAMCLAIM,)

    def initialize(self):
        if not self.redirectIfInvalidOrConsumedToken():
            self.claimed_profile = getUtility(IPersonSet).getByEmail(
                self.context.email)
            # Let's pretend the claimed profile provides ITeam while we
            # render/process this page, so that it behaves like a team.
            directlyProvides(removeSecurityProxy(self.claimed_profile), ITeam)
        super(ClaimTeamView, self).initialize()

    def setUpWidgets(self, context=None):
        self.form_fields['teamowner'].for_display = True
        super(ClaimTeamView, self).setUpWidgets(context=self.claimed_profile)
        alsoProvides(self.widgets['teamowner'], IAlwaysSubmittedWidget)

    @property
    def initial_values(self):
        return {'teamowner': self.context.requester}

    @action(_('Continue'), name='confirm')
    def confirm_action(self, action, data):
        self.claimed_profile.convertToTeam(team_owner=self.context.requester)
        # Although we converted the person to a team it seems that the
        # security proxy still thinks it's an IPerson and not an ITeam,
        # which means to edit it we need to be logged in as the person we
        # just converted into a team.  Of course, we can't do that, so we'll
        # have to remove its security proxy before we update it.
        self.updateContextFromData(
            data, context=removeSecurityProxy(self.claimed_profile))
        self.next_url = canonical_url(self.claimed_profile)
        self.request.response.addInfoNotification(
            _('Team claimed successfully'))

    @action(_('Cancel'), name='cancel')
    def cancel_action(self, action, data):
        self._cancel()


class ResetPasswordView(BaseLoginTokenView, LaunchpadFormView):

    schema = ILoginToken
    field_names = ['email', 'password']
    custom_widget('password', PasswordChangeWidget)
    label = 'Reset password'
    expected_token_types = (LoginTokenType.PASSWORDRECOVERY,)

    def initialize(self):
        self.redirectIfInvalidOrConsumedToken()
        super(ResetPasswordView, self).initialize()

    def validate(self, form_values):
        """Validate the email address."""
        email = form_values.get("email", "").strip()
        # All operations with email addresses must be case-insensitive. We
        # enforce that in EmailAddressSet, but here we only do a comparison,
        # so we have to .lower() them first.
        if email.lower() != self.context.email.lower():
            self.addError(_(
                "The email address you provided didn't match the address "
                "you provided when requesting the password reset."))

    @action(_('Continue'), name='continue')
    def continue_action(self, action, data):
        """Reset the user's password. When password is successfully changed,
        the LoginToken (self.context) used is consumed, so nobody can use
        it again.
        """
        emailset = getUtility(IEmailAddressSet)
        emailaddress = emailset.getByEmail(self.context.email)

        # XXX: Guilherme Salgado 2006-09-27 bug=62674:
        # It should be possible to do the login before this and avoid
        # this hack. In case the user doesn't want to be logged in
        # automatically we can log him out after doing what we want.
        naked_person = removeSecurityProxy(getUtility(IPersonSet).get(
            removeSecurityProxy(emailaddress).personID))
        #      end of evil code.

        # Suspended accounts cannot reset their password.
        reason = ('Your password cannot be reset because your account '
            'is suspended.')
        if self.accountWasSuspended(naked_person, reason):
            return
        # Reset password can be used to reactivate a deactivated account.
        elif naked_person.account.status == AccountStatus.DEACTIVATED:
            naked_person.reactivateAccount(
                comment="User reactivated the account using reset password.",
                password=data['password'],
                preferred_email=emailaddress)
            self.request.response.addInfoNotification(
                _('Welcome back to Launchpad.'))
        else:
            naked_person.password = data.get('password')

        # Make sure this person has a preferred email address.
        if naked_person.preferredemail != emailaddress:
            # Must remove the security proxy of the email address because the
            # user is not logged in at this point and we may need to change
            # its status.
            naked_person.validateAndEnsurePreferredEmail(
                removeSecurityProxy(emailaddress))

        self.context.consume()

        self.logInPersonByEmail(self.context.email)

        self.next_url = canonical_url(self.context.requester)
        self.request.response.addInfoNotification(
            _('Your password has been reset successfully.'))

        return self.maybeCompleteOpenIDRequest()

    @action(_('Cancel'), name='cancel')
    def cancel_action(self, action, data):
        self._cancel()


class ValidateGPGKeyView(BaseLoginTokenView, LaunchpadFormView):

    schema = IGPGKeyValidationForm
    field_names = []
    expected_token_types = (LoginTokenType.VALIDATEGPG,
                            LoginTokenType.VALIDATESIGNONLYGPG)

    def initialize(self):
        if not self.redirectIfInvalidOrConsumedToken():
            if self.context.tokentype == LoginTokenType.VALIDATESIGNONLYGPG:
                self.field_names = ['text_signature']
        super(ValidateGPGKeyView, self).initialize()

    def validate(self, data):
        self.gpg_key = self._getGPGKey()
        if self.context.tokentype == LoginTokenType.VALIDATESIGNONLYGPG:
            self._validateSignOnlyGPGKey(data)

    @action(_('Cancel'), name='cancel')
    def cancel_action(self, action, data):
        self._cancel()

    @action(_('Continue'), name='continue')
    def continue_action_gpg(self, action, data):
        self.next_url = canonical_url(self.context.requester)
        assert self.gpg_key is not None
        can_encrypt = (
            self.context.tokentype != LoginTokenType.VALIDATESIGNONLYGPG)
        self._activateGPGKey(self.gpg_key, can_encrypt=can_encrypt)

    def _validateSignOnlyGPGKey(self, data):
        # Verify the signed content.
        signedcontent = data.get('text_signature')
        if signedcontent is None:
            return

        try:
            signature = getUtility(IGPGHandler).getVerifiedSignature(
                signedcontent.encode('ASCII'))
        except (GPGVerificationError, UnicodeEncodeError), e:
            self.addError(_(
                'Launchpad could not verify your signature: ${err}',
                mapping=dict(err=str(e))))
            return

        if signature.fingerprint != self.context.fingerprint:
            self.addError(_(
                'The key used to sign the content (${fprint}) is not the '
                'key you were registering',
                mapping=dict(fprint=signature.fingerprint)))
            return

        # We compare the word-splitted content to avoid failures due
        # to whitepace differences.
        if signature.plain_data.split() != self.validationphrase.split():
            self.addError(_(
                'The signed content does not match the message found '
                'in the email.'))
            return

    def _activateGPGKey(self, key, can_encrypt):
        gpgkeyset = getUtility(IGPGKeySet)

        fingerprint = key.fingerprint
        requester = self.context.requester
        person_url = canonical_url(requester)

        # Is it a revalidation ?
        lpkey = gpgkeyset.getByFingerprint(fingerprint)

        if lpkey:
            lpkey.active = True
            lpkey.can_encrypt = can_encrypt
            msgid = _(
                'Key ${lpkey} successfully reactivated. '
                '<a href="${url}/+editpgpkeys">See more Information'
                '</a>',
                mapping=dict(lpkey=lpkey.displayname, url=person_url))
            self.request.response.addInfoNotification(structured(msgid))
            self.context.consume()
            return

        # Otherwise prepare to add
        ownerID = self.context.requester.id
        keyid = key.keyid
        keysize = key.keysize
        algorithm = GPGKeyAlgorithm.items[key.algorithm]

        # Add new key in DB. See IGPGKeySet for further information
        lpkey = gpgkeyset.new(ownerID, keyid, fingerprint, keysize, algorithm,
                              can_encrypt=can_encrypt)

        self.context.consume()
        self.request.response.addInfoNotification(_(
            "The key ${lpkey} was successfully validated. ",
            mapping=dict(lpkey=lpkey.displayname)))
        created, owned_by_others = self._createEmailAddresses(key.emails)

        if len(created):
            msgid = _(
                "<p>Some of your key's UIDs (<code>${emails}</code>) are "
                "not registered in Launchpad. If you want to use them in "
                'Launchpad, you will need to <a href="${url}/+editemails">'
                'confirm them</a> first.</p>',
                mapping=dict(emails=', '.join(created), url=person_url))
            self.request.response.addInfoNotification(structured(msgid))

        if len(owned_by_others):
            msgid = _(
                "<p>Also, some of them (<code>${emails}</code>) are "
                "associated with other profile(s) in Launchpad, so you may "
                'want to <a href="/people/+requestmerge">merge them</a> into '
                "your current one.</p>",
                mapping=dict(emails=', '.join(owned_by_others)))
            self.request.response.addInfoNotification(structured(msgid))

    def _createEmailAddresses(self, uids):
        """Create EmailAddresses for the GPG UIDs that do not exist yet.

        For each of the given UIDs, check if it is already registered and, if
        not, register it.

        Return a tuple containing the list of newly created emails (as
        strings) and the emails that exist and are already assigned to another
        person (also as strings).
        """
        emailset = getUtility(IEmailAddressSet)
        requester = self.context.requester
        emails = chain(requester.validatedemails, [requester.preferredemail])
        # Must remove the security proxy because the user may not be logged in
        # and thus won't be allowed to view the requester's email addresses.
        emails = [
            removeSecurityProxy(email).email.lower() for email in emails]

        created = []
        existing_and_owned_by_others = []
        for uid in uids:
            # Here we use .lower() because the case of email addresses's chars
            # don't matter to us (e.g. 'foo@baz.com' is the same as
            # 'Foo@Baz.com').  However, note that we use the original form
            # when creating a new email.
            if uid.lower() not in emails:
                # EmailAddressSet.getByEmail() is not case-sensitive, so
                # there's no need to do uid.lower() here.
                if emailset.getByEmail(uid) is not None:
                    # This email address is registered but does not belong to
                    # our user.
                    existing_and_owned_by_others.append(uid)
                else:
                    # The email is not yet registered, so we register it for
                    # our user.
                    email = emailset.new(uid, requester)
                    created.append(uid)

        return created, existing_and_owned_by_others

    @property
    def validationphrase(self):
        """The phrase used to validate sign-only GPG keys"""
        utctime = self.context.created.astimezone(UTC)
        return 'Please register %s to the\nLaunchpad user %s.  %s UTC' % (
            self.context.fingerprint, self.context.requester.name,
            utctime.strftime('%Y-%m-%d %H:%M:%S'))

    def _getGPGKey(self):
        """Look up the OpenPGP key for this login token.

        If the key can not be retrieved from the keyserver, the key
        has been revoked or expired, None is returned and an error is set
        using self.addError.
        """
        gpghandler = getUtility(IGPGHandler)

        requester = self.context.requester
        fingerprint = self.context.fingerprint
        assert fingerprint is not None

        person_url = canonical_url(requester)
        try:
            key = gpghandler.retrieveKey(fingerprint)
        except GPGKeyNotFoundError:
            self.addError(
                structured(_(
                'Launchpad could not import this OpenPGP key, because '
                '${key}. Check that you published it correctly in the '
                'global key ring (using <kbd>gpg --send-keys '
                'KEY</kbd>) and that you entered the fingerprint '
                'correctly (as produced by <kbd>gpg --fingerprint '
                'YOU</kdb>). Try later or <a href="${url}/+editpgpkeys"> '
                'cancel your request</a>.',
                mapping=dict(key=key, url=person_url))))
            return None

        # If key is globally revoked, skip the import and consume the token.
        if key.revoked:
            self.addError(
                    structured(_(
                'The key ${key} cannot be validated because it has been '
                'publicly revoked. You will need to generate a new key '
                '(using <kbd>gpg --genkey</kbd>) and repeat the previous '
                'process to <a href="${url}/+editpgpkeys">find and '
                'import</a> the new key.',
                mapping=dict(key=key.keyid, url=person_url))))
            return None

        if key.expired:
            self.addError(
                        structured(_(
                'The key ${key} cannot be validated because it has expired. '
                'Change the expiry date (in a terminal, enter '
                '<kbd>gpg --edit-key <var>your@e-mail.address</var></kbd> '
                'then enter <kbd>expire</kbd>), and try again.',
                mapping=dict(key=key.keyid))))
            return None

        return key


class ValidateEmailView(BaseLoginTokenView, LaunchpadFormView):

    schema = Interface
    field_names = []
    expected_token_types = (LoginTokenType.VALIDATEEMAIL,
                            LoginTokenType.VALIDATETEAMEMAIL)

    def initialize(self):
        self.redirectIfInvalidOrConsumedToken()
        super(ValidateEmailView, self).initialize()

    def validate(self, data):
        """Make sure the email address this token refers to is not in use."""
        validated = (
            EmailAddressStatus.VALIDATED, EmailAddressStatus.PREFERRED)
        requester = self.context.requester

        emailset = getUtility(IEmailAddressSet)
        email = emailset.getByEmail(self.context.email)
        if email is not None:
            if email.person.id != requester.id:
                dupe = email.person
                dname = cgi.escape(dupe.name)
                # Yes, hardcoding an autogenerated field name is an evil
                # hack, but if it fails nothing will happen.
                # -- Guilherme Salgado 2005-07-09
                url = allvhosts.configs['mainsite'].rooturl
                url += '/people/+requestmerge?field.dupeaccount=%s' % dname
                self.addError(
                        structured(_(
                    'This email address is already registered for another '
                    'Launchpad user account. This account can be a '
                    'duplicate of yours, created automatically, and in this '
                    'case you should be able to <a href="${url}">merge them'
                    '</a> into a single one.',
                    mapping=dict(url=url))))
            elif email.status in validated:
                self.addError(_(
                    "This email address is already registered and validated "
                    "for your Launchpad account. There's no need to validate "
                    "it again."))
            else:
                # Yay, email is not used by anybody else and is not yet
                # validated.
                pass

    @action(_('Cancel'), name='cancel')
    def cancel_action(self, action, data):
        self._cancel()

    @action(_('Continue'), name='continue')
    def continue_action(self, action, data):
        """Mark the new email address as VALIDATED in the database.

        If this is the first validated email of this person, it'll be marked
        as the preferred one.

        If the requester is a team, the team's contact address is removed (if
        any) and this becomes the team's contact address.
        """
        self.next_url = canonical_url(self.context.requester)
        email = self._ensureEmail()
        requester = self.context.requester

        if self.context.tokentype == LoginTokenType.VALIDATETEAMEMAIL:
            requester.setContactAddress(email)
        elif self.context.tokentype == LoginTokenType.VALIDATEEMAIL:
            requester.validateAndEnsurePreferredEmail(email)
        else:
            raise AssertionError(
                "We don't know how to process this token (%s) and this error "
                "should've been caught earlier" % self.context.tokentype)

        self.context.consume()
        self.request.response.addInfoNotification(
            _('Email address successfully confirmed.'))
        return self.maybeCompleteOpenIDRequest()

    def _ensureEmail(self):
        """Make sure self.requester has this token's email address as one of
        its email addresses and return it.
        """
        emailset = getUtility(IEmailAddressSet)
        email = emailset.getByEmail(self.context.email)
        if email is None:
            email = emailset.new(self.context.email, self.context.requester)
        return email


class NewAccountView(BaseLoginTokenView, LaunchpadFormView):
    """Page to create a new Launchpad account.

    # This is just a small test to make sure
    # LoginOrRegister.registered_origins and
    # NewAccountView.urls_and_rationales are kept in sync.
    >>> from canonical.launchpad.webapp.login import LoginOrRegister
    >>> urls = sorted(LoginOrRegister.registered_origins.values())
    >>> urls == sorted(NewAccountView.urls_and_rationales.keys())
    True
    """

    urls_and_rationales = {
        ShipItConstants.ubuntu_url:
            PersonCreationRationale.OWNER_CREATED_SHIPIT,
        ShipItConstants.kubuntu_url:
            PersonCreationRationale.OWNER_CREATED_SHIPIT,
        ShipItConstants.edubuntu_url:
            PersonCreationRationale.OWNER_CREATED_SHIPIT,
        }

    created_person = None

    schema = INewPersonForm
    field_names = ['displayname', 'hide_email_addresses', 'password']
    custom_widget('password', PasswordChangeWidget)
    label = 'Complete your registration'
    expected_token_types = (
        LoginTokenType.NEWACCOUNT, LoginTokenType.NEWPROFILE)

    def initialize(self):
        if self.redirectIfInvalidOrConsumedToken():
            return
        else:
            self.email = getUtility(IEmailAddressSet).getByEmail(
                self.context.email)
            super(NewAccountView, self).initialize()

    # Use a method to set self.next_url rather than a property because we
    # want to override self.next_url in a subclass of this.
    def setNextUrl(self):
        if self.context.redirection_url:
            self.next_url = self.context.redirection_url
        elif self.user is not None:
            # User is logged in, redirect to his home page.
            self.next_url = canonical_url(self.user)
        elif self.created_person is not None:
            # User is not logged in, redirect to the created person's home
            # page.
            self.next_url = canonical_url(self.created_person)
        else:
            self.next_url = None

    def validate(self, form_values):
        """Verify if the email address is not used by an existing account."""
        if self.email is not None:
            person = removeSecurityProxy(getUtility(IPersonSet).get(
                removeSecurityProxy(self.email).personID))
            if person.is_valid_person:
                self.addError(_(
                    'The email address ${email} is already registered.',
                    mapping=dict(email=self.context.email)))

    @action(_('Continue'), name='continue')
    def continue_action(self, action, data):
        """Create a new Person with the context's email address and set a
        preferred email and password to it, or use an existing Person
        associated with the context's email address, setting it as the
        preferred address and also setting the password.

        If everything went ok, we consume the LoginToken (self.context), so
        nobody can use it again.
        """
        if self.email is not None:
            # This is a placeholder profile automatically created by one of
            # our scripts, let's just confirm its email address and set a
            # password.
            person = getUtility(IPersonSet).get(
                removeSecurityProxy(self.email).personID)
            assert not person.is_valid_person, (
                'Account %s has already been claimed and this should '
                'have been caught by the validate() method.' % person.name)
            email = self.email
            # The user is not yet logged in, but we need to set some
            # things on his new account, so we need to remove the security
            # proxy from it.
            # XXX: Guilherme Salgado 2006-09-27 bug=62674:
            # We should be able to login with this person and set the
            # password, to avoid removing the security proxy, but it didn't
            # work, so I'm leaving this hack for now.
            naked_person = removeSecurityProxy(person)
            # Suspended accounts cannot reactivate their profile.
            reason = ('This profile cannot be claimed because the account '
                'is suspended.')
            if self.accountWasSuspended(naked_person, reason):
                return
            naked_person.displayname = data['displayname']
            naked_person.hide_email_addresses = data['hide_email_addresses']
            naked_person.activateAccount(
                "Activated by new account.",
                password=data['password'],
                preferred_email=self.email)
            naked_person.creation_rationale = self._getCreationRationale()
            naked_person.creation_comment = None
        else:
            person, email = self._createPersonAndEmail(
                data['displayname'], data['hide_email_addresses'],
                data['password'])
            account = getUtility(IAccountSet).get(person.accountID)
            removeSecurityProxy(account).status = AccountStatus.ACTIVE
            person.validateAndEnsurePreferredEmail(email)

        self.created_person = person
        self.context.consume()
        self.logInPersonByEmail(removeSecurityProxy(email).email)
        self.request.response.addInfoNotification(_(
            "Registration completed successfully"))
        self.setNextUrl()

        return self.maybeCompleteOpenIDRequest()

    def _getCreationRationale(self):
        """Return the creation rationale that should be used for this account.

        If there's an OpenID request in the session we use the given
        trust_root to find out the creation rationale. If there's no OpenID
        request but there is a rationale for the logintoken's redirection_url,
        then use that, otherwise uses
        PersonCreationRationale.OWNER_CREATED_LAUNCHPAD.
        """
        try:
            self.restoreRequestFromSession('token' + self.context.token)
        except UnexpectedFormData:
            # There is no OpenIDRequest in the session, so we'll try to infer
            # the creation rationale from the token's redirection_url.
            rationale = self.urls_and_rationales.get(
                self.context.redirection_url)
            if rationale is None:
                rationale = PersonCreationRationale.OWNER_CREATED_LAUNCHPAD
        else:
            rpconfig = getUtility(IOpenIDRPConfigSet).getByTrustRoot(
                self.openid_request.trust_root)
            if rpconfig is not None:
                rationale = rpconfig.creation_rationale
            else:
                rationale = (
                    PersonCreationRationale.OWNER_CREATED_UNKNOWN_TRUSTROOT)
        return rationale

    def _createPersonAndEmail(
            self, displayname, hide_email_addresses, password):
        """Create and return a new Person and EmailAddress.

        Use the given arguments and the email address stored in the
        LoginToken (our context).

        Also fire ObjectCreatedEvents for both the newly created Person
        and EmailAddress.
        """
        rationale = self._getCreationRationale()
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            self.context.email, rationale, displayname=displayname,
            password=password, passwordEncrypted=True,
            hide_email_addresses=hide_email_addresses)

        notify(ObjectCreatedEvent(person))
        notify(ObjectCreatedEvent(email))
        return person, email


class MergePeopleView(BaseLoginTokenView, LaunchpadView):

    expected_token_types = (LoginTokenType.ACCOUNTMERGE,)
    mergeCompleted = False

    def initialize(self):
        self.redirectIfInvalidOrConsumedToken()
        self.dupe = getUtility(IPersonSet).getByEmail(self.context.email)

    def success(self, message):
        # We're not a GeneralFormView, so we need to do the redirect
        # ourselves.
        BaseLoginTokenView.success(self, message)
        self.request.response.redirect(canonical_url(self.context.requester))

    def processForm(self):
        """Perform the merge."""
        if self.request.method != "POST":
            return

        # Merge requests must have a valid user account (one with a preferred
        # email) as requester.
        assert self.context.requester.preferredemail is not None
        self._doMerge()
        if self.mergeCompleted:
            self.success(_(
                'The accounts have been merged successfully. Everything that '
                'belonged to the duplicated account should now belong to '
                'your own account.'))
        else:
            self.success(_(
                'The e-mail address %s has been assigned to you, but the '
                'duplicate account you selected has other registered e-mail '
                'addresses too. To complete the merge, you have to prove '
                'that you have access to all those e-mail addresses.'
                % self.context.email))
        self.context.consume()

    def _doMerge(self):
        # The user proved that he has access to this email address of the
        # dupe account, so we can assign it to him.
        requester = self.context.requester
        emailset = getUtility(IEmailAddressSet)
        email = removeSecurityProxy(emailset.getByEmail(self.context.email))
        # As a person can have at most one preferred email, ensure
        # that this new email does not have the PREFERRED status.
        email.status = EmailAddressStatus.NEW
        email.personID = requester.id
        email.accountID = requester.accountID
        requester.validateAndEnsurePreferredEmail(email)

        # Need to flush all changes we made, so subsequent queries we make
        # with this transaction will see this changes and thus they'll be
        # displayed on the page that calls this method.
        flush_database_updates()

        # Now we must check if the dupe account still have registered email
        # addresses. If it hasn't we can actually do the merge.
        if emailset.getByPerson(self.dupe):
            self.mergeCompleted = False
            return

        # Call Stuart's magic function which will reassign all of the dupe
        # account's stuff to the user account.
        getUtility(IPersonSet).merge(self.dupe, requester)
        self.mergeCompleted = True


class BugTrackerHandshakeView(BaseLoginTokenView):
    """A view for authentication BugTracker handshake tokens."""
    expected_token_types = (LoginTokenType.BUGTRACKER,)

    def __call__(self):
        # We don't render any templates from this view as it's a
        # machine-only one, so we set the response to be plaintext.
        self.request.response.setHeader('Content-type', 'text/plain')

        # Reject the request if it is not a POST - but do not consume
        # the token.
        if self.request.method != 'POST':
            self.request.response.setStatus(405)
            self.request.response.setHeader('Allow', 'POST')
            return ("Only POST requests are accepted for bugtracker "
                    "handshakes.")

        # If the token has been used already or is invalid, return an
        # HTTP 410 (Gone).
        if self.redirectIfInvalidOrConsumedToken():
            self.request.response.setStatus(410)
            return "Token has already been used or is invalid."

        # The token is valid, so consume it and return an HTTP 200. This
        # tells the remote tracker that authentication was successful.
        self.context.consume()
        self.request.response.setStatus(200)
        self.request.response.setHeader('Content-type', 'text/plain')
        return "Handshake token validated."

