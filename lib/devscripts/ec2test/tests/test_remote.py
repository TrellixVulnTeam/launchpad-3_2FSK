# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the script run on the remote server."""

__metaclass__ = type

import gzip
import os
from StringIO import StringIO
import sys
import tempfile
import unittest

from bzrlib.tests import TestCaseWithTransport

from testtools import TestCase

from devscripts.ec2test.remote import (
    FlagFallStream,
    gzip_file,
    remove_pidfile,
    Request,
    SummaryResult,
    write_pidfile,
    )


class TestFlagFallStream(TestCase):
    """Tests for `FlagFallStream`."""

    def test_doesnt_write_before_flag(self):
        # A FlagFallStream does not forward any writes before it sees the
        # 'flag'.
        stream = StringIO()
        flag = self.getUniqueString('flag')
        flagfall = FlagFallStream(stream, flag)
        flagfall.write('foo')
        flagfall.flush()
        self.assertEqual('', stream.getvalue())

    def test_writes_after_flag(self):
        # After a FlagFallStream sees the flag, it forwards all writes.
        stream = StringIO()
        flag = self.getUniqueString('flag')
        flagfall = FlagFallStream(stream, flag)
        flagfall.write('foo')
        flagfall.write(flag)
        flagfall.write('bar')
        self.assertEqual('%sbar' % (flag,), stream.getvalue())

    def test_mixed_write(self):
        # If a single call to write has pre-flagfall and post-flagfall data in
        # it, then only the post-flagfall data is forwarded to the stream.
        stream = StringIO()
        flag = self.getUniqueString('flag')
        flagfall = FlagFallStream(stream, flag)
        flagfall.write('foo%sbar' % (flag,))
        self.assertEqual('%sbar' % (flag,), stream.getvalue())


class TestSummaryResult(TestCase):
    """Tests for `SummaryResult`."""

    def makeException(self, factory=None, *args, **kwargs):
        if factory is None:
            factory = RuntimeError
        try:
            raise factory(*args, **kwargs)
        except:
            return sys.exc_info()

    def test_formatError(self):
        # SummaryResult._formatError() combines the name of the test, the kind
        # of error and the details of the error in a nicely-formatted way.
        result = SummaryResult(None)
        output = result._formatError('FOO', 'test', 'error')
        expected = '%s\nFOO: test\n%s\nerror\n' % (
            result.double_line, result.single_line)
        self.assertEqual(expected, output)

    def test_addError(self):
        # SummaryResult.addError doesn't write immediately.
        stream = StringIO()
        test = self
        error = self.makeException()
        result = SummaryResult(stream)
        expected = result._formatError(
            'ERROR', test, result._exc_info_to_string(error, test))
        result.addError(test, error)
        self.assertEqual(expected, stream.getvalue())

    def test_addFailure_does_not_write_immediately(self):
        # SummaryResult.addFailure doesn't write immediately.
        stream = StringIO()
        test = self
        error = self.makeException()
        result = SummaryResult(stream)
        expected = result._formatError(
            'FAILURE', test, result._exc_info_to_string(error, test))
        result.addFailure(test, error)
        self.assertEqual(expected, stream.getvalue())


class TestPidfileHelpers(TestCase):
    """Tests for `write_pidfile` and `remove_pidfile`."""

    def test_write_pidfile(self):
        fd, path = tempfile.mkstemp()
        self.addCleanup(os.unlink, path)
        os.close(fd)
        write_pidfile(path)
        self.assertEqual(os.getpid(), int(open(path, 'r').read()))

    def test_remove_pidfile(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        write_pidfile(path)
        remove_pidfile(path)
        self.assertEqual(False, os.path.exists(path))

    def test_remove_nonexistent_pidfile(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, 'doesntexist')
        remove_pidfile(path)
        self.assertEqual(False, os.path.exists(path))


class TestGzipFile(TestCase):
    """Tests for `gzip_file`."""

    def test_gzip_file(self):
        fd, path = tempfile.mkstemp()
        contents = 'foobarbaz\n'
        os.write(fd, contents)
        os.close(fd)
        gz_file = gzip_file(path)
        self.assertEqual(contents, gzip.open(gz_file, 'r').read())


class TestRequest(TestCaseWithTransport):
    """Tests for `Request`."""

    def test_doesnt_want_email(self):
        # If no email addresses were provided, then the user does not want to
        # receive email.
        req = Request(None, None, None, None, emails=None, pqm_message=None)
        self.assertEqual(False, req.wants_email)

    def test_wants_email(self):
        # If some email addresses were provided, then the user wants to
        # receive email.
        req = Request(
            None, None, None, None, emails=['foo@example.com'],
            pqm_message=None)
        self.assertEqual(True, req.wants_email)

    def test_get_trunk_details(self):
        tree = self.make_branch_and_tree('.')
        branch = tree.branch
        parent = 'http://example.com/bzr/branch'
        branch.set_parent(parent)
        req = Request(None, None, branch.base, None)
        self.assertEqual((parent, branch.revno()), req.get_trunk_details())

    def test_get_branch_details_no_commits(self):
        tree = self.make_branch_and_tree('.')
        req = Request(None, None, tree.basedir, None)
        self.assertEqual(None, req.get_branch_details())

    def test_get_branch_details_no_merge(self):
        tree = self.make_branch_and_tree('.')
        tree.commit(message='foo')
        req = Request(None, None, tree.basedir, None)
        self.assertEqual(None, req.get_branch_details())

    def test_get_branch_details_merge(self):
        tree = self.make_branch_and_tree('.')
        # Fake a merge, giving silly revision ids.
        tree.add_pending_merge('foo', 'bar')
        req = Request('https://example.com/bzr/thing', 42, tree.basedir, None)
        self.assertEqual(
            ('https://example.com/bzr/thing', 42), req.get_branch_details())

    def test_get_nick_trunk_only(self):
        tree = self.make_branch_and_tree('.')
        branch = tree.branch
        parent = 'http://example.com/bzr/db-devel'
        branch.set_parent(parent)
        req = Request(None, None, branch.base, None)
        self.assertEqual('db-devel', req.get_nick())

    def test_get_nick_merge(self):
        tree = self.make_branch_and_tree('.')
        # Fake a merge, giving silly revision ids.
        tree.add_pending_merge('foo', 'bar')
        req = Request('https://example.com/bzr/thing', 42, tree.basedir, None)
        self.assertEqual('thing', req.get_nick())

    def test_get_merge_description_trunk_only(self):
        tree = self.make_branch_and_tree('.')
        branch = tree.branch
        parent = 'http://example.com/bzr/db-devel'
        branch.set_parent(parent)
        req = Request(None, None, branch.base, None)
        self.assertEqual('db-devel', req.get_merge_description())

    def test_get_merge_description_merge(self):
        tree = self.make_branch_and_tree('.')
        branch = tree.branch
        parent = 'http://example.com/bzr/db-devel/'
        branch.set_parent(parent)
        tree.add_pending_merge('foo', 'bar')
        req = Request('https://example.com/bzr/thing', 42, tree.basedir, None)
        self.assertEqual('thing => db-devel', req.get_merge_description())


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
