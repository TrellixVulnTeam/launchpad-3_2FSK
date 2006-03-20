# Copyright 2005 Canonical Ltd.  All rights reserved.

"""IBranchTarget browser views."""

__metaclass__ = type

__all__ = [
    'BranchTargetView',
    ]

from canonical.launchpad.interfaces import IPerson, IProduct
from canonical.lp.dbschema import BranchLifecycleStatus

# XXX This stuff was cargo-culted from ITicketTarget, that needs to be factored
# out. See bug 4011. -- David Allouche 2005-09-09


class BranchTargetView:

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def context_relationship(self):
        """The relationship text used for display.

        Explains how the this branch listing relates to the context object. 
        """
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

         - all branches (self.context.branches)
         - authored by this person (self.context.authored_branches)
         - registered by this person (self.context.registered_branches)
         - subscribed by this person (self.context.subscribed_branches)
        """
        categories = {}
        if not IPerson.providedBy(self.context):
            branches = self.context.branches
        else:
            url = self.request.getURL()
            if '+authoredbranches' in url:
                branches = self.context.authored_branches
            elif '+registeredbranches' in url:
                branches = self.context.registered_branches
            elif '+subscribedbranches' in url:
                branches = self.context.subscribed_branches
            else:
                branches = self.context.branches
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
        return sorted(categories, key=self.category_display_order)

    @staticmethod
    def category_display_order(category):
        display_order = [
            BranchLifecycleStatus.MATURE,
            BranchLifecycleStatus.DEVELOPMENT,
            BranchLifecycleStatus.EXPERIMENTAL,
            BranchLifecycleStatus.MERGED,
            BranchLifecycleStatus.ABANDONED,
            BranchLifecycleStatus.NEW,
            ]
        return display_order.index(category['status'])
