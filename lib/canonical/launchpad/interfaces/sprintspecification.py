# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Interfaces for linking between Sprint and a Specification."""

__metaclass__ = type

__all__ = [
    'ISprintSpecification',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Int, Text
from canonical.launchpad import _

class ISprintSpecification(Interface):
    """A link between a Sprint and a Specification."""

    id = Attribute("The ID of this sprint/spec link. We expose this because"
        "there is no uniqueness of spec names across products and of course "
        "distros, so there is no unique way to identify a sprintspec by "
        "spec name, because multiple specs at a sprint could have the same "
        "name.")
    sprint = Choice(title=_('Sprint'), required=True, readonly=True,
        description=_("The meeting or sprint at which this specification will "
        "be discussed or implemented."), vocabulary='Sprint')
    specification = Int(title=_('Specification'), required=True,
        readonly=True)
    status = Choice(title=_('Agenda Status'), required=True,
        vocabulary='SprintSpecificationStatus')
    whiteboard = Text(title=_('Whiteboard'), required=False,
        description=_(
            "Any reasoning or rationale for the status you set here."
            "Your changes will override the current text. Note that "
            "this is purely related to this spec at this meeting, not "
            "the specification in general."))

    is_confirmed = Attribute("True if this spec is confirmed for the "
        "agenda of this sprint.")

