# Copyright 2004 Canonical Ltd.  All rights reserved.
#

"""Tests for pool.py."""

__metaclass__ = type


import os
import sha
import sys
import shutil
from tempfile import mkdtemp
import unittest

from canonical.archivepublisher.tests.util import FakeLogger
from canonical.archivepublisher.diskpool import DiskPool, poolify


class MockFile:
    def __init__(self, contents):
        self.contents = contents

    def open(self):
        self.loc = 0
    
    def read(self, chunksize):
        end_chunk = self.loc + chunksize
        chunk = self.contents[self.loc:end_chunk]
        self.loc = end_chunk
        return chunk

    def close(self):
        pass


class PoolTestingFile:
    def __init__(self, pool, sourcename, filename):
        self.pool = pool
        self.sourcename = sourcename
        self.filename = filename
        self.contents = sourcename

    def addToPool(self, component):
        return self.pool.addFile(
            component, self.sourcename, self.filename,
            sha.sha(self.contents).hexdigest(), MockFile(self.contents))

    def removeFromPool(self, component):
        return self.pool.removeFile(component, self.sourcename, self.filename)

    def checkExists(self, component):
        path = self.pool.pathFor(component, self.sourcename, self.filename)
        return os.path.exists(path)

    def checkIsLink(self, component):
        path = self.pool.pathFor(component, self.sourcename, self.filename)
        return os.path.islink(path)

    def checkIsFile(self, component):
        return self.checkExists(component) and not self.checkIsLink(component)
    
        
class TestPoolification(unittest.TestCase):

    def testPoolificationOkay(self):
        """poolify should poolify properly"""
        cases = (
            ( "foo", "main", "main/f/foo" ),
            ( "foo", "universe", "universe/f/foo" ),
            ( "libfoo", "main", "main/libf/libfoo" )
            )
        for case in cases:
            self.assertEqual( case[2], poolify(case[0], case[1]) )


class TestPool(unittest.TestCase):
    def setUp(self):
        self.pool_path = mkdtemp()
        self.pool = DiskPool(self.pool_path, FakeLogger())

    def tearDown(self):
        shutil.rmtree(self.pool_path)

    def testSimpleAdd(self):
        """Adding a new file should work."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.FILE_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        
    def testSimpleSymlink(self):
        """Adding a file twice should result in a symlink."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")
        result = foo.addToPool("universe")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testSymlinkShuffleOnAdd(self):
        """If the second add is a more preferred component, links shuffle."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("universe")
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testRemoveSymlink(self):
        """Remove file should just remove a symlink"""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")
        foo.addToPool("universe")
        
        size = foo.removeFromPool("universe")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(31, size)

    def testRemoveLoneFile(self):
        """Removing a file with no symlinks removes it."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")
        
        size = foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(3, size)

    def testSymlinkShuffleOnRemove(self):
        """Removing a file with a symlink shuffles links."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("universe")
        foo.addToPool("main")

        foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("main"))
        self.assertTrue(foo.checkIsFile("universe"))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
