# Copyright 2006-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0231

"""Unit tests for worker.py."""

__metaclass__ = type

from StringIO import StringIO
import unittest

import bzrlib.branch
from bzrlib.branch import BranchReferenceFormat, BzrBranchFormat7
from bzrlib.bzrdir import BzrDir, BzrDirMetaFormat1
from bzrlib.errors import NotBranchError
from bzrlib.remote import RemoteBranch
from bzrlib.repofmt.pack_repo import RepositoryFormatKnitPack1
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import server
from bzrlib.tests import TestCaseInTempDir, TestCaseWithTransport
from bzrlib.transport import get_transport

from canonical.codehosting.bzrutils import ensure_base
from canonical.codehosting.puller.worker import (
    BadUrl, BadUrlLaunchpad, BadUrlScheme, BadUrlSsh, BranchOpener,
    BranchReferenceForbidden, BranchReferenceLoopError, HostedBranchOpener,
    ImportedBranchOpener, MirroredBranchOpener, PullerWorkerProtocol,
    StackingLoopError, get_vfs_format_classes, install_worker_ui_factory,
    StackedOnBranchNotFound)
from canonical.codehosting.puller.tests import PullerWorkerMixin
from canonical.launchpad.interfaces.branch import BranchType
from canonical.launchpad.testing import LaunchpadObjectFactory, TestCase
from canonical.testing import reset_logging


def get_netstrings(line):
    """Parse `line` as a sequence of netstrings.

    :return: A list of strings.
    """
    strings = []
    while len(line) > 0:
        colon_index = line.find(':')
        length = int(line[:colon_index])
        strings.append(line[colon_index+1:colon_index+1+length])
        assert ',' == line[colon_index+1+length], (
            'Expected %r == %r' % (',', line[colon_index+1+length]))
        line = line[colon_index+length+2:]
    return strings


class TestGetVfsFormatClasses(TestCaseWithTransport):
    """Tests for `canonical.codehosting.puller.worker.get_vfs_format_classes`.
    """

    def tearDown(self):
        # This makes sure the connections held by the branches opened in the
        # test are dropped, so the daemon threads serving those branches can
        # exit.
        import gc
        gc.collect()
        super(TestGetVfsFormatClasses, self).tearDown()

    def test_get_vfs_format_classes(self):
        # get_vfs_format_classes for a returns the underlying format classes
        # of the branch, repo and bzrdir, even if the branch is a
        # RemoteBranch.
        self.transport_server = server.SmartTCPServer_for_testing
        vfs_branch = self.make_branch('.')
        remote_branch = bzrlib.branch.Branch.open(self.get_url('.'))
        # Check that our set up worked: remote_branch is Remote and
        # source_branch is not.
        self.assertIsInstance(remote_branch, RemoteBranch)
        self.failIf(isinstance(vfs_branch, RemoteBranch))
        # Now, get_vfs_format_classes on both branches returns the same format
        # information.
        self.assertEqual(
            get_vfs_format_classes(vfs_branch),
            get_vfs_format_classes(remote_branch))


class TestPullerWorker(TestCaseWithTransport, PullerWorkerMixin):
    """Test the mirroring functionality of PullerWorker."""

    def testMirredOpener(self):
        # A PullerWorker for a mirrored branch gets a MirroredBranchOpener as
        # its branch_opener.
        worker = self.makePullerWorker(branch_type=BranchType.MIRRORED)
        self.assertIsInstance(worker.branch_opener, MirroredBranchOpener)

    def testHostedOpener(self):
        # A PullerWorker for a hosted branch gets a HostedBranchOpener as
        # its branch_opener.
        worker = self.makePullerWorker(branch_type=BranchType.HOSTED)
        self.assertIsInstance(worker.branch_opener, HostedBranchOpener)

    def testImportedOpener(self):
        # A PullerWorker for an imported branch gets a ImportedBranchOpener as
        # its branch_opener.
        worker = self.makePullerWorker(branch_type=BranchType.IMPORTED)
        self.assertIsInstance(worker.branch_opener, ImportedBranchOpener)

    def testMirrorActuallyMirrors(self):
        # Check that mirror() will mirror the Bazaar branch.
        source_tree = self.make_branch_and_tree('source-branch')
        to_mirror = self.makePullerWorker(
            source_tree.branch.base, self.get_url('dest'))
        source_tree.commit('commit message')
        to_mirror.mirrorWithoutChecks()
        mirrored_branch = bzrlib.branch.Branch.open(to_mirror.dest)
        self.assertEqual(
            source_tree.last_revision(), mirrored_branch.last_revision())

    def testMirrorEmptyBranch(self):
        # We can mirror an empty branch.
        source_branch = self.make_branch('source-branch')
        to_mirror = self.makePullerWorker(
            source_branch.base, self.get_url('dest'))
        to_mirror.mirrorWithoutChecks()
        mirrored_branch = bzrlib.branch.Branch.open(to_mirror.dest)
        self.assertEqual(NULL_REVISION, mirrored_branch.last_revision())

    def testCanMirrorWhenDestDirExists(self):
        # We can mirror a branch even if the destination exists, and contains
        # data but is not a branch.
        source_tree = self.make_branch_and_tree('source-branch')
        to_mirror = self.makePullerWorker(
            source_tree.branch.base, self.get_url('destdir'))
        source_tree.commit('commit message')
        # Make the directory.
        dest = get_transport(to_mirror.dest)
        ensure_base(dest)
        dest.mkdir('.bzr')
        # 'dest' is not a branch.
        self.assertRaises(
            NotBranchError, bzrlib.branch.Branch.open, to_mirror.dest)
        to_mirror.mirrorWithoutChecks()
        mirrored_branch = bzrlib.branch.Branch.open(to_mirror.dest)
        self.assertEqual(
            source_tree.last_revision(), mirrored_branch.last_revision())

    def testHttpTransportStillThere(self):
        # We tweak the http:// transport in the worker. Make sure that it's
        # still available after mirroring.
        http = get_transport('http://example.com')
        source_branch = self.make_branch('source-branch')
        to_mirror = self.makePullerWorker(
            source_branch.base, self.get_url('destdir'))
        to_mirror.mirrorWithoutChecks()
        new_http = get_transport('http://example.com')
        self.assertEqual(get_transport('http://example.com').base, http.base)
        self.assertEqual(new_http.__class__, http.__class__)

    def testRaisesStackedOnBranchNotFoundInitialMirror(self):
        # If the stacked-on branch cannot be found in the mirrored area on an
        # initial mirror, then raise StackedOnBranchNotFound. This will ensure
        # the puller will mirror the stacked branch as soon as the stacked-on
        # branch has been mirrored.
        stacked_on_branch = self.make_branch(
            'stacked-on-branch', format='1.6')
        stacked_branch = self.make_branch('source-branch', format='1.6')
        stacked_branch.set_stacked_on_url('../stacked-on-branch')
        # Make a sub-directory so that the relative URL cannot be found.
        self.get_transport('mirrored-area').ensure_base()
        # Make an empty directory with the same name as the stacked-on branch
        # to show that we are checking for more than just directory existence.
        # See bug 270757.
        self.get_transport('mirrored-area/stacked-on-branch').ensure_base()
        to_mirror = self.makePullerWorker(
            stacked_branch.base, self.get_url('mirrored-area/destdir'))
        self.assertRaises(
            StackedOnBranchNotFound, to_mirror.mirrorWithoutChecks)

    def testRaisesStackedOnBranchNotFoundRemirror(self):
        # If the stacked-on branch cannot be found in the mirrored area on an
        # update, then raise StackedOnBranchNotFound. This will ensure the
        # puller will mirror the stacked branch as soon as the stacked-on
        # branch has been mirrored.
        stacked_branch = self.make_branch('source-branch', format='1.6')
        # Make a sub-directory so that the relative URL cannot be found.
        self.get_transport('mirrored-area').ensure_base()
        # Make an empty directory with the same name as the stacked-on branch
        # to show that we are checking for more than just directory existence.
        # See bug 270757.
        self.get_transport('mirrored-area/stacked-on-branch').ensure_base()
        to_mirror = self.makePullerWorker(
            stacked_branch.base, self.get_url('mirrored-area/destdir'))
        to_mirror.mirrorWithoutChecks()
        stacked_on_branch = self.make_branch(
            'stacked-on-branch', format='1.6')
        stacked_branch.set_stacked_on_url('../stacked-on-branch')
        self.assertRaises(
            StackedOnBranchNotFound, to_mirror.mirrorWithoutChecks)

    def testDoesntSendStackedInfoUnstackableFormat(self):
        # Mirroring an unstackable branch doesn't send the stacked-on location
        # to the master.
        source_branch = self.make_branch('source-branch')
        protocol_output = StringIO()
        to_mirror = self.makePullerWorker(
            source_branch.base, self.get_url('destdir'),
            protocol=PullerWorkerProtocol(protocol_output))
        to_mirror.mirrorWithoutChecks()
        self.assertEqual([], get_netstrings(protocol_output.getvalue()))

    def testDoesntSendStackedInfoNotStacked(self):
        # Mirroring a non-stacked branch doesn't send the stacked-on location
        # to the master.
        source_branch = self.make_branch(
            'source-branch', format='development')
        protocol_output = StringIO()
        to_mirror = self.makePullerWorker(
            source_branch.base, self.get_url('destdir'),
            protocol=PullerWorkerProtocol(protocol_output))
        to_mirror.mirrorWithoutChecks()
        self.assertEqual([], get_netstrings(protocol_output.getvalue()))

    def testSendsStackedInfo(self):
        # Mirroring a non-stacked branch doesn't send the stacked-on location
        # to the master.
        base_branch = self.make_branch('base_branch', format='development')
        stacked_branch = self.make_branch(
            'stacked-branch', format='development')
        stacked_branch.set_stacked_on_url(base_branch.base)
        protocol_output = StringIO()
        to_mirror = self.makePullerWorker(
            stacked_branch.base, self.get_url('destdir'),
            protocol=PullerWorkerProtocol(protocol_output))
        to_mirror.mirrorWithoutChecks()
        self.assertEqual(
            ['setStackedOn', str(to_mirror.branch_id),
             stacked_branch.get_stacked_on_url()],
            get_netstrings(protocol_output.getvalue()))


class TestBranchOpenerCheckSource(TestCase):
    """Unit tests for `BranchOpener.checkSource`."""

    class StubbedBranchOpener(BranchOpener):
        """BranchOpener that provides canned answers.

        We implement the methods we need to to be able to control all the
        inputs to the `BranchOpener.checkSource` method, which is what is
        being tested in this class.
        """

        def __init__(self, should_follow_references, references,
                     unsafe_urls=None):
            self._should_follow_references = should_follow_references
            self._reference_values = {}
            for i in range(len(references) - 1):
                self._reference_values[references[i]] = references[i+1]
            if unsafe_urls is None:
                unsafe_urls = set()
            self.unsafe_urls = unsafe_urls
            self.follow_reference_calls = []
            self.check_one_url_calls = []

        def followReference(self, url):
            self.follow_reference_calls.append(url)
            return self._reference_values[url]

        def shouldFollowReferences(self):
            return self._should_follow_references

        def checkOneURL(self, url):
            self.check_one_url_calls.append(url)
            if url in self.unsafe_urls:
                raise BadUrl(url)

    def testCheckInitialURL(self):
        # checkSource rejects all URLs that are not allowed.
        opener = self.StubbedBranchOpener(None, [], set(['a']))
        self.assertRaises(BadUrl, opener.checkSource, 'a')

    def testNotReference(self):
        # When branch references are forbidden, checkSource does not raise on
        # non-references.
        opener = self.StubbedBranchOpener(False, ['a', None])
        # This raises a NotBranchError since it passes the checks and tries to
        # open 'a'.
        self.assertRaises(NotBranchError, opener.checkSource, 'a')
        self.assertEquals(['a'], opener.follow_reference_calls)

    def testBranchReferenceForbidden(self):
        # checkSource raises BranchReferenceForbidden if branch references are
        # forbidden and the source URL points to a branch reference.
        opener = self.StubbedBranchOpener(False, ['a', 'b'])
        self.assertRaises(
            BranchReferenceForbidden, opener.checkSource, 'a')
        self.assertEquals(['a'], opener.follow_reference_calls)

    def testAllowedReference(self):
        # checkSource does not raise if following references is allowed and
        # the source URL points to a branch reference to a permitted location.
        opener = self.StubbedBranchOpener(True, ['a', 'b', None])
        # This raises a NotBranchError since it passes the checks and tries to
        # open 'a'.
        self.assertRaises(NotBranchError, opener.checkSource, 'a')
        self.assertEquals(['a', 'b'], opener.follow_reference_calls)

    def testCheckReferencedURLs(self):
        # checkSource checks if the URL a reference points to is safe.
        opener = self.StubbedBranchOpener(
            True, ['a', 'b', None], unsafe_urls=set('b'))
        self.assertRaises(BadUrl, opener.checkSource, 'a')
        self.assertEquals(['a'], opener.follow_reference_calls)

    def testSelfReferencingBranch(self):
        # checkSource raises BranchReferenceLoopError if following references
        # is allowed and the source url points to a self-referencing branch
        # reference.
        opener = self.StubbedBranchOpener(True, ['a', 'a'])
        self.assertRaises(
            BranchReferenceLoopError, opener.checkSource, 'a')
        self.assertEquals(['a'], opener.follow_reference_calls)

    def testBranchReferenceLoop(self):
        # checkSource raises BranchReferenceLoopError if following references
        # is allowed and the source url points to a loop of branch references.
        references = ['a', 'b', 'a']
        opener = self.StubbedBranchOpener(True, references)
        self.assertRaises(
            BranchReferenceLoopError, opener.checkSource, 'a')
        self.assertEquals(['a', 'b'], opener.follow_reference_calls)


class TestBranchOpenerStacking(TestCaseWithTransport):

    def makeBranchOpener(self, allowed_urls):
        allowed_urls = [url.rstrip('/') for url in allowed_urls]
        opener = BranchOpener()
        def checkOneURL(url):
            if url.rstrip('/') not in allowed_urls:
                raise BadUrl(url)
        opener.checkOneURL = checkOneURL
        return opener

    def makeBranch(self, path, branch_format, repository_format):
        """Make a Bazaar branch at 'path' with the given formats."""
        bzrdir_format = BzrDirMetaFormat1()
        bzrdir_format.set_branch_format(branch_format)
        bzrdir = self.make_bzrdir(path, format=bzrdir_format)
        repository_format.initialize(bzrdir)
        return bzrdir.create_branch()

    def testAllowedURL(self):
        # checkSource does not raise an exception for branches stacked on
        # branches with allowed URLs.
        stacked_on_branch = self.make_branch('base-branch', format='1.6')
        stacked_branch = self.make_branch('stacked-branch', format='1.6')
        stacked_branch.set_stacked_on_url(stacked_on_branch.base)
        opener = self.makeBranchOpener(
            [stacked_branch.base, stacked_on_branch.base])
        # This doesn't raise an exception.
        opener.checkSource(stacked_branch.base)

    def testUnstackableRepository(self):
        # checkSource treats branches with UnstackableRepositoryFormats as
        # being not stacked.
        branch = self.makeBranch(
            'unstacked', BzrBranchFormat7(), RepositoryFormatKnitPack1())
        opener = self.makeBranchOpener([branch.base])
        # This doesn't raise an exception.
        opener.checkSource(branch.base)

    def testAllowedRelativeURL(self):
        # checkSource passes on absolute urls to checkOneURL, even if the
        # value of stacked_on_location in the config is set to a relative URL.
        stacked_on_branch = self.make_branch('base-branch', format='1.6')
        stacked_branch = self.make_branch('stacked-branch', format='1.6')
        stacked_branch.set_stacked_on_url('../base-branch')
        opener = self.makeBranchOpener(
            [stacked_branch.base, stacked_on_branch.base])
        # Note that stacked_on_branch.base is not '../base-branch', it's an
        # absolute URL.
        self.assertNotEqual('../base-branch', stacked_on_branch.base)
        # This doesn't raise an exception.
        opener.checkSource(stacked_branch.base)

    def testAllowedRelativeNested(self):
        # Relative URLs are resolved relative to the stacked branch.
        self.get_transport().mkdir('subdir')
        a = self.make_branch('subdir/a', format='1.6')
        b = self.make_branch('b', format='1.6')
        b.set_stacked_on_url('../subdir/a')
        c = self.make_branch('subdir/c', format='1.6')
        c.set_stacked_on_url('../../b')
        opener = self.makeBranchOpener([c.base, b.base, a.base])
        # This doesn't raise an exception.
        opener.checkSource(c.base)

    def testForbiddenURL(self):
        # checkSource raises a BadUrl exception if a branch is stacked on a
        # branch with a forbidden URL.
        stacked_on_branch = self.make_branch('base-branch', format='1.6')
        stacked_branch = self.make_branch('stacked-branch', format='1.6')
        stacked_branch.set_stacked_on_url(stacked_on_branch.base)
        opener = self.makeBranchOpener([stacked_branch.base])
        self.assertRaises(BadUrl, opener.checkSource, stacked_branch.base)

    def testForbiddenURLNested(self):
        # checkSource raises a BadUrl exception if a branch is stacked on a
        # branch that is in turn stacked on a branch with a forbidden URL.
        a = self.make_branch('a', format='1.6')
        b = self.make_branch('b', format='1.6')
        b.set_stacked_on_url(a.base)
        c = self.make_branch('c', format='1.6')
        c.set_stacked_on_url(b.base)
        opener = self.makeBranchOpener([c.base, b.base])
        self.assertRaises(BadUrl, opener.checkSource, c.base)

    def testSelfStackedBranch(self):
        # checkSource raises StackingLoopError if a branch is stacked on
        # itself. This avoids infinite recursion errors.
        a = self.make_branch('a', format='1.6')
        a.set_stacked_on_url(a.base)
        opener = self.makeBranchOpener([a.base])
        self.assertRaises(StackingLoopError, opener.checkSource, a.base)

    def testLoopStackedBranch(self):
        # checkSource raises StackingLoopError if a branch is stacked in such
        # a way so that it is ultimately stacked on itself. e.g. a stacked on
        # b stacked on a.
        a = self.make_branch('a', format='1.6')
        b = self.make_branch('b', format='1.6')
        a.set_stacked_on_url(b.base)
        b.set_stacked_on_url(a.base)
        opener = self.makeBranchOpener([a.base, b.base])
        self.assertRaises(StackingLoopError, opener.checkSource, a.base)
        self.assertRaises(StackingLoopError, opener.checkSource, b.base)


class TestReferenceMirroring(TestCaseWithTransport):
    """Feature tests for mirroring of branch references."""

    def createBranchReference(self, url):
        """Create a pure branch reference that points to the specified URL.

        :param url: target of the branch reference.
        :return: file url to the created pure branch reference.
        """
        # XXX DavidAllouche 2007-09-12 bug=139109:
        # We do this manually because the bzrlib API does not support creating
        # a branch reference without opening it.
        t = get_transport(self.get_url('.'))
        t.mkdir('reference')
        a_bzrdir = BzrDir.create(self.get_url('reference'))
        branch_reference_format = BranchReferenceFormat()
        branch_transport = a_bzrdir.get_branch_transport(
            branch_reference_format)
        branch_transport.put_bytes('location', url)
        branch_transport.put_bytes(
            'format', branch_reference_format.get_format_string())
        return a_bzrdir.root_transport.base

    def testCreateBranchReference(self):
        # createBranchReference creates a branch reference and returns a URL
        # that points to that branch reference.

        # First create a branch and a reference to that branch.
        target_branch = self.make_branch('repo')
        reference_url = self.createBranchReference(target_branch.base)

        # References are transparent, so we can't test much about them. The
        # least we can do is confirm that the reference URL isn't the branch
        # URL.
        self.assertNotEqual(reference_url, target_branch.base)

        # Open the branch reference and check that the result is indeed the
        # branch we wanted it to point at.
        opened_branch = bzrlib.branch.Branch.open(reference_url)
        self.assertEqual(opened_branch.base, target_branch.base)

    def testFollowReferenceValue(self):
        # BranchOpener.followReference gives the reference value for
        # a branch reference.
        opener = BranchOpener()
        reference_value = 'http://example.com/branch'
        reference_url = self.createBranchReference(reference_value)
        self.assertEqual(
            reference_value, opener.followReference(reference_url))

    def testFollowReferenceNone(self):
        # BranchOpener.followReference gives None for a normal branch.
        self.make_branch('repo')
        branch_url = self.get_url('repo')
        opener = BranchOpener()
        self.assertIs(None, opener.followReference(branch_url))


class TestMirroredBranchOpener(TestCase):
    """Tests specific to `MirroredBranchOpener`."""

    def setUp(self):
        self.factory = LaunchpadObjectFactory()

    def testNoFileURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlScheme, opener.checkOneURL,
            self.factory.getUniqueURL(scheme='file'))

    def testNoUnknownSchemeURLs(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlScheme, opener.checkOneURL,
            self.factory.getUniqueURL(scheme='decorator+scheme'))

    def testNoSSHURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlSsh, opener.checkOneURL,
            self.factory.getUniqueURL(scheme='bzr+ssh'))

    def testNoSftpURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlSsh, opener.checkOneURL,
            self.factory.getUniqueURL(scheme='sftp'))

    def testNoLaunchpadURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlLaunchpad, opener.checkOneURL,
            self.factory.getUniqueURL(host='bazaar.launchpad.dev'))

    def testNoHTTPSLaunchpadURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlLaunchpad, opener.checkOneURL,
            self.factory.getUniqueURL(
                host='bazaar.launchpad.dev', scheme='https'))

    def testNoOtherHostLaunchpadURL(self):
        opener = MirroredBranchOpener()
        self.assertRaises(
            BadUrlLaunchpad, opener.checkOneURL,
            self.factory.getUniqueURL(host='code.launchpad.dev'))

    def testLocalhost(self):
        self.pushConfig(
            'codehosting', blacklisted_hostnames='localhost,127.0.0.1')
        opener = MirroredBranchOpener()
        localhost_url = self.factory.getUniqueURL(host='localhost')
        self.assertRaises(BadUrl, opener.checkOneURL, localhost_url)
        localhost_url = self.factory.getUniqueURL(host='127.0.0.1')
        self.assertRaises(BadUrl, opener.checkOneURL, localhost_url)


class TestWorkerProtocol(TestCaseInTempDir, PullerWorkerMixin):
    """Tests for the client-side implementation of the protocol used to
    communicate to the master process.
    """

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.output = StringIO()
        self.protocol = PullerWorkerProtocol(self.output)

    def assertSentNetstrings(self, expected_netstrings):
        """Assert that the protocol sent the given netstrings (in order)."""
        observed_netstrings = get_netstrings(self.output.getvalue())
        self.assertEqual(expected_netstrings, observed_netstrings)

    def resetBuffers(self):
        # Empty the test output and error buffers.
        self.output.truncate(0)
        self.assertEqual('', self.output.getvalue())

    def test_nothingSentOnConstruction(self):
        # The protocol sends nothing until it receives an event.
        self.branch_to_mirror = self.makePullerWorker(protocol=self.protocol)
        self.assertSentNetstrings([])

    def test_startMirror(self):
        # Calling startMirroring sends 'startMirroring' as a netstring.
        self.protocol.startMirroring()
        self.assertSentNetstrings(['startMirroring', '0'])

    def test_mirrorSucceeded(self):
        # Calling 'mirrorSucceeded' sends the revno and 'mirrorSucceeded'.
        self.protocol.startMirroring()
        self.resetBuffers()
        self.protocol.mirrorSucceeded(1234)
        self.assertSentNetstrings(['mirrorSucceeded', '1', '1234'])

    def test_mirrorFailed(self):
        # Calling 'mirrorFailed' sends the error message.
        self.protocol.startMirroring()
        self.resetBuffers()
        self.protocol.mirrorFailed('Error Message', 'OOPS')
        self.assertSentNetstrings(
            ['mirrorFailed', '2', 'Error Message', 'OOPS'])

    def test_progressMade(self):
        # Calling 'progressMade' sends an arbitrary string indicating
        # progress.
        self.protocol.progressMade()
        self.assertSentNetstrings(['progressMade', '0'])

    def test_setStackedOn(self):
        # Calling 'setStackedOn' sends the location of the stacked-on branch,
        # if any.
        self.protocol.setStackedOn('/~foo/bar/baz')
        self.assertSentNetstrings(['setStackedOn', '1', '/~foo/bar/baz'])

    def test_mirrorDeferred(self):
        # Calling 'mirrorDeferred' sends 'mirrorDeferred' as a netstring.
        self.protocol.mirrorDeferred()
        self.assertSentNetstrings(['mirrorDeferred', '0'])


class TestWorkerProgressReporting(TestCaseWithTransport):
    """Tests for the WorkerProgressBar progress reporting mechanism."""

    class StubProtocol:
        """A stub for PullerWorkerProtocol that just defines progressMade."""
        def __init__(self):
            self.call_count = 0
        def progressMade(self):
            self.call_count += 1

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.saved_factory = bzrlib.ui.ui_factory

    def tearDown(self):
        TestCaseWithTransport.tearDown(self)
        bzrlib.ui.ui_factory = self.saved_factory
        reset_logging()

    def test_simple(self):
        # Even the simplest of pulls should call progressMade at least once.
        p = self.StubProtocol()
        install_worker_ui_factory(p)
        b1 = self.make_branch('some-branch')
        b2_tree = self.make_branch_and_tree('some-other-branch')
        b2 = b2_tree.branch
        b2_tree.commit('rev1', allow_pointless=True)
        b1.pull(b2)
        self.assertPositive(p.call_count)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
