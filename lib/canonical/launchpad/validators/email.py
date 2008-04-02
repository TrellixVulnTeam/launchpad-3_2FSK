# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""EmailAdress validator"""

__metaclass__ = type

import re

from canonical.launchpad import _
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp.menu import structured


def valid_email(emailaddr):
    """Validate an email address.

    >>> valid_email('kiko.async@hotmail.com')
    True
    >>> valid_email('kiko+async@hotmail.com')
    True
    >>> valid_email('kiko-async@hotmail.com')
    True
    >>> valid_email('kiko_async@hotmail.com')
    True
    >>> valid_email('kiko@async.com.br')
    True
    >>> valid_email('kiko@canonical.com')
    True
    >>> valid_email('kiko@UBUNTU.COM')
    True
    >>> valid_email('i@tv')
    True
    >>> valid_email('kiko@gnu.info')
    True
    >>> valid_email('user@z.de')
    True

    >>> valid_email('user@z..de')
    False
    >>> valid_email('user@.z.de')
    False

    As per OOPS-256D762:

    >>> valid_email('keith@risby-family.co.uk')
    True
    >>> valid_email('keith@risby-family-.co.uk')
    False
    >>> valid_email('keith@-risby-family.co.uk')
    False
    """
    email_re = r"^[_\.0-9a-zA-Z-+]+@(([0-9a-zA-Z-]{1,}\.)*)[a-zA-Z]{2,}$"
    email_match = re.match(email_re, emailaddr)
    if not email_match:
        return False
    host_minus_tld = email_match.group(1)
    if not host_minus_tld:
        return True
    for part in host_minus_tld.split("."):
        if part.startswith("-") or part.endswith("-"):
            return False
    return True


def email_validator(emailaddr):
    """Raise a LaunchpadValidationError if the email is invalid.

    Otherwise, return True.

    >>> email_validator('bugs@example.com')
    True
    >>> email_validator('not-valid')
    Traceback (most recent call last):
    ...
    LaunchpadValidationError: Invalid email 'not-valid'.
    """
    if not valid_email(emailaddr):
        raise LaunchpadValidationError(_("Invalid email '%s'.") % emailaddr)
    return True
