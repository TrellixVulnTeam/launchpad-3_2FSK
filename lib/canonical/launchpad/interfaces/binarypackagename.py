# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Binary package name interfaces."""

__metaclass__ = type

__all__ = [
    'IBinaryPackageName',
    'IBinaryPackageNameSet',
    ]

from zope.schema import Int, TextLine
from zope.interface import Interface, Attribute

from canonical.launchpad import _
from canonical.launchpad.validators.name import name_validator 


class IBinaryPackageName(Interface):
    id = Int(title=_('ID'), required=True)

    name = TextLine(title=_('Valid Binary package name'),
                    required=True, constraint=name_validator)

    binarypackages = Attribute('binarypackages')

    def nameSelector(sourcepackage=None, selected=None):
        """Return browser-ready HTML to select a Binary Package Name"""

    def __unicode__():
        """Return the name"""


class IBinaryPackageNameSet(Interface):

    def __getitem__(name):
        """Retrieve a binarypackagename by name."""

    def __iter__():
        """Iterate over names"""

    def findByName(name):
        """Find binarypackagenames by its name or part of it"""

    def queryByName(name):
        """Return a binary package name.

        If there is no matching binary package name, return None.
        """

    def new(name):
        """Create a new binary package name."""

    def getOrCreateByName(name):
        """Get a binary package by name, creating it if necessary."""

    def ensure(name):
        """Ensure that the given BinaryPackageName exists, creating it
        if necessary.

        Returns the BinaryPackageName
        """
