# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Test harness for running the bugs-fixed-elsewhere.txt tests."""

__metaclass__ = type

__all__ = []

import unittest

from zope.component import getUtility

from canonical.database.sqlbase import cursor, sqlvalues
from canonical.launchpad.webapp.interfaces import ILaunchBag
from lp.bugs.interfaces.bug import CreateBugParams
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.product import IProductSet
from canonical.launchpad.ftests import login
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, setUp, tearDown)
from canonical.testing import LaunchpadFunctionalLayer


def bugtarget_filebug(bugtarget, summary):
    """File a bug as the current user on the bug target and return it."""
    return bugtarget.createBug(CreateBugParams(
        getUtility(ILaunchBag).user, summary, comment=summary))

def commonSetUp(test):
    """Set up common for all tests."""
    setUp(test)
    test.globs['filebug'] = bugtarget_filebug
    login('test@canonical.com')
    # Ensure that there are no fixed bugs in sample data that might
    # interfere with the tests.
    cur = cursor()
    cur.execute("UPDATE BugTask SET status = %s" % (
        sqlvalues(BugTaskStatus.NEW)))


def productSetUp(test):
    commonSetUp(test)
    test.globs['bugtarget'] = getUtility(IProductSet).getByName('firefox')


def distributionSetUp(test):
    commonSetUp(test)
    test.globs['bugtarget'] = getUtility(IDistributionSet).getByName('ubuntu')


def test_suite():
    suite = unittest.TestSuite()

    setUpMethods = [
        productSetUp,
        distributionSetUp,
        ]

    for setUpMethod in setUpMethods:
        test = LayeredDocFileSuite('bugs-fixed-elsewhere.txt',
            setUp=setUpMethod, tearDown=tearDown,
            layer=LaunchpadFunctionalLayer)
        suite.addTest(test)
    return suite
