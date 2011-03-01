# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Subscribers for `IFAQ`."""

__metaclass__ = type
__all__ = ['update_last_updated']


from canonical.database.constants import UTC_NOW
from lp.registry.interfaces.person import IPerson


def update_last_updated(faq, event):
    """Update the last_updated_by and date_last_updated attributes."""
    faq.last_updated_by = IPerson(event.user)
    faq.date_last_updated = UTC_NOW
