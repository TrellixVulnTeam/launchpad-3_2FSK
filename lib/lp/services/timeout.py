# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers to time out external operations."""

__metaclass__ = type
__all__ = [
    "get_default_timeout_function",
    "SafeTransportWithTimeout",
    "set_default_timeout_function",
    "TimeoutError",
    "TransportWithTimeout",
    "urlfetch",
    "with_timeout",
    ]

import socket
import sys
from threading import (
    Lock,
    Thread,
    )
from xmlrpclib import (
    SafeTransport,
    Transport,
    )

from requests import Session
from requests.adapters import (
    DEFAULT_POOLBLOCK,
    HTTPAdapter,
    )
from requests.packages.urllib3.connectionpool import (
    HTTPConnectionPool,
    HTTPSConnectionPool,
    )
from requests.packages.urllib3.exceptions import ClosedPoolError
from requests.packages.urllib3.poolmanager import (
    PoolManager,
    SSL_KEYWORDS,
    )


default_timeout_function = None


def get_default_timeout_function():
    """Return the function returning the default timeout value to use."""
    global default_timeout_function
    return default_timeout_function


def set_default_timeout_function(timeout_function):
    """Change the function returning the default timeout value to use."""
    global default_timeout_function
    default_timeout_function = timeout_function


class TimeoutError(Exception):
    """Exception raised when a function doesn't complete within time."""


class ThreadCapturingResult(Thread):
    """Thread subclass that saves the return value of its target.

    It also saves exceptions raised when invoking the target.
    """

    def __init__(self, target, args, kwargs, **opt):
        super(ThreadCapturingResult, self).__init__(**opt)
        self.target = target
        self.args = args
        self.kwargs = kwargs

    def run(self):
        """See `Thread`."""
        try:
            self.result = self.target(*self.args, **self.kwargs)
        except (SystemExit, KeyboardInterrupt):
            # Don't trap those.
            raise
        except Exception:
            self.exc_info = sys.exc_info()


class DefaultTimeout:
    """Descriptor returning the timeout computed by the default function."""

    def __get__(self, obj, type=None):
        global default_timeout_function
        if default_timeout_function is None:
            raise AssertionError(
                "no timeout set and there is no default timeout function.")
        return default_timeout_function()


class with_timeout:
    """Make sure the decorated function doesn't exceed a time out.

    This will execute the function in a separate thread. If the function
    doesn't complete in the timeout, a TimeoutError is raised. The clean-up
    function will be called to "stop" the thread. (If it's possible to do so.)
    """

    timeout = DefaultTimeout()

    def __init__(self, cleanup=None, timeout=None):
        """Creates the function decorator.

        :param cleanup: That may be a callable or a string. If it's a string,
            a method under that name will be looked up. That callable will
            be called if the timeout is exceeded.
        :param timeout: The number of seconds to wait for.
        """
        # If the cleanup function is specified by name, the function but be a
        # method, so defined in a class definition context.
        if isinstance(cleanup, basestring):
            frame = sys._getframe(1)
            f_locals = frame.f_locals

            # Try to make sure we were called from a class def.
            if f_locals is frame.f_globals or '__module__' not in f_locals:
                raise TypeError(
                    "when not wrapping a method, cleanup must be a callable.")
        self.cleanup = cleanup
        if timeout is not None:
            self.timeout = timeout

    def __call__(self, f):
        """Wraps the method."""
        def call_with_timeout(*args, **kwargs):
            # Ensure that we have a timeout before we start the thread
            timeout = self.timeout
            if getattr(timeout, '__call__', None):
                # timeout may be a method or a function on the calling
                # instance class.
                if args:
                    timeout = timeout(args[0])
                else:
                    timeout = timeout()
            t = ThreadCapturingResult(f, args, kwargs)
            t.start()
            t.join(timeout)
            if t.isAlive():
                if self.cleanup is not None:
                    if isinstance(self.cleanup, basestring):
                        # 'self' will be first positional argument.
                        getattr(args[0], self.cleanup)()
                    else:
                        self.cleanup()
                    # Collect cleaned-up worker thread.
                    t.join()
                raise TimeoutError("timeout exceeded.")
            if getattr(t, 'exc_info', None) is not None:
                exc_info = t.exc_info
                # Remove the cyclic reference for faster GC.
                del t.exc_info
                raise exc_info[0], exc_info[1], exc_info[2]
            return t.result

        return call_with_timeout


class CleanableConnectionPoolMixin:
    """Enhance urllib3's connection pools to support forced socket cleanup."""

    def __init__(self, *args, **kwargs):
        super(CleanableConnectionPoolMixin, self).__init__(*args, **kwargs)
        self._all_connections = []
        self._all_connections_mutex = Lock()

    def _new_conn(self):
        self._all_connections_mutex.acquire()
        try:
            if self._all_connections is None:
                raise ClosedPoolError(self, "Pool is closed.")
            conn = super(CleanableConnectionPoolMixin, self)._new_conn()
            self._all_connections.append(conn)
            return conn
        finally:
            self._all_connections_mutex.release()

    def close(self):
        self._all_connections_mutex.acquire()
        try:
            if self._all_connections is None:
                return
            for conn in self._all_connections:
                sock = getattr(conn, "sock", None)
                if sock is not None:
                    sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                    conn.sock = None
            self._all_connections = None
        finally:
            self._all_connections_mutex.release()
        super(CleanableConnectionPoolMixin, self).close()


class CleanableHTTPConnectionPool(
    CleanableConnectionPoolMixin, HTTPConnectionPool):
    pass


class CleanableHTTPSConnectionPool(
    CleanableConnectionPoolMixin, HTTPSConnectionPool):
    pass


cleanable_pool_classes_by_scheme = {
    "http": CleanableHTTPConnectionPool,
    "https": CleanableHTTPSConnectionPool,
    }


class CleanablePoolManager(PoolManager):
    """A version of urllib3's PoolManager supporting forced socket cleanup."""

    # XXX cjwatson 2015-03-11: Reimplements PoolManager._new_pool; check
    # this when upgrading requests.
    def _new_pool(self, scheme, host, port):
        if scheme not in cleanable_pool_classes_by_scheme:
            raise ValueError("Unhandled scheme: %s" % scheme)
        pool_cls = cleanable_pool_classes_by_scheme[scheme]
        if scheme == 'http':
            kwargs = self.connection_pool_kw.copy()
            for kw in SSL_KEYWORDS:
                kwargs.pop(kw, None)

        return pool_cls(host, port, **kwargs)


class CleanableHTTPAdapter(HTTPAdapter):
    """Enhance HTTPAdapter to use CleanablePoolManager."""

    # XXX cjwatson 2015-03-11: Reimplements HTTPAdapter.init_poolmanager;
    # check this when upgrading requests.
    def init_poolmanager(self, connections, maxsize, block=DEFAULT_POOLBLOCK):
        # save these values for pickling
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block

        self.poolmanager = CleanablePoolManager(
            num_pools=connections, maxsize=maxsize, block=block)


class URLFetcher:
    """Object fetching remote URLs with a time out."""

    @with_timeout(cleanup='cleanup')
    def fetch(self, url, **request_kwargs):
        """Fetch the URL using a custom HTTP handler supporting timeout."""
        request_kwargs.setdefault("method", "GET")
        self.session = Session()
        # Don't honour things like environment proxy configuration.
        self.session.trust_env = False
        # Mount our custom adapters.
        self.session.mount("https://", CleanableHTTPAdapter())
        self.session.mount("http://", CleanableHTTPAdapter())
        return self.session.request(url=url, **request_kwargs).content

    def cleanup(self):
        """Reset the connection when the operation timed out."""
        self.session.close()


def urlfetch(url, **request_kwargs):
    """Wrapper for `requests.get()` that times out."""
    return URLFetcher().fetch(url, **request_kwargs)


class TransportWithTimeout(Transport):
    """Create a HTTP transport for XMLRPC with timeouts."""

    def make_connection(self, host):
        """Create the connection for the transport and save it."""
        self.conn = Transport.make_connection(self, host)
        return self.conn

    @with_timeout(cleanup='cleanup')
    def request(self, host, handler, request_body, verbose=0):
        """Make the request but using the with_timeout decorator."""
        return Transport.request(
            self, host, handler, request_body, verbose)

    def cleanup(self):
        """In the event of a timeout cleanup by closing the connection."""
        try:
            self.conn.sock.shutdown(socket.SHUT_RDWR)
        except AttributeError:
            # It's possible that the other thread closed the socket
            # beforehand.
            pass
        self.conn.close()


class SafeTransportWithTimeout(SafeTransport):
    """Create a HTTPS transport for XMLRPC with timeouts."""

    timeout = None

    def __init__(self, timeout=None):
        # Old style class call to super required.
        SafeTransport.__init__(self)
        self.timeout = timeout

    def make_connection(self, host):
        """Create the connection for the transport and save it."""
        self.conn = SafeTransport.make_connection(self, host)
        return self.conn

    @with_timeout(cleanup='cleanup', timeout=lambda self: self.timeout)
    def request(self, host, handler, request_body, verbose=0):
        """Make the request but using the with_timeout decorator."""
        return SafeTransport.request(
            self, host, handler, request_body, verbose)

    def cleanup(self):
        """In the event of a timeout cleanup by closing the connection."""
        try:
            self.conn._conn.sock.shutdown(socket.SHUT_RDWR)
        except AttributeError:
            # It's possible that the other thread closed the socket
            # beforehand.
            pass
        self.conn._conn.close()
