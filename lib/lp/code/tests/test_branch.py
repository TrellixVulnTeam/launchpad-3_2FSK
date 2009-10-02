# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for methods of Branch and BranchSet."""

import unittest

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.authorization import check_permission
from canonical.testing import DatabaseFunctionalLayer

from lp.archiveuploader.permission import verify_upload
from lp.code.enums import (
    BranchSubscriptionDiffSize, BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel)
from lp.code.interfaces.linkedbranch import ICanHasLinkedBranch
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.testing import run_with_login, TestCaseWithFactory


class PermissionTest(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def assertPermission(self, can_access, person, secure_object, permission):
        """Assert that 'person' can or cannot access 'secure_object'.

        :param can_access: Whether or not the person can access the object.
        :param person: The `IPerson` who is trying to access the object.
        :param secure_object: The secured object.
        :param permission: The Launchpad permission that 'person' is trying to
            access 'secure_object' with.
        """
        self.assertEqual(
            can_access,
            run_with_login(
                person, check_permission, permission, secure_object))

    def assertAuthenticatedView(self, branch, person, can_access):
        """Can 'branch' be accessed by 'person'?

        :param branch: The `IBranch` we're curious about.
        :param person: The `IPerson` trying to access it.
        :param can_access: Whether we expect 'person' be able to access it.
        """
        self.assertPermission(can_access, person, branch, 'launchpad.View')

    def assertUnauthenticatedView(self, branch, can_access):
        """Can 'branch' be accessed anonymously?

        :param branch: The `IBranch` we're curious about.
        :param can_access: Whether we expect to access it anonymously.
        """
        self.assertAuthenticatedView(branch, None, can_access)

    def assertCanEdit(self, person, secured_object):
        """Assert 'person' can edit 'secured_object'.

        That is, assert 'person' has 'launchpad.Edit' permissions on
        'secured_object'.

        :param person: An `IPerson`. None means anonymous.
        :param secured_object: An object, secured through the Zope security
            layer.
        """
        self.assertPermission(True, person, secured_object, 'launchpad.Edit')

    def assertCannotEdit(self, person, secured_object):
        """Assert 'person' cannot edit 'secured_object'.

        That is, assert 'person' does not have 'launchpad.Edit' permissions on
        'secured_object'.

        :param person: An `IPerson`. None means anonymous.
        :param secured_object: An object, secured through the Zope security
            layer.
        """
        self.assertPermission(False, person, secured_object, 'launchpad.Edit')


class TestAccessBranch(PermissionTest):

    def test_publicBranchUnauthenticated(self):
        # Public branches can be accessed without authentication.
        branch = self.factory.makeAnyBranch()
        self.assertUnauthenticatedView(branch, True)

    def test_publicBranchArbitraryUser(self):
        # Public branches can be accessed by anyone.
        branch = self.factory.makeAnyBranch()
        person = self.factory.makePerson()
        self.assertAuthenticatedView(branch, person, True)

    def test_privateBranchUnauthenticated(self):
        # Private branches cannot be accessed without authentication.
        branch = self.factory.makeAnyBranch(private=True)
        self.assertUnauthenticatedView(branch, False)

    def test_privateBranchOwner(self):
        # The owner of a branch can always access it.
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(private=True, owner=owner)
        self.assertAuthenticatedView(branch, owner, True)

    def test_privateBranchOwnerMember(self):
        # Any member of the team that owns the branch can access it.
        team_owner = self.factory.makePerson()
        team = self.factory.makeTeam(team_owner)
        person = self.factory.makePerson()
        removeSecurityProxy(team).addMember(person, team_owner)
        branch = self.factory.makeAnyBranch(private=True, owner=team)
        self.assertAuthenticatedView(branch, person, True)

    def test_privateBranchBazaarExperts(self):
        # The Bazaar experts can access any branch.
        celebs = getUtility(ILaunchpadCelebrities)
        branch = self.factory.makeAnyBranch(private=True)
        self.assertAuthenticatedView(
            branch, celebs.bazaar_experts.teamowner, True)

    def test_privateBranchAdmins(self):
        # Launchpad admins can access any branch.
        celebs = getUtility(ILaunchpadCelebrities)
        branch = self.factory.makeAnyBranch(private=True)
        self.assertAuthenticatedView(branch, celebs.admin.teamowner, True)

    def test_privateBranchSubscriber(self):
        # If you are subscribed to a branch, you can access it.
        branch = self.factory.makeAnyBranch(private=True)
        person = self.factory.makePerson()
        removeSecurityProxy(branch).subscribe(
            person, BranchSubscriptionNotificationLevel.NOEMAIL,
            BranchSubscriptionDiffSize.NODIFF,
            CodeReviewNotificationLevel.NOEMAIL)
        self.assertAuthenticatedView(branch, person, True)

    def test_privateBranchAnyoneElse(self):
        # In general, you can't access a private branch.
        branch = self.factory.makeAnyBranch(private=True)
        person = self.factory.makePerson()
        self.assertAuthenticatedView(branch, person, False)

    def test_stackedOnPrivateBranchUnauthenticated(self):
        # If a branch is stacked on a private branch, then you cannot access
        # it when unauthenticated.
        stacked_on_branch = self.factory.makeAnyBranch(private=True)
        stacked_branch = self.factory.makeAnyBranch(
            stacked_on=stacked_on_branch)
        self.assertUnauthenticatedView(stacked_branch, False)

    def test_stackedOnPrivateBranchAuthenticated(self):
        # If a branch is stacked on a private branch, you can only access it
        # if you can access both branches.
        stacked_on_branch = self.factory.makeAnyBranch(private=True)
        stacked_branch = self.factory.makeAnyBranch(
            stacked_on=stacked_on_branch)
        person = self.factory.makePerson()
        self.assertAuthenticatedView(stacked_branch, person, False)

    def test_manyLevelsOfStackingUnauthenticated(self):
        # If a branch is stacked on a branch stacked on a private branch, you
        # still can't access it when unauthenticated.
        stacked_on_branch = self.factory.makeAnyBranch(private=True)
        branch_a = self.factory.makeAnyBranch(stacked_on=stacked_on_branch)
        branch_b = self.factory.makeAnyBranch(stacked_on=branch_a)
        self.assertUnauthenticatedView(branch_b, False)

    def test_manyLevelsOfStackingAuthenticated(self):
        # If a branch is stacked on a branch stacked on a private branch, you
        # still can't access it when unauthenticated.
        stacked_on_branch = self.factory.makeAnyBranch(private=True)
        branch_a = self.factory.makeAnyBranch(stacked_on=stacked_on_branch)
        branch_b = self.factory.makeAnyBranch(stacked_on=branch_a)
        person = self.factory.makePerson()
        self.assertAuthenticatedView(branch_b, person, False)

    def test_loopedPublicStackedOn(self):
        # It's possible, although nonsensical, for branch stackings to form a
        # loop. e.g., branch A is stacked on branch B is stacked on branch A.
        # If all of these branches are public, then we want anyone to be able
        # to access it / them.
        stacked_branch = self.factory.makeAnyBranch()
        removeSecurityProxy(stacked_branch).stacked_on = stacked_branch
        person = self.factory.makePerson()
        self.assertAuthenticatedView(stacked_branch, person, True)

    def test_loopedPrivateStackedOn(self):
        # It's possible, although nonsensical, for branch stackings to form a
        # loop. e.g., branch A is stacked on branch B is stacked on branch A.
        # If all of these branches are private, then only people who can
        # access all of them can get to them.
        stacked_branch = self.factory.makeAnyBranch(private=True)
        removeSecurityProxy(stacked_branch).stacked_on = stacked_branch
        person = self.factory.makePerson()
        self.assertAuthenticatedView(stacked_branch, person, False)

    def test_loopedPublicStackedOnUnauthenticated(self):
        # It's possible, although nonsensical, for branch stackings to form a
        # loop. e.g., branch A is stacked on branch B is stacked on branch A.
        # If all of these branches are public, then you can get them without
        # being logged in.
        stacked_branch = self.factory.makeAnyBranch()
        removeSecurityProxy(stacked_branch).stacked_on = stacked_branch
        self.assertUnauthenticatedView(stacked_branch, True)


class TestWriteToBranch(PermissionTest):
    """Test who can write to branches."""

    def test_owner_can_write(self):
        # The owner of a branch can write to the branch.
        branch = self.factory.makeAnyBranch()
        self.assertCanEdit(branch.owner, branch)

    def test_random_person_cannot_write(self):
        # Arbitrary logged in people cannot write to branches.
        branch = self.factory.makeAnyBranch()
        person = self.factory.makePerson()
        self.assertCannotEdit(person, branch)

    def test_member_of_owning_team_can_write(self):
        # Members of the team that owns a branch can write to the branch.
        team = self.factory.makeTeam()
        person = self.factory.makePerson()
        removeSecurityProxy(team).addMember(person, team.teamowner)
        branch = self.factory.makeAnyBranch(owner=team)
        self.assertCanEdit(person, branch)

    def makeOfficialPackageBranch(self):
        """Make a branch linked to the pocket of a source package."""
        branch = self.factory.makePackageBranch()
        pocket = self.factory.getAnyPocket()
        sourcepackage = branch.sourcepackage
        suite_sourcepackage = sourcepackage.getSuiteSourcePackage(pocket)
        registrant = self.factory.makePerson()
        ubuntu_branches = getUtility(ILaunchpadCelebrities).ubuntu_branches
        run_with_login(
            ubuntu_branches.teamowner,
            ICanHasLinkedBranch(suite_sourcepackage).setBranch,
            branch, registrant)
        return branch

    def test_owner_can_write_to_official_package_branch(self):
        # The owner of an official package branch can write to it, just like a
        # regular person.
        branch = self.makeOfficialPackageBranch()
        self.assertCanEdit(branch.owner, branch)

    def personMayEditBranch(self, person, branch):
        """Return True if person may edit branch.

        A person P may be allowed to edit the branch B on the following
        grounds:

          - P is owner of B or member of team owning B
          - B is a source package branch (i.e. a branch linked to a
            source package SP in the distro series DS, component C) and
            - P is authorised to upload SP in DS.distribution.main_archive
            - P is authorised to upload to C in DS.distribution.main_archive
            - P is authorised to upload SP via a package set

        Please note: this method is not in the proper place here and needs
        to find a better home.
        """
        def current_component(ds, package):
            releases = ds.getCurrentSourceReleases(
                [package.sourcepackagename])
            return releases.get(package, None)

        # This is a bit hacky but works in the context of the test at hand.
        result = run_with_login(
            person, check_permission, 'launchpad.Edit', branch)
        # P is owner of B or member of team owning B.
        if result == True:
            return result

        # Check whether we're dealing with a source package branch and
        # whether person is authorised to upload the respective source
        # package.
        package = branch.sourcepackage
        if package is None:
            # No package .. hmm .. this can't be a source package branch
            # then. Abort.
            return False

        distroseries = branch.distroseries
        if distroseries is None:
            # No distro series? Very fishy .. abort.
            return False

        archive = branch.distroseries.distribution.main_archive
        spn = package.sourcepackagename
        component = current_component(distroseries, package)

        # Is person authorised to upload the source package this branch
        # is targeting?
        result = verify_upload(person, spn, archive, component)
        # verify_upload() indicates that person *is* allowed to upload by
        # returning None.
        return result is None
        
    def assertCanUpload(self, person, spn, archive, component,
                        strict_component=True):
        """Assert that 'person' can upload 'spn' to 'archive'."""
        # For now, just check that doesn't raise an exception.
        self.assertIs(
            None,
            verify_upload(person, spn, archive, component, strict_component))

    def assertCannotUpload(self, reason, person, spn, archive, component):
        """Assert that 'person' cannot upload to the archive.

        :param reason: The expected reason for not being able to upload. A
            string.
        :param person: The person trying to upload.
        :param spn: The `ISourcePackageName` being uploaded to. None if the
            package does not yet exist.
        :param archive: The `IArchive` being uploaded to.
        :param component: The IComponent to which the package belongs.
        """
        exception = verify_upload(person, spn, archive, component)
        self.assertEqual(reason, str(exception))

    def test_package_upload_permissions_grant_branch_edit(self):
        # If you can upload to the package, then you are also allowed to write
        # to the branch.
        permission_set = getUtility(IArchivePermissionSet)
        # Only admins or techboard members can add permissions normally. That
        # restriction isn't relevant to these tests.
        self.permission_set = removeSecurityProxy(permission_set)
        branch = self.makeOfficialPackageBranch()
        package = branch.sourcepackage
        person = self.factory.makePerson()
        # Give 'person' permission to upload to 'package'.
        archive = branch.distroseries.distribution.main_archive
        spn = package.sourcepackagename
        self.permission_set.newPackageUploader(archive, person, spn)

        # Make sure person *is* authorised to upload the source package
        # targeted by the branch at hand.
        self.assertCanUpload(person, spn, archive, None)
        # Now person should be able to edit.
        self.assertTrue(self.personMayEditBranch(person, branch))

        # person2 has no upload rights ..
        person2 = self.factory.makePerson()
        self.assertCannotUpload(
            ("The signer of this package has no upload rights to this "
             "distribution's primary archive.  Did you mean to upload to "
             "a PPA?"),
            person2, spn, archive, None)
        # .. and is not authorised to edit the branch.
        self.assertFalse(self.personMayEditBranch(person2, branch))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
