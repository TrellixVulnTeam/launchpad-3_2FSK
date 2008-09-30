# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for bzrutils."""

__metaclass__ = type

import gc

from bzrlib.bzrdir import BzrDirFormat
from bzrlib import errors
from bzrlib.tests import (
    adapt_tests, default_transport, TestLoader, TestNotApplicable)
from bzrlib.tests.bzrdir_implementations import (
    BzrDirTestProviderAdapter, TestCaseWithBzrDir)
from bzrlib.transport.memory import MemoryServer

from canonical.codehosting.bzrutils import get_branch_stacked_on_url
from canonical.codehosting.tests.helpers import TestResultWrapper


class TestGetBranchStackedOnURL(TestCaseWithBzrDir):
    """Tests for get_branch_stacked_on_url()."""

    def __str__(self):
        """Return the test id so that Zope test output shows the format."""
        return self.id()

    def tearDown(self):
        # This makes sure the connections held by the branches opened in the
        # test are dropped, so the daemon threads serving those branches can
        # exit.
        gc.collect()
        TestCaseWithBzrDir.tearDown(self)

    def run(self, result=None):
        """Run the test, with the result wrapped so that it knows about skips.
        """
        if result is None:
            result = self.defaultTestResult()
        super(TestGetBranchStackedOnURL, self).run(TestResultWrapper(result))

    def testGetBranchStackedOnUrl(self):
        # get_branch_stacked_on_url returns the URL of the stacked-on branch.
        stacked_on_branch = self.make_branch('stacked-on')
        stacked_branch = self.make_branch('stacked')
        try:
            stacked_branch.set_stacked_on_url('../stacked-on')
        except errors.UnstackableBranchFormat:
            raise TestNotApplicable('This format does not support stacking.')
        # Deleting the stacked-on branch ensures that Bazaar will raise an
        # error if it tries to open the stacked-on branch.
        self.get_transport('.').delete_tree('stacked-on')
        self.assertEqual(
            '../stacked-on',
            get_branch_stacked_on_url(stacked_branch.bzrdir))

    def testGetBranchStackedOnUrlUnstackable(self):
        # get_branch_stacked_on_url raises UnstackableBranchFormat if it's
        # called on the bzrdir of a branch that cannot be stacked.
        branch = self.make_branch('source')
        try:
            branch.get_stacked_on_url()
        except errors.NotStacked:
            raise TestNotApplicable('This format supports stacked branches.')
        except errors.UnstackableBranchFormat:
            pass
        self.assertRaises(
            errors.UnstackableBranchFormat,
            get_branch_stacked_on_url, branch.bzrdir)

    def testGetBranchStackedOnUrlNotStacked(self):
        # get_branch_stacked_on_url raises NotStacked if it's called on the
        # bzrdir of a non-stacked branch.
        branch = self.make_branch('source')
        try:
            branch.get_stacked_on_url()
        except errors.NotStacked:
            pass
        except errors.UnstackableBranchFormat:
            raise TestNotApplicable(
                'This format does not support stacked branches')
        self.assertRaises(
            errors.NotStacked, get_branch_stacked_on_url, branch.bzrdir)

    def testGetBranchStackedOnUrlNoBranch(self):
        # get_branch_stacked_on_url raises a NotBranchError if it's called on
        # a bzrdir that's not got a branch.
        a_bzrdir = self.make_bzrdir('source')
        if a_bzrdir.has_branch():
            raise TestNotApplicable(
                'This format does not support branchless bzrdirs.')
        self.assertRaises(
            errors.NotBranchError, get_branch_stacked_on_url, a_bzrdir)


def load_tests(basic_tests, module, loader):
    """Parametrize the tests by BzrDir.

    This is mostly copy-and-pasted from
    bzrlib/tests/bzrdir_implementations/__init__.py.
    """
    result = loader.suiteClass()

    # Add a format that supports stacking.
    from bzrlib.bzrdir import BzrDirMetaFormat1
    from bzrlib.branch import BzrBranchFormat7
    from bzrlib.repofmt.pack_repo import RepositoryFormatKnitPack5
    stacking_format = BzrDirMetaFormat1()
    stacking_format.set_branch_format(BzrBranchFormat7())
    stacking_format.repository_format = RepositoryFormatKnitPack5()
    BzrDirFormat.register_format(stacking_format)

    formats = BzrDirFormat.known_formats()
    adapter = BzrDirTestProviderAdapter(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats)
    # add the tests for the sub modules
    adapt_tests(basic_tests, adapter, result)

    # This will always add the tests for smart server transport, regardless of
    # the --transport option the user specified to 'bzr selftest'.
    from bzrlib.smart.server import (
        ReadonlySmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing_v2_only,
        SmartTCPServer_for_testing,
        SmartTCPServer_for_testing_v2_only,
        )
    from bzrlib.remote import RemoteBzrDirFormat

    # test the remote server behaviour using a MemoryTransport
    smart_server_suite = loader.suiteClass()
    adapt_to_smart_server = BzrDirTestProviderAdapter(
        MemoryServer,
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBzrDirFormat())],
        name_suffix='-default')
    adapt_tests(basic_tests, adapt_to_smart_server, smart_server_suite)
    adapt_to_smart_server = BzrDirTestProviderAdapter(
        MemoryServer,
        SmartTCPServer_for_testing_v2_only,
        ReadonlySmartTCPServer_for_testing_v2_only,
        [(RemoteBzrDirFormat())],
        name_suffix='-v2')
    adapt_tests(basic_tests, adapt_to_smart_server, smart_server_suite)
    result.addTests(smart_server_suite)
    return result


def test_suite():
    loader = TestLoader()
    return loader.loadTestsFromName(__name__)
