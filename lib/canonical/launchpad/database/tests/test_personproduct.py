# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Test the Person/Product non-database class."""

__metaclass__ = type

import unittest

from canonical.launchpad.database.personproduct import PersonProduct
from lp.testing import TestCaseWithFactory
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.url import urlappend
from canonical.testing import DatabaseFunctionalLayer


class TestPersonProductCanonicalUrl(TestCaseWithFactory):
    """Tests for the canonical url of `IPersonProduct`s."""

    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        # The canonical_url of a person product is ~person/product.
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        pp = PersonProduct(person, product)
        self.assertEqual(
            urlappend(canonical_url(person),
                      product.name),
            canonical_url(pp))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

