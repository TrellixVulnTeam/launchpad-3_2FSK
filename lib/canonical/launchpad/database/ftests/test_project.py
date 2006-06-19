# Copyright 2004 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from zope.testing.doctestunit import DocTestSuite
from zope.component import getUtility
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestSetup
from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.testing import layers

def setUp(test):
    test.globs['getUtility'] = getUtility
    LaunchpadFunctionalTestSetup().setUp()
    login(ANONYMOUS)

def tearDown(test):
    LaunchpadFunctionalTestSetup().tearDown()

def test_suite():
    suite = DocTestSuite('canonical.launchpad.database.project',
            setUp=setUp, tearDown=tearDown)
    suite.layer = layers.Functional
    return suite
