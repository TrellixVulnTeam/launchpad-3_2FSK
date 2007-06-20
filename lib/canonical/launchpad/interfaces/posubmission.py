# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute
from zope.schema import Object, Datetime, Bool
from canonical.launchpad import _

__metaclass__ = type
__all__ = [
    'IPOSubmission',
    'IPOSubmissionSet'
    ]

class IPOSubmissionSet(Interface):
    """The set of submissions we have in our database."""

    def getPOSubmissionByID(id):
        """Return the IPOsubmission with the given id or None.

        :arg id: IPOSubmission.id
        """


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

    active = Bool(
        title=_("Whether this submission is active."),
        required=True)
    published = Bool(
        title=_("Whether this submission is published."),
        required=True)

    def destroySelf():
        """Remove this object.

        It should not be referenced by any other object.
        """

    def suggestion_htmlid(for_pomsgset, description='suggestion'):
        """Unique identifier for self as suggestion for POMsgSet.

        Constructs an identifier suitable for use in HTML.

        :description: a keyword to be embedded in the id string.  Must be
        suitable for use in an HTML element id.
        """
