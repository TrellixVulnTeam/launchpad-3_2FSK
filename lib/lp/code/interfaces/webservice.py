# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice."""

# The exceptions are imported so that they can produce the special
# status code defined by webservice_error when they are raised.
from lp.code.errors import (
    BranchMergeProposalExists, CodeImportAlreadyRunning,
    CodeImportNotInReviewedState)
from lp.code.interfaces.branch import (
    IBranch, IBranchSet, BranchCreatorNotMemberOfOwnerTeam,
    BranchCreatorNotOwner, BranchExists)
from lp.code.interfaces.branchmergeproposal import IBranchMergeProposal
from lp.code.interfaces.branchsubscription import IBranchSubscription
from lp.code.interfaces.codeimport import ICodeImport
from lp.code.interfaces.codereviewcomment import ICodeReviewComment
from lp.code.interfaces.codereviewvote import ICodeReviewVoteReference
from lp.code.interfaces.diff import IDiff, IPreviewDiff, IStaticDiff
