# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Functions and classes that are subscribed to registry events."""

__metaclass__ = type

__all__ = [
    'product_licenses_modified',
    ]

from datetime import datetime

import pytz

from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import License
from lp.services.config import config
from lp.services.mail.helpers import get_email_template
from lp.services.mail.sendmail import (
    format_address,
    simple_sendmail,
    )
from lp.services.webapp.publisher import canonical_url


def product_licenses_modified(product, event):
    """Send a notification if licenses changed and a license is special."""
    licenses_changed = 'licenses' in event.edited_fields
    needs_notification = LicenseNotification.needs_notification(product)
    if licenses_changed and needs_notification:
        user = IPerson(event.user)
        notification = LicenseNotification(product, user)
        notification.send()


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
        licenses = list(self.product.licenses)
        if [License.DONT_KNOW] == licenses:
            template_name = 'product-license-dont-know.txt'
        elif License.OTHER_PROPRIETARY in licenses:
            template_name = 'product-license-other-proprietary.txt'
        else:
            template_name = 'product-license-other-open-source.txt'
        return template_name

    def getCommercialUseMessage(self):
        commercial_subscription = self.product.commercial_subscription
        if commercial_subscription is None:
            return ''
        iso_date = commercial_subscription.date_expires.date().isoformat()
        if not self.product.has_current_commercial_subscription:
            return (
                "%s's commercial subscription expired on %s" %
                (self.product.displayname, iso_date))
        elif 'complimentary' in commercial_subscription.sales_system_id:
            return (
                "%s's complimentary commercial subscription expires on %s" %
                (self.product.displayname, iso_date))
        else:
            return (
                "%s's commercial subscription expires on %s" %
                (self.product.displayname, iso_date))

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

    @staticmethod
    def _indent(text):
        """Indent the text to be included in the message."""
        if text is None:
            return None
        text = '\n    '.join(line for line in text.split('\n'))
        text = '    ' + text
        return text

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
