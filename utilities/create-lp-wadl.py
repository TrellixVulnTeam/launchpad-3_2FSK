#! /usr/bin/python2.4
# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Create a static WADL file describing the current webservice.

Usage hint:

% LPCONFIG="edge" utilities/create-lp-wadl.py > launchpad.wadl
"""

import _pythonpath

import sys

from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.webapp.servers import (
    WebServicePublication, WebServiceTestRequest)
from canonical.launchpad.webapp.vhosts import allvhosts
from canonical.lazr.rest.resource import ServiceRootResource

def main():
    ServiceRootResource.cached_wadl = None # do not use cached file version
    execute_zcml_for_scripts()

    # Request the WADL from the root resource.
    # We do this by creating a request object asking for a WADL
    # representation.
    request = WebServiceTestRequest(environ={
        'SERVER_URL': allvhosts.configs['api'].rooturl,
        'HTTP_HOST': allvhosts.configs['api'].hostname,
        'HTTP_ACCEPT': 'application/vd.sun.wadl+xml'
        })
    # We then bypass the usual publisher processing by associating
    # the request with the WebServicePublication (usually done  by the
    # publisher) and then calling the root resource - retrieved through
    # getApplication().
    request.setPublication(WebServicePublication(None))
    login(ANONYMOUS, request)
    print request.publication.getApplication(request)(request)
    return 0

if __name__ == '__main__':
    sys.exit(main())
