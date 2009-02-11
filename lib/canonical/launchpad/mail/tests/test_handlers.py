# Copyright 2005, 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from textwrap import dedent
import transaction
import unittest

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib import errors as bzr_errors
from bzrlib.transport import get_transport
from canonical.database.constants import UTC_NOW
from zope.component import getUtility
from zope.security.management import setSecurityPolicy
from zope.security.proxy import removeSecurityProxy
from zope.testing.doctest import DocTestSuite

from canonical.config import config
from canonical.codehosting.jobs import JobRunner
from canonical.launchpad.interfaces import (
    BranchSubscriptionNotificationLevel, BranchType,
    CodeReviewNotificationLevel, CodeReviewVote, IBranchSet)
from canonical.launchpad.interfaces.branchmergeproposal import (
    BranchMergeProposalStatus)
from canonical.launchpad.database import MessageSet
from canonical.launchpad.database.branchmergeproposal import (
    CreateMergeProposalJob)
from canonical.launchpad.interfaces.mail import EmailProcessingError
from canonical.launchpad.mail.codehandler import (
    AddReviewerEmailCommand, CodeEmailCommands, CodeHandler,
    CodeReviewEmailCommandExecutionContext,
    InvalidBranchMergeProposalAddress,
    MissingMergeDirective, NonLaunchpadTarget,
    UpdateStatusEmailCommand, VoteEmailCommand)
from canonical.launchpad.mail.commands import BugEmailCommand
from canonical.launchpad.mail.handlers import (
    mail_handlers, MaloneHandler)
from canonical.launchpad.testing import (
    login, login_person, TestCase, TestCaseWithFactory)
from canonical.launchpad.tests.mail_helpers import pop_notifications
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.authorization import LaunchpadSecurityPolicy
from canonical.testing import LaunchpadFunctionalLayer, LaunchpadZopelessLayer


class TestGetCodeEmailCommands(TestCase):
    """Test CodeEmailCommands.getCommands."""

    def test_no_message(self):
        # Null in, empty list out.
        self.assertEqual([], CodeEmailCommands.getCommands(None))

    def test_vote_command(self):
        # Check that the vote command is correctly created.
        [command] = CodeEmailCommands.getCommands(" vote approve tag me")
        self.assertIsInstance(command, VoteEmailCommand)
        self.assertEqual('vote', command.name)
        self.assertEqual(['approve', 'tag', 'me'], command.string_args)

    def test_review_as_vote_command(self):
        # Check that the vote command is correctly created.
        [command] = CodeEmailCommands.getCommands(" review approve tag me")
        self.assertIsInstance(command, VoteEmailCommand)
        self.assertEqual('review', command.name)
        self.assertEqual(['approve', 'tag', 'me'], command.string_args)

    def test_status_command(self):
        # Check that the update status command is correctly created.
        [command] = CodeEmailCommands.getCommands(" status approved")
        self.assertIsInstance(command, UpdateStatusEmailCommand)
        self.assertEqual('status', command.name)
        self.assertEqual(['approved'], command.string_args)

    def test_reviewer_command(self):
        # Check that the add review command is correctly created.
        [command] = CodeEmailCommands.getCommands(
            " reviewer test@canonical.com db")
        self.assertIsInstance(command, AddReviewerEmailCommand)
        self.assertEqual('reviewer', command.name)
        self.assertEqual(['test@canonical.com', 'db'], command.string_args)

    def test_ignored_commands(self):
        # Check that other "commands" are not created.
        self.assertEqual([], CodeEmailCommands.getCommands(
            " not-a-command\n spam"))

    def test_vote_commands_come_first(self):
        # Vote commands come before either status or reviewer commands.
        message_body = """
            status approved
            vote approve db
            """
        vote_command, status_command = CodeEmailCommands.getCommands(
            message_body)
        self.assertIsInstance(vote_command, VoteEmailCommand)
        self.assertIsInstance(status_command, UpdateStatusEmailCommand)

        message_body = """
            reviewer foo.bar
            vote reject
            """
        vote_command, reviewer_command = CodeEmailCommands.getCommands(
            message_body)

        self.assertIsInstance(vote_command, VoteEmailCommand)
        self.assertIsInstance(reviewer_command, AddReviewerEmailCommand)


class TestCodeHandler(TestCaseWithFactory):
    """Test the code email hander."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')
        self.code_handler = CodeHandler()
        self._old_policy = setSecurityPolicy(LaunchpadSecurityPolicy)

    def tearDown(self):
        setSecurityPolicy(self._old_policy)

    def switchDbUser(self, user):
        """Commit the transactionand switch to the new user."""
        transaction.commit()
        LaunchpadZopelessLayer.switchDbUser(user)

    def test_get(self):
        handler = mail_handlers.get(config.launchpad.code_domain)
        self.assertIsInstance(handler, CodeHandler)

    def test_process(self):
        """Processing an email creates an appropriate CodeReviewComment."""
        mail = self.factory.makeSignedMessage('<my-id>')
        bmp = self.factory.makeBranchMergeProposal()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.assertTrue(self.code_handler.process(
            mail, email_addr, None), "Succeeded, but didn't return True")
        # if the message has not been created, this raises SQLObjectNotFound
        message = MessageSet().get('<my-id>')

    def test_processBadAddress(self):
        """When a bad address is supplied, it returns False."""
        mail = self.factory.makeSignedMessage('<my-id>')
        self.switchDbUser(config.processmail.dbuser)
        self.assertFalse(self.code_handler.process(mail,
            'foo@code.launchpad.dev', None))

    def test_processNonExistantAddress(self):
        """When a non-existant address is supplied, it returns False."""
        mail = self.factory.makeSignedMessage('<my-id>')
        self.switchDbUser(config.processmail.dbuser)
        self.assertFalse(self.code_handler.process(mail,
            'mp+0@code.launchpad.dev', None))

    def test_processBadVote(self):
        """process handles bad votes properly."""
        mail = self.factory.makeSignedMessage(body=' vote badvalue')
        # Make sure that the correct user principal is there.
        login(mail['From'])
        bmp = self.factory.makeBranchMergeProposal()
        # Remove the notifications sent about the new proposal.
        pop_notifications()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.assertTrue(self.code_handler.process(
            mail, email_addr, None), "Didn't return True")
        notification = pop_notifications()[0]
        self.assertEqual('Submit Request Failure', notification['subject'])
        # The returned message is a multipart message, the first part is
        # the message, and the second is the original message.
        message, original = notification.get_payload()
        self.assertEqual(dedent("""\
        An error occurred while processing a mail you sent to Launchpad's email
        interface.

        Failing command:
            vote badvalue

        Error message:

        The 'review' command expects any of the following arguments:
        abstain, approve, disapprove, needs_fixing, resubmit

        For example:

            review needs_fixing


        -- 
        For more information about using Launchpad by e-mail, see
        https://help.launchpad.net/EmailInterface
        or send an email to help@launchpad.net"""),
                                message.get_payload(decode=True))
        self.assertEqual(mail['From'], notification['To'])

    def test_getReplyAddress(self):
        """getReplyAddress should return From or Reply-to address."""
        mail = self.factory.makeSignedMessage()
        self.switchDbUser(config.processmail.dbuser)
        self.assertEqual(
            mail['From'], self.code_handler._getReplyAddress(mail))
        mail['Reply-to'] = self.factory.getUniqueEmailAddress()
        self.assertEqual(
            mail['Reply-to'], self.code_handler._getReplyAddress(mail))

    def test_processVote(self):
        """Process respects the vote command."""
        mail = self.factory.makeSignedMessage(body=' vote Abstain EBAILIWICK')
        bmp = self.factory.makeBranchMergeProposal()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.code_handler.process(mail, email_addr, None)
        self.assertEqual(CodeReviewVote.ABSTAIN, bmp.all_comments[0].vote)
        self.assertEqual('ebailiwick', bmp.all_comments[0].vote_tag)

    def test_processVoteColon(self):
        """Process respects the vote: command."""
        mail = self.factory.makeSignedMessage(
            body=' vote: Abstain EBAILIWICK')
        bmp = self.factory.makeBranchMergeProposal()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.code_handler.process(mail, email_addr, None)
        self.assertEqual(CodeReviewVote.ABSTAIN, bmp.all_comments[0].vote)
        self.assertEqual('ebailiwick', bmp.all_comments[0].vote_tag)

    def test_processReview(self):
        """Process respects the review command."""
        mail = self.factory.makeSignedMessage(body=' review Abstain ROAR!')
        bmp = self.factory.makeBranchMergeProposal()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.code_handler.process(mail, email_addr, None)
        self.assertEqual(CodeReviewVote.ABSTAIN, bmp.all_comments[0].vote)
        self.assertEqual('roar!', bmp.all_comments[0].vote_tag)

    def test_processReviewColon(self):
        """Process respects the review: command."""
        mail = self.factory.makeSignedMessage(body=' review: Abstain ROAR!')
        bmp = self.factory.makeBranchMergeProposal()
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.code_handler.process(mail, email_addr, None)
        self.assertEqual(CodeReviewVote.ABSTAIN, bmp.all_comments[0].vote)
        self.assertEqual('roar!', bmp.all_comments[0].vote_tag)

    def test_processWithExistingVote(self):
        """Process respects the vote command."""
        mail = self.factory.makeSignedMessage(body=' vote Abstain EBAILIWICK')
        bmp = self.factory.makeBranchMergeProposal()
        sender = self.factory.makePerson()
        bmp.nominateReviewer(sender, bmp.registrant)
        email_addr = bmp.address
        [vote] = list(bmp.votes)
        self.assertEqual(sender, vote.reviewer)
        self.assertTrue(vote.comment is None)
        self.switchDbUser(config.processmail.dbuser)
        # Login the sender as they are set as the message owner.
        login_person(sender)
        self.code_handler.process(mail, email_addr, None)
        comment = bmp.all_comments[0]
        self.assertEqual(CodeReviewVote.ABSTAIN, comment.vote)
        self.assertEqual('ebailiwick', comment.vote_tag)
        [vote] = list(bmp.votes)
        self.assertEqual(sender, vote.reviewer)
        self.assertEqual(comment, vote.comment)

    def test_processSendsMail(self):
        """Processing mail causes mail to be sent."""
        mail = self.factory.makeSignedMessage(
            body=' vote Abstain EBAILIWICK', subject='subject')
        bmp = self.factory.makeBranchMergeProposal()
        # Pop the notifications generated by the new proposal.
        pop_notifications()
        subscriber = self.factory.makePerson()
        bmp.source_branch.subscribe(
            subscriber, BranchSubscriptionNotificationLevel.NOEMAIL, None,
            CodeReviewNotificationLevel.FULL)
        email_addr = bmp.address
        self.switchDbUser(config.processmail.dbuser)
        self.code_handler.process(mail, email_addr, None)
        notification = pop_notifications()[0]
        self.assertEqual('subject', notification['Subject'])
        expected_body = ('Review: Abstain ebailiwick\n'
                         ' vote Abstain EBAILIWICK\n'
                         '-- \n'
                         '%s\n'
                         'You are subscribed to branch %s.' %
                         (canonical_url(bmp), bmp.source_branch.bzr_identity))
        self.assertEqual(expected_body, notification.get_payload(decode=True))

    def test_getBranchMergeProposal(self):
        """The correct BranchMergeProposal is returned for the address."""
        bmp = self.factory.makeBranchMergeProposal()
        self.switchDbUser(config.processmail.dbuser)
        bmp2 = self.code_handler.getBranchMergeProposal(bmp.address)
        self.assertEqual(bmp, bmp2)

    def test_getBranchMergeProposalInvalid(self):
        """InvalidBranchMergeProposalAddress is raised if appropriate."""
        self.switchDbUser(config.processmail.dbuser)
        self.assertRaises(InvalidBranchMergeProposalAddress,
                          self.code_handler.getBranchMergeProposal, '')
        self.assertRaises(InvalidBranchMergeProposalAddress,
                          self.code_handler.getBranchMergeProposal, 'mp+abc@')

    def test_acquireBranchesForProposal(self):
        """Ensure CodeHandler._acquireBranchesForProposal works."""
        target_branch = self.factory.makeAnyBranch()
        source_branch = self.factory.makeAnyBranch()
        md = self.factory.makeMergeDirective(source_branch, target_branch)
        submitter = self.factory.makePerson()
        self.switchDbUser(config.processmail.dbuser)
        mp_source, mp_target = self.code_handler._acquireBranchesForProposal(
            md, submitter)
        self.assertEqual(mp_source, source_branch)
        self.assertEqual(mp_target, target_branch)
        transaction.commit()

    def test_acquireBranchesForProposalRemoteTarget(self):
        """CodeHandler._acquireBranchesForProposal fails on remote targets."""
        source_branch = self.factory.makeAnyBranch()
        md = self.factory.makeMergeDirective(
            source_branch, target_branch_url='http://example.com')
        submitter = self.factory.makePerson()
        self.switchDbUser(config.processmail.dbuser)
        self.assertRaises(
            NonLaunchpadTarget, self.code_handler._acquireBranchesForProposal,
            md, submitter)
        transaction.commit()

    def test_acquireBranchesForProposalRemoteSource(self):
        """CodeHandler._acquireBranchesForProposal allows remote sources.

        If there's no existing remote branch, it creates one, using
        the suffix of the url as a branch name seed.
        """
        target_branch = self.factory.makeProductBranch()
        source_branch_url = 'http://example.com/suffix'
        md = self.factory.makeMergeDirective(
            source_branch_url=source_branch_url, target_branch=target_branch)
        branches = getUtility(IBranchSet)
        self.assertIs(None, branches.getByUrl(source_branch_url))
        submitter = self.factory.makePerson()
        self.switchDbUser(config.processmail.dbuser)
        mp_source, mp_target = self.code_handler._acquireBranchesForProposal(
            md, submitter)
        self.assertEqual(mp_target, target_branch)
        self.assertIsNot(None, mp_source)
        self.assertEqual(mp_source, branches.getByUrl(source_branch_url))
        self.assertEqual(BranchType.REMOTE, mp_source.branch_type)
        self.assertEqual(mp_target.product, mp_source.product)
        self.assertEqual('suffix', mp_source.name)
        transaction.commit()

    def test_acquireBranchesForProposalRemoteSourceDupeName(self):
        """CodeHandler._acquireBranchesForProposal creates names safely.

        When creating a new branch, it uses the suffix of the url as a branch
        name seed.  If there is already a branch with that name, it appends
        a numeric suffix.
        """
        target_branch = self.factory.makeProductBranch()
        source_branch_url = 'http://example.com/suffix'
        md = self.factory.makeMergeDirective(
            source_branch_url=source_branch_url, target_branch=target_branch)
        branches = getUtility(IBranchSet)
        submitter = self.factory.makePerson()
        duplicate_branch = self.factory.makeProductBranch(
            product=target_branch.product, name='suffix', owner=submitter)
        self.switchDbUser(config.processmail.dbuser)
        mp_source, mp_target = self.code_handler._acquireBranchesForProposal(
            md, submitter)
        self.assertEqual('suffix-1', mp_source.name)
        transaction.commit()

    def test_findMergeDirectiveAndComment(self):
        """findMergeDirectiveAndComment works."""
        md = self.factory.makeMergeDirective()
        message = self.factory.makeSignedMessage(
            body='Hi!\n', attachment_contents=''.join(md.to_lines()),
            force_transfer_encoding=True)
        code_handler = CodeHandler()
        self.switchDbUser(config.processmail.dbuser)
        comment, md2 = code_handler.findMergeDirectiveAndComment(message)
        self.assertEqual('Hi!\n', comment)
        self.assertEqual(md.revision_id, md2.revision_id)
        self.assertEqual(md.target_branch, md2.target_branch)
        transaction.commit()

    def test_findMergeDirectiveAndCommentEmptyBody(self):
        """findMergeDirectiveAndComment handles empty message bodies.

        Empty message bodies are returned verbatim.
        """
        md = self.factory.makeMergeDirective()
        message = self.factory.makeSignedMessage(
            body='', attachment_contents=''.join(md.to_lines()))
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        comment, md2 = code_handler.findMergeDirectiveAndComment(message)
        self.assertEqual('', comment)
        transaction.commit()

    def test_findMergeDirectiveAndCommentNoMergeDirective(self):
        """findMergeDirectiveAndComment handles missing merge directives.

        MissingMergeDirective is raised when no merge directive is present.
        """
        md = self.factory.makeMergeDirective()
        message = self.factory.makeSignedMessage(body='Hi!\n')
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        self.assertRaises(MissingMergeDirective,
            code_handler.findMergeDirectiveAndComment, message)
        transaction.commit()

    def test_processMergeProposal(self):
        """processMergeProposal creates a merge proposal and comment."""
        message, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail())
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        bmp, comment = code_handler.processMergeProposal(message)
        self.assertEqual(source, bmp.source_branch)
        self.assertEqual(target, bmp.target_branch)
        self.assertEqual('booga', bmp.review_diff.diff.text)
        self.assertEqual('Hi!\n', comment.message.text_contents)
        self.assertEqual('My subject', comment.message.subject)
        transaction.commit()

    def test_processMergeProposalEmptyMessage(self):
        """processMergeProposal handles empty message bodies.

        Messages with empty bodies produce merge proposals only, not
        comments.
        """
        message, file_alias, source_branch, target_branch = (
            self.factory.makeMergeDirectiveEmail(body=' '))
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        bmp, comment = code_handler.processMergeProposal(message)
        self.assertEqual(source_branch, bmp.source_branch)
        self.assertEqual(target_branch, bmp.target_branch)
        self.assertIs(None, comment)
        self.assertEqual(0, bmp.all_comments.count())
        transaction.commit()

    def test_processWithMergeDirectiveEmail(self):
        """process creates a merge proposal from a merge directive email."""
        message, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail())
        # Ensure the message is stored in the librarian.
        # mail.incoming.handleMail also explicitly does this.
        transaction.commit()
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        self.assertEqual(0, source.landing_targets.count())
        code_handler.process(message, 'merge@code.launchpad.net', file_alias)
        JobRunner.fromReady(CreateMergeProposalJob).runAll()
        self.assertEqual(target, source.landing_targets[0].target_branch)
        # ensure the DB operations violate no constraints.
        transaction.commit()

    def test_processMergeProposalExists(self):
        """processMergeProposal raises BranchMergeProposalExists

        If there is already a merge proposal with the same target and source
        branches of the merge directive, an email is sent to the user.
        """
        message, file_alias, source, target = (
            self.factory.makeMergeDirectiveEmail())
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        bmp, comment = code_handler.processMergeProposal(message)
        _unused = pop_notifications()
        transaction.commit()
        _unused = code_handler.processMergeProposal(message)
        [notification] = pop_notifications()
        self.assertEqual(
            notification['Subject'], 'Error Creating Merge Proposal')
        self.assertEqual(
            notification.get_payload(decode=True),
            'The branch %s is already proposed for merging into %s.\n\n' % (
                source.bzr_identity, target.bzr_identity))
        self.assertEqual(notification['to'], message['from'])

    def test_processMissingMergeDirective(self):
        """process sends an email if the original email lacks an attachment.
        """
        message = self.factory.makeSignedMessage(body='A body',
            subject='A subject', attachment_contents='')
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        code_handler.processMergeProposal(message)
        transaction.commit()
        [notification] = pop_notifications()

        self.assertEqual(
            notification['Subject'], 'Error Creating Merge Proposal')
        self.assertEqual(
            notification.get_payload(),
            'Your email did not contain a merge directive. Please resend '
            'your email with\nthe merge directive attached.\n'
            )
        self.assertEqual(notification['to'],
            message['from'])

    def test_processMergeDirectiveWithBundle(self):
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree()
        tree.branch.set_public_branch(branch.bzr_identity)
        tree.commit('rev1')
        source = tree.bzrdir.sprout('source').open_workingtree()
        source.commit('rev2')
        message = self.factory.makeBundleMergeDirectiveEmail(
            source.branch, branch)
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        bmp, comment = code_handler.processMergeProposal(message)
        self.assertRaises(
            bzr_errors.NotBranchError, Branch.open,
            bmp.source_branch.warehouse_url)
        local_source = Branch.open(bmp.source_branch.getPullURL())
        self.assertEqual(
            source.branch.last_revision(), local_source.last_revision())
        self.assertIsNot(None, bmp.source_branch.next_mirror_time)

    def mirror(self, db_branch, bzr_branch):
        transport = get_transport(db_branch.warehouse_url)
        transport.clone('../..').ensure_base()
        transport.clone('..').ensure_base()
        lp_mirror = BzrDir.create_branch_convenience(db_branch.warehouse_url)
        lp_mirror.pull(bzr_branch)

    def test_processMergeDirectiveWithBundleExistingBranch(self):
        self.useBzrBranches()
        branch, tree = self.create_branch_and_tree('target')
        tree.branch.set_public_branch(branch.bzr_identity)
        tree.commit('rev1')
        lp_source, lp_source_tree = self.create_branch_and_tree(
            'lpsource', branch.product, hosted=True)
        self.assertIs(lp_source.next_mirror_time, None)
        lp_source_tree.pull(tree.branch)
        lp_source_tree.commit('rev2', rev_id='rev2')
        self.mirror(lp_source, lp_source_tree.branch)
        source = lp_source_tree.bzrdir.sprout('source').open_workingtree()
        source.commit('rev3', rev_id='rev3')
        source.branch.set_public_branch(lp_source.bzr_identity)
        message = self.factory.makeBundleMergeDirectiveEmail(
            source.branch, branch)
        self.switchDbUser(config.processmail.dbuser)
        code_handler = CodeHandler()
        bmp, comment = code_handler.processMergeProposal(message)
        self.assertEqual(lp_source, bmp.source_branch)
        self.assertIsNot(None, lp_source.next_mirror_time)
        mirror = removeSecurityProxy(bmp.source_branch).getBzrBranch()
        self.assertEqual('rev2', mirror.last_revision())
        hosted = Branch.open(bmp.source_branch.getPullURL())
        self.assertEqual('rev3', hosted.last_revision())


class TestVoteEmailCommand(TestCase):
    """Test the vote and tag processing of the VoteEmailCommand."""

    # We don't need no stinking layer.

    def setUp(self):
        class FakeExecutionContext:
            vote = None
            vote_tags = None
        self.context = FakeExecutionContext()

    def test_getVoteNoArgs(self):
        """getVote returns None, None when no arguments are supplied."""
        command = VoteEmailCommand('vote', [])
        self.assertRaises(EmailProcessingError, command.execute, self.context)

    def assertVoteAndTag(self, expected_vote, expected_tag, command):
        """Execute the command and check the resulting vote and tag."""
        command.execute(self.context)
        self.assertEqual(expected_vote, self.context.vote)
        if expected_tag is None:
            self.assertIs(None, self.context.vote_tags)
        else:
            self.assertEqual(expected_tag, self.context.vote_tags)

    def test_getVoteOneArg(self):
        """getVote returns vote, None when only a vote is supplied."""
        command = VoteEmailCommand('vote', ['apPRoVe'])
        self.assertVoteAndTag(CodeReviewVote.APPROVE, None, command)

    def test_getVoteDisapprove(self):
        """getVote returns disapprove when it is specified."""
        command = VoteEmailCommand('vote', ['dIsAppRoVe'])
        self.assertVoteAndTag(CodeReviewVote.DISAPPROVE, None, command)

    def test_getVoteBadValue(self):
        """getVote returns vote, None when only a vote is supplied."""
        command = VoteEmailCommand('vote', ['badvalue'])
        self.assertRaises(EmailProcessingError, command.execute, self.context)

    def test_getVoteThreeArg(self):
        """getVote returns vote, vote_tag when both are supplied."""
        command = VoteEmailCommand('vote', ['apPRoVe', 'DB', 'TAG'])
        self.assertVoteAndTag(CodeReviewVote.APPROVE, 'DB TAG', command)

    def test_getVoteApproveAlias(self):
        """Test the approve alias of +1."""
        command = VoteEmailCommand('vote', ['+1'])
        self.assertVoteAndTag(CodeReviewVote.APPROVE, None, command)

    def test_getVoteAbstainAlias(self):
        """Test the abstain alias of 0."""
        command = VoteEmailCommand('vote', ['0'])
        self.assertVoteAndTag(CodeReviewVote.ABSTAIN, None, command)
        command = VoteEmailCommand('vote', ['+0'])
        self.assertVoteAndTag(CodeReviewVote.ABSTAIN, None, command)
        command = VoteEmailCommand('vote', ['-0'])
        self.assertVoteAndTag(CodeReviewVote.ABSTAIN, None, command)

    def test_getVoteDisapproveAlias(self):
        """Test the disapprove alias of -1."""
        command = VoteEmailCommand('vote', ['-1'])
        self.assertVoteAndTag(CodeReviewVote.DISAPPROVE, None, command)

    def test_getVoteNeedsFixingAlias(self):
        """Test the needs_fixing aliases of needsfixing and needs-fixing."""
        command = VoteEmailCommand('vote', ['needsfixing'])
        self.assertVoteAndTag(CodeReviewVote.NEEDS_FIXING, None, command)
        command = VoteEmailCommand('vote', ['needs-fixing'])
        self.assertVoteAndTag(CodeReviewVote.NEEDS_FIXING, None, command)


class TestUpdateStatusEmailCommand(TestCaseWithFactory):
    """Test the UpdateStatusEmailCommand."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')
        self._old_policy = setSecurityPolicy(LaunchpadSecurityPolicy)
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        # Default the user to be the target branch owner, so they are
        # authorised to update the status.
        self.context = CodeReviewEmailCommandExecutionContext(
            self.merge_proposal, self.merge_proposal.target_branch.owner)
        transaction.commit()
        self.layer.switchDbUser(config.processmail.dbuser)

    def tearDown(self):
        setSecurityPolicy(self._old_policy)

    def test_numberOfArguments(self):
        # The command needs one and only one arg.
        command = UpdateStatusEmailCommand('status', [])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        self.assertEqual(
            "The 'status' argument expects 1 argument(s). It got 0.\n",
            str(error))
        command = UpdateStatusEmailCommand('status', ['approve', 'spam'])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        self.assertEqual(
            "The 'status' argument expects 1 argument(s). It got 2.\n",
            str(error))

    def test_status_approved(self):
        # Test that approve sets the status of the merge proposal.
        self.assertNotEqual(
            BranchMergeProposalStatus.CODE_APPROVED,
            self.merge_proposal.queue_status)
        command = UpdateStatusEmailCommand('status', ['approved'])
        command.execute(self.context)
        self.assertEqual(
            BranchMergeProposalStatus.CODE_APPROVED,
            self.merge_proposal.queue_status)
        # The vote is also set if it wasn't before.
        self.assertEqual(CodeReviewVote.APPROVE, self.context.vote)
        # Commit the transaction to check database permissions.
        transaction.commit()

    def test_status_approved_doesnt_override_vote(self):
        # Test that approve sets the status of the merge proposal.
        self.context.vote = CodeReviewVote.NEEDS_FIXING
        command = UpdateStatusEmailCommand('status', ['approved'])
        command.execute(self.context)
        self.assertEqual(
            BranchMergeProposalStatus.CODE_APPROVED,
            self.merge_proposal.queue_status)
        self.assertEqual(CodeReviewVote.NEEDS_FIXING, self.context.vote)

    def test_status_rejected(self):
        # Test that rejected sets the status of the merge proposal.
        self.assertNotEqual(
            BranchMergeProposalStatus.REJECTED,
            self.merge_proposal.queue_status)
        command = UpdateStatusEmailCommand('status', ['rejected'])
        command.execute(self.context)
        self.assertEqual(
            BranchMergeProposalStatus.REJECTED,
            self.merge_proposal.queue_status)
        # The vote is also set if it wasn't before.
        self.assertEqual(CodeReviewVote.DISAPPROVE, self.context.vote)
        # Commit the transaction to check database permissions.
        transaction.commit()

    def test_status_rejected_doesnt_override_vote(self):
        # Test that approve sets the status of the merge proposal.
        self.context.vote = CodeReviewVote.NEEDS_FIXING
        command = UpdateStatusEmailCommand('status', ['rejected'])
        command.execute(self.context)
        self.assertEqual(
            BranchMergeProposalStatus.REJECTED,
            self.merge_proposal.queue_status)
        self.assertEqual(CodeReviewVote.NEEDS_FIXING, self.context.vote)

    def test_unknown_status(self):
        # Unknown status values will cause an email response to the user.
        command = UpdateStatusEmailCommand('status', ['bob'])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        self.assertEqual(
            "The 'status' command expects any of the following arguments:\n"
            "approved, rejected\n\n"
            "For example:\n\n"
            "    status approved\n",
            str(error))

    def test_not_a_reviewer(self):
        # If the user is not a reviewer, they can not update the status.
        self.context.user = self.context.merge_proposal.registrant
        command = UpdateStatusEmailCommand('status', ['approve'])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        target = self.merge_proposal.target_branch.bzr_identity
        self.assertEqual(
            "You are not a reviewer for the branch %s.\n" % target,
            str(error))


class TestAddReviewerEmailCommand(TestCaseWithFactory):
    """Test the AddReviewerEmailCommand."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user='test@canonical.com')
        self._old_policy = setSecurityPolicy(LaunchpadSecurityPolicy)
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        # Default the user to be the target branch owner, so they are
        # authorised to update the status.
        self.context = CodeReviewEmailCommandExecutionContext(
            self.merge_proposal, self.merge_proposal.target_branch.owner)
        self.reviewer = self.factory.makePerson()
        transaction.commit()
        self.layer.switchDbUser(config.processmail.dbuser)

    def tearDown(self):
        setSecurityPolicy(self._old_policy)

    def test_numberOfArguments(self):
        # The command needs at least one arg.
        command = AddReviewerEmailCommand('reviewer', [])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        self.assertEqual(
            "The 'reviewer' argument expects one or more argument(s). "
            "It got 0.\n",
            str(error))

    def test_add_reviewer(self):
        # The simple case is to add a reviewer with no tags.
        command = AddReviewerEmailCommand('reviewer', [self.reviewer.name])
        command.execute(self.context)
        [vote_ref] = list(self.context.merge_proposal.votes)
        self.assertEqual(self.reviewer, vote_ref.reviewer)
        self.assertEqual(self.context.user, vote_ref.registrant)
        self.assertIs(None, vote_ref.review_type)
        self.assertIs(None, vote_ref.comment)

    def test_add_reviewer_with_tags(self):
        # The simple case is to add a reviewer with no tags.
        command = AddReviewerEmailCommand(
            'reviewer', [self.reviewer.name, 'DB', 'Foo'])
        command.execute(self.context)
        [vote_ref] = list(self.context.merge_proposal.votes)
        self.assertEqual(self.reviewer, vote_ref.reviewer)
        self.assertEqual(self.context.user, vote_ref.registrant)
        self.assertEqual('db foo', vote_ref.review_type)
        self.assertIs(None, vote_ref.comment)

    def test_unknown_reviewer(self):
        # An unknown user raises.
        command = AddReviewerEmailCommand('reviewer', ['unknown@example.com'])
        error = self.assertRaises(
            EmailProcessingError, command.execute, self.context)
        self.assertEqual(
            "There's no such person with the specified name or email: "
            "unknown@example.com\n",
            str(error))


class TestMaloneHandler(TestCaseWithFactory):
    """Test that the Malone/bugs handler works."""

    layer = LaunchpadFunctionalLayer

    def test_getCommandsEmpty(self):
        """getCommands returns an empty list for messages with no command."""
        message = self.factory.makeSignedMessage()
        handler = MaloneHandler()
        self.assertEqual([], handler.getCommands(message))

    def test_getCommandsBug(self):
        """getCommands returns a reasonable list if commands are specified."""
        message = self.factory.makeSignedMessage(body=' bug foo')
        handler = MaloneHandler()
        commands = handler.getCommands(message)
        self.assertEqual(1, len(commands))
        self.assertTrue(isinstance(commands[0], BugEmailCommand))
        self.assertEqual('bug', commands[0].name)
        self.assertEqual(['foo'], commands[0].string_args)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTests(DocTestSuite('canonical.launchpad.mail.handlers'))
    suite.addTests(unittest.TestLoader().loadTestsFromName(__name__))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
