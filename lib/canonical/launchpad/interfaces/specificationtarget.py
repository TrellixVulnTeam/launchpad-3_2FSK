# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Interfaces for things which have Specifications."""

__metaclass__ = type

__all__ = [
    'IHasSpecifications',
    'ISpecificationTarget',
    'ISpecificationGoal',
    ]

from zope.interface import Interface, Attribute

from canonical.launchpad import _

class IHasSpecifications(Interface):
    """An object that has specifications attached to it.
    
    For example, people, products and distributions have specifications
    associated with them, and you can use this interface to query those.
    """

    def specifications(quantity=None, sort=None, filter=None):
        """Specifications for this target.

        The sort is a dbschema which indicates the preferred sort order. The
        filter is an indicator of the kinds of specs to be returned, and
        appropriate filters depend on the kind of object this method is on.
        If there is a quantity, then limit the result to that number.

        In the case where the filter is [] or None, the content class will
        decide what its own appropriate "default" filter is. In some cases,
        it will show all specs, in others, all approved specs, and in
        others, all incomplete specs.
        """



class ISpecificationTarget(IHasSpecifications):
    """An interface for the objects which actually have unique
    specifications directly attached to them.
    """

    def getSpecification(name):
        """Returns the specification with the given name, for this target,
        or None.
        """


class ISpecificationGoal(ISpecificationTarget):
    """An interface for those things which can have specifications proposed
    as goals for them.
    """

    def acceptSpecificationGoal(spec):
        """Accepts the given specification as a goal for this item."""

    def declineSpecificationGoal(spec):
        """Declines the specification as a goal for this item."""

    def acceptSpecificationGoals(speclist):
        """Accepts the list of specifications as goals for this item.

        Returns the number of proposed specifications left.
        """

    def declineSpecificationGoals(speclist):
        """Declines the list of specifications as goals for this item.

        Returns the number of proposed specifications left.
        """

