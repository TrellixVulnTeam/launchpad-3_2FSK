# Copyright 2006 Canonical Ltd.  All rights reserved.
"""distributionmirror-prober tests."""

__metaclass__ = type


import httplib
import logging
import os
from StringIO import StringIO
from unittest import TestCase, TestLoader

from twisted.internet import reactor, defer
from twisted.python.failure import Failure
from twisted.web import server

from sqlobject import SQLObjectNotFound

import canonical
from canonical.config import config
from canonical.lp.dbschema import PackagePublishingPocket
from canonical.launchpad.webapp.uri import URI
from canonical.launchpad.daemons.tachandler import TacTestSetup
from canonical.launchpad.database import DistributionMirror, DistroSeries
from canonical.launchpad.ftests.harness import LaunchpadZopelessTestCase
from canonical.tests.test_twisted import TwistedTestCase
from canonical.launchpad.scripts import distributionmirror_prober
from canonical.launchpad.scripts.distributionmirror_prober import (
    ProberFactory, ArchiveMirrorProberCallbacks, BadResponseCode,
    MirrorCDImageProberCallbacks, ProberTimeout, RedirectAwareProberFactory,
    InfiniteLoopDetected, UnknownURLScheme, MAX_REDIRECTS, ConnectionSkipped,
    RedirectAwareProberProtocol, probe_archive_mirror, probe_cdimage_mirror,
    should_skip_host, PER_HOST_REQUESTS, MIN_REQUEST_TIMEOUT_RATIO,
    MIN_REQUESTS_TO_CONSIDER_RATIO, _build_request_for_cdimage_file_list,
    restore_http_proxy, MultiLock, OVERALL_REQUESTS)
from canonical.launchpad.scripts.ftests.distributionmirror_http_server import (
    DistributionMirrorTestHTTPServer)


class HTTPServerTestSetup(TacTestSetup):

    def setUpRoot(self):
        pass

    @property
    def root(self):
        return '/var/tmp'

    @property
    def tacfile(self):
        return os.path.abspath(os.path.join(
            os.path.dirname(canonical.__file__), os.pardir, os.pardir,
            'daemons/distributionmirror_http_server.tac'
            ))

    @property
    def pidfile(self):
        return os.path.join(self.root, 'distributionmirror_http_server.pid')

    @property
    def logfile(self):
        return os.path.join(self.root, 'distributionmirror_http_server.log')


class TestProberProtocolAndFactory(TwistedTestCase):

    def setUp(self):
        self.orig_proxy = os.getenv('http_proxy')
        root = DistributionMirrorTestHTTPServer()
        site = server.Site(root)
        site.displayTracebacks = False
        self.listening_port = reactor.listenTCP(0, site)
        self.port = self.listening_port.getHost().port
        self.urls = {'timeout': u'http://localhost:%s/timeout' % self.port,
                     '200': u'http://localhost:%s/valid-mirror' % self.port,
                     '500': u'http://localhost:%s/error' % self.port,
                     '404': u'http://localhost:%s/invalid-mirror' % self.port}

    def tearDown(self):
        restore_http_proxy(self.orig_proxy)
        return self.listening_port.stopListening()

    def _createProberAndProbe(self, url):
        prober = ProberFactory(url)
        return prober.probe()

    def test_environment_http_proxy_is_handled_correctly(self):
        os.environ['http_proxy'] = 'http://squid.internal:3128'
        prober = ProberFactory(self.urls['200'])
        self.failUnlessEqual(prober.request_host, 'localhost')
        self.failUnlessEqual(prober.request_port, self.port)
        self.failUnlessEqual(prober.request_path, '/valid-mirror')
        self.failUnlessEqual(prober.connect_host, 'squid.internal')
        self.failUnlessEqual(prober.connect_port, 3128)
        self.failUnlessEqual(prober.connect_path, self.urls['200'])

    def _test_connect_to_host(self, url, host):
        """Check that a ProberFactory created with the given url will actually
        connect to the given host.
        """
        prober = ProberFactory(url)
        def fakeConnect(host, port, factory):
            factory.connecting_to = host
            factory.succeeded('200')
        prober.connecting_to = None
        orig_connect = reactor.connectTCP
        reactor.connectTCP = fakeConnect
        def restore_connect(result, orig_connect):
            self.failUnlessEqual(prober.connecting_to, host)
            reactor.connectTCP = orig_connect
            return None
        deferred = prober.probe()
        return deferred.addCallback(restore_connect, orig_connect)

    def test_connect_to_proxy_when_http_proxy_exists(self):
        os.environ['http_proxy'] = 'http://squid.internal:3128'
        self._test_connect_to_host(self.urls['200'], 'squid.internal')

    def test_connect_to_host_when_http_proxy_does_not_exist(self):
        try:
            del os.environ['http_proxy']
        except KeyError:
            pass
        self._test_connect_to_host(self.urls['200'], 'localhost')

    def test_probe_sets_up_timeout_call(self):
        prober = ProberFactory(self.urls['200'])
        self.failUnless(getattr(prober, 'timeoutCall', None) is None)
        deferred = prober.probe()
        self.failUnless(getattr(prober, 'timeoutCall', None) is not None)
        return deferred

    def test_redirectawareprober_follows_http_redirect(self):
        url = 'http://localhost:%s/redirect-to-valid-mirror' % self.port
        prober = RedirectAwareProberFactory(url)
        self.failUnless(prober.redirection_count == 0)
        self.failUnless(prober.url == url)
        deferred = prober.probe()
        def got_result(result):
            self.failUnless(prober.redirection_count == 1)
            self.failUnless(
                prober.url == 'http://localhost:%s/valid-mirror' % self.port)
            self.failUnless(result == str(httplib.OK))
        return deferred.addCallback(got_result)

    def test_redirectawareprober_detects_infinite_loop(self):
        prober = RedirectAwareProberFactory(
            'http://localhost:%s/redirect-infinite-loop' % self.port)
        deferred = prober.probe()
        return self.assertFailure(deferred, InfiniteLoopDetected)

    def test_redirectawareprober_fail_on_unknown_scheme(self):
        prober = RedirectAwareProberFactory(
            'http://localhost:%s/redirect-unknown-url-scheme' % self.port)
        deferred = prober.probe()
        return self.assertFailure(deferred, UnknownURLScheme)

    def test_200(self):
        d = self._createProberAndProbe(self.urls['200'])
        def got_result(result):
            self.failUnless(
                result == str(httplib.OK),
                "Expected a '200' status but got '%s'" % result)
        return d.addCallback(got_result)

    def test_success_cancel_timeout_call(self):
        prober = ProberFactory(self.urls['200'])
        deferred = prober.probe()
        self.failUnless(prober.timeoutCall.active())
        def check_timeout_call(result):
            self.failIf(prober.timeoutCall.active())
        return deferred.addCallback(check_timeout_call)

    def test_failure_cancel_timeout_call(self):
        prober = ProberFactory(self.urls['500'])
        deferred = prober.probe()
        self.failUnless(prober.timeoutCall.active())
        def check_timeout_call(result):
            self.failIf(prober.timeoutCall.active())
        return deferred.addErrback(check_timeout_call)

    def test_notfound(self):
        d = self._createProberAndProbe(self.urls['404'])
        return self.assertFailure(d, BadResponseCode)

    def test_500(self):
        d = self._createProberAndProbe(self.urls['500'])
        return self.assertFailure(d, BadResponseCode)

    def test_timeout(self):
        d = self._createProberAndProbe(self.urls['timeout'])
        return self.assertFailure(d, ProberTimeout)


class FakeTimeOutCall:
    resetCalled = False

    def reset(self, seconds):
        self.resetCalled = True


class FakeTransport:
    disconnecting = False

    def loseConnection(self):
        self.disconnecting = True

    def write(self, text):
        pass


class FakeFactory(RedirectAwareProberFactory):
    redirectedTo = None

    def redirect(self, url):
        self.redirectedTo = url


class TestProberFactoryRequestTimeoutRatioWithoutTwisted(TestCase):
    """Tests to ensure we stop issuing requests on a given host if the
    requests/timeouts ratio on that host is too low.

    The tests here will stub the prober's connect() method, so that we can
    easily check whether it was called or not without actually issuing any
    connections.
    """

    host = 'foo.bar'

    def setUp(self):
        self.orig_host_requests = dict(distributionmirror_prober.host_requests)
        self.orig_host_timeouts = dict(distributionmirror_prober.host_timeouts)

    def tearDown(self):
        # Restore the globals that our tests fiddle with.
        distributionmirror_prober.host_requests = self.orig_host_requests
        distributionmirror_prober.host_timeouts = self.orig_host_timeouts

    def _createProberStubConnectAndProbe(self, requests, timeouts):
        """Create a ProberFactory object with a URL inside self.host and call
        its probe() method.

        Before the prober.probe() method is called, we stub the connect
        method, because all we want is to check whether that method was called
        or not --we don't want to actually connect.
        """
        def connect():
            prober.connectCalled = True
        distributionmirror_prober.host_requests = {self.host: requests}
        distributionmirror_prober.host_timeouts = {self.host: timeouts}
        prober = ProberFactory('http://%s/baz' % self.host)
        prober.connectCalled = False
        prober.failed = lambda error: None
        prober.connect = connect
        prober.probe()
        return prober

    def test_connect_is_called_if_not_enough_requests(self):
        """Test that only a small ratio is not enough to cause a host to be
        skipped; we also need to have a considerable number of requests.
        """
        requests = MIN_REQUESTS_TO_CONSIDER_RATIO - 1
        timeouts = requests
        prober = self._createProberStubConnectAndProbe(requests, timeouts)
        self.failUnless(prober.connectCalled)
        # Ensure the number of requests and timeouts we're using should
        # _NOT_ cause a given host to be skipped.
        self.failIf(should_skip_host(self.host))

    def test_connect_is_not_called_after_too_many_timeouts(self):
        """If we get a small requests/timeouts ratio on a given host, we'll
        stop issuing requests on that host.
        """
        # If the ratio is small enough and we have a considerable number of
        # requests, we won't issue more connections on that host.
        requests = MIN_REQUESTS_TO_CONSIDER_RATIO
        timeouts = (
            (MIN_REQUESTS_TO_CONSIDER_RATIO / MIN_REQUEST_TIMEOUT_RATIO) + 2)
        prober = self._createProberStubConnectAndProbe(requests, timeouts)
        self.failIf(prober.connectCalled)
        # Ensure the number of requests and timeouts we're using should
        # actually cause a given host to be skipped.
        self.failUnless(should_skip_host(self.host))

    def test_connect_is_called_if_not_many_timeouts(self):
        # If the ratio is not too small we consider it's safe to keep 
        # issuing connections on that host.
        requests = MIN_REQUESTS_TO_CONSIDER_RATIO
        timeouts = (
            (MIN_REQUESTS_TO_CONSIDER_RATIO / MIN_REQUEST_TIMEOUT_RATIO) - 2)
        prober = self._createProberStubConnectAndProbe(requests, timeouts)
        self.failUnless(prober.connectCalled)
        # Ensure the number of requests and timeouts we're using should
        # _NOT_ cause a given host to be skipped.
        self.failIf(should_skip_host(self.host))


class TestProberFactoryRequestTimeoutRatioWithTwisted(TwistedTestCase):
    """Tests to ensure we stop issuing requests on a given host if the
    requests/timeouts ratio on that host is too low.

    The tests here will check that we'll record a timeout whenever we get a
    ProberTimeout from twisted, as well as checking that twisted raises
    ConnectionSkipped when it finds a URL that should not be probed. This
    means that we need a test HTTP server as well as the twisted magic to
    actually connect to the server.
    """

    def setUp(self):
        self.orig_host_requests = dict(distributionmirror_prober.host_requests)
        self.orig_host_timeouts = dict(distributionmirror_prober.host_timeouts)
        distributionmirror_prober.host_requests = {}
        distributionmirror_prober.host_timeouts = {}
        root = DistributionMirrorTestHTTPServer()
        site = server.Site(root)
        site.displayTracebacks = False
        self.listening_port = reactor.listenTCP(0, site)
        self.port = self.listening_port.getHost().port

    def tearDown(self):
        # Restore the globals that our tests fiddle with.
        distributionmirror_prober.host_requests = self.orig_host_requests
        distributionmirror_prober.host_timeouts = self.orig_host_timeouts
        return self.listening_port.stopListening()

    def _createProberAndProbe(self, url):
        prober = ProberFactory(url)
        return prober.probe()

    def test_timeout_is_recorded(self):
        host = 'localhost'
        d = self._createProberAndProbe(
            u'http://%s:%s/timeout' % (host, self.port))
        def got_error(error):
            self.failUnlessEqual(
                {host: 1}, distributionmirror_prober.host_requests)
            self.failUnlessEqual(
                {host: 1}, distributionmirror_prober.host_timeouts)
        return d.addErrback(got_error)

    def test_non_timeout_is_recorded(self):
        host = 'localhost'
        d = self._createProberAndProbe(
            u'http://%s:%s/valid-mirror' % (host, self.port))
        def got_result(result):
            self.failUnlessEqual(
                {host: 1}, distributionmirror_prober.host_requests)
            self.failUnlessEqual(
                {host: 0}, distributionmirror_prober.host_timeouts)
        return d.addCallback(got_result)

    def test_failure_after_too_many_timeouts(self):
        host = 'foo.bar'
        requests = MIN_REQUESTS_TO_CONSIDER_RATIO
        timeouts = (
            (MIN_REQUESTS_TO_CONSIDER_RATIO / MIN_REQUEST_TIMEOUT_RATIO) + 2)
        distributionmirror_prober.host_requests = {host: requests}
        distributionmirror_prober.host_timeouts = {host: timeouts}
        # Ensure the number of requests and timeouts we're using should
        # cause a given host to be skipped.
        self.failUnless(should_skip_host(host))

        d = self._createProberAndProbe(
            u'http://%s:%s/timeout' % (host, self.port))
        return self.assertFailure(d, ConnectionSkipped)

class TestMultiLock(TestCase):

    def test_MultiLock(self):
        host_semaphore = defer.DeferredSemaphore(1)
        overall_semaphore = defer.DeferredSemaphore(1)
        deferred = defer.Deferred()

        # Keep host_semaphore busy.
        host_semaphore.run(lambda: deferred)

        self.multi_acquired = False
        self.multi_acquired2 = False
        multi_sem = MultiLock(host_semaphore, overall_semaphore)
        multi_sem.run(lambda: setattr(self, 'multi_acquired', True))
        multi_sem.run(lambda: setattr(self, 'multi_acquired2', True))
        self.assertFalse(self.multi_acquired)
        self.assertFalse(self.multi_acquired2)

        # Release host_semaphore.
        deferred.callback(None)

        # multi_sem will now have been able to acquire both semaphores, and so
        # it will have run its task.
        self.assertTrue(self.multi_acquired)
        self.assertTrue(self.multi_acquired2)

        # Keep multi_sem busy.
        deferred = defer.Deferred()
        multi_sem.run(lambda: deferred)
        self.multi_acquired = False
        multi_sem.run(lambda: setattr(self, 'multi_acquired', True))
        self.assertFalse(self.multi_acquired)

        # Unblock multi_sem, enabling it to run its task.
        deferred.callback(None)
        self.assertTrue(self.multi_acquired)


class TestRedirectAwareProberFactoryAndProtocol(TestCase):

    def test_redirect_resets_timeout(self):
        prober = RedirectAwareProberFactory('http://foo.bar')
        prober.timeoutCall = FakeTimeOutCall()
        prober.connect = lambda: None
        self.failIf(prober.timeoutCall.resetCalled)
        prober.redirect('http://bar.foo')
        self.failUnless(prober.timeoutCall.resetCalled)

    def _createFactoryAndStubConnectAndTimeoutCall(self):
        prober = RedirectAwareProberFactory('http://foo.bar')
        prober.timeoutCall = FakeTimeOutCall()
        prober.connectCalled = False
        def connect():
            prober.connectCalled = True
        prober.connect = connect
        return prober

    def test_connect_depends_on_localhost_only_config(self):
        # If localhost_only is True and the host to which we would connect is
        # not localhost, the connect() method is not called.
        orig_config = config.distributionmirrorprober.localhost_only
        config.distributionmirrorprober.localhost_only = True
        prober = self._createFactoryAndStubConnectAndTimeoutCall()
        self.failUnless(prober.connect_host != 'localhost')
        prober.probe()
        self.failIf(prober.connectCalled)

        # If localhost_only is False, then it doesn't matter the host to which
        # we'll connect to --the connect() method will be called.
        config.distributionmirrorprober.localhost_only = False
        prober = self._createFactoryAndStubConnectAndTimeoutCall()
        prober.probe()
        self.failUnless(prober.connectCalled)
        config.distributionmirrorprober.localhost_only = orig_config

    def test_noconnection_is_made_when_infiniteloop_detected(self):
        prober = self._createFactoryAndStubConnectAndTimeoutCall()
        prober.failed = lambda error: None
        prober.redirection_count = MAX_REDIRECTS
        prober.redirect('http://bar.foo')
        self.failIf(prober.connectCalled)

    def test_noconnection_is_made_when_url_scheme_is_not_http_or_ftp(self):
        prober = self._createFactoryAndStubConnectAndTimeoutCall()
        prober.failed = lambda error: None
        prober.redirect('ssh://bar.foo')
        self.failIf(prober.connectCalled)

    def test_connection_is_made_on_successful_redirect(self):
        prober = self._createFactoryAndStubConnectAndTimeoutCall()
        prober.redirect('http://bar.foo')
        self.failUnless(prober.connectCalled)

    def test_connection_is_closed_on_redirect(self):
        protocol = RedirectAwareProberProtocol()
        protocol.factory = FakeFactory('http://foo.bar/')
        protocol.makeConnection(FakeTransport())
        protocol.dataReceived(
            "HTTP/1.1 301 Moved Permanently\r\n"
            "Location: http://foo.baz/\r\n"
            "Length: 0\r\n"
            "\r\n")
        self.assertEqual('http://foo.baz/', protocol.factory.redirectedTo)
        self.failUnless(protocol.transport.disconnecting)


class TestMirrorCDImageProberCallbacks(LaunchpadZopelessTestCase):
    dbuser = config.distributionmirrorprober.dbuser

    def setUp(self):
        self.logger = logging.getLogger('distributionmirror-prober')
        self.logger.errorCalled = False
        def error(msg):
            self.logger.errorCalled = True
        self.logger.error = error
        mirror = DistributionMirror.get(1)
        warty = DistroSeries.get(1)
        flavour = 'ubuntu'
        log_file = StringIO()
        self.callbacks = MirrorCDImageProberCallbacks(
            mirror, warty, flavour, log_file)

    def test_mirrorcdimageseries_creation_and_deletion(self):
        callbacks = self.callbacks
        all_success = [(defer.SUCCESS, '200'), (defer.SUCCESS, '200')]
        mirror_cdimage_series = callbacks.ensureOrDeleteMirrorCDImageSeries(
             all_success)
        self.failUnless(
            mirror_cdimage_series is not None,
            "If the prober gets a list of 200 Okay statuses, a new "
            "MirrorCDImageSeries should be created.")

        not_all_success = [
            (defer.FAILURE, Failure(BadResponseCode(str(httplib.NOT_FOUND)))),
            (defer.SUCCESS, '200')]
        callbacks.ensureOrDeleteMirrorCDImageSeries(not_all_success)
        # If the prober gets at least one 404 status, we need to make sure
        # there's no MirrorCDImageSeries for that series and flavour.
        self.assertRaises(SQLObjectNotFound, mirror_cdimage_series.sync)

    def test_expected_failures_are_ignored(self):
        # Any errors included in callbacks.expected_failures are simply
        # ignored by ensureOrDeleteMirrorCDImageSeries() because they've been
        # logged by logMissingURL() already and they're expected to happen
        # some times.
        self.failUnlessEqual(
            set(self.callbacks.expected_failures),
            set([BadResponseCode, ProberTimeout, ConnectionSkipped]))
        exceptions = [BadResponseCode(str(httplib.NOT_FOUND)),
                      ProberTimeout('http://localhost/', 5),
                      ConnectionSkipped()]
        for exception in exceptions:
            failure = self.callbacks.ensureOrDeleteMirrorCDImageSeries(
                [(defer.FAILURE, Failure(exception))])
            # Twisted callbacks may raise or return a failure; that's why we
            # check the return value.
            self.failIf(isinstance(failure, Failure))
            # Also, these failures are not logged to stdout/stderr since
            # they're expected to happen.
            self.failIf(self.logger.errorCalled)

    def test_unexpected_failures_are_logged_but_not_raised(self):
        # Errors which are not expected as logged using the
        # prober's logger to make sure people see it while still alowing other
        # mirrors to be probed.
        failure = self.callbacks.ensureOrDeleteMirrorCDImageSeries(
            [(defer.FAILURE, Failure(ZeroDivisionError()))])
        # Twisted callbacks may raise or return a failure; that's why we
        # check the return value.
        self.failIf(isinstance(failure, Failure))
        # Unlike the expected failures, these ones must be logged as errors to
        # stdout/stderr.
        self.failUnless(self.logger.errorCalled)


class TestArchiveMirrorProberCallbacks(LaunchpadZopelessTestCase):

    def setUp(self):
        mirror = DistributionMirror.get(1)
        warty = DistroSeries.get(1)
        pocket = PackagePublishingPocket.RELEASE
        component = warty.components[0]
        log_file = StringIO()
        url = 'foo'
        self.callbacks = ArchiveMirrorProberCallbacks(
            mirror, warty, pocket, component, url, log_file)

    def test_failure_propagation(self):
        # Make sure that deleteMirrorSeries() does not propagate
        # ProberTimeout, BadResponseCode or ConnectionSkipped failures.
        try:
            self.callbacks.deleteMirrorSeries(
                Failure(ProberTimeout('http://localhost/', 5)))
        except Exception, e:
            self.fail("A timeout shouldn't be propagated. Got %s" % e)
        try:
            self.callbacks.deleteMirrorSeries(
                Failure(BadResponseCode(str(httplib.INTERNAL_SERVER_ERROR))))
        except Exception, e:
            self.fail("A bad response code shouldn't be propagated. Got %s" % e)
        try:
            self.callbacks.deleteMirrorSeries(Failure(ConnectionSkipped()))
        except Exception, e:
            self.fail("A ConnectionSkipped exception shouldn't be "
                      "propagated. Got %s" % e)

        # Make sure that deleteMirrorSeries() propagate any failure that is
        # not a ProberTimeout, a BadResponseCode or a ConnectionSkipped.
        d = defer.Deferred()
        d.addErrback(self.callbacks.deleteMirrorSeries)
        def got_result(result):
            self.fail(
                "Any failure that's not a timeout/bad-response/skipped "
                "should be propagated.")
        ok = []
        def got_failure(failure):
            ok.append(1)
        d.addCallbacks(got_result, got_failure)
        d.errback(Failure(ZeroDivisionError()))
        self.assertEqual([1], ok)

    def test_mirrorseries_creation_and_deletion(self):
        mirror_distro_series_source = self.callbacks.ensureMirrorSeries(
             str(httplib.OK))
        self.failUnless(
            mirror_distro_series_source is not None,
            "If the prober gets a 200 Okay status, a new "
            "MirrorDistroSeriesSource/MirrorDistroArchSeries should be "
            "created.")

        self.callbacks.deleteMirrorSeries(
            Failure(BadResponseCode(str(httplib.NOT_FOUND))))
        # If the prober gets a 404 status, we need to make sure there's no
        # MirrorDistroSeriesSource/MirrorDistroArchSeries referent to
        # that url
        self.assertRaises(
            SQLObjectNotFound, mirror_distro_series_source.sync)


class TestProbeFunctionSemaphores(LaunchpadZopelessTestCase):
    """Make sure we use one DeferredSemaphore for each hostname when probing
    mirrors.
    """

    def setUp(self):
        self.logger = None

    def test_MirrorCDImageSeries_records_are_deleted_before_probing(self):
        mirror = DistributionMirror.byName('releases-mirror2')
        self.failUnless(mirror.cdimage_serieses.count() > 0)
        # Note that calling this function won't actually probe any mirrors; we
        # need to call reactor.run() to actually start the probing.
        probe_cdimage_mirror(mirror, StringIO(), [], logging)
        self.failUnlessEqual(mirror.cdimage_serieses.count(), 0)

    def test_archive_mirror_probe_function(self):
        mirror1 = DistributionMirror.byName('archive-mirror')
        mirror2 = DistributionMirror.byName('archive-mirror2')
        mirror3 = DistributionMirror.byName('canonical-archive')
        self._test_one_semaphore_for_each_host(
            mirror1, mirror2, mirror3, probe_archive_mirror)

    def test_cdimage_mirror_probe_function(self):
        mirror1 = DistributionMirror.byName('releases-mirror')
        mirror2 = DistributionMirror.byName('releases-mirror2')
        mirror3 = DistributionMirror.byName('canonical-releases')
        self._test_one_semaphore_for_each_host(
            mirror1, mirror2, mirror3, probe_cdimage_mirror)

    def _test_one_semaphore_for_each_host(
            self, mirror1, mirror2, mirror3, probe_function):
        """Check that we create one semaphore per host when probing the given
        mirrors using the given probe_function.

        mirror1.base_url and mirror2.base_url must be on the same host while
        mirror3.base_url must be on a different one.

        The given probe_function must be either probe_cdimage_mirror or
        probe_archive_mirror.
        """
        host_locks = {}
        mirror1_host = URI(mirror1.base_url).host
        mirror2_host = URI(mirror2.base_url).host
        mirror3_host = URI(mirror3.base_url).host

        probe_function(
            mirror1, StringIO(), [], logging, host_locks=host_locks)
        # Since we have a single mirror to probe we need to have a single
        # DeferredSemaphore with a limit of 1, to ensure we don't issue
        # simultaneous connections on that host.
        self.assertEquals(len(host_locks), 1)
        multi_lock = host_locks[mirror1_host]
        self.assertEquals(multi_lock.host_lock.limit, PER_HOST_REQUESTS)
        # Note that our multi_lock contains another semaphore to control the
        # overall number of requests.
        self.assertEquals(multi_lock.overall_lock.limit, OVERALL_REQUESTS)

        probe_function(
            mirror2, StringIO(), [], logging, host_locks=host_locks)
        # Now we have two mirrors to probe, but they have the same hostname,
        # so we'll still have a single semaphore in host_semaphores.
        self.assertEquals(mirror2_host, mirror1_host)
        self.assertEquals(len(host_locks), 1)
        multi_lock = host_locks[mirror2_host]
        self.assertEquals(multi_lock.host_lock.limit, PER_HOST_REQUESTS)

        probe_function(
            mirror3, StringIO(), [], logging, host_locks=host_locks)
        # This third mirror is on a separate host, so we'll have a second
        # semaphore added to host_semaphores.
        self.failUnless(mirror3_host != mirror1_host)
        self.assertEquals(len(host_locks), 2)
        multi_lock = host_locks[mirror3_host]
        self.assertEquals(multi_lock.host_lock.limit, PER_HOST_REQUESTS)

        # When using an http_proxy, even though we'll actually connect to the
        # proxy, we'll use the mirror's host as the key to find the semaphore
        # that should be used
        orig_proxy = os.getenv('http_proxy')
        os.environ['http_proxy'] = 'http://squid.internal:3128/'
        probe_function(
            mirror3, StringIO(), [], logging, host_locks=host_locks)
        self.assertEquals(len(host_locks), 2)
        restore_http_proxy(orig_proxy)


class TestCDImageFileListFetching(TestCase):

    def test_no_cache(self):
        url = 'http://releases.ubuntu.com/.manifest'
        request = _build_request_for_cdimage_file_list(url)
        self.failUnlessEqual(request.headers['Pragma'], 'no-cache')
        self.failUnlessEqual(request.headers['Cache-control'], 'no-cache')


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
