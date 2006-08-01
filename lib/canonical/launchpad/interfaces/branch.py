# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Branch interfaces."""

__metaclass__ = type

__all__ = [
    'IBranch',
    'IBranchSet',
    ]

from zope.interface import Interface, Attribute

from zope.component import getUtility
from zope.schema import Bool, Int, Choice, Text, TextLine, Datetime

from canonical.config import config
from canonical.lp.dbschema import BranchLifecycleStatus

from canonical.launchpad import _
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.interfaces import IHasOwner
from canonical.launchpad.interfaces.validation import valid_webref

class BranchUrlField(TextLine):

    def _validate(self, url):
        # import here to avoid circular import
        from canonical.launchpad.webapp import canonical_url
        url = url.rstrip('/')
        TextLine._validate(self, url)
        if IBranch.providedBy(self.context) and self.context.url == url:
            return # url was not changed
        if (url + '/').startswith(config.launchpad.supermirror_root):
            message = _(
                "Don't manually register a bzr branch on "
                "<code>bazaar.launchpad.net</code>. Create it by SFTP, and it "
                "is registered automatically.")
            raise LaunchpadValidationError(message)
        branch = getUtility(IBranchSet).getByUrl(url)
        if branch is not None:
            message = _(
                "The bzr branch <a href=\"%s\">%s</a> is already registered "
                "with this URL.")
            raise LaunchpadValidationError(
                message, canonical_url(branch), branch.displayname)


class IBranch(IHasOwner):
    """A Bazaar branch."""

    id = Int(title=_('ID'), readonly=True, required=True)
    name = TextLine(
        title=_('Name'), required=True, description=_("Keep very "
        "short, unique, and descriptive, because it will be used in URLs. "
        "Examples: main, devel, release-1.0, gnome-vfs."),
        constraint=name_validator)
    title = TextLine(
        title=_('Title'), required=False, description=_("Describe the "
        "branch as clearly as possible in up to 70 characters. This "
        "title is displayed in every branch list or report."))
    summary = Text(
        title=_('Summary'), required=False, description=_("A "
        "single-paragraph description of the branch. This will be "
        "displayed on the branch page."))
    url = BranchUrlField(
        title=_('Branch URL'), required=True,
        description=_("The URL where the Bazaar branch is hosted. This is "
            "the URL used to checkout the branch. The only branch format "
            "supported is that of the Bazaar revision control system, see "
            "www.bazaar-vcs.org for more information."),
        constraint=valid_webref)

    whiteboard = Text(title=_('Status Whiteboard'), required=False,
        description=_('Notes on the current status of the branch.'))
    mirror_status_message = Text(
        title=_('The last message we got when mirroring this branch '
                'into supermirror.'), required=False, readonly=False)
    started_at = Int(title=_('Started At'), required=False,
        description=_("The number of the first revision"
                      " to display on that branch."))

    # People attributes
    """Product owner, it can either a valid Person or Team
            inside Launchpad context."""
    owner = Choice(title=_('Owner'), required=True, vocabulary='ValidOwner',
        description=_("Branch owner, either a valid Person or Team."))
    author = Choice(
        title=_('Author'), required=False, vocabulary='ValidPersonOrTeam',
        description=_("The author of the branch. Leave blank if the author "
                      "does not have a Launchpad account."))

    # Product attributes
    product = Choice(
        title=_('Product'), required=False, vocabulary='Product',
        description=_("The product this branch belongs to."))
    product_name = Attribute("The name of the product, or '+junk'.")
    branch_product_name = Attribute(
        "The product name specified within the branch.")
    product_locked = Bool(
        title=_("Product Locked"),
        description=_("Whether the product name specified within the branch "
                      " is overriden by the product name set in Launchpad."))

    # Display attributes
    unique_name = Attribute(
        "Unique name of the branch, including the owner and product names.")
    displayname = Attribute(
        "The branch title if provided, or the unique_name.")
    sort_key = Attribute(
        "Key for sorting branches for display.")


    # Home page attributes
    home_page = TextLine(
        title=_('Web Page'), required=False,
        description=_("The URL of a web page describing the branch, "
                      "if there is such a page."), constraint=valid_webref)
    branch_home_page = Attribute(
        "The home page URL specified within the branch.")
    home_page_locked = Bool(
        title=_("Home Page Locked"),
        description=_("Whether the home page specified within the branch "
                      " is overriden by the home page set in Launchpad."))

    # Stats and status attributes
    lifecycle_status = Choice(
        title=_('Status'), vocabulary='BranchLifecycleStatus',
        default=BranchLifecycleStatus.NEW,
        description=_(
        "The author's assessment of the branch's maturity. "
        " Mature: recommend for production use."
        " Development: useful work that is expected to be merged eventually."
        " Experimental: not recommended for merging yet, and maybe ever."
        " Merged: integrated into mainline, of historical interest only."
        " Abandoned: no longer considered relevant by the author."
        " New: unspecified maturity."))

    # TODO: landing_target, needs a BranchVocabulaty. See bug #4119.
    # -- DavidAllouche 2005-09-05

    current_delta_url = Attribute(
        "URL of a page showing the delta produced "
        "by merging this branch into the landing branch.")
    current_diff_adds = Attribute(
        "Count of lines added in merge delta.")
    current_diff_deletes = Attribute(
        "Count of lines deleted in the merge delta.")
    current_conflicts_url = Attribute(
        "URL of a page showing the conflicts produced "
        "by merging this branch into the landing branch.")
    current_activity = Attribute("Current branch activity.")
    stats_updated = Attribute("Last time the branch stats were updated.")

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

    # Scanning attributes
    last_scanned = Datetime(
        title=_("Last time this branch was successfully scanned."),
        required=False)
    last_scanned_id = Text(
        title=_("Last scanned revision ID"), required=False,
        description=_("The head revision ID of the branch when last "
                      "successfully scanned."))

    cache_url = Attribute("Private mirror of the branch, for internal use.")
    warehouse_url = Attribute(
        "URL for accessing the branch by ID. "
        "This is for in-datacentre services only and allows such services to "
        "be unaffected during branch renames. "
        "See doc/bazaar for more information about the branch warehouse.")

    # Bug attributes
    related_bugs = Attribute(
        "The bugs related to this branch, likely branches on which "
        "some work has been done to fix this bug.")

    # Joins
    revision_history = Attribute("The sequence of revisions in that branch.")
    revision_count = Attribute("The number of revisions in that branch.")
    subscriptions = Attribute("BranchSubscriptions associated to this branch.")
    subscribers = Attribute("Persons subscribed to this branch.")

    def has_subscription(person):
        """Is this person subscribed to the branch?"""

    def latest_revisions(quantity=10):
        """A specific number of the latest revisions in that branch."""

    def revisions_since(timestamp):
        """Revisions in the history that are more recent than timestamp."""

    # subscription-related methods
    def subscribe(person):
        """Subscribe this person to the branch.

        :return: new or existing BranchSubscription."""

    def unsubscribe(person):
        """Remove the person's subscription to this branch."""

    # revision number manipulation
    def getRevisionNumber(sequence):
        """Gets the RevisionNumber for the given sequence number.

        If no such RevisionNumber exists, None is returned.
        """

    def createRevisionNumber(sequence, revision):
        """Create a RevisionNumber mapping sequence to revision."""

    def truncateHistory(from_rev):
        """Truncate the history of the given branch.

        RevisionNumber objects with sequence numbers greater than or
        equal to from_rev are destroyed.

        Returns True if any RevisionNumber objects were destroyed.
        """


class IBranchSet(Interface):
    """Interface representing the set of branches."""

    def __getitem__(branch_id):
        """Return the branch with the given id.

        Raise NotFoundError if there is no such branch.
        """

    def __iter__():
        """Return an iterator that will go through all branches."""

    all = Attribute("All branches in the system.")

    def get(branch_id, default=None):
        """Return the branch with the given id.

        Return the default value if there is no such branch.
        """

    def new(name, owner, product, url, title,
            lifecycle_status=BranchLifecycleStatus.NEW, author=None,
            summary=None, home_page=None):
        """Create a new branch."""

    def getByUniqueName(self, unique_name, default=None):
        """Find a branch by its ~owner/product/name unique name."""

    def getByUrl(url, default=None):
        """Find a branch by URL.

        Either from the external specified in Branch.url, or from the
        supermirror URL on http://bazaar.launchpad.net/.

        Return the default value if no match was found.
        """

    def getBranchesToScan():
        """Return an iterator for the branches that need to be scanned."""
