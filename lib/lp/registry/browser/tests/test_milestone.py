# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test milestone views."""

__metaclass__ = type

import unittest

from zope.app.form.interfaces import WidgetInputError
from zope.component import getUtility

from canonical.launchpad.validators import LaunchpadValidationError
from canonical.testing import DatabaseFunctionalLayer
from lp.testing import ANONYMOUS, login_person, login, TestCaseWithFactory
from lp.testing.views import create_initialized_view
from lp.testing.memcache import MemcacheTestCase


class TestMilestoneViews(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer 

    def setUp(self):
        #TODO: Remove sample data in favor of making a package,
        #if feasible
        TestCaseWithFactory.setUp(self)
        self.product = self.factory.makeProduct() 
        self.series = self.factory.makeSeries(product=self.product)
        owner = self.product.owner
        login_person(owner)

    def test_add_milestone(self):
        form = {
            'field.name': '1.1',
            'field.actions.register': 'Register Milestone',
        }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        self.assertEqual([], view.errors)

    def test_add_milestone_with_good_date(self):
        form = {
            'field.name': '1.1',
            'field.dateexpected': '2010-10-10',
            'field.actions.register': 'Register Milestone',
        }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        self.assertEqual([], view.errors)

    def test_add_milestone_with_bad_date(self):
        form = {
            'field.name': '1.1',
            'field.dateexpected': '1010-10-10',
            'field.actions.register': 'Register Milestone',
        }
        view = create_initialized_view(
            self.series, '+addmilestone', form=form)
        self.assertEqual([WidgetInputError('dateexpected', u'Date Targeted', LaunchpadValidationError(u'Date and time could not be formatted. Please submit date in , YYYY-MM-DD format.'))], view.errors)


class TestMilestoneMemcache(MemcacheTestCase):

    def setUp(self):
        super(TestMilestoneMemcache, self).setUp()
        product = self.factory.makeProduct()
        login_person(product.owner)
        series = self.factory.makeProductSeries(product=product)
        self.milestone = self.factory.makeMilestone(
            productseries=series, name="1.1")
        bugtask = self.factory.makeBugTask(target=product)
        bugtask.transitionToAssignee(product.owner)
        bugtask.milestone = self.milestone
        self.observer = self.factory.makePerson()

    def test_milestone_index_memcache_anonymous(self):
        # Miss the cache on first render.
        login(ANONYMOUS)
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Hit the cache on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheHit(
            '<dt>Assigned to you:</dt>',
            'anonymous, view/expire_cache_minutes minute', content)
        self.assertCacheHit(
            'id="milestone_bugtasks"',
            'anonymous, view/expire_cache_minutes minute', content)

    def test_milestone_index_memcache_no_cache_logged_in(self):
        login_person(self.observer)
        # Miss the cache on first render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Miss the cache again on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)

    def test_milestone_index_active_cache_time(self):
        # Verify the active milestone cache time.
        view = create_initialized_view(self.milestone, name='+index')
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)

    def test_milestone_index_inactive_cache_time(self):
        # Verify the inactive milestone cache time.
        self.milestone.active = False
        view = create_initialized_view(self.milestone, name='+index')
        self.assertFalse(view.milestone.active)
        self.assertEqual(360, view.expire_cache_minutes)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
