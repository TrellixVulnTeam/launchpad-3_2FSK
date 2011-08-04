# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from datetime import timedelta
import unittest

from lazr.lifecycle.event import ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import Equals
from zope.component import getUtility
from zope.event import notify
from zope.interface import providedBy
from zope.security.proxy import removeSecurityProxy

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.searchbuilder import (
    all,
    any,
    )
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.app.enums import ServiceUsage
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.interfaces.bugtarget import IBugTarget
from lp.bugs.interfaces.bugtask import (
    BugTaskImportance,
    BugTaskSearchParams,
    BugTaskStatus,
    IBugTaskSet,
    RESOLVED_BUGTASK_STATUSES,
    UNRESOLVED_BUGTASK_STATUSES,
    )
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.model.bugtask import (
    bug_target_from_key,
    bug_target_to_key,
    build_tag_search_clause,
    IllegalTarget,
    validate_new_target,
    validate_target,
    )
from lp.bugs.tests.bug import (
    create_old_bug,
    )
from lp.hardwaredb.interfaces.hwdb import (
    HWBus,
    IHWDeviceSet,
    )
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    )
from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.projectgroup import IProjectGroupSet
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.testing import (
    ANONYMOUS,
    EventRecorder,
    feature_flags,
    login,
    login_person,
    logout,
    normalize_whitespace,
    person_logged_in,
    set_feature_flag,
    StormStatementRecorder,
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.matchers import HasQueryCount


class TestBugTaskDelta(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugTaskDelta, self).setUp()
        login('foo.bar@canonical.com')

    def test_get_empty_delta(self):
        # getDelta() should return None when no change has been made.
        bug_task = self.factory.makeBugTask()
        self.assertEqual(bug_task.getDelta(bug_task), None)

    def check_delta(self, bug_task_before, bug_task_after, **expected_delta):
        # Get a delta between one bug task and another, then compare
        # the contents of the delta with expected_delta (a dict, or
        # something that can be dictified). Anything not mentioned in
        # expected_delta is assumed to be None in the delta.
        delta = bug_task_after.getDelta(bug_task_before)
        expected_delta.setdefault('bugtask', bug_task_after)
        names = set(
            name for interface in providedBy(delta) for name in interface)
        for name in names:
            self.assertEquals(
                getattr(delta, name), expected_delta.get(name))

    def test_get_bugwatch_delta(self):
        # Exercise getDelta() with a change to bugwatch.
        bug_task = self.factory.makeBugTask()
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        bug_watch = self.factory.makeBugWatch(bug=bug_task.bug)
        bug_task.bugwatch = bug_watch

        self.check_delta(
            bug_task_before_modification, bug_task,
            bugwatch=dict(old=None, new=bug_watch))

    def test_get_target_delta(self):
        # Exercise getDelta() with a change to target.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        bug_task = self.factory.makeBugTask(target=product)
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        new_product = self.factory.makeProduct(owner=user)
        bug_task.transitionToTarget(new_product)

        self.check_delta(
            bug_task_before_modification, bug_task,
            target=dict(old=product, new=new_product))

    def test_get_milestone_delta(self):
        # Exercise getDelta() with a change to milestone.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        bug_task = self.factory.makeBugTask(target=product)
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        milestone = self.factory.makeMilestone(product=product)
        bug_task.milestone = milestone

        self.check_delta(
            bug_task_before_modification, bug_task,
            milestone=dict(old=None, new=milestone))

    def test_get_assignee_delta(self):
        # Exercise getDelta() with a change to assignee.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        bug_task = self.factory.makeBugTask(target=product)
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        bug_task.transitionToAssignee(user)

        self.check_delta(
            bug_task_before_modification, bug_task,
            assignee=dict(old=None, new=user))

    def test_get_status_delta(self):
        # Exercise getDelta() with a change to status.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        bug_task = self.factory.makeBugTask(target=product)
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        bug_task.transitionToStatus(BugTaskStatus.FIXRELEASED, user)

        self.check_delta(
            bug_task_before_modification, bug_task,
            status=dict(old=bug_task_before_modification.status,
                        new=bug_task.status))

    def test_get_importance_delta(self):
        # Exercise getDelta() with a change to importance.
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        bug_task = self.factory.makeBugTask(target=product)
        bug_task_before_modification = Snapshot(
            bug_task, providing=providedBy(bug_task))

        bug_task.transitionToImportance(BugTaskImportance.HIGH, user)

        self.check_delta(
            bug_task_before_modification, bug_task,
            importance=dict(old=bug_task_before_modification.importance,
                            new=bug_task.importance))


class TestBugTaskTagSearchClauses(TestCase):

    def searchClause(self, tag_spec):
        return build_tag_search_clause(tag_spec)

    def assertEqualIgnoringWhitespace(self, expected, observed):
        return self.assertEqual(
            normalize_whitespace(expected),
            normalize_whitespace(observed))

    def test_empty(self):
        # Specifying no tags is valid.
        self.assertEqual(self.searchClause(any()), None)
        self.assertEqual(self.searchClause(all()), None)

    def test_single_tag_presence_any(self):
        # The WHERE clause to test for the presence of a single
        # tag where at least one tag is desired.
        expected_query = (
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag IN ('fred'))""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(any(u'fred')))

    def test_single_tag_presence_all(self):
        # The WHERE clause to test for the presence of a single
        # tag where all tags are desired.
        expected_query = (
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(all(u'fred')))

    def test_single_tag_absence_any(self):
        # The WHERE clause to test for the absence of a single
        # tag where at least one tag is desired.
        expected_query = (
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(any(u'-fred')))

    def test_single_tag_absence_all(self):
        # The WHERE clause to test for the absence of a single
        # tag where all tags are desired.
        expected_query = (
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag IN ('fred'))""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(all(u'-fred')))

    def test_tag_presence(self):
        # The WHERE clause to test for the presence of tags. Should be
        # the same for an `any` query or an `all` query.
        expected_query = (
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id)""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(any(u'*')))
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(all(u'*')))

    def test_tag_absence(self):
        # The WHERE clause to test for the absence of tags. Should be
        # the same for an `any` query or an `all` query.
        expected_query = (
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id)""")
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(any(u'-*')))
        self.assertEqualIgnoringWhitespace(
            expected_query,
            self.searchClause(all(u'-*')))

    def test_multiple_tag_presence_any(self):
        # The WHERE clause to test for the presence of *any* of
        # several tags.
        self.assertEqualIgnoringWhitespace(
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag IN ('bob', 'fred'))""",
            self.searchClause(any(u'fred', u'bob')))
        # In an `any` query, a positive wildcard is dominant over
        # other positive tags because "bugs with one or more tags" is
        # a superset of "bugs with a specific tag".
        self.assertEqualIgnoringWhitespace(
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id)""",
            self.searchClause(any(u'fred', u'*')))

    def test_multiple_tag_absence_any(self):
        # The WHERE clause to test for the absence of *any* of several
        # tags.
        self.assertEqualIgnoringWhitespace(
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'bob'
                  INTERSECT
                  SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""",
            self.searchClause(any(u'-fred', u'-bob')))
        # In an `any` query, a negative wildcard is superfluous in the
        # presence of other negative tags because "bugs without a
        # specific tag" is a superset of "bugs without any tags".
        self.assertEqualIgnoringWhitespace(
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""",
            self.searchClause(any(u'-fred', u'-*')))

    def test_multiple_tag_presence_all(self):
        # The WHERE clause to test for the presence of *all* specified
        # tags.
        self.assertEqualIgnoringWhitespace(
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'bob'
                  INTERSECT
                  SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""",
            self.searchClause(all(u'fred', u'bob')))
        # In an `all` query, a positive wildcard is superfluous in the
        # presence of other positive tags because "bugs with a
        # specific tag" is a subset of (i.e. more specific than) "bugs
        # with one or more tags".
        self.assertEqualIgnoringWhitespace(
            """EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag = 'fred')""",
            self.searchClause(all(u'fred', u'*')))

    def test_multiple_tag_absence_all(self):
        # The WHERE clause to test for the absence of all specified
        # tags.
        self.assertEqualIgnoringWhitespace(
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id
                     AND BugTag.tag IN ('bob', 'fred'))""",
            self.searchClause(all(u'-fred', u'-bob')))
        # In an `all` query, a negative wildcard is dominant over
        # other negative tags because "bugs without any tags" is a
        # subset of (i.e. more specific than) "bugs without a specific
        # tag".
        self.assertEqualIgnoringWhitespace(
            """NOT EXISTS
                 (SELECT TRUE FROM BugTag
                   WHERE BugTag.bug = Bug.id)""",
            self.searchClause(all(u'-fred', u'-*')))

    def test_mixed_tags_any(self):
        # The WHERE clause to test for the presence of one or more
        # specific tags or the absence of one or more other specific
        # tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('fred'))
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'bob'))""",
            self.searchClause(any(u'fred', u'-bob')))
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('eric', 'fred'))
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'bob'
                   INTERSECT
                   SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'harry'))""",
            self.searchClause(any(u'fred', u'-bob', u'eric', u'-harry')))
        # The positive wildcard is dominant over other positive tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id)
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'bob'
                   INTERSECT
                   SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'harry'))""",
            self.searchClause(any(u'fred', u'-bob', u'*', u'-harry')))
        # The negative wildcard is superfluous in the presence of
        # other negative tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('eric', 'fred'))
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'bob'))""",
            self.searchClause(any(u'fred', u'-bob', u'eric', u'-*')))
        # The negative wildcard is not superfluous in the absence of
        # other negative tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('eric', 'fred'))
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id))""",
            self.searchClause(any(u'fred', u'-*', u'eric')))
        # The positive wildcard is dominant over other positive tags,
        # and the negative wildcard is superfluous in the presence of
        # other negative tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id)
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'harry'))""",
            self.searchClause(any(u'fred', u'-*', u'*', u'-harry')))

    def test_mixed_tags_all(self):
        # The WHERE clause to test for the presence of one or more
        # specific tags and the absence of one or more other specific
        # tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'fred')
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('bob')))""",
            self.searchClause(all(u'fred', u'-bob')))
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'eric'
                   INTERSECT
                   SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'fred')
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('bob', 'harry')))""",
            self.searchClause(all(u'fred', u'-bob', u'eric', u'-harry')))
        # The positive wildcard is superfluous in the presence of
        # other positive tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'fred')
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('bob', 'harry')))""",
            self.searchClause(all(u'fred', u'-bob', u'*', u'-harry')))
        # The positive wildcard is not superfluous in the absence of
        # other positive tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id)
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag IN ('bob', 'harry')))""",
            self.searchClause(all(u'-bob', u'*', u'-harry')))
        # The negative wildcard is dominant over other negative tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'eric'
                   INTERSECT
                   SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'fred')
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id))""",
            self.searchClause(all(u'fred', u'-bob', u'eric', u'-*')))
        # The positive wildcard is superfluous in the presence of
        # other positive tags, and the negative wildcard is dominant
        # over other negative tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id
                      AND BugTag.tag = 'fred')
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id))""",
            self.searchClause(all(u'fred', u'-*', u'*', u'-harry')))

    def test_mixed_wildcards(self):
        # The WHERE clause to test for the presence of tags or the
        # absence of tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id)
                OR NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id))""",
            self.searchClause(any(u'*', u'-*')))
        # The WHERE clause to test for the presence of tags and the
        # absence of tags.
        self.assertEqualIgnoringWhitespace(
            """(EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id)
                AND NOT EXISTS
                  (SELECT TRUE FROM BugTag
                    WHERE BugTag.bug = Bug.id))""",
            self.searchClause(all(u'*', u'-*')))


class TestBugTaskHardwareSearch(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestBugTaskHardwareSearch, self).setUp()
        self.layer.switchDbUser('launchpad')

    def test_search_results_without_duplicates(self):
        # Searching for hardware related bugtasks returns each
        # matching task exactly once, even if devices from more than
        # one HWDB submission match the given criteria.
        new_submission = self.factory.makeHWSubmission(
            emailaddress=u'test@canonical.com')
        self.layer.txn.commit()
        device = getUtility(IHWDeviceSet).getByDeviceID(
            HWBus.PCI, '0x10de', '0x0455')
        self.layer.switchDbUser('hwdb-submission-processor')
        self.factory.makeHWSubmissionDevice(
            new_submission, device, None, None, 1)
        self.layer.txn.commit()
        self.layer.switchDbUser('launchpad')
        search_params = BugTaskSearchParams(
            user=None, hardware_bus=HWBus.PCI, hardware_vendor_id='0x10de',
            hardware_product_id='0x0455', hardware_owner_is_bug_reporter=True)
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        bugtasks = ubuntu.searchTasks(search_params)
        self.assertEqual(
            [1, 2],
            [bugtask.bug.id for bugtask in bugtasks])


class TestBugTaskPermissionsToSetAssigneeMixin:

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Create the test setup.

        We need
        - bug task targets (a product and a product series, or
          a distribution and distoseries, see classes derived from
          this one)
        - persons and team with special roles: product and distribution,
          owners, bug supervisors, drivers
        - bug tasks for the targets
        """
        super(TestBugTaskPermissionsToSetAssigneeMixin, self).setUp()
        self.target_owner_member = self.factory.makePerson()
        self.target_owner_team = self.factory.makeTeam(
            owner=self.target_owner_member)
        self.regular_user = self.factory.makePerson()

        login_person(self.target_owner_member)
        # Target and bug supervisor creation are deferred to sub-classes.
        self.makeTarget()
        self.setBugSupervisor()

        self.driver_team = self.factory.makeTeam(
            owner=self.target_owner_member)
        self.driver_member = self.factory.makePerson()
        self.driver_team.addMember(
            self.driver_member, self.target_owner_member)
        self.target.driver = self.driver_team

        self.series_driver_team = self.factory.makeTeam(
            owner=self.target_owner_member)
        self.series_driver_member = self.factory.makePerson()
        self.series_driver_team.addMember(
            self.series_driver_member, self.target_owner_member)
        self.series.driver = self.series_driver_team

        self.series_bugtask = self.factory.makeBugTask(target=self.series)
        self.series_bugtask.transitionToAssignee(self.regular_user)
        bug = self.series_bugtask.bug
        # If factory.makeBugTask() is called with a series target, it
        # creates automatically another bug task for the main target.
        self.target_bugtask = bug.getBugTask(self.target)
        self.target_bugtask.transitionToAssignee(self.regular_user)
        logout()

    def makeTarget(self):
        """Create a target and a series.

        The target and series must be assigned as attributes of self:
        'self.target' and 'self.series'.
        """
        raise NotImplementedError(self.makeTarget)

    def setBugSupervisor(self):
        """Set bug supervisor variables.

        This is the standard interface for sub-classes, but this
        method should return _setBugSupervisorData or
        _setBugSupervisorDataNone depending on what is required.
        """
        raise NotImplementedError(self.setBugSupervisor)

    def _setBugSupervisorData(self):
        """Helper function used by sub-classes to setup bug supervisors."""
        self.supervisor_team = self.factory.makeTeam(
            owner=self.target_owner_member)
        self.supervisor_member = self.factory.makePerson()
        self.supervisor_team.addMember(
            self.supervisor_member, self.target_owner_member)
        self.target.setBugSupervisor(
            self.supervisor_team, self.target_owner_member)

    def _setBugSupervisorDataNone(self):
        """Helper for sub-classes to work around setting a bug supervisor."""
        self.supervisor_member = None

    def test_userCanSetAnyAssignee_anonymous_user(self):
        # Anonymous users cannot set anybody as an assignee.
        login(ANONYMOUS)
        self.assertFalse(self.target_bugtask.userCanSetAnyAssignee(None))
        self.assertFalse(self.series_bugtask.userCanSetAnyAssignee(None))

    def test_userCanUnassign_anonymous_user(self):
        # Anonymous users cannot unassign anyone.
        login(ANONYMOUS)
        self.assertFalse(self.target_bugtask.userCanUnassign(None))
        self.assertFalse(self.series_bugtask.userCanUnassign(None))

    def test_userCanSetAnyAssignee_regular_user(self):
        # If we have a bug supervisor, check that regular user cannot
        # assign to someone else.  Otherwise, the regular user should
        # be able to assign to anyone.
        login_person(self.regular_user)
        if self.supervisor_member is not None:
            self.assertFalse(
                self.target_bugtask.userCanSetAnyAssignee(self.regular_user))
            self.assertFalse(
                self.series_bugtask.userCanSetAnyAssignee(self.regular_user))
        else:
            self.assertTrue(
                self.target_bugtask.userCanSetAnyAssignee(self.regular_user))
            self.assertTrue(
                self.series_bugtask.userCanSetAnyAssignee(self.regular_user))

    def test_userCanUnassign_regular_user(self):
        # Ordinary users can unassign themselves...
        login_person(self.regular_user)
        self.assertEqual(self.target_bugtask.assignee, self.regular_user)
        self.assertEqual(self.series_bugtask.assignee, self.regular_user)
        self.assertTrue(
            self.target_bugtask.userCanUnassign(self.regular_user))
        self.assertTrue(
            self.series_bugtask.userCanUnassign(self.regular_user))
        # ...but not other assignees.
        login_person(self.target_owner_member)
        other_user = self.factory.makePerson()
        self.series_bugtask.transitionToAssignee(other_user)
        self.target_bugtask.transitionToAssignee(other_user)
        login_person(self.regular_user)
        self.assertFalse(
            self.target_bugtask.userCanUnassign(self.regular_user))
        self.assertFalse(
            self.series_bugtask.userCanUnassign(self.regular_user))

    def test_userCanSetAnyAssignee_target_owner(self):
        # The bug task target owner can assign anybody.
        login_person(self.target_owner_member)
        self.assertTrue(
            self.target_bugtask.userCanSetAnyAssignee(self.target.owner))
        self.assertTrue(
            self.series_bugtask.userCanSetAnyAssignee(self.target.owner))

    def test_userCanUnassign_target_owner(self):
        # The target owner can unassign anybody.
        login_person(self.target_owner_member)
        self.assertTrue(
            self.target_bugtask.userCanUnassign(self.target_owner_member))
        self.assertTrue(
            self.series_bugtask.userCanUnassign(self.target_owner_member))

    def test_userCanSetAnyAssignee_bug_supervisor(self):
        # A bug supervisor can assign anybody.
        if self.supervisor_member is not None:
            login_person(self.supervisor_member)
            self.assertTrue(
                self.target_bugtask.userCanSetAnyAssignee(
                    self.supervisor_member))
            self.assertTrue(
                self.series_bugtask.userCanSetAnyAssignee(
                    self.supervisor_member))

    def test_userCanUnassign_bug_supervisor(self):
        # A bug supervisor can unassign anybody.
        if self.supervisor_member is not None:
            login_person(self.supervisor_member)
            self.assertTrue(
                self.target_bugtask.userCanUnassign(self.supervisor_member))
            self.assertTrue(
                self.series_bugtask.userCanUnassign(self.supervisor_member))

    def test_userCanSetAnyAssignee_driver(self):
        # A project driver can assign anybody.
        login_person(self.driver_member)
        self.assertTrue(
            self.target_bugtask.userCanSetAnyAssignee(self.driver_member))
        self.assertTrue(
            self.series_bugtask.userCanSetAnyAssignee(self.driver_member))

    def test_userCanUnassign_driver(self):
        # A project driver can unassign anybody.
        login_person(self.driver_member)
        self.assertTrue(
            self.target_bugtask.userCanUnassign(self.driver_member))
        self.assertTrue(
            self.series_bugtask.userCanUnassign(self.driver_member))

    def test_userCanSetAnyAssignee_series_driver(self):
        # A series driver can assign anybody to series bug tasks.
        login_person(self.driver_member)
        self.assertTrue(
            self.series_bugtask.userCanSetAnyAssignee(
                self.series_driver_member))
        if self.supervisor_member is not None:
            # But he cannot assign anybody to bug tasks of the main target...
            self.assertFalse(
                self.target_bugtask.userCanSetAnyAssignee(
                    self.series_driver_member))
        else:
            # ...unless a bug supervisor is not set.
            self.assertTrue(
                self.target_bugtask.userCanSetAnyAssignee(
                    self.series_driver_member))

    def test_userCanUnassign_series_driver(self):
        # The target owner can unassign anybody from series bug tasks...
        login_person(self.series_driver_member)
        self.assertTrue(
            self.series_bugtask.userCanUnassign(self.series_driver_member))
        # ...but not from tasks of the main product/distribution.
        self.assertFalse(
            self.target_bugtask.userCanUnassign(self.series_driver_member))

    def test_userCanSetAnyAssignee_launchpad_admins(self):
        # Launchpad admins can assign anybody.
        login_person(self.target_owner_member)
        foo_bar = getUtility(IPersonSet).getByEmail('foo.bar@canonical.com')
        login_person(foo_bar)
        self.assertTrue(self.target_bugtask.userCanSetAnyAssignee(foo_bar))
        self.assertTrue(self.series_bugtask.userCanSetAnyAssignee(foo_bar))

    def test_userCanUnassign_launchpad_admins(self):
        # Launchpad admins can unassign anybody.
        login_person(self.target_owner_member)
        foo_bar = getUtility(IPersonSet).getByEmail('foo.bar@canonical.com')
        login_person(foo_bar)
        self.assertTrue(self.target_bugtask.userCanUnassign(foo_bar))
        self.assertTrue(self.series_bugtask.userCanUnassign(foo_bar))

    def test_userCanSetAnyAssignee_bug_importer(self):
        # The bug importer celebrity can assign anybody.
        login_person(self.target_owner_member)
        bug_importer = getUtility(ILaunchpadCelebrities).bug_importer
        login_person(bug_importer)
        self.assertTrue(
            self.target_bugtask.userCanSetAnyAssignee(bug_importer))
        self.assertTrue(
            self.series_bugtask.userCanSetAnyAssignee(bug_importer))

    def test_userCanUnassign_launchpad_bug_importer(self):
        # The bug importer celebrity can unassign anybody.
        login_person(self.target_owner_member)
        bug_importer = getUtility(ILaunchpadCelebrities).bug_importer
        login_person(bug_importer)
        self.assertTrue(self.target_bugtask.userCanUnassign(bug_importer))
        self.assertTrue(self.series_bugtask.userCanUnassign(bug_importer))


class TestProductBugTaskPermissionsToSetAssignee(
    TestBugTaskPermissionsToSetAssigneeMixin, TestCaseWithFactory):

    def makeTarget(self):
        """Create a product and a product series."""
        self.target = self.factory.makeProduct(owner=self.target_owner_team)
        self.series = self.factory.makeProductSeries(self.target)

    def setBugSupervisor(self):
        """Establish a bug supervisor for this target."""
        self._setBugSupervisorData()


class TestProductNoBugSupervisorBugTaskPermissionsToSetAssignee(
    TestBugTaskPermissionsToSetAssigneeMixin, TestCaseWithFactory):

    def makeTarget(self):
        """Create a product and a product series without a bug supervisor."""
        self.target = self.factory.makeProduct(owner=self.target_owner_team)
        self.series = self.factory.makeProductSeries(self.target)

    def setBugSupervisor(self):
        """Set bug supervisor to None."""
        self._setBugSupervisorDataNone()


class TestDistributionBugTaskPermissionsToSetAssignee(
    TestBugTaskPermissionsToSetAssigneeMixin, TestCaseWithFactory):

    def makeTarget(self):
        """Create a distribution and a distroseries."""
        self.target = self.factory.makeDistribution(
            owner=self.target_owner_team)
        self.series = self.factory.makeDistroSeries(self.target)

    def setBugSupervisor(self):
        """Set bug supervisor to None."""
        self._setBugSupervisorData()


class TestDistributionNoBugSupervisorBugTaskPermissionsToSetAssignee(
    TestBugTaskPermissionsToSetAssigneeMixin, TestCaseWithFactory):

    def makeTarget(self):
        """Create a distribution and a distroseries."""
        self.target = self.factory.makeDistribution(
            owner=self.target_owner_team)
        self.series = self.factory.makeDistroSeries(self.target)

    def setBugSupervisor(self):
        """Establish a bug supervisor for this target."""
        self._setBugSupervisorDataNone()


class TestBugTaskSearch(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def login(self):
        # Log in as an arbitrary person.
        person = self.factory.makePerson()
        login_person(person)
        self.addCleanup(logout)
        return person

    def makeBugTarget(self):
        """Make an arbitrary bug target with no tasks on it."""
        return IBugTarget(self.factory.makeProduct())

    def test_no_tasks(self):
        # A brand new bug target has no tasks.
        target = self.makeBugTarget()
        self.assertEqual([], list(target.searchTasks(None)))

    def test_new_task_shows_up(self):
        # When we create a new bugtask on the target, it shows up in
        # searchTasks.
        target = self.makeBugTarget()
        self.login()
        task = self.factory.makeBugTask(target=target)
        self.assertEqual([task], list(target.searchTasks(None)))

    def test_modified_since_excludes_earlier_bugtasks(self):
        # When we search for bug tasks that have been modified since a certain
        # time, tasks for bugs that have not been modified since then are
        # excluded.
        target = self.makeBugTarget()
        self.login()
        task = self.factory.makeBugTask(target=target)
        date = task.bug.date_last_updated + timedelta(days=1)
        result = target.searchTasks(None, modified_since=date)
        self.assertEqual([], list(result))

    def test_modified_since_includes_later_bugtasks(self):
        # When we search for bug tasks that have been modified since a certain
        # time, tasks for bugs that have been modified since then are
        # included.
        target = self.makeBugTarget()
        self.login()
        task = self.factory.makeBugTask(target=target)
        date = task.bug.date_last_updated - timedelta(days=1)
        result = target.searchTasks(None, modified_since=date)
        self.assertEqual([task], list(result))

    def test_modified_since_includes_later_bugtasks_excludes_earlier(self):
        # When we search for bugs that have been modified since a certain
        # time, tasks for bugs that have been modified since then are
        # included, tasks that have not are excluded.
        target = self.makeBugTarget()
        self.login()
        task1 = self.factory.makeBugTask(target=target)
        date = task1.bug.date_last_updated
        task1.bug.date_last_updated -= timedelta(days=1)
        task2 = self.factory.makeBugTask(target=target)
        task2.bug.date_last_updated += timedelta(days=1)
        result = target.searchTasks(None, modified_since=date)
        self.assertEqual([task2], list(result))

    def test_private_bug_view_permissions_cached(self):
        """Private bugs from a search know the user can see the bugs."""
        target = self.makeBugTarget()
        person = self.login()
        self.factory.makeBug(product=target, private=True, owner=person)
        self.factory.makeBug(product=target, private=True, owner=person)
        self.factory.makeBug(product=target, private=True, owner=person)
        # Search style and parameters taken from the milestone index view
        # where the issue was discovered.
        login_person(person)
        tasks = target.searchTasks(BugTaskSearchParams(
            person, omit_dupes=True, orderby=['status', '-importance', 'id']))
        # We must have found the bugs.
        self.assertEqual(3, tasks.count())
        # Cache in the storm cache the account->person lookup so its not
        # distorting what we're testing.
        IPerson(person.account, None)
        # The should take 2 queries - one for the tasks, one for the related
        # products (eager loaded targets).
        has_expected_queries = HasQueryCount(Equals(2))
        # No extra queries should be issued to access a regular attribute
        # on the bug that would normally trigger lazy evaluation for security
        # checking.  Note that the 'id' attribute does not trigger a check.
        with StormStatementRecorder() as recorder:
            [task.getConjoinedMaster for task in tasks]
            self.assertThat(recorder, has_expected_queries)

    def test_omit_targeted_default_is_false(self):
        # The default value of omit_targeted is false so bugs targeted
        # to a series are not hidden.
        target = self.factory.makeDistroRelease()
        self.login()
        task1 = self.factory.makeBugTask(target=target)
        default_result = target.searchTasks(None)
        self.assertEqual([task1], list(default_result))

    def test_created_since_excludes_earlier_bugtasks(self):
        # When we search for bug tasks that have been created since a certain
        # time, tasks for bugs that have not been created since then are
        # excluded.
        target = self.makeBugTarget()
        self.login()
        task = self.factory.makeBugTask(target=target)
        date = task.datecreated + timedelta(days=1)
        result = target.searchTasks(None, created_since=date)
        self.assertEqual([], list(result))

    def test_created_since_includes_later_bugtasks(self):
        # When we search for bug tasks that have been created since a certain
        # time, tasks for bugs that have been created since then are
        # included.
        target = self.makeBugTarget()
        self.login()
        task = self.factory.makeBugTask(target=target)
        date = task.datecreated - timedelta(days=1)
        result = target.searchTasks(None, created_since=date)
        self.assertEqual([task], list(result))

    def test_created_since_includes_later_bugtasks_excludes_earlier(self):
        # When we search for bugs that have been created since a certain
        # time, tasks for bugs that have been created since then are
        # included, tasks that have not are excluded.
        target = self.makeBugTarget()
        self.login()
        task1 = self.factory.makeBugTask(target=target)
        date = task1.datecreated
        task1.datecreated -= timedelta(days=1)
        task2 = self.factory.makeBugTask(target=target)
        task2.datecreated += timedelta(days=1)
        result = target.searchTasks(None, created_since=date)
        self.assertEqual([task2], list(result))


class BugTaskSetSearchTest(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_explicit_blueprint_specified(self):
        # If the linked_blueprints is an integer id, then only bugtasks for
        # bugs that are linked to that blueprint are returned.
        bug1 = self.factory.makeBug()
        blueprint1 = self.factory.makeBlueprint()
        with person_logged_in(blueprint1.owner):
            blueprint1.linkBug(bug1)
        bug2 = self.factory.makeBug()
        blueprint2 = self.factory.makeBlueprint()
        with person_logged_in(blueprint2.owner):
            blueprint2.linkBug(bug2)
        self.factory.makeBug()
        params = BugTaskSearchParams(
            user=None, linked_blueprints=blueprint1.id)
        tasks = set(getUtility(IBugTaskSet).search(params))
        self.assertThat(set(bug1.bugtasks), Equals(tasks))


class BugTaskSearchBugsElsewhereTest(unittest.TestCase):
    """Tests for searching bugs filtering on related bug tasks.

    It also acts as a helper class, which makes related doctests more
    readable, since they can use methods from this class.
    """
    layer = DatabaseFunctionalLayer

    def __init__(self, methodName='runTest', helper_only=False):
        """If helper_only is True, set up it only as a helper class."""
        if not helper_only:
            unittest.TestCase.__init__(self, methodName=methodName)

    def setUp(self):
        login(ANONYMOUS)

    def tearDown(self):
        logout()

    def _getBugTaskByTarget(self, bug, target):
        """Return a bug's bugtask for the given target."""
        for bugtask in bug.bugtasks:
            if bugtask.target == target:
                return bugtask
        else:
            raise AssertionError(
                "Didn't find a %s task on bug %s." % (
                    target.bugtargetname, bug.id))

    def setUpBugsResolvedUpstreamTests(self):
        """Modify some bugtasks to match the resolved upstream filter."""
        bugset = getUtility(IBugSet)
        productset = getUtility(IProductSet)
        firefox = productset.getByName("firefox")
        thunderbird = productset.getByName("thunderbird")

        # Mark an upstream task on bug #1 "Fix Released"
        bug_one = bugset.get(1)
        firefox_upstream = self._getBugTaskByTarget(bug_one, firefox)
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            firefox_upstream.product.bug_tracking_usage)
        self.old_firefox_status = firefox_upstream.status
        firefox_upstream.transitionToStatus(
            BugTaskStatus.FIXRELEASED, getUtility(ILaunchBag).user)
        self.firefox_upstream = firefox_upstream

        # Mark an upstream task on bug #9 "Fix Committed"
        bug_nine = bugset.get(9)
        thunderbird_upstream = self._getBugTaskByTarget(bug_nine, thunderbird)
        self.old_thunderbird_status = thunderbird_upstream.status
        thunderbird_upstream.transitionToStatus(
            BugTaskStatus.FIXCOMMITTED, getUtility(ILaunchBag).user)
        self.thunderbird_upstream = thunderbird_upstream

        # Add a watch to a Debian bug for bug #2, and mark the task Fix
        # Released.
        bug_two = bugset.get(2)
        bugwatchset = getUtility(IBugWatchSet)

        # Get a debbugs watch.
        watch_debbugs_327452 = bugwatchset.get(9)
        self.assertEquals(watch_debbugs_327452.bugtracker.name, "debbugs")
        self.assertEquals(watch_debbugs_327452.remotebug, "327452")

        # Associate the watch to a Fix Released task.
        debian = getUtility(IDistributionSet).getByName("debian")
        debian_firefox = debian.getSourcePackage("mozilla-firefox")
        bug_two_in_debian_firefox = self._getBugTaskByTarget(
            bug_two, debian_firefox)
        bug_two_in_debian_firefox.bugwatch = watch_debbugs_327452
        bug_two_in_debian_firefox.transitionToStatus(
            BugTaskStatus.FIXRELEASED, getUtility(ILaunchBag).user)

        flush_database_updates()

    def tearDownBugsElsewhereTests(self):
        """Resets the modified bugtasks to their original statuses."""
        self.firefox_upstream.transitionToStatus(
            self.old_firefox_status,
            self.firefox_upstream.target.bug_supervisor)
        self.thunderbird_upstream.transitionToStatus(
            self.old_thunderbird_status,
            self.firefox_upstream.target.bug_supervisor)
        flush_database_updates()

    def assertBugTaskIsPendingBugWatchElsewhere(self, bugtask):
        """Assert the bugtask is pending a bug watch elsewhere.

        Pending a bugwatch elsewhere means that at least one of the bugtask's
        related task's target isn't using Malone, and that
        related_bugtask.bugwatch is None.
        """
        non_malone_using_bugtasks = [
            related_task for related_task in bugtask.related_tasks
            if not related_task.target_uses_malone]
        pending_bugwatch_bugtasks = [
            related_bugtask for related_bugtask in non_malone_using_bugtasks
            if related_bugtask.bugwatch is None]
        self.assert_(
            len(pending_bugwatch_bugtasks) > 0,
            'Bugtask %s on %s has no related bug watches elsewhere.' % (
                bugtask.id, bugtask.target.displayname))

    def assertBugTaskIsResolvedUpstream(self, bugtask):
        """Make sure at least one of the related upstream tasks is resolved.

        "Resolved", for our purposes, means either that one of the related
        tasks is an upstream task in FIXCOMMITTED or FIXRELEASED state, or
        it is a task with a bugwatch, and in FIXCOMMITTED, FIXRELEASED, or
        INVALID state.
        """
        resolved_upstream_states = [
            BugTaskStatus.FIXCOMMITTED, BugTaskStatus.FIXRELEASED]
        resolved_bugwatch_states = [
            BugTaskStatus.FIXCOMMITTED, BugTaskStatus.FIXRELEASED,
            BugTaskStatus.INVALID]

        # Helper functions for the list comprehension below.
        def _is_resolved_upstream_task(bugtask):
            return (
                bugtask.product is not None and
                bugtask.status in resolved_upstream_states)

        def _is_resolved_bugwatch_task(bugtask):
            return (
                bugtask.bugwatch and bugtask.status in
                resolved_bugwatch_states)

        resolved_related_tasks = [
            related_task for related_task in bugtask.related_tasks
            if (_is_resolved_upstream_task(related_task) or
                _is_resolved_bugwatch_task(related_task))]

        self.assert_(len(resolved_related_tasks) > 0)
        self.assert_(
            len(resolved_related_tasks) > 0,
            'Bugtask %s on %s has no resolved related tasks.' % (
                bugtask.id, bugtask.target.displayname))

    def assertBugTaskIsOpenUpstream(self, bugtask):
        """Make sure at least one of the related upstream tasks is open.

        "Open", for our purposes, means either that one of the related
        tasks is an upstream task or a task with a bugwatch which has
        one of the states listed in open_states.
        """
        open_states = [
            BugTaskStatus.NEW,
            BugTaskStatus.INCOMPLETE,
            BugTaskStatus.CONFIRMED,
            BugTaskStatus.INPROGRESS,
            BugTaskStatus.UNKNOWN]

        # Helper functions for the list comprehension below.
        def _is_open_upstream_task(bugtask):
            return (
                bugtask.product is not None and
                bugtask.status in open_states)

        def _is_open_bugwatch_task(bugtask):
            return (
                bugtask.bugwatch and bugtask.status in
                open_states)

        open_related_tasks = [
            related_task for related_task in bugtask.related_tasks
            if (_is_open_upstream_task(related_task) or
                _is_open_bugwatch_task(related_task))]

        self.assert_(
            len(open_related_tasks) > 0,
            'Bugtask %s on %s has no open related tasks.' % (
                bugtask.id, bugtask.target.displayname))

    def _hasUpstreamTask(self, bug):
        """Does this bug have an upstream task associated with it?

        Returns True if yes, otherwise False.
        """
        for bugtask in bug.bugtasks:
            if bugtask.product is not None:
                return True
        return False

    def assertShouldBeShownOnNoUpstreamTaskSearch(self, bugtask):
        """Should the bugtask be shown in the search no upstream task search?

        Returns True if yes, otherwise False.
        """
        self.assert_(
            not self._hasUpstreamTask(bugtask.bug),
            'Bugtask %s on %s has upstream tasks.' % (
                bugtask.id, bugtask.target.displayname))


class BugTaskSetFindExpirableBugTasksTest(unittest.TestCase):
    """Test `BugTaskSet.findExpirableBugTasks()` behaviour."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Setup the zope interaction and create expirable bugtasks."""
        login('test@canonical.com')
        self.user = getUtility(ILaunchBag).user
        self.distribution = getUtility(IDistributionSet).getByName('ubuntu')
        self.distroseries = self.distribution.getSeries('hoary')
        self.product = getUtility(IProductSet).getByName('jokosher')
        self.productseries = self.product.getSeries('trunk')
        self.bugtaskset = getUtility(IBugTaskSet)
        bugtasks = []
        bugtasks.append(
            create_old_bug("90 days old", 90, self.distribution))
        bugtasks.append(
            self.bugtaskset.createTask(
                bugtasks[-1].bug, self.user, self.distroseries))
        bugtasks.append(
            create_old_bug("90 days old", 90, self.product))
        bugtasks.append(
            self.bugtaskset.createTask(
                bugtasks[-1].bug, self.user, self.productseries))

    def tearDown(self):
        logout()

    def testSupportedTargetParam(self):
        """The target param supports a limited set of BugTargets.

        Four BugTarget types may passed as the target argument:
        Distribution, DistroSeries, Product, ProductSeries.
        """
        supported_targets_and_task_count = [
            (self.distribution, 2), (self.distroseries, 1), (self.product, 2),
            (self.productseries, 1), (None, 4)]
        for target, expected_count in supported_targets_and_task_count:
            expirable_bugtasks = self.bugtaskset.findExpirableBugTasks(
                0, self.user, target=target)
            self.assertEqual(expected_count, expirable_bugtasks.count(),
                 "%s has %d expirable bugtasks, expected %d." %
                 (self.distroseries, expirable_bugtasks.count(),
                  expected_count))

    def testUnsupportedBugTargetParam(self):
        """Test that unsupported targets raise errors.

        Three BugTarget types are not supported because the UI does not
        provide bug-index to link to the 'bugs that can expire' page.
        ProjectGroup, SourcePackage, and DistributionSourcePackage will
        raise an NotImplementedError.

        Passing an unknown bugtarget type will raise an AssertionError.
        """
        project = getUtility(IProjectGroupSet).getByName('mozilla')
        distributionsourcepackage = self.distribution.getSourcePackage(
            'mozilla-firefox')
        sourcepackage = self.distroseries.getSourcePackage(
            'mozilla-firefox')
        unsupported_targets = [project, distributionsourcepackage,
                               sourcepackage]
        for target in unsupported_targets:
            self.assertRaises(
                NotImplementedError, self.bugtaskset.findExpirableBugTasks,
                0, self.user, target=target)

        # Objects that are not a known BugTarget type raise an AssertionError.
        self.assertRaises(
            AssertionError, self.bugtaskset.findExpirableBugTasks,
            0, self.user, target=[])


class BugTaskSetTest(unittest.TestCase):
    """Test `BugTaskSet` methods."""
    layer = DatabaseFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)

    def test_getBugTasks(self):
        """ IBugTaskSet.getBugTasks() returns a dictionary mapping the given
        bugs to their bugtasks. It does that in a single query, to avoid
        hitting the DB again when getting the bugs' tasks.
        """
        login('no-priv@canonical.com')
        factory = LaunchpadObjectFactory()
        bug1 = factory.makeBug()
        factory.makeBugTask(bug1)
        bug2 = factory.makeBug()
        factory.makeBugTask(bug2)
        factory.makeBugTask(bug2)

        bugs_and_tasks = getUtility(IBugTaskSet).getBugTasks(
            [bug1.id, bug2.id])
        # The bugtasks returned by getBugTasks() are exactly the same as the
        # ones returned by bug.bugtasks, obviously.
        self.failUnlessEqual(
            set(bugs_and_tasks[bug1]).difference(bug1.bugtasks),
            set([]))
        self.failUnlessEqual(
            set(bugs_and_tasks[bug2]).difference(bug2.bugtasks),
            set([]))

    def test_getBugTasks_with_empty_list(self):
        # When given an empty list of bug IDs, getBugTasks() will return an
        # empty dictionary.
        bugs_and_tasks = getUtility(IBugTaskSet).getBugTasks([])
        self.failUnlessEqual(bugs_and_tasks, {})


class TestBugTaskStatuses(TestCase):

    def test_open_and_resolved_statuses(self):
        """
        There are constants that are used to define which statuses are for
        resolved bugs (`RESOLVED_BUGTASK_STATUSES`), and which are for
        unresolved bugs (`UNRESOLVED_BUGTASK_STATUSES`). The two constants
        include all statuses defined in BugTaskStatus, except for Unknown.
        """
        self.assertNotIn(BugTaskStatus.UNKNOWN, RESOLVED_BUGTASK_STATUSES)
        self.assertNotIn(BugTaskStatus.UNKNOWN, UNRESOLVED_BUGTASK_STATUSES)


class TestBugTaskContributor(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_non_contributor(self):
        owner = self.factory.makePerson()
        bug = self.factory.makeBug(owner=owner)
        # Create a person who has not contributed
        person = self.factory.makePerson()
        result = bug.default_bugtask.getContributorInfo(owner, person)
        self.assertFalse(result['is_contributor'])
        self.assertEqual(person.displayname, result['person_name'])
        self.assertEqual(
            bug.default_bugtask.pillar.displayname, result['pillar_name'])

    def test_contributor(self):
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product, owner=owner)
        bug1 = self.factory.makeBug(product=product, owner=owner)
        # Create a person who has contributed
        person = self.factory.makePerson()
        login('foo.bar@canonical.com')
        bug1.default_bugtask.transitionToAssignee(person)
        result = bug.default_bugtask.getContributorInfo(owner, person)
        self.assertTrue(result['is_contributor'])
        self.assertEqual(person.displayname, result['person_name'])
        self.assertEqual(
            bug.default_bugtask.pillar.displayname, result['pillar_name'])


class TestConjoinedBugTasks(TestCaseWithFactory):
    """Tests for conjoined bug task functionality."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestConjoinedBugTasks, self).setUp()
        self.owner = self.factory.makePerson()
        self.distro = self.factory.makeDistribution(
            name="eggs", owner=self.owner, bug_supervisor=self.owner)
        distro_release = self.factory.makeDistroRelease(
            distribution=self.distro, registrant=self.owner)
        source_package = self.factory.makeSourcePackage(
            sourcepackagename="spam", distroseries=distro_release)
        bug = self.factory.makeBug(
            distribution=self.distro,
            sourcepackagename=source_package.sourcepackagename,
            owner=self.owner)
        with person_logged_in(self.owner):
            nomination = bug.addNomination(self.owner, distro_release)
            nomination.approve(self.owner)
            self.generic_task, self.series_task = bug.bugtasks

    def test_editing_generic_status_reflects_upon_conjoined_master(self):
        # If a change is made to the status of a conjoined slave
        # (generic) task, that change is reflected upon the conjoined
        # master.
        with person_logged_in(self.owner):
            self.generic_task.transitionToStatus(
                BugTaskStatus.CONFIRMED, self.owner)
            self.assertEqual(
                BugTaskStatus.CONFIRMED, self.series_task.status)

    def test_editing_generic_importance_reflects_upon_conjoined_master(self):
        # If a change is made to the importance of a conjoined slave
        # (generic) task, that change is reflected upon the conjoined
        # master.
        with person_logged_in(self.owner):
            self.generic_task.transitionToImportance(
                BugTaskImportance.HIGH, self.owner)
            self.assertEqual(
                BugTaskImportance.HIGH, self.series_task.importance)

    def test_editing_generic_assignee_reflects_upon_conjoined_master(self):
        # If a change is made to the assignee of a conjoined slave
        # (generic) task, that change is reflected upon the conjoined
        # master.
        with person_logged_in(self.owner):
            self.generic_task.transitionToAssignee(self.owner)
            self.assertEqual(
                self.owner, self.series_task.assignee)

    def test_editing_generic_package_reflects_upon_conjoined_master(self):
        # If a change is made to the source package of a conjoined slave
        # (generic) task, that change is reflected upon the conjoined
        # master.
        source_package_name = self.factory.makeSourcePackageName("ham")
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=self.distro.currentseries,
            sourcepackagename=source_package_name)
        with person_logged_in(self.owner):
            self.generic_task.transitionToTarget(
                self.distro.getSourcePackage(source_package_name))
            self.assertEqual(
                source_package_name, self.series_task.sourcepackagename)

# START TEMPORARY BIT FOR BUGTASK AUTOCONFIRM FEATURE FLAG.
# When feature flag code is removed, delete these tests (up to "# END
# TEMPORARY BIT FOR BUGTASK AUTOCONFIRM FEATURE FLAG.")


class TestAutoConfirmBugTasksFlagForProduct(TestCaseWithFactory):
    """Tests for auto-confirming bug tasks."""
    # Tests for _checkAutoconfirmFeatureFlag.

    layer = DatabaseFunctionalLayer

    def makeTarget(self):
        return self.factory.makeProduct()

    flag = u'bugs.autoconfirm.enabled_product_names'
    alt_flag = u'bugs.autoconfirm.enabled_distribution_names'

    def test_False(self):
        # With no feature flags turned on, we do not auto-confirm.
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        self.assertFalse(
            removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())

    def test_flag_False(self):
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        with feature_flags():
            set_feature_flag(self.flag, u'   ')
            self.assertFalse(
                removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())

    def test_explicit_flag(self):
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        with feature_flags():
            set_feature_flag(self.flag, bug_task.pillar.name)
            self.assertTrue(
                removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())

    def test_explicit_flag_of_many(self):
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        with feature_flags():
            set_feature_flag(
                self.flag, u'  foo bar  ' + bug_task.pillar.name + '    baz ')
            self.assertTrue(
                removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())

    def test_match_all_flag(self):
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        with feature_flags():
            set_feature_flag(self.flag, u'*')
            self.assertTrue(
                removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())

    def test_alt_flag_does_not_affect(self):
        bug_task = self.factory.makeBugTask(target=self.makeTarget())
        with feature_flags():
            set_feature_flag(self.alt_flag, bug_task.pillar.name)
            self.assertFalse(
                removeSecurityProxy(bug_task)._checkAutoconfirmFeatureFlag())


class TestAutoConfirmBugTasksFlagForProductSeries(
    TestAutoConfirmBugTasksFlagForProduct):
    """Tests for auto-confirming bug tasks."""

    def makeTarget(self):
        return self.factory.makeProductSeries()


class TestAutoConfirmBugTasksFlagForDistribution(
    TestAutoConfirmBugTasksFlagForProduct):
    """Tests for auto-confirming bug tasks."""

    flag = TestAutoConfirmBugTasksFlagForProduct.alt_flag
    alt_flag = TestAutoConfirmBugTasksFlagForProduct.flag

    def makeTarget(self):
        return self.factory.makeDistribution()


class TestAutoConfirmBugTasksFlagForDistributionSeries(
    TestAutoConfirmBugTasksFlagForDistribution):
    """Tests for auto-confirming bug tasks."""

    def makeTarget(self):
        return self.factory.makeDistroSeries()


class TestAutoConfirmBugTasksFlagForDistributionSourcePackage(
    TestAutoConfirmBugTasksFlagForDistribution):
    """Tests for auto-confirming bug tasks."""

    def makeTarget(self):
        return self.factory.makeDistributionSourcePackage()


class TestAutoConfirmBugTasksTransitionToTarget(TestCaseWithFactory):
    """Tests for auto-confirming bug tasks."""
    # Tests for making sure that switching a task from one project that
    # does not auto-confirm to another that does performs the auto-confirm
    # correctly, if appropriate.  This is only necessary for as long as a
    # project may not participate in auto-confirm.

    layer = DatabaseFunctionalLayer

    def test_no_transitionToTarget(self):
        # We can change the target.  If the normal bug conditions do not
        # hold, there will be no transition.
        person = self.factory.makePerson()
        autoconfirm_product = self.factory.makeProduct(owner=person)
        no_autoconfirm_product = self.factory.makeProduct(owner=person)
        with feature_flags():
            set_feature_flag(u'bugs.autoconfirm.enabled_product_names',
                             autoconfirm_product.name)
            bug_task = self.factory.makeBugTask(
                target=no_autoconfirm_product, owner=person)
            with person_logged_in(person):
                bug_task.maybeConfirm()
                self.assertEqual(BugTaskStatus.NEW, bug_task.status)
                bug_task.transitionToTarget(autoconfirm_product)
                self.assertEqual(BugTaskStatus.NEW, bug_task.status)

    def test_transitionToTarget(self):
        # If the conditions *do* hold, though, we will auto-confirm.
        person = self.factory.makePerson()
        another_person = self.factory.makePerson()
        autoconfirm_product = self.factory.makeProduct(owner=person)
        no_autoconfirm_product = self.factory.makeProduct(owner=person)
        with feature_flags():
            set_feature_flag(u'bugs.autoconfirm.enabled_product_names',
                             autoconfirm_product.name)
            bug_task = self.factory.makeBugTask(
                target=no_autoconfirm_product, owner=person)
            with person_logged_in(another_person):
                bug_task.bug.markUserAffected(another_person)
            with person_logged_in(person):
                bug_task.maybeConfirm()
                self.assertEqual(BugTaskStatus.NEW, bug_task.status)
                bug_task.transitionToTarget(autoconfirm_product)
                self.assertEqual(BugTaskStatus.CONFIRMED, bug_task.status)
# END TEMPORARY BIT FOR BUGTASK AUTOCONFIRM FEATURE FLAG.


class TestAutoConfirmBugTasks(TestCaseWithFactory):
    """Tests for auto-confirming bug tasks."""
    # Tests for maybeConfirm

    layer = DatabaseFunctionalLayer

    def test_auto_confirm(self):
        # A typical new bugtask auto-confirms.
        # When feature flag code is removed, remove the next two lines and
        # dedent the rest.
        with feature_flags():
            set_feature_flag(u'bugs.autoconfirm.enabled_product_names', u'*')
            bug_task = self.factory.makeBugTask()
            self.assertEqual(BugTaskStatus.NEW, bug_task.status)
            with EventRecorder() as recorder:
                bug_task.maybeConfirm()
                self.assertEqual(BugTaskStatus.CONFIRMED, bug_task.status)
                self.assertEqual(1, len(recorder.events))
                event = recorder.events[0]
                self.assertEqual(getUtility(ILaunchpadCelebrities).janitor,
                                 event.user)
                self.assertEqual(['status'], event.edited_fields)
                self.assertEqual(BugTaskStatus.NEW,
                                 event.object_before_modification.status)
                self.assertEqual(bug_task, event.object)

    def test_do_not_confirm_bugwatch_tasks(self):
        # A bugwatch bugtask does not auto-confirm.
        # When feature flag code is removed, remove the next two lines and
        # dedent the rest.
        with feature_flags():
            set_feature_flag(u'bugs.autoconfirm.enabled_product_names', u'*')
            product = self.factory.makeProduct()
            with person_logged_in(product.owner):
                bug = self.factory.makeBug(
                    product=product, owner=product.owner)
                bug_task = bug.getBugTask(product)
                watch = self.factory.makeBugWatch(bug=bug)
                bug_task.bugwatch = watch
            self.assertEqual(BugTaskStatus.NEW, bug_task.status)
            with EventRecorder() as recorder:
                bug_task.maybeConfirm()
                self.assertEqual(BugTaskStatus.NEW, bug_task.status)
                self.assertEqual(0, len(recorder.events))

    def test_only_confirm_new_tasks(self):
        # A non-new bugtask does not auto-confirm.
        # When feature flag code is removed, remove the next two lines and
        # dedent the rest.
        with feature_flags():
            set_feature_flag(u'bugs.autoconfirm.enabled_product_names', u'*')
            bug_task = self.factory.makeBugTask()
            removeSecurityProxy(bug_task).transitionToStatus(
                BugTaskStatus.CONFIRMED, bug_task.bug.owner)
            self.assertEqual(BugTaskStatus.CONFIRMED, bug_task.status)
            with EventRecorder() as recorder:
                bug_task.maybeConfirm()
                self.assertEqual(BugTaskStatus.CONFIRMED, bug_task.status)
                self.assertEqual(0, len(recorder.events))


class TestValidateTransitionToTarget(TestCaseWithFactory):
    """Tests for BugTask.validateTransitionToTarget."""

    layer = DatabaseFunctionalLayer

    def makeAndCheckTransition(self, old, new):
        task = self.factory.makeBugTask(target=old)
        with person_logged_in(task.owner):
            task.validateTransitionToTarget(new)

    def assertTransitionWorks(self, a, b):
        """Check that a transition between two targets works both ways."""
        self.makeAndCheckTransition(a, b)
        self.makeAndCheckTransition(b, a)

    def assertTransitionForbidden(self, a, b):
        """Check that a transition between two targets fails both ways."""
        self.assertRaises(IllegalTarget, self.makeAndCheckTransition, a, b)
        self.assertRaises(IllegalTarget, self.makeAndCheckTransition, b, a)

    def test_product_to_product_works(self):
        self.assertTransitionWorks(
            self.factory.makeProduct(),
            self.factory.makeProduct())

    def test_product_to_distribution_works(self):
        self.assertTransitionWorks(
            self.factory.makeProduct(),
            self.factory.makeDistributionSourcePackage())

    def test_product_to_package_works(self):
        self.assertTransitionWorks(
            self.factory.makeProduct(),
            self.factory.makeDistributionSourcePackage())

    def test_distribution_to_distribution_works(self):
        self.assertTransitionWorks(
            self.factory.makeDistribution(),
            self.factory.makeDistribution())

    def test_distribution_to_package_works(self):
        distro = self.factory.makeDistribution()
        dsp = self.factory.makeDistributionSourcePackage(distribution=distro)
        self.assertEquals(dsp.distribution, distro)
        self.assertTransitionWorks(distro, dsp)

    def test_package_to_package_works(self):
        distro = self.factory.makeDistribution()
        self.assertTransitionWorks(
            self.factory.makeDistributionSourcePackage(distribution=distro),
            self.factory.makeDistributionSourcePackage(distribution=distro))

    def test_sourcepackage_to_sourcepackage_in_same_series_works(self):
        sp1 = self.factory.makeSourcePackage()
        sp2 = self.factory.makeSourcePackage(distroseries=sp1.distroseries)
        self.assertTransitionWorks(sp1, sp2)

    def test_sourcepackage_to_same_series_works(self):
        sp = self.factory.makeSourcePackage()
        self.assertTransitionWorks(sp, sp.distroseries)

    def test_different_distros_works(self):
        self.assertTransitionWorks(
            self.factory.makeDistributionSourcePackage(),
            self.factory.makeDistributionSourcePackage())

    def test_cannot_transition_to_productseries(self):
        product = self.factory.makeProduct()
        self.assertTransitionForbidden(
            product,
            self.factory.makeProductSeries(product=product))

    def test_cannot_transition_to_distroseries(self):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro)
        self.assertTransitionForbidden(distro, series)

    def test_cannot_transition_to_sourcepackage(self):
        dsp = self.factory.makeDistributionSourcePackage()
        series = self.factory.makeDistroSeries(distribution=dsp.distribution)
        sp = self.factory.makeSourcePackage(
            distroseries=series, sourcepackagename=dsp.sourcepackagename)
        self.assertTransitionForbidden(dsp, sp)

    def test_cannot_transition_to_sourcepackage_in_different_series(self):
        distro = self.factory.makeDistribution()
        ds1 = self.factory.makeDistroSeries(distribution=distro)
        sp1 = self.factory.makeSourcePackage(distroseries=ds1)
        ds2 = self.factory.makeDistroSeries(distribution=distro)
        sp2 = self.factory.makeSourcePackage(distroseries=ds2)
        self.assertTransitionForbidden(sp1, sp2)

    def test_validate_target_is_called(self):
        p = self.factory.makeProduct()
        task1 = self.factory.makeBugTask(target=p)
        task2 = self.factory.makeBugTask(
            bug=task1.bug, target=self.factory.makeProduct())
        with person_logged_in(task2.owner):
            self.assertRaisesWithContent(
                IllegalTarget,
                "A fix for this bug has already been requested for %s"
                % p.displayname, task2.transitionToTarget, p)


class TestTransitionToTarget(TestCaseWithFactory):
    """Tests for BugTask.transitionToTarget."""

    layer = DatabaseFunctionalLayer

    def makeAndTransition(self, old, new):
        task = self.factory.makeBugTask(target=old)
        p = self.factory.makePerson()
        self.assertEqual(old, task.target)
        old_state = Snapshot(task, providing=providedBy(task))
        with person_logged_in(task.owner):
            task.bug.subscribe(p, p)
            task.transitionToTarget(new)
            notify(ObjectModifiedEvent(task, old_state, ["target"]))
        return task

    def assertTransitionWorks(self, a, b):
        """Check that a transition between two targets works both ways."""
        self.assertEqual(b, self.makeAndTransition(a, b).target)
        self.assertEqual(a, self.makeAndTransition(b, a).target)

    def test_transition_works(self):
        self.assertTransitionWorks(
            self.factory.makeProduct(),
            self.factory.makeProduct())

    def test_target_type_transition_works(self):
        # A transition from one type of target to another works.
        self.assertTransitionWorks(
            self.factory.makeProduct(),
            self.factory.makeDistributionSourcePackage())

    def test_validation(self):
        # validateTransitionToTarget is called before any transition.
        p = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=p)

        # Patch out validateTransitionToTarget to raise an exception
        # that we can check. Also check that the target was not changed.
        msg = self.factory.getUniqueString()
        removeSecurityProxy(task).validateTransitionToTarget = FakeMethod(
            failure=IllegalTarget(msg))
        with person_logged_in(task.owner):
            self.assertRaisesWithContent(
                IllegalTarget, msg,
                task.transitionToTarget, self.factory.makeProduct())
        self.assertEqual(p, task.target)

    def test_transition_to_same_is_noop(self):
        # While a no-op transition would normally be rejected due to
        # task duplication, transitionToTarget short-circuits.
        p = self.factory.makeProduct()
        self.assertTransitionWorks(p, p)

    def test_milestone_unset_on_transition(self):
        # A task's milestone is reset when its target changes.
        product = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=product)
        with person_logged_in(task.owner):
            task.milestone = self.factory.makeMilestone(product=product)
            task.transitionToTarget(self.factory.makeProduct())
        self.assertIs(None, task.milestone)

    def test_milestone_preserved_if_transition_rejected(self):
        # If validation rejects a transition, the milestone is not unset.
        product = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=product)
        with person_logged_in(task.owner):
            task.milestone = milestone = self.factory.makeMilestone(
                product=product)
            self.assertRaises(
                IllegalTarget,
                task.transitionToTarget, self.factory.makeSourcePackage())
        self.assertEqual(milestone, task.milestone)

    def test_targetnamecache_updated(self):
        new_product = self.factory.makeProduct()
        task = self.factory.makeBugTask()
        with person_logged_in(task.owner):
            task.transitionToTarget(new_product)
        self.assertEqual(
            new_product.bugtargetdisplayname,
            removeSecurityProxy(task).targetnamecache)


class TestBugTargetKeys(TestCaseWithFactory):
    """Tests for bug_target_to_key and bug_target_from_key."""

    layer = DatabaseFunctionalLayer

    def assertTargetKeyWorks(self, target, flat):
        """Check that a target flattens to the dict and back."""
        self.assertEqual(flat, bug_target_to_key(target))
        self.assertEqual(target, bug_target_from_key(**flat))

    def test_product(self):
        product = self.factory.makeProduct()
        self.assertTargetKeyWorks(
            product,
            dict(
                product=product,
                productseries=None,
                distribution=None,
                distroseries=None,
                sourcepackagename=None,
                ))

    def test_productseries(self):
        series = self.factory.makeProductSeries()
        self.assertTargetKeyWorks(
            series,
            dict(
                product=None,
                productseries=series,
                distribution=None,
                distroseries=None,
                sourcepackagename=None,
                ))

    def test_distribution(self):
        distro = self.factory.makeDistribution()
        self.assertTargetKeyWorks(
            distro,
            dict(
                product=None,
                productseries=None,
                distribution=distro,
                distroseries=None,
                sourcepackagename=None,
                ))

    def test_distroseries(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertTargetKeyWorks(
            distroseries,
            dict(
                product=None,
                productseries=None,
                distribution=None,
                distroseries=distroseries,
                sourcepackagename=None,
                ))

    def test_distributionsourcepackage(self):
        dsp = self.factory.makeDistributionSourcePackage()
        self.assertTargetKeyWorks(
            dsp,
            dict(
                product=None,
                productseries=None,
                distribution=dsp.distribution,
                distroseries=None,
                sourcepackagename=dsp.sourcepackagename,
                ))

    def test_sourcepackage(self):
        sp = self.factory.makeSourcePackage()
        self.assertTargetKeyWorks(
            sp,
            dict(
                product=None,
                productseries=None,
                distribution=None,
                distroseries=sp.distroseries,
                sourcepackagename=sp.sourcepackagename,
                ))

    def test_no_key_for_non_targets(self):
        self.assertRaises(
            AssertionError, bug_target_to_key, self.factory.makePerson())

    def test_no_target_for_bad_keys(self):
        self.assertRaises(
            AssertionError, bug_target_from_key, None, None, None, None, None)


class TestValidateTarget(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_new_product_is_allowed(self):
        # A new product not on the bug is OK.
        p1 = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=p1)
        p2 = self.factory.makeProduct()
        validate_target(task.bug, p2)

    def test_same_product_is_forbidden(self):
        # A product with an existing task is not.
        p = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=p)
        self.assertRaisesWithContent(
            IllegalTarget,
            "A fix for this bug has already been requested for %s"
            % p.displayname,
            validate_target, task.bug, p)

    def test_new_distribution_is_allowed(self):
        # A new distribution not on the bug is OK.
        d1 = self.factory.makeDistribution()
        task = self.factory.makeBugTask(target=d1)
        d2 = self.factory.makeDistribution()
        validate_target(task.bug, d2)

    def test_new_productseries_is_allowed(self):
        # A new productseries not on the bug is OK.
        ds1 = self.factory.makeProductSeries()
        task = self.factory.makeBugTask(target=ds1)
        ds2 = self.factory.makeProductSeries()
        validate_target(task.bug, ds2)

    def test_new_distroseries_is_allowed(self):
        # A new distroseries not on the bug is OK.
        ds1 = self.factory.makeDistroSeries()
        task = self.factory.makeBugTask(target=ds1)
        ds2 = self.factory.makeDistroSeries()
        validate_target(task.bug, ds2)

    def test_new_sourcepackage_is_allowed(self):
        # A new sourcepackage not on the bug is OK.
        sp1 = self.factory.makeSourcePackage()
        task = self.factory.makeBugTask(target=sp1)
        sp2 = self.factory.makeSourcePackage()
        validate_target(task.bug, sp2)

    def test_multiple_packageless_distribution_tasks_are_forbidden(self):
        # A distribution with an existing task is not.
        d = self.factory.makeDistribution()
        task = self.factory.makeBugTask(target=d)
        self.assertRaisesWithContent(
            IllegalTarget,
            "A fix for this bug has already been requested for %s"
            % d.displayname,
            validate_target, task.bug, d)

    def test_distributionsourcepackage_task_is_allowed(self):
        # A DistributionSourcePackage task can coexist with a task for
        # its Distribution.
        d = self.factory.makeDistribution()
        task = self.factory.makeBugTask(target=d)
        dsp = self.factory.makeDistributionSourcePackage(distribution=d)
        validate_target(task.bug, dsp)

    def test_different_distributionsourcepackage_tasks_are_allowed(self):
        # A DistributionSourcePackage task can also coexist with a task
        # for another one.
        dsp1 = self.factory.makeDistributionSourcePackage()
        task = self.factory.makeBugTask(target=dsp1)
        dsp2 = self.factory.makeDistributionSourcePackage(
            distribution=dsp1.distribution)
        validate_target(task.bug, dsp2)

    def test_same_distributionsourcepackage_task_is_forbidden(self):
        # But a DistributionSourcePackage task cannot coexist with a
        # task for itself.
        dsp = self.factory.makeDistributionSourcePackage()
        task = self.factory.makeBugTask(target=dsp)
        self.assertRaisesWithContent(
            IllegalTarget,
            "A fix for this bug has already been requested for %s in %s"
            % (dsp.sourcepackagename.name, dsp.distribution.displayname),
            validate_target, task.bug, dsp)

    def test_dsp_without_publications_disallowed(self):
        # If a distribution has series, a DistributionSourcePackage task
        # can only be created if the package is published in a distro
        # archive.
        series = self.factory.makeDistroSeries()
        dsp = self.factory.makeDistributionSourcePackage(
            distribution=series.distribution)
        task = self.factory.makeBugTask()
        self.assertRaisesWithContent(
            IllegalTarget,
            "Package %s not published in %s"
            % (dsp.sourcepackagename.name, dsp.distribution.displayname),
            validate_target, task.bug, dsp)

    def test_dsp_with_publications_allowed(self):
        # If a distribution has series, a DistributionSourcePackage task
        # can only be created if the package is published in a distro
        # archive.
        series = self.factory.makeDistroSeries()
        dsp = self.factory.makeDistributionSourcePackage(
            distribution=series.distribution)
        task = self.factory.makeBugTask()
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series, sourcepackagename=dsp.sourcepackagename,
            archive=series.main_archive)
        validate_target(task.bug, dsp)

    def test_dsp_with_only_ppa_publications_disallowed(self):
        # If a distribution has series, a DistributionSourcePackage task
        # can only be created if the package is published in a distro
        # archive. PPA publications don't count.
        series = self.factory.makeDistroSeries()
        dsp = self.factory.makeDistributionSourcePackage(
            distribution=series.distribution)
        task = self.factory.makeBugTask()
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series, sourcepackagename=dsp.sourcepackagename,
            archive=self.factory.makeArchive(purpose=ArchivePurpose.PPA))
        self.assertRaisesWithContent(
            IllegalTarget,
            "Package %s not published in %s"
            % (dsp.sourcepackagename.name, dsp.distribution.displayname),
            validate_target, task.bug, dsp)


class TestValidateNewTarget(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_products_are_ok(self):
        p1 = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=p1)
        p2 = self.factory.makeProduct()
        validate_new_target(task.bug, p2)

    def test_calls_validate_target(self):
        p = self.factory.makeProduct()
        task = self.factory.makeBugTask(target=p)
        self.assertRaisesWithContent(
            IllegalTarget,
            "A fix for this bug has already been requested for %s"
            % p.displayname,
            validate_new_target, task.bug, p)

    def test_package_task_with_distribution_task_forbidden(self):
        d = self.factory.makeDistribution()
        dsp = self.factory.makeDistributionSourcePackage(distribution=d)
        task = self.factory.makeBugTask(target=d)
        self.assertRaisesWithContent(
            IllegalTarget,
            "This bug is already open on %s with no package specified. "
            "You should fill in a package name for the existing bug."
            % d.displayname,
            validate_new_target, task.bug, dsp)

    def test_distribution_task_with_package_task_forbidden(self):
        d = self.factory.makeDistribution()
        dsp = self.factory.makeDistributionSourcePackage(distribution=d)
        task = self.factory.makeBugTask(target=dsp)
        self.assertRaisesWithContent(
            IllegalTarget,
            "This bug is already on %s. Please specify an affected "
            "package in which the bug has not yet been reported."
            % d.displayname,
            validate_new_target, task.bug, d)
