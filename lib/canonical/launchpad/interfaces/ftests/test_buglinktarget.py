# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Test harness for running the buglinktarget.txt interface test

This module will run the interface test against the CVE and Ticket
implementations of that interface.
"""

__metaclass__ = type

__all__ = []

import unittest

from zope.component import getUtility

from canonical.functional import SystemDoctestLayer, FunctionalDocFileSuite
from canonical.launchpad.interfaces import ICveSet, ITicketSet
from canonical.launchpad.ftests.test_system_documentation import (
    default_optionflags, setUp, tearDown)

def ticketSetUp(test):
    setUp(test)
    test.globs['target'] = getUtility(ITicketSet).get(1)


def cveSetUp(test):
    setUp(test)
    test.globs['target'] = getUtility(ICveSet)['2005-2730']


def test_suite():
    suite = unittest.TestSuite()

    targets = [('cve', cveSetUp),
               ('ticket', ticketSetUp),
               ]

    for name, setUpMethod in targets:
        test = FunctionalDocFileSuite('buglinktarget.txt',
                    setUp=setUpMethod, tearDown=tearDown,
                    optionflags=default_optionflags, package=__name__)
        test.name = 'buglinktarget-%s.txt' % name
        test.layer = SystemDoctestLayer
        suite.addTest(test)

    #test = FunctionalDocFileSuite('tickettarget-sourcepackage.txt',
                #setUp=setUp, tearDown=tearDown,
                #optionflags=default_optionflags, package=__name__)
    #test.layer = SystemDoctestLayer
    #suite.addTest(test)
    return suite


if __name__ == '__main__':
    unittest.main()
