# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Functions and classes that are subscribed to registry events."""

__metaclass__ = type

__all__ = [
    'product_licenses_modified',
    ]

from datetime import datetime
import textwrap

import pytz
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.person import (
    IPerson,
    IPersonViewRestricted,
    )
from lp.registry.interfaces.product import License
from lp.registry.model.personnotification import PersonNotification
from lp.services.config import config
from lp.services.mail.helpers import get_email_template
from lp.services.mail.sendmail import (
    format_address,
    simple_sendmail,
    )
from lp.services.webapp.menu import structured
from lp.services.webapp.publisher import (
    canonical_url,
    get_current_browser_request,
    )


# tracking emails is a pain, we want to just track any change to the @property
# validedemails, but then again we don't want validated, because it might not
# be. We want the notice to go out on a new email.
PERSON_FIELDS_MONITORED = [
    'preferredemail',
    'validatedemails'
]


def product_licenses_modified(product, event):
    """Send a notification if licenses changed and a license is special."""
    if not event.edited_fields:
        return
    licenses_changed = 'licenses' in event.edited_fields
    needs_notification = LicenseNotification.needs_notification(product)
    if licenses_changed and needs_notification:
        user = IPerson(event.user)
        notification = LicenseNotification(product, user)
        notification.send()
        notification.display()


class LicenseNotification:
    """Send notification about special licenses to the user."""

    def __init__(self, product, user):
        self.product = product
        self.user = user

    @staticmethod
    def needs_notification(product):
        licenses = list(product.licenses)
        return (
            License.OTHER_PROPRIETARY in licenses
            or License.OTHER_OPEN_SOURCE in licenses
            or [License.DONT_KNOW] == licenses)

    def getTemplateName(self):
        """Return the name of the email template for the licensing case."""
        licenses = list(self.product.licenses)
        if [License.DONT_KNOW] == licenses:
            template_name = 'product-license-dont-know.txt'
        elif License.OTHER_PROPRIETARY in licenses:
            template_name = 'product-license-other-proprietary.txt'
        else:
            template_name = 'product-license-other-open-source.txt'
        return template_name

    def getCommercialUseMessage(self):
        """Return a message explaining the current commercial subscription."""
        commercial_subscription = self.product.commercial_subscription
        if commercial_subscription is None:
            return ''
        iso_date = commercial_subscription.date_expires.date().isoformat()
        if not self.product.has_current_commercial_subscription:
            message = "%s's commercial subscription expired on %s."
        elif 'complimentary' in commercial_subscription.sales_system_id:
            message = (
                "%s's complimentary commercial subscription expires on %s.")
        else:
            message = "%s's commercial subscription expires on %s."
        message = message % (self.product.displayname, iso_date)
        return textwrap.fill(message, 72)

    def send(self):
        """Send a message to the user about the product's license."""
        if not self.needs_notification(self.product):
            # The project has a common license.
            return False
        user_address = format_address(
            self.user.displayname, self.user.preferredemail.email)
        from_address = format_address(
            "Launchpad", config.canonical.noreply_from_address)
        commercial_address = format_address(
            'Commercial', 'commercial@launchpad.net')
        substitutions = dict(
            user_displayname=self.user.displayname,
            user_name=self.user.name,
            product_name=self.product.name,
            product_url=canonical_url(self.product),
            commercial_use_expiration=self.getCommercialUseMessage(),
            )
        # Email the user about license policy.
        subject = (
            "License information for %(product_name)s "
            "in Launchpad" % substitutions)
        template = get_email_template(
            self.getTemplateName(), app='registry')
        message = template % substitutions
        simple_sendmail(
            from_address, user_address,
            subject, message, headers={'Reply-To': commercial_address})
        # Inform that Launchpad recognized the license change.
        self._addLicenseChangeToReviewWhiteboard()
        return True

    def display(self):
        """Show a message in a browser page about the product's license."""
        request = get_current_browser_request()
        message = self.getCommercialUseMessage()
        if request is None or message == '':
            return False
        safe_message = structured(
            '%s<br />Learn more about '
            '<a href="https://help.launchpad.net/CommercialHosting">'
            'commercial subscriptions</a>', message)
        request.response.addNotification(safe_message)
        return True

    @staticmethod
    def _formatDate(now=None):
        """Return the date formatted for messages."""
        if now is None:
            now = datetime.now(tz=pytz.UTC)
        return now.strftime('%Y-%m-%d')

    def _addLicenseChangeToReviewWhiteboard(self):
        """Update the whiteboard for the reviewer's benefit."""
        now = self._formatDate()
        whiteboard = 'User notified of license policy on %s.' % now
        naked_product = removeSecurityProxy(self.product)
        if naked_product.reviewer_whiteboard is None:
            naked_product.reviewer_whiteboard = whiteboard
        else:
            naked_product.reviewer_whiteboard += '\n' + whiteboard


def person_details_modified(person, event):
    """Send a notification if important details on a person change."""
    if not event.edited_fields:
        return

    # We want to keep tabs on which fields changed so we can attempt to have
    # an intelligent reply message on what just happened.
    changed_fields = set(PERSON_FIELDS_MONITORED) &  set(event.edited_fields)

    if changed_fields:
        user = IPersonViewRestricted(event.user)
        original_object = event.object_before_modification
        prev_preferred_email = original_object.preferredemail.email

        notification = PersonDetailsChangeNotification(
            changed_fields, user,
            override_noticeto=(user.displayname, prev_preferred_email))
        notification.send()


class PersonDetailsChangeNotification(object):
    """Schedule an email notification to the user about account changes"""

    def __init__(self, field, user, override_noticeto=None):
        """Notify the user that their account has changed

        :param field: the bit of account data that's altered
        :param user: the user that changed
        """
        self.changed = field
        self.user = user
        self.notification = PersonNotification()
        self.notification.person = user
        self.override_noticeto = override_noticeto

    def getTemplateName(self):
        """Return the name of the email template to use in the notification."""
        return 'person-details-change.txt'

    def send(self):
        """Send the notification to the user about their account change."""
        self.notification.subject = (
            "Your Launchpad.net account details have changed."
        )
        tpl_substitutions = dict(
            user_displayname=self.user.displayname,
            user_name=self.user.name,
            )
        template = get_email_template(
            self.getTemplateName(), app='registry')
        message = template % tpl_substitutions
        self.notification.body = message
        if self.override_noticeto:
            self.notification.send(
                sendto=(self.user.displayname, self.override_noticeto))
        else:
            self.notification.send()
        return True
