# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Base class view for branch listings."""

__metaclass__ = type

__all__ = [
    'BranchListingView',
    ]

from datetime import datetime

from zope.component import getUtility
from zope.interface import implements

from canonical.lp import decorates
from canonical.lp.dbschema import (BranchLifecycleStatus,
                                   BranchLifecycleStatusFilter)

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.interfaces import (
    DEFAULT_BRANCH_STATUS_IN_LISTING, IBranch, IBranchLifecycleFilter,
    IBranchSet, IBugBranchSet, IBranchBatchNavigator)
from canonical.launchpad.webapp import LaunchpadFormView, custom_widget
from canonical.launchpad.webapp.batching import TableBatchNavigator
from canonical.widgets import LaunchpadDropdownWidget


class BranchListingItem:
    """A decorated branch.

    Some attributes that we want to display are too convoluted or expensive
    to get on the fly for each branch in the listing.  These items are
    prefetched by the view and decorate the branch.
    """
    decorates(IBranch, 'branch')

    def __init__(self, branch, last_commit, elapsed, bugbranches, role=None):
        self.branch = branch
        self.last_commit = last_commit
        self.elapsed_time = elapsed
        self.bugbranches = bugbranches
        self.role = role
        

class BranchListingBatchNavigator(TableBatchNavigator):
    """Batch up the branch listings."""
    implements(IBranchBatchNavigator)

    def __init__(self, view):
        TableBatchNavigator.__init__(
            self, view._branches(), view.request,
            columns_to_show=view.extra_columns)
        self.view = view
        self.column_count = 4 + len(view.extra_columns)
        self._now = datetime.now()

    @cachedproperty
    def last_commit(self):
        """Get the last commit times for the current batch."""
        return getUtility(IBranchSet).getLastCommitForBranches(
            self.currentBatch())

    @cachedproperty
    def branch_bug_links(self):
        """Get all bugs associated the with current batch."""
        bugbranches = getUtility(IBugBranchSet).getBugBranchesForBranches(
            self.batch)
        result = {}
        for bugbranch in bugbranches:
            result.setdefault(
                bugbranch.branch.id, []).append(bugbranch)
        return result

    def _createItem(self, branch):
        last_commit = self.last_commit[branch]
        elapsed = last_commit and (self._now - last_commit)
        bug_branches = self.branch_bug_links.get(branch.id)
        role = self.view.roleForBranch(branch)
        return BranchListingItem(
            branch, last_commit, elapsed, bug_branches, role)

    def branches(self):
        "Return a list of BranchListingItems"
        return [self._createItem(branch) for branch in self.currentBatch()] 

    @cachedproperty
    def multiple_pages(self):
        return self.batch.total() > self.batch.size

    @property
    def table_class(self):
        if self.multiple_pages:
            return "listing"
        else:
            return "listing sortable"
        

class BranchListingView(LaunchpadFormView):
    """A base class for views of branch listings."""
    schema = IBranchLifecycleFilter
    field_names = ['lifecycle']
    custom_widget('lifecycle', LaunchpadDropdownWidget)
    extra_columns = []
    title_prefix = 'Bazaar'

    @property
    def page_title(self):
        return '%s branches for %s' % (
            self.title_prefix, self.context.displayname)
    
    @property
    def initial_values(self):
        return {
            'lifecycle': BranchLifecycleStatusFilter.CURRENT
            }

    @cachedproperty
    def selected_lifecycle_status(self):
        widget = self.widgets['lifecycle']

        if widget.hasValidInput():
            lifecycle_filter = widget.getInputValue()
        else:
            lifecycle_filter = BranchLifecycleStatusFilter.CURRENT

        if lifecycle_filter == BranchLifecycleStatusFilter.ALL:
            return None
        elif lifecycle_filter == BranchLifecycleStatusFilter.CURRENT:
            return DEFAULT_BRANCH_STATUS_IN_LISTING
        else:
            return (BranchLifecycleStatus.items[lifecycle_filter.value], )

    def branches(self):
        """All branches related to this target, sorted for display."""
        # Separate the public property from the underlying virtual method.
        return BranchListingBatchNavigator(self)

    def roleForBranch(self, branch):
        """Overridden by derived classes to display something useful."""
        return None

    @property
    def no_branch_message(self):
        """This may also be overridded i derived classes."""
        if self.selected_lifecycle_status:
            message = (
                'There may be branches related to %s '
                'but none of them match the current filter criteria '
                'for this page. Try filtering on "Any Status".')
        else:
            message = (
                'There are no branches related to %s '
                'in Launchpad today. You can use Launchpad as a registry for '
                'Bazaar branches, and encourage broader community '
                'participation in your project using '
                'distributed version control.')
        return message % self.context.displayname


