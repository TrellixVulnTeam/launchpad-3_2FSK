# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from datetime import timedelta
import unittest

from lazr.lifecycle.interfaces import IObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import Equals
from zope.component import getUtility
from zope.interface import providedBy

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.searchbuilder import (
    all,
    any,
    )
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.lazr.testing.event import TestEventListener
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.app.enums import ServiceUsage
from lp.bugs.interfaces.bug import IBugSet, IBug
from lp.bugs.interfaces.bugtarget import IBugTarget
from lp.bugs.interfaces.bugtask import (
    BugTaskImportance,
    BugTaskSearchParams,
    BugTaskStatus,
    IBugTaskSet,
    IUpstreamBugTask,
    RESOLVED_BUGTASK_STATUSES,
    UNRESOLVED_BUGTASK_STATUSES,
    IBugTask)
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.model.bugtask import build_tag_search_clause
from lp.bugs.tests.bug import (
    create_old_bug,
    sync_bugtasks,
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
from lp.testing import (
    ANONYMOUS,
    login,
    login_person,
    logout,
    normalize_whitespace,
    person_logged_in,
    StormStatementRecorder,
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.factory import LaunchpadObjectFactory, remove_security_proxy_and_shout_at_engineer
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

    def test_get_mismatched_delta(self):
        # getDelta() should raise TypeError when different types of
        # bug tasks are passed in.
        product = self.factory.makeProduct()
        product_bug_task = self.factory.makeBugTask(target=product)
        distro_source_package = self.factory.makeDistributionSourcePackage()
        distro_source_package_bug_task = self.factory.makeBugTask(
            target=distro_source_package)
        self.assertRaises(
            TypeError, product_bug_task.getDelta,
            distro_source_package_bug_task)

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
                IUpstreamBugTask.providedBy(bugtask) and
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
                IUpstreamBugTask.providedBy(bugtask) and
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
            if IUpstreamBugTask.providedBy(bugtask):
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
                bug=bugtasks[-1].bug, owner=self.user,
                distroseries=self.distroseries))
        bugtasks.append(
            create_old_bug("90 days old", 90, self.product))
        bugtasks.append(
            self.bugtaskset.createTask(
                bug=bugtasks[-1].bug, owner=self.user,
                productseries=self.productseries))
        sync_bugtasks(bugtasks)

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


class TestPrivateBugTask(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def tearDown(self):
        self.listener.unregister()
        super(TestPrivateBugTask, self).tearDown()

    def test_privateBugUnassignMe(self):
        owner = self.factory.makePerson(name="bugowner")
        bug = self.factory.makeBug(owner=owner, private=True)

        def bug_listener(object, event):
            print "%s" % event

        self.listener = TestEventListener(
            IBugTask, IObjectModifiedEvent, bug_listener)
        # A user can unassign themselves from a private bug.
        bug_assignee = self.factory.makePerson(name="bugassignee")
        # Assign a user
        with person_logged_in(owner):
            bug.default_bugtask.transitionToAssignee(bug_assignee)
        # Unassign the user
        with person_logged_in(bug_assignee):
            bug.default_bugtask.transitionToAssignee(None)
        self.assertTrue(not bug.userCanView(bug_assignee))

