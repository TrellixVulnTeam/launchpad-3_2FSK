# Copyright 2008, 2009 Canonical Ltd.  All rights reserved.

"""Tests for BranchJobs."""

__metaclass__ = type

from unittest import TestLoader

from bzrlib import errors as bzr_errors
from canonical.testing import DatabaseFunctionalLayer, LaunchpadZopelessLayer
from sqlobject import SQLObjectNotFound
import transaction

from canonical.launchpad.database.branchjob import (
    BranchDiffJob, BranchJob, BranchJobType, RevisionsAddedJob,
    RevisionMailJob)
from canonical.launchpad.database.branchrevision import BranchRevision
from canonical.launchpad.database.revision import RevisionSet
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.testing import verifyObject
from canonical.launchpad.interfaces import (
    BranchSubscriptionNotificationLevel, CodeReviewNotificationLevel)
from canonical.launchpad.interfaces.branchjob import (
    IBranchDiffJob, IBranchJob, IRevisionMailJob)
from canonical.launchpad.interfaces.branchsubscription import (
    BranchSubscriptionDiffSize,)
from canonical.launchpad.testing import TestCaseWithFactory
from canonical.launchpad.tests.mail_helpers import pop_notifications


class TestBranchJob(TestCaseWithFactory):
    """Tests for BranchJob."""

    layer = DatabaseFunctionalLayer

    def test_providesInterface(self):
        """Ensure that BranchJob implements IBranchJob."""
        branch = self.factory.makeAnyBranch()
        verifyObject(
            IBranchJob, BranchJob(branch, BranchJobType.STATIC_DIFF, {}))

    def test_destroySelf_destroys_job(self):
        """Ensure that BranchJob.destroySelf destroys the Job as well."""
        branch = self.factory.makeAnyBranch()
        branch_job = BranchJob(branch, BranchJobType.STATIC_DIFF, {})
        job_id = branch_job.job.id
        branch_job.destroySelf()
        self.assertRaises(SQLObjectNotFound, BranchJob.get, job_id)


class TestBranchDiffJob(TestCaseWithFactory):
    """Tests for BranchDiffJob."""

    layer = LaunchpadZopelessLayer

    def test_providesInterface(self):
        """Ensure that BranchDiffJob implements IBranchDiffJob."""
        verifyObject(
            IBranchDiffJob, BranchDiffJob.create(1, '0', '1'))

    def test_run_revision_ids(self):
        """Ensure that run calculates revision ids."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.commit('First commit', rev_id='rev1')
        job = BranchDiffJob.create(branch, '0', '1')
        static_diff = job.run()
        self.assertEqual('null:', static_diff.from_revision_id)
        self.assertEqual('rev1', static_diff.to_revision_id)

    def test_run_diff_content(self):
        """Ensure that run generates expected diff."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        open('file', 'wb').write('foo\n')
        tree.add('file')
        tree.commit('First commit')
        open('file', 'wb').write('bar\n')
        tree.commit('Next commit')
        job = BranchDiffJob.create(branch, '1', '2')
        static_diff = job.run()
        transaction.commit()
        content_lines = static_diff.diff.text.splitlines()
        self.assertEqual(
            content_lines[3:], ['@@ -1,1 +1,1 @@', '-foo', '+bar', ''],
            content_lines[3:])
        self.assertEqual(7, len(content_lines))

    def test_run_is_idempotent(self):
        """Ensure running an equivalent job emits the same diff."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.commit('First commit')
        job1 = BranchDiffJob.create(branch, '0', '1')
        static_diff1 = job1.run()
        job2 = BranchDiffJob.create(branch, '0', '1')
        static_diff2 = job2.run()
        self.assertTrue(static_diff1 is static_diff2)

    def create_rev1_diff(self):
        """Create a StaticDiff for use by test methods.

        This diff contains an add of a file called hello.txt, with contents
        "Hello World\n".
        """
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        first_revision = 'rev-1'
        tree_transport = tree.bzrdir.root_transport
        tree_transport.put_bytes("hello.txt", "Hello World\n")
        tree.add('hello.txt')
        tree.commit('rev1', timestamp=1e9, timezone=0)
        job = BranchDiffJob.create(branch, '0', '1')
        diff = job.run()
        transaction.commit()
        return diff

    def test_diff_contents(self):
        """Ensure the diff contents match expectations."""
        diff = self.create_rev1_diff()
        expected = (
            "=== added file 'hello.txt'" '\n'
            "--- hello.txt" '\t' "1970-01-01 00:00:00 +0000" '\n'
            "+++ hello.txt" '\t' "2001-09-09 01:46:40 +0000" '\n'
            "@@ -0,0 +1,1 @@" '\n'
            "+Hello World" '\n'
            '\n')
        self.assertEqual(diff.diff.text, expected)

    def test_diff_is_bytes(self):
        """Diffs should be bytestrings.

        Diffs have no single encoding, because they may encompass files in
        multiple encodings.  Therefore, we consider them binary, to avoid
        lossy decoding.
        """
        diff = self.create_rev1_diff()
        self.assertIsInstance(diff.diff.text, str)


class TestRevisionMailJob(TestCaseWithFactory):
    """Tests for BranchDiffJob."""

    layer = LaunchpadZopelessLayer

    def test_providesInterface(self):
        """Ensure that BranchDiffJob implements IBranchDiffJob."""
        branch = self.factory.makeAnyBranch()
        job = RevisionMailJob.create(
            branch, 0, 'from@example.com', 'hello', False, 'subject')
        verifyObject(IRevisionMailJob, job)

    def test_run_sends_mail(self):
        """Ensure RevisionMailJob.run sends mail with correct values."""
        branch = self.factory.makeAnyBranch()
        branch.subscribe(branch.registrant,
            BranchSubscriptionNotificationLevel.FULL,
            BranchSubscriptionDiffSize.WHOLEDIFF,
            CodeReviewNotificationLevel.FULL)
        job = RevisionMailJob.create(
            branch, 0, 'from@example.com', 'hello', False, 'subject')
        job.run()
        (mail,) = pop_notifications()
        self.assertEqual('0', mail['X-Launchpad-Branch-Revision-Number'])
        self.assertEqual('from@example.com', mail['from'])
        self.assertEqual('subject', mail['subject'])
        self.assertEqual(
            'hello\n'
            '\n--\n\n'
            '%(url)s\n'
            '\nYou are subscribed to branch %(identity)s.\n'
            'To unsubscribe from this branch go to'
            ' %(url)s/+edit-subscription.\n' % {
                'url': canonical_url(branch),
                'identity': branch.bzr_identity
                },
            mail.get_payload(decode=True))

    def test_revno_string(self):
        """Ensure that revnos can be strings."""
        branch = self.factory.makeAnyBranch()
        job = RevisionMailJob.create(
            branch, 'removed', 'from@example.com', 'hello', False, 'subject')
        self.assertEqual('removed', job.revno)

    def test_revno_long(self):
        "Ensure that the revno is a long, not an int."
        branch = self.factory.makeAnyBranch()
        job = RevisionMailJob.create(
            branch, 1, 'from@example.com', 'hello', False, 'subject')
        self.assertIsInstance(job.revno, long)

    def test_perform_diff_performs_diff(self):
        """Ensure that a diff is generated when perform_diff is True."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.bzrdir.root_transport.put_bytes('foo', 'bar\n')
        tree.add('foo')
        tree.commit('First commit')
        job = RevisionMailJob.create(
            branch, 1, 'from@example.com', 'hello', True, 'subject')
        mailer = job.getMailer()
        self.assertIn('+bar\n', mailer.diff)

    def test_perform_diff_ignored_for_revno_0(self):
        """For the null revision, no diff is generated."""
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        job = RevisionMailJob.create(
            branch, 0, 'from@example.com', 'hello', True, 'subject')
        self.assertIs(None, job.from_revision_spec)
        self.assertIs(None, job.to_revision_spec)
        mailer = job.getMailer()
        self.assertIs(None, mailer.diff)

    def test_iterReady_ignores_BranchDiffJobs(self):
        """Only BranchDiffJobs should not be listed."""
        branch = self.factory.makeAnyBranch()
        BranchDiffJob.create(branch, 0, 1)
        self.assertEqual([], list(RevisionMailJob.iterReady()))

    def test_iterReady_includes_ready_jobs(self):
        """Ready jobs should be listed."""
        branch = self.factory.makeAnyBranch()
        job = RevisionMailJob.create(
            branch, 0, 'from@example.org', 'body', False, 'subject')
        job.job.sync()
        job.context.sync()
        self.assertEqual([job], list(RevisionMailJob.iterReady()))

    def test_iterReady_excludes_unready_jobs(self):
        """Unready jobs should not be listed."""
        branch = self.factory.makeAnyBranch()
        job = RevisionMailJob.create(
            branch, 0, 'from@example.org', 'body', False, 'subject')
        job.job.start()
        job.job.complete()
        self.assertEqual([], list(RevisionMailJob.iterReady()))


class TestRevisionsAddedJob(TestCaseWithFactory):
    """Tests for RevisionsAddedJob."""

    layer = LaunchpadZopelessLayer

    def test_create(self):
        branch = self.factory.makeBranch()
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev2', '')
        self.assertEqual('rev1', job.last_scanned_id)
        self.assertEqual('rev2', job.last_revision_id)
        self.assertEqual(branch, job.branch)
        self.assertEqual(
            BranchJobType.REVISIONS_ADDED_MAIL, job.context.job_type)

    def test_iterReady(self):
        branch = self.factory.makeBranch()
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev2', '')
        self.assertEqual([job], list(RevisionsAddedJob.iterReady()))

    def updateDBRevisions(self, branch, bzr_branch, revision_ids=None):
        if revision_ids is None:
            revision_ids = bzr_branch.revision_history()
        for bzr_revision in bzr_branch.repository.get_revisions(revision_ids):
            existing = branch.getBranchRevision(
                revision_id=bzr_revision.revision_id)
            if existing is None:
                revision = RevisionSet().newFromBazaarRevision(bzr_revision)
            else:
                revision = RevisionSet().getByRevisionId(
                    bzr_revision.revision_id)
            try:
                revno = bzr_branch.revision_id_to_revno(revision.revision_id)
            except bzr_errors.NoSuchRevision:
                revno = None
            if existing is not None:
                BranchRevision.delete(existing.id)
            branch.createBranchRevision(revno, revision)

    def create3CommitsBranch(self):
        branch, tree = self.create_branch_and_tree()
        tree.lock_write()
        try:
            tree.commit('rev1', rev_id='rev1')
            tree.commit('rev2', rev_id='rev2')
            tree.commit('rev3', rev_id='rev3')
            transaction.commit()
            self.layer.switchDbUser('branchscanner')
            self.updateDBRevisions(
                branch, tree.branch, ['rev1', 'rev2', 'rev3'])
        finally:
            tree.unlock()
        return branch, tree

    def test_iterAddedMainline(self):
        self.useBzrBranches()
        branch, tree = self.create3CommitsBranch()
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev2', '')
        job.bzr_branch.lock_write()
        self.addCleanup(job.bzr_branch.unlock)
        [(revision, revno)] = list(job.iterAddedMainline())
        self.assertEqual(2, revno)

    def test_iterAddedNonMainline(self):
        self.useBzrBranches()
        branch, tree = self.create3CommitsBranch()
        tree.pull(tree.branch, overwrite=True, stop_revision='rev2')
        tree.add_parent_tree_id('rev3')
        tree.commit('rev3a', rev_id='rev3a')
        self.updateDBRevisions(branch, tree.branch, ['rev3', 'rev3a'])
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev3', '')
        job.bzr_branch.lock_write()
        self.addCleanup(job.bzr_branch.unlock)
        out = [x.revision_id for x, y in job.iterAddedMainline()]
        self.assertEqual(['rev2'], out)

    def makeBranchWithCommit(self):
        jrandom = self.factory.makePerson(name='jrandom')
        product = self.factory.makeProduct(name='foo')
        branch = self.factory.makeProductBranch(
            name='bar', product=product, owner=jrandom)
        branch.subscribe(branch.registrant,
            BranchSubscriptionNotificationLevel.FULL,
            BranchSubscriptionDiffSize.WHOLEDIFF,
            CodeReviewNotificationLevel.FULL)
        branch, tree = self.create_branch_and_tree(db_branch=branch)
        tree.branch.nick = 'nicholas'
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit(
            'rev1', rev_id='rev1', timestamp=1000, timezone=0,
            committer='J. Random Hacker <jrandom@example.org>')
        return branch, tree

    def test_getRevisionMessage(self):
        self.useBzrBranches()
        branch, tree = self.makeBranchWithCommit()
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev1', '')
        message = job.getRevisionMessage('rev1', 1)
        self.assertEqual(
        '------------------------------------------------------------\n'
        'revno: 1\n'
        'committer: J. Random Hacker <jrandom@example.org>\n'
        'branch nick: nicholas\n'
        'timestamp: Thu 1970-01-01 00:16:40 +0000\n'
        'message:\n'
        '  rev1\n', message)

    def commitRevision(self, message=None, committer=None,
                       extra_parents=None, rev_id=None,
                       timestamp=None, timezone=None, revprops=None):
        if message is None:
            message = self.LOG
        if committer is None:
            committer = self.factory.getUniqueString()
        if extra_parents is not None:
            self.bzr_tree.add_pending_merge(*extra_parents)
        self.bzr_tree.commit(
            message, committer=committer, rev_id=rev_id,
            timestamp=timestamp, timezone=timezone, allow_pointless=True,
            revprops=revprops)

    def test_email_format(self):
        self.useBzrBranches()
        db_branch, tree = self.create_branch_and_tree()
        first_revision = 'rev-1'
        tree.bzrdir.root_transport.put_bytes('hello.txt', 'Hello World\n')
        tree.add('hello.txt')
        tree.commit(
            rev_id=first_revision, message="Log message",
            committer="Joe Bloggs <joe@example.com>", timestamp=1000000000.0,
            timezone=0)
        tree.bzrdir.root_transport.put_bytes(
            'hello.txt', 'Hello World\n\nFoo Bar\n')
        second_revision = 'rev-2'
        tree.commit(
            rev_id=second_revision, message="Extended contents",
            committer="Joe Bloggs <joe@example.com>", timestamp=1000100000.0,
            timezone=0)
        transaction.commit()
        self.layer.switchDbUser('branchscanner')
        self.updateDBRevisions(db_branch, tree.branch)
        expected = (
            u"-"*60 + '\n'
            "revno: 1" '\n'
            "committer: Joe Bloggs <joe@example.com>" '\n'
            "branch nick: %s" '\n'
            "timestamp: Sun 2001-09-09 01:46:40 +0000" '\n'
            "message:" '\n'
            "  Log message" '\n'
            "added:" '\n'
            "  hello.txt" '\n' % tree.branch.nick)
        job = RevisionsAddedJob.create(db_branch, '', '', '')
        self.assertEqual(
            job.getRevisionMessage(first_revision, 1), expected)

        expected_diff = (
            "=== modified file 'hello.txt'" '\n'
            "--- hello.txt" '\t' "2001-09-09 01:46:40 +0000" '\n'
            "+++ hello.txt" '\t' "2001-09-10 05:33:20 +0000" '\n'
            "@@ -1,1 +1,3 @@" '\n'
            " Hello World" '\n'
            "+" '\n'
            "+Foo Bar" '\n'
            '\n')
        expected_message = (
            u"-"*60 + '\n'
            "revno: 2" '\n'
            "committer: Joe Bloggs <joe@example.com>" '\n'
            "branch nick: %s" '\n'
            "timestamp: Mon 2001-09-10 05:33:20 +0000" '\n'
            "message:" '\n'
            "  Extended contents" '\n'
            "modified:" '\n'
            "  hello.txt" '\n' % tree.branch.nick)
        tree.branch.lock_read()
        tree.branch.unlock()
        message = job.getRevisionMessage(second_revision, 2)
        self.assertEqual(message, expected_message)

    def test_message_encoding(self):
        """Test handling of non-ASCII commit messages."""
        self.useBzrBranches()
        db_branch, tree = self.create_branch_and_tree()
        rev_id = 'rev-1'
        tree.commit(
            rev_id=rev_id, message=u"Non ASCII: \xe9",
            committer=u"Non ASCII: \xed", timestamp=1000000000.0, timezone=0)
        transaction.commit()
        self.layer.switchDbUser('branchscanner')
        self.updateDBRevisions(db_branch, tree.branch)
        job = RevisionsAddedJob.create(db_branch, '', '', '')
        message = job.getRevisionMessage(rev_id, 1)
        # The revision message must be a unicode object.
        expected = (
            u'-' * 60 + '\n'
            u"revno: 1" '\n'
            u"committer: Non ASCII: \xed" '\n'
            u"branch nick: %s" '\n'
            u"timestamp: Sun 2001-09-09 01:46:40 +0000" '\n'
            u"message:" '\n'
            u"  Non ASCII: \xe9" '\n' % tree.branch.nick)
        self.assertEqual(message, expected)

    def test_getMailerForRevision(self):
        self.useBzrBranches()
        branch, tree = self.makeBranchWithCommit()
        revision = tree.branch.repository.get_revision('rev1')
        job = RevisionsAddedJob.create(branch, 'rev1', 'rev1', '')
        mailer = job.getMailerForRevision(revision, 1, True)
        subject = mailer.generateEmail(
            branch.registrant.preferredemail.email, branch.registrant).subject
        self.assertEqual(
            '[Branch ~jrandom/foo/bar] Rev 1: rev1', subject)

    def test_only_nodiff_subscribers_means_no_diff_generated(self):
        self.layer.switchDbUser('launchpad')
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        subscriptions = branch.getSubscriptionsByLevel(
            [BranchSubscriptionNotificationLevel.FULL])
        for s in subscriptions:
            s.max_diff_lines = BranchSubscriptionDiffSize.NODIFF
        job = RevisionsAddedJob.create(branch, '', '', '')
        self.assertFalse(job.generateDiffs())


def test_suite():
    return TestLoader().loadTestsFromName(__name__)
