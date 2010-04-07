# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'LoginRoot',
    'LaunchpadBrowserPublication',
    ]

import os
import re
import sys
import thread
import threading
import traceback
import urllib

from cProfile import Profile
from datetime import datetime

import tickcount
import transaction

from psycopg2.extensions import TransactionRollbackError
from storm.database import STATE_DISCONNECTED
from storm.exceptions import DisconnectionError, IntegrityError
from storm.zope.interfaces import IZStorm

from zc.zservertracelog.interfaces import ITraceLog
import zope.app.publication.browser
from zope.app import zapi  # used to get at the adapters service
from zope.app.publication.interfaces import BeforeTraverseEvent
from zope.app.security.interfaces import IUnauthenticatedPrincipal
from zope.component import getUtility, queryMultiAdapter
from zope.error.interfaces import IErrorReportingUtility
from zope.event import notify
from zope.interface import implements, providedBy
from zope.publisher.interfaces import IPublishTraverse, Retry
from zope.publisher.interfaces.browser import (
    IDefaultSkin, IBrowserRequest)
from zope.publisher.publish import mapply
from zope.security.proxy import removeSecurityProxy
from zope.security.management import newInteraction

import canonical.launchpad.layers as layers
import canonical.launchpad.webapp.adapter as da

from canonical.config import config, dbconfig
from canonical.mem import memory, resident
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.oauth import IOAuthSignedRequest
from canonical.launchpad.readonly import is_read_only
from lp.registry.interfaces.person import (
    IPerson, IPersonSet, ITeam)
from canonical.launchpad.webapp.interfaces import (
    IDatabasePolicy, ILaunchpadRoot, INotificationResponse, IOpenLaunchBag,
    IPlacelessAuthUtility, IPrimaryContext, IStoreSelector, MAIN_STORE,
    MASTER_FLAVOR, OffsiteFormPostError, NoReferrerError, SLAVE_FLAVOR)
from canonical.launchpad.webapp.dbpolicy import (
    DatabaseBlockedPolicy, LaunchpadDatabasePolicy)
from canonical.launchpad.webapp.menu import structured
from canonical.launchpad.webapp.opstats import OpStats
from lazr.uri import URI, InvalidURIError
from canonical.launchpad.webapp.vhosts import allvhosts


METHOD_WRAPPER_TYPE = type({}.__setitem__)


class ProfilingOops(Exception):
    """Fake exception used to log OOPS information when profiling pages."""


class LoginRoot:
    """Object that provides IPublishTraverse to return only itself.

    We anchor the +login view to this object.  This allows other
    special namespaces to be traversed, but doesn't traverse other
    normal names.
    """
    implements(IPublishTraverse)

    def publishTraverse(self, request, name):
        if not request.getTraversalStack():
            root_object = getUtility(ILaunchpadRoot)
            view = queryMultiAdapter((root_object, request), name=name)
            return view
        else:
            return self


class LaunchpadBrowserPublication(
    zope.app.publication.browser.BrowserPublication):
    """Subclass of z.a.publication.BrowserPublication that removes ZODB.

    This subclass undoes the ZODB-specific things in ZopePublication, a
    superclass of z.a.publication.BrowserPublication.
    """
    # This class does not __init__ its parent or specify exception types
    # so that it can replace its parent class.
    # pylint: disable-msg=W0231,W0702

    root_object_interface = ILaunchpadRoot

    def __init__(self, db):
        self.db = db
        self.thread_locals = threading.local()

    def annotateTransaction(self, txn, request, ob):
        """See `zope.app.publication.zopepublication.ZopePublication`.

        We override the method to simply save the authenticated user id
        in the transaction.
        """
        # It is possible that request.principal is None if the principal has
        # not been set yet.
        if request.principal is not None:
            txn.setUser(request.principal.id)

        return txn

    def getDefaultTraversal(self, request, ob):
        superclass = zope.app.publication.browser.BrowserPublication
        return superclass.getDefaultTraversal(self, request, ob)

    def getApplication(self, request):
        end_of_traversal_stack = request.getTraversalStack()[:1]
        if end_of_traversal_stack == ['+login']:
            return LoginRoot()
        else:
            bag = getUtility(IOpenLaunchBag)
            if bag.site is None:
                root_object = getUtility(self.root_object_interface)
                bag.add(root_object)
            else:
                root_object = bag.site
            return root_object

    # The below overrides to zopepublication (callTraversalHooks,
    # afterTraversal, and _maybePlacefullyAuthenticate) make the
    # assumption that there will never be a ZODB "local"
    # authentication service (such as the "pluggable auth service").
    # If this becomes untrue at some point, the code will need to be
    # revisited.

    def beforeTraversal(self, request):
        self.startProfilingHook()
        request._traversalticks_start = tickcount.tickcount()
        threadid = thread.get_ident()
        threadrequestfile = open('thread-%s.request' % threadid, 'w')
        try:
            request_txt = unicode(request).encode('UTF-8')
        except:
            request_txt = 'Exception converting request to string\n\n'
            try:
                request_txt += traceback.format_exc()
            except:
                request_txt += 'Unable to render traceback!'
        threadrequestfile.write(request_txt)
        threadrequestfile.close()

        # Tell our custom database adapter that the request has started.
        da.set_request_started()

        newInteraction(request)

        transaction.begin()

        db_policy = IDatabasePolicy(request)
        if not isinstance(db_policy, DatabaseBlockedPolicy):
            # Database access is not blocked, so make sure our stores point to
            # the appropriate databases, according to the mode we're on.
            main_master_store = getUtility(IStoreSelector).get(
                MAIN_STORE, MASTER_FLAVOR)
            # XXX: 2009-01-12, salgado, bug=506536: We shouldn't need to go
            # through private attributes to get to the store's database.
            dsn = main_master_store._connection._database.dsn_without_user
            if dsn.strip() != dbconfig.main_master.strip():
                # Remove the stores from zstorm to force them to be
                # re-created, thus using the correct databases for the mode
                # we're on right now.
                main_slave_store = getUtility(IStoreSelector).get(
                    MAIN_STORE, SLAVE_FLAVOR)
                zstorm = getUtility(IZStorm)
                for store in [main_master_store, main_slave_store]:
                    zstorm.remove(store)
                    store.close()

        # Now we are logged in, install the correct IDatabasePolicy for
        # this request.
        getUtility(IStoreSelector).push(db_policy)

        getUtility(IOpenLaunchBag).clear()

        # Set the default layer.
        adapters = zapi.getGlobalSiteManager().adapters
        layer = adapters.lookup((providedBy(request),), IDefaultSkin, '')
        if layer is not None:
            layers.setAdditionalLayer(request, layer)

        principal = self.getPrincipal(request)
        request.setPrincipal(principal)
        self.maybeRestrictToTeam(request)
        self.maybeBlockOffsiteFormPost(request)
        self.maybeNotifyReadOnlyMode(request)

    def maybeNotifyReadOnlyMode(self, request):
        """Hook to notify about read-only mode."""
        if is_read_only():
            notification_response = INotificationResponse(request, None)
            if notification_response is not None:
                notification_response.addWarningNotification(
                    structured("""
                        Launchpad is undergoing maintenance and is in
                        read-only mode. <i>You cannot make any
                        changes.</i> Please see the <a
                        href="http://blog.launchpad.net/maintenance">Launchpad
                        Blog</a> for details.
                        """))

    def getPrincipal(self, request):
        """Return the authenticated principal for this request.

        If there is no authenticated principal or the principal represents a
        personless account, return the unauthenticated principal.
        """
        auth_utility = getUtility(IPlacelessAuthUtility)
        principal = auth_utility.authenticate(request)
        if principal is None or principal.person is None:
            # This is either an unauthenticated user or a user who
            # authenticated on our OpenID server using a personless account.
            principal = auth_utility.unauthenticatedPrincipal()
            assert principal is not None, "Missing unauthenticated principal."
        return principal

    def maybeRestrictToTeam(self, request):
        restrict_to_team = config.launchpad.restrict_to_team
        if not restrict_to_team:
            return

        restrictedlogin = '+restricted-login'
        restrictedinfo = '+restricted-info'

        # Always allow access to +restrictedlogin and +restrictedinfo.
        traversal_stack = request.getTraversalStack()
        if (traversal_stack == [restrictedlogin] or
            traversal_stack == [restrictedinfo]):
            return

        principal = request.principal
        team = getUtility(IPersonSet).getByName(restrict_to_team)
        if team is None:
            raise AssertionError(
                'restrict_to_team "%s" not found' % restrict_to_team)
        elif not ITeam.providedBy(team):
            raise AssertionError(
                'restrict_to_team "%s" is not a team' % restrict_to_team)

        if IUnauthenticatedPrincipal.providedBy(principal):
            location = '/%s' % restrictedlogin
        else:
            # We have a team we can work with.
            user = IPerson(principal)
            if (user.inTeam(team) or
                user.inTeam(getUtility(ILaunchpadCelebrities).admin)):
                return
            else:
                location = '/%s' % restrictedinfo

        non_restricted_url = self.getNonRestrictedURL(request)
        if non_restricted_url is not None:
            location += '?production=%s' % urllib.quote(non_restricted_url)

        request.response.setResult('')
        request.response.redirect(location, temporary_if_possible=True)
        # Quash further traversal.
        request.setTraversalStack([])

    def getNonRestrictedURL(self, request):
        """Returns the non-restricted version of the request URL.

        The intended use is for determining the equivalent URL on the
        production Launchpad instance if a user accidentally ends up
        on a restrict_to_team Launchpad instance.

        If a non-restricted URL can not be determined, None is returned.
        """
        base_host = config.vhost.mainsite.hostname
        production_host = config.launchpad.non_restricted_hostname
        # If we don't have a production hostname, or it is the same as
        # this instance, then we can't provide a nonRestricted URL.
        if production_host is None or base_host == production_host:
            return None

        # Are we under the main site's domain?
        uri = URI(request.getURL())
        if not uri.host.endswith(base_host):
            return None

        # Update the hostname, and complete the URL from the request:
        new_host = uri.host[:-len(base_host)] + production_host
        uri = uri.replace(host=new_host, path=request['PATH_INFO'])
        query_string = request.get('QUERY_STRING')
        if query_string:
            uri = uri.replace(query=query_string)
        return str(uri)

    def maybeBlockOffsiteFormPost(self, request):
        """Check if an attempt was made to post a form from a remote site.

        The OffsiteFormPostError exception is raised if the following
        holds true:
          1. the request method is POST *AND*
          2. a. the HTTP referer header is empty *OR*
             b. the host portion of the referrer is not a registered vhost
        """
        if request.method != 'POST':
            return
        # XXX: jamesh 2007-11-23 bug=124421:
        # Allow offsite posts to our TestOpenID endpoint.  Ideally we'd
        # have a better way of marking this URL as allowing offsite
        # form posts.
        if request['PATH_INFO'] == '/+openid':
            return
        if (IOAuthSignedRequest.providedBy(request)
            or not IBrowserRequest.providedBy(request)
            or request['PATH_INFO']  in (
                '/+storeblob', '/+request-token', '/+access-token',
                '/+hwdb/+submit')):
            # We only want to check for the referrer header if we are
            # in the middle of a request initiated by a web browser. A
            # request to the web service (which is necessarily
            # OAuth-signed) or a request that does not implement
            # IBrowserRequest (such as an XML-RPC request) can do
            # without a Referer.
            #
            # XXX gary 2010-03-09 bug=535122,538097
            # The one-off exceptions are necessary because existing
            # non-browser applications make requests to these URLs
            # without providing a Referer. Apport makes POST requests
            # to +storeblob without providing a Referer (bug 538097),
            # and launchpadlib used to make POST requests to
            # +request-token and +access-token without providing a
            # Referer.
            #
            # We'll have to keep an application's one-off exception
            # until the application has been changed to send a
            # Referer, and until we have no legacy versions of that
            # application to support. For instance, we can't get rid
            # of the apport exception until after Lucid's end-of-life
            # date. We should be able to get rid of the launchpadlib
            # exception after Karmic's end-of-life date.
            return
        referrer = request.getHeader('referer') # match HTTP spec misspelling
        if not referrer:
            raise NoReferrerError('No value for REFERER header')
        # XXX: jamesh 2007-04-26 bug=98437:
        # The Zope testing infrastructure sets a default (incorrect)
        # referrer value of "localhost" or "localhost:9000" if no
        # referrer is included in the request.  We let it pass through
        # here for the benefits of the tests.  Web browsers send full
        # URLs so this does not open us up to extra XSRF attacks.
        if referrer in ['localhost', 'localhost:9000']:
            return
        # Extract the hostname from the referrer URI
        try:
            hostname = URI(referrer).host
        except InvalidURIError:
            hostname = None
        if hostname not in allvhosts.hostnames:
            raise OffsiteFormPostError(referrer)

    def callObject(self, request, ob):
        """See `zope.publisher.interfaces.IPublication`.

        Our implementation make sure that no result is returned on
        redirect.

        It also sets the launchpad.userid and launchpad.pageid WSGI
        environment variables.
        """
        request._publicationticks_start = tickcount.tickcount()
        if request.response.getStatus() in [301, 302, 303, 307]:
            return ''

        request.setInWSGIEnvironment(
            'launchpad.userid', request.principal.id)

        # launchpad.pageid contains an identifier of the form
        # ContextName:ViewName. It will end up in the page log.
        view = removeSecurityProxy(ob)
        # It's possible that the view is a bounded method.
        view = getattr(view, 'im_self', view)
        context = removeSecurityProxy(getattr(view, 'context', None))
        if context is None:
            pageid = ''
        else:
            # ZCML registration will set the name under which the view
            # is accessible in the instance __name__ attribute. We use
            # that if it's available, otherwise fall back to the class
            # name.
            if getattr(view, '__name__', None) is not None:
                view_name = view.__name__
            else:
                view_name = view.__class__.__name__
            pageid = '%s:%s' % (context.__class__.__name__, view_name)
        # The view name used in the pageid usually comes from ZCML and so
        # it will be a unicode string although it shouldn't.  To avoid
        # problems we encode it into ASCII.
        request.setInWSGIEnvironment(
            'launchpad.pageid', pageid.encode('ASCII'))

        if isinstance(removeSecurityProxy(ob), METHOD_WRAPPER_TYPE):
            # this is a direct call on a C-defined method such as __repr__ or
            # dict.__setitem__.  Apparently publishing this is possible and
            # acceptable, at least in the case of
            # canonical.launchpad.webapp.servers.PrivateXMLRPCPublication.
            # mapply cannot handle these methods because it cannot introspect
            # them.  We'll just call them directly.
            return ob(*request.getPositionalArguments())

        return mapply(ob, request.getPositionalArguments(), request)

    def afterCall(self, request, ob):
        """See `zope.publisher.interfaces.IPublication`.

        Our implementation calls self.finishReadOnlyRequest(), which by
        default aborts the transaction, for read-only requests.
        Because of this we cannot chain to the superclass and implement
        the whole behaviour here.
        """
        orig_env = request._orig_env
        assert hasattr(request, '_publicationticks_start'), (
            'request._publicationticks_start, which should have been set by '
            'callObject(), was not found.')
        ticks = tickcount.difference(
            request._publicationticks_start, tickcount.tickcount())
        request.setInWSGIEnvironment('launchpad.publicationticks', ticks)
        # Annotate the transaction with user data. That was done by
        # zope.app.publication.zopepublication.ZopePublication.
        txn = transaction.get()
        self.annotateTransaction(txn, request, ob)

        # Abort the transaction on a read-only request.
        # NOTHING AFTER THIS SHOULD CAUSE A RETRY.
        if request.method in ['GET', 'HEAD']:
            self.finishReadOnlyRequest(txn)
        elif txn.isDoomed():
            txn.abort() # Sends an abort to the database, even though
            # transaction is still doomed.
        else:
            txn.commit()

        # Don't render any content for a HEAD.  This was done
        # by zope.app.publication.browser.BrowserPublication
        if request.method == 'HEAD':
            request.response.setResult('')

        try:
            getUtility(IStoreSelector).pop()
        except IndexError:
            # We have to cope with no database policy being installed
            # to allow doc/webapp-publication.txt tests to pass. These
            # tests rely on calling the afterCall hook without first
            # calling beforeTraversal or doing proper cleanup.
            pass

    def finishReadOnlyRequest(self, txn):
        """Hook called at the end of a read-only request.

        By default it abort()s the transaction, but subclasses may need to
        commit it instead, so they must overwrite this.
        """
        txn.abort()

    def callTraversalHooks(self, request, ob):
        """ We don't want to call _maybePlacefullyAuthenticate as does
        zopepublication """
        # In some cases we seem to be called more than once for a given
        # traversed object, so we need to be careful here and only append an
        # object the first time we see it.
        if ob not in request.traversed_objects:
            request.traversed_objects.append(ob)
        notify(BeforeTraverseEvent(ob, request))

    def afterTraversal(self, request, ob):
        """See zope.publisher.interfaces.IPublication.

        This hook does not invoke our parent's afterTraversal hook
        in zopepublication.py because we don't want to call
        _maybePlacefullyAuthenticate.
        """
        # Log the URL including vhost information to the ZServer tracelog.
        tracelog = ITraceLog(request, None)
        if tracelog is not None:
            tracelog.log(request.getURL())

        assert hasattr(request, '_traversalticks_start'), (
            'request._traversalticks_start, which should have been set by '
            'beforeTraversal(), was not found.')
        ticks = tickcount.difference(
            request._traversalticks_start, tickcount.tickcount())
        request.setInWSGIEnvironment('launchpad.traversalticks', ticks)

    def _maybePlacefullyAuthenticate(self, request, ob):
        """ This should never be called because we've excised it in
        favor of dealing with auth in events; if it is called for any
        reason, raise an error """
        raise NotImplementedError

    def handleException(self, object, request, exc_info, retry_allowed=True):
        # Uninstall the database policy.
        store_selector = getUtility(IStoreSelector)
        if store_selector.get_current() is not None:
            db_policy = store_selector.pop()
        else:
            db_policy = None

        orig_env = request._orig_env
        ticks = tickcount.tickcount()
        if (hasattr(request, '_publicationticks_start') and
            not orig_env.has_key('launchpad.publicationticks')):
            # The traversal process has been started but hasn't completed.
            assert orig_env.has_key('launchpad.traversalticks'), (
                'We reached the publication process so we must have finished '
                'the traversal.')
            ticks = tickcount.difference(
                request._publicationticks_start, ticks)
            request.setInWSGIEnvironment('launchpad.publicationticks', ticks)
        elif (hasattr(request, '_traversalticks_start') and
              not orig_env.has_key('launchpad.traversalticks')):
            # The traversal process has been started but hasn't completed.
            ticks = tickcount.difference(
                request._traversalticks_start, ticks)
            request.setInWSGIEnvironment('launchpad.traversalticks', ticks)
        else:
            # The exception wasn't raised in the middle of the traversal nor
            # the publication, so there's nothing we need to do here.
            pass

        # Log a soft OOPS for DisconnectionErrors as per Bug #373837.
        # We need to do this before we re-raise the exception as a Retry.
        if isinstance(exc_info[1], DisconnectionError):
            getUtility(IErrorReportingUtility).handling(exc_info, request)

        def should_retry(exc_info):
            if not retry_allowed:
                return False

            # If we get a LookupError and the default database being
            # used is a replica, raise a Retry exception instead of
            # returning the 404 error page. We do this in case the
            # LookupError is caused by replication lag. Our database
            # policy forces the use of the master database for retries.
            if (isinstance(exc_info[1], LookupError)
                and isinstance(db_policy, LaunchpadDatabasePolicy)):
                if db_policy.default_flavor == MASTER_FLAVOR:
                    return False
                else:
                    return True

            # Retry exceptions need to be propagated so they are
            # retried. Retry exceptions occur when an optimistic
            # transaction failed, such as we detected two transactions
            # attempting to modify the same resource.
            # DisconnectionError and TransactionRollbackError indicate
            # a database transaction failure, and should be retried
            # The appserver detects the error state, and a new database
            # connection is opened allowing the appserver to cope with
            # database or network outages.
            # An IntegrityError may be caused when we insert a row
            # into the database that already exists, such as two requests
            # doing an insert-or-update. It may succeed if we try again.
            if isinstance(exc_info[1], (Retry, DisconnectionError,
                IntegrityError, TransactionRollbackError)):
                return True

            return False

        # Re-raise Retry exceptions ourselves rather than invoke
        # our superclass handleException method, as it will log OOPS
        # reports etc. This would be incorrect, as transaction retry
        # is a normal part of operation.
        if should_retry(exc_info):
            if request.supportsRetry():
                # Remove variables used for counting ticks as this request is
                # going to be retried.
                orig_env.pop('launchpad.traversalticks', None)
                orig_env.pop('launchpad.publicationticks', None)
            # Our endRequest needs to know if a retry is pending or not.
            request._wants_retry = True
            if isinstance(exc_info[1], Retry):
                raise
            raise Retry(exc_info)

        superclass = zope.app.publication.browser.BrowserPublication
        superclass.handleException(
            self, object, request, exc_info, retry_allowed)

        # If it's a HEAD request, we don't care about the body, regardless of
        # exception.
        # UPSTREAM: Should this be part of zope,
        #           or is it only required because of our customisations?
        #        - Andrew Bennetts, 2005-03-08
        if request.method == 'HEAD':
            request.response.setResult('')

    def beginErrorHandlingTransaction(self, request, ob, note):
        """Hook for when a new view is started to handle an exception.

        We need to add an additional behavior to the usual Zope behavior.
        We must restart the request timer.  Otherwise we can get OOPS errors
        from our exception views inappropriately.
        """
        # pylint: disable-msg=E1002
        super(LaunchpadBrowserPublication,
              self).beginErrorHandlingTransaction(request, ob, note)
        # XXX: gary 2008-11-04 bug=293614: As the bug describes, we want to
        # only clear the SQL records and timeout when we are preparing for a
        # view (or a side effect). Otherwise, we don't want to clear the
        # records because they are what the error reporting utility uses to
        # create OOPS reports with the SQL commands that led up to the error.
        # At the moment, we can only distinguish based on the "note" argument:
        # an undocumented argument of this undocumented method.
        if note in ('application error-handling',
                    'application error-handling side-effect'):
            da.clear_request_started()
            da.set_request_started()

    def endRequest(self, request, object):
        superclass = zope.app.publication.browser.BrowserPublication
        superclass.endRequest(self, request, object)

        self.endProfilingHook(request)

        da.clear_request_started()

        # Maintain operational statistics.
        if getattr(request, '_wants_retry', False):
            OpStats.stats['retries'] += 1
        else:
            OpStats.stats['requests'] += 1

            # Increment counters for HTTP status codes we track individually
            # NB. We use IBrowserRequest, as other request types such as
            # IXMLRPCRequest use IHTTPRequest as a superclass.
            # This should be fine as Launchpad only deals with browser
            # and XML-RPC requests.
            if IBrowserRequest.providedBy(request):
                OpStats.stats['http requests'] += 1
                status = request.response.getStatus()
                if status == 404: # Not Found
                    OpStats.stats['404s'] += 1
                elif status == 500: # Unhandled exceptions
                    OpStats.stats['500s'] += 1
                elif status == 503: # Timeouts
                    OpStats.stats['503s'] += 1

                # Increment counters for status code groups.
                status_group = str(status)[0] + 'XXs'
                OpStats.stats[status_group] += 1

                # Increment counter for 5XXs_b.
                if is_browser(request) and status_group == '5XXs':
                    OpStats.stats['5XXs_b'] += 1

        # Make sure our databases are in a sane state for the next request.
        thread_name = threading.currentThread().getName()
        for name, store in getUtility(IZStorm).iterstores():
            try:
                assert store._connection._state != STATE_DISCONNECTED, (
                    "Bug #504291: Store left in a disconnected state.")
            except AssertionError:
                # The Store is in a disconnected state. This should
                # not happen, as store.rollback() should have been called
                # by now. Log an OOPS so we know about this. This
                # is Bug #504291 happening.
                getUtility(IErrorReportingUtility).handling(
                    sys.exc_info(), request)
                # Repair things so the server can remain operational.
                store.rollback()
            # Reset all Storm stores when not running the test suite.
            # We could reset them when running the test suite but
            # that'd make writing tests a much more painful task. We
            # still reset the slave stores though to minimize stale
            # cache issues.
            if thread_name != 'MainThread' or name.endswith('-slave'):
                store.reset()

    def startProfilingHook(self):
        """Handle profiling.

        If requests profiling start a profiler. If memory profiling is
        requested, save the VSS and RSS.
        """
        if config.profiling.profile_requests:
            self.thread_locals.profiler = Profile()
            self.thread_locals.profiler.enable()

        if config.profiling.memory_profile_log:
            self.thread_locals.memory_profile_start = (memory(), resident())

    def endProfilingHook(self, request):
        """If profiling is turned on, save profile data for the request."""
        # Create a timestamp including milliseconds.
        now = datetime.fromtimestamp(da.get_request_start_time())
        timestamp = "%s.%d" % (
            now.strftime('%Y-%m-%d_%H:%M:%S'), int(now.microsecond/1000.0))
        pageid = request._orig_env.get('launchpad.pageid', 'Unknown')
        oopsid = getattr(request, 'oopsid', None)

        if config.profiling.profile_requests:
            profiler = self.thread_locals.profiler
            profiler.disable()

            if oopsid is None:
                # Log an OOPS to get a log of the SQL queries, and other
                # useful information,  together with the profiling
                # information.
                info = (ProfilingOops, None, None)
                error_utility = getUtility(IErrorReportingUtility)
                error_utility.raising(info, request)
                oopsid = request.oopsid
            filename = '%s-%s-%s-%s.prof' % (
                timestamp, pageid, oopsid,
                threading.currentThread().getName())

            profiler.dump_stats(
                os.path.join(config.profiling.profile_dir, filename))

            # Free some memory.
            self.thread_locals.profiler = None

        # Dump memory profiling info.
        if config.profiling.memory_profile_log:
            log = file(config.profiling.memory_profile_log, 'a')
            vss_start, rss_start = self.thread_locals.memory_profile_start
            vss_end, rss_end = memory(), resident()
            if oopsid is None:
                oopsid = '-'
            log.write('%s %s %s %f %d %d %d %d\n' % (
                timestamp, pageid, oopsid, da.get_request_duration(),
                vss_start, rss_start, vss_end, rss_end))
            log.close()


class InvalidThreadsConfiguration(Exception):
    """Exception thrown when the number of threads isn't set correctly."""


class DefaultPrimaryContext:
    """The default primary context is the context."""

    implements(IPrimaryContext)

    def __init__(self, context):
        self.context = context


_browser_re = re.compile(r"""(?x)^(
    Mozilla |
    Opera |
    Lynx |
    Links |
    w3m
    )""")

def is_browser(request):
    """Return True if we believe the request was from a browser.

    There will be false positives and false negatives, as we can
    only tell this from the User-Agent: header and this cannot be
    trusted.

    Almost all web browsers provide a User-Agent: header starting
    with 'Mozilla'. This is good enough for our uses. We also
    add a few other common matches as well for good measure.
    We could massage one of the user-agent databases that are
    available into a usable, but we would gain little.
    """
    user_agent = request.getHeader('User-Agent')
    return (
        user_agent is not None
        and _browser_re.search(user_agent) is not None)
