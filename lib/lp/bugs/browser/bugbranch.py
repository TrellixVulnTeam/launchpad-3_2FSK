# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser view classes for BugBranch-related objects."""

__metaclass__ = type
__all__ = [
    'BranchLinkToBugView',
    'BugBranchAddView',
    'BugBranchDeleteView',
    'BugBranchPrimaryContext',
    'BugBranchView',
    ]

from zope.component import adapts, getMultiAdapter
from zope.interface import implements, Interface

from lazr.restful.interfaces import IWebServiceClientRequest

from canonical.cachedproperty import cachedproperty
from canonical.lazr.utils import smartquote

from canonical.launchpad import _
from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadEditFormView, LaunchpadFormView,
    LaunchpadView)
from canonical.launchpad.webapp.interfaces import IPrimaryContext
from lp.bugs.interfaces.bugbranch import IBugBranch
from lp.code.browser.branchmergeproposal import (
    latest_proposals_for_each_branch)
from lp.code.enums import BranchLifecycleStatus


class BugBranchPrimaryContext:
    """The primary context is the bug branch link is that of the branch."""

    implements(IPrimaryContext)

    def __init__(self, bug_branch):
        self.context = IPrimaryContext(bug_branch.branch).context


class BugBranchAddView(LaunchpadFormView):
    """Browser view for linking a bug to a branch."""
    schema = IBugBranch
    # In order to have the branch field rendered using the appropriate
    # widget, we set the LaunchpadFormView attribute for_input to True
    # to get the read only fields rendered as input widgets.
    for_input = True

    field_names = ['branch']

    @action(_('Continue'), name='continue')
    def continue_action(self, action, data):
        branch = data['branch']
        self.context.bug.linkBranch(
            branch=branch, registrant=self.user)
        self.request.response.addNotification(
            "Successfully registered branch %s for this bug." %
            branch.name)

    @property
    def next_url(self):
        return canonical_url(self.context)

    @property
    def label(self):
        return 'Add a branch to bug #%i' % self.context.bug.id

    cancel_url = next_url


class BugBranchDeleteView(LaunchpadEditFormView):
    """View to update a BugBranch."""
    schema = IBugBranch

    field_names = []

    def initialize(self):
        LaunchpadEditFormView.initialize(self)

    @property
    def next_url(self):
        return canonical_url(self.context.bug)

    cancel_url = next_url

    @action('Delete', name='delete')
    def delete_action(self, action, data):
        self.context.bug.unlinkBranch(self.context.branch, self.user)

    label = 'Remove bug branch link'


class BugBranchView(LaunchpadView):
    """Simple view to cache related branch information."""

    @cachedproperty
    def merge_proposals(self):
        """Return a list of active proposals for the branch."""
        branch = self.context.branch
        return latest_proposals_for_each_branch(branch.landing_targets)

    @property
    def show_branch_status(self):
        """Show the branch status if merged and there are no proposals."""
        return (len(self.merge_proposals) == 0 and
                self.context.branch.lifecycle_status == BranchLifecycleStatus.MERGED)


class BranchLinkToBugView(LaunchpadFormView):
    """The view to create bug-branch links."""
    schema = IBugBranch
    # In order to have the bug field rendered using the appropriate
    # widget, we set the LaunchpadFormView attribute for_input to True
    # to get the read only fields rendered as input widgets.
    for_input = True

    field_names = ['bug']

    @property
    def label(self):
        return "Link to a bug report"

    @property
    def page_title(self):
        return smartquote(
            'Link branch "%s" to a bug report' % self.context.displayname)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url

    @action(_('Continue'), name='continue')
    def continue_action(self, action, data):
        bug = data['bug']
        bug_branch = bug.linkBranch(
            branch=self.context, registrant=self.user)


class BugBranchXHTMLRepresentation:
    adapts(IBugBranch, IWebServiceClientRequest)
    implements(Interface)

    def __init__(self, branch, request):
        self.branch = branch
        self.request = request

    def __call__(self):
        """Render `BugBranch` as XHTML using the webservice."""
        branch_view = getMultiAdapter(
            (self.branch, self.request), name="+bug-branch")
        return branch_view()

