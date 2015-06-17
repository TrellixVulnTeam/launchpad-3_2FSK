# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for GitRepositoryView."""

__metaclass__ = type

from datetime import datetime
import doctest

from BeautifulSoup import BeautifulSoup
from fixtures import FakeLogger
import pytz
from testtools.matchers import (
    DocTestMatches,
    Equals,
    )
import transaction
from zope.component import getUtility
from zope.publisher.interfaces import NotFound
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.services import IService
from lp.code.interfaces.githosting import IGitHostingClient
from lp.code.interfaces.revision import IRevisionSet
from lp.registry.enums import BranchSharingPolicy
from lp.registry.interfaces.person import PersonVisibility
from lp.services.database.constants import UTC_NOW
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    admin_logged_in,
    BrowserTestCase,
    login_person,
    logout,
    person_logged_in,
    record_two_runs,
    TestCaseWithFactory,
    )
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import (
    get_feedback_messages,
    setupBrowser,
    setupBrowserForUser,
    )
from lp.testing.publication import test_traverse
from lp.testing.views import (
    create_initialized_view,
    create_view,
    )


class TestGitRepositoryNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_traverse_ref(self):
        [ref] = self.factory.makeGitRefs()
        url = "%s/+ref/%s" % (canonical_url(ref.repository), ref.path)
        self.assertEqual(ref, test_traverse(url)[0])

    def test_traverse_ref_missing(self):
        repository = self.factory.makeGitRepository()
        url = "%s/+ref/refs/heads/master" % canonical_url(repository)
        self.assertRaises(NotFound, test_traverse, url)


class TestGitRepositoryView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_user_can_push(self):
        # A user can push if they have edit permissions.
        repository = self.factory.makeGitRepository()
        with person_logged_in(repository.owner):
            view = create_initialized_view(repository, "+index")
            self.assertTrue(view.user_can_push)

    def test_user_can_push_admins_can(self):
        # Admins can push to any repository.
        repository = self.factory.makeGitRepository()
        with admin_logged_in():
            view = create_initialized_view(repository, "+index")
            self.assertTrue(view.user_can_push)

    def test_user_can_push_non_owner(self):
        # Someone not associated with the repository cannot upload.
        repository = self.factory.makeGitRepository()
        with person_logged_in(self.factory.makePerson()):
            view = create_initialized_view(repository, "+index")
            self.assertFalse(view.user_can_push)

    def test_view_for_user_with_artifact_grant(self):
        # Users with an artifact grant for a repository related to a private
        # project can view the main repository page.
        owner = self.factory.makePerson()
        user = self.factory.makePerson()
        project = self.factory.makeProduct(
            owner=owner, information_type=InformationType.PROPRIETARY)
        with person_logged_in(owner):
            project_name = project.name
            repository = self.factory.makeGitRepository(
                owner=owner, target=project,
                information_type=InformationType.PROPRIETARY)
            getUtility(IService, "sharing").ensureAccessGrants(
                [user], owner, gitrepositories=[repository])
        with person_logged_in(user):
            url = canonical_url(repository)
        # The main check: No Unauthorized error should be raised.
        browser = self.getUserBrowser(url, user=user)
        self.assertIn(project_name, browser.contents)


class TestGitRepositoryViewPrivateArtifacts(BrowserTestCase):
    """Tests that Git repositories with private team artifacts can be viewed.

    A repository may be associated with a private team as follows:
    - the owner is a private team

    A logged in user who is not authorised to see the private team(s) still
    needs to be able to view the repository.  The private team will be
    rendered in the normal way, displaying the team name and Launchpad URL.
    """

    layer = DatabaseFunctionalLayer

    def _getBrowser(self, user=None):
        if user is None:
            browser = setupBrowser()
            logout()
            return browser
        else:
            login_person(user)
            return setupBrowserForUser(user=user)

    def test_view_repository_with_private_owner(self):
        # A repository with a private owner is rendered.
        private_owner = self.factory.makeTeam(
            displayname="PrivateTeam", visibility=PersonVisibility.PRIVATE)
        with person_logged_in(private_owner):
            repository = self.factory.makeGitRepository(owner=private_owner)
        # Ensure the repository owner is rendered.
        url = canonical_url(repository, rootsite="code")
        user = self.factory.makePerson()
        browser = self._getBrowser(user)
        browser.open(url)
        soup = BeautifulSoup(browser.contents)
        self.assertIsNotNone(soup.find('a', text="PrivateTeam"))

    def test_anonymous_view_repository_with_private_owner(self):
        # A repository with a private owner is not rendered for anon users.
        self.useFixture(FakeLogger())
        private_owner = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE)
        with person_logged_in(private_owner):
            repository = self.factory.makeGitRepository(owner=private_owner)
        # Viewing the branch results in an error.
        url = canonical_url(repository, rootsite="code")
        browser = self._getBrowser()
        self.assertRaises(NotFound, browser.open, url)


class TestGitRepositoryBranches(BrowserTestCase):
    """Test the listing of branches in a Git repository."""

    layer = DatabaseFunctionalLayer

    def makeRevisionAuthor(self, person=None):
        if person is None:
            person = self.factory.makePerson()
        email = removeSecurityProxy(person).preferredemail.email
        return getUtility(IRevisionSet).acquireRevisionAuthors([email])[email]

    def test_query_count(self):
        # The number of queries is constant in the number of refs.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)
        now = datetime.now(pytz.UTC)

        def create_ref():
            with person_logged_in(person):
                [ref] = self.factory.makeGitRefs(repository=repository)
                naked_ref = removeSecurityProxy(ref)
                naked_ref.author = self.makeRevisionAuthor()
                naked_ref.author_date = now
                naked_ref.committer = self.makeRevisionAuthor()
                naked_ref.committer_date = now
                naked_ref.commit_message = u"something"

        recorder1, recorder2 = record_two_runs(
            lambda: self.getMainText(repository, "+index"), create_ref, 10)
        self.assertThat(recorder2, HasQueryCount(Equals(recorder1.count)))


class TestGitRepositoryEditReviewerView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_initial_reviewer_not_set(self):
        # If the reviewer is not set, the field is populated with the owner
        # of the repository.
        repository = self.factory.makeGitRepository()
        self.assertIsNone(repository.reviewer)
        view = create_view(repository, "+reviewer")
        self.assertEqual(repository.owner, view.initial_values["reviewer"])

    def test_initial_reviewer_set(self):
        # If the reviewer has been set, it is shown as the initial value.
        repository = self.factory.makeGitRepository()
        login_person(repository.owner)
        repository.reviewer = self.factory.makePerson()
        view = create_view(repository, "+reviewer")
        self.assertEqual(repository.reviewer, view.initial_values["reviewer"])

    def test_set_reviewer(self):
        # Test setting the reviewer.
        repository = self.factory.makeGitRepository()
        reviewer = self.factory.makePerson()
        login_person(repository.owner)
        view = create_initialized_view(repository, "+reviewer")
        view.change_action.success({"reviewer": reviewer})
        self.assertEqual(reviewer, repository.reviewer)
        # Last modified has been updated.
        self.assertSqlAttributeEqualsDate(
            repository, "date_last_modified", UTC_NOW)

    def test_set_reviewer_as_owner_clears_reviewer(self):
        # If the reviewer is set to be the repository owner, the review
        # field is cleared in the database.
        repository = self.factory.makeGitRepository()
        login_person(repository.owner)
        repository.reviewer = self.factory.makePerson()
        view = create_initialized_view(repository, "+reviewer")
        view.change_action.success({"reviewer": repository.owner})
        self.assertIsNone(repository.reviewer)
        # Last modified has been updated.
        self.assertSqlAttributeEqualsDate(
            repository, "date_last_modified", UTC_NOW)

    def test_set_reviewer_to_same_does_not_update_last_modified(self):
        # If the user has set the reviewer to be same and clicked on save,
        # then the underlying object hasn't really been changed, so the last
        # modified is not updated.
        modified_date = datetime(2007, 1, 1, tzinfo=pytz.UTC)
        repository = self.factory.makeGitRepository(date_created=modified_date)
        view = create_initialized_view(repository, "+reviewer")
        view.change_action.success({"reviewer": repository.owner})
        self.assertIsNone(repository.reviewer)
        # Last modified has not been updated.
        self.assertEqual(modified_date, repository.date_last_modified)


class TestGitRepositoryEditView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_rename(self):
        # The name of a repository can be changed via the UI by an
        # authorised user.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person, name=u"foo")
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=person)
        browser.getControl(name="field.name").value = u"bar"
        browser.getControl("Change Git Repository").click()
        with person_logged_in(person):
            self.assertEqual(u"bar", repository.name)

    def test_change_owner(self):
        # An authorised user can change the owner to a team they're a member
        # of.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(name="newowner", members=[person])
        repository = self.factory.makeGitRepository(owner=person)
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=person)
        browser.getControl(name="field.owner").value = ["newowner"]
        browser.getControl("Change Git Repository").click()
        with person_logged_in(person):
            self.assertEqual(team, repository.owner)

    def test_change_owner_personal(self):
        # An authorised user can change the owner of a personal repository
        # to a team they're a member of.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(name="newowner", members=[person])
        repository = self.factory.makeGitRepository(
            owner=person, target=person)
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=person)
        browser.getControl(name="field.owner").value = ["newowner"]
        browser.getControl("Change Git Repository").click()
        with person_logged_in(person):
            self.assertEqual(team, repository.owner)
            self.assertEqual(team, repository.target)

    def test_cannot_change_owner_to_foreign_team(self):
        # A user cannot change the owner of their repository to a team
        # they're not a member of.
        person = self.factory.makePerson()
        self.factory.makeTeam(name="newowner")
        repository = self.factory.makeGitRepository(owner=person)
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=person)
        self.assertNotIn(
            "newowner", browser.getControl(name="field.owner").options)

    def test_information_type_in_ui(self):
        # The information_type of a repository can be changed via the UI by
        # an authorised user.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)
        admin = getUtility(ILaunchpadCelebrities).admin.teamowner
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=admin)
        browser.getControl("Private", index=1).click()
        browser.getControl("Change Git Repository").click()
        with person_logged_in(person):
            self.assertEqual(
                InformationType.USERDATA, repository.information_type)

    def test_edit_view_ajax_render(self):
        # An information type change request is processed as expected when
        # an XHR request is made to the view.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)

        extra = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        request = LaunchpadTestRequest(
            method="POST", form={
                "field.actions.change": "Change Git Repository",
                "field.information_type": "PUBLICSECURITY"},
            **extra)
        with person_logged_in(person):
            view = create_initialized_view(
                repository, name="+edit-information-type",
                request=request, principal=person)
            request.traversed_objects = [
                person, repository.target, repository, view]
            result = view.render()
            self.assertEqual("", result)
            self.assertEqual(
                repository.information_type, InformationType.PUBLICSECURITY)

    def test_change_default_branch(self):
        # An authorised user can change the default branch to one that
        # exists.  They may omit "refs/heads/".
        hosting_client = FakeMethod()
        hosting_client.setProperties = FakeMethod()
        self.useFixture(ZopeUtilityFixture(hosting_client, IGitHostingClient))
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)
        master, new = self.factory.makeGitRefs(
            repository=repository,
            paths=[u"refs/heads/master", u"refs/heads/new"])
        removeSecurityProxy(repository)._default_branch = u"refs/heads/master"
        browser = self.getUserBrowser(
            canonical_url(repository) + "/+edit", user=person)
        browser.getControl(name="field.default_branch").value = u"new"
        browser.getControl("Change Git Repository").click()
        with person_logged_in(person):
            self.assertEqual(
                [((repository.getInternalPath(),),
                 {u"default_branch": u"refs/heads/new"})],
                hosting_client.setProperties.calls)
            self.assertEqual(u"refs/heads/new", repository.default_branch)

    def test_change_default_branch_nonexistent(self):
        # Trying to change the default branch to one that doesn't exist
        # displays an error.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)
        [master] = self.factory.makeGitRefs(
            repository=repository, paths=[u"refs/heads/master"])
        removeSecurityProxy(repository)._default_branch = u"refs/heads/master"
        form = {
            "field.default_branch": "refs/heads/new",
            "field.actions.change": "Change Git Repository",
            }
        transaction.commit()
        with person_logged_in(person):
            view = create_initialized_view(repository, name="+edit", form=form)
        self.assertEqual(
            ["This repository does not contain a reference named "
             "&#x27;refs/heads/new&#x27;."],
            view.errors)
        self.assertEqual(u"refs/heads/master", repository.default_branch)


class TestGitRepositoryEditViewInformationTypes(TestCaseWithFactory):
    """Tests for GitRepositoryEditView.getInformationTypesToShow."""

    layer = DatabaseFunctionalLayer

    def assertShownTypes(self, types, repository, user=None):
        if user is None:
            user = removeSecurityProxy(repository).owner
        with person_logged_in(user):
            view = create_initialized_view(repository, "+edit", user=user)
            self.assertContentEqual(types, view.getInformationTypesToShow())

    def test_public_repository(self):
        # A normal public repository on a public project can be any
        # information type except embargoed and proprietary.
        # The model doesn't enforce this, so it's just a UI thing.
        repository = self.factory.makeGitRepository(
            information_type=InformationType.PUBLIC)
        self.assertShownTypes(
            [InformationType.PUBLIC, InformationType.PUBLICSECURITY,
             InformationType.PRIVATESECURITY, InformationType.USERDATA],
            repository)

    def test_repository_with_disallowed_type(self):
        # We don't force repositories with a disallowed type (e.g.
        # Proprietary on a non-commercial project) to change, so the current
        # type is shown.
        project = self.factory.makeProduct()
        self.factory.makeAccessPolicy(pillar=project)
        repository = self.factory.makeGitRepository(
            target=project, information_type=InformationType.PROPRIETARY)
        self.assertShownTypes(
            [InformationType.PUBLIC, InformationType.PUBLICSECURITY,
             InformationType.PRIVATESECURITY, InformationType.USERDATA,
             InformationType.PROPRIETARY], repository)

    def test_repository_for_project_with_embargoed_and_proprietary(self):
        # Repositories for commercial projects which have a policy of
        # embargoed or proprietary allow only embargoed and proprietary
        # types.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct(owner=owner)
        self.factory.makeCommercialSubscription(product=project)
        with person_logged_in(owner):
            project.setBranchSharingPolicy(
                BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY)
            repository = self.factory.makeGitRepository(
                owner=owner, target=project,
                information_type=InformationType.PROPRIETARY)
        self.assertShownTypes(
            [InformationType.EMBARGOED, InformationType.PROPRIETARY],
            repository)

    def test_repository_for_project_with_proprietary(self):
        # Repositories for commercial projects which have a policy of
        # proprietary allow only the proprietary type.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct(owner=owner)
        self.factory.makeCommercialSubscription(product=product)
        with person_logged_in(owner):
            product.setBranchSharingPolicy(BranchSharingPolicy.PROPRIETARY)
            repository = self.factory.makeGitRepository(
                owner=owner, target=product,
                information_type=InformationType.PROPRIETARY)
        self.assertShownTypes([InformationType.PROPRIETARY], repository)


class TestGitRepositoryDeletionView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_repository_has_delete_link(self):
        # A newly-created repository has a "Delete repository" link.
        repository = self.factory.makeGitRepository()
        delete_url = canonical_url(
            repository, view_name="+delete", rootsite="code")
        browser = self.getViewBrowser(
            repository, "+index", rootsite="code", user=repository.owner)
        delete_link = browser.getLink("Delete repository")
        self.assertEqual(delete_url, delete_link.url)

    def test_warning_message(self):
        # The deletion view informs the user what will happen if they delete
        # the repository.
        repository = self.factory.makeGitRepository()
        name = repository.display_name
        text = self.getMainText(
            repository, "+delete", rootsite="code", user=repository.owner)
        self.assertThat(
            text, DocTestMatches(
                "Delete repository %s ...\n"
                "Repository deletion is permanent.\n"
                "or Cancel" % name,
                flags=(doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)))

    def test_next_url(self):
        # Deleting a repository takes the user back to the code listing for
        # the target, and shows a notification message.
        project = self.factory.makeProduct()
        project_url = canonical_url(project, rootsite="code")
        repository = self.factory.makeGitRepository(target=project)
        name = repository.unique_name
        browser = self.getViewBrowser(
            repository, "+delete", rootsite="code", user=repository.owner)
        browser.getControl("Delete").click()
        self.assertEqual(project_url, browser.url)
        self.assertEqual(
            ["Repository %s deleted." % name],
            get_feedback_messages(browser.contents))

    def test_next_url_personal(self):
        # Deleting a personal repository takes the user back to the code
        # listing for the owner, and shows a notification message.
        owner = self.factory.makePerson()
        owner_url = canonical_url(owner, rootsite="code")
        repository = self.factory.makeGitRepository(owner=owner, target=owner)
        name = repository.unique_name
        browser = self.getViewBrowser(
            repository, "+delete", rootsite="code", user=repository.owner)
        browser.getControl("Delete").click()
        self.assertEqual(owner_url, browser.url)
        self.assertEqual(
            ["Repository %s deleted." % name],
            get_feedback_messages(browser.contents))
