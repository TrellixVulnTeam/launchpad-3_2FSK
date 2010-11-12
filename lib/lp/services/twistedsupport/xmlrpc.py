# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Support for XML-RPC stuff with Twisted."""

__metaclass__ = type
__all__ = [
    'BlockingProxy',
    'DeferredBlockingProxy',
    'trap_fault',
    ]

from twisted.internet import defer
from twisted.web.xmlrpc import (
    Fault,
    _QueryFactory,
    QueryProtocol,
    )


class BlockingProxy:
    """Make an xmlrpclib.ServerProxy behave like a Twisted XML-RPC proxy.

    This is useful for writing code that needs to work in both a synchronous
    and asynchronous fashion.

    Also, some people prefer the callRemote style of invocation, which is more
    explicit.
    """

    def __init__(self, proxy):
        """Construct a `BlockingProxy`.

        :param proxy: An xmlrpclib.ServerProxy.
        """
        self._proxy = proxy

    def callRemote(self, method_name, *args, **kwargs):
        return getattr(self._proxy, method_name)(*args, **kwargs)


class DeferredBlockingProxy(BlockingProxy):
    """Make an xmlrpclib.ServerProxy behave more like a Twisted XML-RPC proxy.

    This is almost exactly like 'BlockingProxy', except that this returns
    Deferreds. It is guaranteed to be exactly as synchronous as the passed-in
    proxy. That means if you pass in a normal xmlrpclib proxy you ought to be
    able to use `lp.services.twistedsupport.extract_result` to get the result.
    """

    def callRemote(self, method_name, *args, **kwargs):
        return defer.maybeDeferred(
            super(DeferredBlockingProxy, self).callRemote,
            method_name, *args, **kwargs)


class DisconnectingQueryProtocol(QueryProtocol):

    def connectionMade(self):
        self._response = None
        QueryProtocol.connectionMade(self)

    def handleResponse(self, contents):
        self.transport.loseConnection()
        self._response = contents

    def connectionLost(self, reason):
        QueryProtocol.connectionLost(reason)
        if self._response is not None:
            response, self._response = self._response, None
            self.factory.parseResponse(response)


def fix_bug_2518():
    # XXX: See http://twistedmatrix.com/trac/ticket/2518.
    _QueryFactory.protocol = DisconnectingQueryProtocol


def trap_fault(failure, *fault_classes):
    """Trap a fault, based on fault code.

    :param failure: A Twisted L{Failure}.
    :param *fault_codes: `LaunchpadFault` subclasses.
    :raise Failure: if 'failure' is not a Fault failure, or if the fault code
        does not match the given codes.
    :return: The Fault if it matches one of the codes.
    """
    failure.trap(Fault)
    fault = failure.value
    if fault.faultCode in [cls.error_code for cls in fault_classes]:
        return fault
    raise failure
