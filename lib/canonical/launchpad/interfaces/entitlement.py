# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Entitlement interfaces."""

__metaclass__ = type

__all__ = [
    'EntitlementInvalidError',
    'EntitlementQuota',
    'EntitlementQuotaExceededError',
    'IEntitlement',
    'IEntitlementSet',
    ]

import sys
from zope.interface import Attribute, Interface
from zope.schema import Choice, Datetime, Int

from canonical.launchpad import _
from canonical.launchpad.fields import Whiteboard

class EntitlementQuotaExceededError(Exception):
    """The quota has been exceeded for the entitlement."""


class EntitlementInvalidError(Exception):
    """The entitlement is not valid."""


class IEntitlement(Interface):
    """An entitlement the right to use a specific feature in Launchpad.

    Entitlements can be granted in an unlimited quantity or with a given
    quota.  They have a start date and optionally an expiration date.  An
    entitlement is invalid if it is not active, the quota is exceeded, or if
    it is expired.
    """

    id = Int(
        title=_("Entitlement id"),
        required=True,
        readonly=True)
    person = Choice(
        title=_('Person'),
        required=True,
        readonly=True,
        vocabulary='ValidPersonOrTeam',
        description=_("Person or team to whom the entitlements is assigned."))
    date_created = Datetime(
        title=_("Date Created"),
        description=_("The date on which this entitlement was created."),
        required=True,
        readonly=True)
    date_starts = Datetime(
        title=_("Date Starts"),
        description=_("The date on which this entitlement starts."),
        readonly=True)
    date_expires = Datetime(
        title=_("Date Expires"),
        description=_("The date on which this entitlement expires."),
        readonly=True)
    entitlement_type = Choice(
        title=_("Type of entitlement."),
        required=True,
        vocabulary='EntitlementType',
        description=_("Type of feature for this entitlement."),
        readonly=True)
    quota = Int(
        title=_("Allocated quota."),
        required=True,
        description=_(
            "A quota is the number of a feature allowed by this entitlement, "
            "for instance 50 private bugs."))
    amount_used = Int(
        title=_("Amount used."),
        description=_(
            "The amount used is the number of instances of a feature "
            "the person has used so far."))
    registrant = Choice(
        title=_('Registrant'),
        vocabulary='ValidPersonOrTeam',
        description=_(
            "Person who registered the entitlement.  "
            "May be None if created automatically."),
        readonly=True)
    approved_by = Choice(
        title=_('Approved By'),
        vocabulary='ValidPersonOrTeam',
        description=_(
            "Person who approved the entitlement.  "
            "May be None if created automatically."),
        readonly=True)
    state = Choice(
        title=_("State"),
        required=True,
        vocabulary='EntitlementState',
        description = _("Current state of the entitlement."))

    whiteboard = Whiteboard(title=_('Whiteboard'), required=False,
        description=_('Notes on the current status of the entitlement.'))

    is_valid = Attribute(
        "Is this entitlement valid?")

    exceeded_quota = Attribute(
        "If the quota is not unlimited, is it exceeded?")

    in_date_range = Attribute(
        "Has the start date passed but not the expiration date?")

    def incrementAmountUsed():
        """Add one to the amount used."""


class IEntitlementSet(Interface):
    """Interface representing a set of Entitlements."""

    def __getitem__(entitlement_id):
        """Return the entitlement with the given id.

        Raise NotFoundError if there is no such entitlement.
        """

    def __iter__():
        """Return an iterator that will go through all entitlements."""

    def count():
        """Return the number of entitlements in the database.

        Only counts public entitlementes.
        """

    def get(entitlement_id, default=None):
        """Return the entitlement with the given id.

        Return the default value if there is no such entitlement.
        """

    def getForPerson(person):
        """Return the entitlements for the person or team.

        Get all entitlements for a person.
        """

    def getValidForPerson(person):
        """Return a list of valid entitlements for the person or team.

        Get all valid entitlements for a person.  None is returned if no valid
        entitlements are found.
        """

    def new(external_id, person, quota, entitlement_type, state,
            date_created=None, date_expires=None, date_starts=None,
            amount_used=None, registrant=None, approved_by=None):
        """Create a new entitlement."""


class EntitlementQuota:
    """This class stores constants for entitlements quotas."""

    UNLIMITED = 0
