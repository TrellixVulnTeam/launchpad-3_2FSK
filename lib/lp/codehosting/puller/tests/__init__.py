# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common code for the puller tests."""

__metaclass__ = type

import os
import shutil
from StringIO import StringIO

from bzrlib.tests import HttpServer, TestCaseWithTransport
from bzrlib import urlutils

from lp.codehosting.vfs import branch_id_to_path
from lp.codehosting.puller.worker import (
    BranchMirrorer, PullerWorker, PullerWorkerProtocol)
from lp.codehosting.tests.helpers import LoomTestMixin
from lp.codehosting.vfs.branchfs import BadUrl, BranchPolicy
from canonical.config import config
from lp.testing import TestCaseWithFactory


class BlacklistPolicy(BranchPolicy):
    """Branch policy that forbids certain URLs."""

    def __init__(self, should_follow_references, unsafe_urls=None):
        if unsafe_urls is None:
            unsafe_urls = set()
        self._unsafe_urls = unsafe_urls
        self._should_follow_references = should_follow_references

    def shouldFollowReferences(self):
        return self._should_follow_references

    def checkOneURL(self, url):
        if url in self._unsafe_urls:
            raise BadUrl(url)

    def transformFallbackLocation(self, branch, url):
        """See `BranchPolicy.transformFallbackLocation`.

        This class is not used for testing our smarter stacking features so we
        just do the simplest thing: return the URL that would be used anyway
        and don't check it.
        """
        return urlutils.join(branch.base, url), False


class AcceptAnythingPolicy(BlacklistPolicy):
    """Accept anything, to make testing easier."""

    def __init__(self):
        super(AcceptAnythingPolicy, self).__init__(True, set())


class WhitelistPolicy(BranchPolicy):
    """Branch policy that only allows certain URLs."""

    def __init__(self, should_follow_references, allowed_urls=None,
                 check=False):
        if allowed_urls is None:
            allowed_urls = []
        self.allowed_urls = set(url.rstrip('/') for url in allowed_urls)
        self.check = check

    def shouldFollowReferences(self):
        return self._should_follow_references

    def checkOneURL(self, url):
        if url.rstrip('/') not in self.allowed_urls:
            raise BadUrl(url)

    def transformFallbackLocation(self, branch, url):
        """See `BranchPolicy.transformFallbackLocation`.

        Here we return the URL that would be used anyway and optionally check
        it.
        """
        return urlutils.join(branch.base, url), self.check


class PullerWorkerMixin:
    """Mixin for tests that want to make PullerWorker objects.

    Assumes that it is mixed into a class that runs in a temporary directory,
    such as `TestCaseInTempDir` and that `get_transport` is provided as a
    method.
    """

    def makePullerWorker(self, src_dir=None, dest_dir=None, branch_type=None,
                         default_stacked_on_url=None, protocol=None,
                         oops_prefix=None, policy=None):
        """Anonymous creation method for PullerWorker."""
        if protocol is None:
            protocol = PullerWorkerProtocol(StringIO())
        if oops_prefix is None:
            oops_prefix = ''
        if branch_type is None:
            if policy is None:
                policy = AcceptAnythingPolicy()
            opener = BranchMirrorer(policy, protocol)
        else:
            opener = None
        return PullerWorker(
            src_dir, dest_dir, branch_id=1, unique_name='foo/bar/baz',
            branch_type=branch_type,
            default_stacked_on_url=default_stacked_on_url, protocol=protocol,
            branch_mirrorer=opener, oops_prefix=oops_prefix)


class PullerBranchTestCase(TestCaseWithTransport, TestCaseWithFactory,
                           LoomTestMixin):
    """Some useful code for the more-integration-y puller tests."""

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        TestCaseWithFactory.setUp(self)
        self.disable_directory_isolation()

    def getHostedPath(self, branch):
        """Return the path of 'branch' in the upload area."""
        return os.path.join(
            config.codehosting.hosted_branches_root,
            branch_id_to_path(branch.id))

    def getMirroredPath(self, branch):
        """Return the path of 'branch' in the supermirror area."""
        return os.path.join(
            config.codehosting.mirrored_branches_root,
            branch_id_to_path(branch.id))

    def makeCleanDirectory(self, path):
        """Guarantee an empty branch upload area."""
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path)
        self.addCleanup(shutil.rmtree, path)

    def pushToBranch(self, branch, tree):
        """Push a Bazaar branch to a given Launchpad branch's hosted area.

        Use this to test mirroring a hosted branch.

        :param branch: A Launchpad Branch object.
        """
        hosted_path = self.getHostedPath(branch)
        out, err = self.run_bzr(
            ['push', '--create-prefix', '-d',
             urlutils.local_path_from_url(tree.branch.base), hosted_path],
            retcode=None)
        # We want to be sure that a new branch was indeed created.
        self.assertEqual("Created new branch.\n", err)

    def serveOverHTTP(self):
        """Serve the current directory over HTTP, returning the server URL."""
        http_server = HttpServer()
        http_server.start_server()
        # Join cleanup added before the tearDown so the tearDown is executed
        # first as this tells the thread to die.  We then join explicitly as
        # the HttpServer.tearDown does not join.  There is a check in the
        # BaseLayer to make sure that threads are not left behind by the
        # tests, and the default behaviour of the HttpServer is to use daemon
        # threads and let the garbage collector get them, however this causes
        # issues with the test runner.
        self.addCleanup(http_server._http_thread.join)
        self.addCleanup(http_server.stop_server)
        return http_server.get_url().rstrip('/')
