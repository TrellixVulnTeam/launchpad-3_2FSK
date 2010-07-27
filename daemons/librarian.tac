# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Twisted Application Configuration file.
# Use with "twistd2.4 -y <file.tac>", e.g. "twistd -noy server.tac"

import signal

from meliae import scanner

from twisted.application import service, strports
from twisted.web import server

from canonical.config import config, dbconfig
from canonical.launchpad.daemons import tachandler
from canonical.launchpad.scripts import execute_zcml_for_scripts

from canonical.librarian.interfaces import DUMP_FILE, SIGDUMPMEM
from canonical.librarian.libraryprotocol import FileUploadFactory
from canonical.librarian import storage, db
from canonical.librarian import web as fatweb
from lp.services.twistedsupport.loggingsupport import set_up_oops_reporting

# Connect to database
dbconfig.setConfigSection('librarian')
execute_zcml_for_scripts()

path = config.librarian_server.root
if config.librarian_server.upstream_host:
    upstreamHost = config.librarian_server.upstream_host
    upstreamPort = config.librarian_server.upstream_port
    print 'Using upstream librarian http://%s:%d' % (
        upstreamHost, upstreamPort)
else:
    upstreamHost = upstreamPort = None

application = service.Application('Librarian')
librarianService = service.IServiceCollection(application)

# Service that announces when the daemon is ready
tachandler.ReadyService().setServiceParent(librarianService)

def setUpListener(uploadPort, webPort, restricted):
    """Set up a librarian listener on the given ports.

    :param restricted: Should this be a restricted listener?  A restricted
        listener will serve only files with the 'restricted' file set and all
        files uploaded through the restricted listener will have that flag
        set.
    """
    librarian_storage = storage.LibrarianStorage(
        path, db.Library(restricted=restricted))
    upload_factory = FileUploadFactory(librarian_storage)
    strports.service(str(uploadPort), upload_factory).setServiceParent(
        librarianService)
    root = fatweb.LibraryFileResource(
        librarian_storage, upstreamHost, upstreamPort)
    root.putChild('search', fatweb.DigestSearchResource(librarian_storage))
    root.putChild('robots.txt', fatweb.robotsTxt)
    site = server.Site(root)
    site.displayTracebacks = False
    strports.service(str(webPort), site).setServiceParent(librarianService)

# Set up the public librarian.
uploadPort = config.librarian.upload_port
webPort = config.librarian.download_port
setUpListener(uploadPort, webPort, restricted=False)

# Set up the restricted librarian.
webPort = config.librarian.restricted_download_port
uploadPort = config.librarian.restricted_upload_port
setUpListener(uploadPort, webPort, restricted=True)

# Log OOPS reports
set_up_oops_reporting('librarian', 'librarian')

# Setup a signal handler to dump the process' memory upon 'kill -44'.
def sigdumpmem_handler(signum, frame):
    scanner.dump_all_objects(DUMP_FILE)

signal.signal(SIGDUMPMEM, sigdumpmem_handler)
