# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""APIs to generate the web sercice WADL and documentation HTML."""

__metaclass__ = type

import pkg_resources
import subprocess
import urlparse

from canonical.launchpad.webapp.interaction import (
    ANONYMOUS,
    setupInteractionByEmail,
    )
from canonical.launchpad.webapp.servers import (
    WebServicePublication,
    WebServiceTestRequest,
    )
from canonical.launchpad.webapp.vhosts import allvhosts


def generate_wadl(version):
    """Generate the WADL for the given version of the web service."""
    url = urlparse.urljoin(allvhosts.configs['api'].rooturl, version)
    # Since we want HTTPS URLs we have to munge the request URL.
    url = url.replace('http://', 'https://')
    request = WebServiceTestRequest(version=version, environ={
        'SERVER_URL': url,
        'HTTP_HOST': allvhosts.configs['api'].hostname,
        'HTTP_ACCEPT': 'application/vd.sun.wadl+xml',
        })
    # We then bypass the usual publisher processing by associating
    # the request with the WebServicePublication (usually done by the
    # publisher) and then calling the root resource - retrieved
    # through getApplication().
    request.setPublication(WebServicePublication(None))
    setupInteractionByEmail(ANONYMOUS, request)
    return request.publication.getApplication(request)(request)


def generate_html(wadl_filename, suppress_stderr=True):
    """Given a WADL file generate HTML documentation from it."""
    # If we're supposed to prevent the subprocess from generating output on
    # stderr (like we want to do during test runs), we reassign the subprocess
    # stderr file handle and then discard the output.  Otherwise we let the
    # subprocess inherit stderr.
    stylesheet = pkg_resources.resource_filename(
        'launchpadlib', 'wadl-to-refhtml.xsl')
    if suppress_stderr:
        stderr = subprocess.PIPE
    else:
        stderr = None
    args = ('xsltproc', stylesheet, wadl_filename)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=stderr)

    output = process.communicate()[0]
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, args)

    return output

