# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.testing import doctest

def test_suite():
    return doctest.DocTestSuite(
            'canonical.launchpad.testing.tests.googleserviceharness',
            optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS
            )
