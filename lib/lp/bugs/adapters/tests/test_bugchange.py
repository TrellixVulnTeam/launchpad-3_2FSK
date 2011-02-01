# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functional tests for request_country"""

__metaclass__ = type

from canonical.launchpad.webapp.publisher import canonical_url
from canonical.testing.layers import ZopelessDatabaseLayer
from lp.bugs.adapters.bugchange import (
    BUG_CHANGE_LOOKUP,
    BugDescriptionChange,
    get_bug_change_class,
    get_bug_changes,
    )
from lp.bugs.adapters.bugdelta import BugDelta
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.bugs.model.bugtask import BugTaskDelta
from lp.registry.enum import BugNotificationLevel
from lp.testing import TestCaseWithFactory


class BugChangeTestCase(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(BugChangeTestCase, self).setUp()

    def test_get_bug_change_class(self):
        # get_bug_change_class() should return whatever is contained
        # in BUG_CHANGE_LOOKUP for a given field name, if that field
        # name is found in BUG_CHANGE_LOOKUP.
        bug = self.factory.makeBug()
        for field_name in BUG_CHANGE_LOOKUP:
            expected = BUG_CHANGE_LOOKUP[field_name]
            received = get_bug_change_class(bug, field_name)
            self.assertEqual(
                expected, received,
                "Expected %s from get_bug_change_class() for field name %s. "
                "Got %s." % (expected, field_name, received))


class BugChangeLevelTestCase(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(BugChangeLevelTestCase, self).setUp()
        self.bug = self.factory.makeBug()
        self.bugtask = self.bug.default_bugtask
        self.user = self.factory.makePerson()

    def createDelta(self, **kwargs):
        return BugDelta(
            bug=self.bug,
            bugurl=canonical_url(self.bug),
            user=self.user,
            **kwargs)

    def test_change_level_metadata_description(self):
        # Changing a bug description is considered to have change_level
        # of BugNotificationLevel.METADATA.
        bug_delta = self.createDelta(
            description={'new': 'new description',
                         'old': self.bug.description})

        change = list(get_bug_changes(bug_delta))[0]
        self.assertTrue(isinstance(change, BugDescriptionChange))
        self.assertEquals(BugNotificationLevel.METADATA,
                          change.change_level)

    def test_change_level_lifecycle_status_closing(self):
        # Changing a bug task status from NEW to FIXRELEASED makes this
        # change a BugNotificationLevel.LIFECYCLE change.
        bugtask_delta = BugTaskDelta(
            bugtask=self.bugtask,
            status={'old': BugTaskStatus.NEW,
                    'new': BugTaskStatus.FIXRELEASED})
        bug_delta = self.createDelta(
            bugtask_deltas=bugtask_delta)

        change = list(get_bug_changes(bug_delta))[0]
        self.assertEquals(BugNotificationLevel.LIFECYCLE,
                          change.change_level)

    def test_change_level_lifecycle_status_reopening(self):
        # Changing a bug task status from FIXRELEASED to TRIAGED makes this
        # change a BugNotificationLevel.LIFECYCLE change.
        bugtask_delta = BugTaskDelta(
            bugtask=self.bugtask,
            status={'old': BugTaskStatus.FIXRELEASED,
                    'new': BugTaskStatus.TRIAGED})
        bug_delta = self.createDelta(
            bugtask_deltas=bugtask_delta)

        change = list(get_bug_changes(bug_delta))[0]
        self.assertEquals(BugNotificationLevel.LIFECYCLE,
                          change.change_level)

    def test_change_level_metadata_status_worked_on(self):
        # Changing a bug task status from TRIAGED to FIXCOMMITTED makes this
        # change a BugNotificationLevel.METADATA change.
        bugtask_delta = BugTaskDelta(
            bugtask=self.bugtask,
            status={'old': BugTaskStatus.TRIAGED,
                    'new': BugTaskStatus.FIXCOMMITTED})
        bug_delta = self.createDelta(
            bugtask_deltas=bugtask_delta)

        change = list(get_bug_changes(bug_delta))[0]
        self.assertEquals(BugNotificationLevel.METADATA,
                          change.change_level)

    def test_change_level_metadata_status_stays_closed(self):
        # Changing a bug task status from OPINION to WONTFIX makes this
        # change a BugNotificationLevel.METADATA change.
        bugtask_delta = BugTaskDelta(
            bugtask=self.bugtask,
            status={'old': BugTaskStatus.OPINION,
                    'new': BugTaskStatus.WONTFIX})
        bug_delta = self.createDelta(
            bugtask_deltas=bugtask_delta)

        change = list(get_bug_changes(bug_delta))[0]
        self.assertEquals(BugNotificationLevel.METADATA,
                          change.change_level)
