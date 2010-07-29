# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import with_statement

"""Tests for bug-branch linking from the bugs side."""

__metaclass__ = type

from zope.component import getUtility
from zope.event import notify
from zope.security.interfaces import Unauthorized

from canonical.testing import DatabaseFunctionalLayer
from lazr.lifecycle.event import ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from lp.bugs.model.bugbranch import BugBranch, BugBranchSet
from lp.bugs.interfaces.bugbranch import IBugBranch, IBugBranchSet
from lp.testing import (
    anonymous_logged_in,
    celebrity_logged_in,
    TestCaseWithFactory,
    )


class TestBugBranchSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_bugbranchset_provides_IBugBranchSet(self):
        # BugBranchSet objects provide IBugBranchSet.
        self.assertProvides(BugBranchSet(), IBugBranchSet)

    def test_getBugBranchesForBranches_no_branches(self):
        bug_branches = getUtility(IBugBranchSet)
        links = bug_branches.getBugBranchesForBranches(
            [], self.factory.makePerson())
        self.assertEqual([], list(links))

    def test_getBugBranchesForBranches(self):
        # IBugBranchSet.getBugBranchesForBranches returns all of the BugBranch
        # objects associated with the given branches.
        branch_1 = self.factory.makeBranch()
        branch_2 = self.factory.makeBranch()
        bug_a = self.factory.makeBug()
        bug_b = self.factory.makeBug()
        self.factory.loginAsAnyone()
        link_1 = bug_a.linkBranch(branch_1, self.factory.makePerson())
        link_2 = bug_a.linkBranch(branch_2, self.factory.makePerson())
        link_3 = bug_b.linkBranch(branch_2, self.factory.makePerson())
        self.assertEqual(
            set([link_1, link_2, link_3]),
            set(getUtility(IBugBranchSet).getBugBranchesForBranches(
                [branch_1, branch_2], self.factory.makePerson())))

    def test_getBugBranchesForBranches_respects_bug_privacy(self):
        # IBugBranchSet.getBugBranchesForBranches returns only the BugBranch
        # objects that are visible by the user who is asking for them.
        branch = self.factory.makeBranch()
        user = self.factory.makePerson()
        public_bug = self.factory.makeBug()
        private_visible_bug = self.factory.makeBug(private=True)
        private_invisible_bug = self.factory.makeBug(private=True)
        with celebrity_logged_in('admin'):
            public_bug.linkBranch(branch, user)
            private_visible_bug.subscribe(user, user)
            private_visible_bug.linkBranch(branch, user)
            private_invisible_bug.linkBranch(branch, user)
        bug_branches = getUtility(IBugBranchSet).getBugBranchesForBranches(
            [branch], user)
        self.assertEqual(
            set([public_bug, private_visible_bug]),
            set([link.bug for link in bug_branches]))


class TestBugBranch(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBugBranch, self).setUp()
        # Bug branch linking is generally available to any logged in user.
        self.factory.loginAsAnyone()

    def test_bugbranch_provides_IBugBranch(self):
        # BugBranch objects provide IBugBranch.
        bug_branch = BugBranch(
            branch=self.factory.makeBranch(), bug=self.factory.makeBug(),
            registrant=self.factory.makePerson())
        self.assertProvides(bug_branch, IBugBranch)

    def test_linkBranch_returns_IBugBranch(self):
        # Bug.linkBranch returns an IBugBranch linking the bug to the branch.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        registrant = self.factory.makePerson()
        bug_branch = bug.linkBranch(branch, registrant)
        self.assertEqual(branch, bug_branch.branch)
        self.assertEqual(bug, bug_branch.bug)
        self.assertEqual(registrant, bug_branch.registrant)

    def test_bug_start_with_no_linked_branches(self):
        # Bugs have a linked_branches attribute which is initially an empty
        # collection.
        bug = self.factory.makeBug()
        self.assertEqual([], list(bug.linked_branches))

    def test_linkBranch_adds_to_linked_branches(self):
        # Bug.linkBranch populates the Bug.linked_branches with the created
        # BugBranch object.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug_branch = bug.linkBranch(branch, self.factory.makePerson())
        self.assertEqual([bug_branch], list(bug.linked_branches))

    def test_linking_branch_twice_returns_same_IBugBranch(self):
        # Calling Bug.linkBranch twice with the same parameters returns the
        # same object.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug_branch = bug.linkBranch(branch, self.factory.makePerson())
        bug_branch_2 = bug.linkBranch(branch, self.factory.makePerson())
        self.assertEqual(bug_branch, bug_branch_2)

    def test_linking_branch_twice_different_registrants(self):
        # Calling Bug.linkBranch twice with the branch but different
        # registrants returns the existing bug branch object rather than
        # creating a new one.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug_branch = bug.linkBranch(branch, self.factory.makePerson())
        bug_branch_2 = bug.linkBranch(branch, self.factory.makePerson())
        self.assertEqual(bug_branch, bug_branch_2)

    def test_bug_has_no_branches(self):
        # Bug.hasBranch returns False for any branch that it is not linked to.
        bug = self.factory.makeBug()
        self.assertFalse(bug.hasBranch(self.factory.makeBranch()))

    def test_bug_has_branch(self):
        # Bug.hasBranch returns False for any branch that it is linked to.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug.linkBranch(branch, self.factory.makePerson())
        self.assertTrue(bug.hasBranch(branch))

    def test_unlink_branch(self):
        # Bug.unlinkBranch removes the bug<->branch link.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug.linkBranch(branch, self.factory.makePerson())
        bug.unlinkBranch(branch, self.factory.makePerson())
        self.assertEqual([], list(bug.linked_branches))
        self.assertFalse(bug.hasBranch(branch))

    def test_unlink_not_linked_branch(self):
        # When unlinkBranch is called with a branch that isn't already linked,
        # nothing discernable happens.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        bug.unlinkBranch(branch, self.factory.makePerson())
        self.assertEqual([], list(bug.linked_branches))
        self.assertFalse(bug.hasBranch(branch))

    def test_the_unwashed_cannot_link_branch_to_private_bug(self):
        # Those who cannot see a bug are forbidden to link a branch to it.
        bug = self.factory.makeBug(private=True)
        self.assertRaises(Unauthorized, getattr, bug, 'linkBranch')

    def test_the_unwashed_cannot_unlink_branch_from_private_bug(self):
        # Those who cannot see a bug are forbidden to unlink branches from it.
        bug = self.factory.makeBug(private=True)
        self.assertRaises(Unauthorized, getattr, bug, 'unlinkBranch')

    def test_anonymous_users_cannot_link_branches(self):
        # Anonymous users cannot link branches to bugs, even public bugs.
        bug = self.factory.makeBug()
        with anonymous_logged_in():
            self.assertRaises(Unauthorized, getattr, bug, 'linkBranch')

    def test_anonymous_users_cannot_unlink_branches(self):
        # Anonymous users cannot unlink branches from bugs, even public bugs.
        bug = self.factory.makeBug()
        with anonymous_logged_in():
            self.assertRaises(Unauthorized, getattr, bug, 'unlinkBranch')

    def test_adding_branch_changes_date_last_updated(self):
        # Adding a branch to a bug changes IBug.date_last_updated.
        bug = self.factory.makeBug()
        last_updated = bug.date_last_updated
        branch = self.factory.makeBranch()
        self.factory.loginAsAnyone()
        bug.linkBranch(branch, self.factory.makePerson())
        self.assertTrue(bug.date_last_updated > last_updated)

    def test_editing_branch_changes_date_last_updated(self):
        # Editing a branch linked to a bug changes IBug.date_last_updated.
        bug = self.factory.makeBug()
        branch = self.factory.makeBranch()
        registrant = self.factory.makePerson()
        self.factory.loginAsAnyone()
        branch_link = bug.linkBranch(branch, registrant)
        last_updated = bug.date_last_updated
        # Rather than modifying the bugbranch link directly, we emit an
        # ObjectModifiedEvent, which is triggered whenever the object is
        # edited.

        # XXX: jml has no idea why we do this. Accessing any attribute of the
        # returned BugBranch appears to be forbidden, and there's no evidence
        # that the object is even editable at all.
        before_modification = Snapshot(branch_link, providing=IBugBranch)
        # XXX: WTF? IBugBranch doesn't even have a status attribute? jml.
        event = ObjectModifiedEvent(
            branch_link, before_modification, ['status'])
        notify(event)
        self.assertTrue(bug.date_last_updated > last_updated)
