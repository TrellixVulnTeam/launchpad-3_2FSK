# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""
Test the examples included in the system documentation in
lib/canonical/launchpad/doc.
"""

import unittest
import logging
import os

import transaction

from zope.component import getUtility
from zope.security.management import getSecurityPolicy, setSecurityPolicy
from zope.testing.doctest import REPORT_NDIFF, NORMALIZE_WHITESPACE, ELLIPSIS
from zope.testing.doctest import DocFileSuite

from canonical.authserver.ftests.harness import AuthserverTacTestSetup
from canonical.config import config
from canonical.database.sqlbase import (
    flush_database_updates, READ_COMMITTED_ISOLATION)
from canonical.functional import FunctionalDocFileSuite, StdoutHandler
from canonical.launchpad.database import DistributionSet, PersonSet
from canonical.launchpad.ftests import login, ANONYMOUS, logout
from canonical.launchpad.interfaces import CreateBugParams, ILaunchBag
from canonical.launchpad.webapp.authorization import LaunchpadSecurityPolicy
from canonical.testing import (
        LaunchpadZopelessLayer, LaunchpadFunctionalLayer,DatabaseLayer,
        FunctionalLayer)

here = os.path.dirname(os.path.realpath(__file__))

default_optionflags = REPORT_NDIFF | NORMALIZE_WHITESPACE | ELLIPSIS


def setGlobs(test):
    test.globs['ANONYMOUS'] = ANONYMOUS
    test.globs['login'] = login
    test.globs['logout'] = logout
    test.globs['ILaunchBag'] = ILaunchBag
    test.globs['getUtility'] = getUtility
    test.globs['transaction'] = transaction
    test.globs['flush_database_updates'] = flush_database_updates


def setUp(test):
    setGlobs(test)
    # Set up an anonymous interaction.
    login(ANONYMOUS)


def tearDown(test):
    logout()

def poExportSetUp(test):
    LaunchpadZopelessLayer.switchDbUser('poexport')
    setUp(test)

def poExportTearDown(test):
    tearDown(test)

def uploaderSetUp(test):
    setUp(test)
    LaunchpadZopelessLayer.switchDbUser('uploader')

def uploaderTearDown(test):
    tearDown(test)

def builddmasterSetUp(test):
    LaunchpadZopelessLayer.alterConnection(
        dbuser=config.builddmaster.dbuser,
        isolation=READ_COMMITTED_ISOLATION)
    setGlobs(test)

def branchscannerSetUp(test):
    LaunchpadZopelessLayer.switchDbUser('branchscanner')
    setUp(test)

def branchscannerTearDown(test):
    tearDown(test)

def answerTrackerSetUp(test):
    setGlobs(test)
    # The Zopeless environment usually runs using the PermissivePolicy
    # but the process-mail.py script in which the tested code runs
    # use the regular web policy.
    test.old_security_policy = getSecurityPolicy()
    setSecurityPolicy(LaunchpadSecurityPolicy)

def answerTrackerTearDown(test):
    setSecurityPolicy(test.old_security_policy)

def peopleKarmaTearDown(test):
    # We can't detect db changes made by the subprocess (yet).
    DatabaseLayer.force_dirty_database()
    tearDown(test)

def branchStatusSetUp(test):
    test._authserver = AuthserverTacTestSetup()
    test._authserver.setUp()

def branchStatusTearDown(test):
    test._authserver.tearDown()

def bugNotificationSendingSetUp(test):
    LaunchpadZopelessLayer.switchDbUser(config.malone.bugnotification_dbuser)
    setUp(test)

def bugNotificationSendingTearDown(test):
    tearDown(test)

def statisticianSetUp(test):
    setUp(test)
    LaunchpadZopelessLayer.switchDbUser(config.statistician.dbuser)

def statisticianTearDown(test):
    tearDown(test)

def distroseriesqueueSetUp(test):
    setUp(test)
    # The test requires that the umask be set to 022, and in fact this comment
    # was made in irc on 13-Apr-2007:
    #
    # (04:29:18 PM) kiko: barry, cprov says that the local umask is controlled
    # enough for us to rely on it
    #
    # Setting it here reproduces the environment that the doctest expects.
    # Save the old umask so we can reset it in the tearDown().
    test.old_umask = os.umask(022)

def distroseriesqueueTearDown(test):
    os.umask(test.old_umask)
    tearDown(test)

def uploadQueueSetUp(test):
    test_dbuser = config.uploadqueue.dbuser
    LaunchpadZopelessLayer.switchDbUser(test_dbuser)
    setUp(test)
    test.globs['test_dbuser'] = test_dbuser

def uploadQueueTearDown(test):
    logout()

def noPrivSetUp(test):
    """Set up a test logged in as no-priv."""
    setUp(test)
    login('no-priv@canonical.com')

def bugLinkedToQuestionSetUp(test):
    setUp(test)
    login('test@canonical.com')
    sample_person = PersonSet().getByEmail('test@canonical.com')
    ubuntu = DistributionSet().getByName('ubuntu')
    ubuntu_question = ubuntu.newQuestion(
        sample_person, "Can't install Ubuntu",
        "I insert the install CD in the CD-ROM drive, but it won't boot.")
    no_priv = PersonSet().getByEmail('no-priv@canonical.com')
    params = CreateBugParams(
        owner=no_priv, title="Installer fails on a Mac PPC",
        comment=ubuntu_question.description)
    bug = ubuntu.createBug(params)
    ubuntu_question.linkBug(bug)
    [ubuntu_bugtask] = bug.bugtasks
    def get_bugtask_linked_to_question():
        return ubuntu_bugtask
    test.globs['get_bugtask_linked_to_question'] = get_bugtask_linked_to_question
    login(ANONYMOUS)


def LayeredDocFileSuite(*args, **kw):
    '''Create a DocFileSuite with a layer.'''
    # Set stdout_logging keyword argument to True to make
    # logging output be sent to stdout, forcing doctests to deal with it.
    stdout_logging = kw.pop('stdout_logging', True)
    stdout_logging_level = kw.pop('stdout_logging_level', logging.INFO)

    kw_setUp = kw.get('setUp')
    def setUp(test):
        if kw_setUp is not None:
            kw_setUp(test)
        if stdout_logging:
            log = StdoutHandler('')
            log.setLoggerLevel(stdout_logging_level)
            log.install()
            test.globs['log'] = log
            # Store as instance attribute so we can uninstall it.
            test._stdout_logger = log
    kw['setUp'] = setUp

    kw_tearDown = kw.get('tearDown')
    def tearDown(test):
        if kw_tearDown is not None:
            kw_tearDown(test)
        if stdout_logging:
            test._stdout_logger.uninstall()
    kw['tearDown'] = tearDown

    layer = kw.pop('layer')
    suite = DocFileSuite(*args, **kw)
    suite.layer = layer
    return suite


# Files that have special needs can construct their own suite
special = {
    # No setup or teardown at all, since it is demonstrating these features.
    'old-testing.txt': LayeredDocFileSuite(
            '../doc/old-testing.txt', optionflags=default_optionflags,
            layer=FunctionalLayer
            ),

    'remove-upstream-translations-script.txt': DocFileSuite(
            '../doc/remove-upstream-translations-script.txt',
            optionflags=default_optionflags, setUp=setGlobs
            ),

    # And these tests want minimal environments too.
    'poparser.txt': DocFileSuite(
            '../doc/poparser.txt', optionflags=default_optionflags
            ),

    'package-relationship.txt': DocFileSuite(
            '../doc/package-relationship.txt',
            optionflags=default_optionflags
            ),

    # POExport stuff is Zopeless and connects as a different database user.
    # poexport-distroseries-(date-)tarball.txt is excluded, since they add
    # data to the database as well.
    'poexport.txt': LayeredDocFileSuite(
            '../doc/poexport.txt',
            setUp=poExportSetUp, tearDown=poExportTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer,
            stdout_logging=False
            ),
    'poexport-template-tarball.txt': LayeredDocFileSuite(
            '../doc/poexport-template-tarball.txt',
            setUp=poExportSetUp, tearDown=poExportTearDown,
            layer=LaunchpadZopelessLayer
            ),
    'poexport-queue.txt': FunctionalDocFileSuite(
            '../doc/poexport-queue.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'librarian.txt': FunctionalDocFileSuite(
            '../doc/librarian.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'message.txt': FunctionalDocFileSuite(
            '../doc/message.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'cve-update.txt': FunctionalDocFileSuite(
            '../doc/cve-update.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'nascentupload.txt': LayeredDocFileSuite(
            '../doc/nascentupload.txt',
            setUp=uploaderSetUp, tearDown=uploaderTearDown,
            layer=LaunchpadZopelessLayer, optionflags=default_optionflags
            ),
    'build-notification.txt': LayeredDocFileSuite(
            '../doc/build-notification.txt',
            setUp=builddmasterSetUp,
            layer=LaunchpadZopelessLayer, optionflags=default_optionflags
            ),
    'buildd-slavescanner.txt': LayeredDocFileSuite(
            '../doc/buildd-slavescanner.txt',
            setUp=builddmasterSetUp,
            layer=LaunchpadZopelessLayer, optionflags=default_optionflags,
            stdout_logging_level=logging.WARNING
            ),
    'revision.txt': LayeredDocFileSuite(
            '../doc/revision.txt',
            setUp=branchscannerSetUp, tearDown=branchscannerTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'answer-tracker-emailinterface.txt': LayeredDocFileSuite(
            '../doc/answer-tracker-emailinterface.txt',
            setUp=answerTrackerSetUp, tearDown=answerTrackerTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer,
            stdout_logging=False
            ),
    'person-karma.txt': FunctionalDocFileSuite(
            '../doc/person-karma.txt',
            setUp=setUp, tearDown=peopleKarmaTearDown,
            optionflags=default_optionflags, layer=LaunchpadFunctionalLayer,
            stdout_logging_level=logging.WARNING
            ),
    'bugnotification-sending.txt': LayeredDocFileSuite(
            '../doc/bugnotification-sending.txt',
            optionflags=default_optionflags,
            layer=LaunchpadZopelessLayer, setUp=bugNotificationSendingSetUp,
            tearDown=bugNotificationSendingTearDown
            ),
    'bugmail-headers.txt': LayeredDocFileSuite(
            '../doc/bugmail-headers.txt',
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer,
            setUp=bugNotificationSendingSetUp,
            tearDown=bugNotificationSendingTearDown),
    'branch-status-client.txt': LayeredDocFileSuite(
            '../doc/branch-status-client.txt',
            setUp=branchStatusSetUp, tearDown=branchStatusTearDown,
            layer=LaunchpadZopelessLayer
            ),
    'translationimportqueue.txt': FunctionalDocFileSuite(
            '../doc/translationimportqueue.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'pofile-pages.txt': FunctionalDocFileSuite(
            '../doc/pofile-pages.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'rosetta-karma.txt': FunctionalDocFileSuite(
            '../doc/rosetta-karma.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer
            ),
    'incomingmail.txt': FunctionalDocFileSuite(
            '../doc/incomingmail.txt',
            setUp=setUp, tearDown=tearDown, layer=LaunchpadFunctionalLayer,
            stdout_logging_level=logging.WARNING
            ),
    'launchpadform.txt': FunctionalDocFileSuite(
            '../doc/launchpadform.txt',
            setUp=setUp, tearDown=tearDown, optionflags=default_optionflags,
            layer=FunctionalLayer
            ),
    'launchpadformharness.txt': FunctionalDocFileSuite(
            '../doc/launchpadformharness.txt',
            setUp=setUp, tearDown=tearDown, optionflags=default_optionflags,
            layer=FunctionalLayer
            ),
    'bug-export.txt': LayeredDocFileSuite(
            '../doc/bug-export.txt',
            setUp=setUp, tearDown=tearDown, optionflags=default_optionflags,
            layer=LaunchpadZopelessLayer
            ),
    'uri.txt': FunctionalDocFileSuite(
            '../doc/uri.txt',
            setUp=setUp, tearDown=tearDown, optionflags=default_optionflags,
            layer=FunctionalLayer
            ),
    'package-cache.txt': LayeredDocFileSuite(
            '../doc/package-cache.txt',
            setUp=statisticianSetUp, tearDown=statisticianTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'script-monitoring.txt': LayeredDocFileSuite(
            '../doc/script-monitoring.txt',
            setUp=setUp, tearDown=tearDown, optionflags=default_optionflags,
            layer=LaunchpadZopelessLayer
            ),
    'distroseriesqueue-debian-installer.txt': FunctionalDocFileSuite(
            '../doc/distroseriesqueue-debian-installer.txt',
            setUp=distroseriesqueueSetUp, tearDown=distroseriesqueueTearDown,
            optionflags=default_optionflags,
            layer=LaunchpadFunctionalLayer
            ),
    'bug-set-status.txt': LayeredDocFileSuite(
            '../doc/bug-set-status.txt',
            setUp=uploadQueueSetUp,
            tearDown=uploadQueueTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'closing-bugs-from-changelogs.txt': LayeredDocFileSuite(
            '../doc/closing-bugs-from-changelogs.txt',
            setUp=uploadQueueSetUp,
            tearDown=uploadQueueTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'bugmessage.txt': LayeredDocFileSuite(
            '../doc/bugmessage.txt',
            setUp=noPrivSetUp, tearDown=tearDown,
            optionflags=default_optionflags, layer=LaunchpadFunctionalLayer
            ),
    'bugmessage.txt-queued': LayeredDocFileSuite(
            '../doc/bugmessage.txt',
            setUp=uploadQueueSetUp,
            tearDown=uploadQueueTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'bugmessage.txt-uploader': LayeredDocFileSuite(
            '../doc/bugmessage.txt',
            setUp=uploaderSetUp,
            tearDown=uploaderTearDown,
            optionflags=default_optionflags, layer=LaunchpadZopelessLayer
            ),
    'bug-private-by-default.txt': LayeredDocFileSuite(
            '../doc/bug-private-by-default.txt',
            setUp=setUp,
            tearDown=tearDown,
            optionflags=default_optionflags,
            layer=LaunchpadZopelessLayer
            ),
    'answer-tracker-notifications-linked-bug.txt': LayeredDocFileSuite(
            '../doc/answer-tracker-notifications-linked-bug.txt',
            setUp=bugLinkedToQuestionSetUp, tearDown=tearDown,
            optionflags=default_optionflags, layer=LaunchpadFunctionalLayer
            ),
    }


def test_suite():
    suite = unittest.TestSuite()

    # Add special needs tests
    keys = special.keys()
    keys.sort()
    for key in keys:
        special_suite = special[key]
        suite.addTest(special_suite)

    testsdir = os.path.abspath(
            os.path.normpath(os.path.join(here, '..', 'doc'))
            )

    # Add tests using default setup/teardown
    filenames = [filename
                 for filename in os.listdir(testsdir)
                 if filename.lower().endswith('.txt')
                    and filename not in special
                 ]
    # Sort the list to give a predictable order.  We do this because when
    # tests interfere with each other, the varying orderings that os.listdir
    # gives on different people's systems make reproducing and debugging
    # problems difficult.  Ideally the test harness would stop the tests from
    # being able to interfere with each other in the first place.
    #   -- Andrew Bennetts, 2005-03-01.
    filenames.sort()
    for filename in filenames:
        path = os.path.join('../doc/', filename)
        one_test = FunctionalDocFileSuite(
            path, setUp=setUp, tearDown=tearDown,
            layer=LaunchpadFunctionalLayer, optionflags=default_optionflags,
            stdout_logging_level=logging.WARNING
            )
        suite.addTest(one_test)

    return suite

if __name__ == '__main__':
    unittest.main(test_suite())
