# Copyright 2008, 2009 Canonical Ltd.  All rights reserved.

"""Branch targets."""

__metaclass__ = type
__all__ = [
    'branch_to_target',
    'PackageBranchTarget',
    'PersonBranchTarget',
    'ProductBranchTarget',
    ]

from zope.interface import implements

from canonical.launchpad.interfaces.branchtarget import IBranchTarget


def branch_to_target(branch):
    """Adapt an IBranch to an IBranchTarget."""
    return branch.target


class _BaseBranchTarget:

    def __eq__(self, other):
        return self.context == other.context

    def __ne__(self, other):
        return self.context != other.context


class PackageBranchTarget(_BaseBranchTarget):
    implements(IBranchTarget)

    def __init__(self, sourcepackage):
        self.sourcepackage = sourcepackage

    @property
    def name(self):
        """See `IBranchTarget`."""
        return self.sourcepackage.path

    @property
    def components(self):
        """See `IBranchTarget`."""
        return [
            self.sourcepackage.distribution,
            self.sourcepackage.distroseries,
            self.sourcepackage,
            ]

    @property
    def context(self):
        """See `IBranchTarget`."""
        return self.sourcepackage

    def getNamespace(self, owner):
        """See `IBranchTarget`."""
        from canonical.launchpad.database.branchnamespace import (
            PackageNamespace)
        return PackageNamespace(owner, self.sourcepackage)


class PersonBranchTarget(_BaseBranchTarget):
    implements(IBranchTarget)

    name = '+junk'

    def __init__(self, person):
        self.person = person

    @property
    def components(self):
        """See `IBranchTarget`."""
        return [self.person]

    @property
    def context(self):
        """See `IBranchTarget`."""
        return self.person

    def getNamespace(self, owner):
        """See `IBranchTarget`."""
        from canonical.launchpad.database.branchnamespace import (
            PersonalNamespace)
        return PersonalNamespace(owner)


class ProductBranchTarget(_BaseBranchTarget):
    implements(IBranchTarget)

    def __init__(self, product):
        self.product = product

    @property
    def components(self):
        """See `IBranchTarget`."""
        return [self.product]

    @property
    def context(self):
        """See `IBranchTarget`."""
        return self.product

    @property
    def name(self):
        """See `IBranchTarget`."""
        return self.product.name

    def getNamespace(self, owner):
        """See `IBranchTarget`."""
        from canonical.launchpad.database.branchnamespace import (
            ProductNamespace)
        return ProductNamespace(owner, self.product)
