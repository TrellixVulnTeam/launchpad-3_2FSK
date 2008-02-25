# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Alter the standard functional testing environment for Launchpad."""

from cStringIO import StringIO
import httplib
import logging
import sys
import unittest
import xmlrpclib

from zope.app.testing.functional import (
    FunctionalTestSetup, HTTPCaller)
from zope.security.management import endInteraction, queryInteraction

from zope.testing import doctest
from zope.testing.loggingsupport import Handler

from canonical.config import config
from canonical.chunkydiff import elided_source
from canonical.launchpad.webapp.interaction import (
    get_current_principal, setupInteraction)
from canonical.testing import FunctionalLayer


class NewFunctionalTestSetup(FunctionalTestSetup):
    """Wrap standard FunctionalTestSetup to ensure it is only called
       from tests specifying a valid Layer.
    """
    def __init__(self, *args, **kw):
        from canonical.testing import ZopelessLayer
        assert FunctionalLayer.isSetUp or ZopelessLayer.isSetUp, """
                FunctionalTestSetup invoked at an inappropriate time.
                May only be invoked in the FunctionalLayer or ZopelessLayer
                """
        super(NewFunctionalTestSetup, self).__init__(*args, **kw)
FunctionalTestSetup = NewFunctionalTestSetup


class StdoutWrapper:
    """A wrapper for sys.stdout.  Writes to this file like object will
    write to whatever sys.stdout is pointing to at the time.

    The purpose of this class is to allow doctest to capture log
    messages.  Since doctest replaces sys.stdout, configuring the
    logging module to send messages to sys.stdout before running the
    tests will not result in the output being captured.  Using an
    instance of this class solves the problem.
    """
    def __getattr__(self, attr):
        return getattr(sys.stdout, attr)


class StdoutHandler(Handler):
    def emit(self, record):
        Handler.emit(self, record)
        print >> StdoutWrapper(), '%s:%s:%s' % (
                    record.levelname, record.name, self.format(record)
                    )


def FunctionalDocFileSuite(*paths, **kw):
    globs = kw.setdefault('globs', {})
    globs['http'] = HTTPCaller()

    # Set stdout_logging keyword argument to True to make
    # logging output be sent to stdout, forcing doctests to deal with it.
    stdout_logging = kw.pop('stdout_logging', True)
    stdout_logging_level = kw.pop('stdout_logging_level', logging.INFO)

    # Make sure that paths are resolved relative to our caller
    kw['package'] = doctest._normalize_module(kw.get('package'))

    if 'optionflags' not in kw:
        old = doctest.set_unittest_reportflags(0)
        doctest.set_unittest_reportflags(old)
        kw['optionflags'] = (old
                             | doctest.ELLIPSIS
                             | doctest.REPORT_NDIFF
                             | doctest.NORMALIZE_WHITESPACE)

    kwsetUp = kw.get('setUp')
    def setUp(test):
        if kwsetUp is not None:
            kwsetUp(test)
        if stdout_logging:
            log = StdoutHandler('')
            log.setLoggerLevel(stdout_logging_level)
            log.install()
            test.globs['log'] = log
            # Store as instance attribute so we can uninstall it.
            test._stdout_logger = log
    kw['setUp'] = setUp

    kwtearDown = kw.get('tearDown')
    def tearDown(test):
        if kwtearDown is not None:
            kwtearDown(test)
        if stdout_logging:
            test._stdout_logger.uninstall()
    kw['tearDown'] = tearDown

    layer = kw.pop('layer', FunctionalLayer)
    suite = doctest.DocFileSuite(*paths, **kw)
    suite.layer = layer
    return suite


def PageTestDocFileSuite(*paths, **kw):
    if not kw.get('stdout_logging'):
        kw['stdout_logging'] = False
    # Make sure that paths are resolved relative to our caller
    kw['package'] = doctest._normalize_module(kw.get('package'))
    suite = FunctionalDocFileSuite(*paths, **kw)
    return suite


class SpecialOutputChecker(doctest.OutputChecker):
    def output_difference(self, example, got, optionflags):
        if config.chunkydiff is False:
            return doctest.OutputChecker.output_difference(
                self, example, got, optionflags)

        if optionflags & doctest.ELLIPSIS:
            normalize_whitespace = optionflags & doctest.NORMALIZE_WHITESPACE
            newgot = elided_source(example.want, got,
                                   normalize_whitespace=normalize_whitespace)
            if newgot == example.want:
                # There was no difference.  May be an error in
                # elided_source().  In any case, return the whole thing.
                newgot = got
        else:
            newgot = got
        return doctest.OutputChecker.output_difference(
            self, example, newgot, optionflags)


class HTTPCallerHTTPConnection(httplib.HTTPConnection):
    """A HTTPConnection which talks to HTTPCaller instead of a real server.

    Only the methods called by xmlrpclib are overridden.
    """

    _data_to_send = ''
    _response = None

    def __init__(self, host):
        httplib.HTTPConnection.__init__(self, host)
        self.caller = HTTPCaller()

    def connect(self):
        """No need to connect."""
        pass

    def send(self, data):
        """Send the request to HTTPCaller."""
        # We don't send it to HTTPCaller yet, we store the data and sends
        # everything at once when the client requests a response.
        self._data_to_send += data

    def getresponse(self):
        """Get the response."""
        current_principal = None
        # End and save the current interaction, since HTTPCaller creates
        # its own interaction.
        if queryInteraction():
            current_principal = get_current_principal()
            endInteraction()
        if self._response is None:
            self._response = self.caller(self._data_to_send)
        # Restore the interaction to what it was before.
        setupInteraction(current_principal)
        return self._response

    def getreply(self):
        """Return a tuple of status code, reason string, and headers."""
        response = self.getresponse()
        return (
            response.getStatus(),
            response.getStatusString(),
            response.getHeaders())

    def getfile(self):
        """Get the response body as a file like object."""
        response = self.getresponse()
        return StringIO(response.consumeBody())


class XMLRPCTestTransport(xmlrpclib.Transport):
    """An XMLRPC Transport which sends the requests to HTTPCaller."""

    def make_connection(self, host):
        """Return our custom HTTPCaller HTTPConnection."""
        host, extra_headers, x509 = self.get_host_info(host)
        return HTTPCallerHTTPConnection(host)


if __name__ == '__main__':
    unittest.main()
