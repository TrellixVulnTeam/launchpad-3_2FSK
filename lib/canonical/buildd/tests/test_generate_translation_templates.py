# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os
from unittest import TestLoader
import tarfile

from lp.testing.fakemethod import FakeMethod

from canonical.buildd.pottery.generate_translation_templates import (
    GenerateTranslationTemplates)

from canonical.launchpad.ftests.script import run_script
from canonical.testing.layers import ZopelessDatabaseLayer
from lp.code.model.directbranchcommit import DirectBranchCommit
from lp.testing import TestCaseWithFactory


class TestGenerateTranslationTemplates(TestCaseWithFactory):
    """Test slave-side generate-translation-templates script."""
    layer = ZopelessDatabaseLayer

    result_name = "translation-templates.tar.gz"

    def test_getBranch_url(self):
        # If passed a branch URL, the template generation script will
        # check out that branch into a directory called "source-tree."
        branch_url = 'lp://~my/translation/branch'

        generator = GenerateTranslationTemplates(
            branch_url, self.result_name, self.makeTemporaryDirectory())
        generator._checkout = FakeMethod()
        generator._getBranch()

        self.assertEqual(1, generator._checkout.call_count)
        self.assertTrue(generator.branch_dir.endswith('source-tree'))

    def test_getBranch_dir(self):
        # If passed a branch directory, the template generation script
        # works directly in that directory.
        branch_dir = '/home/me/branch'

        generator = GenerateTranslationTemplates(
            branch_dir, self.result_name, self.makeTemporaryDirectory())
        generator._checkout = FakeMethod()
        generator._getBranch()

        self.assertEqual(0, generator._checkout.call_count)
        self.assertEqual(branch_dir, generator.branch_dir)

    def _createBranch(self, content_map=None):
        """Create a working branch.
        
        :param content_map: optional dict mapping file names to file contents.
            Each of these files with their contents will be written to the
            branch.

        :return: a fresh lp.code.model.Branch backed by a real bzr branch.
        """
        db_branch, tree = self.create_branch_and_tree(hosted=True)
        populist = DirectBranchCommit(db_branch)
        last_revision = populist.bzrbranch.last_revision()
        db_branch.last_scanned_id = populist.last_scanned_id = last_revision

        if content_map is not None:
            for name, contents in content_map.iteritems():
                populist.writeFile(name, contents)
            populist.commit("Populating branch.")

        return db_branch

    def test_getBranch_bzr(self):
        # _getBranch can retrieve branch contents from a branch URL.
        self.useBzrBranches()
        marker_text = "Ceci n'est pas cet branch."
        branch = self._createBranch({'marker.txt': marker_text})
        branch_url = branch.getPullURL()

        generator = GenerateTranslationTemplates(
            branch_url, self.result_name, self.makeTemporaryDirectory())
        generator.branch_dir = self.makeTemporaryDirectory()
        generator._getBranch()

        marker_file = file(os.path.join(generator.branch_dir, 'marker.txt'))
        self.assertEqual(marker_text, marker_file.read())

    def test_templates_tarball(self):
        # Create a tarball from pot files.
        workdir = self.makeTemporaryDirectory()
        branchdir = os.path.join(workdir, 'branchdir')
        dummy_tar = os.path.join(
            os.path.dirname(__file__),'dummy_templates.tar.gz')
        tar = tarfile.open(dummy_tar, 'r|*')
        tar.extractall(branchdir)
        potnames = [name for name in tar.getnames() if not name.endswith('/')]
        tar.close()

        generator = GenerateTranslationTemplates(
            branchdir, self.result_name, workdir)
        generator._getBranch()
        generator._make_tarball(potnames)
        tar = tarfile.open(os.path.join(workdir, self.result_name), 'r|*')
        tarnames = tar.getnames()
        tar.close()
        self.assertContentEqual(potnames, tarnames)

    def test_script(self):
        tempdir = self.makeTemporaryDirectory()
        workdir = self.makeTemporaryDirectory()
        (retval, out, err) = run_script(
            'lib/canonical/buildd/pottery/generate_translation_templates.py',
            args=[tempdir, self.result_name, workdir])
        self.assertEqual(0, retval)


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
