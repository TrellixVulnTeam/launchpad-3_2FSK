# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.tests.breadcrumbs import (
    BaseBreadcrumbTestCase)


class TestHasSpecificationsBreadcrumbOnBlueprintsVHost(
        BaseBreadcrumbTestCase):
    """Test Breadcrumbs for IHasSpecifications on the blueprints vhost."""

    def setUp(self):
        super(TestHasSpecificationsBreadcrumbOnBlueprintsVHost, self).setUp()
        self.person = self.factory.makePerson()
        self.person_specs_url = canonical_url(
            self.person, rootsite='blueprints')
        self.product = self.factory.makeProduct(
            name='crumb-tester', displayname="Crumb Tester")
        self.product_specs_url = canonical_url(
            self.product, rootsite='blueprints')

    def test_product(self):
        crumbs = self._getBreadcrumbs(
            self.product_specs_url, [self.root, self.product])
        last_crumb = crumbs[-1]
        self.assertEquals(last_crumb.url, self.product_specs_url)
        self.assertEquals(last_crumb.text, 'Blueprints')

    def test_person(self):
        crumbs = self._getBreadcrumbs(
            self.person_specs_url, [self.root, self.person])
        last_crumb = crumbs[-1]
        self.assertEquals(last_crumb.url, self.person_specs_url)
        self.assertEquals(last_crumb.text, 'Blueprints')


class TestSpecificationBreadcrumb(BaseBreadcrumbTestCase):
    """Test breadcrumbs for an `ISpecification`."""

    def setUp(self):
        super(TestSpecificationBreadcrumb, self).setUp()
        self.product = self.factory.makeProduct(
            name='crumb-tester', displayname="Crumb Tester")
        self.specification = self.factory.makeSpecification(
            title="Crumby Specification", product=self.product)
        self.specification_url = canonical_url(
            self.specification, rootsite='blueprints')

    def test_specification(self):
        crumbs = self._getBreadcrumbs(
            self.specification_url,
            [self.root, self.product, self.specification])
        last_crumb = crumbs[-1]
        self.assertEquals(last_crumb.url, self.specification_url)
        self.assertEquals(
            last_crumb.text, self.specification.title)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

