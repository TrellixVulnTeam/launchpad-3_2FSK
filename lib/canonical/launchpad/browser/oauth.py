# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'OAuthAccessTokenView',
    'OAuthAuthorizeTokenView',
    'OAuthRequestTokenView',
    'OAuthTokenAuthorizedView']

from zope.component import getUtility
from zope.formlib.form import Action, Actions

from lp.registry.interfaces.distribution import IDistributionSet
from canonical.launchpad.interfaces.oauth import (
    IOAuthConsumerSet, IOAuthRequestToken, IOAuthRequestTokenSet,
    OAUTH_CHALLENGE)
from lp.registry.interfaces.pillar import IPillarNameSet
from canonical.launchpad.webapp import LaunchpadFormView, LaunchpadView
from canonical.launchpad.webapp.authentication import (
    check_oauth_signature, get_oauth_authorization)
from canonical.launchpad.webapp.interfaces import (
    OAuthPermission, UnexpectedFormData)


class OAuthRequestTokenView(LaunchpadView):
    """Where consumers can ask for a request token."""

    def __call__(self):
        """Create a request token and include its key/secret in the response.

        If the consumer key is empty or the signature doesn't match, respond
        with a 401 status.  If the key is not empty but there's no consumer
        with it, we register a new consumer.
        """
        form = get_oauth_authorization(self.request)
        consumer_key = form.get('oauth_consumer_key')
        if not consumer_key:
            self.request.unauthorized(OAUTH_CHALLENGE)
            return u''

        consumer_set = getUtility(IOAuthConsumerSet)
        consumer = consumer_set.getByKey(consumer_key)
        if consumer is None:
            consumer = consumer_set.new(key=consumer_key)

        if not check_oauth_signature(self.request, consumer, None):
            return u''

        token = consumer.newRequestToken()
        body = u'oauth_token=%s&oauth_token_secret=%s' % (
            token.key, token.secret)
        return body


def token_exists_and_is_not_reviewed(form, action):
    return form.token is not None and not form.token.is_reviewed


def create_oauth_permission_actions():
    """Return a list of `Action`s for each possible `OAuthPermission`."""
    actions = Actions()
    def success(form, action, data):
        form.reviewToken(action.permission)
    for permission in OAuthPermission.items:
        action = Action(
            permission.title, name=permission.name, success=success,
            condition=token_exists_and_is_not_reviewed)
        action.permission = permission
        actions.append(action)
    return actions


class OAuthAuthorizeTokenView(LaunchpadFormView):
    """Where users authorize consumers to access Launchpad on their behalf."""

    actions = create_oauth_permission_actions()
    label = "Authorize application to access Launchpad on your behalf"
    schema = IOAuthRequestToken
    field_names = []
    token = None

    def initialize(self):
        self.storeTokenContext()
        form = get_oauth_authorization(self.request)
        key = form.get('oauth_token')
        if key:
            self.token = getUtility(IOAuthRequestTokenSet).getByKey(key)
        super(OAuthAuthorizeTokenView, self).initialize()

    def storeTokenContext(self):
        """Store the context given by the consumer in this view."""
        self.token_context = None
        # We have no guarantees that lp.context will be together with the
        # OAuth parameters, so we need to check in the Authorization header
        # and on the request's form if it's not in the former.
        oauth_data = get_oauth_authorization(self.request)
        context = oauth_data.get('lp.context')
        if not context:
            context = self.request.form.get('lp.context')
            if not context:
                return
        if '/' in context:
            distro, package = context.split('/')
            distro = getUtility(IDistributionSet).getByName(distro)
            if distro is None:
                raise UnexpectedFormData("Unknown context.")
            context = distro.getSourcePackage(package)
            if context is None:
                raise UnexpectedFormData("Unknown context.")
        else:
            context = getUtility(IPillarNameSet).getByName(context)
            if context is None:
                raise UnexpectedFormData("Unknown context.")
        self.token_context = context

    def reviewToken(self, permission):
        self.token.review(self.user, permission, self.token_context)
        callback = self.request.form.get('oauth_callback')
        if callback:
            self.next_url = callback
        else:
            self.next_url = (
                '+token-authorized?oauth_token=%s' % self.token.key)


class OAuthTokenAuthorizedView(LaunchpadView):
    """Where users who reviewed tokens may get redirected to.

    If the consumer didn't include an oauth_callback when sending the user to
    Launchpad, this is the page the user is redirected to after he logs in and
    reviews the token.
    """

    def initialize(self):
        key = self.request.form.get('oauth_token')
        self.token = getUtility(IOAuthRequestTokenSet).getByKey(key)
        assert self.token.is_reviewed, (
            'Users should be directed to this page only if they already '
            'authorized the token.')


class OAuthAccessTokenView(LaunchpadView):
    """Where consumers may exchange a request token for an access token."""

    def __call__(self):
        """Create an access token and respond with its key/secret/context.

        If the consumer is not registered, the given token key doesn't exist
        (or is not associated with the consumer), the signature does not match
        or no permission has been granted by the user, respond with a 401.
        """
        form = self.request.form
        consumer = getUtility(IOAuthConsumerSet).getByKey(
            form.get('oauth_consumer_key'))

        if consumer is None:
            self.request.unauthorized(OAUTH_CHALLENGE)
            return u''

        token = consumer.getRequestToken(form.get('oauth_token'))
        if token is None:
            self.request.unauthorized(OAUTH_CHALLENGE)
            return u''

        if not check_oauth_signature(self.request, consumer, token):
            return u''

        if (not token.is_reviewed
            or token.permission == OAuthPermission.UNAUTHORIZED):
            self.request.unauthorized(OAUTH_CHALLENGE)
            return u''

        access_token = token.createAccessToken()
        context_name = None
        if access_token.context is not None:
            context_name = access_token.context.name
        body = u'oauth_token=%s&oauth_token_secret=%s&lp.context=%s' % (
            access_token.key, access_token.secret, context_name)
        return body
