# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functional tests for request_country"""
__metaclass__ = type

import unittest

from canonical.launchpad.components.request_country import request_country
from canonical.launchpad.ftests import (
    ANONYMOUS,
    login,
    logout,
    )
from canonical.testing import LaunchpadFunctionalLayer


class RequestCountryTestCase(unittest.TestCase):
    """request_country needs functional tests because it accesses GeoIP
    using a Utility
    """
    lp = '82.211.81.179'
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)

    def tearDown(self):
        logout()

    def testRemoteAddr(self):
        country = request_country({'REMOTE_ADDR': self.lp})
        self.failUnlessEqual(country.name, u'United Kingdom')

    def testXForwardedFor(self):
        country = request_country({
                'HTTP_X_FORWARDED_FOR': self.lp,
                'REMOTE_ADDR': '1.2.3.4',
                })
        self.failUnlessEqual(country.name, u'United Kingdom')

    def testNestedProxies(self):
        country = request_country({
                'HTTP_X_FORWARDED_FOR':
                    'localhost, 127.0.0.1, %s, 1,1,1,1' % self.lp,
                })
        self.failUnlessEqual(country.name, u'United Kingdom')

    def testMissingHeaders(self):
        country = request_country({})
        self.failUnless(country is None)

    def testIgnoreLocalhost(self):
        country = request_country({'HTTP_X_FORWARDED_FOR': '127.0.0.1'})
        self.failUnless(country is None)

        country = request_country({'REMOTE_ADDR': '127.0.0.1'})
        self.failUnless(country is None)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
