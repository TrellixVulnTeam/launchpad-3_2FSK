# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Component interfaces."""

__metaclass__ = type

__all__ = [
    'IComponent',
    'IComponentSelection',
    'IComponentSet'
    ]

from zope.interface import Interface, Attribute
from zope.schema import Choice

from canonical.launchpad import _

class IComponent(Interface):
    """Represents the Component table.

    This class represents the Component table, which stores valid
    distribution components; for Ubuntu this means, for instance,
    'main', 'restricted', 'universe', etc.
    """
    id = Attribute("The ID")
    name = Choice(
        title=_("Component Name"), vocabulary="Component", required=True)


class IComponentSelection(Interface):
    """Represents a single component allowed within a DistroSeries."""
    id = Attribute("The ID")
    distroseries = Attribute("Target DistroSeries")
    component = Attribute("Selected Component")


class IComponentSet(Interface):
    """Set manipulation tools for the Component table."""

    def __iter__():
        """Iterate over components."""

    def __getitem__(name):
        """Retrieve a component by name"""

    def get(component_id):
        """Return the IComponent with the given component_id."""

    def ensure(name):
        """Ensure the existence of a component with given name."""

    def new(name):
        """Create a new component."""

