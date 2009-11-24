#!/usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a code import described by the command line arguments.

By 'processing a code import' we mean importing or updating code from a
remote, non-Bazaar, repository.

This script is usually run by the code-import-worker-db.py script that
communicates progress and results to the database.
"""

__metaclass__ = type


# pylint: disable-msg=W0403
import _pythonpath

from optparse import OptionParser

from bzrlib.transport import get_transport

from canonical.config import config
from lp.codehosting import load_optional_plugin
from lp.codehosting.codeimport.worker import (
    BzrSvnImportWorker, CSCVSImportWorker, CodeImportSourceDetails,
    GitImportWorker, get_default_bazaar_branch_store)
from canonical.launchpad import scripts


class CodeImportWorker:

    def __init__(self):
        parser = OptionParser()
        scripts.logger_options(parser)
        options, self.args = parser.parse_args()
        self.logger = scripts.logger(options, 'code-import-worker')

    def main(self):
        source_details = CodeImportSourceDetails.fromArguments(self.args)
        if source_details.rcstype == 'git':
            load_optional_plugin('git')
            import_worker_cls = GitImportWorker
        elif source_details.rcstype == 'bzr-svn':
            load_optional_plugin('svn')
            import_worker_cls = BzrSvnImportWorker
        else:
            if source_details.rcstype not in ['cvs', 'svn']:
                raise AssertionError(
                    'unknown rcstype %r' % source_details.rcstype)
            import_worker_cls = CSCVSImportWorker
        import_worker = import_worker_cls(
            source_details,
            get_transport(config.codeimport.foreign_tree_store),
            get_default_bazaar_branch_store(), self.logger)
        import_worker.run()


if __name__ == '__main__':
    script = CodeImportWorker()
    script.main()
