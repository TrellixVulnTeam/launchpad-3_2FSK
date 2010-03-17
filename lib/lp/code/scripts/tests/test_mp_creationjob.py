#! /usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the sendbranchmail script"""

import unittest
import transaction

from canonical.testing import ZopelessAppServerLayer
from lp.testing import TestCaseWithFactory
from canonical.launchpad.scripts.tests import run_script
from lp.code.model.branchmergeproposal import BranchMergeProposal
from lp.code.model.branchmergeproposaljob import MergeProposalCreatedJob


class TestDiffBMPs(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def test_mpcreationjobs(self):
        """Ensure mpcreationjobs runs and generates diffs."""
        self.useTempBzrHome()
        target, target_tree = self.createMirroredBranchAndTree()
        target_tree.bzrdir.root_transport.put_bytes('foo', 'foo\n')
        target_tree.add('foo')
        target_tree.commit('added foo')
        target.linkBug(self.factory.makeBug(), target.registrant)
        source, source_tree = self.createMirroredBranchAndTree()
        source_tree.pull(target_tree.branch)
        source_tree.bzrdir.root_transport.put_bytes('foo', 'foo\nbar\n')
        source_tree.commit('added bar')
        # Add a fake revisions so the proposal is ready.
        self.factory.makeRevisionsForBranch(source, count=1)
        source.linkBug(self.factory.makeBug(), source.registrant)
        bmp = BranchMergeProposal(
            source_branch=source, target_branch=target,
            registrant=source.owner)
        job = MergeProposalCreatedJob.create(bmp)
        self.assertIs(None, bmp.preview_diff)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/mpcreationjobs.py', [])
        self.assertEqual(0, retcode)
        self.assertEqual('', stdout)
        self.assertEqual(
            'INFO    creating lockfile\n'
            'INFO    Ran 1 MergeProposalCreatedJobs.\n', stderr)
        self.assertIs(None, bmp.review_diff)
        self.assertIsNot(None, bmp.preview_diff)

    def test_mpcreationjobs_records_oops(self):
        """Ensure mpcreationjobs logs an oops if the job fails."""
        bmp = self.factory.makeBranchMergeProposal()
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=1)
        job = MergeProposalCreatedJob.create(bmp)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/mpcreationjobs.py', [])
        self.assertEqual(0, retcode)
        self.assertEqual('', stdout)
        self.assertIn(
            'INFO    Ran 0 MergeProposalCreatedJobs.\n', stderr)
        self.assertIn(
            'INFO    Job resulted in OOPS:', stderr)

def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
