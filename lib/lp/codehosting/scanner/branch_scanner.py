#!/usr/bin/python2.4
# Copyright 2005-2008 Canonical Ltd.  All rights reserved.

"""Internal helpers for cronscripts/branches-scanner.py"""

__metaclass__ = type

__all__ = ['BranchScanner']


import sys

from bzrlib.errors import NotBranchError, ConnectionError
# This non-standard import is necessary to hook up the event system.
import zope.component.event
from zope.component import getUtility

from lp.code.interfaces.branchscanner import IBranchScanner
from lp.codehosting.vfs import get_scanner_server
from lp.codehosting.scanner import buglinks, email, mergedetection
from lp.codehosting.scanner.bzrsync import (
    BzrSync, schedule_translation_upload)
from lp.codehosting.scanner.fixture import (
    Fixtures, make_zope_event_fixture, run_with_fixture)
from canonical.launchpad.webapp import canonical_url, errorlog


class BranchScanner:
    """Scan bzr branches for meta data and insert them into content objects.

    This class is used by cronscripts/branch-scanner.py to perform its task.
    """

    def __init__(self, ztm, log):
        self.ztm = ztm
        self.log = log

    def scanBranches(self, branches):
        """Scan 'branches'."""
        for branch in branches:
            try:
                self.scanOneBranch(branch)
            except (KeyboardInterrupt, SystemExit):
                # If either was raised, something really wants us to finish.
                # Any other Exception is an error condition and must not
                # terminate the script.
                raise
            except Exception, e:
                # Bugs or error conditions when scanning any given branch must
                # not prevent scanning the other branches. Log the error and
                # keep going.
                self.logScanFailure(branch, str(e))

    def scanAllBranches(self):
        """Run Bzrsync on all branches, and intercept most exceptions."""
        event_handlers = [
            email.queue_tip_changed_email_jobs,
            buglinks.got_new_revision,
            mergedetection.auto_merge_branches,
            mergedetection.auto_merge_proposals,
            schedule_translation_upload,
            ]
        server = get_scanner_server()
        fixture = Fixtures([server, make_zope_event_fixture(*event_handlers)])
        self.log.info('Starting branch scanning')
        branches = getUtility(IBranchScanner).getBranchesToScan()
        run_with_fixture(fixture, self.scanBranches, branches)
        self.log.info('Finished branch scanning')

    def scanOneBranch(self, branch):
        """Run BzrSync on a single branch and handle expected exceptions."""
        try:
            bzrsync = BzrSync(self.ztm, branch, self.log)
        except NotBranchError:
            # The branch is not present in the Warehouse
            self.logScanFailure(branch, "No branch found")
            return
        try:
            bzrsync.syncBranchAndClose()
        except ConnectionError, e:
            # A network glitch occured. Yes, that does happen.
            self.logScanFailure(branch, "Internal network failure: %s" % e)

    def logScanFailure(self, branch, message="Failed to scan"):
        """Log diagnostic for branches that could not be scanned."""
        def safe_getattr(obj, name, default='UNKNOWN'):
            """Safely get the 'name' attribute of 'obj'.

            If getting the attribute raises an exception, log that exception
            and return 'default'.
            """
            try:
                return getattr(obj, name, default)
            except:
                self.log.exception("Couldn't get %s" % (name,))
                return default
        unique_name = safe_getattr(branch, 'unique_name')
        request = errorlog.ScriptRequest([
            ('branch.id', safe_getattr(branch, 'id')),
            ('branch.unique_name', unique_name),
            ('branch.url', safe_getattr(branch, 'url')),
            ('branch.warehouse_url', safe_getattr(branch, 'warehouse_url')),
            ('error-explanation', message)])
        try:
            request.URL = canonical_url(branch)
        except Exception, e:
            self.log.exception("Couldn't get canonical_url: %s" % str(e))
        errorlog.globalErrorUtility.raising(sys.exc_info(), request)
        self.log.info('%s: %s (%s)', request.oopsid, message, unique_name)
