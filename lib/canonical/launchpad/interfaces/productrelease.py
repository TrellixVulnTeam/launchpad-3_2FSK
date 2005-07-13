# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Product release interfaces."""

__metaclass__ = type

__all__ = [
    'IProductReleaseSet',
    'IProductRelease',
    ]

from zope.schema import Choice, Datetime, Int, Text, TextLine
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory

from canonical.lp.dbschema import UpstreamFileType

_ = MessageIDFactory('launchpad')

class IProductReleaseSet(Interface):
    """Auxiliar class for ProductRelease handling."""

    def new(version, owner, productseries, title=None, shortdesc=None,
            description=None, changelog=None):
        """Create a new ProductRelease"""


class IProductRelease(Interface):
    """A specific release (i.e. has a version) of a product. For example,
    Mozilla 1.7.2 or Apache 2.0.48."""
    id = Int(title=_('ID'), required=True, readonly=True)
    datereleased = Datetime(title=_('Date Released'), required=True,
                            readonly=False)
    datecreated = Datetime(title=_('Date Registered'), required=True,
                            readonly=True)
    version = TextLine(title=_('Version'), required=True, readonly=True)
    owner = Int(title=_('Owner'), required=True, readonly=True)
    productseries = Choice(title=_('ProductSeries'), required=True,
                           vocabulary='FilteredProductSeries')
    title = TextLine(title=_('Title'), required=False)
    summary = Text(title=_("Summary"), required=False)
    description = Text(title=_("Description"), required=False)
    changelog = Text(title=_('Changelog'), required=False)
    datecreated = TextLine(title=_('Date Created'), description=_("""The
        date this productrelease was created in Launchpad."""))

    displayname = Attribute(_('Constructed displayname for a productrelease.'))
    manifest = Attribute(_('Manifest Information.'))
    product = Attribute(_('Retrive Product Instance from ProductSeries.'))
    files = Attribute(_('Iterable of product release files.'))

    def addFileAlias(alias_id, file_type=UpstreamFileType.CODETARBALL):
        """Add a link between this product and a library file alias."""
