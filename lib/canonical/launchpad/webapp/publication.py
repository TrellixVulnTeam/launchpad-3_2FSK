# (c) Canonical Ltd. 2004-2006, all rights reserved.

__metaclass__ = type

import gc
import os
from datetime import datetime
import thread
import threading
from time import strftime
import traceback
import urllib

from cProfile import Profile

import tickcount

from psycopg2.extensions import TransactionRollbackError
from storm.exceptions import DisconnectionError, IntegrityError
from storm.zope.interfaces import IZStorm
import transaction

from zope.app import zapi  # used to get at the adapters service
import zope.app.publication.browser
from zope.app.publication.interfaces import BeforeTraverseEvent
from zope.app.security.interfaces import IUnauthenticatedPrincipal
from zope.component import getUtility, queryView
from zope.event import notify
from zope.interface import implements, providedBy

from zope.publisher.interfaces import IPublishTraverse, Retry
from zope.publisher.interfaces.browser import IDefaultSkin, IBrowserRequest
from zope.publisher.publish import mapply

from zope.security.proxy import removeSecurityProxy
from zope.security.management import newInteraction

from canonical.config import config
from canonical.mem import (
    countsByType, deltaCounts, memory, mostRefs, printCounts, readCounts,
    resident)
from canonical.launchpad.webapp.interfaces import (
    ILaunchpadRoot, IOpenLaunchBag, OffsiteFormPostError)
import canonical.launchpad.layers as layers
import canonical.launchpad.webapp.adapter as da
from canonical.launchpad.webapp.interfaces import (
        IDatabasePolicy, IPlacelessAuthUtility)
from canonical.launchpad.webapp.opstats import OpStats
from canonical.launchpad.webapp.uri import URI, InvalidURIError
from canonical.launchpad.webapp.vhosts import allvhosts


__all__ = [
    'LoginRoot',
    'LaunchpadBrowserPublication'
    ]


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
            view = queryView(root_object, name, request)
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

    db_policy = None

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

        self.db_policy = IDatabasePolicy(request)
        self.db_policy.beforeTraversal()

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

    def getPrincipal(self, request):
        """Return the authenticated principal for this request."""
        auth_utility = getUtility(IPlacelessAuthUtility)
        principal = auth_utility.authenticate(request)
        if principal is None:
            principal = auth_utility.unauthenticatedPrincipal()
            assert principal is not None, "Missing unauthenticated principal."
        return principal

    def maybeRestrictToTeam(self, request):

        from canonical.launchpad.interfaces import (
            IPersonSet, IPerson, ITeam, ILaunchpadCelebrities)
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
          1. the request method is POST
          2. the HTTP referer header is not empty
          3. the host portion of the referrer is not a registered vhost
        """
        if request.method != 'POST':
            return
        # XXX: jamesh 2007-11-23 bug=124421:
        # Allow offsite posts to our OpenID endpoint.  Ideally we'd
        # have a better way of marking this URL as allowing offsite
        # form posts.
        if request['PATH_INFO'] == '/+openid':
            return
        referrer = request.getHeader('referer') # match HTTP spec misspelling
        if not referrer:
            return
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
        context = removeSecurityProxy(
            getattr(view, 'context', None))
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
        if request.method in ['GET', 'HEAD']:
            self.finishReadOnlyRequest(txn)
        else:
            txn.commit()

        # Don't render any content for a HEAD.  This was done
        # by zope.app.publication.browser.BrowserPublication
        if request.method == 'HEAD':
            request.response.setResult('')

    def finishReadOnlyRequest(self, txn):
        """Hook called at the end of a read-only request.

        By default it abort()s the transaction, but subclasses may need to
        commit it instead, so they must overwrite this.
        """
        txn.abort()

    def callTraversalHooks(self, request, ob):
        """ We don't want to call _maybePlacefullyAuthenticate as does
        zopepublication """
        notify(BeforeTraverseEvent(ob, request))

    def afterTraversal(self, request, ob):
        """ We don't want to call _maybePlacefullyAuthenticate as does
        zopepublication."""
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

        # Reraise Retry exceptions rather than log.
        if retry_allowed and isinstance(
            exc_info[1], (Retry, DisconnectionError, IntegrityError,
                          TransactionRollbackError)):
            if request.supportsRetry():
                # Remove variables used for counting ticks as this request is
                # going to be retried.
                orig_env.pop('launchpad.traversalticks', None)
                orig_env.pop('launchpad.publicationticks', None)
            if isinstance(exc_info[1], Retry):
                raise
            raise Retry(exc_info)
        superclass = zope.app.publication.browser.BrowserPublication
        superclass.handleException(self, object, request, exc_info,
                                   retry_allowed)
        # If it's a HEAD request, we don't care about the body, regardless of
        # exception.
        # UPSTREAM: Should this be part of zope,
        #           or is it only required because of our customisations?
        #        - Andrew Bennetts, 2005-03-08
        if request.method == 'HEAD':
            request.response.setResult('')

    def endRequest(self, request, object):
        superclass = zope.app.publication.browser.BrowserPublication
        superclass.endRequest(self, request, object)

        self.endProfilingHook(request)

        da.clear_request_started()

        if self.db_policy is not None:
            self.db_policy.endRequest()
            self.db_policy = None

        if config.debug.references:
            self.debugReferencesLeak(request)

        # Maintain operational statistics.
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
            OpStats.stats[str(status)[0] + 'XXs'] += 1

        # Reset all Storm stores when not running the test suite. We could
        # reset them when running the test suite but that'd make writing tests
        # a much more painful task. We still reset the slave stores though
        # to minimize stale cache issues.
        thread_name = threading.currentThread().getName()
        for name, store in getUtility(IZStorm).iterstores():
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

            if oopsid:
                oopsid_part = '-%s' % oopsid
            else:
                oopsid_part = ''
            filename = '%s-%s%s-%s.prof' % (
                timestamp, pageid, oopsid_part,
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

    def debugReferencesLeak(self, request):
        """See what kind of references are increasing.

        This logs the current RSS and references count by types in a
        scoreboard file. If that file exists, we compare the current stats
        with the previous one and logs the increase along the current page id.

        Note that this only provides reliable results when only one thread is
        processing requests.
        """
        gc.collect()
        current_rss = resident()
        current_garbage_count = len(gc.garbage)
        # Convert type to string, because that's what we get when reading
        # the old scoreboard.
        current_refs = [
            (count, str(ref_type)) for count, ref_type in mostRefs(n=0)]
        # Add G as prefix to types on the garbage list.
        current_garbage = [
            (count, 'G%s' % str(ref_type))
            for count, ref_type in countsByType(gc.garbage, n=0)]
        scoreboard_path = config.debug.references_scoreboard_file

        # Read in previous scoreboard if it exists.
        if os.path.exists(scoreboard_path):
            scoreboard = open(scoreboard_path, 'r')
            try:
                stats = scoreboard.readline().split()
                prev_rss = int(stats[0].strip())
                prev_garbage_count = int(stats[1].strip())
                prev_refs = readCounts(scoreboard, '=== GARBAGE ===\n')
                prev_garbage = readCounts(scoreboard)
            finally:
                scoreboard.close()
            mem_leak = current_rss - prev_rss
            garbage_leak = current_garbage_count - prev_garbage_count
            delta_refs = list(deltaCounts(prev_refs, current_refs))
            delta_refs.extend(deltaCounts(prev_garbage, current_garbage))
            self.logReferencesLeak(request, mem_leak, delta_refs)

        # Save the current scoreboard.
        scoreboard = open(scoreboard_path, 'w')
        try:
            scoreboard.write("%d %d\n" % (current_rss, current_garbage_count))
            printCounts(current_refs, scoreboard)
            scoreboard.write('=== GARBAGE ===\n')
            printCounts(current_garbage, scoreboard)
        finally:
            scoreboard.close()

    def logReferencesLeak(self, request, mem_leak, delta_refs):
        """Log the time, pageid, increase in RSS and increase in references.
        """
        log = open(config.debug.references_leak_log, 'a')
        try:
            pageid = request._orig_env.get('launchpad.pageid', 'Unknown')
            # It can happen that the pageid is ''?!?
            if pageid == '':
                pageid = 'Unknown'
            leak_in_mb = float(mem_leak) / (1024*1024)
            formatted_delta = "; ".join(
                "%s=%d" % (ref_type, count)
                for count, ref_type in delta_refs)
            log.write('%s %s %.2fMb %s\n' % (
                strftime('%Y-%m-%d:%H:%M:%S'),
                pageid,
                leak_in_mb,
                formatted_delta))
        finally:
            log.close()


class InvalidThreadsConfiguration(Exception):
    """Exception thrown when the number of threads isn't set correctly."""


def debug_references_startup_check(event):
    """Event handler for IProcessStartingEvent.

    If debug/references is set to True, we make sure that the number of
    threads is configured to 1. We also delete any previous scoreboard file.
    """
    if not config.debug.references:
        return

    if config.threads != 1:
        raise InvalidThreadsConfiguration(
            "Number of threads should be one when debugging references.")

    # Remove any previous scoreboard, the content is meaningless once
    # the server is restarted.
    if os.path.exists(config.debug.references_scoreboard_file):
        os.remove(config.debug.references_scoreboard_file)

