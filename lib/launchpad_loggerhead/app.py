# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import os
import threading
import urllib
import urlparse
import xmlrpclib

from bzrlib import errors, lru_cache, urlutils
from bzrlib.transport import get_transport

from loggerhead.apps import favicon_app, static_app
from loggerhead.apps.branch import BranchWSGIApp

from openid.extensions.sreg import SRegRequest, SRegResponse
from openid.consumer.consumer import CANCEL, Consumer, FAILURE, SUCCESS
from openid.store.memstore import MemoryStore

from paste.fileapp import DataApp
from paste.request import construct_url, parse_querystring, path_info_pop
from paste.httpexceptions import (
    HTTPMovedPermanently, HTTPNotFound, HTTPUnauthorized)

from canonical.config import config
from canonical.launchpad.xmlrpc import faults
from canonical.launchpad.webapp.vhosts import allvhosts
from lp.code.interfaces.codehosting import (
    BRANCH_TRANSPORT, LAUNCHPAD_ANONYMOUS)
from lp.codehosting.vfs import get_lp_server
from lp.codehosting.bzrutils import safe_open

robots_txt = '''\
User-agent: *
Disallow: /
'''

robots_app = DataApp(robots_txt, content_type='text/plain')


thread_transports = threading.local()


def check_fault(fault, *fault_classes):
    """Check if 'fault's faultCode matches any of 'fault_classes'.

    :param fault: An instance of `xmlrpclib.Fault`.
    :param fault_classes: Any number of `LaunchpadFault` subclasses.
    """
    for cls in fault_classes:
        if fault.faultCode == cls.error_code:
            return True
    return False


class RootApp:

    def __init__(self, session_var):
        self.graph_cache = lru_cache.LRUCache(10)
        self.branchfs = xmlrpclib.ServerProxy(
            config.codehosting.codehosting_endpoint)
        self.session_var = session_var
        self.store = MemoryStore()
        self.log = logging.getLogger('lp-loggerhead')

    def get_transport(self):
        t = getattr(thread_transports, 'transport', None)
        if t is None:
            thread_transports.transport = get_transport(
                config.codehosting.internal_branch_by_id_root)
        return thread_transports.transport

    def _make_consumer(self, environ):
        """Build an OpenID `Consumer` object with standard arguments."""
        return Consumer(environ[self.session_var], self.store)

    def _begin_login(self, environ, start_response):
        """Start the process of authenticating with OpenID.

        We redirect the user to Launchpad to identify themselves, asking to be
        sent their nickname.  Launchpad will then redirect them to our +login
        page with enough information that we can then redirect them again to
        the page they were looking at, with a cookie that gives us the
        username.
        """
        openid_vhost = config.launchpad.openid_provider_vhost
        openid_request = self._make_consumer(environ).begin(
            allvhosts.configs[openid_vhost].rooturl)
        openid_request.addExtension(
            SRegRequest(required=['nickname']))
        back_to = construct_url(environ)
        raise HTTPMovedPermanently(openid_request.redirectURL(
            config.codehosting.secure_codebrowse_root,
            config.codehosting.secure_codebrowse_root + '+login/?'
            + urllib.urlencode({'back_to':back_to})))

    def _complete_login(self, environ, start_response):
        """Complete the OpenID authentication process.

        Here we handle the result of the OpenID process.  If the process
        succeeded, we record the username in the session and redirect the user
        to the page they were trying to view that triggered the login attempt.
        In the various failures cases we return a 401 Unauthorized response
        with a brief explanation of what went wrong.
        """
        query = dict(parse_querystring(environ))
        # Passing query['openid.return_to'] here is massive cheating, but
        # given we control the endpoint who cares.
        response = self._make_consumer(environ).complete(
            query, query['openid.return_to'])
        if response.status == SUCCESS:
            self.log.error('open id response: SUCCESS')
            sreg_info = SRegResponse.fromSuccessResponse(response)
            print sreg_info
            environ[self.session_var]['user'] = sreg_info['nickname']
            raise HTTPMovedPermanently(query['back_to'])
        elif response.status == FAILURE:
            self.log.error('open id response: FAILURE: %s', response.message)
            exc = HTTPUnauthorized()
            exc.explanation = response.message
            raise exc
        elif response.status == CANCEL:
            self.log.error('open id response: CANCEL')
            exc = HTTPUnauthorized()
            exc.explanation = "Authetication cancelled."
            raise exc
        else:
            self.log.error('open id response: UNKNOWN')
            exc = HTTPUnauthorized()
            exc.explanation = "Unknown OpenID response."
            raise exc

    def __call__(self, environ, start_response):
        environ['loggerhead.static.url'] = environ['SCRIPT_NAME']
        if environ['PATH_INFO'].startswith('/static/'):
            path_info_pop(environ)
            return static_app(environ, start_response)
        elif environ['PATH_INFO'] == '/favicon.ico':
            return favicon_app(environ, start_response)
        elif environ['PATH_INFO'] == '/robots.txt':
            return robots_app(environ, start_response)
        elif environ['PATH_INFO'].startswith('/+login'):
            return self._complete_login(environ, start_response)
        path = environ['PATH_INFO']
        trailingSlashCount = len(path) - len(path.rstrip('/'))
        user = environ[self.session_var].get('user', LAUNCHPAD_ANONYMOUS)
        lp_server = get_lp_server(user, branch_transport=self.get_transport())
        lp_server.start_server()
        try:
            try:
                transport_type, info, trail = self.branchfs.translatePath(
                    user, urlutils.escape(path))
            except xmlrpclib.Fault, f:
                if check_fault(f, faults.PathTranslationError):
                    raise HTTPNotFound()
                elif check_fault(f, faults.PermissionDenied):
                    # If we're not allowed to see the branch...
                    if environ['wsgi.url_scheme'] != 'https':
                        # ... the request shouldn't have come in over http, as
                        # requests for private branches over http should be
                        # redirected to https by the dynamic rewrite script we
                        # use (which runs before this code is reached), but
                        # just in case...
                        env_copy = environ.copy()
                        env_copy['wsgi.url_scheme'] = 'https'
                        raise HTTPMovedPermanently(construct_url(env_copy))
                    elif user != LAUNCHPAD_ANONYMOUS:
                        # ... if the user is already logged in and still can't
                        # see the branch, they lose.
                        exc = HTTPUnauthorized()
                        exc.explanation = "You are logged in as %s." % user
                        raise exc
                    else:
                        # ... otherwise, lets give them a chance to log in
                        # with OpenID.
                        return self._begin_login(environ, start_response)
                else:
                    raise
            if transport_type != BRANCH_TRANSPORT:
                raise HTTPNotFound()
            trail = urlutils.unescape(trail).encode('utf-8')
            trail += trailingSlashCount * '/'
            amount_consumed = len(path) - len(trail)
            consumed = path[:amount_consumed]
            branch_name = consumed.strip('/')
            self.log.info('Using branch: %s', branch_name)
            if trail and not trail.startswith('/'):
                trail = '/' + trail
            environ['PATH_INFO'] = trail
            environ['SCRIPT_NAME'] += consumed.rstrip('/')
            branch_url = lp_server.get_url() + branch_name
            branch_link = urlparse.urljoin(
                config.codebrowse.launchpad_root, branch_name)
            cachepath = os.path.join(
                config.codebrowse.cachepath, branch_name[1:])
            if not os.path.isdir(cachepath):
                os.makedirs(cachepath)
            self.log.info('branch_url: %s', branch_url)
            try:
                bzr_branch = safe_open(
                    lp_server.get_url().strip(':/'), branch_url)
            except errors.NotBranchError, err:
                self.log.warning('Not a branch: %s', err)
                raise HTTPNotFound()
            bzr_branch.lock_read()
            try:
                view = BranchWSGIApp(
                    bzr_branch, branch_name, {'cachepath': cachepath},
                    self.graph_cache, branch_link=branch_link, served_url=None)
                return view.app(environ, start_response)
            finally:
                bzr_branch.unlock()
        finally:
            lp_server.stop_server()
