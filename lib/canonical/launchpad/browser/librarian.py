# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Browser file for LibraryFileAlias."""

__metaclass__ = type

__all__ = [
    'LibraryFileAliasView',
    'LibraryFileAliasMD5View'
    ]

from canonical.launchpad.interfaces import ILibraryFileAlias
from canonical.launchpad.webapp import LaunchpadView

class LibraryFileAliasView(LaunchpadView):
    """View to handle redirection for downloading files by URL.

    Rather than reference downloadable files via the obscure Librarian
    URL, downloadable files can be referenced via the Product Release URL, e.g.
    http://launchpad.net/firefox/1.0./1.0.0/+download/firefox-1.0.0.tgz.
    """

    __used_for__ = ILibraryFileAlias

    def initialize(self):
        """Redirect the request to the URL of the file in the Librarian."""
        self.request.response.redirect(self.context.getURL())
        
class LibraryFileAliasMD5View(LaunchpadView):
    """View to show the MD5 digest for a librarian file."""
    
    __used_for__ = ILibraryFileAlias
    
    def render(self):
        """Return the plain text MD5 signature"""
        self.request.response.setHeader('Content-type', 'text/plain')
        return self.context.content.md5
