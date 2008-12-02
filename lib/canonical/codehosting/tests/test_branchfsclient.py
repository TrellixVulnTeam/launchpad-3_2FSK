# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for branchfsclient."""

__metaclass__ = type

import unittest

from twisted.python.failure import Failure
from twisted.trial.unittest import TestCase
from twisted.web.xmlrpc import Fault

from canonical.codehosting.branchfsclient import (
    BranchFileSystemClient, NotInCache, trap_fault)
from canonical.codehosting.inmemory import InMemoryFrontend, XMLRPCWrapper
from canonical.launchpad.interfaces.codehosting import BRANCH_TRANSPORT


class TestBranchFileSystemClient(TestCase):
    """Tests for `BranchFileSystemClient`."""

    def setUp(self):
        frontend = InMemoryFrontend()
        self.factory = frontend.getLaunchpadObjectFactory()
        self.user = self.factory.makePerson()
        self._xmlrpc_client = XMLRPCWrapper(frontend.getFilesystemEndpoint())
        self.client = BranchFileSystemClient(
            self._xmlrpc_client, self.user.id)

    def test_translatePath(self):
        branch = self.factory.makeBranch()
        deferred = self.client.translatePath('/' + branch.unique_name)
        deferred.addCallback(
            self.assertEqual,
            (BRANCH_TRANSPORT, dict(id=branch.id, writable=False), ''))
        return deferred

    def test_get_matched_part(self):
        # We cache results based on the part of the URL that the server
        # matched. _getMatchedPart returns that part, based on the path given
        # and the returned data.
        branch = self.factory.makeBranch()
        requested_path = '/%s/a/b' % branch.unique_name
        matched_part = self.client._getMatchedPart(
            requested_path,
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, 'a/b'))
        self.assertEqual('/%s' % branch.unique_name, matched_part)

    def test_get_matched_part_no_trailing_slash(self):
        # _getMatchedPart always returns the absolute path to the object that
        # the server matched, even if there is no trailing slash and no
        # trailing path.
        #
        # This test is added to exercise a corner case.
        branch = self.factory.makeBranch()
        requested_path = '/%s' % branch.unique_name
        matched_part = self.client._getMatchedPart(
            requested_path,
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''))
        self.assertEqual('/%s' % branch.unique_name, matched_part)

    def test_get_matched_part_no_trailing_path(self):
        # _getMatchedPart always returns the absolute path to the object that
        # the server matched, even if there is a trailing slash and no
        # trailing path.
        #
        # This test is added to exercise a corner case.
        branch = self.factory.makeBranch()
        requested_path = '/%s/' % branch.unique_name
        matched_part = self.client._getMatchedPart(
            requested_path,
            (BRANCH_TRANSPORT, {'id': branch.id, 'writable': False}, ''))
        self.assertEqual('/%s' % branch.unique_name, matched_part)

    def test_path_translation_cache(self):
        # We can retrieve data that we've added to the cache. The data we
        # retrieve looks an awful lot like the data that the endpoint sends.
        branch = self.factory.makeBranch()
        fake_data = self.factory.getUniqueString()
        self.client._addToCache(
            (BRANCH_TRANSPORT, fake_data, ''), '/%s' % branch.unique_name)
        result = self.client._getFromCache('/%s/foo/bar' % branch.unique_name)
        self.assertEqual(
            (BRANCH_TRANSPORT, fake_data, 'foo/bar'), result)

    def test_not_in_cache(self):
        # _getFromCache raises an error when the given path isn't in the
        # cache.
        self.assertRaises(
            NotInCache, self.client._getFromCache, "foo")

    def test_translatePath_retrieves_from_cache(self):
        # If the path already has a prefix in the cache, we use that prefix to
        # translate the path.
        branch = self.factory.makeBranch()
        # We'll store fake data in the cache to show that we get data from
        # the cache if it's present.
        fake_data = self.factory.getUniqueString()
        self.client._addToCache(
            (BRANCH_TRANSPORT, fake_data, ''), '/%s' % branch.unique_name)
        requested_path = '/%s/foo/bar' % branch.unique_name
        deferred = self.client.translatePath(requested_path)
        def path_translated((transport_type, data, trailing_path)):
            self.assertEqual(BRANCH_TRANSPORT, transport_type)
            self.assertEqual(fake_data, data)
            self.assertEqual('foo/bar', trailing_path)
        return deferred.addCallback(path_translated)

    def test_translatePath_adds_to_cache(self):
        # translatePath adds successful path translations to the cache, thus
        # allowing for future translations to be retrieved from the cache.
        branch = self.factory.makeBranch()
        deferred = self.client.translatePath('/' + branch.unique_name)
        deferred.addCallback(
            self.assertEqual,
            self.client._getFromCache('/' + branch.unique_name))
        return deferred

    def test_translatePath_control_branch_cache_interaction(self):
        # We don't want the caching to make us mis-interpret paths in the
        # branch as paths into the control transport.
        branch = self.factory.makeBranch()
        dev_focus = self.factory.makeBranch(product=branch.product)
        branch.product.development_focus.user_branch = dev_focus
        deferred = self.client.translatePath(
            '/~' + branch.owner.name + '/' + branch.product.name +
            '/.bzr/format')
        def call_translatePath_again(ignored):
            return self.client.translatePath('/' + branch.unique_name)
        def check_results((transport_type, data, trailing_path)):
            self.assertEqual(BRANCH_TRANSPORT, transport_type)
        deferred.addCallback(call_translatePath_again)
        deferred.addCallback(check_results)
        return deferred

    def test_errors_not_cached(self):
        # Don't cache failed translations. What would be the point?
        deferred = self.client.translatePath('/foo/bar/baz')
        def translated_successfully(result):
            self.fail(
                "Translated successfully. Expected error, got %r" % result)
        def failed_translation(failure):
            self.assertRaises(
                NotInCache, self.client._getFromCache, '/foo/bar/baz')
        return deferred.addCallbacks(
            translated_successfully, failed_translation)


class TestTrapFault(TestCase):
    """Tests for `trap_fault`."""

    def makeFailure(self, exception_factory, *args, **kwargs):
        """Make a `Failure` from the given exception factory."""
        try:
            raise exception_factory(*args, **kwargs)
        except:
            return Failure()

    def assertRaisesFailure(self, failure, function, *args, **kwargs):
        try:
            function(*args, **kwargs)
        except Failure, raised_failure:
            self.assertEqual(failure, raised_failure)

    def test_raises_non_faults(self):
        # trap_fault re-raises any failures it gets that aren't faults.
        failure = self.makeFailure(RuntimeError, 'example failure')
        self.assertRaisesFailure(failure, trap_fault, failure, 235)

    def test_raises_faults_with_wrong_code(self):
        # trap_fault re-raises any failures it gets that are faults but have
        # the wrong fault code.
        failure = self.makeFailure(Fault, 123, 'example failure')
        self.assertRaisesFailure(failure, trap_fault, failure, 235)

    def test_raises_faults_if_no_codes_given(self):
        # If trap_fault is not given any fault codes, it re-raises the fault
        # failure.
        failure = self.makeFailure(Fault, 123, 'example failure')
        self.assertRaisesFailure(failure, trap_fault, failure)

    def test_returns_fault_if_code_matches(self):
        # trap_fault returns the Fault inside the Failure if the fault code
        # matches what's given.
        failure = self.makeFailure(Fault, 123, 'example failure')
        fault = trap_fault(failure, 123)
        self.assertEqual(123, fault.faultCode)
        self.assertEqual('example failure', fault.faultString)

    def test_returns_fault_if_code_matches_one_of_set(self):
        # trap_fault returns the Fault inside the Failure if the fault code
        # matches even one of the given fault codes.
        failure = self.makeFailure(Fault, 123, 'example failure')
        fault = trap_fault(failure, 235, 432, 123, 999)
        self.assertEqual(123, fault.faultCode)
        self.assertEqual('example failure', fault.faultString)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

