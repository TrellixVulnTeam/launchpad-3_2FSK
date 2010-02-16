#!/usr/bin/python2.5 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""When passed a CodeImportJob id on the command line, process that job.

The actual work of processing a job is done by the code-import-worker.py
script which this process runs as a child process and updates the database on
its progress and result.

This script is usually run by the code-import-dispatcher cronscript.
"""

__metaclass__ = type


# pylint: disable-msg=W0403
import _pythonpath

import os

from twisted.internet import defer, reactor
from twisted.python import log

from lp.codehosting.codeimport.workermonitor import (
    CodeImportWorkerMonitor)
from lp.services.scripts.base import LaunchpadScript
from canonical.twistedsupport.loggingsupport import set_up_oops_reporting


class CodeImportWorker(LaunchpadScript):

    def __init__(self, name, dbuser=None, test_args=None):
        LaunchpadScript.__init__(self, name, dbuser, test_args)
        set_up_oops_reporting(name, mangle_stdout=True)

    def main(self):
        # XXX: MichaelHudson 2008-05-07 bug=227586: Setting up the component
        # architecture overrides $GNUPGHOME to something stupid.
        os.environ['GNUPGHOME'] = ''
        reactor.callWhenRunning(self._run_reactor)
        reactor.run()

    def _run_reactor(self):
        defer.maybeDeferred(self._main).addErrback(
            log.err).addCallback(
            lambda ignored: reactor.stop())

    def _main(self):
        arg, = self.args
        return CodeImportWorkerMonitor(int(arg), self.logger).run()

if __name__ == '__main__':
    script = CodeImportWorker('codeimportworker', dbuser='codeimportworker')
    script.run()
