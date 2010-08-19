# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for lp.services.osutils."""

__metaclass__ = type

import errno
import os
import socket
import tempfile
import unittest

from lp.services.osutils import (
    remove_tree,
    until_no_eintr,
    )
from lp.testing import TestCase


class TestRemoveTree(TestCase):
    """Tests for remove_tree."""

    def test_removes_directory(self):
        # remove_tree deletes the directory.
        directory = tempfile.mkdtemp()
        remove_tree(directory)
        self.assertFalse(os.path.isdir(directory))
        self.assertFalse(os.path.exists(directory))

    def test_on_nonexistent_path_passes_silently(self):
        # remove_tree simply does nothing when called on a non-existent path.
        directory = tempfile.mkdtemp()
        nonexistent_tree = os.path.join(directory, 'foo')
        remove_tree(nonexistent_tree)
        self.assertFalse(os.path.isdir(nonexistent_tree))
        self.assertFalse(os.path.exists(nonexistent_tree))

    def test_raises_on_file(self):
        # If remove_tree is pased a file, it raises an OSError.
        directory = tempfile.mkdtemp()
        filename = os.path.join(directory, 'foo')
        fd = open(filename, 'w')
        fd.write('data')
        fd.close()
        self.assertRaises(OSError, remove_tree, filename)


class TestUntilNoEINTR(TestCase):
    """Tests for until_no_eintr."""

    def test_no_calls(self):
        # If the user has, bizarrely, asked for 0 attempts, then never try to
        # call the function.
        calls = []
        until_no_eintr(0, calls.append, None)
        self.assertEqual([], calls)

    def test_function_doesnt_raise(self):
        # If the function doesn't raise, call it only once.
        calls = []
        until_no_eintr(10, calls.append, None)
        self.assertEqual(1, len(calls))

    def test_returns_function_return(self):
        # If the function doesn't raise, return its value.
        ret = until_no_eintr(1, lambda: 42)
        self.assertEqual(42, ret)

    def test_raises_exception(self):
        # If the function raises an exception that's not EINTR, then re-raise
        # it.
        self.assertRaises(ZeroDivisionError, until_no_eintr, 1, lambda: 1/0)

    def test_retries_on_ioerror_eintr(self):
        # Retry the function as long as it keeps raising IOError(EINTR).
        calls = []
        def function():
            calls.append(None)
            if len(calls) < 5:
                raise IOError(errno.EINTR, os.strerror(errno.EINTR))
            return 'orange'
        ret = until_no_eintr(10, function)
        self.assertEqual(5, len(calls))
        self.assertEqual('orange', ret)

    def test_retries_on_oserror_eintr(self):
        # Retry the function as long as it keeps raising OSError(EINTR).
        calls = []
        def function():
            calls.append(None)
            if len(calls) < 5:
                raise OSError(errno.EINTR, os.strerror(errno.EINTR))
            return 'orange'
        ret = until_no_eintr(10, function)
        self.assertEqual(5, len(calls))
        self.assertEqual('orange', ret)

    def test_retries_on_socket_error_eintr(self):
        # Retry the function as long as it keeps raising socket.error(EINTR).
        # This test is redundant on Python 2.6, since socket.error is an
        # IOError there.
        calls = []
        def function():
            calls.append(None)
            if len(calls) < 5:
                raise socket.error(errno.EINTR, os.strerror(errno.EINTR))
            return 'orange'
        ret = until_no_eintr(10, function)
        self.assertEqual(5, len(calls))
        self.assertEqual('orange', ret)

    def test_raises_other_error_without_retry(self):
        # Any other kind of IOError (or OSError or socket.error) is re-raised
        # with a retry attempt.
        calls = []
        def function():
            calls.append(None)
            if len(calls) < 5:
                raise IOError(errno.ENOENT, os.strerror(errno.ENOENT))
            return 'orange'
        error = self.assertRaises(IOError, until_no_eintr, 10, function)
        self.assertEqual(errno.ENOENT, error.errno)
        self.assertEqual(1, len(calls))

    def test_never_exceeds_retries(self):
        # If the function keeps on raising EINTR, then stop running it after
        # the given number of retries, and just re-raise the error.
        calls = []
        def function():
            calls.append(None)
            raise IOError(errno.EINTR, os.strerror(errno.EINTR))
        error = self.assertRaises(IOError, until_no_eintr, 10, function)
        self.assertEqual(errno.EINTR, error.errno)
        self.assertEqual(10, len(calls))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
