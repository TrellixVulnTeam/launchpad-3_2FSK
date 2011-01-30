# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Errors used in the lp/code modules."""

__metaclass__ = type
__all__ = [
    'BadBranchMergeProposalSearchContext',
    'BadStateTransition',
    'BranchCannotBePrivate',
    'BranchCannotBePublic',
    'BranchCreationException',
    'BranchCreationForbidden',
    'BranchCreatorNotMemberOfOwnerTeam',
    'BranchCreatorNotOwner',
    'BranchExists',
    'BranchTargetError',
    'BranchTypeError',
    'BuildAlreadyPending',
    'BuildNotAllowedForDistro',
    'BranchMergeProposalExists',
    'CannotDeleteBranch',
    'CannotHaveLinkedBranch',
    'CodeImportAlreadyRequested',
    'CodeImportAlreadyRunning',
    'CodeImportNotInReviewedState',
    'ClaimReviewFailed',
    'InvalidBranchMergeProposal',
    'InvalidMergeQueueConfig',
    'InvalidNamespace',
    'NoLinkedBranch',
    'NoSuchBranch',
    'PrivateBranchRecipe',
    'ReviewNotPending',
    'TooManyBuilds',
    'TooNewRecipeFormat',
    'UnknownBranchTypeError',
    'UserHasExistingReview',
    'UserNotBranchReviewer',
    'WrongBranchMergeProposal',
]

from bzrlib.plugins.builder.recipe import RecipeParseError
from lazr.restful.declarations import (
    error_status,
    webservice_error,
    )

from lp.app.errors import NameLookupFailed

# Annotate the RecipeParseError's with a 400 webservice status.
error_status(400)(RecipeParseError)


class BadBranchMergeProposalSearchContext(Exception):
    """The context is not valid for a branch merge proposal search."""


class BadStateTransition(Exception):
    """The user requested a state transition that is not possible."""


class BranchCreationException(Exception):
    """Base class for branch creation exceptions."""


class BranchExists(BranchCreationException):
    """Raised when creating a branch that already exists."""

    webservice_error(400)

    def __init__(self, existing_branch):
        # XXX: TimPenhey 2009-07-12 bug=405214: This error
        # message logic is incorrect, but the exact text is being tested
        # in branch-xmlrpc.txt.
        params = {'name': existing_branch.name}
        if existing_branch.product is None:
            params['maybe_junk'] = 'junk '
            params['context'] = existing_branch.owner.name
        else:
            params['maybe_junk'] = ''
            params['context'] = '%s in %s' % (
                existing_branch.owner.name, existing_branch.product.name)
        message = (
            'A %(maybe_junk)sbranch with the name "%(name)s" already exists '
            'for %(context)s.' % params)
        self.existing_branch = existing_branch
        BranchCreationException.__init__(self, message)


class BranchTargetError(Exception):
    """Raised when there is an error determining a branch target."""


class CannotDeleteBranch(Exception):
    """The branch cannot be deleted at this time."""


class BranchCreationForbidden(BranchCreationException):
    """A Branch visibility policy forbids branch creation.

    The exception is raised if the policy for the product does not allow
    the creator of the branch to create a branch for that product.
    """


class BranchCreatorNotMemberOfOwnerTeam(BranchCreationException):
    """Branch creator is not a member of the owner team.

    Raised when a user is attempting to create a branch and set the owner of
    the branch to a team that they are not a member of.
    """

    webservice_error(400)


class BranchCreatorNotOwner(BranchCreationException):
    """A user cannot create a branch belonging to another user.

    Raised when a user is attempting to create a branch and set the owner of
    the branch to another user.
    """

    webservice_error(400)


class BranchTypeError(Exception):
    """An operation cannot be performed for a particular branch type.

    Some branch operations are only valid for certain types of branches.  The
    BranchTypeError exception is raised if one of these operations is called
    with a branch of the wrong type.
    """


class BranchCannotBePublic(Exception):
    """The branch cannot be made public."""


class BranchCannotBePrivate(Exception):
    """The branch cannot be made private."""


class InvalidBranchException(Exception):
    """Base exception for an error resolving a branch for a component.

    Subclasses should set _msg_template to match their required display
    message.
    """

    _msg_template = "Invalid branch for: %s"

    def __init__(self, component):
        self.component = component
        # It's expected that components have a name attribute,
        # so let's assume they will and deal with any error if it occurs.
        try:
            component_name = component.name
        except AttributeError:
            component_name = str(component)
        # The display_message contains something readable for the user.
        self.display_message = self._msg_template % component_name
        Exception.__init__(self, self._msg_template % (repr(component),))


class CannotHaveLinkedBranch(InvalidBranchException):
    """Raised when we try to get the linked branch for a thing that can't."""

    _msg_template = "%s cannot have linked branches."


class ClaimReviewFailed(Exception):
    """The user cannot claim the pending review."""


class InvalidBranchMergeProposal(Exception):
    """Raised during the creation of a new branch merge proposal.

    The text of the exception is the rule violation.
    """


class BranchMergeProposalExists(InvalidBranchMergeProposal):
    """Raised if there is already a matching BranchMergeProposal."""

    webservice_error(400) #Bad request.


class InvalidNamespace(Exception):
    """Raised when someone tries to lookup a namespace with a bad name.

    By 'bad', we mean that the name is unparsable. It might be too short, too
    long or malformed in some other way.
    """

    def __init__(self, name):
        self.name = name
        Exception.__init__(
            self, "Cannot understand namespace name: '%s'" % (name,))


class NoLinkedBranch(InvalidBranchException):
    """Raised when there's no linked branch for a thing."""

    _msg_template = "%s has no linked branch."


class NoSuchBranch(NameLookupFailed):
    """Raised when we try to load a branch that does not exist."""

    _message_prefix = "No such branch"


class PrivateBranchRecipe(Exception):

    def __init__(self, branch):
        message = (
            'Recipe may not refer to private branch: %s' %
            branch.bzr_identity)
        self.branch = branch
        Exception.__init__(self, message)


class ReviewNotPending(Exception):
    """The requested review is not in a pending state."""


class UserHasExistingReview(Exception):
    """The user has an existing review."""


class UserNotBranchReviewer(Exception):
    """The user who attempted to review the merge proposal isn't a reviewer.

    A specific reviewer may be set on a branch.  If a specific reviewer
    isn't set then any user in the team of the owner of the branch is
    considered a reviewer.
    """


class WrongBranchMergeProposal(Exception):
    """The comment requested is not associated with this merge proposal."""


class UnknownBranchTypeError(Exception):
    """Raised when the user specifies an unrecognized branch type."""


class CodeImportNotInReviewedState(Exception):
    """Raised when the user requests an import of a non-automatic import."""

    webservice_error(400)


class CodeImportAlreadyRequested(Exception):
    """Raised when the user requests an import that is already requested."""

    def __init__(self, msg, requesting_user):
        super(CodeImportAlreadyRequested, self).__init__(msg)
        self.requesting_user = requesting_user


class CodeImportAlreadyRunning(Exception):
    """Raised when the user requests an import that is already running."""

    webservice_error(400)


class TooNewRecipeFormat(Exception):
    """The format of the recipe supplied was too new."""

    def __init__(self, supplied_format, newest_supported):
        super(TooNewRecipeFormat, self).__init__()
        self.supplied_format = supplied_format
        self.newest_supported = newest_supported


class RecipeBuildException(Exception):

    def __init__(self, recipe, distroseries, template):
        self.recipe = recipe
        self.distroseries = distroseries
        msg = template % {'recipe': recipe, 'distroseries': distroseries}
        Exception.__init__(self, msg)


class TooManyBuilds(RecipeBuildException):
    """A build was requested that exceeded the quota."""

    webservice_error(400)

    def __init__(self, recipe, distroseries):
        RecipeBuildException.__init__(
            self, recipe, distroseries,
            'You have exceeded your quota for recipe %(recipe)s for'
            ' distroseries %(distroseries)s')


class BuildAlreadyPending(RecipeBuildException):
    """A build was requested when an identical build was already pending."""

    webservice_error(400)

    def __init__(self, recipe, distroseries):
        RecipeBuildException.__init__(
            self, recipe, distroseries,
            'An identical build of this recipe is already pending.')


class BuildNotAllowedForDistro(RecipeBuildException):
    """A build was requested against an unsupported distroseries."""

    webservice_error(400)

    def __init__(self, recipe, distroseries):
        RecipeBuildException.__init__(
            self, recipe, distroseries,
            'A build against this distro is not allowed.')


class InvalidMergeQueueConfig(Exception):
    """The config specified is not a valid JSON string."""

    webservice_error(400)

    def __init__(self):
        message = ('The configuration specified is not a valid JSON string.')
        Exception.__init__(self, message)
