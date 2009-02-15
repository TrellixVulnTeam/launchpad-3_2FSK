# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import operator
import re
import transaction

from bzrlib.branch import Branch
from bzrlib.errors import NotAMergeDirective, NotBranchError
from bzrlib.merge_directive import MergeDirective
from bzrlib.transport import get_transport
from sqlobject import SQLObjectNotFound

from zope.component import getUtility
from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.interfaces.branch import BranchType, IBranchSet
from canonical.launchpad.interfaces.branchmergeproposal import (
    BranchMergeProposalExists, IBranchMergeProposalGetter,
    ICreateMergeProposalJobSource, UserNotBranchReviewer)
from canonical.launchpad.interfaces.branchnamespace import (
    lookup_branch_namespace, split_unique_name)
from canonical.launchpad.interfaces.codereviewcomment import CodeReviewVote
from canonical.launchpad.interfaces.diff import IStaticDiffSource
from canonical.launchpad.interfaces.mail import (
    IMailHandler, EmailProcessingError)
from canonical.launchpad.interfaces.message import IMessageSet
from canonical.launchpad.mail.commands import (
    EmailCommand, EmailCommandCollection)
from canonical.launchpad.mail.helpers import (
    ensure_not_weakly_authenticated, get_error_message, get_main_body,
    get_person_or_team, IncomingEmailError, parse_commands)
from canonical.launchpad.mail.sendmail import simple_sendmail
from canonical.launchpad.mailnotification import (
    send_process_error_notification)
from canonical.launchpad.webapp import urlparse
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.launchpad.webapp.uri import URI


class BadBranchMergeProposalAddress(Exception):
    """The user-supplied address is not an acceptable value."""

class InvalidBranchMergeProposalAddress(BadBranchMergeProposalAddress):
    """The user-supplied address is not an acceptable value."""

class NonExistantBranchMergeProposalAddress(BadBranchMergeProposalAddress):
    """The BranchMergeProposal specified by the address does not exist."""

class InvalidVoteString(Exception):
    """The user-supplied vote is not an acceptable value."""


class NonLaunchpadTarget(Exception):
    """Target branch is not registered with Launchpad."""


class MissingMergeDirective(Exception):
    """Emailed merge proposal lacks a merge directive"""


class CodeReviewEmailCommandExecutionContext:
    """Passed as the only parameter to each code review email command.

    The execution context is created once for each email and then passed to
    each command object as the execution parameter.  The resulting vote and
    vote tags in the context are used in the final code review comment
    creation.
    """

    def __init__(self, merge_proposal, user, notify_event_listeners=True):
        self.merge_proposal = merge_proposal
        self.user = user
        self.vote = None
        self.vote_tags = None
        self.notify_event_listeners = notify_event_listeners


class CodeReviewEmailCommand(EmailCommand):
    """Commands specific to code reviews."""

    # Some code commands need to happen before others, so we order them.
    sort_order = 1

    def execute(self, context):
        raise NotImplementedError


class VoteEmailCommand(CodeReviewEmailCommand):
    """Record the vote to add to the comment."""

    # Votes should happen first, so set the order lower than
    # status updates.
    sort_order = 0

    _vote_alias = {
        '+1': CodeReviewVote.APPROVE,
        '+0': CodeReviewVote.ABSTAIN,
        '0': CodeReviewVote.ABSTAIN,
        '-0': CodeReviewVote.ABSTAIN,
        '-1': CodeReviewVote.DISAPPROVE,
        'needsfixing': CodeReviewVote.NEEDS_FIXING,
        'needs-fixing': CodeReviewVote.NEEDS_FIXING,
        }

    def execute(self, context):
        """Extract the vote and tags from the args."""
        if len(self.string_args) == 0:
            raise EmailProcessingError(
                get_error_message(
                    'num-arguments-mismatch.txt',
                    command_name='review',
                    num_arguments_expected='one or more',
                    num_arguments_got='0'))

        vote_string = self.string_args[0]
        vote_tag_list = self.string_args[1:]
        try:
            context.vote = CodeReviewVote.items[vote_string.upper()]
        except KeyError:
            # If the word doesn't match, check aliases that we allow.
            context.vote = self._vote_alias.get(vote_string)
            if context.vote is None:
                valid_votes = ', '.join(sorted(
                    v.name.lower() for v in CodeReviewVote.items.items))
                raise EmailProcessingError(
                    get_error_message(
                        'dbschema-command-wrong-argument.txt',
                        command_name='review',
                        arguments=valid_votes,
                        example_argument='needs_fixing'))

        if len(vote_tag_list) > 0:
            context.vote_tags = ' '.join(vote_tag_list)


class UpdateStatusEmailCommand(CodeReviewEmailCommand):
    """Update the status of the merge proposal."""

    _numberOfArguments = 1

    def execute(self, context):
        """Update the status of the merge proposal."""
        # Only accepts approved, and rejected for now.
        self._ensureNumberOfArguments()
        new_status = self.string_args[0].lower()
        # Grab the latest rev_id from the source branch.
        # This is what the browser code does right now.
        rev_id = context.merge_proposal.source_branch.last_scanned_id
        try:
            if new_status in ('approved', 'approve'):
                if context.vote is None:
                    context.vote = CodeReviewVote.APPROVE
                context.merge_proposal.approveBranch(context.user, rev_id)
            elif new_status in ('rejected', 'reject'):
                if context.vote is None:
                    context.vote = CodeReviewVote.DISAPPROVE
                context.merge_proposal.rejectBranch(context.user, rev_id)
            else:
                raise EmailProcessingError(
                    get_error_message(
                        'dbschema-command-wrong-argument.txt',
                        command_name=self.name,
                        arguments='approved, rejected',
                        example_argument='approved'))
        except UserNotBranchReviewer:
            raise EmailProcessingError(
                get_error_message(
                    'user-not-reviewer.txt',
                    command_name=self.name,
                    target=context.merge_proposal.target_branch.bzr_identity))


class AddReviewerEmailCommand(CodeReviewEmailCommand):
    """Add a new reviewer."""

    def execute(self, context):
        if len(self.string_args) == 0:
            raise EmailProcessingError(
                get_error_message(
                    'num-arguments-mismatch.txt',
                    command_name=self.name,
                    num_arguments_expected='one or more',
                    num_arguments_got='0'))

        # Pop the first arg as the reviewer.
        reviewer = get_person_or_team(self.string_args.pop(0))
        if len(self.string_args) > 0:
            review_tags = ' '.join(self.string_args)
        else:
            review_tags = None

        context.merge_proposal.nominateReviewer(
            reviewer, context.user, review_tags,
            _notify_listeners=context.notify_event_listeners)


class CodeEmailCommands(EmailCommandCollection):
    """A colleciton of email commands for code."""

    _commands = {
        'vote': VoteEmailCommand,
        'review': VoteEmailCommand,
        'status': UpdateStatusEmailCommand,
        'reviewer': AddReviewerEmailCommand,
        }

    @classmethod
    def getCommands(klass, message_body):
        """Extract the commands from the message body."""
        if message_body is None:
            return []
        commands = [klass.get(name=name, string_args=args) for
                    name, args in parse_commands(message_body,
                                                 klass._commands.keys())]
        return sorted(commands, key=operator.attrgetter('sort_order'))


class CodeHandler:
    """Mail handler for the code domain."""
    implements(IMailHandler)

    addr_pattern = re.compile(r'(mp\+)([^@]+).*')
    allow_unknown_users = False

    def process(self, mail, email_addr, file_alias):
        """Process an email for the code domain.

        Emails may be converted to CodeReviewComments, and / or
        deferred to jobs to create BranchMergeProposals.
        """
        if email_addr.startswith('merge@'):
            job = getUtility(ICreateMergeProposalJobSource).create(file_alias)
            return True
        else:
            try:
                return self.processComment(mail, email_addr, file_alias)
            except AssertionError:
                body = get_error_message('messagemissingsubject.txt')
                simple_sendmail('merge@code.launchpad.net',
                    [mail.get('from')],
                    'Error Creating Merge Proposal', body)
                return

    def processCommands(self, context, email_body_text):
        """Process the commadns in the email_body_text against the context."""
        commands = CodeEmailCommands.getCommands(email_body_text)

        processing_errors = []

        for command in commands:
            try:
                command.execute(context)
            except EmailProcessingError, error:
                processing_errors.append((error, command))

        if len(processing_errors) > 0:
            errors, commands = zip(*processing_errors)
            raise IncomingEmailError(
                '\n'.join(str(error) for error in errors),
                list(commands))

        return len(commands)

    def processComment(self, mail, email_addr, file_alias):
        """Process an email and create a CodeReviewComment.

        The only mail command understood is 'vote', which takes 'approve',
        'disapprove', or 'abstain' as values.  Specifically, it takes
        any CodeReviewVote item value, case-insensitively.
        :return: True.
        """
        try:
            merge_proposal = self.getBranchMergeProposal(email_addr)
        except BadBranchMergeProposalAddress:
            return False

        user = getUtility(ILaunchBag).user
        context = CodeReviewEmailCommandExecutionContext(merge_proposal, user)
        try:
            email_body_text = get_main_body(mail)
            processed_count = self.processCommands(context, email_body_text)

            # Make sure that the email is in fact signed.
            if processed_count > 0:
                ensure_not_weakly_authenticated(mail, 'code review')

            message = getUtility(IMessageSet).fromEmail(
                mail.parsed_string,
                owner=getUtility(ILaunchBag).user,
                filealias=file_alias,
                parsed_message=mail)
            comment = merge_proposal.createCommentFromMessage(
                message, context.vote, context.vote_tags, mail)

        except IncomingEmailError, error:
            send_process_error_notification(
                str(user.preferredemail.email),
                'Submit Request Failure',
                error.message, mail, error.failing_command)
            transaction.abort()
        return True

    @staticmethod
    def _getReplyAddress(mail):
        """The address to use for automatic replies."""
        return mail.get('Reply-to', mail['From'])

    @classmethod
    def getBranchMergeProposal(klass, email_addr):
        """Return branch merge proposal designated by email_addr.

        Addresses are of the form mp+5@code.launchpad.net, where 5 is the
        database id of the related branch merge proposal.

        The inverse operation is BranchMergeProposal.address.
        """
        match = klass.addr_pattern.match(email_addr)
        if match is None:
            raise InvalidBranchMergeProposalAddress(email_addr)
        try:
            merge_proposal_id = int(match.group(2))
        except ValueError:
            raise InvalidBranchMergeProposalAddress(email_addr)
        getter = getUtility(IBranchMergeProposalGetter)
        try:
            return getter.get(merge_proposal_id)
        except SQLObjectNotFound:
            raise NonExistantBranchMergeProposalAddress(email_addr)

    def _acquireBranchesForProposal(self, md, submitter):
        """Find or create DB Branches from a MergeDirective.

        If the target is not a Launchpad branch, NonLaunchpadTarget will be
        raised.  If the source is not a Launchpad branch, a REMOTE branch will
        be created implicitly, with submitter as its owner/registrant.

        :param md: The `MergeDirective` to get branch URLs from.
        :param submitter: The `Person` who requested that the merge be
            performed.
        :return: source_branch, target_branch
        """
        mp_target = getUtility(IBranchSet).getByUrl(md.target_branch)
        if mp_target is None:
            raise NonLaunchpadTarget()
        if md.bundle is None:
            mp_source = self._getSourceNoBundle(
                md, mp_target, submitter)
        else:
            mp_source = self._getSourceWithBundle(
                md, mp_target, submitter)
        return mp_source, mp_target

    @staticmethod
    def _getNewBranchInfo(url, target, submitter):
        """Return the namespace and basename for a branch.

        If an LP URL is provided, the namespace and basename will match the
        LP URL.

        Otherwise, the target is used to determine the namespace, and the base
        depends on what was supplied.

        If a URL is supplied, its base is used.

        If no URL is supplied, 'merge' is used as the base.

        :param url: The public URL of the source branch, if any.
        :param target: The target branch.
        :param submitter: The person submitting the merge proposal.
        """
        if url is not None:
            branches = getUtility(IBranchSet)
            unique_name = branches.URIToUniqueName(URI(url))
            if unique_name is not None:
                namespace_name, base = split_unique_name(unique_name)
                return lookup_branch_namespace(namespace_name), base
        if url is None:
            basename = 'merge'
        else:
            basename = urlparse(url)[2].split('/')[-1]
        namespace = target.container.getNamespace(submitter)
        return namespace, basename

    def _getNewBranch(self, branch_type, url, target, submitter):
        """Return a new database branch.

        :param branch_type: The type of branch to create.
        :param url: The public location of the branch to create.
        :param product: The product associated with the branch to create.
        :param submitter: The person who requested the merge.
        """
        namespace, basename = self._getNewBranchInfo(url, target, submitter)
        if branch_type == BranchType.REMOTE:
            db_url = url
        else:
            db_url = None
        return namespace.createBranchWithPrefix(
            branch_type, basename, submitter, url=db_url)

    def _getSourceNoBundle(self, md, target, submitter):
        """Get a source branch for a merge directive with no bundle."""
        mp_source = getUtility(IBranchSet).getByUrl(md.source_branch)
        if mp_source is None:
            mp_source = self._getNewBranch(
                BranchType.REMOTE, md.source_branch, target, submitter)
        return mp_source

    def _getSourceWithBundle(self, md, target, submitter):
        """Get a source branch for a merge directive with a bundle."""
        mp_source = None
        if md.source_branch is not None:
            mp_source = getUtility(IBranchSet).getByUrl(md.source_branch)
        if mp_source is None:
            mp_source = self._getNewBranch(
                BranchType.HOSTED, md.source_branch, target,
                submitter)
        assert mp_source.branch_type == BranchType.HOSTED
        try:
            bzr_branch = Branch.open(mp_source.getPullURL())
        except NotBranchError:
            bzr_target = removeSecurityProxy(target).getBzrBranch()
            transport = get_transport(
                mp_source.getPullURL(),
                possible_transports=[bzr_target.bzrdir.root_transport])
            transport.clone('../..').ensure_base()
            transport.clone('..').ensure_base()
            bzrdir = bzr_target.bzrdir.clone_on_transport(transport)
            bzr_branch = bzrdir.open_branch()
        md.install_revisions(bzr_branch.repository)
        bzr_branch.pull(bzr_branch, stop_revision=md.revision_id)
        mp_source.requestMirror()
        return mp_source

    def findMergeDirectiveAndComment(self, message):
        """Extract the comment and Merge Directive from a SignedMessage."""
        body = None
        md = None
        for part in message.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True)
            if part['Content-type'].startswith('text/plain'):
                body = payload
            try:
                md = MergeDirective.from_lines(payload.splitlines(True))
            except NotAMergeDirective:
                pass
            if None not in (body, md):
                return body, md
        else:
            raise MissingMergeDirective()

    def processMergeProposal(self, message):
        """Generate a merge proposal (and comment) from an email message.

        The message is expected to contain a merge directive in one of its
        parts.  Its values are used to generate a BranchMergeProposal.
        If the message has a non-empty body, it is turned into a
        CodeReviewComment.
        """
        submitter = getUtility(ILaunchBag).user
        try:
            comment_text, md = self.findMergeDirectiveAndComment(message)
        except MissingMergeDirective:
            body = get_error_message('missingmergedirective.txt')
            simple_sendmail('merge@code.launchpad.net',
                [message.get('from')],
                'Error Creating Merge Proposal', body)
            return

        try:
            source, target = self._acquireBranchesForProposal(md, submitter)
        except NonLaunchpadTarget:
            body = get_error_message('nonlaunchpadtarget.txt',
                target_branch=md.target_branch)
            simple_sendmail('merge@code.launchpad.net',
                [message.get('from')],
                'Error Creating Merge Proposal', body)
            return

        if md.patch is not None:
            diff_source = getUtility(IStaticDiffSource)
            # XXX: Tim Penhey, 2009-02-12, bug 328271
            # If the branch is private we should probably use the restricted
            # librarian.
            # Using the .txt suffix to allow users to view the file in
            # firefox without firefox trying to get them to download it.
            filename = '%s.diff.txt' % source.name
            review_diff = diff_source.acquireFromText(
                md.base_revision_id, md.revision_id, md.patch,
                filename=filename)
            transaction.commit()
        else:
            review_diff = None

        try:
            bmp = source.addLandingTarget(submitter, target,
                                          needs_review=True,
                                          review_diff=review_diff)

            context = CodeReviewEmailCommandExecutionContext(
                bmp, submitter, notify_event_listeners=False)
            processed_count = self.processCommands(context, comment_text)

            if comment_text.strip() == '':
                comment = None
            else:
                comment = bmp.createComment(
                    submitter, message['Subject'], comment_text,
                    _notify_listeners=False)
            return bmp, comment

        except BranchMergeProposalExists:
            body = get_error_message(
                'branchmergeproposal-exists.txt',
                source_branch=source.bzr_identity,
                target_branch=target.bzr_identity)
            simple_sendmail('merge@code.launchpad.net',
                [message.get('from')],
                'Error Creating Merge Proposal', body)
            transaction.abort()
        except IncomingEmailError, error:
            send_process_error_notification(
                str(submitter.preferredemail.email),
                'Submit Request Failure',
                error.message, comment_text, error.failing_command)
            transaction.abort()

