#!/usr/bin/python2.4
#
# Fix plural forms in existing imported PO files.
# Useful with cases like different order of plural forms in
# previously imported PO files and our default plural expression
# for a language.
#
# Copyright 2007 Canonical Ltd.  All rights reserved.
#
import sys
import logging

import _pythonpath

from canonical.launchpad.scripts.base import LaunchpadScript
from canonical.config import config
from canonical.launchpad.scripts.fix_plural_forms import (
    fix_plurals_in_all_pofiles)

class FixPOFilePluralFormsScript(LaunchpadScript):

    description = ("Fix plural forms for PO files with different order "
                   "of plural forms from the ones in our database.")
    usage = "usage: %s" % sys.argv[0]
    loglevel = logging.INFO

    def main(self):
        execute_zcml_for_scripts()
        fix_plurals_in_all_pofiles(self.txn, self.logger)

if __name__ == '__main__':
    script = FixPOFilePluralFormsScript(
        'canonical.launchpad.scripts.fix_pofile_plurals',
        dbuser=config.rosetta.rosettaadmin.dbuser)
    script.run()
