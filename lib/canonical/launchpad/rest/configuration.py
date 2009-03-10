# Copyright 2008 Canonical Ltd.  All rights reserved.

"""A configuration class describing the Launchpad web service."""

__metaclass__ = type
__all__ = [
    'LaunchpadWebServiceConfiguration',
]

from zope.interface import implements

from canonical.config import config
from canonical.lazr.interfaces.rest import IWebServiceConfiguration
from canonical.launchpad.webapp.servers import (
    WebServiceClientRequest, WebServicePublication)

from canonical.launchpad import versioninfo

class LaunchpadWebServiceConfiguration:
    implements(IWebServiceConfiguration)

    path_override = "api"
    service_version_uri_prefix = "beta"
    view_permission = "launchpad.View"

    @property
    def use_https(self):
        return config.vhosts.use_https

    @property
    def code_revision(self):
        return str(versioninfo.revno)

    def createRequest(self, body_stream, environ):
        """See `IWebServiceConfiguration`."""
        request = WebServiceClientRequest(body_stream, environ)
        request.setPublication(WebServicePublication(None))
        return request
