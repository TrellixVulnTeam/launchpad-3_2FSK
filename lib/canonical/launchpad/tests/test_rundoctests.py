# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from zope.testing.doctestunit import DocTestSuite

def test_suite():
    return DocTestSuite('canonical.launchpad.helpers')

