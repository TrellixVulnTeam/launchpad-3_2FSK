# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Cve Reference interfaces. A CVE Reference is not an old-style cveref,
it's part of the CVE database structure we get from cve.mitre.org, and
describes a link between the CVE and another vulnerability tracking system.
It is to CVE what a Watch is to Malone.
"""

__metaclass__ = type

__all__ = ['ICveReference']

from zope.interface import Interface
from zope.schema import Int, TextLine, Text
from canonical.launchpad import _

class ICveReference(Interface):
    """A CVE Reference."""

    id = Int(title=_("Reference ID"), required=True, readonly=True)
    cve = Int(title=_('Bug ID'), required=True, readonly=True)
    source = TextLine(title=_("Source"), required=True, readonly=True)
    content=Text(title=_("Content"), required=True)
    url = TextLine(title=_("URL"), required=False)

