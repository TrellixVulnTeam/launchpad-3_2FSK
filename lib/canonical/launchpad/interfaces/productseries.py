

# Zope schema imports
from zope.schema import Bool, Bytes, Choice, Datetime, Int, Text, \
                        TextLine, Password
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory
_ = MessageIDFactory('launchpad')

class IProductSeries(Interface):
    """A series of releases. For example "2.0" or "1.3" or "dev"."""
    # XXX Mark Shuttleworth 14/10/04 would like to get rid of id in
    # interfaces, as soon as SQLobject allows using the object directly
    # instead of using object.id.
    id = Int(title=_('ID'))
    # field names
    product = Choice( title=_('Product'), required=True,
                      vocabulary='Product')
    name = Text(title=_('Name'), required=True)
    title = Attribute('Title')
    displayname = Text( title=_('Display Name'), required=True)
    shortdesc = Text(title=_("Short Description"), required=True)
    # convenient joins
    releases = Attribute(_("An iterator over the releases in this \
                                  Series."))
    def getRelease(version):
        """Get the release in this series that has the specified version."""

    
class IProductSeriesSet(Interface):
    """A set of ProductSeries objects. Note that it can be restricted by
    initialising it with a product, in which case it iterates over only the
    Product Release Series' for that Product."""

    def __iter__():
        """Return an interator over the ProductSeries', constrained by
        self.product if the ProductSeries was initialised that way."""

    def __getitem__(name):
        """Return a specific ProductSeries, by name, constrained by the
        self.product. For __getitem__, a self.product is absolutely
        required, as ProductSeries names are only unique within the Product
        they cover."""

