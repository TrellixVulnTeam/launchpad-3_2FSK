# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from zope.component import getUtility

from lp.bugs.interfaces.bugtask import IBugTaskSet
from lp.bugs.model.bugsummary import RawBugSummary
from lp.bugs.model.bugtaskflat import BugTaskFlat
from lp.bugs.scripts.bugsummaryrebuild import (
    calculate_bugsummary_rows,
    format_target,
    get_bugsummary_rows,
    get_bugsummary_targets,
    get_bugtask_targets,
    )
from lp.registry.enums import InformationType
from lp.services.database.lpstorm import IStore
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


def rollup_journal():
    IStore(RawBugSummary).execute('SELECT bugsummary_rollup_journal()')


def create_tasks(factory):
    ps = factory.makeProductSeries()
    product = ps.product
    sp = factory.makeSourcePackage(publish=True)

    bug = factory.makeBug(product=product)
    getUtility(IBugTaskSet).createManyTasks(
        bug, bug.owner, [sp, sp.distribution_sourcepackage, ps])

    # There'll be a target for each task, plus a packageless one for
    # each package task.
    expected_targets = [
        (ps.product.id, None, None, None, None),
        (None, ps.id, None, None, None),
        (None, None, sp.distribution.id, None, None),
        (None, None, sp.distribution.id, None, sp.sourcepackagename.id),
        (None, None, None, sp.distroseries.id, None),
        (None, None, None, sp.distroseries.id, sp.sourcepackagename.id)
        ]
    return expected_targets


class TestBugSummaryRebuild(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_get_bugsummary_targets(self):
        # get_bugsummary_targets returns the set of target tuples that are
        # currently represented in BugSummary.
        orig_targets = get_bugsummary_targets()
        expected_targets = create_tasks(self.factory)
        rollup_journal()
        new_targets = get_bugsummary_targets()
        self.assertContentEqual(expected_targets, new_targets - orig_targets)

    def test_get_bugtask_targets(self):
        # get_bugtask_targets returns the set of target tuples that are
        # currently represented in BugTask.
        orig_targets = get_bugtask_targets()
        expected_targets = create_tasks(self.factory)
        new_targets = get_bugtask_targets()
        self.assertContentEqual(expected_targets, new_targets - orig_targets)


class TestGetBugSummaryRows(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_get_bugsummary_rows(self):
        product = self.factory.makeProduct()
        rollup_journal()
        orig_rows = get_bugsummary_rows(
            RawBugSummary.product_id == product.id)
        task = self.factory.makeBug(product=product).default_bugtask
        rollup_journal()
        new_rows = get_bugsummary_rows(
            RawBugSummary.product_id == product.id)
        self.assertContentEqual(
            [(product.id, None, None, None, None, None, task.status,
              task.importance, None, None, False, 1)],
            new_rows - orig_rows)


class TestCalculateBugSummaryRows(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_public_untagged(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product).default_bugtask
        self.assertContentEqual(
            [(bug.status, None, bug.importance, False, None, None, 1)],
            calculate_bugsummary_rows(BugTaskFlat.product_id == product.id))

    def test_public_tagged(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(
            product=product, tags=[u'foo', u'bar']).default_bugtask
        self.assertContentEqual(
            [(bug.status, None, bug.importance, False, None, None, 1),
             (bug.status, None, bug.importance, False, u'foo', None, 1),
             (bug.status, None, bug.importance, False, u'bar', None, 1)],
            calculate_bugsummary_rows(BugTaskFlat.product_id == product.id))

    def test_private_untagged(self):
        product = self.factory.makeProduct()
        owner = self.factory.makePerson()
        bug = self.factory.makeBug(
            product=product, owner=owner,
            information_type=InformationType.USERDATA).default_bugtask
        self.assertContentEqual(
            [(bug.status, None, bug.importance, False, None, owner.id, 1)],
            calculate_bugsummary_rows(BugTaskFlat.product_id == product.id))

    def test_private_tagged(self):
        product = self.factory.makeProduct()
        owner = self.factory.makePerson()
        bug = self.factory.makeBug(
            product=product, owner=owner, tags=[u'foo', u'bar'],
            information_type=InformationType.USERDATA).default_bugtask
        self.assertContentEqual(
            [(bug.status, None, bug.importance, False, None, owner.id, 1),
             (bug.status, None, bug.importance, False, u'foo', owner.id, 1),
             (bug.status, None, bug.importance, False, u'bar', owner.id, 1)],
            calculate_bugsummary_rows(BugTaskFlat.product_id == product.id))


class TestFormatTarget(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_product(self):
        product = self.factory.makeProduct(name='fooix')
        self.assertEqual('fooix', format_target(product))

    def test_productseries(self):
        productseries = self.factory.makeProductSeries(
            product=self.factory.makeProduct(name='fooix'), name='1.0')
        self.assertEqual('fooix/1.0', format_target(productseries))

    def test_distribution(self):
        distribution = self.factory.makeDistribution(name='fooix')
        self.assertEqual('fooix', format_target(distribution))

    def test_distroseries(self):
        distroseries = self.factory.makeDistroSeries(
            distribution=self.factory.makeDistribution(name='fooix'),
            name='1.0')
        self.assertEqual('fooix/1.0', format_target(distroseries))

    def test_distributionsourcepackage(self):
        distribution = self.factory.makeDistribution(name='fooix')
        dsp = distribution.getSourcePackage(
            self.factory.makeSourcePackageName('bar'))
        self.assertEqual('fooix/+source/bar', format_target(dsp))

    def test_sourcepackage(self):
        distroseries = self.factory.makeDistroSeries(
            distribution=self.factory.makeDistribution(name='fooix'),
            name='1.0')
        sp = distroseries.getSourcePackage(
            self.factory.makeSourcePackageName('bar'))
        self.assertEqual('fooix/1.0/+source/bar', format_target(sp))
