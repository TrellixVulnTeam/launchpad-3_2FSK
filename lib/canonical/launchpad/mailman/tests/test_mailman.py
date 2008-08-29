#! /usr/bin/env python2.4
# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Test harness for Launchpad/Mailman doctests."""

import os
import errno
import shutil
import unittest

# pylint: disable-msg=F0401
from Mailman.MailList import MailList
from Mailman.mm_cfg import QUEUE_DIR, VAR_PREFIX

from canonical.launchpad.mailman.testing import helpers
from canonical.launchpad.mailman.testing.layers import MailmanLayer
from canonical.launchpad.testing.browser import (
    setUp as setUpBrowser,
    tearDown as tearDownBrowser)
from canonical.launchpad.testing.systemdocs import LayeredDocFileSuite
from canonical.testing.layers import AppServerLayer


HERE = os.path.dirname(__file__)


def setUp(testobj):
    """Set up for all integration doctests."""
    # We'll always need an smtp server.
    setUpBrowser(testobj)
    AppServerLayer.smtp_controller.reset()
    testobj.globs['smtpd'] = AppServerLayer.smtp_controller
    testobj.globs['mhonarc_watcher'] = MailmanLayer.mhonarc_watcher
    testobj.globs['smtpd_watcher'] = MailmanLayer.smtpd_watcher
    testobj.globs['vette_watcher'] = MailmanLayer.vette_watcher
    testobj.globs['xmlrpc_watcher'] = MailmanLayer.xmlrpc_watcher
    testobj.globs['qrunner_watcher'] = MailmanLayer.qrunner_watcher
    testobj.globs['error_watcher'] = MailmanLayer.error_watcher


def tearDown(testobj):
    """Common tear down for the integration tests."""
    tearDownBrowser(testobj)
    AppServerLayer.smtp_controller.reset()
    # Clear out any qfiles hanging around from a previous run.  Do this first
    # to prevent stale list references.
    for dirpath, dirnames, filenames in os.walk(QUEUE_DIR):
        for filename in filenames:
            if os.path.splitext(filename)[1] == '.pck':
                os.remove(os.path.join(dirpath, filename))
    # Now delete any mailing lists still hanging around.  We don't care if
    # this fails because it means the list doesn't exist.  While we're at it,
    # remove any related archived backup files.
    for team_name in ('itest-one', 'itest-two', 'itest-three', 'fake-team'):
        # pylint: disable-msg=W0702
        try:
            # Ensure that the lock gets cleaned up properly by first acquiring
            # the lock, then unconditionally unlocking it.
            mailing_list = MailList(team_name)
            mailing_list.Unlock()
        except:
            # Yes, ignore all errors, including Mailman's ancient string
            # exceptions.
            pass
        try:
            helpers.run_mailman('./rmlist', '-a', team_name)
        except AssertionError:
            # Ignore errors when the list does not exist.
            pass
        backup_file = os.path.join(
            VAR_PREFIX, 'backups', '%s.tgz' % team_name)
        try:
            os.remove(backup_file)
        except OSError, error:
            if error.errno != errno.ENOENT:
                raise
        # Delete the MHonArc archives if they exist.
        path = os.path.join(VAR_PREFIX, 'mhonarc')
        try:
            shutil.rmtree(path)
        except OSError, error:
            if error.errno != errno.ENOENT:
                raise
    # Remove all held messages.
    data_dir = os.path.join(VAR_PREFIX, 'data')
    for filename in os.listdir(data_dir):
        if filename.startswith('heldmsg'):
            os.remove(os.path.join(data_dir, filename))


def test_suite():
    suite = unittest.TestSuite()
    doc_directory = os.path.normpath(os.path.join(HERE, os.pardir, 'doc'))
    for filename in os.listdir(doc_directory):
        if filename.endswith('.txt'):
            test = LayeredDocFileSuite(
                '../doc/' + filename,
                setUp=setUp, tearDown=tearDown, layer=MailmanLayer)
            suite.addTest(test)
    return suite
