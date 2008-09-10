# Copyright 2005, 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Branch interfaces."""

__metaclass__ = type

__all__ = [
    'BadBranchSearchContext',
    'branch_name_validator',
    'BranchCreationException',
    'BranchCreationForbidden',
    'BranchCreationNoTeamOwnedJunkBranches',
    'BranchCreatorNotMemberOfOwnerTeam',
    'BranchCreatorNotOwner',
    'BranchFormat',
    'BranchLifecycleStatus',
    'BranchLifecycleStatusFilter',
    'BranchListingSort',
    'BranchPersonSearchContext',
    'BranchPersonSearchRestriction',
    'BranchType',
    'BranchTypeError',
    'BRANCH_NAME_VALIDATION_ERROR_MESSAGE',
    'CannotDeleteBranch',
    'ControlFormat',
    'DEFAULT_BRANCH_STATUS_IN_LISTING',
    'IBranch',
    'IBranchSet',
    'IBranchDelta',
    'IBranchBatchNavigator',
    'IBranchListingFilter',
    'IBranchNavigationMenu',
    'IBranchPersonSearchContext',
    'MAXIMUM_MIRROR_FAILURES',
    'MIRROR_TIME_INCREMENT',
    'RepositoryFormat',
    'UICreatableBranchType',
    'UnknownBranchTypeError'
    ]

from cgi import escape
from datetime import timedelta
import re

# ensure correct plugins are loaded
import canonical.codehosting
from bzrlib.branch import (
    BranchReferenceFormat, BzrBranchFormat4, BzrBranchFormat5,
    BzrBranchFormat6, BzrBranchFormat7)
from bzrlib.bzrdir import (
    BzrDirFormat4, BzrDirFormat5, BzrDirFormat6, BzrDirMetaFormat1)
from bzrlib.plugins.loom.branch import (
    BzrBranchLoomFormat1, BzrBranchLoomFormat6)
from bzrlib.repofmt.knitrepo import (RepositoryFormatKnit1,
    RepositoryFormatKnit3, RepositoryFormatKnit4)
from bzrlib.repofmt.pack_repo import (
    RepositoryFormatKnitPack1, RepositoryFormatKnitPack3,
    RepositoryFormatKnitPack4, RepositoryFormatPackDevelopment0,
    RepositoryFormatPackDevelopment0Subtree, RepositoryFormatPackDevelopment1,
    RepositoryFormatPackDevelopment1Subtree, RepositoryFormatKnitPack5,
    RepositoryFormatKnitPack5RichRoot)
from bzrlib.repofmt.weaverepo import (
    RepositoryFormat4, RepositoryFormat5, RepositoryFormat6,
    RepositoryFormat7)
from zope.component import getUtility
from zope.interface import implements, Interface, Attribute
from zope.schema import Bool, Int, Choice, Text, TextLine, Datetime

from canonical.config import config

from canonical.launchpad import _
from canonical.launchpad.fields import (
    PublicPersonChoice, Summary, Title, URIField, Whiteboard)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.interfaces import IHasOwner
from canonical.launchpad.webapp.interfaces import ITableBatchNavigator
from canonical.launchpad.webapp.menu import structured
from canonical.lazr import (
    DBEnumeratedType, DBItem, EnumeratedType, Item, use_template)
from canonical.lazr.rest.declarations import (
    export_as_webservice_entry, export_write_operation, exported)


class BranchLifecycleStatus(DBEnumeratedType):
    """Branch Lifecycle Status

    This indicates the status of the branch, as part of an overall
    "lifecycle". The idea is to indicate to other people how mature this
    branch is, or whether or not the code in the branch has been deprecated.
    Essentially, this tells us what the author of the branch thinks of the
    code in the branch.
    """

    NEW = DBItem(1, """
        New

        This branch has just been created.
        """)

    EXPERIMENTAL = DBItem(10, """
        Experimental

        This branch contains code that is considered experimental. It is
        still under active development and should not be merged into
        production infrastructure.
        """)

    DEVELOPMENT = DBItem(30, """
        Development

        This branch contains substantial work that is shaping up nicely, but
        is not yet ready for merging or production use. The work is
        incomplete, or untested.
        """)

    MATURE = DBItem(50, """
        Mature

        The developer considers this code mature. That means that it
        completely addresses the issues it is supposed to, that it is tested,
        and that it has been found to be stable enough for the developer to
        recommend it to others for inclusion in their work.
        """)

    MERGED = DBItem(70, """
        Merged

        This code has successfully been merged into its target branch(es),
        and no further development is anticipated on the branch.
        """)

    ABANDONED = DBItem(80, """
        Abandoned

        This branch contains work which the author has abandoned, likely
        because it did not prove fruitful.
        """)


class BranchType(DBEnumeratedType):
    """Branch Type

    The type of a branch determins the branch interaction with a number
    of other subsystems.
    """

    HOSTED = DBItem(1, """
        Hosted

        Launchpad is the primary location of this branch.
        """)

    MIRRORED = DBItem(2, """
        Mirrored

        Primarily hosted elsewhere and is periodically mirrored
        from the external location into Launchpad.
        """)

    IMPORTED = DBItem(3, """
        Imported

        Branches that have been converted from some other revision
        control system into bzr and are made available through Launchpad.
        """)

    REMOTE = DBItem(4, """
        Remote

        Registered in Launchpad with an external location,
        but is not to be mirrored, nor available through Launchpad.
        """)


def _format_enum(num, format, format_string=None, description=None):
    instance = format()
    if format_string is None:
        format_string = instance.get_format_string()
    if description is None:
        description = instance.get_format_description()
    return DBItem(num, format_string, description)


class BranchFormat(DBEnumeratedType):
    """Branch on-disk format.

    This indicates which (Bazaar) format is used on-disk.  The list must be
    updated as the list of formats supported by Bazaar is updated.
    """

    UNRECOGNIZED = DBItem(1000, '!Unrecognized!', 'Unrecognized format')

    # Branch 4 was only used with all-in-one formats, so it didn't have its
    # own marker.  It was implied by the control directory marker.
    BZR_BRANCH_4 = _format_enum(
        4, BzrBranchFormat4, 'Fake Bazaar Branch 4 marker')

    BRANCH_REFERENCE = _format_enum(1, BranchReferenceFormat)

    BZR_BRANCH_5 = _format_enum(5, BzrBranchFormat5)

    BZR_BRANCH_6 = _format_enum(6, BzrBranchFormat6)

    BZR_BRANCH_7 = _format_enum(7, BzrBranchFormat7)

    BZR_LOOM_1 = _format_enum(101, BzrBranchLoomFormat1)

    BZR_LOOM_2 = _format_enum(106, BzrBranchLoomFormat6)


class RepositoryFormat(DBEnumeratedType):
    """Repository on-disk format.

    This indicates which (Bazaar) format is used on-disk.  The list must be
    updated as the list of formats supported by Bazaar is updated.
    """

    UNRECOGNIZED = DBItem(1000, '!Unrecognized!', 'Unrecognized format')

    # Repository formats prior to format 7 had no marker because they
    # were implied by the control directory format.
    BZR_REPOSITORY_4 = _format_enum(
        4, RepositoryFormat4, 'Fake Bazaar repository 4 marker')

    BZR_REPOSITORY_5 = _format_enum(
        5, RepositoryFormat5, 'Fake Bazaar repository 5 marker')

    BZR_REPOSITORY_6 = _format_enum(
        6, RepositoryFormat6, 'Fake Bazaar repository 6 marker')

    BZR_REPOSITORY_7 = _format_enum(7, RepositoryFormat7)

    BZR_KNIT_1 = _format_enum(101, RepositoryFormatKnit1)

    BZR_KNIT_3 = _format_enum(103, RepositoryFormatKnit3)

    BZR_KNIT_4 = _format_enum(104, RepositoryFormatKnit4)

    BZR_KNITPACK_1 = _format_enum(201, RepositoryFormatKnitPack1)

    BZR_KNITPACK_3 = _format_enum(203, RepositoryFormatKnitPack3)

    BZR_KNITPACK_4 = _format_enum(204, RepositoryFormatKnitPack4)

    BZR_KNITPACK_5 = _format_enum(
        205, RepositoryFormatKnitPack5,
        description='Packs 5 (needs bzr 1.6, supports stacking)\n')

    BZR_KNITPACK_5_RRB = DBItem(206,
        'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n',
        'Packs 5-Rich Root (needs bzr 1.6, supports stacking)'
        )

    BZR_KNITPACK_5_RR = DBItem(207,
        'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n',
        'Packs 5 rich-root (adds stacking support, requires bzr 1.6.1)',
        )

    BZR_PACK_DEV_0 = _format_enum(
        300, RepositoryFormatPackDevelopment0)

    BZR_PACK_DEV_0_SUBTREE = _format_enum(
        301, RepositoryFormatPackDevelopment0Subtree)

    BZR_DEV_1 = _format_enum(
        302, RepositoryFormatPackDevelopment1)

    BZR_DEV_1_SUBTREE = _format_enum(
        303, RepositoryFormatPackDevelopment1Subtree)


class ControlFormat(DBEnumeratedType):
    """Control directory (BzrDir) format.

    This indicates what control directory format is on disk.  Must be updated
    as new formats become available.
    """

    UNRECOGNIZED = DBItem(1000, '!Unrecognized!', 'Unrecognized format')

    BZR_DIR_4 = _format_enum(4, BzrDirFormat4)

    BZR_DIR_5 = _format_enum(5, BzrDirFormat5)

    BZR_DIR_6 = _format_enum(6, BzrDirFormat6)

    BZR_METADIR_1 = _format_enum(1, BzrDirMetaFormat1)


class UICreatableBranchType(EnumeratedType):
    """The types of branches that can be created through the web UI."""
    use_template(BranchType, exclude='IMPORTED')


DEFAULT_BRANCH_STATUS_IN_LISTING = (
    BranchLifecycleStatus.NEW,
    BranchLifecycleStatus.EXPERIMENTAL,
    BranchLifecycleStatus.DEVELOPMENT,
    BranchLifecycleStatus.MATURE)


# The maximum number of failures before we disable mirroring.
MAXIMUM_MIRROR_FAILURES = 5

# How frequently we mirror branches.
MIRROR_TIME_INCREMENT = timedelta(hours=6)


class BranchCreationException(Exception):
    """Base class for branch creation exceptions."""


class CannotDeleteBranch(Exception):
    """The branch cannot be deleted at this time."""


class UnknownBranchTypeError(Exception):
    """Raised when the user specifies an unrecognized branch type."""


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


class BranchCreationNoTeamOwnedJunkBranches(BranchCreationException):
    """We forbid the creation of team-owned +junk branches.

    Raised when a user is attempting to create a team-owned +junk branch.
    """


class BranchCreatorNotOwner(BranchCreationException):
    """A user cannot create a branch belonging to another user.

    Raised when a user is attempting to create a branch and set the owner of
    the branch to another user.
    """


class BranchTypeError(Exception):
    """An operation cannot be performed for a particular branch type.

    Some branch operations are only valid for certain types of branches.  The
    BranchTypeError exception is raised if one of these operations is called
    with a branch of the wrong type.
    """


class BadBranchSearchContext(Exception):
    """The context is not valid for a branch search."""


class BranchURIField(URIField):

    def _validate(self, value):
        # import here to avoid circular import
        from canonical.launchpad.webapp import canonical_url
        from canonical.launchpad.webapp.uri import URI

        super(BranchURIField, self)._validate(value)

        # XXX thumper 2007-06-12:
        # Move this validation code into IBranchSet so it can be
        # reused in the XMLRPC code, and the Authserver.
        # This also means we could get rid of the imports above.

        # URIField has already established that we have a valid URI
        uri = URI(value)
        supermirror_root = URI(config.codehosting.supermirror_root)
        launchpad_domain = config.vhost.mainsite.hostname
        if uri.underDomain(launchpad_domain):
            message = _(
                "For Launchpad to mirror a branch, the original branch "
                "cannot be on <code>${domain}</code>.",
                mapping={'domain': escape(launchpad_domain)})
            raise LaunchpadValidationError(structured(message))

        # As well as the check against the config, we also need to check
        # against the actual text used in the database constraint.
        constraint_text = 'http://bazaar.launchpad.net'
        if value.startswith(constraint_text):
            message = _(
                "For Launchpad to mirror a branch, the original branch "
                "cannot be on <code>${domain}</code>.",
                mapping={'domain': escape(constraint_text)})
            raise LaunchpadValidationError(structured(message))

        if IBranch.providedBy(self.context) and self.context.url == str(uri):
            return # url was not changed

        if uri.path == '/':
            message = _(
                "URLs for branches cannot point to the root of a site.")
            raise LaunchpadValidationError(message)

        branch = getUtility(IBranchSet).getByUrl(str(uri))
        if branch is not None:
            message = _(
                'The bzr branch <a href="${url}">${branch}</a> is '
                'already registered with this URL.',
                mapping={'url': canonical_url(branch),
                         'branch': escape(branch.displayname)})
            raise LaunchpadValidationError(structured(message))


BRANCH_NAME_VALIDATION_ERROR_MESSAGE = _(
    "Branch names must start with a number or letter.  The characters +, -, "
    "_, . and @ are also allowed after the first character.")


# This is a copy of the pattern in database/schema/trusted.sql.  Don't
# change this without changing that.
valid_branch_name_pattern = re.compile(r"^(?i)[a-z0-9][a-z0-9+\.\-@_]*\Z")


def valid_branch_name(name):
    """Return True if the name is valid as a branch name, otherwise False.

    The rules for what is a valid branch name are described in
    BRANCH_NAME_VALIDATION_ERROR_MESSAGE.
    """
    if valid_branch_name_pattern.match(name):
        return True
    return False


def branch_name_validator(name):
    """Return True if the name is valid, or raise a LaunchpadValidationError.
    """
    if not valid_branch_name(name):
        raise LaunchpadValidationError(
            _("Invalid branch name '${name}'. ${message}",
              mapping={'name': name,
                       'message': BRANCH_NAME_VALIDATION_ERROR_MESSAGE}))
    return True


class IBranchBatchNavigator(ITableBatchNavigator):
    """A marker interface for registering the appropriate branch listings."""


class IBranchNavigationMenu(Interface):
    """A marker interface to indicate the need to show the branch menu."""


class IBranch(IHasOwner):
    """A Bazaar branch."""
    export_as_webservice_entry()

    id = Int(title=_('ID'), readonly=True, required=True)

    # XXX: TimPenhey 2007-08-31
    # The vocabulary set for branch_type is only used for the creation
    # of branches through the automatically generated forms, and doesn't
    # actually represent the complete range of real values that branch_type
    # may actually hold.  Import branches are not created in the same
    # way as Hosted, Mirrored or Remote branches.
    # There are two option:
    #   1) define a separate schema to use in the UI (sledgehammer solution)
    #   2) work out some way to specify a restricted vocabulary in the view
    # Personally I'd like a LAZR way to do number 2.
    branch_type = Choice(
        title=_("Branch Type"), required=True,
        vocabulary=UICreatableBranchType)

    name = exported(
        TextLine(
            title=_('Name'),
            required=True,
            description=_("Keep very short, unique, and descriptive, because "
                          "it will be used in URLs. "
                          "Examples: main, devel, release-1.0, gnome-vfs."),
            constraint=branch_name_validator))
    title = exported(
        Title(
            title=_('Title'), required=False, description=_("Describe the "
            "branch as clearly as possible in up to 70 characters. This "
            "title is displayed in every branch list or report.")))
    summary = exported(
        Summary(
            title=_('Summary'), required=False, description=_("A "
            "single-paragraph description of the branch. This will be "
            "displayed on the branch page.")))
    url = exported(
        BranchURIField(
            title=_('Branch URL'), required=False,
            allowed_schemes=['http', 'https', 'ftp', 'sftp', 'bzr+ssh'],
            allow_userinfo=False,
            allow_query=False,
            allow_fragment=False,
            trailing_slash=False,
            description=_("This is the external location where the Bazaar "
                        "branch is hosted.")))

    branch_format = exported(
        Choice(
            title=_("Branch Format"),
            required=False,
            vocabulary=BranchFormat))

    repository_format = exported(
        Choice(
            title=_("Repository Format"),
            required=False,
            vocabulary=RepositoryFormat))

    control_format = exported(
        Choice(
            title=_("Control Directory"),
            required=False,
            vocabulary=ControlFormat))

    whiteboard = exported(
        Whiteboard(
            title=_('Whiteboard'),
            required=False,
            description=_('Notes on the current status of the branch.')))

    mirror_status_message = exported(
        Text(
            title=_('The last message we got when mirroring this branch '
                    'into supermirror.'),
            required=False,
            readonly=False))

    private = Bool(
        title=_("Keep branch confidential"), required=False,
        description=_("Make this branch visible only to its subscribers."),
        default=False)

    # People attributes
    registrant = exported(
        PublicPersonChoice(
            title=_("The user that registered the branch."),
            required=True,
            vocabulary='ValidPersonOrTeam'))
    owner = exported(
        PublicPersonChoice(
            title=_('Owner'),
            required=True,
            vocabulary='UserTeamsParticipationPlusSelf',
            description=_("Either yourself or a team you are a member of. "
                        "This controls who can modify the branch.")))
    author = exported(
        PublicPersonChoice(
            title=_('Author'),
            required=False,
            vocabulary='ValidPersonOrTeam',
            description=_("The author of the branch. Leave blank if the "
                        "author does not have a Launchpad account.")))
    reviewer = exported(
        PublicPersonChoice(
            title=_('Reviewer'),
            required=False,
            vocabulary='ValidPersonOrTeam',
            description=_("The reviewer of a branch is the person or team "
                          "that is responsible for authorising code to be "
                          "merged.")))

    code_reviewer = Attribute(
        "The reviewer if set, otherwise the owner of the branch.")

    # Product attributes
    product = Choice(
        title=_('Project'), required=False, vocabulary='Product',
        description=_("The project this branch belongs to."))
    product_name = Attribute("The name of the project, or '+junk'.")

    # Display attributes
    unique_name = Attribute(
        "Unique name of the branch, including the owner and project names.")
    displayname = Attribute(
        "The branch title if provided, or the unique_name.")

    # Stats and status attributes
    lifecycle_status = Choice(
        title=_('Status'), vocabulary=BranchLifecycleStatus,
        default=BranchLifecycleStatus.NEW)

    # Mirroring attributes
    last_mirrored = Datetime(
        title=_("Last time this branch was successfully mirrored."),
        required=False)
    last_mirrored_id = Text(
        title=_("Last mirrored revision ID"), required=False,
        description=_("The head revision ID of the branch when last "
                      "successfully mirrored."))
    last_mirror_attempt = Datetime(
        title=_("Last time a mirror of this branch was attempted."),
        required=False)
    mirror_failures = Attribute(
        "Number of failed mirror attempts since the last successful mirror.")
    pull_disabled = Bool(
        title=_("Do not try to pull this branch anymore."),
        description=_("Disable periodic pulling of this branch by Launchpad. "
                      "That will prevent connection attempts to the branch "
                      "URL. Use this if the branch is no longer available."))
    next_mirror_time = Datetime(
        title=_("If this value is more recent than the last mirror attempt, "
                "then the branch will be mirrored on the next mirror run."),
        required=False)

    # Scanning attributes
    last_scanned = Datetime(
        title=_("Last time this branch was successfully scanned."),
        required=False)
    last_scanned_id = Text(
        title=_("Last scanned revision ID"), required=False,
        description=_("The head revision ID of the branch when last "
                      "successfully scanned."))
    revision_count = Int(
        title=_("Revision count"),
        description=_("The revision number of the tip of the branch.")
        )

    stacked_on = Attribute('Stacked-on branch')

    warehouse_url = Attribute(
        "URL for accessing the branch by ID. "
        "This is for in-datacentre services only and allows such services to "
        "be unaffected during branch renames. "
        "See doc/bazaar for more information about the branch warehouse.")

    # Bug attributes
    bug_branches = Attribute(
        "The bug-branch link objects that link this branch to bugs. ")

    related_bugs = Attribute(
        "The bugs related to this branch, likely branches on which "
        "some work has been done to fix this bug.")

    # Specification attributes
    spec_links = Attribute("Specifications linked to this branch")

    # Joins
    revision_history = Attribute(
        """The sequence of BranchRevision for the mainline of that branch.

        They are ordered with the most recent revision first, and the list
        only contains those in the "leftmost tree", or in other words
        the revisions that match the revision history from bzrlib for this
        branch.
        """)
    subscriptions = Attribute(
        "BranchSubscriptions associated to this branch.")
    subscribers = Attribute("Persons subscribed to this branch.")

    date_created = exported(
        Datetime(
            title=_('Date Created'),
            required=True,
            readonly=True))

    date_last_modified = exported(
        Datetime(
            title=_('Date Last Modified'),
            required=True,
            readonly=False))

    def destroySelf(break_references=False):
        """Delete the specified branch.

        BranchRevisions associated with this branch will also be deleted.
        :param break_references: If supplied, break any references to this
            branch by deleting items with mandatory references and
            NULLing other references.
        :raise: CannotDeleteBranch if the branch cannot be deleted.
        """

    def latest_revisions(quantity=10):
        """A specific number of the latest revisions in that branch."""

    landing_targets = Attribute(
        "The BranchMergeProposals where this branch is the source branch.")
    landing_candidates = Attribute(
        "The BranchMergeProposals where this branch is the target branch. "
        "Only active merge proposals are returned (those that have not yet "
        "been merged).")
    dependent_branches = Attribute(
        "The BranchMergeProposals where this branch is the dependent branch. "
        "Only active merge proposals are returned (those that have not yet "
        "been merged).")
    def addLandingTarget(registrant, target_branch, dependent_branch=None,
                         whiteboard=None, date_created=None,
                         needs_review=False):
        """Create a new BranchMergeProposal with this branch as the source.

        Both the target_branch and the dependent_branch, if it is there,
        must be branches of the same project as the source branch.

        Branches without associated projects, junk branches, cannot
        specify landing targets.

        :param registrant: The person who is adding the landing target.
        :param target_branch: Must be another branch, and different to self.
        :param dependent_branch: Optional but if it is not None, it must be
            another branch.
        :param whiteboard: Optional.  Just text, notes or instructions
            pertinant to the landing such as testing notes.
        :param date_created: Used to specify the date_created value of the
            merge request.
        :param needs_review: Used to specify the the proposal is ready for
            review right now.
        """

    def getMergeQueue():
        """The proposals that are QUEUED to land on this branch."""

    def revisions_since(timestamp):
        """Revisions in the history that are more recent than timestamp."""

    code_is_browseable = Attribute(
        "Is the code in this branch accessable through codebrowse?")

    # Don't use Object -- that would cause an import loop with ICodeImport.
    code_import = Attribute("The associated CodeImport, if any.")

    bzr_identity = Attribute(
        "The shortest lp spec URL for this branch. "
        "If the branch is associated with a product as the primary "
        "development focus, then the result should be lp:product.  If "
        "the branch is related to a series, then lp:product/series. "
        "Otherwise the result is lp:~user/product/branch-name.")

    def canBeDeleted():
        """Can this branch be deleted in its current state.

        A branch is considered deletable if it has no revisions, is not
        linked to any bugs, specs, productseries, or code imports, and
        has no subscribers.
        """

    def deletionRequirements():
        """Determine what is required to delete this branch.

        :return: a dict of {object: (operation, reason)}, where object is the
            object that must be deleted or altered, operation is either
            "delete" or "alter", and reason is a string explaining why the
            object needs to be touched.
        """

    def associatedProductSeries():
        """Return the product series that this branch is associated with.

        A branch may be associated with a product series as either a
        user_branch or import_branch.  Also a branch can be associated
        with more than one product series as a user_branch.
        """

    # subscription-related methods
    def subscribe(person, notification_level, max_diff_lines,
                  code_review_level):
        """Subscribe this person to the branch.

        :param person: The `Person` to subscribe.
        :param notification_level: The kinds of branch changes that cause
            notification.
        :param max_diff_lines: The maximum number of lines of diff that may
            appear in a notification.
        :param code_review_level: The kinds of code review activity that cause
            notification.
        :return: new or existing BranchSubscription."""

    def getSubscription(person):
        """Return the BranchSubscription for this person."""

    def hasSubscription(person):
        """Is this person subscribed to the branch?"""

    def unsubscribe(person):
        """Remove the person's subscription to this branch."""

    def getSubscriptionsByLevel(notification_levels):
        """Return the subscriptions that are at the given notification levels.

        :param notification_levels: An iterable of
            `BranchSubscriptionNotificationLevel`s
        :return: An SQLObject query result.
        """

    def getBranchRevision(sequence=None, revision=None, revision_id=None):
        """Get the associated `BranchRevision`.

        One and only one parameter is to be not None.

        :param sequence: The revno of the revision in the mainline history.
        :param revision: A `Revision` object.
        :param revision_id: A revision id string.
        :return: A `BranchRevision` or None.
        """

    def createBranchRevision(sequence, revision):
        """Create a new `BranchRevision` for this branch."""

    def getTipRevision():
        """Return the `Revision` associated with the `last_scanned_id`.

        Will return None if last_scanned_id is None, or if the id
        is not found (as in a ghost revision).
        """

    def updateScannedDetails(revision_id, revision_count):
        """Updates attributes associated with the scanning of the branch.

        A single entry point that is called solely from the branch scanner
        script.
        """

    def getNotificationRecipients():
        """Return a complete INotificationRecipientSet instance.

        The INotificationRecipientSet instance contains the subscribers
        and their subscriptions.
        """

    def getScannerData():
        """Retrieve the full ancestry of a branch for the branch scanner.

        The branch scanner script is the only place where we need to retrieve
        all the BranchRevision rows for a branch. Since the ancestry of some
        branches is into the tens of thousands we don't want to materialise
        BranchRevision instances for each of these.

        :return: tuple of three items.
            1. Ancestry set of bzr revision-ids.
            2. History list of bzr revision-ids. Similar to the result of
               bzrlib.Branch.revision_history().
            3. Dictionnary mapping bzr bzr revision-ids to the database ids of
               the corresponding BranchRevision rows for this branch.
        """

    def getPullURL():
        """Return the URL used to pull the branch into the mirror area."""

    @export_write_operation()
    def requestMirror():
        """Request that this branch be mirrored on the next run of the branch
        puller.
        """

    def startMirroring():
        """Signal that this branch is being mirrored."""

    def mirrorComplete(last_revision_id):
        """Signal that a mirror attempt has completed successfully.

        :param last_revision_id: The revision ID of the tip of the mirrored
            branch.
        """

    def mirrorFailed(reason):
        """Signal that a mirror attempt failed.

        :param reason: An error message that will be displayed on the branch
            detail page.
        """


class IBranchSet(Interface):
    """Interface representing the set of branches."""

    def __getitem__(branch_id):
        """Return the branch with the given id.

        Raise NotFoundError if there is no such branch.
        """

    def __iter__():
        """Return an iterator that will go through all branches."""

    def count():
        """Return the number of branches in the database.

        Only counts public branches.
        """

    def countBranchesWithAssociatedBugs():
        """Return the number of branches that have bugs associated.

        Only counts public branches.
        """

    def get(branch_id, default=None):
        """Return the branch with the given id.

        Return the default value if there is no such branch.
        """

    def getBranch(owner, product, branch_name):
        """Return the branch identified by owner/product/branch_name."""

    def new(branch_type, name, registrant, owner, product, url, title=None,
            lifecycle_status=BranchLifecycleStatus.NEW, author=None,
            summary=None, whiteboard=None, date_created=None):
        """Create a new branch.

        Raises BranchCreationForbidden if the creator is not allowed
        to create a branch for the specified product.

        If product is None (indicating a +junk branch) then the owner must not
        be a team, except for the special case of the ~vcs-imports celebrity.
        """

    def getByProductAndName(product, name):
        """Find all branches in a product with a given name."""

    def getByProductAndNameStartsWith(product, name):
        """Find all branches in a product a name that starts with `name`."""

    def getByUniqueName(unique_name, default=None):
        """Find a branch by its ~owner/product/name unique name.

        Return the default value if no match was found.
        """

    def getRewriteMap():
        """Return the branches that can appear in the rewrite map.

        This returns only public, non-remote branches. The results *will*
        include branches that aren't explicitly private but are stacked-on
        private branches. The rewrite map generator filters these out itself.
        """

    def getByUrl(url, default=None):
        """Find a branch by URL.

        Either from the external specified in Branch.url, or from the
        supermirror URL on http://bazaar.launchpad.net/.

        Return the default value if no match was found.
        """

    def getBranchesToScan():
        """Return an iterator for the branches that need to be scanned."""

    def getActiveUserBranchSummaryForProducts(products):
        """Return the branch count and last commit time for the products.

        Only active branches are counted (i.e. not Merged or Abandoned),
        and only non import branches are counted.
        """

    def getRecentlyChangedBranches(
        branch_count=None,
        lifecycle_statuses=DEFAULT_BRANCH_STATUS_IN_LISTING,
        visible_by_user=None):
        """Return a result set of branches that have been recently updated.

        Only HOSTED and MIRRORED branches are returned in the result set.

        If branch_count is specified, the result set will contain at most
        branch_count items.

        If lifecycle_statuses evaluates to False then branches
        of any lifecycle_status are returned, otherwise only branches
        with a lifecycle_status of one of the lifecycle_statuses
        are returned.

        :param visible_by_user: If a person is not supplied, only public
            branches are returned.  If a person is supplied both public
            branches, and the private branches that the person is entitled to
            see are returned.  Private branches are only visible to the owner
            and subscribers of the branch, and to LP admins.
        :type visible_by_user: `IPerson` or None
        """

    def getRecentlyImportedBranches(
        branch_count=None,
        lifecycle_statuses=DEFAULT_BRANCH_STATUS_IN_LISTING,
        visible_by_user=None):
        """Return a result set of branches that have been recently imported.

        The result set only contains IMPORTED branches.

        If branch_count is specified, the result set will contain at most
        branch_count items.

        If lifecycle_statuses evaluates to False then branches
        of any lifecycle_status are returned, otherwise only branches
        with a lifecycle_status of one of the lifecycle_statuses
        are returned.

        :param visible_by_user: If a person is not supplied, only public
            branches are returned.  If a person is supplied both public
            branches, and the private branches that the person is entitled to
            see are returned.  Private branches are only visible to the owner
            and subscribers of the branch, and to LP admins.
        :type visible_by_user: `IPerson` or None
        """

    def getRecentlyRegisteredBranches(
        branch_count=None,
        lifecycle_statuses=DEFAULT_BRANCH_STATUS_IN_LISTING,
        visible_by_user=None):
        """Return a result set of branches that have been recently registered.

        If branch_count is specified, the result set will contain at most
        branch_count items.

        If lifecycle_statuses evaluates to False then branches
        of any lifecycle_status are returned, otherwise only branches
        with a lifecycle_status of one of the lifecycle_statuses
        are returned.

        :param visible_by_user: If a person is not supplied, only public
            branches are returned.  If a person is supplied both public
            branches, and the private branches that the person is entitled to
            see are returned.  Private branches are only visible to the owner
            and subscribers of the branch, and to LP admins.
        :type visible_by_user: `IPerson` or None
        """

    def getBranchesForContext(
        context=None,
        lifecycle_statuses=None,
        visible_by_user=None,
        sort_by=None):
        """Branches associated with the context.

        :param context: If None, all possible branches are returned, otherwise
            the results will be appropriately filtered by the type of the
            context.
        :type context: Something that implements IProject, IProduct, or
            IPerson.
        :param lifecycle_statuses: If lifecycle_statuses evaluates to False
            then branches of any lifecycle_status are returned, otherwise
            only branches with a lifecycle_status of one of the
            lifecycle_statuses are returned.
        :type lifecycle_statuses: One or more values from the
            BranchLifecycleStatus enumeration.
        :param visible_by_user: If a person is not supplied, only public
            branches are returned.  If a person is supplied both public
            branches, and the private branches that the person is entitled to
            see are returned.  Private branches are only visible to the owner
            and subscribers of the branch, and to LP admins.
        :type visible_by_user: `IPerson` or None
        :param sort_by: What to sort the returned branches by.
        :type sort_by: A value from the `BranchListingSort` enumeration or
            None.
        """

    def getHostedBranchesForPerson(person):
        """Return the hosted branches that the given person can write to."""

    def getLatestBranchesForProduct(product, quantity, visible_by_user=None):
        """Return the most recently created branches for the product.

        At most `quantity` branches are returned. Branches that have been
        merged or abandoned don't appear in the results -- only branches that
        match `DEFAULT_BRANCH_STATUS_IN_LISTING`.

        :param visible_by_user: If a person is not supplied, only public
            branches are returned.  If a person is supplied both public
            branches, and the private branches that the person is entitled to
            see are returned.  Private branches are only visible to the owner
            and subscribers of the branch, and to LP admins.
        :type visible_by_user: `IPerson` or None
        """

    def getPullQueue(branch_type):
        """Return a queue of branches to mirror using the puller.

        :param branch_type: A value from the `BranchType` enum.
        """

    def getTargetBranchesForUsersMergeProposals(user, product):
        """Return a sequence of branches the user has targeted before."""

    def isBranchNameAvailable(owner, product, branch_name):
        """Is the specified branch_name valid for the owner and product.

        :param owner: A `Person` who may be an individual or team.
        :param product: A `Product` or None for a junk branch.
        :param branch_name: The proposed branch name.
        """



class IBranchDelta(Interface):
    """The quantitative changes made to a branch that was edited or altered.
    """

    branch = Attribute("The IBranch, after it's been edited.")
    user = Attribute("The IPerson that did the editing.")

    # fields on the branch itself, we provide just the new changed value
    name = Attribute("Old and new names or None.")
    title = Attribute("Old and new branch titles or None.")
    summary = Attribute("The branch summary or None.")
    url = Attribute("Old and new branch URLs or None.")
    whiteboard = Attribute("The branch whiteboard or None.")
    lifecycle_status = Attribute("Old and new lifecycle status, or None.")
    revision_count = Attribute("Old and new revision counts, or None.")
    last_scanned_id = Attribute("The revision id of the tip revision.")


# XXX: TimPenhey 2007-07-23 bug=66950: The enumerations and interface
# to do with branch listing/filtering/ordering are used only in
# browser/branchlisting.py.

class BranchLifecycleStatusFilter(EnumeratedType):
    """Branch Lifecycle Status Filter

    Used to populate the branch lifecycle status filter widget.
    UI only.
    """
    use_template(BranchLifecycleStatus)

    sort_order = (
        'CURRENT', 'ALL', 'NEW', 'EXPERIMENTAL', 'DEVELOPMENT', 'MATURE',
        'MERGED', 'ABANDONED')

    CURRENT = Item("""
        Any active status

        Show the currently active branches.
        """)

    ALL = Item("""
        Any status

        Show all the branches.
        """)


class BranchListingSort(EnumeratedType):
    """Choices for how to sort branch listings."""

    # XXX: MichaelHudson 2007-10-17 bug=153891: We allow sorting on quantities
    # that are not visible in the listing!

    DEFAULT = Item("""
        by most interesting

        Sort branches by the default ordering for the view.
        """)

    PRODUCT = Item("""
        by project name

        Sort branches by name of the project the branch is for.
        """)

    LIFECYCLE = Item("""
        by lifecycle status

        Sort branches by the lifecycle status.
        """)

    NAME = Item("""
        by branch name

        Sort branches by the display name of the registrant.
        """)

    REGISTRANT = Item("""
        by registrant name

        Sort branches by the display name of the registrant.
        """)

    MOST_RECENTLY_CHANGED_FIRST = Item("""
        most recently changed first

        Sort branches from the most recently to the least recently
        changed.
        """)

    LEAST_RECENTLY_CHANGED_FIRST = Item("""
        least recently changed first

        Sort branches from the least recently to the most recently
        changed.
        """)

    NEWEST_FIRST = Item("""
        newest first

        Sort branches from newest to oldest.
        """)

    OLDEST_FIRST = Item("""
        oldest first

        Sort branches from oldest to newest.
        """)


class IBranchListingFilter(Interface):
    """The schema for the branch listing filtering/ordering form."""

    # Stats and status attributes
    lifecycle = Choice(
        title=_('Lifecycle Filter'), vocabulary=BranchLifecycleStatusFilter,
        default=BranchLifecycleStatusFilter.CURRENT,
        description=_(
        "The author's assessment of the branch's maturity. "
        " Mature: recommend for production use."
        " Development: useful work that is expected to be merged eventually."
        " Experimental: not recommended for merging yet, and maybe ever."
        " Merged: integrated into mainline, of historical interest only."
        " Abandoned: no longer considered relevant by the author."
        " New: unspecified maturity."))

    sort_by = Choice(
        title=_('ordered by'), vocabulary=BranchListingSort,
        default=BranchListingSort.LIFECYCLE)


class BranchPersonSearchRestriction(EnumeratedType):
    """How to further restrict the query for a branch search for people."""

    ALL = Item("""
        All related branches

        All branches owned, registered or subscribed to by the person.
        """)

    REGISTERED = Item("""
        Registered branches

        Only return the branches registered by the person.
        """)

    OWNED = Item("""
        Owned branches

        Only return the branches owned by the person.
        """)

    SUBSCRIBED = Item("""
        Subscribed branches

        Only return the branches subscribed to by the person.
        """)


class IBranchPersonSearchContext(Interface):
    """A `Person` with a search restriction."""

    person = PublicPersonChoice(
        title=_('Person'), required=True,
        vocabulary='ValidPersonOrTeam',
        description=_("The person to restrict the branch search to."))

    restriction = Choice(
        title=_("Search restriction"), required=True,
        vocabulary=BranchPersonSearchRestriction)


class BranchPersonSearchContext:
    """The simple implementation for the person search context."""
    implements(IBranchPersonSearchContext)

    def __init__(self, person, restriction=None):
        self.person = person
        if restriction is None:
            restriction = BranchPersonSearchRestriction.ALL
        self.restriction = restriction
