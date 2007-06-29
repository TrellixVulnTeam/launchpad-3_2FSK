# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

# Twisted Application Configuration file.
# Use with "twistd2.4 -y <file.tac>", e.g. "twistd -noy server.tac"

import os

from twisted.application import service, internet, strports
from twisted.web import server

from canonical.database.sqlbase import SQLBase
from canonical.config import config, dbconfig
from canonical.launchpad.daemons import tachandler
from canonical.launchpad.scripts import execute_zcml_for_scripts

from canonical.librarian.libraryprotocol import FileUploadFactory
from canonical.librarian import storage, db
from canonical.librarian import web as fatweb

# Connect to database
dbconfig.setConfigSection('librarian')
execute_zcml_for_scripts()

application = service.Application('Librarian')
librarianService = service.IServiceCollection(application)

# Service that announces when the daemon is ready
tachandler.ReadyService().setServiceParent(librarianService)

path = config.librarian.server.root
storage = storage.LibrarianStorage(path, db.Library())

f = FileUploadFactory(storage)
uploadPort = str(config.librarian.upload_port)
strports.service(uploadPort, f).setServiceParent(librarianService)

if config.librarian.server.upstream_host:
    upstreamHost = config.librarian.server.upstream_host
    upstreamPort = int(config.librarian.server.upstream_port)
    print 'Using upstream librarian http://%s:%d' % (upstreamHost, upstreamPort)
else:
    upstreamHost = upstreamPort = None
root = fatweb.LibraryFileResource(storage, upstreamHost, upstreamPort)
root.putChild('search', fatweb.DigestSearchResource(storage))
root.putChild('robots.txt', fatweb.robotsTxt)
site = server.Site(root)
site.displayTracebacks = False
webPort = str(config.librarian.download_port)
strports.service(webPort, site).setServiceParent(librarianService)
