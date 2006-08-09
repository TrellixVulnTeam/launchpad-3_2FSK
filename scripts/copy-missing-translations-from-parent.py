#!/usr/bin/env python
# Copyright 2006 Canonical Ltd.  All rights reserved.

import sys
from optparse import OptionParser
from zope.component import getUtility
from canonical.config import config
from canonical.lp import initZopeless
from canonical.launchpad.interfaces import IDistributionSet
from canonical.launchpad.scripts import execute_zcml_for_scripts
from canonical.launchpad.scripts import logger, logger_options

def parse_options(args):
    """Parse a set of command line options.

    Return an optparse.Values object.
    """
    parser = OptionParser()
    parser.add_option("-d", "--distribution", dest="distro",
        default='ubuntu',
        help="The distribution we want to work with.")
    parser.add_option("-r", "--release", dest="release",
        help="The distrorelease where we want to migrate translations.")

    logger_options(parser)

    (options, args) = parser.parse_args(args)

    return options

def main(argv):
    options = parse_options(argv[1:])

    logger_object = logger(options, 'initialise')

    # Setup zcml machinery to be able to use getUtility
    execute_zcml_for_scripts()
    ztm = initZopeless(dbuser=config.rosetta.rosettaadmin.dbuser)

    distribution = getUtility(IDistributionSet)[options.distro]
    release = distribution[options.release]

    release.copyMissingTranslationsFromParent()

    # Finally, we changed many things related with cached statistics,
    # let's update it.
    release.updateStatistics(ztm)

    # Commit the transaction.
    ztm.commit()

if __name__ == '__main__':
    main(sys.argv)

