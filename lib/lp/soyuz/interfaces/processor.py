# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Processor interfaces."""

__metaclass__ = type

__all__ = [
    'IProcessor',
    'IProcessorFamily',
    'IProcessorFamilySet',
    ]

from canonical.launchpad import _

from zope.interface import Interface, Attribute
from zope.schema import Bool

class IProcessor(Interface):
    """The SQLObject Processor Interface"""
    id = Attribute("The Processor ID")
    family = Attribute("The Processor Family Reference")
    name = Attribute("The Processor Name")
    title = Attribute("The Processor Title")
    description = Attribute("The Processor Description")

class IProcessorFamily(Interface):
    """The SQLObject ProcessorFamily Interface"""
    id = Attribute("The ProcessorFamily ID")
    name = Attribute("The Processor Family Name")
    title = Attribute("The Processor Family Title")
    description = Attribute("The Processor Name Description")
    processors = Attribute("The Processors in this family.")
    restricted = Bool(title=_("Whether this family is restricted."))


class IProcessorFamilySet(Interface):
    """Operations related to ProcessorFamily instances."""
    def getByName(name):
        """Return the ProcessorFamily instance with the matching name.

        :param name: The name to look for.

        :return: A `IProcessorFamily` instance if found, None otherwise.
        """

    def getByProcessorName(name):
        """Given a processor name return the ProcessorFamily it belongs to.

        :param name: The name of the processor to look for.

        :return: A `IProcessorFamily` instance if found, None otherwise.
        """

    def new(name, title, description, processors, restricted):
        """Create a new processor family.

        :param name: Name of the family.
        :param title: Title for the family.
        :param description: Extended description of the family
        :param processors: The processors in this family.
        :param restricted: Whether the processor family is restricted
        :return: a `IProcessorFamily`.
        """
