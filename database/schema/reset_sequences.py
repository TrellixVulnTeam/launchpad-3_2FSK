#!/usr/bin/python2.6
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
The sampledata does not update the current values of all the sequences
used to populate the primary keys (this was removed to aid in merging changes
to the sampledata).

This script resets all of these sequences to the correct value based on the
maximum value currently found in the corresponding table.
"""

__metaclass__ = type

# pylint: disable-msg=W0403
import _pythonpath

from optparse import OptionParser
from canonical.database.postgresql import resetSequences
from canonical.database.sqlbase import connect

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option(
            "-d", "--dbname", dest="dbname", help="database name",
            )
    (options, args) = parser.parse_args()
    if args:
        parser.error("Too many options given")
    if not options.dbname:
        parser.error("Required option --dbname not given")
    con = connect(None, options.dbname)
    resetSequences(con.cursor())
    con.commit()

