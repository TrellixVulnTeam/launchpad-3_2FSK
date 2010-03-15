# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0231

"""Definition of the internet servers that Launchpad uses."""

__metaclass__ = type

import cgi
import pytz
import threading
import xmlrpclib
from datetime import datetime

import transaction
from transaction.interfaces import ISynchronizer

from zope.app.form.browser.widget import SimpleInputWidget
from zope.app.form.browser.itemswidgets import  MultiDataHelper
from zope.session.interfaces import ISession
from zope.app.publication.httpfactory import HTTPPublicationRequestFactory
from zope.app.publication.interfaces import IRequestPublicationFactory
from zope.app.publication.requestpublicationregistry import (
    factoryRegistry as publisher_factory_registry)
from zope.app.server import wsgi
from zope.app.wsgi import WSGIPublisherApplication
from zope.component import getUtility
from zope.interface import alsoProvides, implements
from zope.publisher.browser import (
    BrowserRequest, BrowserResponse, TestRequest)
from zope.publisher.interfaces import NotFound
from zope.publisher.xmlrpc import XMLRPCRequest, XMLRPCResponse
from zope.security.interfaces import IParticipation, Unauthorized
from zope.security.proxy import (
    isinstance as zope_isinstance, removeSecurityProxy)
from zope.server.http.commonaccesslogger import CommonAccessLogger
from zope.server.http.wsgihttpserver import PMDBWSGIHTTPServer

from canonical.cachedproperty import cachedproperty
from canonical.config import config

from canonical.lazr.interfaces.feed import IFeed
from lazr.restful.interfaces import (
    IWebServiceConfiguration, IWebServiceVersion)
from lazr.restful.publisher import (
    WebServicePublicationMixin, WebServiceRequestTraversal)

from lp.testopenid.interfaces.server import ITestOpenIDApplication
from canonical.launchpad.interfaces.launchpad import (
    IFeedsApplication, IPrivateApplication, IWebServiceApplication)
from canonical.launchpad.interfaces.oauth import (
    ClockSkew, IOAuthConsumerSet, NonceAlreadyUsed, TimestampOrderingError)
import canonical.launchpad.layers

from canonical.launchpad.webapp.adapter import (
    get_request_duration, RequestExpired)
from canonical.launchpad.webapp.authorization import (
    LAUNCHPAD_SECURITY_POLICY_CACHE_KEY)
from canonical.launchpad.webapp.notifications import (
    NotificationRequest, NotificationResponse, NotificationList)
from canonical.launchpad.webapp.interfaces import (
    ILaunchpadBrowserApplicationRequest, ILaunchpadProtocolError,
    IBasicLaunchpadRequest, IBrowserFormNG, INotificationRequest,
    INotificationResponse, IPlacelessAuthUtility, UnexpectedFormData,
    IPlacelessLoginSource, OAuthPermission)
from canonical.launchpad.webapp.authentication import (
    check_oauth_signature, get_oauth_authorization)
from canonical.launchpad.webapp.errorlog import ErrorReportRequest
from lazr.uri import URI
from canonical.launchpad.webapp.vhosts import allvhosts
from canonical.launchpad.webapp.publication import LaunchpadBrowserPublication
from canonical.launchpad.webapp.publisher import (
    get_current_browser_request, RedirectionView)
from canonical.launchpad.webapp.opstats import OpStats
from zc.zservertracelog.tracelog import Server as ZServerTracelogServer

from canonical.lazr.timeout import set_default_timeout_function


class StepsToGo:
    """

    >>> class FakeRequest:
    ...     def __init__(self, traversed, stack):
    ...         self._traversed_names = traversed
    ...         self.stack = stack
    ...     def getTraversalStack(self):
    ...         return self.stack
    ...     def setTraversalStack(self, stack):
    ...         self.stack = stack

    >>> request = FakeRequest([], ['baz', 'bar', 'foo'])
    >>> stepstogo = StepsToGo(request)
    >>> stepstogo.startswith()
    True
    >>> stepstogo.startswith('foo')
    True
    >>> stepstogo.startswith('foo', 'bar')
    True
    >>> stepstogo.startswith('foo', 'baz')
    False
    >>> len(stepstogo)
    3
    >>> print stepstogo.consume()
    foo
    >>> request._traversed_names
    ['foo']
    >>> request.stack
    ['baz', 'bar']
    >>> print stepstogo.consume()
    bar
    >>> bool(stepstogo)
    True
    >>> print stepstogo.consume()
    baz
    >>> print stepstogo.consume()
    None
    >>> bool(stepstogo)
    False

    >>> request = FakeRequest([], ['baz', 'bar', 'foo'])
    >>> list(StepsToGo(request))
    ['foo', 'bar', 'baz']

    """

    @property
    def _stack(self):
        return self.request.getTraversalStack()

    def __init__(self, request):
        self.request = request

    def __iter__(self):
        return self

    def consume(self):
        """Remove the next path step and return it.

        Returns None if there are no path steps left.
        """
        stack = self.request.getTraversalStack()
        try:
            nextstep = stack.pop()
        except IndexError:
            return None
        self.request._traversed_names.append(nextstep)
        self.request.setTraversalStack(stack)
        return nextstep

    def next(self):
        value = self.consume()
        if value is None:
            raise StopIteration
        return value

    def startswith(self, *args):
        """Return whether the steps to go start with the names given."""
        if not args:
            return True
        return self._stack[-len(args):] == list(reversed(args))

    def __len__(self):
        return len(self._stack)

    def __nonzero__(self):
        return bool(self._stack)


class ApplicationServerSettingRequestFactory:
    """Create a request and call its setApplicationServer method.

    Due to the factory-fanatical design of this part of Zope3, we need
    to have a kind of proxying factory here so that we can create an
    appropriate request and call its setApplicationServer method before it
    is used.
    """

    def __init__(self, requestfactory, host, protocol, port):
        self.requestfactory = requestfactory
        self.host = host
        self.protocol = protocol
        self.port = port

    def __call__(self, body_instream, environ, response=None):
        """Equivalent to the request's __init__ method."""
        # Make sure that HTTPS variable is set so that request.getURL() is
        # sane
        if self.protocol == 'https':
            environ['HTTPS'] = 'on'
        request = self.requestfactory(body_instream, environ, response)
        request.setApplicationServer(self.host, self.protocol, self.port)
        return request


class VirtualHostRequestPublicationFactory:
    """An `IRequestPublicationFactory` handling request to a Launchpad vhost.

    This factory will accepts requests to a particular Launchpad virtual host
    that matches a particular port and set of HTTP methods.
    """
    implements(IRequestPublicationFactory)

    default_methods = ['GET', 'HEAD', 'POST']

    def __init__(self, vhost_name, request_factory, publication_factory,
                 port=None, methods=None, handle_default_host=False):
        """Creates a new factory.

        :param vhost_name: The config section defining the virtual host
             handled by this factory.
        :param request_factory: The request factory to use for this virtual
             host's requests.
        :param publication_factory: The publication factory to use for this
            virtual host's requests.
        :param port: The port which is handled by this factory. If
            this is None, this factory will handle requests that
            originate on any port.
        :param methods: A sequence of HTTP methods that this factory handles.
        :param handle_default_host: Whether or not this factory is
            capable of handling requests that specify no hostname.
        """

        self.vhost_name = vhost_name
        self.request_factory = request_factory
        self.publication_factory = publication_factory
        self.port = port
        if methods is None:
            methods = self.default_methods
        self.methods = methods
        self.handle_default_host = handle_default_host

        self.vhost_config = allvhosts.configs[self.vhost_name]
        self.all_hostnames = set(self.vhost_config.althostnames
                                 + [self.vhost_config.hostname])
        self._thread_local = threading.local()
        self._thread_local.environment = None

    def canHandle(self, environment):
        """See `IRequestPublicationFactory`.

        Returns true if the HTTP host and port of the incoming request
        match the ones this factory is equipped to handle.
        """
        # We look at the wsgi environment to get the port this request
        # is coming in over.  The port number can be in one of two
        # places; either it's on the SERVER_PORT environment variable
        # or, as is the case with the test suite, it's on the
        # HTTP_HOST variable after a colon.
        # The former takes precedence, the port from the host variable is
        # only checked because the test suite doesn't set SERVER_PORT.
        host = environment.get('HTTP_HOST', '')
        port = environment.get('SERVER_PORT')
        if ":" in host:
            assert len(host.split(':')) == 2, (
                "Having a ':' in the host name isn't allowed.")
            host, new_port = host.split(':')
            if port is None:
                port = new_port

        if host == '':
            if not self.handle_default_host:
                return False
        elif host not in self.all_hostnames:
            return False
        else:
            # This factory handles this host.
            pass

        if self.port is not None:
            if port is not None:
                try:
                    port = int(port)
                except (ValueError):
                    port = None
            if self.port != port:
                return False

        self._thread_local.environment = environment
        self._thread_local.host = host
        return True

    def __call__(self):
        """See `IRequestPublicationFactory`.

        We know that this factory is the right one for the given host
        and port. But there might be something else wrong with the
        request.  For instance, it might have the wrong HTTP method.
        """
        environment = self._thread_local.environment
        if environment is None:
            raise AssertionError('This factory declined the request.')

        root_url = URI(self.vhost_config.rooturl)

        real_request_factory, publication_factory = (
            self.checkRequest(environment))

        if not real_request_factory:
            real_request_factory, publication_factory = (
                self.getRequestAndPublicationFactories(environment))

        host = environment.get('HTTP_HOST', '').split(':')[0]
        if host in ['', 'localhost']:
            # Sometimes requests come in to the default or local host.
            # If we set the application server for these requests,
            # they'll be handled as launchpad.net requests, and
            # responses will go out containing launchpad.net URLs.
            # That's a little unelegant, so we don't set the application
            # server for these requests.
            request_factory = real_request_factory
        else:
            request_factory = ApplicationServerSettingRequestFactory(
                real_request_factory,
                root_url.host,
                root_url.scheme,
                root_url.port)

        self._thread_local.environment = None
        return (request_factory, publication_factory)

    def getRequestAndPublicationFactories(self, environment):
        """Return the request and publication factories to use.

        You can override this method if the request and publication can
        vary based on the environment.
        """
        return self.request_factory, self.publication_factory

    def getAcceptableMethods(self, environment):
        """Return the HTTP methods acceptable in this particular environment.
        """
        return self.methods

    def checkRequest(self, environment):
        """Makes sure that the incoming HTTP request is of an expected type.

        This is different from canHandle() because we know the request
        went to the right place. It's just that it might be an invalid
        request for this handler.

        :return: An appropriate ProtocolErrorPublicationFactory if the
            HTTP request doesn't comply with the expected protocol. If
            the request does comply, (None, None).
        """
        method = environment.get('REQUEST_METHOD')

        if method in self.getAcceptableMethods(environment):
            factories = (None, None)
        else:
            request_factory = ProtocolErrorRequest
            publication_factory = ProtocolErrorPublicationFactory(
                405, headers={'Allow':" ".join(self.methods)})
            factories = (request_factory, publication_factory)

        return factories


class XMLRPCRequestPublicationFactory(VirtualHostRequestPublicationFactory):
    """A VirtualHostRequestPublicationFactory for XML-RPC.

    This factory only accepts XML-RPC method calls.
    """

    def __init__(self, vhost_name, request_factory, publication_factory,
                 port=None):
        super(XMLRPCRequestPublicationFactory, self).__init__(
            vhost_name, request_factory, publication_factory, port, ['POST'])

    def checkRequest(self, environment):
        """See `VirtualHostRequestPublicationFactory`.

        Accept only requests where the MIME type is text/xml.
        """
        request_factory, publication_factory = (
            super(XMLRPCRequestPublicationFactory, self).checkRequest(
                environment))
        if request_factory is None:
            mime_type = environment.get('CONTENT_TYPE')
            if mime_type != 'text/xml':
                request_factory = ProtocolErrorRequest
                # 415 - Unsupported Media Type
                publication_factory = ProtocolErrorPublicationFactory(415)
        return request_factory, publication_factory


class WebServiceRequestPublicationFactory(
    VirtualHostRequestPublicationFactory):
    """A VirtualHostRequestPublicationFactory for requests against
    resources published through a web service.
    """

    default_methods = [
        'GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS']

    def __init__(self, vhost_name, request_factory, publication_factory,
                 port=None):
        """This factory accepts requests that use all five major HTTP methods.
        """
        super(WebServiceRequestPublicationFactory, self).__init__(
            vhost_name, request_factory, publication_factory, port)


class VHostWebServiceRequestPublicationFactory(
    VirtualHostRequestPublicationFactory):
    """An `IRequestPublicationFactory` handling requests to vhosts.

    It also handles requests to the launchpad web service, if the
    request's path points to a web service resource.
    """

    def getAcceptableMethods(self, environment):
        """See `VirtualHostRequestPublicationFactory`.

        If this is a request for a webservice path, returns the appropriate
        methods.
        """
        if self.isWebServicePath(environment.get('PATH_INFO', '')):
            return WebServiceRequestPublicationFactory.default_methods
        else:
            return super(
                VHostWebServiceRequestPublicationFactory,
                self).getAcceptableMethods(environment)

    def getRequestAndPublicationFactories(self, environment):
        """See `VirtualHostRequestPublicationFactory`.

        If this is a request for a webservice path, returns the appropriate
        factories.
        """
        if self.isWebServicePath(environment.get('PATH_INFO', '')):
            return WebServiceClientRequest, WebServicePublication
        else:
            return super(
                VHostWebServiceRequestPublicationFactory,
                self).getRequestAndPublicationFactories(environment)

    def isWebServicePath(self, path):
        """Does the path refer to a web service resource?"""
        # Add a trailing slash, if it is missing.
        if not path.endswith('/'):
            path = path + '/'
        ws_config = getUtility(IWebServiceConfiguration)
        return path.startswith('/%s/' % ws_config.path_override)


class NotFoundRequestPublicationFactory:
    """An IRequestPublicationFactory which always yields a 404."""

    def canHandle(self, environment):
        """See `IRequestPublicationFactory`."""
        return True

    def __call__(self):
        """See `IRequestPublicationFactory`.

        Unlike other publication factories, this one doesn't wrap its
        request factory in an ApplicationServerSettingRequestFactory.
        That's because it's only triggered when there's no valid hostname.
        """
        return (ProtocolErrorRequest, ProtocolErrorPublicationFactory(404))


def get_query_string_params(request):
    """Return a dict of the decoded query string params for a request.

    The parameter values will be decoded as unicodes, exactly as
    `BrowserRequest` would do to build the request form.

    Defined here so that it can be used in both BasicLaunchpadRequest and
    the LaunchpadTestRequest (which doesn't inherit from
    BasicLaunchpadRequest).
    """
    query_string = request.get('QUERY_STRING', '')

    # Just in case QUERY_STRING is in the environment explicitly as
    # None (Some tests seem to do this, but not sure if it can ever
    # happen outside of tests.)
    if query_string is None:
        query_string = ''

    parsed_qs = cgi.parse_qs(query_string, keep_blank_values=True)
    # Use BrowserRequest._decode() for decoding the received parameters.
    decoded_qs = {}
    for key, values in parsed_qs.iteritems():
        decoded_qs[key] = [
            request._decode(value) for value in values]
    return decoded_qs


class BasicLaunchpadRequest:
    """Mixin request class to provide stepstogo."""

    implements(IBasicLaunchpadRequest)

    def __init__(self, body_instream, environ, response=None):
        self.traversed_objects = []
        self._wsgi_keys = set()
        self.needs_datepicker_iframe = False
        self.needs_datetimepicker_iframe = False
        self.needs_json = False
        self.needs_gmap2 = False
        super(BasicLaunchpadRequest, self).__init__(
            body_instream, environ, response)

        # Our response always vary based on authentication.
        self.response.setHeader('Vary', 'Cookie, Authorization')

    @property
    def stepstogo(self):
        return StepsToGo(self)

    def retry(self):
        """See IPublisherRequest."""
        new_request = super(BasicLaunchpadRequest, self).retry()
        # Propagate the list of keys we have set in the WSGI environment.
        new_request._wsgi_keys = self._wsgi_keys
        return new_request

    def getNearest(self, *some_interfaces):
        """See ILaunchpadBrowserApplicationRequest.getNearest()"""
        for context in reversed(self.traversed_objects):
            for iface in some_interfaces:
                if iface.providedBy(context):
                    return context, iface
        return None, None

    def setInWSGIEnvironment(self, key, value):
        """Set a key-value pair in the WSGI environment of this request.

        Raises KeyError if the key is already present in the environment
        but not set with setInWSGIEnvironment().
        """
        # This method expects the BasicLaunchpadRequest mixin to be used
        # with a base that provides self._orig_env.
        if key not in self._wsgi_keys and key in self._orig_env:
            raise KeyError("'%s' already present in wsgi environment." % key)
        self._orig_env[key] = value
        self._wsgi_keys.add(key)

    @cachedproperty
    def query_string_params(self):
        """See ILaunchpadBrowserApplicationRequest."""
        return get_query_string_params(self)


class LaunchpadBrowserRequestMixin:
    """A mixin for classes that share some method implementations."""

    def getRootURL(self, rootsite):
        """See IBasicLaunchpadRequest."""
        if rootsite is not None:
            assert rootsite in allvhosts.configs, (
                "rootsite is %s.  Must be in %r." % (
                    rootsite, sorted(allvhosts.configs.keys())))
            root_url = allvhosts.configs[rootsite].rooturl
        else:
            root_url = self.getApplicationURL() + '/'
        return root_url


class LaunchpadBrowserRequest(BasicLaunchpadRequest, BrowserRequest,
                              NotificationRequest, ErrorReportRequest,
                              LaunchpadBrowserRequestMixin):
    """Integration of launchpad mixin request classes to make an uber
    launchpad request class.
    """

    implements(ILaunchpadBrowserApplicationRequest, ISynchronizer)

    retry_max_count = 5    # How many times we're willing to retry

    def __init__(self, body_instream, environ, response=None):
        BasicLaunchpadRequest.__init__(self, body_instream, environ, response)
        transaction.manager.registerSynch(self)

    def _createResponse(self):
        """As per zope.publisher.browser.BrowserRequest._createResponse"""
        return LaunchpadBrowserResponse()

    def isRedirectInhibited(self):
        """Returns True if edge redirection has been inhibited."""
        return self.cookies.get('inhibit_beta_redirect', '0') == '1'

    @cachedproperty
    def form_ng(self):
        """See ILaunchpadBrowserApplicationRequest."""
        return BrowserFormNG(self.form)

    def setPrincipal(self, principal):
        self.clearSecurityPolicyCache()
        BrowserRequest.setPrincipal(self, principal)

    def clearSecurityPolicyCache(self):
        if LAUNCHPAD_SECURITY_POLICY_CACHE_KEY in self.annotations:
            del self.annotations[LAUNCHPAD_SECURITY_POLICY_CACHE_KEY]

    def beforeCompletion(self, transaction):
        """See `ISynchronizer`."""
        pass

    def afterCompletion(self, transaction):
        """See `ISynchronizer`.

        We clear the cache of security policy results on commit, as objects
        will be refetched from the database and the security checks may result
        in different answers.
        """
        self.clearSecurityPolicyCache()

    def newTransaction(self, transaction):
        """See `ISynchronizer`."""
        pass

class BrowserFormNG:
    """Wrapper that provides IBrowserFormNG around a regular form dict."""

    implements(IBrowserFormNG)

    def __init__(self, form):
        """Create a new BrowserFormNG that wraps a dict containing form data.
        """
        self.form = form

    def __contains__(self, name):
        """See IBrowserFormNG."""
        return name in self.form

    def __iter__(self):
        """See IBrowserFormNG."""
        return iter(self.form)

    def getOne(self, name, default=None):
        """See IBrowserFormNG."""
        value = self.form.get(name, default)
        if zope_isinstance(value, (list, tuple)):
            raise UnexpectedFormData(
                'Expected only one value form field %s: %s' % (name, value))
        return value

    def getAll(self, name, default=None):
        """See IBrowserFormNG."""
        # We don't want a mutable as a default parameter, so we use None as a
        # marker.
        if default is None:
            default = []
        else:
            assert zope_isinstance(default, list), (
                "default should be a list: %s" % default)
        value = self.form.get(name, default)
        if not zope_isinstance(value, list):
            value = [value]
        return value


def web_service_request_to_browser_request(webservice_request):
    """Convert a given webservice request into a webapp one.

    Simply overrides 'SERVER_URL' to the 'mainsite', preserving headers and
    body.
    """
    body = webservice_request.bodyStream.getCacheStream().read()
    environ = dict(webservice_request.environment)
    environ['SERVER_URL'] = allvhosts.configs['mainsite'].rooturl
    return LaunchpadBrowserRequest(body, environ)


class Zope3WidgetsUseIBrowserFormNGMonkeyPatch:
    """Make Zope3 widgets use IBrowserFormNG.

    Replace the SimpleInputWidget._getFormInput method with one using
    `IBrowserFormNG`.
    """

    installed = False

    @classmethod
    def install(cls):
        """Install the monkey patch."""
        assert not cls.installed, "Monkey patch is already installed."
        def _getFormInput_single(self):
            """Return the submitted form value.

            :raises UnexpectedFormData: If more than one value is submitted.
            """
            return self.request.form_ng.getOne(self.name)

        def _getFormInput_multi(self):
            """Return the submitted form values.
            """
            return self.request.form_ng.getAll(self.name)

        # Save the original method and replace it with fixed ones.
        # We don't save MultiDataHelper._getFormInput because it doesn't
        # override the one in SimpleInputWidget.
        cls._original__getFormInput = SimpleInputWidget._getFormInput
        SimpleInputWidget._getFormInput = _getFormInput_single
        MultiDataHelper._getFormInput = _getFormInput_multi
        cls.installed = True

    @classmethod
    def uninstall(cls):
        """Uninstall the monkey patch."""
        assert cls.installed, "Monkey patch is not installed."

        # Restore saved method.
        SimpleInputWidget._getFormInput = cls._original__getFormInput
        del MultiDataHelper._getFormInput
        cls.installed = False


Zope3WidgetsUseIBrowserFormNGMonkeyPatch.install()


class LaunchpadBrowserResponse(NotificationResponse, BrowserResponse):

    # Note that NotificationResponse defines a 'redirect' method which
    # needs to override the 'redirect' method in BrowserResponse
    def __init__(self, header_output=None, http_transaction=None):
        super(LaunchpadBrowserResponse, self).__init__()

    def redirect(self, location, status=None, trusted=True,
                 temporary_if_possible=False):
        """Do a redirect.

        Unlike Zope's BrowserResponse.redirect(), consider all redirects to be
        trusted. Otherwise we'd have to change all callsites that redirect
        from lp.net to vhost.lp.net to pass trusted=True.

        If temporary_if_possible is True, then do a temporary redirect
        if this is a HEAD or GET, otherwise do a 303.

        See RFC 2616.

        The interface doesn't say that redirect returns anything.
        However, Zope's implementation does return the location given.  This
        is largely useless, as it is just the location given which is often
        relative.  So we won't return anything.
        """
        if temporary_if_possible:
            assert status is None, (
                "Do not set 'status' if also setting "
                "'temporary_if_possible'.")
            method = self._request.method
            if method == 'GET' or method == 'HEAD':
                status = 307
            else:
                status = 303
        super(LaunchpadBrowserResponse, self).redirect(
            unicode(location).encode('UTF-8'), status=status, trusted=trusted)


def adaptResponseToSession(response):
    """Adapt LaunchpadBrowserResponse to ISession"""
    return ISession(response._request)


def adaptRequestToResponse(request):
    """Adapt LaunchpadBrowserRequest to LaunchpadBrowserResponse"""
    return request.response


class LaunchpadTestRequest(TestRequest, ErrorReportRequest,
                           LaunchpadBrowserRequestMixin):
    """Mock request for use in unit and functional tests.

    >>> request = LaunchpadTestRequest(SERVER_URL='http://127.0.0.1/foo/bar')

    This class subclasses TestRequest - the standard Mock request object
    used in unit tests

    >>> isinstance(request, TestRequest)
    True

    It provides LaunchpadLayer and adds a mock INotificationRequest
    implementation.

    >>> canonical.launchpad.layers.LaunchpadLayer.providedBy(request)
    True
    >>> INotificationRequest.providedBy(request)
    True
    >>> request.uuid == request.response.uuid
    True
    >>> request.notifications is request.response.notifications
    True

    It also provides the form_ng attribute that is available from
    LaunchpadBrowserRequest.

    >>> from zope.interface.verify import verifyObject
    >>> verifyObject(IBrowserFormNG, request.form_ng)
    True

    It also provides the query_string_params dict that is available from
    LaunchpadBrowserRequest.

    >>> request = LaunchpadTestRequest(SERVER_URL='http://127.0.0.1/foo/bar',
    ...     QUERY_STRING='a=1&b=2&c=3')
    >>> request.charsets = ['utf-8']
    >>> request.query_string_params == {'a': ['1'], 'b': ['2'], 'c': ['3']}
    True

    It also provides the  hooks for popup calendar iframes:

    >>> request.needs_datetimepicker_iframe
    False
    >>> request.needs_datepicker_iframe
    False

    And for JSON and GMap2:

    >>> request.needs_json
    False
    >>> request.needs_gmap2
    False

    """
    implements(INotificationRequest, IBasicLaunchpadRequest, IParticipation,
               canonical.launchpad.layers.LaunchpadLayer)
    # These two attributes satisfy IParticipation.
    principal = None
    interaction = None

    def __init__(self, body_instream=None, environ=None, form=None,
                 skin=None, outstream=None, method='GET', **kw):
        super(LaunchpadTestRequest, self).__init__(
            body_instream=body_instream, environ=environ, form=form,
            skin=skin, outstream=outstream, REQUEST_METHOD=method, **kw)
        self.traversed_objects = []
        self.needs_datepicker_iframe = False
        self.needs_datetimepicker_iframe = False
        self.needs_json = False
        self.needs_gmap2 = False

    @property
    def uuid(self):
        return self.response.uuid

    @property
    def notifications(self):
        """See INotificationRequest."""
        return self.response.notifications

    @property
    def stepstogo(self):
        """See IBasicLaunchpadRequest."""
        return StepsToGo(self)

    def getNearest(self, *some_interfaces):
        """See IBasicLaunchpadRequest."""
        return None, None

    def setInWSGIEnvironment(self, key, value):
        """See IBasicLaunchpadRequest."""
        self._orig_env[key] = value

    def _createResponse(self):
        """As per zope.publisher.browser.BrowserRequest._createResponse"""
        return LaunchpadTestResponse()

    @property
    def form_ng(self):
        """See ILaunchpadBrowserApplicationRequest."""
        return BrowserFormNG(self.form)

    @property
    def query_string_params(self):
        """See ILaunchpadBrowserApplicationRequest."""
        return get_query_string_params(self)

    def setPrincipal(self, principal):
        """See `IPublicationRequest`."""
        self.principal = principal


class LaunchpadTestResponse(LaunchpadBrowserResponse):
    """Mock response for use in unit and functional tests.

    >>> request = LaunchpadTestRequest()
    >>> response = request.response
    >>> isinstance(response, LaunchpadTestResponse)
    True
    >>> INotificationResponse.providedBy(response)
    True

    >>> response.addWarningNotification('Warning Notification')
    >>> request.notifications[0].message
    u'Warning Notification'
    """
    implements(INotificationResponse)

    uuid = 'LaunchpadTestResponse'

    _notifications = None

    @property
    def notifications(self):
        if self._notifications is None:
            self._notifications = NotificationList()
        return self._notifications


class DebugLayerRequestFactory(HTTPPublicationRequestFactory):
    """RequestFactory that sets the DebugLayer on a request."""

    def __call__(self, input_stream, env, output_stream=None):
        """See zope.app.publication.interfaces.IPublicationRequestFactory"""
        assert output_stream is None, 'output_stream is deprecated in Z3.2'

        # Mark the request with the 'canonical.launchpad.layers.debug' layer
        request = HTTPPublicationRequestFactory.__call__(
            self, input_stream, env)
        canonical.launchpad.layers.setFirstLayer(
            request, canonical.launchpad.layers.DebugLayer)
        return request


class LaunchpadAccessLogger(CommonAccessLogger):

    def log(self, task):
        """Receives a completed task and logs it in launchpad log format.

        task IP address
        X_FORWARDED_FOR
        HOST
        datetime task started
        request string  (1st line of request)
        response status
        response bytes written
        number of sql statements
        request duration
        number of ticks during traversal
        number of ticks during publication
        launchpad user id
        launchpad page id
        REFERER
        USER_AGENT

        """
        request_headers = task.request_data.headers
        cgi_env = task.getCGIEnvironment()

        x_forwarded_for = request_headers.get('X_FORWARDED_FOR', '')
        host = request_headers.get('HOST', '')
        start_time = self.log_date_string(task.start_time)
        first_line = task.request_data.first_line
        status = task.status
        bytes_written = task.bytes_written
        userid = cgi_env.get('launchpad.userid', '')
        pageid = cgi_env.get('launchpad.pageid', '')
        sql_statements = cgi_env.get('launchpad.sqlstatements', 0)
        request_duration = cgi_env.get('launchpad.requestduration', 0)
        traversal_ticks = cgi_env.get('launchpad.traversalticks', 0)
        publication_ticks = cgi_env.get('launchpad.publicationticks', 0)
        referer = request_headers.get('REFERER', '')
        user_agent = request_headers.get('USER_AGENT', '')

        log_template = (' - "%s" "%s" [%s] "%s" %s %d %d %s %s '
                        '%s "%s" "%s" "%s" "%s"\n')
        self.output.logRequest(
            task.channel.addr[0],
            log_template % (
                x_forwarded_for,
                host,
                start_time,
                first_line,
                status,
                bytes_written,
                sql_statements,
                request_duration,
                traversal_ticks,
                publication_ticks,
                userid,
                pageid,
                referer,
                user_agent
                )
           )


http = wsgi.ServerType(
    ZServerTracelogServer, # subclass of WSGIHTTPServer
    WSGIPublisherApplication,
    LaunchpadAccessLogger,
    8080,
    True)

pmhttp = wsgi.ServerType(
    PMDBWSGIHTTPServer,
    WSGIPublisherApplication,
    LaunchpadAccessLogger,
    8081,
    True)

debughttp = wsgi.ServerType(
    ZServerTracelogServer, # subclass of WSGIHTTPServer
    WSGIPublisherApplication,
    LaunchpadAccessLogger,
    8082,
    True,
    requestFactory=DebugLayerRequestFactory)

privatexmlrpc = wsgi.ServerType(
    ZServerTracelogServer, # subclass of WSGIHTTPServer
    WSGIPublisherApplication,
    LaunchpadAccessLogger,
    8080,
    True)


# ---- mainsite

class MainLaunchpadPublication(LaunchpadBrowserPublication):
    """The publication used for the main Launchpad site."""

# ---- blueprint

class BlueprintBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.BlueprintLayer)

class BlueprintPublication(LaunchpadBrowserPublication):
    """The publication used for the Blueprint site."""

# ---- code

class CodePublication(LaunchpadBrowserPublication):
    """The publication used for the Code site."""

class CodeBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.CodeLayer)

# ---- translations

class TranslationsPublication(LaunchpadBrowserPublication):
    """The publication used for the Translations site."""

class TranslationsBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.TranslationsLayer)

    def __init__(self, body_instream, environ, response=None):
        super(TranslationsBrowserRequest, self).__init__(
            body_instream, environ, response)
        # Some of the responses from translations vary based on language.
        self.response.setHeader(
            'Vary', 'Cookie, Authorization, Accept-Language')

# ---- bugs

class BugsPublication(LaunchpadBrowserPublication):
    """The publication used for the Bugs site."""

class BugsBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.BugsLayer)

# ---- answers

class AnswersPublication(LaunchpadBrowserPublication):
    """The publication used for the Answers site."""

class AnswersBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.AnswersLayer)

    def __init__(self, body_instream, environ, response=None):
        super(AnswersBrowserRequest, self).__init__(
            body_instream, environ, response)
        # Many of the responses from Answers vary based on language.
        self.response.setHeader(
            'Vary', 'Cookie, Authorization, Accept-Language')


class AccountPrincipalMixin:
    """Mixin for publication that works with person-less accounts."""

    def getPrincipal(self, request):
        """Return the authenticated principal for this request.

        This is only necessary because, unlike in LaunchpadBrowserPublication,
        here we want principals representing personless accounts to be
        returned, so that personless accounts can use our OpenID server.
        """
        auth_utility = getUtility(IPlacelessAuthUtility)
        principal = auth_utility.authenticate(request)
        if principal is None:
            principal = auth_utility.unauthenticatedPrincipal()
            assert principal is not None, "Missing unauthenticated principal."
        return principal


# ---- feeds

class FeedsPublication(LaunchpadBrowserPublication):
    """The publication used for Launchpad feed requests."""

    root_object_interface = IFeedsApplication

    def traverseName(self, request, ob, name):
        """Override traverseName to restrict urls on feeds.launchpad.net.

        Feeds.lp.net should only serve classes that implement the IFeed
        interface or redirect to some other url.
        """
        # LaunchpadImageFolder is imported here to avoid an import loop.
        from canonical.launchpad.browser.launchpad import LaunchpadImageFolder
        result = super(FeedsPublication, self).traverseName(request, ob, name)
        if len(request.stepstogo) == 0:
            # The url has been fully traversed. Now we can check that
            # the result is a feed, an image, or a redirection.
            naked_result = removeSecurityProxy(result)
            if (IFeed.providedBy(result) or
                isinstance(naked_result, LaunchpadImageFolder) or
                getattr(naked_result, 'status', None) == 301):
                return result
            else:
                raise NotFound(self, '', request)
        else:
            # There are still url segments to traverse.
            return result

    def getPrincipal(self, request):
        """For feeds always return the anonymous user."""
        auth_utility = getUtility(IPlacelessAuthUtility)
        return auth_utility.unauthenticatedPrincipal()


class FeedsBrowserRequest(LaunchpadBrowserRequest):
    """Request type for a launchpad feed."""
    implements(canonical.launchpad.layers.FeedsLayer)


# ---- testopenid

class TestOpenIDBrowserRequest(LaunchpadBrowserRequest):
    implements(canonical.launchpad.layers.TestOpenIDLayer)


class TestOpenIDBrowserPublication(LaunchpadBrowserPublication):
    root_object_interface = ITestOpenIDApplication


# ---- web service

class WebServicePublication(WebServicePublicationMixin,
                            LaunchpadBrowserPublication):
    """The publication used for Launchpad web service requests."""

    root_object_interface = IWebServiceApplication

    def getApplication(self, request):
        """See `zope.publisher.interfaces.IPublication`.

        Always use the web service application to serve web service
        resources, no matter what application is normally used to serve
        the underlying objects.
        """
        return getUtility(IWebServiceApplication)

    def getResource(self, request, ob):
        """Return the resource that can publish the object ob.

        This is done at the end of traversal.  If the published object
        supports the ICollection, or IEntry interface we wrap it into the
        appropriate resource.
        """
        if zope_isinstance(ob, RedirectionView):
            # A redirection should be served as is.
            return ob
        else:
            return super(WebServicePublication, self).getResource(request, ob)

    def finishReadOnlyRequest(self, txn):
        """Commit the transaction so that created OAuthNonces are stored."""
        # Transaction commits usually need to be aware of the possibility of
        # a doomed transaction.  We do not expect that this code will
        # encounter doomed transactions.  If it does, this will need to be
        # revisited.
        txn.commit()

    def getPrincipal(self, request):
        """See `LaunchpadBrowserPublication`.

        Web service requests are authenticated using OAuth, except for the
        one made using (presumably) JavaScript on the /api override path.
        """
        # Use the regular HTTP authentication, when the request is not
        # on the API virtual host but comes through the path_override on
        # the other regular virtual hosts.
        request_path = request.get('PATH_INFO', '')
        web_service_config = getUtility(IWebServiceConfiguration)
        if request_path.startswith("/%s" % web_service_config.path_override):
            return super(WebServicePublication, self).getPrincipal(request)

        # Fetch OAuth authorization information from the request.
        form = get_oauth_authorization(request)

        consumer_key = form.get('oauth_consumer_key')
        consumers = getUtility(IOAuthConsumerSet)
        consumer = consumers.getByKey(consumer_key)
        token_key = form.get('oauth_token')
        anonymous_request = (token_key == '')
        if consumer is None:
            if consumer_key is None:
                # Most likely the user is trying to make a totally
                # unauthenticated request.
                raise Unauthorized(
                    'Request is missing an OAuth consumer key.')
            if anonymous_request:
                # This is the first time anyone has tried to make an
                # anonymous request using this consumer
                # name. Dynamically create the consumer.
                #
                # In the normal website this wouldn't be possible
                # because GET requests have their transactions rolled
                # back. But webservice requests always have their
                # transactions committed so that we can keep track of
                # the OAuth nonces and prevent replay attacks.
                consumer = consumers.new(consumer_key, '')
            else:
                # An unknown consumer can never make a non-anonymous
                # request, because access tokens are registered with a
                # specific, known consumer.
                raise Unauthorized('Unknown consumer (%s).' % consumer_key)
        if anonymous_request:
            # Skip the OAuth verification step and let the user access the
            # web service as an unauthenticated user.
            #
            # XXX leonardr 2009-12-15 bug=496964: Ideally we'd be
            # auto-creating a token for the anonymous user the first
            # time, passing it through the OAuth verification step,
            # and using it on all subsequent anonymous requests.
            auth_utility = getUtility(IPlacelessAuthUtility)
            return auth_utility.unauthenticatedPrincipal()
        token = consumer.getAccessToken(token_key)
        if token is None:
            raise Unauthorized('Unknown access token (%s).' % token_key)
        nonce = form.get('oauth_nonce')
        timestamp = form.get('oauth_timestamp')
        try:
            token.checkNonceAndTimestamp(nonce, timestamp)
        except (NonceAlreadyUsed, TimestampOrderingError, ClockSkew), e:
            raise Unauthorized('Invalid nonce/timestamp: %s' % e)
        now = datetime.now(pytz.timezone('UTC'))
        if token.permission == OAuthPermission.UNAUTHORIZED:
            raise Unauthorized('Unauthorized token (%s).' % token.key)
        elif token.date_expires is not None and token.date_expires <= now:
            raise Unauthorized('Expired token (%s).' % token.key)
        elif not check_oauth_signature(request, consumer, token):
            raise Unauthorized('Invalid signature.')
        else:
            # Everything is fine, let's return the principal.
            pass
        principal = getUtility(IPlacelessLoginSource).getPrincipal(
            token.person.account.id, access_level=token.permission,
            scope=token.context)

        return principal


class WebServiceClientRequest(WebServiceRequestTraversal,
                              LaunchpadBrowserRequest):
    """Request type for a resource published through the web service."""
    implements(canonical.launchpad.layers.WebServiceLayer)

    def __init__(self, body_instream, environ, response=None):
        super(WebServiceClientRequest, self).__init__(
            body_instream, environ, response)
        # Web service requests use content negotiation.
        self.response.setHeader('Vary', 'Cookie, Authorization, Accept')

    def getRootURL(self, rootsite):
        """See IBasicLaunchpadRequest."""
        # When browsing the web service, we want URLs to point back at the web
        # service, so we basically ignore rootsite.
        return self.getApplicationURL() + '/'


class WebServiceTestRequest(WebServiceRequestTraversal, LaunchpadTestRequest):
    """Test request for the webservice.

    It provides the WebServiceLayer and supports the getResource()
    web publication hook.
    """
    implements(canonical.launchpad.layers.WebServiceLayer)

    def __init__(self, body_instream=None, environ=None, version=None, **kw):
        test_environ = {
            'SERVER_URL': 'http://api.launchpad.dev',
            'HTTP_HOST': 'api.launchpad.dev',
            }
        if environ is not None:
            test_environ.update(environ)
        super(WebServiceTestRequest, self).__init__(
            body_instream=body_instream, environ=test_environ, **kw)
        if version is None:
            version = getUtility(IWebServiceConfiguration).active_versions[-1]
        self.version = version
        version_marker = getUtility(IWebServiceVersion, name=version)
        alsoProvides(self, version_marker)


# ---- xmlrpc

class PublicXMLRPCPublication(LaunchpadBrowserPublication):
    """The publication used for public XML-RPC requests."""
    def handleException(self, object, request, exc_info, retry_allowed=True):
        LaunchpadBrowserPublication.handleException(
                self, object, request, exc_info, retry_allowed
                )
        OpStats.stats['xml-rpc faults'] += 1

    def endRequest(self, request, object):
        OpStats.stats['xml-rpc requests'] += 1
        return LaunchpadBrowserPublication.endRequest(self, request, object)


class PublicXMLRPCRequest(BasicLaunchpadRequest, XMLRPCRequest,
                          ErrorReportRequest, LaunchpadBrowserRequestMixin):
    """Request type for doing public XML-RPC in Launchpad."""

    def _createResponse(self):
        return PublicXMLRPCResponse()


class PublicXMLRPCResponse(XMLRPCResponse):
    """Response type for doing public XML-RPC in Launchpad."""

    def handleException(self, exc_info):
        # If we don't have a proper xmlrpclib.Fault, and we have
        # logged an OOPS, create a Fault that reports the OOPS ID to
        # the user.
        exc_value = exc_info[1]
        if not isinstance(exc_value, xmlrpclib.Fault):
            request = get_current_browser_request()
            if request is not None and request.oopsid is not None:
                exc_info = (xmlrpclib.Fault,
                            xmlrpclib.Fault(-1, request.oopsid),
                            None)
        XMLRPCResponse.handleException(self, exc_info)


class PrivateXMLRPCPublication(PublicXMLRPCPublication):
    """The publication used for private XML-RPC requests."""

    root_object_interface = IPrivateApplication

    def traverseName(self, request, ob, name):
        """Traverse to an end point or let normal traversal do its thing."""
        assert isinstance(request, PrivateXMLRPCRequest), (
            'Not a private XML-RPC request')
        missing = object()
        end_point = getattr(ob, name, missing)
        if end_point is missing:
            return super(PrivateXMLRPCPublication, self).traverseName(
                request, ob, name)
        return end_point


class PrivateXMLRPCRequest(PublicXMLRPCRequest):
    """Request type for doing private XML-RPC in Launchpad."""
    # For now, the same as public requests.


# ---- Protocol errors

class ProtocolErrorRequest(LaunchpadBrowserRequest):
    """An HTTP request that happened to result in an HTTP error."""

    def traverse(self, object):
        """It's already been determined that there's an error. Return None."""
        return None


class ProtocolErrorPublicationFactory:
    """This class publishes error messages in response to protocol errors."""

    def __init__(self, status, headers=None):
        """Store the headers and status for turning into a parameterized
        publication.
        """
        if not headers:
            headers = {}
        self.status = status
        self.headers = headers

    def __call__(self, db):
        """Create a parameterized publication object."""
        return ProtocolErrorPublication(self.status, self.headers)


class ProtocolErrorPublication(LaunchpadBrowserPublication):
    """Publication used for requests that turn out to be protocol errors."""

    def __init__(self, status, headers):
        """Prepare to construct a ProtocolErrorException

        :param status: The HTTP status to send
        :param headers: Any HTTP headers that should be sent.
        """
        super(ProtocolErrorPublication, self).__init__(None)
        self.status = status
        self.headers = headers

    def callObject(self, request, object):
        """Raise an approprate exception for this protocol error."""
        if self.status == 404:
            raise NotFound(self, '', request)
        else:
            raise ProtocolErrorException(self.status, self.headers)


class ProtocolErrorException(Exception):
    """An exception for requests that turn out to be protocol errors."""
    implements(ILaunchpadProtocolError)

    def __init__(self, status, headers):
        """Store status and headers for rendering in the HTTP response."""
        Exception.__init__(self)
        self.status = status
        self.headers = headers

    def __str__(self):
        """A protocol error can be well-represented by its HTTP status code.
        """
        return "Protocol error: %s" % self.status


def launchpad_default_timeout():
    """Return the time before the request should be expired."""
    timeout = config.database.db_statement_timeout
    if timeout is None:
        return None
    left = timeout - get_request_duration()
    if left < 0:
        raise RequestExpired('request expired.')
    return left


def set_launchpad_default_timeout(event):
    """Set the LAZR default timeout function."""
    set_default_timeout_function(launchpad_default_timeout)


def register_launchpad_request_publication_factories():
    """Register our factories with the Zope3 publisher.

    DEATH TO ZCML!
    """
    VHRP = VirtualHostRequestPublicationFactory
    VWSHRP = VHostWebServiceRequestPublicationFactory

    factories = [
        VWSHRP('mainsite', LaunchpadBrowserRequest, MainLaunchpadPublication,
               handle_default_host=True),
        VWSHRP('blueprints', BlueprintBrowserRequest, BlueprintPublication),
        VWSHRP('code', CodeBrowserRequest, CodePublication),
        VWSHRP('translations', TranslationsBrowserRequest,
               TranslationsPublication),
        VWSHRP('bugs', BugsBrowserRequest, BugsPublication),
        VWSHRP('answers', AnswersBrowserRequest, AnswersPublication),
        VHRP('feeds', FeedsBrowserRequest, FeedsPublication),
        WebServiceRequestPublicationFactory(
            'api', WebServiceClientRequest, WebServicePublication),
        XMLRPCRequestPublicationFactory(
            'xmlrpc', PublicXMLRPCRequest, PublicXMLRPCPublication)
        ]

    if config.launchpad.enable_test_openid_provider:
        factories.append(VHRP('testopenid', TestOpenIDBrowserRequest,
                              TestOpenIDBrowserPublication))

    # We may also have a private XML-RPC server.
    private_port = None
    for server in config.servers:
        if server.type == 'PrivateXMLRPC':
            ip, private_port = server.address
            break

    if private_port is not None:
        factories.append(XMLRPCRequestPublicationFactory(
            'xmlrpc_private', PrivateXMLRPCRequest,
            PrivateXMLRPCPublication, port=private_port))

    # Register those factories, in priority order corresponding to
    # their order in the list. This means picking a large number for
    # the first factory and giving each subsequent factory the next
    # lower number. We need to leave one space left over for the
    # catch-all handler defined below, so we start at
    # len(factories)+1.
    for priority, factory in enumerate(factories):
        publisher_factory_registry.register(
            "*", "*", factory.vhost_name, len(factories)-priority+1, factory)

    # Register a catch-all "not found" handler at the lowest priority.
    publisher_factory_registry.register(
        "*", "*", "*", 0, NotFoundRequestPublicationFactory())

register_launchpad_request_publication_factories()
