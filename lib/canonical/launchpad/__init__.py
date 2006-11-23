# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

# This deprecation causes a load of spurious DeprecationWarnings.
# Hopefully this decision will be reversed before 3.3 is released causing
# this to become a load of spurious exceptions. Bug 39883.
import warnings
warnings.filterwarnings(
        'ignore', r'.*Use explicit i18n:translate=""', DeprecationWarning
        )

# Modules should 'from canonical.launchpad import _' instead of constructing
# their own MessageFactory
from zope.i18nmessageid import MessageFactory
_ = MessageFactory("launchpad")

# Load versioninfo.py so that we get errors on start-up rather than waiting
# for first page load.
import canonical.launchpad.versioninfo
