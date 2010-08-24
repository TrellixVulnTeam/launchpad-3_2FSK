# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""XXX: Module docstring goes here."""

__metaclass__ = type

import unittest

from canonical.testing import DatabaseFunctionalLayer
from lp.testing import TestCase


class TestSomething(TestCase):
    # XXX: Sample test class.  Replace with your own test class(es).

    # XXX: Optional layer--see lib/canonical/testing/layers.py
    # Get the simplest layer that your test will work on, or if you
    # don't even use the database, don't set it at all.
    layer = DatabaseFunctionalLayer

    # XXX: Sample test.  Replace with your own test methods.
    def test_baseline(self):

        # XXX: Assertions take expected value first, actual value second.
        self.assertEqual(4, 2 + 2)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
