# Copyright 2006-2007 Canonical Ltd.  All rights reserved.
"""
Unified support for different translation import and export formats.
"""
__metaclass__ = type

# XXX CarlosPerelloMarin 20070423: Reviewer, how could I format this to fit
# in 79 columns? Maybe using two imports?
# from canonical.launchpad import components
# from components.translationformats.translation_import import *
from canonical.launchpad.components.translationformats.translation_import import *

# XXX CarlosPerelloMarin 20070609: POHeader still needs to be used outside the
# abstraction layer until we get rid of IPOFile.header which is .po specific.
from canonical.launchpad.components.translationformats.gettext_po_parser import (
    POHeader)
