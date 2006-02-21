# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Run launchpad.database functional doctests"""

__metaclass__ = type

import unittest
from zope.testing.doctest import DocFileSuite, DocTestSuite
from zope.testing.doctest import REPORT_NDIFF, NORMALIZE_WHITESPACE, ELLIPSIS

def test_suite():
    # XXX: Test temporarily disabled. Bug #32231 -- StuartBishop 20060221
    return None
    suite = unittest.TestSuite([
        DocFileSuite('test_adapter.txt',
                     optionflags=REPORT_NDIFF|NORMALIZE_WHITESPACE|ELLIPSIS),
        ])
    return suite

