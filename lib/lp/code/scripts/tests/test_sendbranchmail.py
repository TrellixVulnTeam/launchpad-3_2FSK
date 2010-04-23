#! /usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the sendbranchmail script"""

import unittest
import transaction

from canonical.testing import ZopelessAppServerLayer
from canonical.launchpad.scripts.tests import run_script
from lp.code.enums import (
    BranchSubscriptionDiffSize, BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel)
from lp.code.model.branchjob import (
    RevisionMailJob, RevisionsAddedJob)
from lp.testing import TestCaseWithFactory


class TestSendbranchmail(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def createBranch(self):
        branch, tree = self.createMirroredBranchAndTree()
        branch.subscribe(branch.registrant,
            BranchSubscriptionNotificationLevel.FULL,
            BranchSubscriptionDiffSize.WHOLEDIFF,
            CodeReviewNotificationLevel.FULL)
        transport = tree.bzrdir.root_transport
        transport.put_bytes('foo', 'bar')
        tree.add('foo')
        tree.commit('Added foo.', rev_id='rev1')
        return branch, tree

    def test_sendbranchmail(self):
        """Ensure sendbranchmail runs and sends email."""
        self.useTempBzrHome()
        branch, tree = self.createBranch()
        RevisionMailJob.create(
            branch, 1, 'from@example.org', 'body', True, 'foo')
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/sendbranchmail.py', [])
        self.assertEqual(
            'INFO    Creating lockfile: /var/lock/launchpad-sendbranchmail.lock\n'
            'INFO    Ran 1 RevisionMailJobs.\n', stderr)
        self.assertEqual('', stdout)
        self.assertEqual(0, retcode)

    def test_sendbranchmail_handles_oops(self):
        """Ensure sendbranchmail runs and sends email."""
        self.useTempBzrHome()
        branch = self.factory.makeBranch()
        RevisionMailJob.create(
            branch, 1, 'from@example.org', 'body', True, 'foo')
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/sendbranchmail.py', [])
        self.assertIn(
            'INFO    Creating lockfile: /var/lock/launchpad-sendbranchmail.lock\n',
            stderr)
        self.assertIn('INFO    Job resulted in OOPS:', stderr)
        self.assertIn('INFO    Ran 0 RevisionMailJobs.\n', stderr)
        self.assertEqual('', stdout)
        self.assertEqual(0, retcode)

    def test_revision_added_job(self):
        """RevisionsAddedJobs are run by sendbranchmail."""
        self.useTempBzrHome()
        branch, tree = self.createBranch()
        tree.bzrdir.root_transport.put_bytes('foo', 'baz')
        tree.commit('Added foo.', rev_id='rev2')
        RevisionsAddedJob.create(
            branch, 'rev1', 'rev2', 'from@example.org')
        transaction.commit()
        retcode, stdout, stderr = run_script(
            'cronscripts/sendbranchmail.py', [])
        self.assertEqual(
            'INFO    Creating lockfile: /var/lock/launchpad-sendbranchmail.lock\n'
            'INFO    Ran 1 RevisionMailJobs.\n',
            stderr)
        self.assertEqual('', stdout)
        self.assertEqual(0, retcode)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
