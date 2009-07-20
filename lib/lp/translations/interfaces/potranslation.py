# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

from zope.interface import Interface, Attribute

__metaclass__ = type

__all__ = ('IPOTranslation', )

class IPOTranslation(Interface):
    """A translation in a PO file."""

    translation = Attribute("A translation string.")
