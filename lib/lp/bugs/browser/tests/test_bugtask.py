# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import with_statement

__metaclass__ = type


from contextlib import nested
from doctest import DocTestSuite
import unittest

from storm.store import Store
from testtools.matchers import (
    Equals,
    LessThan,
    MatchesAny,
    )
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.ftests import (
    ANONYMOUS,
    login,
    login_person,
    )
from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite,
    setUp,
    tearDown,
    )
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import LaunchpadFunctionalLayer
from lp.bugs.browser import bugtask
from lp.bugs.browser.bugtask import (
    BugTaskView,
    BugTaskEditView,
    BugTasksAndNominationsView,
    )
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.testing import (
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import (
    ADMIN_EMAIL,
    NO_PRIVILEGE_EMAIL,
    USER_EMAIL,
    )


class TestBugTaskView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def record_view_initialization(self, bugtask, person):
        self.invalidate_caches(bugtask)
        # Login first because logging in triggers queries.
        with nested(person_logged_in(person), StormStatementRecorder()) as (
            _,
            recorder):
            view = BugTaskView(bugtask, LaunchpadTestRequest())
            view.initialize()
        return recorder

    def invalidate_caches(self, obj):
        store = Store.of(obj)
        # Make sure everything is in the database.
        store.flush()
        # And invalidate the cache (not a reset, because that stops us using
        # the domain objects)
        store.invalidate()

    def test_query_counts_constant_with_team_memberships(self):
        login(ADMIN_EMAIL)
        bugtask = self.factory.makeBugTask()
        person_no_teams = self.factory.makePerson()
        person_with_teams = self.factory.makePerson()
        for _ in range(10):
            self.factory.makeTeam(members=[person_with_teams])
        # count with no teams
        recorder = self.record_view_initialization(bugtask, person_no_teams)
        self.assertThat(recorder, HasQueryCount(LessThan(14)))
        count_with_no_teams = recorder.count
        # count with many teams
        recorder2 = self.record_view_initialization(bugtask, person_with_teams)
        # Allow an increase of one because storm bug 619017 causes additional
        # queries, revalidating things unnecessarily. An increase which is
        # less than the number of new teams shows it is definitely not
        # growing per-team.
        self.assertThat(recorder2, HasQueryCount(
            LessThan(count_with_no_teams + 3),
            ))


class TestBugTasksAndNominationsView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBugTasksAndNominationsView, self).setUp()
        login(ADMIN_EMAIL)
        self.bug = self.factory.makeBug()
        self.view = BugTasksAndNominationsView(
            self.bug, LaunchpadTestRequest())

    def test_current_user_affected_status(self):
        self.failUnlessEqual(
            None, self.view.current_user_affected_status)
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnlessEqual(
            True, self.view.current_user_affected_status)
        self.view.context.markUserAffected(self.view.user, False)
        self.failUnlessEqual(
            False, self.view.current_user_affected_status)

    def test_current_user_affected_js_status(self):
        self.failUnlessEqual(
            'null', self.view.current_user_affected_js_status)
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnlessEqual(
            'true', self.view.current_user_affected_js_status)
        self.view.context.markUserAffected(self.view.user, False)
        self.failUnlessEqual(
            'false', self.view.current_user_affected_js_status)

    def test_not_many_bugtasks(self):
        for count in range(10 - len(self.bug.bugtasks) - 1):
            self.factory.makeBugTask(bug=self.bug)
        self.view.initialize()
        self.failIf(self.view.many_bugtasks)
        row_view = self.view._getTableRowView(
            self.bug.default_bugtask, False, False)
        self.failIf(row_view.many_bugtasks)

    def test_many_bugtasks(self):
        for count in range(10 - len(self.bug.bugtasks)):
            self.factory.makeBugTask(bug=self.bug)
        self.view.initialize()
        self.failUnless(self.view.many_bugtasks)
        row_view = self.view._getTableRowView(
            self.bug.default_bugtask, False, False)
        self.failUnless(row_view.many_bugtasks)

    def test_other_users_affected_count(self):
        # The number of other users affected does not change when the
        # logged-in user marked him or herself as affected or not.
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        self.view.context.markUserAffected(self.view.user, False)
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)

    def test_other_users_affected_count_other_users(self):
        # The number of other users affected only changes when other
        # users mark themselves as affected.
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        other_user_1 = self.factory.makePerson()
        self.view.context.markUserAffected(other_user_1, True)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)
        other_user_2 = self.factory.makePerson()
        self.view.context.markUserAffected(other_user_2, True)
        self.failUnlessEqual(
            3, self.view.other_users_affected_count)
        self.view.context.markUserAffected(other_user_1, False)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)

    def test_affected_statement_no_one_affected(self):
        self.bug.markUserAffected(self.bug.owner, False)
        self.failUnlessEqual(
            0, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "Does this bug affect you?",
            self.view.affected_statement)

    def test_affected_statement_only_you(self):
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnless(self.bug.isUserAffected(self.view.user))
        self.view.context.markUserAffected(self.bug.owner, False)
        self.failUnlessEqual(
            0, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects you",
            self.view.affected_statement)

    def test_affected_statement_only_not_you(self):
        self.view.context.markUserAffected(self.view.user, False)
        self.failIf(self.bug.isUserAffected(self.view.user))
        self.view.context.markUserAffected(self.bug.owner, False)
        self.failUnlessEqual(
            0, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug doesn't affect you",
            self.view.affected_statement)

    def test_affected_statement_1_person_not_you(self):
        self.assertIs(None, self.bug.isUserAffected(self.view.user))
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects 1 person. Does this bug affect you?",
            self.view.affected_statement)

    def test_affected_statement_1_person_and_you(self):
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnless(self.bug.isUserAffected(self.view.user))
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects you and 1 other person",
            self.view.affected_statement)

    def test_affected_statement_1_person_and_not_you(self):
        self.view.context.markUserAffected(self.view.user, False)
        self.failIf(self.bug.isUserAffected(self.view.user))
        self.failUnlessEqual(
            1, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects 1 person, but not you",
            self.view.affected_statement)

    def test_affected_statement_more_than_1_person_not_you(self):
        self.assertIs(None, self.bug.isUserAffected(self.view.user))
        other_user = self.factory.makePerson()
        self.view.context.markUserAffected(other_user, True)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects 2 people. Does this bug affect you?",
            self.view.affected_statement)

    def test_affected_statement_more_than_1_person_and_you(self):
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnless(self.bug.isUserAffected(self.view.user))
        other_user = self.factory.makePerson()
        self.view.context.markUserAffected(other_user, True)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects you and 2 other people",
            self.view.affected_statement)

    def test_affected_statement_more_than_1_person_and_not_you(self):
        self.view.context.markUserAffected(self.view.user, False)
        self.failIf(self.bug.isUserAffected(self.view.user))
        other_user = self.factory.makePerson()
        self.view.context.markUserAffected(other_user, True)
        self.failUnlessEqual(
            2, self.view.other_users_affected_count)
        self.failUnlessEqual(
            "This bug affects 2 people, but not you",
            self.view.affected_statement)

    def test_anon_affected_statement_no_one_affected(self):
        self.bug.markUserAffected(self.bug.owner, False)
        self.failUnlessEqual(0, self.bug.users_affected_count)
        self.assertIs(None, self.view.anon_affected_statement)

    def test_anon_affected_statement_1_user_affected(self):
        self.failUnlessEqual(1, self.bug.users_affected_count)
        self.failUnlessEqual(
            "This bug affects 1 person",
            self.view.anon_affected_statement)

    def test_anon_affected_statement_2_users_affected(self):
        self.view.context.markUserAffected(self.view.user, True)
        self.failUnlessEqual(2, self.bug.users_affected_count)
        self.failUnlessEqual(
            "This bug affects 2 people",
            self.view.anon_affected_statement)


class TestBugTaskEditViewStatusField(TestCaseWithFactory):
    """We show only those options as possible value in the status
    field that the user can select.
    """

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBugTaskEditViewStatusField, self).setUp()
        product_owner = self.factory.makePerson(name='product-owner')
        bug_supervisor = self.factory.makePerson(name='bug-supervisor')
        product = self.factory.makeProduct(
            owner=product_owner, bug_supervisor=bug_supervisor)
        self.bug = self.factory.makeBug(product=product)

    def getWidgetOptionTitles(self, widget):
        """Return the titles of options of the given choice widget."""
        return [
            item.value.title for item in widget.field.vocabulary]

    def test_status_field_items_for_anonymous(self):
        # Anonymous users see only the current value.
        login(ANONYMOUS)
        view = BugTaskEditView(
            self.bug.default_bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            ['New'], self.getWidgetOptionTitles(view.form_fields['status']))

    def test_status_field_items_for_ordinary_users(self):
        # Ordinary users can set the status to all values except Won't fix,
        # Expired, Triaged, Unknown.
        login(NO_PRIVILEGE_EMAIL)
        view = BugTaskEditView(
            self.bug.default_bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            ['New', 'Incomplete', 'Opinion', 'Invalid', 'Confirmed',
             'In Progress', 'Fix Committed', 'Fix Released'],
            self.getWidgetOptionTitles(view.form_fields['status']))

    def test_status_field_privileged_persons(self):
        # The bug target owner and the bug target supervisor can set
        # the status to any value except Unknown and Expired.
        for user in (
            self.bug.default_bugtask.pillar.owner,
            self.bug.default_bugtask.pillar.bug_supervisor):
            login_person(user)
            view = BugTaskEditView(
                self.bug.default_bugtask, LaunchpadTestRequest())
            view.initialize()
            self.assertEqual(
                ['New', 'Incomplete', 'Opinion', 'Invalid', "Won't Fix",
                 'Confirmed', 'Triaged', 'In Progress', 'Fix Committed',
                 'Fix Released'],
                self.getWidgetOptionTitles(view.form_fields['status']),
                'Unexpected set of settable status options for %s'
                % user.name)

    def test_status_field_bug_task_in_status_unknown(self):
        # If a bugtask has the status Unknown, this status is included
        # in the options.
        owner = self.bug.default_bugtask.pillar.owner
        login_person(owner)
        self.bug.default_bugtask.transitionToStatus(
            BugTaskStatus.UNKNOWN, owner)
        login(NO_PRIVILEGE_EMAIL)
        view = BugTaskEditView(
            self.bug.default_bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            ['New', 'Incomplete', 'Opinion', 'Invalid', 'Confirmed',
             'In Progress', 'Fix Committed', 'Fix Released', 'Unknown'],
            self.getWidgetOptionTitles(view.form_fields['status']))

    def test_status_field_bug_task_in_status_expired(self):
        # If a bugtask has the status Expired, this status is included
        # in the options.
        removeSecurityProxy(self.bug.default_bugtask).status = (
            BugTaskStatus.EXPIRED)
        login(NO_PRIVILEGE_EMAIL)
        view = BugTaskEditView(
            self.bug.default_bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            ['New', 'Incomplete', 'Opinion', 'Invalid', 'Expired',
             'Confirmed', 'In Progress', 'Fix Committed', 'Fix Released'],
            self.getWidgetOptionTitles(view.form_fields['status']))


class TestBugTaskEditViewAssigneeField(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestBugTaskEditViewAssigneeField, self).setUp()
        self.bugtask = self.factory.makeBug().default_bugtask

    def test_assignee_field_vocabulary_regular_user(self):
        # For regular users, the assignee vocabulary is
        # AllUserTeamsParticipation.
        login(USER_EMAIL)
        view = BugTaskEditView(self.bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            'AllUserTeamsParticipation',
            view.form_fields['assignee'].field.vocabularyName)

    def test_assignee_field_vocabulary_privileged_user(self):
        # Privileged users, like the bug task target owner, can
        # assign anybody.
        login_person(self.bugtask.target.owner)
        view = BugTaskEditView(self.bugtask, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(
            'ValidAssignee',
            view.form_fields['assignee'].field.vocabularyName)


def test_suite():
    suite = unittest.TestLoader().loadTestsFromName(__name__)
    suite.addTest(DocTestSuite(bugtask))
    suite.addTest(LayeredDocFileSuite(
        'bugtask-target-link-titles.txt', setUp=setUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer))
    return suite


if __name__ == '__main__':
    unittest.TextTestRunner().run(test_suite())
