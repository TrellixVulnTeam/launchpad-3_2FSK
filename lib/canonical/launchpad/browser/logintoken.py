# Copyright 2004 Canonical Ltd
import urllib

from zope.component import getUtility
from zope.event import notify
from zope.app.form.browser.add import AddView
from zope.app.form.interfaces import WidgetsError
from zope.app.event.objectevent import ObjectCreatedEvent

from canonical.database.sqlbase import flushUpdates

from canonical.lp.dbschema import EmailAddressStatus, LoginTokenType

from canonical.foaf.nickname import generate_nick

from canonical.launchpad.webapp.interfaces import IPlacelessLoginSource
from canonical.launchpad.webapp.login import logInPerson

from canonical.launchpad.interfaces import IPersonSet, IEmailAddressSet
from canonical.launchpad.interfaces import IPasswordEncryptor, IEmailAddressSet


class LoginTokenView(object):
    """The default view for LoginToken.

    This view will check the token type and then redirect to the specific view
    for that type of token. We use this view so we don't have to add
    "+validate", "+newaccount", etc, on URLs we send by email.
    """

    PAGES = {LoginTokenType.PASSWORDRECOVERY: '+resetpassword',
             LoginTokenType.ACCOUNTMERGE: '+accountmerge',
             LoginTokenType.NEWACCOUNT: '+newaccount',
             LoginTokenType.VALIDATEEMAIL: '+validate'}

    def __init__(self, context, request):
        self.context = context
        self.request = request
        url = urllib.basejoin(str(request.URL),
                              self.PAGES[context.tokentype])
        request.response.redirect(url)


class ResetPasswordView(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.errormessage = None
        self.formProcessed = False
        self.email = None

    def processForm(self):
        """Check the email address, check if both passwords match and then
        reset the user's password. When password is successfully changed, the
        LoginToken (self.context) used is removed, so nobody can use it again.
        """
        if self.request.method != "POST":
            return

        self.email = self.request.form.get("email").strip()
        if self.email != self.context.email:
            self.errormessage = ("The email address you provided didn't "
                                 "match with the one you provided when you "
                                 "requested the password reset.")
            return

        password = self.request.form.get("password")
        password2 = self.request.form.get("password2")
        if not password and not password2:
            self.errormessage = "Your password cannot be empty."
            return

        if password != password2:
            self.errormessage = "Password didn't match."
            return

        # Make sure this person has a preferred email address.
        emailset = getUtility(IEmailAddressSet)
        emailaddress = emailset.getByEmail(self.context.email)
        emailaddress.status = EmailAddressStatus.VALIDATED
        flushUpdates()
        person = emailaddress.person
        if (person.preferredemail is None and 
            len(person.validatedemails) == 1):
            # This user have no preferred email set and this is the only
            # validated email he owns. We must set it as the preferred one.
            person.preferredemail = emailaddress

        encryptor = getUtility(IPasswordEncryptor)
        password = encryptor.encrypt(password)
        person.password = password
        self.formProcessed = True
        self.context.destroySelf()

    def successfullyProcessed(self):
        return self.formProcessed and not self.errormessage


class ValidateEmailView(object):

    def __init__(self, context, request):
        self.request = request
        self.context = context
        self.errormessage = ""
        self.formProcessed = False

    def successfullyProcessed(self):
        return self.formProcessed and not self.errormessage

    def processForm(self):
        if self.request.method != "POST":
            return

        self.formProcessed = True
        self.validate()

    def validate(self):
        """Check the requester and requesteremail, verify if the user provided
        the correct password and then set the email address status to
        VALIDATED. Also, if this is the first validated email for this user,
        we set it as the PREFERRED one for that user.
        When everything went ok, we delete the LoginToken (self.context) from
        the database, so nobody can use it again.
        """
        # Email validation requests must have a registered requester.
        assert self.context.requester is not None
        assert self.context.requesteremail is not None
        requester = self.context.requester
        password = self.request.form.get("password")
        encryptor = getUtility(IPasswordEncryptor)
        if not encryptor.validate(password, requester.password):
            self.errormessage = "Wrong password. Please try again."
            return 

        emailset = getUtility(IEmailAddressSet)
        reqemail = emailset.getByEmail(self.context.requesteremail)
        assert reqemail is not None
        assert reqemail.person == requester

        status = EmailAddressStatus.VALIDATED
        if not requester.preferredemail and not requester.validatedemails:
            # This is the first VALIDATED email for this Person, and we
            # need it to be the preferred one, to be able to communicate
            # with the user.
            status = EmailAddressStatus.PREFERRED

        email = emailset.getByEmail(self.context.email)
        if email is not None:
            # This email was obtained via gina or lucille and have been
            # marked as NEW on the DB. In this case all we have to do is
            # set that email status to VALIDATED.
            email.status = status
            self.context.destroySelf()
            return

        # New email validated by the user. We must add it to our emailaddress
        # table.
        email = emailset.new(self.context.email, status, requester.id)
        self.context.destroySelf()


class NewAccountView(AddView):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        AddView.__init__(self, context, request)
        self._nextURL = '.'
        self.passwordMismatch = False

    def nextURL(self):
        return self._nextURL

    def createAndAdd(self, data):
        """Check if both passwords match and then create a new Person.
        When everything went ok, we delete the LoginToken (self.context) from
        the database, so nobody can use it again.
        """
        kw = {}
        for key, value in data.items():
            kw[str(key)] = value

        errors = []

        password = kw['password']
        # We don't want to pass password2 to PersonSet.new().
        password2 = kw.pop('password2')
        if password2 != password:
            self.passwordMismatch = True
            errors.append('Password mismatch')

        if errors:
            raise WidgetsError(errors)

        kw['name'] = generate_nick(self.context.email)
        person = getUtility(IPersonSet).newPerson(**kw)
        notify(ObjectCreatedEvent(person))

        emailset = getUtility(IEmailAddressSet)
        preferred = EmailAddressStatus.PREFERRED
        email = emailset.new(self.context.email, preferred, person.id)
        notify(ObjectCreatedEvent(email))

        self._nextURL = '/people/%s' % person.name
        self.context.destroySelf()

        loginsource = getUtility(IPlacelessLoginSource)
        principal = loginsource.getPrincipalByLogin(email.email)
        if principal is not None and principal.validate(password):
            logInPerson(self.request, principal, email.email)
        return True


class MergePeopleView(object):

    def __init__(self, context, request):
        self.request = request
        self.context = context
        self.errormessage = ""
        self.formProcessed = False
        self.mergeCompleted = False
        self.dupe = getUtility(IPersonSet).getByEmail(context.email)

    def processForm(self):
        if self.request.method != "POST":
            return

        self.formProcessed = True
        if self.validate():
            self.doMerge()
            self.context.destroySelf()
            return

    def successfullyProcessed(self):
        return self.formProcessed and not self.errormessage

    def validate(self):
        """Verify if the user provided the correct password."""
        # Merge requests must have a registered requester.
        assert self.context.requester is not None
        assert self.context.requesteremail is not None
        requester = self.context.requester
        password = self.request.form.get("password")
        encryptor = getUtility(IPasswordEncryptor)
        if not encryptor.validate(password, requester.password):
            self.errormessage = "Wrong password. Please try again."
            return False

        return True

    def doMerge(self):
        # The user proved that he has access to this email address of the
        # dupe account, so we can assign it to him.
        email = getUtility(IEmailAddressSet).getByEmail(self.context.email)
        email.person = self.context.requester.id
        email.status = EmailAddressStatus.VALIDATED
        flushUpdates()
        
        # Now we must check if the dupe account still have registered email
        # addresses. If it haven't we can actually do the merge.
        if getUtility(IEmailAddressSet).getByPerson(self.dupe.id):
            self.mergeCompleted = False
            return

        # Call Stuart's magic function which will reassign all of the dupe
        # account's stuff to the user account.
        self.mergeCompleted = True
