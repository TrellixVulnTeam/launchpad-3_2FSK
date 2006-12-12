# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Test harness for running the bugtarget-recently-touched-bugs.txt tests.

This module will run the tests against the all the current IBugTarget
implementations.
"""

__metaclass__ = type

__all__ = []

import unittest

from zope.component import getUtility

from canonical.functional import FunctionalDocFileSuite
from canonical.launchpad.interfaces import (
    CreateBugParams, IBugTaskSet, IDistributionSet, ILaunchBag, IProductSet,
    IProjectSet)
from canonical.launchpad.ftests.test_system_documentation import (
    default_optionflags, setUp, tearDown)
from canonical.testing import LaunchpadFunctionalLayer


def bugtarget_filebug(bugtarget, summary):
    """File a bug as the current user on the bug target and return it."""
    return bugtarget.createBug(CreateBugParams(
        getUtility(ILaunchBag).user, summary, comment=summary))


def productSetUp(test):
    setUp(test)
    test.globs['bugtarget'] = getUtility(IProductSet).getByName('firefox')
    test.globs['filebug'] = bugtarget_filebug


def project_filebug(project, summary):
    """File a bug on a project.

    Since it's not possible to file a bug on a project directly, the bug
    will be filed on one of its products.
    """
    # It doesn't matter on which product the bug is filed on.
    bug = bugtarget_filebug(project.products[0], summary)
    return bug


def projectSetUp(test):
    setUp(test)
    test.globs['bugtarget'] = getUtility(IProjectSet).getByName('mozilla')
    test.globs['filebug'] = project_filebug


def distributionSetUp(test):
    setUp(test)
    test.globs['bugtarget'] = getUtility(IDistributionSet).getByName('ubuntu')
    test.globs['filebug'] = bugtarget_filebug


def distributionSourcePackageSetUp(test):
    setUp(test)
    ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    test.globs['bugtarget'] = ubuntu.getSourcePackage('mozilla-firefox')
    test.globs['filebug'] = bugtarget_filebug


def distrorelease_filebug(distrorelease, summary, sourcepackagename=None):
    """File a bug on a distrorelease.

    Since bugs can't be filed on distroreleases directly, a bug will
    first be filed on its distribution, and then a release task will be
    added.
    """
    bug = bugtarget_filebug(distrorelease.distribution, summary)
    getUtility(IBugTaskSet).createTask(
        bug, getUtility(ILaunchBag).user, distrorelease=distrorelease,
        sourcepackagename=sourcepackagename)
    return bug


def distributionReleaseSetUp(test):
    setUp(test)
    ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    test.globs['bugtarget'] = ubuntu.getRelease('warty')
    test.globs['filebug'] = distrorelease_filebug


def sourcepackage_filebug(source_package, summary):
    """File a bug on a source package in a distrorelease."""
    bug = distrorelease_filebug(
        source_package.distrorelease, summary,
        sourcepackagename=source_package.sourcepackagename)
    return bug


def sourcePackageSetUp(test):
    setUp(test)
    ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    warty = ubuntu.getRelease('warty')
    test.globs['bugtarget'] = warty.getSourcePackage('mozilla-firefox')
    test.globs['filebug'] = sourcepackage_filebug


def test_suite():
    suite = unittest.TestSuite()

    bugtargets = [
        ('product', productSetUp),
        ('project', projectSetUp),
        ('distribution', distributionSetUp),
        ('distribution-source-package', distributionSourcePackageSetUp),
        ('distrorelease', distributionReleaseSetUp),
        ('sourcepackage', sourcePackageSetUp),
        ]

    for name, setUpMethod in bugtargets:
        test = FunctionalDocFileSuite('bugtarget-recently-touched-bugs.txt',
            setUp=setUpMethod, tearDown=tearDown,
            optionflags=default_optionflags, package=__name__,
            layer=LaunchpadFunctionalLayer)
        suite.addTest(test)
    return suite


if __name__ == '__main__':
    unittest.main()
