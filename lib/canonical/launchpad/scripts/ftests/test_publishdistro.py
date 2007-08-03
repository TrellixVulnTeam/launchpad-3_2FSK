# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Functional tests for publish-distro.py script."""

__metaclass__ = type

import os
import subprocess
import sys
import unittest

from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.interfaces import (
    IArchiveSet, IDistributionSet, IPersonSet)
from canonical.launchpad.tests.test_publishing import TestNativePublishingBase
from canonical.lp.dbschema import (
    ArchivePurpose, PackagePublishingStatus, PackagePublishingPocket)

class TestPublishDistro(TestNativePublishingBase):
    """Test the publish-distro.py script works properly."""

    def runPublishDistro(self, extra_args, distribution="ubuntutest"):
        """Run publish-distro.py, returning the result and output."""
        script = os.path.join(config.root, "scripts", "publish-distro.py")
        args = [sys.executable, script, "-v", "-d", "ubuntutest"]
        args.extend(extra_args)
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return (process.returncode, stdout, stderr)

    def testRun(self):
        """Try a simple publish-distro run.

        Expect database publishing record to be updated to PUBLISHED and
        the file to be written in disk.
        """
        pub_source = self.getPubSource(filecontent='foo')
        self.layer.txn.commit()

        rc, out, err = self.runPublishDistro([])

        self.assertEqual(0, rc, "Publisher failed with:\n%s\n%s" % (out, err))
        self.assertEqual(pub_source.status, PackagePublishingStatus.PUBLISHED)

        foo_path = "%s/main/f/foo/foo.dsc" % self.pool_dir
        self.assertEqual(open(foo_path).read().strip(), 'foo')

    def assertExists(self, path):
        """Assert if the given path exists."""
        self.assertTrue(os.path.exists(path), "Not Found: '%s'" % path)

    def assertNotExists(self, path):
        """Assert if the given path does not exist."""
        self.assertFalse(os.path.exists(path), "Found: '%s'" % path)

    def testRunWithSuite(self):
        """Try to run publish-distro with restricted suite option.

        Expect only update and disk writing only in the publishing record
        targeted to the specified suite, other records should be untouched
        and not present in disk.
        """
        pub_source = self.getPubSource(filecontent='foo')
        pub_source2 = self.getPubSource(
            sourcename='baz', filecontent='baz',
            distroseries=self.ubuntutest['hoary-test'])
        self.layer.txn.commit()

        rc, out, err = self.runPublishDistro(['-s', 'hoary-test'])

        self.assertEqual(0, rc, "Publisher failed with:\n%s\n%s" % (out, err))

        self.assertEqual(pub_source.status, PackagePublishingStatus.PENDING)
        self.assertEqual(pub_source2.status, PackagePublishingStatus.PUBLISHED)

        foo_path = "%s/main/f/foo/foo.dsc" % self.pool_dir
        self.assertNotExists(foo_path)

        baz_path = "%s/main/b/baz/baz.dsc" % self.pool_dir
        self.assertEqual('baz', open(baz_path).read().strip())

    def testForPPA(self):
        """Try to run publish-distro in PPA mode.

        It should deal only with PPA publications.
        """
        pub_source = self.getPubSource(filecontent='foo')

        cprov = getUtility(IPersonSet).getByName('cprov')
        pub_source2 = self.getPubSource(
            sourcename='baz', filecontent='baz', archive=cprov.archive)

        ubuntutest = getUtility(IDistributionSet)['ubuntutest']
        name16 = getUtility(IPersonSet).getByName('name16')
        getUtility(IArchiveSet).new(purpose=ArchivePurpose.PPA, owner=name16,
            distribution=ubuntutest)
        pub_source3 = self.getPubSource(
            sourcename='bar', filecontent='bar', archive=name16.archive)

        self.layer.txn.commit()

        rc, out, err = self.runPublishDistro(['--ppa'])

        self.assertEqual(0, rc, "Publisher failed with:\n%s\n%s" % (out, err))

        self.assertEqual(pub_source.status, PackagePublishingStatus.PENDING)
        self.assertEqual(pub_source2.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(pub_source3.status, PackagePublishingStatus.PUBLISHED)

        foo_path = "%s/main/f/foo/foo.dsc" % self.pool_dir
        self.assertEqual(False, os.path.exists(foo_path))

        baz_path = os.path.join(
            config.personalpackagearchive.root, cprov.name,
            'ubuntutest/pool/main/b/baz/baz.dsc')
        self.assertEqual('baz', open(baz_path).read().strip())

        bar_path = os.path.join(
            config.personalpackagearchive.root, name16.name,
            'ubuntutest/pool/main/b/bar/bar.dsc')
        self.assertEqual('bar', open(bar_path).read().strip())

    def testRunWithEmptySuites(self):
        """Try a publish-distro run on empty suites in careful_apt mode

        Expect it to create all indexes, including current 'Release' file
        for the empty suites specified.
        """
        rc, out, err = self.runPublishDistro(
            ['-A', '-s', 'hoary-test-updates', '-s', 'hoary-test-backports'])

        self.assertEqual(0, rc)

        # Check "Release" files
        release_path = "%s/hoary-test-updates/Release" % self.config.distsroot
        self.assertExists(release_path)

        release_path = "%s/hoary-test-backports/Release" % self.config.distsroot
        self.assertExists(release_path)

        release_path = "%s/hoary-test/Release" % self.config.distsroot
        self.assertNotExists(release_path)

        # Check some index files
        index_path = (
            "%s/hoary-test-updates/main/binary-i386/Packages"
            % self.config.distsroot)
        self.assertExists(index_path)

        index_path = (
            "%s/hoary-test-backports/main/binary-i386/Packages"
            % self.config.distsroot)
        self.assertExists(index_path)

        index_path = (
            "%s/hoary-test/main/binary-i386/Packages" % self.config.distsroot)
        self.assertNotExists(index_path)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
