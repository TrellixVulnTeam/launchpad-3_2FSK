# Copyright 2009 Canonical Ltd.  All rights reserved.

"""A configuration class describing the LAZR example web service."""

__metaclass__ = type
__all__ = [
    'CookbookWebServiceConfiguration',
]

from zope.interface import implements

from canonical.lazr.interfaces.rest import IWebServiceConfiguration

class CookbookWebServiceConfiguration:
    """A configuration object for the cookbook web service."""
    implements(IWebServiceConfiguration)

    path_override = "api"
    service_version_uri_prefix = "1.0"
    view_permission = "lazr.View"
    use_https = True
    code_revision = "test.revision"
