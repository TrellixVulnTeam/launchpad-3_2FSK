# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Validators for the .name attribute (defined in various schemas.)"""

__metaclass__ = type

import re
from textwrap import dedent

from canonical.launchpad import _
from canonical.launchpad.validators import LaunchpadValidationError

valid_name_pattern = re.compile(r"^[a-z0-9][a-z0-9\+\.\-]*$")
invalid_name_pattern = re.compile(r"^[^a-z0-9]+|[^a-z0-9\\+\\.\\-]+")

def sanitize_name(name):
    """Remove from the given name all characters that are not allowed on names.

    The characters not allowed in Launchpad names are described by
    invalid_name_pattern.

    >>> sanitize_name('foo_bar')
    'foobar'
    >>> sanitize_name('baz bar $fd')
    'bazbarfd'
    """
    return invalid_name_pattern.sub('', name)

def valid_name(name):
    """Return True if the name is valid, otherwise False.

    Lauchpad `name` attributes are designed for use as url components
    and short unique identifiers to things.

    The default name constraints may be too strict for some objects,
    such as binary packages or arch branches where naming conventions already
    exists, so they may use their own specialized name validators
    """
    if valid_name_pattern.match(name):
        return True
    return False

def name_validator(name):
    """Return True if the name is valid, or raise a LaunchpadValidationError"""
    if not valid_name(name):
        raise LaunchpadValidationError(_(dedent("""
            Invalid name '%s'. Names must start with a letter or
            number and be lowercase. The characters <samp>+</samp>,
            <samp>-</samp> and <samp>.</samp> are also allowed after the
            first character.
            """)), name)
    return True

