# Copyright 2005 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute

__metaclass__ = type
__all__ = ('IPOSubmission', )

class IPOSubmission(Interface):
    """A submission of a translation to a PO file."""

    id = Attribute("The ID for this submission.")
    pomsgset = Attribute("The PO message set for which is this submission.")
    pluralform = Attribute("The # of pluralform that we are submitting.")
    potranslation = Attribute("The translation that was submitted.")
    datecreated = Attribute("The date we saw this submission.")
    origin = Attribute("Where the submission originally came from.")
    person = Attribute("The owner of this submission, if we have one.")
    validationstatus = Attribute(
        "The status of the validation of the translation.")
    active_selections = Attribute(
        "The IPOSelection that has this submission as active.")
    published_selections = Attribute(
        "The IPOSelection that has this submission as published.")
