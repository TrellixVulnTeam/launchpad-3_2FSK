# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fiter bugtasks based on context."""

__metaclass__ = type
__all__ = [
    'filter_bugtasks_by_context',
    ]

from collections import defaultdict

from lp.registry.interfaces.product import IProduct


class ProductWeightCalculator:
    """Give higher weighing to tasks for the matching product."""

    def __init__(self, product):
        self.productID = product.id

    def __call__(self, bugtask):
        """Full weight is given to tasks for this product.

        Given that there must be a product task for a series of that product
        to have a task, we give no more weighting to a productseries task than
        any other.
        """
        if bugtask.productID == self.productID:
            if bugtask.productseriesID is None:
                return (1, bugtask)
        return (2, bugtask)


class SimpleWeightCalculator:
    """All tasks have the same weighting."""

    def __call__(self, bugtask):
        return (1, bugtask)


def get_weight_calculator(context):
    if IProduct.providedBy(context):
        return ProductWeightCalculator(context)
    else:
        return SimpleWeightCalculator()


def filter_bugtasks_by_context(context, bugtasks):
    """Return the bugtasks filtered so there is only one bug task per bug.

    The context is used to return the most relevent bugtask for that context.

    An initial constraint is to not require any database queries from this method.

    Current contexts that impact selection:
      IProduct
      IProductSeries
      IDistribution
      IDistroSeries
      ISourcePackage
    Others:
      get the first bugtask for any particular bug

    If the context is a Product, then return the product bug task if there is
    one.  If the context is a ProductSeries, then return the productseries
    task if there is one, and if there isn't, look for the product task.  A
    similar approach is taked for Distribution and distroseries.

    For source packages, we look for the source package task, followed by the
    distro source package, then the distroseries task, and lastly the distro
    task.

    If there is no specific matching task, we return the first task (the one
    with the smallest database id).
    """
    weight_calculator = get_weight_calculator(context)

    bug_mapping = defaultdict(list)
    for task in bugtasks:
        bug_mapping[task.bugID].append(weight_calculator(task))

    return [sorted(tasks)[0][1] for tasks in bug_mapping.itervalues()]
