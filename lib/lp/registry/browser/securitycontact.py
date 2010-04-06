# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser view classes for security contacts."""

__metaclass__ = type
__all__ = ["SecurityContactEditView"]

from canonical.launchpad.interfaces.launchpad import IHasSecurityContact
from canonical.launchpad.webapp import (
    canonical_url, LaunchpadFormView, action)


class SecurityContactEditView(LaunchpadFormView):
    """Browser view for editing the security contact.

    self.context is assumed to implement IHasSecurityContact.
    """

    schema = IHasSecurityContact
    field_names = ['security_contact']

    @property
    def label(self):
        """See `LaunchpadFormView`."""
        return 'Edit %s security contact' % self.context.displayname

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @property
    def initial_values(self):
        return {
            'security_contact': self.context.security_contact}

    @action('Change', name='change')
    def change_action(self, action, data):
        security_contact = data['security_contact']
        if self.context.security_contact == security_contact:
            return

        self.context.security_contact = security_contact
        if security_contact:
            security_contact_display_value = None
            if security_contact.preferredemail:
                # The security contact was set to a new person or team.
                security_contact_display_value = (
                    security_contact.preferredemail.email)
            else:
                # The security contact doesn't have a preferred email address,
                # so it must be a team.
                assert security_contact.isTeam(), (
                    "Expected security contact with no email address "
                    "to be a team.")
                security_contact_display_value = security_contact.displayname

            self.request.response.addNotification(
                "Successfully changed the security contact to %s" %
                security_contact_display_value)
        else:
            self.request.response.addNotification(
                "Successfully removed the security contact")

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url
