# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for BranchView."""

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
from textwrap import dedent

import pytz
import simplejson
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.launchpad.helpers import truncate_text
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from canonical.launchpad.testing.pages import (
    extract_text,
    find_tag_by_id,
    setupBrowser,
    )
from lp.app.interfaces.headings import IRootContext
from lp.bugs.interfaces.bugtask import (
    BugTaskStatus,
    UNRESOLVED_BUGTASK_STATUSES,
    )
from lp.code.browser.branch import (
    BranchAddView,
    BranchMirrorStatusView,
    BranchReviewerEditView,
    BranchSparkView,
    BranchView,
    )
from lp.code.browser.branchlisting import PersonOwnedBranchesView
from lp.code.bzr import ControlFormat
from lp.code.enums import (
    BranchLifecycleStatus,
    BranchType,
    )
from lp.code.interfaces.branchtarget import IBranchTarget
from lp.testing import (
    BrowserTestCase,
    login,
    login_person,
    logout,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.matchers import BrowsesWithQueryLimit
from lp.testing.views import create_initialized_view


class TestBranchMirrorHidden(TestCaseWithFactory):
    """Make sure that the appropriate mirror locations are hidden."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        config.push(
            "test", dedent("""\
                [codehosting]
                private_mirror_hosts: private.example.com
                """))

    def tearDown(self):
        config.pop("test")
        TestCaseWithFactory.tearDown(self)

    def testNormalBranch(self):
        # A branch from a normal location is fine.
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED,
            url="http://example.com/good/mirror")
        view = BranchView(branch, LaunchpadTestRequest())
        view.initialize()
        self.assertTrue(view.user is None)
        self.assertEqual(
            "http://example.com/good/mirror", view.mirror_location)

    def testLocationlessRemoteBranch(self):
        # A branch from a normal location is fine.
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.REMOTE,
            url=None)
        view = BranchView(branch, LaunchpadTestRequest())
        view.initialize()
        self.assertTrue(view.user is None)
        self.assertIs(None, view.mirror_location)

    def testHiddenBranchAsAnonymous(self):
        # A branch location with a defined private host is hidden from
        # anonymous browsers.
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED,
            url="http://private.example.com/bzr-mysql/mysql-5.0")
        view = BranchView(branch, LaunchpadTestRequest())
        view.initialize()
        self.assertTrue(view.user is None)
        self.assertEqual(
            "<private server>", view.mirror_location)

    def testHiddenBranchAsBranchOwner(self):
        # A branch location with a defined private host is visible to the
        # owner.
        owner = self.factory.makePerson(
            email="eric@example.com", password="test")
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED,
            owner=owner,
            url="http://private.example.com/bzr-mysql/mysql-5.0")
        # Now log in the owner.
        logout()
        login('eric@example.com')
        view = BranchView(branch, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(view.user, owner)
        self.assertEqual(
            "http://private.example.com/bzr-mysql/mysql-5.0",
            view.mirror_location)

    def testHiddenBranchAsOtherLoggedInUser(self):
        # A branch location with a defined private host is hidden from other
        # users.
        owner = self.factory.makePerson(
            email="eric@example.com", password="test")
        other = self.factory.makePerson(
            email="other@example.com", password="test")
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED,
            owner=owner,
            url="http://private.example.com/bzr-mysql/mysql-5.0")
        # Now log in the other person.
        logout()
        login('other@example.com')
        view = BranchView(branch, LaunchpadTestRequest())
        view.initialize()
        self.assertEqual(view.user, other)
        self.assertEqual(
            "<private server>", view.mirror_location)


class TestBranchView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBranchView, self).setUp()
        self.request = LaunchpadTestRequest()

    def testMirrorStatusMessageIsTruncated(self):
        """mirror_status_message is truncated if the text is overly long."""
        branch = self.factory.makeBranch(branch_type=BranchType.MIRRORED)
        branch.mirrorFailed(
            "on quick brown fox the dog jumps to" *
            BranchMirrorStatusView.MAXIMUM_STATUS_MESSAGE_LENGTH)
        branch_view = BranchMirrorStatusView(branch, self.request)
        self.assertEqual(
            truncate_text(branch.mirror_status_message,
                          branch_view.MAXIMUM_STATUS_MESSAGE_LENGTH) + ' ...',
            branch_view.mirror_status_message)

    def testMirrorStatusMessage(self):
        """mirror_status_message on the view is the same as on the branch."""
        branch = self.factory.makeBranch(branch_type=BranchType.MIRRORED)
        branch.mirrorFailed("This is a short error message.")
        branch_view = BranchMirrorStatusView(branch, self.request)
        self.assertTrue(
            len(branch.mirror_status_message)
            <= branch_view.MAXIMUM_STATUS_MESSAGE_LENGTH,
            "branch.mirror_status_message longer than expected: %r"
            % (branch.mirror_status_message, ))
        self.assertEqual(
            branch.mirror_status_message, branch_view.mirror_status_message)
        self.assertEqual(
            "This is a short error message.",
            branch_view.mirror_status_message)

    def testBranchAddRequestsMirror(self):
        """Registering a mirrored branch requests a mirror."""
        arbitrary_person = self.factory.makePerson()
        arbitrary_product = self.factory.makeProduct()
        login_person(arbitrary_person)
        try:
            add_view = BranchAddView(arbitrary_person, self.request)
            add_view.initialize()
            data = {
                'branch_type': BranchType.MIRRORED,
                'name': 'some-branch',
                'url': 'http://example.com',
                'title': 'Branch Title',
                'summary': '',
                'lifecycle_status': BranchLifecycleStatus.DEVELOPMENT,
                'whiteboard': '',
                'owner': arbitrary_person,
                'author': arbitrary_person,
                'product': arbitrary_product,
                }
            add_view.add_action.success(data)
            # Make sure that next_mirror_time is a datetime, not an sqlbuilder
            # expression.
            removeSecurityProxy(add_view.branch).sync()
            now = datetime.now(pytz.timezone('UTC'))
            self.assertNotEqual(None, add_view.branch.next_mirror_time)
            self.assertTrue(
                add_view.branch.next_mirror_time < now,
                "next_mirror_time not set to UTC_NOW: %s < %s"
                % (add_view.branch.next_mirror_time, now))
        finally:
            logout()

    def testShowMergeLinksOnManyBranchProject(self):
        # The merge links are shown on projects that have multiple branches.
        product = self.factory.makeProduct(name='super-awesome-project')
        branch1 = self.factory.makeAnyBranch(product=product)
        self.factory.makeAnyBranch(product=product)
        view = BranchView(branch1, self.request)
        view.initialize()
        self.assertTrue(view.show_merge_links)

    def testShowMergeLinksOnJunkBranch(self):
        # The merge links are not shown on junk branches because they do not
        # support merge proposals.
        junk_branch = self.factory.makeBranch(product=None)
        view = BranchView(junk_branch, self.request)
        view.initialize()
        self.assertFalse(view.show_merge_links)

    def testShowMergeLinksOnSingleBranchProject(self):
        # The merge links are not shown on branches attached to a project that
        # only has one branch because it's pointless to propose it for merging
        # if there's nothing to merge into.
        branch = self.factory.makeAnyBranch()
        view = BranchView(branch, self.request)
        view.initialize()
        self.assertFalse(view.show_merge_links)

    def testNoProductSeriesPushingTranslations(self):
        # By default, a branch view shows no product series pushing
        # translations to the branch.
        branch = self.factory.makeBranch()

        view = BranchView(branch, self.request)
        view.initialize()
        self.assertEqual(list(view.translations_sources()), [])

    def testProductSeriesPushingTranslations(self):
        # If a product series exports its translations to the branch,
        # the view shows it.
        product = self.factory.makeProduct()
        trunk = product.getSeries('trunk')
        branch = self.factory.makeBranch(owner=product.owner)
        removeSecurityProxy(trunk).translations_branch = branch

        view = BranchView(branch, self.request)
        view.initialize()
        self.assertEqual(list(view.translations_sources()), [trunk])

    def test_is_empty_directory(self):
        # Branches are considered empty until they get a control format.
        branch = self.factory.makeBranch()
        view = BranchView(branch, self.request)
        view.initialize()
        self.assertTrue(view.is_empty_directory)
        with person_logged_in(branch.owner):
            # Make it look as though the branch has been pushed.
            branch.branchChanged(
                None, None, ControlFormat.BZR_METADIR_1, None, None)
        self.assertFalse(view.is_empty_directory)

    def test_empty_directories_use_existing(self):
        # Push example should include --use-existing for empty directories.
        branch = self.factory.makeBranch(owner=self.user)
        text = self.getMainText(branch)
        self.assertIn('push\n--use-existing', text)
        with person_logged_in(self.user):
            # Make it look as though the branch has been pushed.
            branch.branchChanged(
                None, None, ControlFormat.BZR_METADIR_1, None, None)
        text = self.getMainText(branch)
        self.assertNotIn('push\n--use-existing', text)

    def test_user_can_upload(self):
        # A user can upload if they have edit permissions.
        branch = self.factory.makeAnyBranch()
        view = create_initialized_view(branch, '+index')
        login_person(branch.owner)
        self.assertTrue(view.user_can_upload)

    def test_user_can_upload_admins_can(self):
        # Admins can upload to any hosted branch.
        branch = self.factory.makeAnyBranch()
        view = create_initialized_view(branch, '+index')
        login('admin@canonical.com')
        self.assertTrue(view.user_can_upload)

    def test_user_can_upload_non_owner(self):
        # Someone not associated with the branch cannot upload
        branch = self.factory.makeAnyBranch()
        view = create_initialized_view(branch, '+index')
        login_person(self.factory.makePerson())
        self.assertFalse(view.user_can_upload)

    def test_user_can_upload_mirrored(self):
        # Even the owner of a mirrored branch can't upload.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        view = create_initialized_view(branch, '+index')
        login_person(branch.owner)
        self.assertFalse(view.user_can_upload)

    def _addBugLinks(self, branch):
        for status in BugTaskStatus.items:
            bug = self.factory.makeBug(status=status)
            branch.linkBug(bug, branch.owner)

    def test_linked_bugtasks(self):
        # The linked bugs for a non series branch shows all linked bugs.
        branch = self.factory.makeAnyBranch()
        with person_logged_in(branch.owner):
            self._addBugLinks(branch)
        view = create_initialized_view(branch, '+index')
        self.assertEqual(len(BugTaskStatus), len(view.linked_bugtasks))
        self.assertFalse(view.context.is_series_branch)

    def test_linked_bugtasks_privacy(self):
        # If a linked bug is private, it is not in the linked bugs if the user
        # can't see any of the tasks.
        branch = self.factory.makeAnyBranch()
        reporter = self.factory.makePerson()
        bug = self.factory.makeBug(private=True, owner=reporter)
        with person_logged_in(reporter):
            branch.linkBug(bug, reporter)
            view = create_initialized_view(branch, '+index')
            self.assertEqual([bug.id],
                [task.bug.id for task in view.linked_bugtasks])
        with person_logged_in(branch.owner):
            view = create_initialized_view(branch, '+index')
            self.assertEqual([], view.linked_bugtasks)

    def test_linked_bugtasks_series_branch(self):
        # The linked bugtasks for a series branch shows only unresolved bugs.
        product = self.factory.makeProduct()
        branch = self.factory.makeProductBranch(product=product)
        with person_logged_in(product.owner):
            product.development_focus.branch = branch
        with person_logged_in(branch.owner):
            self._addBugLinks(branch)
        view = create_initialized_view(branch, '+index')
        for bugtask in view.linked_bugtasks:
            self.assertTrue(
                bugtask.status in UNRESOLVED_BUGTASK_STATUSES)

    def test_linked_bugs_nonseries_branch_query_scaling(self):
        # As we add linked bugs, the query count for a branch index page stays
        # constant.
        branch = self.factory.makeAnyBranch()
        browses_under_limit = BrowsesWithQueryLimit(54, branch.owner)
        # Start with some bugs, otherwise we might see a spurious increase
        # depending on optimisations in eager loaders.
        with person_logged_in(branch.owner):
            self._addBugLinks(branch)
            self.assertThat(branch, browses_under_limit)
        with person_logged_in(branch.owner):
            # Add plenty of bugs.
            for _ in range(5):
                self._addBugLinks(branch)
            self.assertThat(branch, browses_under_limit)

    def test_linked_bugs_series_branch_query_scaling(self):
        # As we add linked bugs, the query count for a branch index page stays
        # constant.
        product = self.factory.makeProduct()
        branch = self.factory.makeProductBranch(product=product)
        browses_under_limit = BrowsesWithQueryLimit(54, branch.owner)
        with person_logged_in(product.owner):
            product.development_focus.branch = branch
        # Start with some bugs, otherwise we might see a spurious increase
        # depending on optimisations in eager loaders.
        with person_logged_in(branch.owner):
            self._addBugLinks(branch)
            self.assertThat(branch, browses_under_limit)
        with person_logged_in(branch.owner):
            # Add plenty of bugs.
            for _ in range(5):
                self._addBugLinks(branch)
            self.assertThat(branch, browses_under_limit)

    def _add_revisions(self, branch, nr_revisions=1):
        revisions = []
        for seq in range(1, nr_revisions+1):
            revision = self.factory.makeRevision(
                author="Eric the Viking <eric@vikings-r-us.example.com>",
                log_body=(
                    "Testing the email address in revisions\n"
                    "email Bob (bob@example.com) for details."))

            branch_revision = branch.createBranchRevision(seq, revision)
            branch.updateScannedDetails(revision, seq)
            revisions.append(branch_revision)
        return revisions

    def test_recent_revisions(self):
        # There is a heading for the recent revisions.
        branch = self.factory.makeAnyBranch()
        with person_logged_in(branch.owner):
            self._add_revisions(branch)
        browser = self.getUserBrowser(canonical_url(branch))
        tag = find_tag_by_id(browser.contents, 'recent-revisions')
        text = extract_text(tag)
        expected_text = """
            Recent revisions
            .*
            1. By Eric the Viking &lt;eric@vikings-r-us.example.com&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(bob@example.com\) for details.
            """

        self.assertTextMatchesExpressionIgnoreWhitespace(expected_text, text)

    def test_recent_revisions_email_hidden_with_no_login(self):
        # If the user is not logged in, the email addresses are hidden in both
        # the revision author and the commit message.
        branch = self.factory.makeAnyBranch()
        with person_logged_in(branch.owner):
            self._add_revisions(branch)
            branch_url = canonical_url(branch)
        browser = setupBrowser()
        logout()
        browser.open(branch_url)
        tag = find_tag_by_id(browser.contents, 'recent-revisions')
        text = extract_text(tag)
        expected_text = """
            Recent revisions
            .*
            1. By Eric the Viking &lt;email address hidden&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(&lt;email address hidden&gt;\) for details.
            """
        self.assertTextMatchesExpressionIgnoreWhitespace(expected_text, text)

    def test_recent_revisions_with_merge_proposals(self):
        # Revisions which result from merging in a branch with a merge
        # proposal show the merge proposal details.

        branch = self.factory.makeAnyBranch()
        with person_logged_in(branch.owner):
            revisions = self._add_revisions(branch, 2)
            mp = self.factory.makeBranchMergeProposal(
                target_branch=branch, registrant=branch.owner)
            mp.markAsMerged(merged_revno=revisions[0].sequence)

            # These values are extracted here and used below.
            mp_url = canonical_url(mp, rootsite='code', force_local_path=True)
            branch_display_name = mp.source_branch.displayname

        browser = self.getUserBrowser(canonical_url(branch))

        revision_content = find_tag_by_id(
            browser.contents, 'recent-revisions')

        text = extract_text(revision_content)
        expected_text = """
            Recent revisions
            .*
            2. By Eric the Viking &lt;eric@vikings-r-us.example.com&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(bob@example.com\) for details.\n
            1. By Eric the Viking &lt;eric@vikings-r-us.example.com&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(bob@example.com\) for details.
            Merged branch %s
            """ % branch_display_name

        self.assertTextMatchesExpressionIgnoreWhitespace(expected_text, text)

        links = revision_content.findAll('a')
        self.assertEqual(mp_url, links[2]['href'])

    def test_recent_revisions_with_merge_proposals_and_bug_links(self):
        # Revisions which result from merging in a branch with a merge
        # proposal show the merge proposal details. If the source branch of
        # the merge proposal has linked bugs, these should also be shown.

        branch = self.factory.makeAnyBranch()
        with person_logged_in(branch.owner):
            revisions = self._add_revisions(branch, 2)
            mp = self.factory.makeBranchMergeProposal(
                target_branch=branch, registrant=branch.owner)
            mp.markAsMerged(merged_revno=revisions[0].sequence)

            # record linked bug info for use below
            linked_bug_urls = []
            linked_bug_text = []
            for x in range(0, 2):
                bug = self.factory.makeBug()
                mp.source_branch.linkBug(bug, branch.owner)
                linked_bug_urls.append(
                    canonical_url(bug.default_bugtask, rootsite='bugs'))
                bug_text = "Bug #%s: %s" % (bug.id, bug.title)
                linked_bug_text.append(bug_text)

            # These values are extracted here and used below.
            linked_bug_rendered_text = "\n".join(linked_bug_text)
            mp_url = canonical_url(mp, force_local_path=True)
            branch_display_name = mp.source_branch.displayname

        browser = self.getUserBrowser(canonical_url(branch))

        revision_content = find_tag_by_id(
            browser.contents, 'recent-revisions')

        text = extract_text(revision_content)
        expected_text = """
            Recent revisions
            .*
            2. By Eric the Viking &lt;eric@vikings-r-us.example.com&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(bob@example.com\) for details.\n
            1. By Eric the Viking &lt;eric@vikings-r-us.example.com&gt;
            .*
            Testing the email address in revisions\n
            email Bob \(bob@example.com\) for details.
            Merged branch %s
            %s
            """ % (branch_display_name, linked_bug_rendered_text)

        self.assertTextMatchesExpressionIgnoreWhitespace(expected_text, text)

        links = revision_content.findAll('a')
        self.assertEqual(mp_url, links[2]['href'])
        self.assertEqual(linked_bug_urls[0], links[3]['href'])
        self.assertEqual(linked_bug_urls[1], links[4]['href'])


class TestBranchAddView(TestCaseWithFactory):
    """Test the BranchAddView view."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBranchAddView, self).setUp()
        self.person = self.factory.makePerson()
        login_person(self.person)
        self.request = LaunchpadTestRequest()

    def tearDown(self):
        logout()
        super(TestBranchAddView, self).tearDown()

    def get_view(self, context):
        view = BranchAddView(context, self.request)
        view.initialize()
        return view

    def test_target_person(self):
        add_view = self.get_view(self.person)
        self.assertTrue(IBranchTarget.providedBy(add_view.target))

    def test_target_product(self):
        product = self.factory.makeProduct()
        add_view = self.get_view(product)
        self.assertTrue(IBranchTarget.providedBy(add_view.target))


class TestBranchReviewerEditView(TestCaseWithFactory):
    """Test the BranchReviewerEditView view."""

    layer = DatabaseFunctionalLayer

    def test_initial_reviewer_not_set(self):
        # If the reviewer is not set, the field is populated with the owner of
        # the branch.
        branch = self.factory.makeAnyBranch()
        self.assertIs(None, branch.reviewer)
        view = BranchReviewerEditView(branch, LaunchpadTestRequest())
        self.assertEqual(
            branch.owner,
            view.initial_values['reviewer'])

    def test_initial_reviewer_set(self):
        # If the reviewer has been set, it is shown as the initial value.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.reviewer = self.factory.makePerson()
        view = BranchReviewerEditView(branch, LaunchpadTestRequest())
        self.assertEqual(
            branch.reviewer,
            view.initial_values['reviewer'])

    def test_set_reviewer(self):
        # Test setting the reviewer.
        branch = self.factory.makeAnyBranch()
        reviewer = self.factory.makePerson()
        login_person(branch.owner)
        view = BranchReviewerEditView(branch, LaunchpadTestRequest())
        view.initialize()
        view.change_action.success({'reviewer': reviewer})
        self.assertEqual(reviewer, branch.reviewer)
        # Last modified has been updated.
        self.assertSqlAttributeEqualsDate(
            branch, 'date_last_modified', UTC_NOW)

    def test_set_reviewer_as_owner_clears_reviewer(self):
        # If the reviewer is set to be the branch owner, the review field is
        # cleared in the database.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.reviewer = self.factory.makePerson()
        view = BranchReviewerEditView(branch, LaunchpadTestRequest())
        view.initialize()
        view.change_action.success({'reviewer': branch.owner})
        self.assertIs(None, branch.reviewer)
        # Last modified has been updated.
        self.assertSqlAttributeEqualsDate(
            branch, 'date_last_modified', UTC_NOW)

    def test_set_reviewer_to_same_does_not_update_last_modified(self):
        # If the user has set the reviewer to be same and clicked on save,
        # then the underlying object hasn't really been changed, so the last
        # modified is not updated.
        modified_date = datetime(2007, 1, 1, tzinfo=pytz.UTC)
        branch = self.factory.makeAnyBranch(date_created=modified_date)
        view = BranchReviewerEditView(branch, LaunchpadTestRequest())
        view.initialize()
        view.change_action.success({'reviewer': branch.owner})
        self.assertIs(None, branch.reviewer)
        # Last modified has not been updated.
        self.assertEqual(modified_date, branch.date_last_modified)


class TestBranchBzrIdentity(TestCaseWithFactory):
    """Test the bzr_identity on the PersonOwnedBranchesView."""

    layer = DatabaseFunctionalLayer

    def test_dev_focus_identity(self):
        # A branch that is a development focus branch, should show using the
        # short name on the listing.
        product = self.factory.makeProduct(name="fooix")
        branch = self.factory.makeProductBranch(product=product)
        # To avoid dealing with admins, just log in the product owner to set
        # the development focus branch.
        login_person(product.owner)
        product.development_focus.branch = branch
        view = PersonOwnedBranchesView(branch.owner, LaunchpadTestRequest())
        view.initialize()
        navigator = view.branches()
        [decorated_branch] = navigator.branches
        self.assertEqual("lp://dev/fooix", decorated_branch.bzr_identity)


class TestBranchSparkView(TestCaseWithFactory):
    """Tests for the BranchSparkView class."""

    layer = DatabaseFunctionalLayer

    def test_empty_branch(self):
        # A branch with no commits produces...
        branch = self.factory.makeAnyBranch()
        view = BranchSparkView(branch, LaunchpadTestRequest())
        json = simplejson.loads(view.render())
        self.assertEqual(0, json['count'])
        self.assertEqual('empty branch', json['last_commit'])

    def test_content_type(self):
        # The response has the correct (JSON) content type...
        branch = self.factory.makeAnyBranch()
        request = LaunchpadTestRequest()
        view = BranchSparkView(branch, request)
        view.render()
        self.assertEqual(
            request.response.getHeader('content-type'),
            'application/json')

    def test_old_commits(self):
        # A branch with a commit older than the COMMIT_DAYS will create a list
        # of commits that all say zero.
        branch = self.factory.makeAnyBranch()
        revision = self.factory.makeRevision(
            revision_date=datetime(
                year=2008, month=9, day=10, tzinfo=pytz.UTC))
        branch.createBranchRevision(1, revision)
        branch.updateScannedDetails(revision, 1)

        view = BranchSparkView(branch, LaunchpadTestRequest())
        json = simplejson.loads(view.render())

        self.assertEqual(0, json['count'])
        self.assertEqual([0] * 90, json['commits'])
        self.assertEqual('2008-09-10', json['last_commit'])

    def test_last_commit_string(self):
        # If the last commit was very recent, we get a nicer string.
        branch = self.factory.makeAnyBranch()
        # Make the revision date six hours ago.
        revision_date = datetime.now(tz=pytz.UTC) - timedelta(seconds=6*3600)
        revision = self.factory.makeRevision(
            revision_date=revision_date)
        branch.createBranchRevision(1, revision)
        branch.updateScannedDetails(revision, 1)

        view = BranchSparkView(branch, LaunchpadTestRequest())
        json = simplejson.loads(view.render())
        self.assertEqual('6 hours ago', json['last_commit'])

    def test_new_commits(self):
        # If there are no commits for the day, there are zeros, if there are
        # commits, then the array contains the number of commits for that day.
        branch = self.factory.makeAnyBranch()
        # Create a commit 5 days ago.
        revision_date = datetime.now(tz=pytz.UTC) - timedelta(days=5)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.createBranchRevision(1, revision)
        branch.updateScannedDetails(revision, 1)

        view = BranchSparkView(branch, LaunchpadTestRequest())
        json = simplejson.loads(view.render())

        self.assertEqual(1, json['count'])
        commits = ([0] * 84) + [1, 0, 0, 0, 0, 0]
        self.assertEqual(commits, json['commits'])
        self.assertEqual(84, json['max_commits'])

    def test_commit_for_just_now(self):
        # A commit now should show as a commit on the last day.
        branch = self.factory.makeAnyBranch()
        revision_date = datetime.now(tz=pytz.UTC)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.createBranchRevision(1, revision)
        branch.updateScannedDetails(revision, 1)

        view = BranchSparkView(branch, LaunchpadTestRequest())
        json = simplejson.loads(view.render())

        self.assertEqual(1, json['count'])
        commits = ([0] * 89) + [1]
        self.assertEqual(commits, json['commits'])


class TestBranchProposalsVisible(TestCaseWithFactory):
    """Test that the BranchView filters out proposals the user cannot see."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)

    def test_public_target(self):
        # If the user can see the target, then there are merges, and the
        # landing_target is available for the template rendering.
        bmp = self.factory.makeBranchMergeProposal()
        branch = bmp.source_branch
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertFalse(view.no_merges)
        [target] = view.landing_targets
        # Check the ids as the target is a DecoratedMergeProposal.
        self.assertEqual(bmp.id, target.id)

    def test_private_target(self):
        # If the target is private, the landing targets should not include it.
        bmp = self.factory.makeBranchMergeProposal()
        branch = bmp.source_branch
        removeSecurityProxy(bmp.target_branch).private = True
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertTrue(view.no_merges)
        self.assertEqual([], view.landing_targets)

    def test_public_source(self):
        # If the user can see the source, then there are merges, and the
        # landing_candidate is available for the template rendering.
        bmp = self.factory.makeBranchMergeProposal()
        branch = bmp.target_branch
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertFalse(view.no_merges)
        [candidate] = view.landing_candidates
        # Check the ids as the target is a DecoratedMergeProposal.
        self.assertEqual(bmp.id, candidate.id)

    def test_private_source(self):
        # If the source is private, the landing candidates should not include
        # it.
        bmp = self.factory.makeBranchMergeProposal()
        branch = bmp.target_branch
        removeSecurityProxy(bmp.source_branch).private = True
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertTrue(view.no_merges)
        self.assertEqual([], view.landing_candidates)

    def test_prerequisite_public(self):
        # If the branch is a prerequisite branch for a public proposals, then
        # there are merges.
        branch = self.factory.makeProductBranch()
        bmp = self.factory.makeBranchMergeProposal(prerequisite_branch=branch)
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertFalse(view.no_merges)
        [proposal] = view.dependent_branches
        self.assertEqual(bmp, proposal)

    def test_prerequisite_private(self):
        # If the branch is a prerequisite branch where either the source or
        # the target is private, then the dependent_branches are not shown.
        branch = self.factory.makeProductBranch()
        bmp = self.factory.makeBranchMergeProposal(prerequisite_branch=branch)
        removeSecurityProxy(bmp.source_branch).private = True
        view = BranchView(branch, LaunchpadTestRequest())
        self.assertTrue(view.no_merges)
        self.assertEqual([], view.dependent_branches)


class TestBranchRootContext(TestCaseWithFactory):
    """Test the adaptation of IBranch to IRootContext."""

    layer = DatabaseFunctionalLayer

    def test_personal_branch(self):
        # The root context of a personal branch is the person.
        branch = self.factory.makePersonalBranch()
        root_context = IRootContext(branch)
        self.assertEqual(branch.owner, root_context)

    def test_package_branch(self):
        # The root context of a package branch is the distribution.
        branch = self.factory.makePackageBranch()
        root_context = IRootContext(branch)
        self.assertEqual(branch.distroseries.distribution, root_context)

    def test_product_branch(self):
        # The root context of a product branch is the product.
        branch = self.factory.makeProductBranch()
        root_context = IRootContext(branch)
        self.assertEqual(branch.product, root_context)
