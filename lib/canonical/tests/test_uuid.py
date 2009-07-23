# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest
from zope.testing.doctestunit import DocTestSuite
import canonical.uuid

def test_suite():
    suite = DocTestSuite(canonical.uuid)
    return suite

if __name__ == "__main__":
    DEFAULT = test_suite()
    unittest.main(defaultTest='DEFAULT')

