# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Module docstring goes here."""

__metaclass__ = type

import re
import sys
import time
import unittest
import logging
from urllib2 import urlopen
from StringIO import StringIO
from datetime import datetime, timedelta
from pytz import utc

import transaction
from zope.testing import doctest
from canonical.launchpad.ftests.harness import LaunchpadFunctionalTestSetup
from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.librarian.ftests.harness import LibrarianTestSetup
from canonical.functional import FunctionalTestSetup
from canonical.testing.layers import Functional

import os.path

this_directory = os.path.dirname(__file__)

def setUp(test):
    # Suck this modules environment into the test environment
    test.globs.update(globals())
    LaunchpadFunctionalTestSetup().setUp()
    login(ANONYMOUS)

def tearDown(test):
    LibrarianTestSetup().tearDown() # Started explicitly in the doctest
    LaunchpadFunctionalTestSetup().tearDown()

def test_suite():
    suite = doctest.DocFileSuite(
            'librarianformatter.txt', setUp=setUp, tearDown=tearDown,
            optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS
            )
    suite.layer = Functional
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
