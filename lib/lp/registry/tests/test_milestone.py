# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Milestone related test helper."""

__metaclass__ = type

from operator import attrgetter
import unittest

from zope.component import getUtility

from canonical.launchpad.ftests import (
    ANONYMOUS,
    login,
    logout,
    )
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.app.errors import NotFoundError
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.milestone import (
    IHasMilestones,
    IMilestoneSet,
    )
from lp.registry.interfaces.product import IProductSet
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.matchers import DoesNotSnapshot


class MilestoneTest(unittest.TestCase):
    """Milestone tests."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)

    def tearDown(self):
        logout()

    def testMilestoneSetIterator(self):
        """Test of MilestoneSet.__iter__()."""
        all_milestones_ids = set(
            milestone.id for milestone in getUtility(IMilestoneSet))
        self.assertEqual(all_milestones_ids,
                         set((1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)))

    def testMilestoneSetGet(self):
        """Test of MilestoneSet.get()"""
        milestone_set = getUtility(IMilestoneSet)
        self.assertEqual(milestone_set.get(1).id, 1)
        self.assertRaises(NotFoundError, milestone_set.get, 100000)

    def testMilestoneSetGetIDs(self):
        """Test of MilestoneSet.getByIds()"""
        milestone_set = getUtility(IMilestoneSet)
        milestones = milestone_set.getByIds([1,3])
        ids = sorted(map(attrgetter('id'), milestones))
        self.assertEqual([1, 3], ids)

    def testMilestoneSetGetByIDs_ignores_missing(self):
        milestone_set = getUtility(IMilestoneSet)
        self.assertEqual([], list(milestone_set.getByIds([100000])))

    def testMilestoneSetGetByNameAndProduct(self):
        """Test of MilestoneSet.getByNameAndProduct()"""
        firefox = getUtility(IProductSet).getByName('firefox')
        milestone_set = getUtility(IMilestoneSet)
        milestone = milestone_set.getByNameAndProduct('1.0', firefox)
        self.assertEqual(milestone.name, '1.0')
        self.assertEqual(milestone.target, firefox)

        marker = object()
        milestone = milestone_set.getByNameAndProduct(
            'does not exist', firefox, default=marker)
        self.assertEqual(milestone, marker)

    def testMilestoneSetGetByNameAndDistribution(self):
        """Test of MilestoneSet.getByNameAndDistribution()"""
        debian = getUtility(IDistributionSet).getByName('debian')
        milestone_set = getUtility(IMilestoneSet)
        milestone = milestone_set.getByNameAndDistribution('3.1', debian)
        self.assertEqual(milestone.name, '3.1')
        self.assertEqual(milestone.target, debian)

        marker = object()
        milestone = milestone_set.getByNameAndDistribution(
            'does not exist', debian, default=marker)
        self.assertEqual(milestone, marker)

    def testMilestoneSetGetVisibleMilestones(self):
        all_visible_milestones_ids = [
            milestone.id
            for milestone in getUtility(IMilestoneSet).getVisibleMilestones()]
        self.assertEqual(
            all_visible_milestones_ids,
            [1, 2, 3])


class HasMilestonesSnapshotTestCase(TestCaseWithFactory):
    """A TestCase for snapshots of pillars with milestones."""

    layer = DatabaseFunctionalLayer

    def check_skipped(self, target):
        """Asserts that fields marked doNotSnapshot are skipped."""
        skipped = [
            'milestones',
            'all_milestones',
            ]
        self.assertThat(target, DoesNotSnapshot(skipped, IHasMilestones))

    def test_product(self):
        product = self.factory.makeProduct()
        self.check_skipped(product)

    def test_distribution(self):
        distribution = self.factory.makeDistribution()
        self.check_skipped(distribution)

    def test_distroseries(self):
        distroseries = self.factory.makeDistroSeries()
        self.check_skipped(distroseries)

    def test_projectgroup(self):
        projectgroup = self.factory.makeProject()
        self.check_skipped(projectgroup)


class MilestoneBugTaskTest(TestCaseWithFactory):
    """Test cases for retrieving bugtasks for a milestone."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(MilestoneBugTaskTest, self).setUp()
        self.owner = self.factory.makePerson()
        self.product = self.factory.makeProduct(name="product1")
        self.milestone = self.factory.makeMilestone(product=self.product)

    def _create_bugtasks(self, num, milestone=None):
        bugtasks = []
        with person_logged_in(self.owner):
            for n in xrange(num):
                bugtask = self.factory.makeBugTask(
                    target=self.product,
                    owner=self.owner)
                if milestone:
                    bugtask.milestone = milestone
                bugtasks.append(bugtask)
        return bugtasks

    def test_bugtask_retrieval(self):
        # Ensure that all bugtasks on a milestone can be retrieved.
        bugtasks = self._create_bugtasks(5, self.milestone)
        self.assertContentEqual(
            bugtasks,
            self.milestone.bugtasks(self.owner))


class MilestoneSpecificationTest(TestCaseWithFactory):
    """Test cases for retrieving specifications for a milestone."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(MilestoneSpecificationTest, self).setUp()
        self.owner = self.factory.makePerson()
        self.product = self.factory.makeProduct(name="product1")
        self.milestone = self.factory.makeMilestone(product=self.product)

    def _create_specifications(self, num, milestone=None):
        specifications = []
        with person_logged_in(self.owner):
            for n in xrange(num):
                specification = self.factory.makeSpecification(
                    product=self.product,
                    owner=self.owner,
                    milestone=milestone)
                specifications.append(specification)
        return specifications

    def test_specification_retrieval(self):
        # Ensure that all specifications on a milestone can be retrieved.
        specifications = self._create_specifications(5, self.milestone)
        self.assertContentEqual(
            specifications,
            self.milestone.specifications)
