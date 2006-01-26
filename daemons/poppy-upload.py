#!/usr/bin/python

import sys
import logging
import optparse

from canonical.poppy.server import run_server
from canonical.archivepublisher.poppyinterface import PoppyInterface
from canonical.launchpad.scripts import logger, logger_options


def main():

    parser = optparse.OptionParser()
    logger_options(parser)

    parser.add_option("--cmd", action="store", metavar="CMD",
                      help="Run CMD after each upload completion")

    options, args = parser.parse_args()

    log = logger(options, "poppy-upload")

    if len(args) != 2:
        print "usage: poppy-upload.py rootuploaddirectory port"
        return 1

    root, port = args
    host = "0.0.0.0"
    ident = "lucille upload server"
    numthreads = 4
   
    iface = PoppyInterface(root, log, cmd=options.cmd)

    run_server(host, int(port), ident, numthreads,
               iface.new_client_hook, iface.client_done_hook,
               iface.auth_verify_hook)
    return 0

if __name__ == '__main__':
    sys.exit(main())
