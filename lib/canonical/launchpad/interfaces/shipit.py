# Copyright 2005 Canonical Ltd.  All rights reserved.

__all__ = ['IStandardShipItRequest', 'IStandardShipItRequestSet',
           'IRequestedCDs', 'IShippingRequest', 'IShippingRequestSet',
           'ShippingRequestStatus', 'IShipment', 'IShippingRun',
           'IShipItCountry', 'IShippingRunSet', 'IShipmentSet',
           'ShippingRequestPriority', 'IShipItReport', 'IShipItReportSet',
           'IShippingRequestAdmin', 'IShippingRequestEdit',
           'SOFT_MAX_SHIPPINGRUN_SIZE', 'ShipItConstants']

from zope.schema import Bool, Choice, Int, Datetime, Text, TextLine
from zope.interface import Interface, Attribute, implements
from zope.schema.interfaces import IChoice
from zope.app.form.browser.itemswidgets import DropdownWidget

from canonical.lp.dbschema import ShipItDistroRelease
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.interfaces.validation import (
    validate_shipit_recipientdisplayname, validate_shipit_phone,
    validate_shipit_city, validate_shipit_addressline1,
    validate_shipit_addressline2, validate_shipit_organization,
    validate_shipit_province)

from canonical.launchpad import _

# The maximum number of requests in a single shipping run
SOFT_MAX_SHIPPINGRUN_SIZE = 10000


def _validate_positive_int(value):
    """Return True if the given value is a positive integer.

    If it's not a positive integer, then raise a LaunchpadValidationError.
    You must not pass non-unicode type objects to this function.
    """
    assert isinstance(value, int)
    if value < 0:
        raise LaunchpadValidationError(_(
            "Quantities must be greater than or equal 0."))
    else:
        return True


class ShipItConstants:
    ubuntu_url = 'https://shipit.ubuntu.com'
    kubuntu_url = 'https://shipit.kubuntu.com'
    edubuntu_url = 'https://shipit.edubuntu.com'
    current_distrorelease = ShipItDistroRelease.DAPPER


class IEmptyDefaultChoice(IChoice):
    pass


class EmptyDefaultChoice(Choice):
    implements(IEmptyDefaultChoice)


# XXX: This sould probably be moved somewhere else, but as I need to get this
# in production ASAP I'm leaving it here for now. -- Guilherme Salgado
# 2005-10-03
class EmptyDefaultDropdownWidget(DropdownWidget):
    """A dropdown widget in which the default option is one that is not part
    of its vocabulary.
    """
    firstItem = True

    def renderItems(self, value):
        items = DropdownWidget.renderItems(self, value)
        option = '<option value="">Choose one</option>'
        items.insert(0, option)
        return items


class IShipItCountry(Interface):
    """This schema is only to get the Country widget."""

    country = EmptyDefaultChoice(title=_('Country'), required=True, 
                     vocabulary='CountryName')


class IShippingRequest(Interface):
    """A shipping request."""

    id = Int(title=_('The unique ID'), required=True, readonly=True)

    recipient = Int(title=_('Recipient'), required=True, readonly=True)

    daterequested = Datetime(
        title=_('Date of Request'), required=True, readonly=True)

    approved = Bool(
        title=_('Is This Request Approved?'), required=False, readonly=False)

    whoapproved = Int(
        title=_('Who Approved'), required=False, readonly=False,
        description=_('Automatically approved or someone approved?'))

    cancelled = Bool(
        title=_('Cancelled?'), required=False, readonly=False,
        description=_('The user can decide to cancel his request, or '
                      'the ShipIt operator can do it.'))

    whocancelled = Int(
        title=_('Who Cancelled'), required=False, readonly=False)

    reason = Text(
        title=_('Want more CDs?'), required=False, readonly=False,
        description=_("If none of the options above suit your needs, please "
                      "explain here how many CDs you want and why."))

    highpriority = Bool(
        title=_('High Priority?'), required=False, readonly=False,
        description=_('Is this a high priority request?'))

    recipientdisplayname = TextLine(
            title=_('Name'), required=True, readonly=False,
            constraint=validate_shipit_recipientdisplayname,
            description=_("The name of the person who's going to receive "
                          "this order.")
            )
    addressline1 = TextLine(
            title=_('Address'), required=True, readonly=False,
            constraint=validate_shipit_addressline1,
            description=_('The address to where the CDs will be shipped '
                          '(Line 1)')
            )
    addressline2 = TextLine(
            title=_(''), required=False, readonly=False,
            constraint=validate_shipit_addressline2,
            description=_('The address to where the CDs will be shipped '
                          '(Line 2)')
            )
    city = TextLine(
            title=_('City/Town/etc'), required=True, readonly=False,
            constraint=validate_shipit_city,
            description=_('The City/Town/Village/etc to where the CDs will be '
                          'shipped.')
            )
    province = TextLine(
            title=_('State/Province'), required=False, readonly=False,
            constraint=validate_shipit_province,
            description=_('The State/Province/etc to where the CDs will be '
                          'shipped.')
            )
    country = EmptyDefaultChoice(
            title=_('Country'), required=True, readonly=False,
            vocabulary='CountryName',
            description=_('The Country to where the CDs will be shipped.')
            )
    postcode = TextLine(
            title=_('Postcode'), required=False, readonly=False,
            description=_('The Postcode to where the CDs will be shipped.')
            )
    phone = TextLine(
            title=_('Phone'), required=True, readonly=False,
            constraint=validate_shipit_phone,
            description=_('[(+CountryCode) number] e.g. (+55) 16 33619445')
            )
    organization = TextLine(
            title=_('Organization'), required=False, readonly=False,
            constraint=validate_shipit_organization,
            description=_('The Organization requesting the CDs')
            )

    recipient_email = Attribute(_("The recipient's email address."))
    shipment = Attribute(_(
        "This request's Shipment or None if the request wasn't shipped yet."))
    countrycode = Attribute(
        _("The iso3166code2 code of this request's country. Can't be None."))
    shippingservice = Attribute(
        _("The shipping service used to ship this request. Can't be None."))

    def getTotalCDs():
        """Return the total number of CDs in this request."""

    def getTotalApprovedCDs():
        """Return the total number of approved CDs in this request."""

    def isDenied():
        """Return True if this request was denied.
        
        A denied request has self.approved == False, while a request that's
        pending approval has self.approved == None.
        """

    def getAllRequestedCDs():
        """Return all RequestedCDs of this ShippingRequest."""

    def getRequestedCDsGroupedByFlavourAndArch():
        """Return a dictionary mapping ShipItFlavours and ShipItArchitectures
        to the RequestedCDs objects of that architecture and flavour.
        """

    def getQuantitiesByFlavour(flavour):
        """Return a dictionary mapping ShipItArchitectures to the RequestedCDs
        objects of that architecture and the given flavour.
        """

    def setQuantitiesBasedOnStandardRequest(request_type):
        """Set the quantities specified for the flavour in the given standard
        request type to this request.
        """

    def setQuantities(quantities):
        """Set the quantities of this request by either creating new
        RequestedCDs objects or changing existing ones.

        :quantities: must be a dictionary mapping flavours to architectures
                     and quantities, i.e.
                     {ShipItFlavour.UBUNTU:
                        {ShipItArchitecture.X86: quantity1,
                         ShipItArchitecture.PPC: quantity2}
                     }
        """

    def setApprovedQuantities(quantities):
        """Set the approved quantities using the given values.

        :quantities: must be a dictionary mapping flavours to architectures
                     and quantities, i.e.
                     {ShipItFlavour.UBUNTU:
                        {ShipItArchitecture.X86: quantity1,
                         ShipItArchitecture.PPC: quantity2}
                     }

        You must not set approved quantities on a non-approved request.
        """

    def isAwaitingApproval():
        """Return True if this request is still waiting for approval."""

    def isApproved():
        """Return True if this request was approved."""

    def deny():
        """Deny this request."""

    def clearApproval():
        """Mark this request as waiting for approval.

        This method should be used only on approved requests.
        """

    def approve(whoapproved=None):
        """Approve this request with the exact quantities as it was submitted.

        This will set the approved attribute to True and the whoapproved
        attribute to whoapproved. If whoapproved is None, that means this
        request was auto approved.

        This method can only be called on non-cancelled non-approved requests.
        """

    def cancel(whocancelled):
        """Cancel this request.
        
        This is done by setting cancelled=True and whocancelled=whocancelled
        on this request.
        This method will also set quantityx86approved, quantityppcapproved, 
        quantityamd64approved, approved and whoapproved to None.
        """


class ShippingRequestStatus:
    """The status of a ShippingRequest."""

    PENDING = 'pending'
    APPROVED = 'approved'
    DENIED = 'denied'
    ALL = 'all'


class IShippingRequestSet(Interface):
    """The set of all ShippingRequests"""

    def new(recipient, recipientdisplayname, country, city, addressline1,
            phone, addressline2=None, province=None, postcode=None,
            organization=None, reason=None):
        """Create and return a new ShippingRequest.

        You must not create a new request for a recipient that already has a 
        currentShipItRequest. Refer to IPerson.currentShipItRequest() for more
        information about what is a current request.
        """

    def exportRequestsToFiles(priority, ztm):
        """Export all approved, unshipped and non-cancelled into CSV files.

        Group approved, unshipped and non-cancelled requests into one or more
        ShippingRuns with at most SOFT_MAX_SHIPPINGRUN_SIZE requests each 
        and for each ShippingRun export it into a CSV file and upload it to 
        the Librarian.
        """

    def getOldestPending():
        """Return the oldest request with status PENDING.
        
        Return None if there's no requests with status PENDING.
        """

    def getUnshippedRequests(priority):
        """Return all requests that are eligible for shipping.

        These are approved requests that weren't shipped yet.
        """

    def get(id, default=None):
        """Return the ShippingRequest with the given id.
        
        Return the default value if there's no ShippingRequest with this id.
        """

    def search(status=ShippingRequestStatus.ALL, flavour=None,
               recipient_text=None, include_cancelled=True):
        """Search for requests that match the given arguments."""

    def generateShipmentSizeBasedReport():
        """Generate a csv file with the size of shipments and the number of
        shipments of that size.
        """

    def generateCountryBasedReport():
        """Generate a csv file with statiscs about orders placed by country."""

    def generateWeekBasedReport(start_date, end_date):
        """Generate a csv file with statistics about orders placed by week.

        Only the orders placed between start_date and end_date are considered.
        """


class IRequestedCDs(Interface):

    id = Int(title=_('The unique ID'), required=True, readonly=True)
    request = Int(title=_('The ShippingRequest'), required=True, readonly=True)
    distrorelease = Int(title=_('Distro Release'), required=True, readonly=True)
    flavour = Choice(title=_('Distro Flavour'), required=True, readonly=True,
                     vocabulary='ShipItFlavour')
    architecture = Int(title=_('Architecture'), required=True, readonly=True)
    quantity = Int(
        title=_('The number of CDs'), required=True, readonly=False,
        description=_('Number of requested CDs for this architecture.'),
        constraint=_validate_positive_int)
    quantityapproved = Int(
        title=_('Quantity Approved'), required=False, readonly=False,
        description=_('Number of approved CDs for this architecture.'),
        constraint=_validate_positive_int)
    description = Attribute(_('A text description of this IRequestedCDs.'))


class IStandardShipItRequest(Interface):
    """A standard ShipIt request."""

    id = Int(title=_('The unique ID'), required=True, readonly=True)

    flavour = Choice(title=_('Distribution Flavour'), required=True,
                     readonly=False, vocabulary='ShipItFlavour')
    quantityx86 = Int(
        title=_('PC CDs'), required=True, readonly=False,
        description=_('Number of PC CDs in this request.'),
        constraint=_validate_positive_int)

    quantityppc = Int(
        title=_('Mac CDs'), required=True, readonly=False,
        description=_('Number of Mac CDs in this request.'),
        constraint=_validate_positive_int)

    quantityamd64 = Int(
        title=_('64-bit PC CDs'), required=True, readonly=False,
        description=_('Number of 64-bit PC CDs in this request.'),
        constraint=_validate_positive_int)

    isdefault = Bool(
        title=_('Is this the default option?'),
        description=_('The default option is the one that is always '
                      'initially selected in the list of options the '
                      'user will see.'),
        required=False, readonly=False, default=False)

    totalCDs = Attribute(_('Total number of CDs in this request.'))
    description = Attribute(_('Description'))
    description_without_flavour = Attribute(_('Description without Flavour'))

    def destroySelf():
        """Delete this object from the database."""


class IStandardShipItRequestSet(Interface):
    """The set of all standard ShipIt requests."""

    def new(flavour, quantityx86, quantityamd64, quantityppc, description,
            isdefault):
        """Create and return a new StandardShipItRequest."""

    def getAll():
        """Return all standard ShipIt requests."""

    def getByFlavour(flavour):
        """Return all standard ShipIt requests for the given flavour."""

    def get(id, default=None):
        """Return the StandardShipItRequest with the given id.
        
        Return the default value if nothing's found.
        """

    def getAllGroupedByFlavour():
        """Return a dictionary mapping ShipItFlavours to the 
        StandardShipItRequests of that flavour.
        """

    def getByNumbersOfCDs(flavour, quantityx86, quantityamd64, quantityppc):
        """Return the StandardShipItRequest with the given number of CDs for
        the given flavour.

        Return None if there's no StandardShipItRequest with the given number
        of CDs.
        """


class IShipment(Interface):
    """The shipment of a given request."""

    id = Int(title=_('The unique ID'), required=True, readonly=True)
    logintoken = TextLine(title=_('Token'), readonly=True, required=True)
    dateshipped = Datetime(
        title=_('Date Shipped'), readonly=True, required=True)
    shippingservice = Int(
        title=_('Shipping Service'), readonly=True, required=True)
    shippingrun = Int(title=_('Shipping Run'), readonly=True, required=True)
    request = Int(title=_('The ShipIt Request'), readonly=True, required=True)
    trackingcode = TextLine(
        title=_('Tracking Code'), readonly=True, required=False)


class IShipmentSet(Interface):
    """The set of Shipment objects."""

    def new(shippingservice, shippingrun, trackingcode=None, dateshipped=None):
        """Create a new Shipment object with the given arguments."""

    def getByToken(token):
        """Return the Shipment with the given token or None if it doesn't 
        exist.
        """


class IShippingRun(Interface):
    """A set of requests that were sent to shipping at the same date."""

    id = Int(title=_('The unique ID'), required=True, readonly=True)
    datecreated = Datetime(
        title=_('Date of Creation'), required=True, readonly=True)

    csvfile = Int(
        title=_('A csv file with all requests of this run.'),
        required=False, readonly=False)

    sentforshipping = Bool(
        title=_('Was this ShippingRun sent for shipping?'),
        required=False, readonly=False)

    requests = Attribute(_('All requests that are part of this shipping run.'))

    def exportToCSVFile():
        """Generate a CSV file with all requests that are part of this
        shipping run, upload it to the Librarian and store the Librarian
        reference on the csvfile attribute.
        """


class IShippingRunSet(Interface):
    """The set of ShippingRun objects."""

    def new():
        """Create a new ShippingRun object."""

    def get(id):
        """Return the ShippingRun with the given id or None if it doesn't
        exist.
        """

    def getUnshipped():
        """Return all ShippingRuns that are not yet sent for shipping. """

    def getShipped():
        """Return all ShippingRuns that are already sent for shipping. """


class ShippingRequestPriority:
    """The priority of a given ShippingRequest."""

    HIGH = 'high'
    NORMAL = 'normal'


class IShipItReport(Interface):
    """A report based on shipit data."""

    datecreated = Datetime(
        title=_('Date of Creation'), required=True, readonly=True)

    csvfile = Int(
        title=_('A csv file with all requests of this run.'),
        required=True, readonly=True)


class IShipItReportSet(Interface):
    """The set of ShipItReport"""

    def new(csvfile):
        """Create a new ShipItReport object."""

    def getAll():
        """Return all ShipItReport objects."""


class IShippingRequestAdmin(Interface):
    """A schema used to render and validate the page for shipit admins to
    create/change ShippingRequests.
    """

    ubuntu_quantityx86 = Int(
        title=_('PC'), description=_('Quantity of Ubuntu PC CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    ubuntu_quantityppc = Int(
        title=_('Mac'), description=_('Quantity of Ubuntu Mac CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    ubuntu_quantityamd64 = Int(
        title=_('64-bit PC'), description=_('Quantity of Ubuntu 64-bit PC CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)

    kubuntu_quantityx86 = Int(
        title=_('PC'), description=_('Quantity of Kubuntu PC CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    kubuntu_quantityamd64 = Int(
        title=_('64-bit PC'),
        description=_('Quantity of Kubuntu 64-bit PC CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)

    edubuntu_quantityx86 = Int(
        title=_('PC'), description=_('Quantity of Edubuntu PC CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)

    highpriority = IShippingRequest.get('highpriority')
    recipientdisplayname = IShippingRequest.get('recipientdisplayname')
    addressline1 = IShippingRequest.get('addressline1')
    addressline2 = IShippingRequest.get('addressline2')
    city = IShippingRequest.get('city')
    province = IShippingRequest.get('province')
    country = IShippingRequest.get('country')
    postcode = IShippingRequest.get('postcode')
    phone = IShippingRequest.get('phone')
    organization = IShippingRequest.get('organization')


class IShippingRequestEdit(Interface):
    """A schema used to render and validate the page for shipit admins to
    approve/deny ShippingRequests.
    """

    ubuntu_quantityx86approved = Int(
        title=_('PC'), description=_('Quantity of Ubuntu X86 Approved CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    ubuntu_quantityppcapproved = Int(
        title=_('Mac'), description=_('Quantity of Ubuntu PPC Approved CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    ubuntu_quantityamd64approved = Int(
        title=_('64-bit PC'), 
        description=_('Quantity of Ubuntu AMD64 Approved CDs'), required=False, 
        readonly=False, constraint=_validate_positive_int)

    kubuntu_quantityx86approved = Int(
        title=_('PC'), description=_('Quantity of Kubuntu X86 Approved CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)
    kubuntu_quantityamd64approved = Int(
        title=_('64-bit PC'),
        description=_('Quantity of Kubuntu AMD64 Approved CDs'), required=False,
        readonly=False, constraint=_validate_positive_int)

    edubuntu_quantityx86approved = Int(
        title=_('PC'), description=_('Quantity of Edubuntu X86 Approved CDs'),
        required=False, readonly=False, constraint=_validate_positive_int)

    highpriority = IShippingRequest.get('highpriority')
