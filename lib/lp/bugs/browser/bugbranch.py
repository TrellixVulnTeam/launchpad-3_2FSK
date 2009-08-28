# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser view classes for BugBranch-related objects."""

__metaclass__ = type
__all__ = [
    'BranchLinkToBugView',
    'BugBranchAddView',
    'BugBranchDeleteView',
    'BugBranchPrimaryContext',
    ]

from zope.interface import implements

from canonical.lazr.utils import smartquote

from canonical.launchpad import _
from canonical.launchpad.webapp import (
    action, canonical_url, LaunchpadEditFormView, LaunchpadFormView)
from canonical.launchpad.webapp.interfaces import IPrimaryContext
from lp.bugs.interfaces.bugbranch import IBugBranch


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
