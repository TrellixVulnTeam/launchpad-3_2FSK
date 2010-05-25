# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Security contact interfaces."""

__metaclass__ = type

__all__ = [
    'IHasSecurityContact',
    ]

from zope.interface import Interface

from lazr.restful.declarations import exported

from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice


class IHasSecurityContact(Interface):
    """An object that has a security contact."""

    security_contact = exported(PublicPersonChoice(
        title=_("Security Contact"),
        description=_(
            "The person or team who handles security-related bug reports"),
        required=False, vocabulary='ValidPersonOrTeam'))
