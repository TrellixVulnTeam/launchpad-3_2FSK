# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for bug task status transitions."""

__metaclass__ = type

from zope.security.proxy import removeSecurityProxy

from canonical.testing.layers import LaunchpadFunctionalLayer
from lp.bugs.interfaces.bugtask import UserCannotEditBugTaskStatus
from lp.bugs.model.bugtask import BugTaskStatus
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )


class TestBugTaskStatusTransitionForUser(TestCaseWithFactory):
    """Test bugtask status transitions for a regular logged in user."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBugTaskStatusTransitionForUser, self).setUp()
        self.user = self.factory.makePerson()
        self.task = self.factory.makeBugTask()

    def test_user_transition_all_statuses(self):
        # A regular user should not be able to set statuses in
        # BUG_SUPERVISOR_BUGTASK_STATUSES, but can set any
        # other status.
        self.assertEqual(self.task.status, BugTaskStatus.NEW)
        with person_logged_in(self.user):
            self.assertRaises(
                UserCannotEditBugTaskStatus, self.task.transitionToStatus,
                BugTaskStatus.WONTFIX, self.user)
            self.assertRaises(
                UserCannotEditBugTaskStatus, self.task.transitionToStatus,
                BugTaskStatus.EXPIRED, self.user)
            self.assertRaises(
                UserCannotEditBugTaskStatus, self.task.transitionToStatus,
                BugTaskStatus.TRIAGED, self.user)
            self.task.transitionToStatus(BugTaskStatus.NEW, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.NEW)
            self.task.transitionToStatus(
                BugTaskStatus.INCOMPLETE, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.INCOMPLETE)
            self.task.transitionToStatus(BugTaskStatus.OPINION, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.OPINION)
            self.task.transitionToStatus(BugTaskStatus.INVALID, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.INVALID)
            self.task.transitionToStatus(BugTaskStatus.CONFIRMED, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.CONFIRMED)
            self.task.transitionToStatus(
                BugTaskStatus.INPROGRESS, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.INPROGRESS)
            self.task.transitionToStatus(
                BugTaskStatus.FIXCOMMITTED, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.FIXCOMMITTED)
            self.task.transitionToStatus(
                BugTaskStatus.FIXRELEASED, self.user)
            self.assertEqual(self.task.status, BugTaskStatus.FIXRELEASED)

    def test_user_cannot_unset_wont_fix_status(self):
        # A regular user should not be able to transition a bug away
        # from Won't Fix.
        removeSecurityProxy(self.task).status = BugTaskStatus.WONTFIX
        with person_logged_in(self.user):
            self.assertRaises(
                UserCannotEditBugTaskStatus, self.task.transitionToStatus,
                BugTaskStatus.CONFIRMED, self.user)

    def test_user_canTransitionToStatus(self):
        # Regular user cannot transition to BUG_SUPERVISOR_BUGTASK_STATUSES,
        # but can transition to any other status.
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.WONTFIX, self.user),
            False)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.EXPIRED, self.user),
            False)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.TRIAGED, self.user),
            False)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.NEW, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INCOMPLETE, self.user), True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.OPINION, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INVALID, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.CONFIRMED, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INPROGRESS, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.FIXCOMMITTED, self.user),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.FIXRELEASED, self.user),
            True)

    def test_user_canTransitionToStatus_from_wontfix(self):
        # A regular user cannot transition away from Won't Fix,
        # so canTransitionToStatus should return False.
        removeSecurityProxy(self.task).status = BugTaskStatus.WONTFIX
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.NEW, self.user),
            False)


class TestBugTaskStatusTransitionForPrivilegedUserBase:
    """Base class used to test privileged users and status transitions."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBugTaskStatusTransitionForPrivilegedUserBase, self).setUp()
        # Creation of task and target are deferred to subclasses.
        self.task = None
        self.person = None
        self.makePersonAndTask()

    def makePersonAndTask(self):
        """Create a bug task and privileged person for this task.

        This method is user by subclasses to correctly setup
        each test.
        """
        raise NotImplementedError(self.makePersonAndTask)

    def test_privileged_user_transition_any_status(self):
        # Privileged users (like owner or bug supervisor) should
        # be able to set any status.
        with person_logged_in(self.person):
            self.task.transitionToStatus(BugTaskStatus.WONTFIX, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.WONTFIX)
            self.task.transitionToStatus(BugTaskStatus.EXPIRED, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.EXPIRED)
            self.task.transitionToStatus(BugTaskStatus.TRIAGED, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.TRIAGED)
            self.task.transitionToStatus(BugTaskStatus.NEW, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.NEW)
            self.task.transitionToStatus(
                BugTaskStatus.INCOMPLETE, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.INCOMPLETE)
            self.task.transitionToStatus(BugTaskStatus.OPINION, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.OPINION)
            self.task.transitionToStatus(BugTaskStatus.INVALID, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.INVALID)
            self.task.transitionToStatus(BugTaskStatus.CONFIRMED, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.CONFIRMED)
            self.task.transitionToStatus(
                BugTaskStatus.INPROGRESS, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.INPROGRESS)
            self.task.transitionToStatus(
                BugTaskStatus.FIXCOMMITTED, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.FIXCOMMITTED)
            self.task.transitionToStatus(
                BugTaskStatus.FIXRELEASED, self.person)
            self.assertEqual(self.task.status, BugTaskStatus.FIXRELEASED)

    def test_privileged_user_canTransitionToStatus(self):
        # Privileged users (like owner or bug supervisor) should
        # be able to set any status, so canTransitionToStatus should
        # always return True.
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.WONTFIX, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.EXPIRED, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.TRIAGED, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.NEW, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INCOMPLETE, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.OPINION, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INVALID, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.CONFIRMED, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.INPROGRESS, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.FIXCOMMITTED, self.person),
            True)
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.FIXRELEASED, self.person),
            True)

    def test_privileged_user_canTransitionToStatus_from_wontfix(self):
        # A privileged user can transition away from Won't Fix, so
        # canTransitionToStatus should return True.
        removeSecurityProxy(self.task).status = BugTaskStatus.WONTFIX
        self.assertEqual(
            self.task.canTransitionToStatus(
                BugTaskStatus.NEW, self.person),
            True)


class TestBugTaskStatusTransitionOwnerPerson(
    TestBugTaskStatusTransitionForPrivilegedUserBase, TestCaseWithFactory):
    """Tests to ensure owner person can transition to any status.."""

    def makePersonAndTask(self):
        self.person = self.factory.makePerson()
        self.product = self.factory.makeProduct(owner=self.person)
        self.task = self.factory.makeBugTask(target=self.product)


class TestBugTaskStatusTransitionOwnerTeam(
    TestBugTaskStatusTransitionForPrivilegedUserBase, TestCaseWithFactory):
    """Tests to ensure owner team can transition to any status.."""

    def makePersonAndTask(self):
        self.person = self.factory.makePerson()
        self.team = self.factory.makeTeam(members=[self.person])
        self.product = self.factory.makeProduct(owner=self.team)
        self.task = self.factory.makeBugTask(target=self.product)


class TestBugTaskStatusTransitionBugSupervisorPerson(
    TestBugTaskStatusTransitionForPrivilegedUserBase, TestCaseWithFactory):
    """Tests to ensure bug supervisor person can transition to any status."""

    def makePersonAndTask(self):
        self.owner = self.factory.makePerson()
        self.person = self.factory.makePerson()
        self.product = self.factory.makeProduct(owner=self.owner)
        self.task = self.factory.makeBugTask(target=self.product)
        with person_logged_in(self.owner):
            self.product.setBugSupervisor(self.person, self.person)


class TestBugTaskStatusTransitionBugSupervisorTeamMember(
    TestBugTaskStatusTransitionForPrivilegedUserBase, TestCaseWithFactory):
    """Tests to ensure bug supervisor team can transition to any status."""

    def makePersonAndTask(self):
        self.owner = self.factory.makePerson()
        self.person = self.factory.makePerson()
        self.team = self.factory.makeTeam(members=[self.person])
        self.product = self.factory.makeProduct(owner=self.owner)
        self.task = self.factory.makeBugTask(target=self.product)
        with person_logged_in(self.owner):
            self.product.setBugSupervisor(self.team, self.team)

