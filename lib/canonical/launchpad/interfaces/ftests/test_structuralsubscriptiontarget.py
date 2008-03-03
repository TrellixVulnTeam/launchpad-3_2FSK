# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Test harness for running tests against IStructuralsubscriptionTarget
implementations.
"""

import unittest

from zope.component import getUtility

from canonical.launchpad.interfaces import (
    IDistributionSet, IProductSet)
from canonical.launchpad.interfaces.ftests.test_bugtarget import (
    bugtarget_filebug)
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, setUp, tearDown)
from canonical.testing import LaunchpadFunctionalLayer

def distributionSourcePackageSetUp(test):
    setUp(test)
    ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    test.globs['target'] = ubuntu.getSourcePackage('evolution')
    test.globs['other_target'] = ubuntu.getSourcePackage('pmount')
    test.globs['filebug'] = bugtarget_filebug

def productSetUp(test):
    setUp(test)
    test.globs['target'] = getUtility(IProductSet).getByName('firefox')
    test.globs['filebug'] = bugtarget_filebug

def distributionSetUp(test):
    setUp(test)
    test.globs['target'] = getUtility(IDistributionSet).getByName('ubuntu')
    test.globs['filebug'] = bugtarget_filebug

def milestone_filebug(milestone, summary, status=None):
    bug = bugtarget_filebug(milestone.target, summary, status=status)
    bug.bugtasks[0].milestone = milestone
    return bug

def milestoneSetUp(test):
    setUp(test)
    firefox = getUtility(IProductSet).getByName('firefox')
    test.globs['target'] = firefox.getMilestone('1.0')
    test.globs['filebug'] = milestone_filebug

def test_suite():
    """Return the `IStructuralSubscriptionTarget` TestSuite."""
    suite = unittest.TestSuite()

    setUpMethods = [
        distributionSourcePackageSetUp,
        productSetUp,
        distributionSetUp,
        milestoneSetUp,
        ]

    for setUpMethod in setUpMethods:
        test = LayeredDocFileSuite('structural-subscription-target.txt',
            setUp=setUpMethod, tearDown=tearDown,
            layer=LaunchpadFunctionalLayer)
        suite.addTest(test)

    return suite
