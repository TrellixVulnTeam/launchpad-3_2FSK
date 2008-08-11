# Copyright 2008 Canonical Ltd.  All rights reserved.

"""A marker layer for the Mailman integration tests."""

__metaclass__ = type
__all__ = [
    'MailmanLayer',
    ]


import os
import atexit

from canonical.testing.layers import AppServerLayer
from canonical.launchpad.mailman.runmailman import start_mailman, stop_mailman
from canonical.launchpad.mailman.testing import logwatcher


class MailmanLayer(AppServerLayer):
    """A layer for the Mailman integration tests."""

    # Log watchers, shared among all layer tests.
    mhonarc_watcher = None
    smtpd_watcher = None
    vette_watcher = None
    xmlrpc_watcher = None
    qrunner_watcher = None

    @classmethod
    def setUp(cls):
        # Stop Mailman if it's currently running.
        pid_file = os.path.join(
            AppServerLayer.appserver_config.mailman.build_var_dir,
            'data', 'master-qrunner.pid')
        if os.path.exists(pid_file):
            stop_mailman(quiet=True, config=AppServerLayer.appserver_config)
        start_mailman(quiet=True, config=AppServerLayer.appserver_config)
        # Make sure that mailman is killed even if tearDown() is skipped.
        atexit.register(cls.tearDown)

    @classmethod
    def tearDown(cls):
        stop_mailman(quiet=True, config=AppServerLayer.appserver_config)

    @classmethod
    def testSetUp(cls):
        # Create the common log watchers.
        cls.mhonarc_watcher = logwatcher.MHonArcWatcher()
        cls.smtpd_watcher = logwatcher.SMTPDWatcher()
        cls.vette_watcher = logwatcher.VetteWatcher()
        cls.xmlrpc_watcher = logwatcher.XMLRPCWatcher()
        cls.qrunner_watcher = logwatcher.QrunnerWatcher()

    @classmethod
    def testTearDown(cls):
        # Finished with the common log watchers.
        cls.mhonarc_watcher.close()
        cls.smtpd_watcher.close()
        cls.vette_watcher.close()
        cls.xmlrpc_watcher.close()
        cls.qrunner_watcher.close()
        cls.mhonarc_watcher = None
        cls.smtpd_watcher = None
        cls.vette_watcher = None
        cls.xmlrpc_watcher = None
        cls.qrunner_watcher = None
