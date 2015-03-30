# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal Git API."""

__metaclass__ = type

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.code.errors import GitRepositoryCreationFault
from lp.code.interfaces.codehosting import (
    LAUNCHPAD_ANONYMOUS,
    LAUNCHPAD_SERVICES,
    )
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.code.interfaces.gitjob import IGitRefScanJobSource
from lp.code.interfaces.gitrepository import (
    GIT_FEATURE_FLAG,
    GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE,
    IGitRepositorySet,
    )
from lp.code.xmlrpc.git import GitAPI
from lp.services.features.testing import FeatureFixture
from lp.services.webapp.escaping import html_escape
from lp.testing import (
    ANONYMOUS,
    login,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    AppServerLayer,
    LaunchpadFunctionalLayer,
    )
from lp.xmlrpc import faults


class FakeGitHostingClient:
    """A GitHostingClient lookalike that just logs calls."""

    def __init__(self):
        self.calls = []

    def create(self, path):
        self.calls.append(("create", path))


class BrokenGitHostingClient:
    """A GitHostingClient lookalike that pretends the remote end is down."""

    def create(self, path):
        raise GitRepositoryCreationFault("nothing here")


class TestGitAPIFeatureFlag(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestGitAPIFeatureFlag, self).setUp()
        self.git_api = GitAPI(None, None)
        self.git_api.hosting_client = FakeGitHostingClient()

    def test_feature_flag_disabled(self):
        # Without a feature flag, attempts to create a new Git repository fail.
        requester = self.factory.makePerson()
        message = "You do not have permission to create Git repositories."
        fault = self.git_api.translatePath(
            u"/~%s/+git/random" % requester.name, "write", requester.id, True)
        self.assertEqual(faults.PermissionDenied(message), fault)

    def test_feature_flag_disabled_existing(self):
        # Even without a feature flag, it is possible to operate on Git
        # repositories that already exist.
        requester = self.factory.makePerson()
        path = u"/~%s/+git/random" % requester.name
        with FeatureFixture({GIT_FEATURE_FLAG: u"on"}):
            translation = self.git_api.translatePath(
                path, "write", requester.id, True)
        login(ANONYMOUS)
        repository = getUtility(IGitRepositorySet).getByPath(
            requester, path.lstrip("/"))
        self.assertIsNotNone(repository)
        self.assertEqual(
            {"path": repository.getInternalPath(), "writable": True,
             "trailing": ""},
            translation)
        translation = self.git_api.translatePath(
            path, "write", requester.id, True)
        login(ANONYMOUS)
        self.assertEqual(
            {"path": repository.getInternalPath(), "writable": True,
             "trailing": ""},
            translation)
        # But we cannot create another one without the feature flag.
        message = "You do not have permission to create Git repositories."
        fault = self.git_api.translatePath(
            u"/~%s/+git/another" % requester.name, "write", requester.id, True)
        self.assertEqual(faults.PermissionDenied(message), fault)


class TestGitAPIMixin:
    """Helper methods for `IGitAPI` tests, and security-relevant tests."""

    def setUp(self):
        super(TestGitAPIMixin, self).setUp()
        self.useFixture(FeatureFixture({GIT_FEATURE_FLAG: u"on"}))
        self.git_api = GitAPI(None, None)
        self.git_api.hosting_client = FakeGitHostingClient()

    def assertPathTranslationError(self, requester, path, permission="read",
                                   can_authenticate=False):
        """Assert that the given path cannot be translated."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.PathTranslationError(path.strip("/")), fault)

    def assertPermissionDenied(self, requester, path,
                               message="Permission denied.",
                               permission="read", can_authenticate=False):
        """Assert that looking at the given path returns PermissionDenied."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.PermissionDenied(message), fault)

    def assertUnauthorized(self, requester, path,
                           message="Authorisation required.",
                           permission="read", can_authenticate=False):
        """Assert that looking at the given path returns Unauthorized."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.Unauthorized(message), fault)

    def assertNotFound(self, requester, path, message, permission="read",
                       can_authenticate=False):
        """Assert that looking at the given path returns NotFound."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.NotFound(message), fault)

    def assertInvalidSourcePackageName(self, requester, path, name,
                                       permission="read",
                                       can_authenticate=False):
        """Assert that looking at the given path returns
        InvalidSourcePackageName."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.InvalidSourcePackageName(name), fault)

    def assertInvalidBranchName(self, requester, path, message,
                                permission="read", can_authenticate=False):
        """Assert that looking at the given path returns InvalidBranchName."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertEqual(faults.InvalidBranchName(Exception(message)), fault)

    def assertOopsOccurred(self, requester, path,
                           permission="read", can_authenticate=False):
        """Assert that looking at the given path OOPSes."""
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        fault = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        self.assertIsInstance(fault, faults.OopsOccurred)
        prefix = (
            "An unexpected error has occurred while creating a Git "
            "repository. Please report a Launchpad bug and quote: ")
        self.assertStartsWith(fault.faultString, prefix)
        return fault.faultString[len(prefix):].rstrip(".")

    def assertTranslates(self, requester, path, repository, writable,
                         permission="read", can_authenticate=False,
                         trailing=""):
        if requester not in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester = requester.id
        translation = self.git_api.translatePath(
            path, permission, requester, can_authenticate)
        login(ANONYMOUS)
        self.assertEqual(
            {"path": repository.getInternalPath(), "writable": writable,
             "trailing": trailing},
            translation)

    def assertCreates(self, requester, path, can_authenticate=False):
        if requester in (LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES):
            requester_id = requester
        else:
            requester_id = requester.id
        translation = self.git_api.translatePath(
            path, "write", requester_id, can_authenticate)
        login(ANONYMOUS)
        repository = getUtility(IGitRepositorySet).getByPath(
            requester, path.lstrip("/"))
        self.assertIsNotNone(repository)
        self.assertEqual(requester, repository.registrant)
        self.assertEqual(
            {"path": repository.getInternalPath(), "writable": True,
             "trailing": ""},
            translation)
        self.assertEqual(
            [("create", repository.getInternalPath())],
            self.git_api.hosting_client.calls)
        return repository

    def test_translatePath_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                owner=requester, information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, True)

    def test_translatePath_cannot_see_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertPermissionDenied(requester, path)

    def test_translatePath_anonymous_cannot_see_private_repository(self):
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertPermissionDenied(
            LAUNCHPAD_ANONYMOUS, path, can_authenticate=False)
        self.assertUnauthorized(
            LAUNCHPAD_ANONYMOUS, path, can_authenticate=True)

    def test_translatePath_team_unowned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(self.factory.makePerson())
        repository = self.factory.makeGitRepository(owner=team)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)
        self.assertPermissionDenied(requester, path, permission="write")

    def test_translatePath_create_personal_team_denied(self):
        # translatePath refuses to create a personal repository for a team
        # of which the requester is not a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam()
        message = "%s is not a member of %s" % (
            requester.displayname, team.displayname)
        self.assertPermissionDenied(
            requester, u"/~%s/+git/random" % team.name, message=message,
            permission="write")

    def test_translatePath_create_other_user(self):
        # Creating a repository for another user fails.
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        project = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        path = u"/~%s/%s/+git/%s" % (other_person.name, project.name, name)
        message = "%s cannot create Git repositories owned by %s" % (
            requester.displayname, other_person.displayname)
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_project_not_owner(self):
        # Somebody without edit permission on the project cannot create a
        # repository and immediately set it as the default for that project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = u"/%s" % project.name
        message = "You cannot set the default Git repository for '%s'." % (
            path.strip("/"))
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())

    def test_translatePath_create_project_not_team_owner_default(self):
        # A non-owner member of a team cannot immediately set a
        # newly-created team-owned repository as that team's default for a
        # project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        project = self.factory.makeProduct()
        path = u"/~%s/%s" % (team.name, project.name)
        message = "You cannot set the default Git repository for '%s'." % (
            path.strip("/"))
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())

    def test_translatePath_create_package_not_team_owner_default(self):
        # A non-owner member of a team cannot immediately set a
        # newly-created team-owned repository as that team's default for a
        # package.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            team.name, dsp.distribution.name, dsp.sourcepackagename.name)
        message = "You cannot set the default Git repository for '%s'." % (
            path.strip("/"))
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())


class TestGitAPI(TestGitAPIMixin, TestCaseWithFactory):
    """Tests for the implementation of `IGitAPI`."""

    layer = LaunchpadFunctionalLayer

    def test_translatePath_cannot_translate(self):
        # Sometimes translatePath will not know how to translate a path.
        # When this happens, it returns a Fault saying so, including the
        # path it couldn't translate.
        requester = self.factory.makePerson()
        self.assertPathTranslationError(requester, u"/untranslatable")

    def test_translatePath_repository(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_no_leading_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_trailing_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s/" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_trailing_segments(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s/foo/bar" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, False, trailing="foo/bar")

    def test_translatePath_no_such_repository(self):
        requester = self.factory.makePerson()
        path = u"/%s/+git/no-such-repository" % requester.name
        self.assertPathTranslationError(requester, path)

    def test_translatePath_no_such_repository_non_ascii(self):
        requester = self.factory.makePerson()
        path = u"/%s/+git/\N{LATIN SMALL LETTER I WITH DIAERESIS}" % (
            requester.name)
        self.assertPathTranslationError(requester, path)

    def test_translatePath_anonymous_public_repository(self):
        repository = self.factory.makeGitRepository()
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            LAUNCHPAD_ANONYMOUS, path, repository, False,
            can_authenticate=False)
        self.assertTranslates(
            LAUNCHPAD_ANONYMOUS, path, repository, False,
            can_authenticate=True)

    def test_translatePath_owned(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, True, permission="write")

    def test_translatePath_team_owned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(requester)
        repository = self.factory.makeGitRepository(owner=team)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, True, permission="write")

    def test_translatePath_shortened_path(self):
        # translatePath translates the shortened path to a repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        with person_logged_in(repository.target.owner):
            getUtility(IGitRepositorySet).setDefaultRepository(
                repository.target, repository)
        path = u"/%s" % repository.target.name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_create_project(self):
        # translatePath creates a project repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        self.assertCreates(
            requester, u"/~%s/%s/+git/random" % (requester.name, project.name))

    def test_translatePath_create_package(self):
        # translatePath creates a package repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        self.assertCreates(
            requester,
            u"/~%s/%s/+source/%s/+git/random" % (
                requester.name,
                dsp.distribution.name, dsp.sourcepackagename.name))

    def test_translatePath_create_personal(self):
        # translatePath creates a personal repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        self.assertCreates(requester, u"/~%s/+git/random" % requester.name)

    def test_translatePath_create_personal_team(self):
        # translatePath creates a personal repository for a team of which
        # the requester is a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        self.assertCreates(requester, u"/~%s/+git/random" % team.name)

    def test_translatePath_anonymous_cannot_create(self):
        # Anonymous users cannot create repositories.
        project = self.factory.makeProject()
        self.assertPathTranslationError(
            LAUNCHPAD_ANONYMOUS, u"/%s" % project.name,
            permission="write", can_authenticate=False)
        self.assertPathTranslationError(
            LAUNCHPAD_ANONYMOUS, u"/%s" % project.name,
            permission="write", can_authenticate=True)

    def test_translatePath_create_invalid_namespace(self):
        # Trying to create a repository at a path that isn't valid for Git
        # repositories returns a PermissionDenied fault.
        requester = self.factory.makePerson()
        path = u"/~%s" % requester.name
        message = "'%s' is not a valid Git repository path." % path.strip("/")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_no_such_person(self):
        # Creating a repository for a non-existent person fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_no_such_project(self):
        # Creating a repository for a non-existent project fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~%s/nonexistent/+git/random" % requester.name,
            "Project 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_no_such_person_or_project(self):
        # If neither the person nor the project are found, then the missing
        # person is reported in preference.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~nonexistent/nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_invalid_project(self):
        # Creating a repository with an invalid project name fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/_bad_project/+git/random",
            "Project '_bad_project' does not exist.", permission="write")

    def test_translatePath_create_missing_sourcepackagename(self):
        # If translatePath is asked to create a repository for a missing
        # source package, it will create the source package.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = u"/~%s/%s/+source/new-package/+git/%s" % (
            requester.name, distro.name, repository_name)
        repository = self.assertCreates(requester, path)
        self.assertEqual(
            "new-package", repository.target.sourcepackagename.name)

    def test_translatePath_create_invalid_sourcepackagename(self):
        # Creating a repository for an invalid source package name fails.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = u"/~%s/%s/+source/new package/+git/%s" % (
            requester.name, distro.name, repository_name)
        self.assertInvalidSourcePackageName(
            requester, path, "new package", permission="write")

    def test_translatePath_create_bad_name(self):
        # Creating a repository with an invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = "invalid name!"
        path = u"/~%s/%s/+git/%s" % (
            requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s" %
            (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE))
        self.assertInvalidBranchName(
            requester, path, message, permission="write")

    def test_translatePath_create_unicode_name(self):
        # Creating a repository with a non-ASCII invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = u"invalid\N{LATIN SMALL LETTER E WITH ACUTE}"
        path = u"/~%s/%s/+git/%s" % (
            requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s" %
            (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE))
        self.assertInvalidBranchName(
            requester, path, message, permission="write")

    def test_translatePath_create_project_default(self):
        # A repository can be created and immediately set as the default for
        # a project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct(owner=requester)
        repository = self.assertCreates(requester, u"/%s" % project.name)
        self.assertTrue(repository.target_default)
        self.assertFalse(repository.owner_default)

    def test_translatePath_create_package_default_denied(self):
        # A repository cannot (yet) be created and immediately set as the
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/%s/+source/%s" % (
            dsp.distribution.name, dsp.sourcepackagename.name)
        message = (
            "Cannot automatically set the default repository for this target; "
            "push to a named repository instead.")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_project_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, u"/~%s/%s" % (requester.name, project.name))
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)

    def test_translatePath_create_project_team_owner_default(self):
        # The owner of a team can create a team-owned repository and
        # immediately set it as that team's default for a project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(owner=requester)
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, u"/~%s/%s" % (team.name, project.name))
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)

    def test_translatePath_create_package_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            requester.name, dsp.distribution.name, dsp.sourcepackagename.name)
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)

    def test_translatePath_create_package_team_owner_default(self):
        # The owner of a team can create a team-owned repository and
        # immediately set it as that team's default for a package.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(owner=requester)
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            team.name, dsp.distribution.name, dsp.sourcepackagename.name)
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)

    def test_translatePath_create_broken_hosting_service(self):
        # If the hosting service is down, trying to create a repository
        # fails and doesn't leave junk around in the Launchpad database.
        self.git_api.hosting_client = BrokenGitHostingClient()
        requester = self.factory.makePerson()
        initial_count = getUtility(IAllGitRepositories).count()
        oops_id = self.assertOopsOccurred(
            requester, u"/~%s/+git/random" % requester.name,
            permission="write")
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())
        # The error report OOPS ID should match the fault, and the traceback
        # text should show the underlying exception.
        self.assertEqual(1, len(self.oopses))
        self.assertEqual(oops_id, self.oopses[0]["id"])
        self.assertIn(
            "GitRepositoryCreationFault: nothing here",
            self.oopses[0]["tb_text"])

    def test_notify(self):
        # The notify call creates a GitRefScanJob.
        repository = self.factory.makeGitRepository()
        self.assertIsNone(self.git_api.notify(repository.getInternalPath()))
        job_source = getUtility(IGitRefScanJobSource)
        [job] = list(job_source.iterReady())
        self.assertEqual(repository, job.repository)

    def test_notify_missing_repository(self):
        # A notify call on a non-existent repository returns a fault and
        # does not create a job.
        fault = self.git_api.notify("10000")
        self.assertIsInstance(fault, faults.NotFound)
        job_source = getUtility(IGitRefScanJobSource)
        self.assertEqual([], list(job_source.iterReady()))


class TestGitAPISecurity(TestGitAPIMixin, TestCaseWithFactory):
    """Slow tests for `IGitAPI`.

    These use AppServerLayer to check that `run_with_login` is behaving
    itself properly.
    """

    layer = AppServerLayer
