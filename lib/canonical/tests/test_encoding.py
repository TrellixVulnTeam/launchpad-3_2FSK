# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest
from zope.testing.doctest import DocTestSuite, ELLIPSIS
import canonical.encoding

def test_suite():
    suite = DocTestSuite(canonical.encoding, optionflags=ELLIPSIS)
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
