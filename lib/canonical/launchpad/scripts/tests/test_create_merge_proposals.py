#! /usr/bin/python2.4
# Copyright 2008, 2009 Canonical Ltd.  All rights reserved.

"""Test the create_merge_proposals script"""

from cStringIO import StringIO
import unittest

from bzrlib import errors as bzr_errors
from bzrlib.branch import Branch
import transaction
from zope.component import getUtility

from canonical.testing import ZopelessAppServerLayer
from canonical.codehosting.vfs import get_multi_server
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.launchpad.scripts.tests import run_script
from canonical.launchpad.database.branchmergeproposal import (
    CreateMergeProposalJob)
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet


class TestCreateMergeProposals(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def test_create_merge_proposals(self):
        """Ensure create_merge_proposals runs and creates proposals."""
        email, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail())
        CreateMergeProposalJob.create(file_alias)
        self.assertEqual(0, source.landing_targets.count())
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/create_merge_proposals.py', [])
        self.assertEqual(0, retcode)
        self.assertEqual(
            'INFO    creating lockfile\n'
            'INFO    Ran 1 CreateMergeProposalJobs.\n', stderr)
        self.assertEqual('', stdout)
        self.assertEqual(1, source.landing_targets.count())

    def test_merge_directive_with_bundle(self):
        self.useTempBzrHome()
        server = get_multi_server(write_hosted=True, write_mirrored=True)
        server.setUp()
        self.addCleanup(server.destroy)
        branch, tree = self.create_branch_and_tree()
        tree.branch.set_public_branch(branch.bzr_identity)
        tree.commit('rev1')
        source = tree.bzrdir.sprout('source').open_workingtree()
        source.commit('rev2')
        message = self.factory.makeBundleMergeDirectiveEmail(
            source.branch, branch)
        message_str = message.as_string()
        library_file_aliases = getUtility(ILibraryFileAliasSet)
        file_alias = library_file_aliases.create(
            '*', len(message_str), StringIO(message_str), '*')
        CreateMergeProposalJob.create(file_alias)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/create_merge_proposals.py', [])
        self.assertEqual(0, retcode)
        self.assertEqual(
            'INFO    creating lockfile\n'
            'INFO    Ran 1 CreateMergeProposalJobs.\n', stderr)
        self.assertEqual('', stdout)
        # The hosted location should be populated, not the mirror.
        bmp = branch.landing_candidates[0]
        self.assertRaises(
            bzr_errors.NotBranchError, Branch.open,
            bmp.source_branch.warehouse_url)
        local_source = Branch.open(bmp.source_branch.getPullURL())
        # The hosted branch has the correct last revision.
        self.assertEqual(
            source.branch.last_revision(), local_source.last_revision())
        # A mirror should be scheduled.
        self.assertIsNot(None, bmp.source_branch.next_mirror_time)

    def test_oops(self):
        """A bogus request should cause an oops, not an exception."""
        file_alias = self.factory.makeLibraryFileAlias('bogus')
        CreateMergeProposalJob.create(file_alias)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/create_merge_proposals.py', [])
        self.assertEqual(
            'INFO    creating lockfile\n'
            'INFO    Ran 0 CreateMergeProposalJobs.\n', stderr)
        self.assertEqual('', stdout)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
