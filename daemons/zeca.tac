# Copyright 2004-2008 Canonical Ltd.  All rights reserved.

# Twisted Application Configuration file.
# Use with "twistd2.3 -y <file.tac>", e.g. "twistd -noy server.tac"

from twisted.application import service, internet, strports
from twisted.web import server

from canonical.config import config
from canonical.launchpad.daemons import tachandler
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.zeca import Zeca, KeyServer, LookUp, SubmitKey

# Needed for using IGPGHandler for processing key submit.
execute_zcml_for_scripts()

root = config.zeca.root

application = service.Application('Zeca')
zecaService = service.IServiceCollection(application)

# Service that announces when the daemon is ready
tachandler.ReadyService().setServiceParent(zecaService)

zeca = Zeca()
keyserver = KeyServer()
keyserver.putChild('lookup', LookUp(root))
keyserver.putChild('add', SubmitKey(root))
zeca.putChild('pks', keyserver)

site = server.Site(zeca)
site.displayTracebacks = False
strports.service('11371', site).setServiceParent(zecaService)
