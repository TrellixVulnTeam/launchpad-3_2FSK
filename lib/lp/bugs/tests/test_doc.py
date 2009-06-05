# Copyright 2009 Canonical Ltd.  All rights reserved.
"""
Run the doctests and pagetests.
"""

import logging
import os
import unittest

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.testing.pages import PageTestSuite
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, setUp, tearDown)
from canonical.testing import (
    DatabaseFunctionalLayer, DatabaseLayer, LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer)
from lp.registry.tests import mailinglists_helper


here = os.path.dirname(os.path.realpath(__file__))


def lobotomizeSteveASetUp(test):
    """Call lobotomize_stevea() and standard setUp"""
    lobotomize_stevea()
    setUp(test)


def checkwatchesSetUp(test):
    """Setup the check watches script tests."""
    setUp(test)
    LaunchpadZopelessLayer.switchDbUser(config.checkwatches.dbuser)

def uploaderSetUp(test):
    """setup the package uploader script tests."""
    setUp(test)
    LaunchpadZopelessLayer.switchDbUser('uploader')

def uploaderTearDown(test):
    """Tear down the package uploader script tests."""
    # XXX sinzui 2007-11-14:
    # This function is not needed. The test should be switched to tearDown.
    tearDown(test)


def branchscannerBugsSetUp(test):
    """Setup the user for the branch scanner tests."""
    lobotomize_stevea()
    branchscannerSetUp(test)


def bugNotificationSendingSetUp(test):
    lobotomize_stevea()
    LaunchpadZopelessLayer.switchDbUser(config.malone.bugnotification_dbuser)
    setUp(test)

def bugNotificationSendingTearDown(test):
    tearDown(test)

def cveSetUp(test):
    lobotomize_stevea()
    LaunchpadZopelessLayer.switchDbUser(config.cveupdater.dbuser)
    setUp(test)

def uploadQueueSetUp(test):
    lobotomize_stevea()
    test_dbuser = config.uploadqueue.dbuser
    LaunchpadZopelessLayer.switchDbUser(test_dbuser)
    setUp(test)
    test.globs['test_dbuser'] = test_dbuser

def uploaderBugsSetUp(test):
    """Set up a test suite using the 'uploader' db user.

    Some aspects of the bug tracker are being used by the Soyuz uploader.
    In order to test that these functions work as expected from the uploader,
    we run them using the same db user used by the uploader.
    """
    lobotomize_stevea()
    test_dbuser = config.uploader.dbuser
    LaunchpadZopelessLayer.switchDbUser(test_dbuser)
    setUp(test)
    test.globs['test_dbuser'] = test_dbuser

def uploaderBugsTearDown(test):
    logout()

def uploadQueueTearDown(test):
    logout()

def noPrivSetUp(test):
    """Set up a test logged in as no-priv."""
    setUp(test)
    login('no-priv@canonical.com')

def bugtaskExpirationSetUp(test):
    """Setup globs for bug expiration."""
    setUp(test)
    test.globs['commit'] = commit
    login('test@canonical.com')


special = {
    'cve-update.txt': LayeredDocFileSuite(
        '../doc/cve-update.txt',
        setUp=cveSetUp, tearDown=tearDown, layer=LaunchpadZopelessLayer
        ),
    'bugnotificationrecipients.txt-uploader': LayeredDocFileSuite(
        '../doc/bugnotificationrecipients.txt',
        setUp=uploaderBugsSetUp,
        tearDown=uploaderBugsTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugnotificationrecipients.txt-queued': LayeredDocFileSuite(
        '../doc/bugnotificationrecipients.txt',
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugnotification-comment-syncing-team.txt': LayeredDocFileSuite(
        '../doc/bugnotification-comment-syncing-team.txt',
        layer=LaunchpadZopelessLayer, setUp=bugNotificationSendingSetUp,
        tearDown=bugNotificationSendingTearDown
        ),
    'bugnotificationrecipients.txt-branchscanner': LayeredDocFileSuite(
        '../doc/bugnotificationrecipients.txt',
        setUp=branchscannerBugsSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugnotificationrecipients.txt': LayeredDocFileSuite(
        '../doc/bugnotificationrecipients.txt',
        setUp=lobotomizeSteveASetUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer
        ),
    'bugnotification-threading.txt': LayeredDocFileSuite(
        '../doc/bugnotification-threading.txt',
        setUp=lobotomizeSteveASetUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer
        ),
    'bugnotification-sending.txt': LayeredDocFileSuite(
        '../doc/bugnotification-sending.txt',
        layer=LaunchpadZopelessLayer, setUp=bugNotificationSendingSetUp,
        tearDown=bugNotificationSendingTearDown
        ),
    'bugmail-headers.txt': LayeredDocFileSuite(
        '../doc/bugmail-headers.txt',
        layer=LaunchpadZopelessLayer,
        setUp=bugNotificationSendingSetUp,
        tearDown=bugNotificationSendingTearDown),
    'bugzilla-import.txt': LayeredDocFileSuite(
        '../doc/bugzilla-import.txt',
        setUp=setUp, tearDown=tearDown,
        stdout_logging_level=logging.WARNING,
        layer=LaunchpadZopelessLayer
        ),
    'bug-export.txt': LayeredDocFileSuite(
        '../doc/bug-export.txt',
        setUp=setUp, tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bug-set-status.txt': LayeredDocFileSuite(
        '../doc/bug-set-status.txt',
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bug-set-status.txt-uploader': LayeredDocFileSuite(
        '../doc/bug-set-status.txt',
        setUp=uploaderBugsSetUp,
        tearDown=uploaderBugsTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugtask-expiration.txt': LayeredDocFileSuite(
        '../doc/bugtask-expiration.txt',
        setUp=bugtaskExpirationSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugmessage.txt': LayeredDocFileSuite(
        '../doc/bugmessage.txt',
        setUp=noPrivSetUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer
        ),
    'bugmessage.txt-queued': LayeredDocFileSuite(
        '../doc/bugmessage.txt',
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugmessage.txt-uploader': LayeredDocFileSuite(
        '../doc/bugmessage.txt',
        setUp=uploaderSetUp,
        tearDown=uploaderTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugmessage.txt-checkwatches': LayeredDocFileSuite(
        '../doc/bugmessage.txt',
        setUp=checkwatchesSetUp,
        tearDown=uploaderTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bug-private-by-default.txt': LayeredDocFileSuite(
        '../doc/bug-private-by-default.txt',
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugtracker-person.txt': LayeredDocFileSuite(
        '../doc/bugtracker-person.txt',
        setUp=checkwatchesSetUp,
        tearDown=uploaderTearDown,
        layer=LaunchpadZopelessLayer
        ),
    'bugwatch.txt':
        LayeredDocFileSuite(
        '../doc/bugwatch.txt',
        setUp=setUp, tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker.txt',
        setUp=setUp, tearDown=tearDown,
        stdout_logging_level=logging.WARNING,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-bug-imports.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-bug-imports.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-bugzilla.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-bugzilla.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-bugzilla-lp-plugin.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-bugzilla-lp-plugin.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-bugzilla-oddities.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-bugzilla-oddities.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-checkwatches.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-checkwatches.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-comment-imports.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-comment-imports.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-comment-pushing.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-comment-pushing.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-debbugs.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-debbugs.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-emailaddress.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-emailaddress.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-linking-back.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-linking-back.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        stdout_logging_level=logging.ERROR,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-mantis-csv.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-mantis-csv.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-mantis.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-mantis.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-roundup-python-bugs.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-roundup-python-bugs.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-roundup.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-roundup.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-rt.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-rt.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-sourceforge.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-sourceforge.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-trac.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-trac.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'externalbugtracker-trac-lp-plugin.txt':
        LayeredDocFileSuite(
        '../doc/externalbugtracker-trac-lp-plugin.txt',
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer
        ),
    'filebug-data-parser.txt': LayeredDocFileSuite(
    '../doc/filebug-data-parser.txt'),
    }


def test_suite():
    suite = unittest.TestSuite()

    stories_dir = os.path.join(os.path.pardir, 'stories')
    suite.addTest(PageTestSuite(stories_dir))
    stories_path = os.path.join(here, stories_dir)
    for story_dir in os.listdir(stories_path):
        full_story_dir = os.path.join(stories_path, story_dir)
        if not os.path.isdir(full_story_dir):
            continue
        story_path = os.path.join(stories_dir, story_dir)
        suite.addTest(PageTestSuite(story_path))

    testsdir = os.path.abspath(
        os.path.normpath(os.path.join(here, os.path.pardir, 'doc'))
        )

    # Add special needs tests
    for key in sorted(special):
        special_suite = special[key]
        suite.addTest(special_suite)

    # Add tests using default setup/teardown
    filenames = [filename
                 for filename in os.listdir(testsdir)
                 if filename.endswith('.txt') and filename not in special]
    # Sort the list to give a predictable order.
    filenames.sort()
    for filename in filenames:
        path = os.path.join('../doc/', filename)
        one_test = LayeredDocFileSuite(
            path, setUp=setUp, tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
            stdout_logging_level=logging.WARNING
            )
        suite.addTest(one_test)

    return suite
