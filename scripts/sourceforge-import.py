#!/usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import optparse
import sys

# pylint: disable-msg=W0403
import _pythonpath

from zope.component import getUtility
from canonical.config import config
from canonical.lp import initZopeless
from canonical.launchpad.interfaces import IProductSet
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger_options, logger)
from canonical.launchpad.ftests import login
from canonical.launchpad.webapp.interaction import Participation

from canonical.launchpad.scripts.sftracker import Tracker, TrackerImporter

def main(argv):
    parser = optparse.OptionParser(description="This script imports bugs "
                                   "from Sourceforge into Launchpad.")

    parser.add_option('--product', metavar='PRODUCT', action='store',
                      help='The product to associate bugs with',
                      type='string', dest='product', default=None)
    parser.add_option('--dumpfile', metavar='XML', action='store',
                      help='The XML tracker data dump',
                      type='string', dest='dumpfile', default=None)
    parser.add_option('--dumpdir', metavar='DIR', action='store',
                      help='The directory with the dumped tracker data',
                      type='string', dest='dumpdir', default=None)
    parser.add_option('--verify-users', dest='verify_users',
                      help='Should created users have verified emails?',
                      action='store_true', default=False)

    logger_options(parser, logging.INFO)

    options, args = parser.parse_args(argv[1:])
    logger(options, 'canonical.launchpad.scripts.sftracker')

    # don't send email
    send_email_data = """
        [zopeless]
        send_email: False
        """
    config.push('send_email_data', send_email_data)

    execute_zcml_for_scripts()
    ztm = initZopeless()
    # XXX gary 21-Oct-2008 bug 285808
    # We should reconsider using a ftest helper for production code.  For now,
    # we explicitly keep the code from using a test request by using a basic
    # participation.
    login('bug-importer@launchpad.net', Participation())

    product = getUtility(IProductSet).getByName(options.product)
    tracker = Tracker(options.dumpfile, options.dumpdir)
    importer = TrackerImporter(product, options.verify_users)

    importer.importTracker(ztm, tracker)
    config.pop('send_email_data')

if __name__ == '__main__':
    sys.exit(main(sys.argv))
