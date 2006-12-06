# Copyright 2005 Canonical Ltd.  All rights reserved.

"""IBranchTarget browser views."""

__metaclass__ = type

__all__ = [
    'BranchTargetView',
    'PersonBranchesView',
    ]

import operator

from canonical.lp.dbschema import BranchLifecycleStatus

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.interfaces import IPerson, IProduct
from canonical.launchpad.webapp import LaunchpadView

# XXX This stuff was initially cargo-culted from ITicketTarget, some of it
# could be factored out. See bug 4011. -- David Allouche 2005-09-09


class BranchTargetView(LaunchpadView):

    # The default set of statum to show
    CURRENT = set([BranchLifecycleStatus.NEW,
                   BranchLifecycleStatus.EXPERIMENTAL,
                   BranchLifecycleStatus.DEVELOPMENT,
                   BranchLifecycleStatus.MATURE])
                  

    def initialize(self):
        self.show = self.request.get('show', 'current').upper()

    @cachedproperty
    def branches(self):
        """All branches related to this target, sorted for display."""
        # A cache to avoid repulling data from the database, which can be
        # particularly expensive
        branches = self.context.branches
        return sorted(branches, key=operator.attrgetter('sort_key'))

    @cachedproperty
    def visible_branches(self):
        """The branches that should be visible to the user."""
        # short circuit trivial case
        if self.show == 'ALL':
            return self.branches
        try:
            show_status = BranchLifecycleStatus.items[self.show]
            branches = [b for b in self.context.branches
                        if b.lifecycle_status == show_status]
        except KeyError:
            # no point erroring out, just show the default set
            branches = [b for b in self.context.branches
                        if b.lifecycle_status in self.CURRENT]
        return sorted(branches, key=operator.attrgetter('sort_key'))

    def context_relationship(self):
        """The relationship text used for display.

        Explains how the this branch listing relates to the context object. 
        """
        if self.in_product_context():
            return "registered for"
        url = self.request.getURL()
        if '+authoredbranches' in url:
            return "authored by"
        elif '+registeredbranches' in url:
            return "registered but not authored by"
        elif '+subscribedbranches' in url:
            return "subscribed to by"
        else:
            return "related to"

    def in_person_context(self):
        """Whether the context object is a person."""
        return IPerson.providedBy(self.context)

    def in_product_context(self):
        """Whether the context object is a product."""
        return IProduct.providedBy(self.context)

    def categories(self):
        """This organises the branches related to this target by
        "category", where a category corresponds to a particular branch
        status. It also determines the order of those categories, and the
        order of the branches inside each category. This is used for the
        +branches view.

        It is also used in IPerson, which is not an IBranchTarget but
        which does have a IPerson.branches. In this case, it will also
        detect which set of branches you want to see. The options are:

         - all branches (self.branches)
         - authored by this person (self.context.authored_branches)
         - registered by this person (self.context.registered_branches)
         - subscribed by this person (self.context.subscribed_branches)
        """
        categories = {}
        if not IPerson.providedBy(self.context):
            branches = self.branches
        else:
            url = self.request.getURL()
            if '+authoredbranches' in url:
                branches = self.context.authored_branches
            elif '+registeredbranches' in url:
                branches = self.context.registered_branches
            elif '+subscribedbranches' in url:
                branches = self.context.subscribed_branches
            else:
                branches = self.branches
        for branch in branches:
            if categories.has_key(branch.lifecycle_status):
                category = categories[branch.lifecycle_status]
            else:
                category = {}
                category['status'] = branch.lifecycle_status
                category['branches'] = []
                categories[branch.lifecycle_status] = category
            category['branches'].append(branch)
        categories = categories.values()
        for category in categories:
            category['branches'].sort(key=operator.attrgetter('sort_key'))
        return sorted(categories, key=self.category_sortkey)

    @staticmethod
    def category_sortkey(category):
        return category['status'].sortkey


class PersonBranchesView(BranchTargetView):
    """View used for the tabular listing of branches related to a person.

    The context must provide IPerson.
    """

    @cachedproperty
    def _authored_branch_set(self):
        """Set of branches authored by the person."""
        # must be cached because it is used by branch_role
        return set(self.context.authored_branches)

    @cachedproperty
    def _registered_branch_set(self):
        """Set of branches registered but not authored by the person."""
        # must be cached because it is used by branch_role
        return set(self.context.registered_branches)

    @cachedproperty
    def _subscribed_branch_set(self):
        """Set of branches this person is subscribed to."""
        # must be cached because it is used by branch_role
        return set(self.context.subscribed_branches)

    def branch_role(self, branch):
        """Primary role of this person for this branch.

        This explains why a branch appears on the person's page. The person may
        be 'Author', 'Registrant' or 'Subscriber'.

        :precondition: the branch must be part of the list provided by
            PersonBranchesView.branches.
        :return: dictionary of two items: 'title' and 'sortkey' describing the
            role of this person for this branch.
        """
        if branch in self._authored_branch_set:
            return {'title': 'Author', 'sortkey': 10}
        if branch in self._registered_branch_set:
            return {'title': 'Registrant', 'sortkey': 20}
        assert branch in self._subscribed_branch_set, (
            "Unable determine role of person %r for branch %r" % (
            self.context.name, branch.unique_name))
        return {'title': 'Subscriber', 'sortkey': 30}
        
