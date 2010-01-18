# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for source package builds."""

__metaclass__ = type

import unittest

import transaction
from zope.component import getUtility

from canonical.testing.layers import DatabaseFunctionalLayer

from lp.soyuz.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildJob, ISourcePackageRecipeBuild,
    ISourcePackageRecipeBuildSource)
from lp.testing import TestCaseWithFactory


class TestSourcePackageRecipeBuild(TestCaseWithFactory):
    """Test the source package build object."""

    layer = DatabaseFunctionalLayer

    def makeSourcePackageRecipeBuild(self):
        """Create a `SourcePackageRecipeBuild` for testing."""
        return getUtility(ISourcePackageRecipeBuildSource).new(
            sourcepackage=self.factory.makeSourcePackage(),
            recipe=self.factory.makeSourcePackageRecipe(),
            archive=self.factory.makeArchive(),
            requester=self.factory.makePerson())

    def test_providesInterface(self):
        # SourcePackageRecipeBuild provides ISourcePackageRecipeBuild.
        spb = self.makeSourcePackageRecipeBuild()
        self.assertProvides(spb, ISourcePackageRecipeBuild)

    def test_saves_record(self):
        # A source package recipe build can be stored in the database
        spb = self.makeSourcePackageRecipeBuild()
        transaction.commit()
        self.assertProvides(spb, ISourcePackageRecipeBuild)

    def test_makeJob(self):
        # A build farm job can be obtained from a SourcePackageRecipeBuild
        spb = self.makeSourcePackageRecipeBuild()
        job = spb.makeJob()
        self.assertProvides(job, ISourcePackageRecipeBuildJob)

    def test_getTitle(self):
        # A build farm job implements getTitle().
        spb = self.makeSourcePackageRecipeBuild()
        job = spb.makeJob()
        title_prefix = "%s-%s-%s" % (
            job.build.distroseries.displayname, job.build.sourcepackagename,
            job.build.archive.displayname)
        self.assertTrue(job.getTitle().startswith(title_prefix))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
