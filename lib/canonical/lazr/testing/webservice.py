# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Testing helpers for webservice unit tests."""

__metaclass__ = type
__all__ = [
    'FakeRequest',
    'FakeResponse',
    'pprint_entry',
    ]

from zope.interface import implements
from zope.publisher.interfaces.http import IHTTPApplicationRequest

from canonical.lazr.interfaces.rest import WebServiceLayer


class FakeResponse(object):
    """Simple response wrapper object."""
    def __init__(self):
        self.status = 599
        self.headers = {}

    def setStatus(self, new_status):
        self.status = new_status

    def setHeader(self, name, value):
        self.headers[name] = value

    def getHeader(self, name):
        """Return the value of the named header."""
        return self.headers.get(name)

    def getStatus(self):
        """Return the response status code."""
        return self.status

class FakeRequest(object):
    """Simple request object for testing purpose."""
    # IHTTPApplicationRequest makes us eligible for
    # get_current_browser_request()
    implements(IHTTPApplicationRequest, WebServiceLayer)

    def __init__(self):
        self.response = FakeResponse()
        self.principal = None
        self.interaction = None

    def getApplicationURL(self):
        return "http://api.example.org"

    def get(self, key, default=None):
        """Simulate an empty set of request parameters."""
        return default


def pprint_entry(json_body):
    """Pretty-print a webservice entry JSON representation."""
    for key, value in sorted(json_body.items()):
        print '%s: %r' % (key, value)

