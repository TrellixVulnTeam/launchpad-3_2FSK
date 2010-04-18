# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal codehosting API."""

__metaclass__ = type

import datetime
import pytz
import unittest

from bzrlib.tests import multiply_tests
from bzrlib.urlutils import escape

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.codehosting.inmemory import InMemoryFrontend
from canonical.database.constants import UTC_NOW
from canonical.launchpad.ftests import ANONYMOUS, login, logout
from lp.services.scripts.interfaces.scriptactivity import (
    IScriptActivitySet)
from lp.code.interfaces.codehosting import (
    BRANCH_TRANSPORT, CONTROL_TRANSPORT)
from canonical.launchpad.interfaces.launchpad import ILaunchBag
from lp.testing import TestCaseWithFactory
from lp.testing.factory import LaunchpadObjectFactory
from canonical.launchpad.webapp.interfaces import NotFoundError
from canonical.launchpad.xmlrpc import faults
from canonical.testing import DatabaseFunctionalLayer, FunctionalLayer

from lp.code.enums import BranchType
from lp.code.errors import UnknownBranchTypeError
from lp.code.interfaces.branch import BRANCH_NAME_VALIDATION_ERROR_MESSAGE
from lp.code.interfaces.branchjob import IBranchScanJobSource
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.branchtarget import IBranchTarget
from lp.code.model.tests.test_branchpuller import AcquireBranchToPullTests
from lp.code.xmlrpc.codehosting import (
    BranchFileSystem, BranchPuller, LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES,
    run_with_login)


UTC = pytz.timezone('UTC')


def get_logged_in_username(requester=None):
    """Return the username of the logged in person.

    Used by `TestRunWithLogin`.
    """
    user = getUtility(ILaunchBag).user
    if user is None:
        return None
    return user.name


class TestRunWithLogin(TestCaseWithFactory):
    """Tests for the `run_with_login` decorator."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestRunWithLogin, self).setUp()
        self.person = self.factory.makePerson()

    def test_loginAsRequester(self):
        # run_with_login logs in as user given as the first argument
        # to the method being decorated.
        username = run_with_login(self.person.id, get_logged_in_username)
        # person.name is a protected field so we must be logged in before
        # attempting to access it.
        login(ANONYMOUS)
        self.assertEqual(self.person.name, username)
        logout()

    def test_loginAsRequesterName(self):
        # run_with_login can take a username as well as user id.
        username = run_with_login(self.person.name, get_logged_in_username)
        login(ANONYMOUS)
        self.assertEqual(self.person.name, username)
        logout()

    def test_logoutAtEnd(self):
        # run_with_login logs out once the decorated method is
        # finished.
        run_with_login(self.person.id, get_logged_in_username)
        self.assertEqual(None, get_logged_in_username())

    def test_logoutAfterException(self):
        # run_with_login logs out even if the decorated method raises
        # an exception.
        def raise_exception(requester, exc_factory, *args):
            raise exc_factory(*args)
        self.assertRaises(
            RuntimeError, run_with_login, self.person.id, raise_exception,
            RuntimeError, 'error message')
        self.assertEqual(None, get_logged_in_username())

    def test_passesRequesterInAsPerson(self):
        # run_with_login passes in the Launchpad Person object of the
        # requesting user.
        user = run_with_login(self.person.id, lambda x: x)
        login(ANONYMOUS)
        self.assertEqual(self.person.name, user.name)
        logout()

    def test_invalidRequester(self):
        # A method wrapped with run_with_login raises NotFoundError if
        # there is no person with the passed in id.
        self.assertRaises(
            NotFoundError, run_with_login, -1, lambda x: None)

    def test_cheatsForLaunchpadServices(self):
        # Various Launchpad services need to use the authserver to get
        # information about branches, unencumbered by petty
        # restrictions of ownership or privacy. `run_with_login`
        # detects the special username `LAUNCHPAD_SERVICES` and passes
        # that through to the decorated function without logging in.
        username = run_with_login(LAUNCHPAD_SERVICES, lambda x: x)
        self.assertEqual(LAUNCHPAD_SERVICES, username)
        login_id = run_with_login(LAUNCHPAD_SERVICES, get_logged_in_username)
        self.assertEqual(None, login_id)


class BranchPullerTest(TestCaseWithFactory):
    """Tests for the implementation of `IBranchPuller`.

    :ivar frontend: A nullary callable that returns an object that implements
        getPullerEndpoint, getLaunchpadObjectFactory and getBranchLookup.
    """

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        frontend = self.frontend()
        self.storage = frontend.getPullerEndpoint()
        self.factory = frontend.getLaunchpadObjectFactory()
        self.branch_lookup = frontend.getBranchLookup()
        self.getLastActivity = frontend.getLastActivity

    def assertMirrorFailed(self, branch, failure_message, num_failures=1):
        """Assert that `branch` failed to mirror.

        :param branch: The branch that failed to mirror.
        :param failure_message: The last message that the branch failed with.
        :param num_failures: The number of times this branch has failed to
            mirror. Defaults to one.
        """
        self.assertSqlAttributeEqualsDate(
            branch, 'last_mirror_attempt', UTC_NOW)
        self.assertIs(None, branch.last_mirrored)
        self.assertEqual(num_failures, branch.mirror_failures)
        self.assertEqual(failure_message, branch.mirror_status_message)

    def assertMirrorSucceeded(self, branch, revision_id):
        """Assert that `branch` mirrored to `revision_id`."""
        self.assertSqlAttributeEqualsDate(
            branch, 'last_mirror_attempt', UTC_NOW)
        self.assertSqlAttributeEqualsDate(
            branch, 'last_mirrored', UTC_NOW)
        self.assertEqual(0, branch.mirror_failures)
        self.assertEqual(revision_id, branch.last_mirrored_id)

    def assertUnmirrored(self, branch):
        """Assert that `branch` has not yet been mirrored.

        Asserts that last_mirror_attempt, last_mirrored and
        mirror_status_message are all None, and that mirror_failures is 0.
        """
        self.assertIs(None, branch.last_mirror_attempt)
        self.assertIs(None, branch.last_mirrored)
        self.assertEqual(0, branch.mirror_failures)
        self.assertIs(None, branch.mirror_status_message)

    def getUnusedBranchID(self):
        """Return a branch ID that isn't in the database."""
        branch_id = 999
        # We can't be sure until the sample data is gone.
        self.assertIs(self.branch_lookup.get(branch_id), None)
        return branch_id

    def test_startMirroring(self):
        # startMirroring updates last_mirror_attempt to 'now', leaves
        # last_mirrored alone and returns True when passed the id of an
        # existing branch.
        branch = self.factory.makeAnyBranch()
        self.assertUnmirrored(branch)

        success = self.storage.startMirroring(branch.id)
        self.assertEqual(success, True)

        self.assertSqlAttributeEqualsDate(
            branch, 'last_mirror_attempt', UTC_NOW)
        self.assertIs(None, branch.last_mirrored)

    def test_startMirroringInvalidBranch(self):
        # startMirroring returns False when given a branch id which does not
        # exist.
        invalid_id = self.getUnusedBranchID()
        fault = self.storage.startMirroring(invalid_id)
        self.assertEqual(faults.NoBranchWithID(invalid_id), fault)

    def test_mirrorFailed(self):
        branch = self.factory.makeAnyBranch()
        self.assertUnmirrored(branch)

        self.storage.startMirroring(branch.id)
        failure_message = self.factory.getUniqueString()
        success = self.storage.mirrorFailed(branch.id, failure_message)
        self.assertEqual(True, success)
        self.assertMirrorFailed(branch, failure_message)

    def test_mirrorFailedWithNotBranchID(self):
        branch_id = self.getUnusedBranchID()
        failure_message = self.factory.getUniqueString()
        fault = self.storage.mirrorFailed(branch_id, failure_message)
        self.assertEqual(faults.NoBranchWithID(branch_id), fault)

    def test_mirrorComplete(self):
        # mirrorComplete marks the branch as having been successfully
        # mirrored, with no failures and no status message.
        branch = self.factory.makeAnyBranch()
        self.assertUnmirrored(branch)

        self.storage.startMirroring(branch.id)
        revision_id = self.factory.getUniqueString()
        success = self.storage.mirrorComplete(branch.id, revision_id)
        self.assertEqual(True, success)
        self.assertMirrorSucceeded(branch, revision_id)

    def test_mirrorCompleteWithNoBranchID(self):
        # mirrorComplete returns a Fault if there's no branch with the given
        # ID.
        branch_id = self.getUnusedBranchID()
        fault = self.storage.mirrorComplete(
            branch_id, self.factory.getUniqueString())
        self.assertEqual(faults.NoBranchWithID(branch_id), fault)

    def test_mirrorComplete_resets_failure_count(self):
        # mirrorComplete marks the branch as successfully mirrored and removes
        # all memory of failure.

        # First, mark the branch as failed.
        branch = self.factory.makeAnyBranch()
        self.storage.startMirroring(branch.id)
        failure_message = self.factory.getUniqueString()
        self.storage.mirrorFailed(branch.id, failure_message)
        self.assertMirrorFailed(branch, failure_message)

        # Start and successfully finish a mirror.
        self.storage.startMirroring(branch.id)
        revision_id = self.factory.getUniqueString()
        self.storage.mirrorComplete(branch.id, revision_id)

        # Confirm that it succeeded.
        self.assertMirrorSucceeded(branch, revision_id)

    def test_mirrorComplete_resets_mirror_request(self):
        # After successfully mirroring a hosted branch, next_mirror_time
        # should be set to NULL.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)

        # Request that branch be mirrored. This sets next_mirror_time.
        branch.requestMirror()

        # Simulate successfully mirroring the branch.
        self.storage.startMirroring(branch.id)
        self.storage.mirrorComplete(branch.id, self.factory.getUniqueString())

        self.assertIs(None, branch.next_mirror_time)

    def test_recordSuccess(self):
        # recordSuccess must insert the given data into ScriptActivity.
        started = datetime.datetime(2007, 07, 05, 19, 32, 1, tzinfo=UTC)
        completed = datetime.datetime(2007, 07, 05, 19, 34, 24, tzinfo=UTC)
        started_tuple = tuple(started.utctimetuple())
        completed_tuple = tuple(completed.utctimetuple())
        success = self.storage.recordSuccess(
            'test-recordsuccess', 'vostok', started_tuple, completed_tuple)
        self.assertEqual(True, success)

        activity = self.getLastActivity('test-recordsuccess')
        self.assertEqual('vostok', activity.hostname)
        self.assertEqual(started, activity.date_started)
        self.assertEqual(completed, activity.date_completed)

    def test_setStackedOnDefaultURLFragment(self):
        # setStackedOn records that one branch is stacked on another. One way
        # to find the stacked-on branch is by the URL fragment that's
        # generated as part of Launchpad's default stacking.
        stacked_branch = self.factory.makeAnyBranch()
        stacked_on_branch = self.factory.makeAnyBranch()
        self.storage.setStackedOn(
            stacked_branch.id, '/%s' % stacked_on_branch.unique_name)
        self.assertEqual(stacked_branch.stacked_on, stacked_on_branch)

    def test_setStackedOnExternalURL(self):
        # If setStackedOn is passed an external URL, rather than a URL
        # fragment, it will mark the branch as being stacked on the branch in
        # Launchpad registered with that external URL.
        stacked_branch = self.factory.makeAnyBranch()
        stacked_on_branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED)
        self.storage.setStackedOn(stacked_branch.id, stacked_on_branch.url)
        self.assertEqual(stacked_branch.stacked_on, stacked_on_branch)

    def test_setStackedOnExternalURLWithTrailingSlash(self):
        # If setStackedOn is passed an external URL with a trailing slash, it
        # won't make a big deal out of it, it will treat it like any other
        # URL.
        stacked_branch = self.factory.makeAnyBranch()
        stacked_on_branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED)
        url = stacked_on_branch.url + '/'
        self.storage.setStackedOn(stacked_branch.id, url)
        self.assertEqual(stacked_branch.stacked_on, stacked_on_branch)

    def test_setStackedOnNothing(self):
        # If setStackedOn is passed an empty string as a stacked-on location,
        # the branch is marked as not being stacked on any branch.
        stacked_on_branch = self.factory.makeAnyBranch()
        stacked_branch = self.factory.makeAnyBranch(
            stacked_on=stacked_on_branch)
        self.storage.setStackedOn(stacked_branch.id, '')
        self.assertIs(stacked_branch.stacked_on, None)

    def test_setStackedOnBranchNotFound(self):
        # If setStackedOn can't find a branch for the given location, it will
        # return a Fault.
        stacked_branch = self.factory.makeAnyBranch()
        url = self.factory.getUniqueURL()
        fault = self.storage.setStackedOn(stacked_branch.id, url)
        self.assertEqual(faults.NoSuchBranch(url), fault)

    def test_setStackedOnNoBranchWithID(self):
        # If setStackedOn is called for a branch that doesn't exist, it will
        # return a Fault.
        stacked_on_branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED)
        branch_id = self.getUnusedBranchID()
        fault = self.storage.setStackedOn(branch_id, stacked_on_branch.url)
        self.assertEqual(faults.NoBranchWithID(branch_id), fault)


class AcquireBranchToPullTestsViaEndpoint(TestCaseWithFactory,
                                          AcquireBranchToPullTests):
    """Tests for `acquireBranchToPull` method of `IBranchPuller`."""

    def setUp(self):
        super(AcquireBranchToPullTestsViaEndpoint, self).setUp()
        frontend = self.frontend()
        self.storage = frontend.getPullerEndpoint()
        self.factory = frontend.getLaunchpadObjectFactory()

    def assertNoBranchIsAquired(self, *branch_types):
        """See `AcquireBranchToPullTests`."""
        branch_types = tuple(branch_type.name for branch_type in branch_types)
        pull_info = self.storage.acquireBranchToPull(branch_types)
        self.assertEqual((), pull_info)

    def assertBranchIsAquired(self, branch, *branch_types):
        """See `AcquireBranchToPullTests`."""
        branch = removeSecurityProxy(branch)
        branch_types = tuple(branch_type.name for branch_type in branch_types)
        pull_info = self.storage.acquireBranchToPull(branch_types)
        default_branch = branch.target.default_stacked_on_branch
        if default_branch:
            default_branch_name = default_branch
        else:
            default_branch_name = ''
        self.assertEqual(
            pull_info,
            (branch.id, branch.getPullURL(), branch.unique_name,
             default_branch_name, branch.branch_type.name))
        self.assertIsNot(None, branch.last_mirror_attempt)
        self.assertIs(None, branch.next_mirror_time)

    def startMirroring(self, branch):
        """See `AcquireBranchToPullTests`."""
        self.storage.startMirroring(branch.id)

    def test_branch_type_returned_mirrored(self):
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.requestMirror()
        pull_info = self.storage.acquireBranchToPull(())
        _, _, _, _, branch_type = pull_info
        self.assertEqual('MIRRORED', branch_type)

    def test_branch_type_returned_import(self):
        branch = self.factory.makeAnyBranch(branch_type=BranchType.IMPORTED)
        branch.requestMirror()
        pull_info = self.storage.acquireBranchToPull(())
        _, _, _, _, branch_type = pull_info
        self.assertEqual('IMPORTED', branch_type)

    def test_default_stacked_on_branch_returned(self):
        branch = self.factory.makeProductBranch(
            branch_type=BranchType.MIRRORED)
        self.factory.enableDefaultStackingForProduct(branch.product)
        branch.requestMirror()
        pull_info = self.storage.acquireBranchToPull(())
        _, _, _, default_stacked_on_branch, _ = pull_info
        self.assertEqual(
            default_stacked_on_branch,
            '/' + branch.target.default_stacked_on_branch.unique_name)

    def test_private_default_stacked_not_returned_for_mirrored_branch(self):
        # We don't stack mirrored branches on a private default stacked on
        # branch.
        product = self.factory.makeProduct()
        default_branch = self.factory.makeProductBranch(
            product=product, private=True)
        self.factory.enableDefaultStackingForProduct(product, default_branch)
        mirrored_branch = self.factory.makeProductBranch(
            branch_type=BranchType.MIRRORED, product=product)
        mirrored_branch.requestMirror()
        pull_info = self.storage.acquireBranchToPull(())
        _, _, _, default_stacked_on_branch, _ = pull_info
        self.assertEqual(
            '', default_stacked_on_branch)

    def test_unknown_branch_type_name_raises(self):
        self.assertRaises(
            UnknownBranchTypeError, self.storage.acquireBranchToPull,
            ('NO_SUCH_TYPE',))


class BranchFileSystemTest(TestCaseWithFactory):
    """Tests for the implementation of `IBranchFileSystem`."""

    def setUp(self):
        super(BranchFileSystemTest, self).setUp()
        frontend = self.frontend()
        self.branchfs = frontend.getFilesystemEndpoint()
        self.factory = frontend.getLaunchpadObjectFactory()
        self.branch_lookup = frontend.getBranchLookup()

    def test_createBranch(self):
        # createBranch creates a branch with the supplied details and the
        # caller as registrant.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        branch_id = self.branchfs.createBranch(
            owner.id, escape('/~%s/%s/%s' % (owner.name, product.name, name)))
        login(ANONYMOUS)
        branch = self.branch_lookup.get(branch_id)
        self.assertEqual(owner, branch.owner)
        self.assertEqual(product, branch.product)
        self.assertEqual(name, branch.name)
        self.assertEqual(owner, branch.registrant)
        self.assertEqual(BranchType.HOSTED, branch.branch_type)

    def test_createBranch_no_preceding_slash(self):
        requester = self.factory.makePerson()
        path = escape(u'invalid')
        fault = self.branchfs.createBranch(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(faults.InvalidPath(path), fault)

    def test_createBranch_junk(self):
        # createBranch can create +junk branches.
        owner = self.factory.makePerson()
        name = self.factory.getUniqueString()
        branch_id = self.branchfs.createBranch(
            owner.id, escape('/~%s/%s/%s' % (owner.name, '+junk', name)))
        login(ANONYMOUS)
        branch = self.branch_lookup.get(branch_id)
        self.assertEqual(owner, branch.owner)
        self.assertEqual(None, branch.product)
        self.assertEqual(name, branch.name)
        self.assertEqual(owner, branch.registrant)
        self.assertEqual(BranchType.HOSTED, branch.branch_type)

    def test_createBranch_team_junk(self):
        # createBranch can create +junk branches on teams.
        registrant = self.factory.makePerson()
        team = self.factory.makeTeam(registrant)
        name = self.factory.getUniqueString()
        branch_id = self.branchfs.createBranch(
            registrant.id, escape('/~%s/+junk/%s' % (team.name, name)))
        login(ANONYMOUS)
        branch = self.branch_lookup.get(branch_id)
        self.assertEqual(team, branch.owner)
        self.assertEqual(None, branch.product)
        self.assertEqual(name, branch.name)
        self.assertEqual(registrant, branch.registrant)
        self.assertEqual(BranchType.HOSTED, branch.branch_type)

    def test_createBranch_bad_product(self):
        # Creating a branch for a non-existant product fails.
        owner = self.factory.makePerson()
        name = self.factory.getUniqueString()
        message = "Project 'no-such-product' does not exist."
        fault = self.branchfs.createBranch(
            owner.id, escape('/~%s/no-such-product/%s' % (owner.name, name)))
        self.assertEqual(faults.NotFound(message), fault)

    def test_createBranch_other_user(self):
        # Creating a branch under another user's directory fails.
        creator = self.factory.makePerson()
        other_person = self.factory.makePerson()
        product = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        message = ("%s cannot create branches owned by %s"
                   % (creator.displayname, other_person.displayname))
        fault = self.branchfs.createBranch(
            creator.id,
            escape('/~%s/%s/%s' % (other_person.name, product.name, name)))
        self.assertEqual(faults.PermissionDenied(message), fault)

    def test_createBranch_bad_name(self):
        # Creating a branch with an invalid name fails.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        invalid_name = 'invalid name!'
        message = ("Invalid branch name '%s'. %s"
                   % (invalid_name, BRANCH_NAME_VALIDATION_ERROR_MESSAGE))
        fault = self.branchfs.createBranch(
            owner.id, escape(
                '/~%s/%s/%s' % (owner.name, product.name, invalid_name)))
        self.assertEqual(faults.PermissionDenied(message), fault)

    def test_createBranch_unicode_name(self):
        # Creating a branch with an invalid name fails.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        invalid_name = u'invalid\N{LATIN SMALL LETTER E WITH ACUTE}'
        message = ("Invalid branch name '%s'. %s"
                   % (invalid_name.encode('utf-8'),
                      str(BRANCH_NAME_VALIDATION_ERROR_MESSAGE)))
        fault = self.branchfs.createBranch(
            owner.id, escape(
                '/~%s/%s/%s' % (owner.name, product.name, invalid_name)))
        self.assertEqual(
            faults.PermissionDenied(message), fault)

    def test_createBranch_bad_user(self):
        # Creating a branch under a non-existent user fails.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        message = "User/team 'no-one' does not exist."
        fault = self.branchfs.createBranch(
            owner.id, escape('/~no-one/%s/%s' % (product.name, name)))
        self.assertEqual(faults.NotFound(message), fault)

    def test_createBranch_bad_user_bad_product(self):
        # If both the user and the product are not found, then the missing
        # user "wins" the error reporting race (as the url reads
        # ~user/product/branch).
        owner = self.factory.makePerson()
        name = self.factory.getUniqueString()
        message = "User/team 'no-one' does not exist."
        fault = self.branchfs.createBranch(
            owner.id, escape('/~no-one/no-product/%s' % (name,)))
        self.assertEqual(faults.NotFound(message), fault)

    def test_createBranch_not_branch(self):
        # Trying to create a branch at a path that's not valid for branches
        # raises a PermissionDenied fault.
        owner = self.factory.makePerson()
        path = escape('/~%s' % owner.name)
        fault = self.branchfs.createBranch(owner.id, path)
        message = "Cannot create branch at '%s'" % path
        self.assertEqual(faults.PermissionDenied(message), fault)

    def test_createBranch_source_package(self):
        # createBranch can take the path to a source package branch and create
        # it with all the right attributes.
        owner = self.factory.makePerson()
        sourcepackage = self.factory.makeSourcePackage()
        branch_name = self.factory.getUniqueString()
        unique_name = '/~%s/%s/%s/%s/%s' % (
            owner.name,
            sourcepackage.distribution.name,
            sourcepackage.distroseries.name,
            sourcepackage.sourcepackagename.name,
            branch_name)
        branch_id = self.branchfs.createBranch(owner.id, escape(unique_name))
        login(ANONYMOUS)
        branch = self.branch_lookup.get(branch_id)
        self.assertEqual(owner, branch.owner)
        self.assertEqual(sourcepackage.distroseries, branch.distroseries)
        self.assertEqual(
            sourcepackage.sourcepackagename, branch.sourcepackagename)
        self.assertEqual(branch_name, branch.name)
        self.assertEqual(owner, branch.registrant)
        self.assertEqual(BranchType.HOSTED, branch.branch_type)

    def test_createBranch_invalid_distro(self):
        # If createBranch is called with the path to a non-existent distro, it
        # will return a Fault saying so in plain English.
        owner = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        sourcepackagename = self.factory.makeSourcePackageName()
        branch_name = self.factory.getUniqueString()
        unique_name = '/~%s/ningnangnong/%s/%s/%s' % (
            owner.name, distroseries.name, sourcepackagename.name,
            branch_name)
        fault = self.branchfs.createBranch(owner.id, escape(unique_name))
        message = "No such distribution: 'ningnangnong'."
        self.assertEqual(faults.NotFound(message), fault)

    def test_createBranch_invalid_distroseries(self):
        # If createBranch is called with the path to a non-existent
        # distroseries, it will return a Fault saying so.
        owner = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        sourcepackagename = self.factory.makeSourcePackageName()
        branch_name = self.factory.getUniqueString()
        unique_name = '/~%s/%s/ningnangnong/%s/%s' % (
            owner.name, distribution.name, sourcepackagename.name,
            branch_name)
        fault = self.branchfs.createBranch(owner.id, escape(unique_name))
        message = "No such distribution series: 'ningnangnong'."
        self.assertEqual(faults.NotFound(message), fault)

    def test_createBranch_invalid_sourcepackagename(self):
        # If createBranch is called with the path to an invalid source
        # package, it will return a Fault saying so.
        owner = self.factory.makePerson()
        distroseries = self.factory.makeDistroRelease()
        branch_name = self.factory.getUniqueString()
        unique_name = '/~%s/%s/%s/ningnangnong/%s' % (
            owner.name, distroseries.distribution.name, distroseries.name,
            branch_name)
        fault = self.branchfs.createBranch(owner.id, escape(unique_name))
        message = "No such source package: 'ningnangnong'."
        self.assertEqual(faults.NotFound(message), fault)

    def test_initialMirrorRequest(self):
        # The default 'next_mirror_time' for a newly created hosted branch
        # should be None.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)
        self.assertIs(None, branch.next_mirror_time)

    def test_requestMirror(self):
        # requestMirror should set the next_mirror_time field to be the
        # current time.
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)
        self.branchfs.requestMirror(requester.id, branch.id)
        self.assertSqlAttributeEqualsDate(
            branch, 'next_mirror_time', UTC_NOW)

    def test_requestMirror_private(self):
        # requestMirror can be used to request the mirror of a private branch.
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(owner=requester, private=True)
        branch = removeSecurityProxy(branch)
        self.branchfs.requestMirror(requester.id, branch.id)
        self.assertSqlAttributeEqualsDate(
            branch, 'next_mirror_time', UTC_NOW)

    def test_branchChanged_sets_last_mirrored_id(self):
        # branchChanged sets the last_mirrored_id attribute on the branch.
        revid = self.factory.getUniqueString()
        branch = self.factory.makeAnyBranch()
        self.branchfs.branchChanged(branch.id, '', revid)
        self.assertEqual(revid, branch.last_mirrored_id)

    def test_branchChanged_sets_stacked_on(self):
        # branchChanged sets the stacked_on attribute based on the unique_name
        # passed in.
        branch = self.factory.makeAnyBranch()
        stacked_on = self.factory.makeAnyBranch()
        self.branchfs.branchChanged(branch.id, stacked_on.unique_name, '')
        self.assertEqual(stacked_on, branch.stacked_on)

    def test_branchChanged_unsets_stacked_on(self):
        # branchChanged clears the stacked_on attribute on the branch if '' is
        # passed in as the stacked_on location.
        branch = self.factory.makeAnyBranch()
        removeSecurityProxy(branch).stacked_on = self.factory.makeAnyBranch()
        self.branchfs.branchChanged(branch.id, '', '')
        self.assertIs(None, branch.stacked_on)

    def test_branchChanged_sets_last_mirrored(self):
        # branchChanged sets the last_mirrored attribute on the branch to the
        # current time.
        branch = self.factory.makeAnyBranch()
        self.branchfs.branchChanged(branch.id, '', '')
        # We can't test "now" precisely, but lets check that last_mirrored was
        # set to _something_.
        self.assertIsNot(None, branch.last_mirrored)

    def test_branchChanged_records_bogus_stacked_on_url(self):
        # If a bogus location is passed in as the stacked_on parameter,
        # mirror_status_message is set to indicate the problem and stacked_on
        # set to None.
        branch = self.factory.makeAnyBranch()
        self.branchfs.branchChanged(branch.id, '~does/not/exist', '')
        self.assertIs(None, branch.stacked_on)
        self.assertTrue('~does/not/exist' in branch.mirror_status_message)

    def test_branchChanged_fault_on_unknown_id(self):
        # If the id passed in doesn't match an existing branch, the fault
        # "NoBranchWithID" is returned.
        unused_id = -1
        self.assertFaultEqual(
            faults.NoBranchWithID(unused_id),
            self.branchfs.branchChanged(unused_id, '', ''))

    def test_branchChanged_creates_scan_job(self):
        # branchChanged() creates a scan job for the branch.
        if not isinstance(self.frontend, LaunchpadDatabaseFrontend):
            return
        branch = self.factory.makeAnyBranch()
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))
        self.branchfs.branchChanged(branch.id, '', 'rev1')
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(1, len(jobs))

    def test_branchChanged_doesnt_create_scan_job_for_noop_change(self):
        # XXX Is this even the right thing to do?
        if not isinstance(self.frontend, LaunchpadDatabaseFrontend):
            return
        branch = self.factory.makeAnyBranch()
        removeSecurityProxy(branch).last_mirrored_id = 'rev1'
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))
        self.branchfs.branchChanged(branch.id, '', 'rev1')
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))

    def assertCannotTranslate(self, requester, path):
        """Assert that we cannot translate 'path'."""
        fault = self.branchfs.translatePath(requester.id, path)
        self.assertEqual(faults.PathTranslationError(path), fault)

    def assertNotFound(self, requester, path):
        """Assert that the given path cannot be found."""
        if requester not in [LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES]:
            requester = requester.id
        fault = self.branchfs.translatePath(requester, path)
        self.assertEqual(faults.PathTranslationError(path), fault)

    def assertPermissionDenied(self, requester, path):
        """Assert that looking at the given path gives permission denied."""
        if requester not in [LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES]:
            requester = requester.id
        fault = self.branchfs.translatePath(requester, path)
        self.assertEqual(faults.PermissionDenied(), fault)

    def _makeProductWithDevFocus(self, private=False):
        """Make a stacking-enabled product with a development focus.

        :param private: Whether the development focus branch should be
            private.
        :return: The new Product and the new Branch.
        """
        product = self.factory.makeProduct()
        branch = self.factory.makeProductBranch(private=private)
        self.factory.enableDefaultStackingForProduct(product, branch)
        target = IBranchTarget(removeSecurityProxy(product))
        self.assertEqual(target.default_stacked_on_branch, branch)
        return product, branch

    def test_translatePath_cannot_translate(self):
        # Sometimes translatePath will not know how to translate a path. When
        # this happens, it returns a Fault saying so, including the path it
        # couldn't translate.
        requester = self.factory.makePerson()
        path = escape(u'/untranslatable')
        self.assertCannotTranslate(requester, path)

    def test_translatePath_no_preceding_slash(self):
        requester = self.factory.makePerson()
        path = escape(u'invalid')
        fault = self.branchfs.translatePath(requester.id, path)
        self.assertEqual(faults.InvalidPath(path), fault)

    def test_translatePath_branch(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_branch_with_trailing_slash(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        path = escape(u'/%s/' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_path_in_branch(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        path = escape(u'/%s/child' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, 'child'),
            translation)

    def test_translatePath_nested_path_in_branch(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        path = escape(u'/%s/a/b' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, 'a/b'),
            translation)

    def test_translatePath_preserves_escaping(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        child_path = u'a@b'
        # This test is only meaningful if the path isn't the same when
        # escaped.
        self.assertNotEqual(escape(child_path), child_path.encode('utf-8'))
        path = escape(u'/%s/%s' % (branch.unique_name, child_path))
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT,
             {'id': branch.id, 'writable': False},
             escape(child_path)), translation)

    def test_translatePath_no_such_junk_branch(self):
        requester = self.factory.makePerson()
        path = '/~%s/+junk/.bzr/branch-format' % (requester.name,)
        self.assertNotFound(requester, path)

    def test_translatePath_branches_in_parent_dirs_not_found(self):
        requester = self.factory.makePerson()
        product = self.factory.makeProduct()
        path = '/~%s/%s/.bzr/branch-format' % (requester.name, product.name)
        self.assertNotFound(requester, path)

    def test_translatePath_no_such_branch(self):
        requester = self.factory.makePerson()
        product = self.factory.makeProduct()
        path = '/~%s/%s/no-such-branch' % (requester.name, product.name)
        self.assertNotFound(requester, path)

    def test_translatePath_no_such_branch_non_ascii(self):
        requester = self.factory.makePerson()
        product = self.factory.makeProduct()
        path = u'/~%s/%s/non-asci\N{LATIN SMALL LETTER I WITH DIAERESIS}' % (
            requester.name, product.name)
        self.assertNotFound(requester, escape(path))

    def test_translatePath_private_branch(self):
        requester = self.factory.makePerson()
        branch = removeSecurityProxy(
            self.factory.makeAnyBranch(
                branch_type=BranchType.HOSTED, private=True, owner=requester))
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': True}, ''),
            translation)

    def test_translatePath_cant_see_private_branch(self):
        requester = self.factory.makePerson()
        branch = removeSecurityProxy(self.factory.makeAnyBranch(private=True))
        path = escape(u'/%s' % branch.unique_name)
        self.assertPermissionDenied(requester, path)

    def test_translatePath_remote_branch(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(branch_type=BranchType.REMOTE)
        path = escape(u'/%s' % branch.unique_name)
        self.assertNotFound(requester, path)

    def test_translatePath_launchpad_services_private(self):
        branch = removeSecurityProxy(self.factory.makeAnyBranch(private=True))
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(LAUNCHPAD_SERVICES, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_anonymous_cant_see_private_branch(self):
        branch = removeSecurityProxy(self.factory.makeAnyBranch(private=True))
        path = escape(u'/%s' % branch.unique_name)
        self.assertPermissionDenied(LAUNCHPAD_ANONYMOUS, path)

    def test_translatePath_anonymous_public_branch(self):
        branch = self.factory.makeAnyBranch()
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(LAUNCHPAD_ANONYMOUS, path)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_owned(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.HOSTED, owner=requester)
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': True}, ''),
            translation)

    def test_translatePath_team_owned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(requester)
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.HOSTED, owner=team)
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': True}, ''),
            translation)

    def test_translatePath_team_unowned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(self.factory.makePerson())
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.HOSTED, owner=team)
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_owned_mirrored(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.MIRRORED, owner=requester)
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def test_translatePath_owned_imported(self):
        requester = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(
            branch_type=BranchType.IMPORTED, owner=requester)
        path = escape(u'/%s' % branch.unique_name)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertEqual(
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''),
            translation)

    def assertTranslationIsControlDirectory(self, translation,
                                            default_stacked_on,
                                            trailing_path):
        """Assert that 'translation' points to the right control transport."""
        unique_name = escape(u'/' + default_stacked_on)
        expected_translation = (
            CONTROL_TRANSPORT,
            {'default_stack_on': unique_name}, trailing_path)
        self.assertEqual(expected_translation, translation)

    def test_translatePath_control_directory(self):
        requester = self.factory.makePerson()
        product, branch = self._makeProductWithDevFocus()
        path = escape(u'/~%s/%s/.bzr' % (requester.name, product.name))
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertTranslationIsControlDirectory(
            translation,
            default_stacked_on=branch.unique_name,
            trailing_path='.bzr')

    def test_translatePath_control_directory_no_stacked_set(self):
        # When there's no default stacked-on branch set for the project, we
        # don't even bother translating control directory paths.
        requester = self.factory.makePerson()
        product = self.factory.makeProduct()
        path = escape(u'/~%s/%s/.bzr/' % (requester.name, product.name))
        self.assertNotFound(requester, path)

    def test_translatePath_control_directory_invisble_branch(self):
        requester = self.factory.makePerson()
        product, branch = self._makeProductWithDevFocus(private=True)
        path = escape(u'/~%s/%s/.bzr/' % (requester.name, product.name))
        self.assertNotFound(requester, path)

    def test_translatePath_control_directory_private_branch(self):
        product, branch = self._makeProductWithDevFocus(private=True)
        branch = removeSecurityProxy(branch)
        requester = branch.owner
        path = escape(u'/~%s/%s/.bzr/' % (requester.name, product.name))
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertTranslationIsControlDirectory(
            translation,
            default_stacked_on=branch.unique_name,
            trailing_path='.bzr')

    def test_translatePath_control_directory_other_owner(self):
        requester = self.factory.makePerson()
        product, branch = self._makeProductWithDevFocus()
        owner = self.factory.makePerson()
        path = escape(u'/~%s/%s/.bzr' % (owner.name, product.name))
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertTranslationIsControlDirectory(
            translation,
            default_stacked_on=branch.unique_name,
            trailing_path='.bzr')

    def test_translatePath_control_directory_package_no_focus(self):
        # If the package has no default stacked-on branch, then don't show the
        # control directory.
        requester = self.factory.makePerson()
        package = self.factory.makeSourcePackage()
        self.assertIs(None, IBranchTarget(package).default_stacked_on_branch)
        path = '/~%s/%s/.bzr/' % (requester.name, package.path)
        self.assertNotFound(requester, path)

    def test_translatePath_control_directory_package(self):
        # If the package has a default stacked-on branch, then show the
        # control directory.
        requester = self.factory.makePerson()
        package = self.factory.makeSourcePackage()
        branch = self.factory.makePackageBranch(sourcepackage=package)
        self.factory.enableDefaultStackingForPackage(package, branch)
        self.assertIsNot(
            None, IBranchTarget(package).default_stacked_on_branch)
        path = '/~%s/%s/.bzr/' % (requester.name, package.path)
        translation = self.branchfs.translatePath(requester.id, path)
        login(ANONYMOUS)
        self.assertTranslationIsControlDirectory(
            translation,
            default_stacked_on=branch.unique_name,
            trailing_path='.bzr')


class LaunchpadDatabaseFrontend:
    """A 'frontend' to Launchpad's branch services.

    A 'frontend' here means something that provides access to the various
    XML-RPC endpoints, object factories and 'database' methods needed to write
    unit tests for XML-RPC endpoints.

    All of these methods are gathered together in this class so that
    alternative implementations can be provided, see `InMemoryFrontend`.
    """

    def getFilesystemEndpoint(self):
        """Return the branch filesystem endpoint for testing."""
        return BranchFileSystem(None, None)

    def getPullerEndpoint(self):
        """Return the branch puller endpoint for testing."""
        return BranchPuller(None, None)

    def getLaunchpadObjectFactory(self):
        """Return the Launchpad object factory for testing.

        See `LaunchpadObjectFactory`.
        """
        return LaunchpadObjectFactory()

    def getBranchLookup(self):
        """Return an implementation of `IBranchLookup`.

        Tests should use this to get the branch set they need, rather than
        using 'getUtility(IBranchSet)'. This allows in-memory implementations
        to work correctly.
        """
        return getUtility(IBranchLookup)

    def getLastActivity(self, activity_name):
        """Get the last script activity with 'activity_name'."""
        return getUtility(IScriptActivitySet).getLastActivity(activity_name)


def test_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    puller_tests = unittest.TestSuite(
        [loader.loadTestsFromTestCase(BranchPullerTest),
         loader.loadTestsFromTestCase(AcquireBranchToPullTestsViaEndpoint),
         loader.loadTestsFromTestCase(BranchFileSystemTest),
         ])
    scenarios = [
        ('db', {'frontend': LaunchpadDatabaseFrontend,
                'layer': DatabaseFunctionalLayer}),
        ('inmemory', {'frontend': InMemoryFrontend,
                      'layer': FunctionalLayer}),
        ]
    multiply_tests(puller_tests, scenarios, suite)
    suite.addTests(loader.loadTestsFromTestCase(TestRunWithLogin))
    return suite
