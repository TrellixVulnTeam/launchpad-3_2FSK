# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Helpers for OpenID page tests."""

__metaclass__ = type
__all__ = [
    'ConsumerView',
    'PublisherFetcher',
    'complete_from_browser',
    'make_endpoint',
    'make_identifier_select_endpoint',
]

from StringIO import StringIO
import urllib2

from openid import fetchers
from openid.consumer.discover import (
    OpenIDServiceEndpoint, OPENID_1_0_TYPE, OPENID_1_1_TYPE,
    OPENID_2_0_TYPE, OPENID_IDP_2_0_TYPE)
from openid.message import IDENTIFIER_SELECT

from canonical.launchpad.webapp import LaunchpadView
from canonical.launchpad.webapp.vhosts import allvhosts


class ConsumerView(LaunchpadView):
    """Register a view that renders the parameters in the response
    in an easily testable format.
    """
    def render(self):
        out = StringIO()
        print >> out, 'Consumer received %s' % self.request.method
        keys = sorted(self.request.form.keys())
        for key in keys:
            print >> out, '%s:%s' % (key, self.request.form[key])
        return out.getvalue()


class PublisherFetcher(fetchers.Urllib2Fetcher):
    """An `HTTPFetcher` that passes requests on to the Zope publisher."""
    def __init__(self):
        super(PublisherFetcher, self).__init__()
        # This module does "from test import pystone".  Doing this
        # import earlier causes "make run" to fail due to test.py
        # shadowing the package.
        from zope.testbrowser.testing import PublisherHTTPHandler
        self.opener = urllib2.build_opener(PublisherHTTPHandler)

    def urlopen(self, request):
        request.add_header('X-zope-handle-errors', True)
        return self.opener.open(request)


def get_requested_server_url(url='http://openid.launchpad.dev/'):
    """Return the OpenID Server URL."""
    vhost, ignored = url[len('http://'):].split('.', 1)
    if vhost not in ('id', 'openid'):
        # The claimed URL is not on Launchpad, fallback to the beta rules.
        vhost = 'openid'
    return allvhosts.configs[vhost].rooturl + '+openid'


def make_endpoint(protocol_uri, claimed_id, local_id=None):
    """Create an endpoint for use with `Consumer.beginWithoutDiscovery`.

    :arg protocol_uri: The URI for the OpenID protocol version.  This
        should be one of the OPENID_X_Y_TYPE constants.
    :arg claimed_id: The claimed identity URL for the endpoint.
    :arg local_id: The OP local identifier for the endpoint.  If this
        argument is not provided, it defaults to claimed_id.
    """
    assert protocol_uri in [
        OPENID_1_0_TYPE, OPENID_1_1_TYPE, OPENID_2_0_TYPE], (
        "Unexpected protocol URI: %s" % protocol_uri)

    endpoint = OpenIDServiceEndpoint()
    endpoint.type_uris = [protocol_uri]
    endpoint.server_url = get_requested_server_url(claimed_id)
    endpoint.claimed_id = claimed_id
    endpoint.local_id = local_id or claimed_id
    return endpoint


def make_identifier_select_endpoint(protocol_uri):
    """Create an endpoint for use in OpenID identifier select mode.

    :arg protocol_uri: The URI for the OpenID protocol version.  This
        should be one of the OPENID_X_Y_TYPE constants.

    If the OpenID 1.x protocol is selected, the endpoint will be
    suitable for use with Launchpad's non-standard identifier select
    workflow.
    """
    assert protocol_uri in [
        OPENID_1_0_TYPE, OPENID_1_1_TYPE, OPENID_2_0_TYPE], (
        "Unexpected protocol URI: %s" % protocol_uri)

    endpoint = OpenIDServiceEndpoint()
    endpoint.server_url = get_requested_server_url()
    if protocol_uri == OPENID_2_0_TYPE:
        endpoint.type_uris = [OPENID_IDP_2_0_TYPE]
    else:
        endpoint.type_uris = [protocol_uri]
        endpoint.claimed_id = IDENTIFIER_SELECT
        endpoint.local_id = IDENTIFIER_SELECT
    return endpoint


def maybe_fixup_identifier_select_request(consumer, claimed_id):
    """Fix up an OpenID 1.x identifier select request.

    :arg consumer: an OpenID `Consumer` instance.
    :arg claimed_id: the expected claimed ID for the response.

    OpenID 1.x does not support identifier select, so responses using
    our non-standard identifier select mode appear to be corrupt.

    This function checks to see if the current request was a 1.x
    identifier select one, and updates the internal state to use the
    given claimed ID if so.
    """
    endpoint = consumer.session[consumer._token_key]
    if (OPENID_1_0_TYPE in endpoint.type_uris or
        OPENID_1_1_TYPE in endpoint.type_uris):
        assert endpoint.claimed_id == IDENTIFIER_SELECT, (
            "Request did not use identifier select mode")
        endpoint.claimed_id = claimed_id
        endpoint.local_id = claimed_id
    else:
        # For standard identifier select, local_id is None.
        assert endpoint.local_id is None, (
            "Request did not use identifier select mode")


def complete_from_browser(consumer, browser, expected_claimed_id=None):
    """Complete OpenID request based on output of +openid-consumer.

    :arg consumer: an OpenID `Consumer` instance.
    :arg browser: a Zope testbrowser `Browser` instance.
    :arg expected_claimed_id: the expected claimed ID for the response,
        or None if the request did not use identifier select mode.

    This function parses the body of the +openid-consumer view into a
    set of query arguments representing the OpenID response.

    If the third argument is provided, it will also attempt to fix up
    1.x identifier select requests.
    """
    assert browser.contents.startswith('Consumer received '), (
        "Browser contents does not look like it came from +openid-consumer")
    # Skip the first "Consumer received GET" line
    query = dict(line.split(':', 1)
                 for line in browser.contents.splitlines()[1:])
    if expected_claimed_id is not None:
        maybe_fixup_identifier_select_request(
            consumer, expected_claimed_id)
        # The return_to URL verification for OpenID 1.x requests fails
        # for our non-standard identifier select mode, so disable it.
        consumer.consumer._verifyDiscoveryResultsOpenID1 = (
            lambda msg, endpoint: endpoint)

    response = consumer.complete(query, browser.url)

    if expected_claimed_id is not None:
        del consumer.consumer._verifyDiscoveryResultsOpenID1
    return response
