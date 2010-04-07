#!/usr/bin/python2.6 -S
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
from twisted.web import xmlrpc

from canonical.config import config

from lp.codehosting.codeimport.workermonitor import (
    CodeImportWorkerMonitor)
from lp.services.scripts.base import LaunchpadScript
from lp.services.twistedsupport.loggingsupport import set_up_oops_reporting


class CodeImportWorker(LaunchpadScript):

    def __init__(self, name, dbuser=None, test_args=None):
        LaunchpadScript.__init__(self, name, dbuser, test_args)
        set_up_oops_reporting(name, mangle_stdout=True)

    def _init_db(self, implicit_begin, isolation):
        # This script doesn't access the database.
        pass

    def main(self):
        arg, = self.args
        job_id = int(arg)
        # XXX: MichaelHudson 2008-05-07 bug=227586: Setting up the component
        # architecture overrides $GNUPGHOME to something stupid.
        os.environ['GNUPGHOME'] = ''
        reactor.callWhenRunning(self._do_import, job_id)
        reactor.run()

    def _do_import(self, job_id):
        defer.maybeDeferred(self._main, job_id).addErrback(
            log.err).addCallback(
            lambda ignored: reactor.stop())

    def _main(self, job_id):
        worker = CodeImportWorkerMonitor(
            job_id, self.logger,
            xmlrpc.Proxy(config.codeimportdispatcher.codeimportscheduler_url))
        return worker.run()

if __name__ == '__main__':
    script = CodeImportWorker('codeimportworker')
    script.run()
