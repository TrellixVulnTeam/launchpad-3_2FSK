# Copyright 2005 Canonical Ltd

__metaclass__ = type

__all__ = [
    'StandardShipItRequestAddView', 'ShippingRequestApproveOrDenyView',
    'ShippingRequestsView', 'ShipItLoginView', 'ShipItRequestView',
    'ShipItUnauthorizedView', 'StandardShipItRequestsView',
    'ShipItExportsView', 'ShipItNavigation', 'ShipItReportsView',
    'ShippingRequestAdminView', 'StandardShipItRequestSetNavigation',
    'ShippingRequestSetNavigation']


from zope.event import notify
from zope.component import getUtility
from zope.app.form.browser.add import AddView
from zope.app.form.interfaces import WidgetsError, IInputWidget
from zope.app.form.utility import setUpWidgets
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile

from canonical.config import config
from canonical.cachedproperty import cachedproperty
from canonical.lp.dbschema import (
    ShipItFlavour, ShipItArchitecture, ShipItDistroRelease,
    ShippingRequestStatus)
from canonical.launchpad.helpers import (
    intOrZero, get_email_template, shortlist)
from canonical.launchpad.webapp.error import SystemErrorView
from canonical.launchpad.webapp.login import LoginOrRegister
from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp.generalform import GeneralFormView
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp import (
    canonical_url, Navigation, stepto, redirection)
from canonical.launchpad.mail.sendmail import simple_sendmail
from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.interfaces.validation import shipit_postcode_required
from canonical.launchpad.interfaces import (
    IStandardShipItRequestSet, IShippingRequestSet, ILaunchBag,
    ILaunchpadCelebrities, IShippingRunSet, IShipItApplication,
    IShipItReportSet, UnexpectedFormData, IShippingRequestUser,
    ShipItConstants)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.layers import (
    ShipItUbuntuLayer, ShipItKUbuntuLayer, ShipItEdUbuntuLayer)
from canonical.launchpad import _


class ShipItUnauthorizedView(SystemErrorView):

    response_code = 403
    forbidden_page = ViewPageTemplateFile('../templates/shipit-forbidden.pt')

    def __call__(self):
        # Users should always go to shipit.ubuntu.com and login before
        # going to any other page.
        return self.forbidden_page()


# XXX: The LoginOrRegister class is not really designed to be reused. That
# class must either be fixed to allow proper reuse or we should write a new
# class which doesn't reuses LoginOrRegister here. -- GuilhermeSalgado
# 2005-09-09
class ShipItLoginView(LoginOrRegister):
    """Process the login form and redirect the user to the request page."""

    possible_origins = {
        ShipItFlavour.UBUNTU: 'shipit-ubuntu',
        ShipItFlavour.KUBUNTU: 'shipit-kubuntu',
        ShipItFlavour.EDUBUNTU: 'shipit-edubuntu'}
        
    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.flavour = _get_flavour_from_layer(request)
        self.origin = self.possible_origins[self.flavour]

    def getApplicationURL(self):
        return 'https://launchpad.net'

    def process_form(self):
        if getUtility(ILaunchBag).user is not None:
            # Already logged in.
            self._redirect()
            return
        LoginOrRegister.process_form(self)
        if self.login_success():
            self._redirect()

    def _redirect(self):
        """Redirect the logged in user to the request page.

        If the logged in user is a ShipIt administrator, then he's redirected
        to the 'requests' page, where all requests are shown.
        """
        user = getUtility(ILaunchBag).user
        assert user is not None
        if user.inTeam(getUtility(ILaunchpadCelebrities).shipit_admin):
            self.request.response.redirect('requests')
        else:
            current_order = user.currentShipItRequest()
            if (current_order and
                current_order.containsCustomQuantitiesOfFlavour(self.flavour)):
                self.request.response.redirect('specialrequest')
            else:
                self.request.response.redirect('myrequest')


def _get_flavour_from_layer(request):
    """Check what ShipIt Layer the given request provides and return the
    ShipItFlavour corresponding to that layer.
    """
    if ShipItUbuntuLayer.providedBy(request):
        return ShipItFlavour.UBUNTU
    elif ShipItEdUbuntuLayer.providedBy(request):
        return ShipItFlavour.EDUBUNTU
    elif ShipItKUbuntuLayer.providedBy(request):
        return ShipItFlavour.KUBUNTU
    else:
        raise AssertionError(
            'This request must provide one of ShipItEdUbuntuLayer, '
            'ShipItKUbuntuLayer or ShipItUbuntuLayer')


class ShipItRequestView(GeneralFormView):
    """The view for people to create/edit ShipIt requests."""

    from_email_addresses = {
        ShipItFlavour.UBUNTU: config.shipit.ubuntu_from_email_address,
        ShipItFlavour.EDUBUNTU: config.shipit.edubuntu_from_email_address,
        ShipItFlavour.KUBUNTU: config.shipit.kubuntu_from_email_address}

    should_show_custom_request = False

    # Field names that are part of the schema but don't exist in our
    # context object.
    _extra_fields = None

    schema = IShippingRequestUser
    fieldNames = None
    process_status = None
    index = ViewPageTemplateFile('../templates/shipit-requestcds.pt')

    def __init__(self, context, request):
        """Override GeneralFormView.__init__() not to set up widgets."""
        self.context = context
        self.request = request
        self.flavour = _get_flavour_from_layer(request)
        self.from_email_address = self.from_email_addresses[self.flavour]
        self.fieldNames = [
            'recipientdisplayname', 'addressline1', 'addressline2', 'city',
            'province', 'country', 'postcode', 'phone', 'organization']
        self._extra_fields = []
        self.quantity_fields_mapping = {}

    def _setExtraFields(self):
        """Set self._extra_fields that are shown in the custom order form.

        These fields include the 'reason' and quantity widgets for users to
        make custom orders.
        """
        if self.flavour == ShipItFlavour.UBUNTU:
            self.quantity_fields_mapping = {
                ShipItArchitecture.X86: 'ubuntu_quantityx86',
                ShipItArchitecture.PPC: 'ubuntu_quantityppc',
                ShipItArchitecture.AMD64: 'ubuntu_quantityamd64'}
        elif self.flavour == ShipItFlavour.KUBUNTU:
            self.quantity_fields_mapping = {
                ShipItArchitecture.X86: 'ubuntu_quantityx86',
                ShipItArchitecture.AMD64: 'ubuntu_quantityamd64'}
        elif self.flavour == ShipItFlavour.EDUBUNTU:
            self.quantity_fields_mapping = {
                ShipItArchitecture.X86: 'ubuntu_quantityx86'}
        else:
            raise AssertionError('Unrecognized flavour: %s' % self.flavour)

        self._extra_fields = self.quantity_fields_mapping.values()
        self.fieldNames.append('reason')
        self.fieldNames.extend(self._extra_fields)

    @property
    def dvds_section(self):
        """Get the HTML containing links to DVD sales for this flavour."""
        if self.flavour == ShipItFlavour.UBUNTU:
            return ViewPageTemplateFile('../templates/shipit-ubuntu-dvds.pt')(
                self)
        elif self.flavour == ShipItFlavour.KUBUNTU:
            return ViewPageTemplateFile('../templates/shipit-kubuntu-dvds.pt')(
                self)
        else:
            # We don't have DVDs for Edubuntu. :-(
            return u''

    @property
    def _keyword_arguments(self):
        """All fields should be given as keyword arguments."""
        return self.fieldNames

    @property
    def _standard_fields(self):
        return list(set(self.fieldNames) - set(self._extra_fields))

    @property
    def quantity_widgets(self):
        """Return a list with the quantity widgets that need to be shown."""
        return [getattr(self, field_name + '_widget')
                for field_name in self.quantity_fields_mapping.values()]

    def currentOrderIsCustom(self):
        """Return True if the current order contains custom quantities of CDs
        of self.flavour.
        """
        return self.current_order.containsCustomQuantitiesOfFlavour(
            self.flavour)

    def _setUpWidgets(self, context=None):
        # First we set up the standard widgets
        setUpWidgets(
            self, self.schema, IInputWidget, names=self._standard_fields,
            initial=self.initial_values, context=context)
        # And then we set up the extra widgets that depend on the layer we are
        # and are not attributes of our context; that's why their initial
        # values comes from a different property.
        if self._extra_fields:
            setUpWidgets(
                self, self.schema, IInputWidget, names=self._extra_fields,
                initial=self.extra_fields_initial_values, context=context)
                    
    def renderCustomrequestForm(self):
        self._setExtraFields()
        self.should_show_custom_request = True
        return self._renderForm()

    def renderStandardrequestForm(self):
        self.should_show_custom_request = False
        return self._renderForm()

    def _renderForm(self):
        self._setUpWidgets()
        self.process_form()
        return self.index()

    @property
    def download_url(self):
        """Return the URL where the ISO images of this flavour are located."""
        if self.flavour == ShipItFlavour.UBUNTU:
            return "http://www.ubuntu.com/download"
        elif self.flavour == ShipItFlavour.EDUBUNTU:
            return "http://www.edubuntu.org/Download"
        elif self.flavour == ShipItFlavour.KUBUNTU:
            return "http://www.kubuntu.org/download.php"
        else:
            raise AssertionError('Invalid self.flavour: %s' % self.flavour)

    @property
    def is_edubuntu(self):
        return self.flavour == ShipItFlavour.EDUBUNTU

    @property
    def is_kubuntu(self):
        return self.flavour == ShipItFlavour.KUBUNTU

    @property
    def initial_values(self):
        """Get initial values from this user's current request, if there's one.

        If this user has no current request, then get the initial values from
        the last shipped request made by this user.
        """
        field_values = {}
        user = getUtility(ILaunchBag).user
        current_order = user.currentShipItRequest()
        existing_order = current_order
        if existing_order is None:
            existing_order = user.lastShippedRequest()

        if existing_order is not None:
            for name in self._standard_fields:
                if existing_order != current_order and name == 'reason':
                    # Don't use the reason provided for a request that was
                    # shipped already.
                    continue
                field_values[name] = getattr(existing_order, name)

        return field_values

    @property
    def extra_fields_initial_values(self):
        field_values = {}
        if self.current_order is None:
            return field_values
        quantities = self._getCurrentOrderQuantitiesOfThisFlavour()
        for arch, field_name in self.quantity_fields_mapping.items():
            field_values[field_name] = quantities[arch]
        return field_values

    def standardShipItRequests(self):
        """Return all standard ShipIt Requests sorted by quantity of CDs."""
        requests = getUtility(IStandardShipItRequestSet).getByFlavour(
            self.flavour)
        return sorted(requests, key=lambda request: request.totalCDs)

    @cachedproperty
    def current_order_standard_id(self):
        """The current order's StandardShipItRequest id, or None.
        
        If there's no current order or the current order doesn't contain any
        CDs of self.flavour, None will be returned.
        """
        if self.current_order is None:
            return None

        quantities = self._getCurrentOrderQuantitiesOfThisFlavour()
        standard = getUtility(IStandardShipItRequestSet).getByNumbersOfCDs(
            self.flavour, quantities[ShipItArchitecture.X86],
            quantities[ShipItArchitecture.AMD64],
            quantities[ShipItArchitecture.PPC])

        if standard is None:
            return None
        else:
            return standard.id

    def _getCurrentOrderQuantitiesOfThisFlavour(self):
        assert self.current_order is not None
        return self.current_order.getQuantitiesOfFlavour(self.flavour)

    def currentOrderContainsCDsOfThisFlavour(self):
        """Return True if the current order contains any CDs of self.flavour.

        You must not use this method if self.current_order is None.
        """
        assert self.current_order is not None
        quantities = self.current_order.getQuantitiesOfFlavour(self.flavour)
        return bool(sum(quantities.values()))

    @cachedproperty('_current_order')
    def current_order(self):
        return self.user.currentShipItRequest()

    @property
    def selected_standardrequest(self):
        """Return the id of the standardrequest radio button that should be
        selected.

        If the submitted form contains a 'ordertype' variable, that's the one
        that should be requested. If not, we check if the current shipit 
        request is a standard one, and if so, return the standard request id
        of this shipit request. Lastly, if none of the above exists, we return
        the standard request whose isdefault attribute is True.
        """
        ordertype = self.request.form.get('ordertype')
        if ordertype:
            try:
                return int(ordertype)
            except ValueError:
                raise UnexpectedFormData(
                    'Expected an id but got "%s"' % ordertype)
        if self.current_order_standard_id:
            return self.current_order_standard_id
        for standardrequest in self.standardShipItRequests():
            if standardrequest.isdefault:
                return standardrequest.id

    def process_form(self):
        """Overwrite GeneralFormView's process_form() method because we want
        to be able to have a 'Cancel' button in a different <form> element.
        """
        if 'cancel' in self.request.form:
            if self.current_order is None:
                # This is probably a user reloading the form he submitted
                # cancelling his request, so we'll just refresh the page so he
                # can see that he has no current request, actually.
                return ''
            self.current_order.cancel(self.user)
            self.process_status = 'Request Cancelled'
        else:
            self.process_status = GeneralFormView.process_form(self)

        flush_database_updates()
        self._current_order = self.user.currentShipItRequest()
        return self.process_status

    def process(self, *args, **kw):
        """Process the submitted form, either creating a new request, or
        changing an existing one.
        """
        form = self.request.form
        need_notification = False
        reason = kw.get('reason')
        requestset = getUtility(IShippingRequestSet)
        current_order = self.current_order
        if not current_order:
            current_order = getUtility(IShippingRequestSet).new(
                self.user, kw.get('recipientdisplayname'), kw.get('country'),
                kw.get('city'), kw.get('addressline1'), kw.get('phone'),
                kw.get('addressline2'), kw.get('province'), kw.get('postcode'),
                kw.get('organization'), reason)
            if self.should_show_custom_request:
                msg = ('Request accepted. Please note that special requests '
                       'can take up to <strong>ten weeks<strong> to deliver. '
                       'For quicker processing, choose a '
                       '<a href="/myrequest">standard option</a> instead.')
            else:
                msg = ('Request accepted. Please note that requests usually '
                       'take from 4 to 6 weeks to deliver, depending on the '
                       'country of shipping.')
        else:
            for name in self._standard_fields:
                setattr(current_order, name, kw.get(name))
            # 'reason' is special cased because it's only displayed on the
            # custom request form, and so it's part of self._extra_fields and
            # not self._standard_fields. Also, we can't simply override
            # current_order.reason because the user might have made a custom
            # request for a given flavour and is now making a standard request
            # for another flavour (and standard requests don't have a reason).
            if reason:
                current_order.reason = reason
            msg = 'Request changed successfully.'

        # Save the total of CDs for later comparison, as it may change inside
        # setQuantities().
        original_total_of_cds = current_order.getTotalCDs()

        request_type_id = form.get('ordertype')
        if request_type_id:
            assert not self._extra_fields
            request_type = getUtility(IStandardShipItRequestSet).get(
                request_type_id)
            if request_type is None or request_type.flavour != self.flavour:
                # Either a shipit admin removed this option after the user
                # loaded the page or the user is poisoning the form.
                return ("The option you chose was not found. Please select "
                        "one from the list below.")
            quantities = request_type.quantities
            total_cds = request_type.totalCDs
        else:
            assert not request_type_id
            quantities = {}
            total_cds = 0
            for arch, field_name in self.quantity_fields_mapping.items():
                quantities[arch] = intOrZero(kw.get(field_name))
                total_cds += quantities[arch]

        # Here we set both requested and approved quantities. This is not a
        # problem because if this order needs manual approval, it'll be
        # flagged as pending approval, meaning that somebody will have to
        # check (and possibly change) its approved quantities before it can be
        # shipped.
        current_order.setQuantities({self.flavour: quantities})

        # Make sure that subsequent queries will see the RequestedCDs objects
        # created/updated when we set the order quantities above.
        flush_database_updates()

        current_flavours = current_order.getContainedFlavours()

        max_size_for_auto_approval = ShipItConstants.max_size_for_auto_approval
        new_total_of_cds = current_order.getTotalCDs()
        shipped_orders = self.user.shippedShipItRequestsOfCurrentRelease()
        if shipped_orders.count() >= 2:
            # User has more than 2 shipped orders. Now we need to check if any
            # of the flavours contained in this order is also contained in two
            # or more of this user's previous orders and, if so, mark this
            # order to be denied later.
            shipped_orders_with_flavour = {}
            for order in shipped_orders:
                for flavour in order.getContainedFlavours():
                    count = shipped_orders_with_flavour.get(flavour, 0)
                    shipped_orders_with_flavour[flavour] = count + 1

            for flavour in current_flavours:
                if shipped_orders_with_flavour.get(flavour, 0) >= 2:
                    current_order.markAsPendingSpecial()
                    break
        elif new_total_of_cds > max_size_for_auto_approval:
            assert current_order.isCustom()
            # If the order was already approved and the guy is just reducing
            # the number of CDs, there's no reason for de-approving it.
            if (current_order.isApproved() and
                new_total_of_cds >= original_total_of_cds):
                current_order.clearApproval()
        elif current_order.isAwaitingApproval():
            assert not current_order.isDenied()
            if (not shipped_orders or 
                not self.userAlreadyRequestedFlavours(current_flavours)):
                # This is either the first order containing CDs of the current
                # distrorelease made by this user or it contains only CDs of
                # flavours this user hasn't requested before.
                current_order.approve()
        elif (self.userAlreadyRequestedFlavours(current_flavours) and
              current_order.isApproved()):
            # If the user changes his approved request to include flavours
            # which he has already ordered, we clear the approval flag and
            # curb his greed!
            current_order.clearApproval()
        else:
            # No need to approve or clear approval for this order.
            pass

        if not current_order.isApproved():
            # The approved quantities of a request are set when the request is
            # created, for simplicity's sake. If we chose to deny or leave the
            # request pending in the code above, we need to clear them out.
            current_order.clearApprovedQuantities()

        if current_order.isAwaitingApproval():
            # This request needs manual approval, so we need to notify the
            # shipit admins.
            self._notifyShipItAdmins(current_order)

        return msg

    def userAlreadyRequestedFlavours(self, flavours):
        """Return True if any of the given flavours is contained in any of
        this users's shipped requests of the current distrorelease.
        """
        flavours = set(flavours)
        for order in self.user.shippedShipItRequestsOfCurrentRelease():
            if flavours.intersection(order.getContainedFlavours()):
                return True
        return False

    def validate(self, data):
        errors = []
        # We use a custom template with some extra widgets, so we have to
        # cheat here and access self.request.form
        if not self.request.form.get('ordertype') and not self._extra_fields:
            errors.append(UnexpectedFormData(_(
                'The number of requested CDs was not provided.')))

        country = data['country']
        if shipit_postcode_required(country) and not data['postcode']:
            errors.append(LaunchpadValidationError(_(
                "Shipping to your country requires a postcode, but you didn't "
                "provide one. Please enter one below.")))

        if self.quantity_fields_mapping:
            total_cds = 0
            for field_name in self.quantity_fields_mapping.values():
                total_cds += intOrZero(data[field_name])
            if total_cds == 0:
                errors.append(LaunchpadValidationError(_(
                    "You can't make a request with 0 CDs")))

        if errors:
            raise WidgetsError(errors)

    def _notifyShipItAdmins(self, order):
        """Notify the shipit admins by email that there's a new request."""
        subject = '[ShipIt] New Request Pending Approval (#%d)' % order.id
        recipient = order.recipient
        headers = {'Reply-To': order.recipient_email}
        shipped_requests = recipient.shippedShipItRequestsOfCurrentRelease()
        replacements = {'recipientname': order.recipientdisplayname,
                        'recipientemail': order.recipient_email,
                        'requesturl': canonical_url(order),
                        'shipped_requests': shipped_requests.count(),
                        'reason': order.reason}
        message = get_email_template('shipit-custom-request.txt') % replacements
        shipit_admins = config.shipit.admins_email_address
        simple_sendmail(
            self.from_email_address, shipit_admins, subject, message, headers)


class _SelectMenuOption:
    """An option of a HTML <select>.

    This class simply stores a name, a title and whether the option should be
    selected or not.
    """
    
    def __init__(self, name, title, is_selected=False):
        self.name = name
        self.title = title
        self.is_selected = is_selected


class ShippingRequestsView:
    """The view to list ShippingRequests that match a given criteria."""

    submitted = False
    # Using the item's name here is clearer than using its id and also helps
    # making tests more readable.
    selectedStatus = ShippingRequestStatus.PENDING.name
    selectedFlavourName = 'any'
    selectedDistroReleaseName = ShipItConstants.current_distrorelease.name
    recipient_text = ''

    @cachedproperty
    def requests_totals(self):
        requests = shortlist(
            self.batchNavigator.currentBatch(), longest_expected=100)
        return getUtility(IShippingRequestSet).getTotalsForRequests(requests)

    def _build_options(self, names_and_titles, selected_name):
        """Return a list of _SelectMenuOption elements with the given names
        and titles.

        The option whose name is equal to selected_name also gets a
        is_selected set to True.
        """
        options = []
        for name, title in names_and_titles:
            option = _SelectMenuOption(name, title)
            if selected_name == name:
                option.is_selected = True
            options.append(option)
        return options

    def flavour_options(self):
        names_and_titles = [
            (flavour.name, flavour.title) for flavour in ShipItFlavour.items]
        names_and_titles.append(('any', 'Any flavour'))
        return self._build_options(names_and_titles, self.selectedFlavourName)

    def release_options(self):
        names_and_titles = [(release.name, release.title) 
                            for release in ShipItDistroRelease.items]
        names_and_titles.append(('any', 'Any'))
        return self._build_options(
            names_and_titles, self.selectedDistroReleaseName)

    def status_options(self):
        names_and_titles = [(status.name, status.title) 
                            for status in ShippingRequestStatus.items]
        names_and_titles.append(('all', 'All'))
        return self._build_options(names_and_titles, self.selectedStatus)

    def processForm(self):
        """Process the form, if it was submitted."""
        request = self.request
        if not request.get('show'):
            self.batchNavigator = self._getBatchNavigator([])
            return

        self.submitted = True
        self.selectedStatus = request.get('statusfilter')
        if self.selectedStatus == 'all':
            status = None
        else:
            status = ShippingRequestStatus.items[self.selectedStatus]

        self.selectedDistroReleaseName = request.get('releasefilter')
        if self.selectedDistroReleaseName == 'any':
            release = None
        else:
            release = ShipItDistroRelease.items[self.selectedDistroReleaseName]

        self.selectedFlavourName = request.get('flavourfilter')
        if self.selectedFlavourName == 'any':
            flavour = None
        else:
            flavour = ShipItFlavour.items[self.selectedFlavourName]

        orderby = str(request.get('orderby'))
        self.recipient_text = request.get('recipient_text')

        requestset = getUtility(IShippingRequestSet)
        results = requestset.search(
            status=status, flavour=flavour, distrorelease=release,
            recipient_text=self.recipient_text, orderBy=orderby)
        self.batchNavigator = self._getBatchNavigator(results)

    def _getBatchNavigator(self, results):
        return BatchNavigator(results, self.request)


class StandardShipItRequestsView:
    """The view for the list of all StandardShipItRequests."""

    def processForm(self):
        if self.request.method != 'POST':
            return

        for key, value in self.request.form.items():
            if value == 'Delete':
                id = int(key)
                getUtility(IStandardShipItRequestSet).get(id).destroySelf()


class StandardShipItRequestAddView(AddView):
    """The view to add a new Standard ShipIt Request."""

    def nextURL(self):
        return '.'

    def createAndAdd(self, data):
        flavour = data.get('flavour')
        quantityx86 = data.get('quantityx86')
        quantityamd64 = data.get('quantityamd64')
        quantityppc = data.get('quantityppc')
        isdefault = data.get('isdefault')
        request = getUtility(IStandardShipItRequestSet).new(
            flavour, quantityx86, quantityamd64, quantityppc, isdefault)
        notify(ObjectCreatedEvent(request))


class ShippingRequestAdminMixinView:
    """Basic functionality for administering a ShippingRequest.

    Any class that inherits from this one should also inherit from
    GeneralFormView, or another class that stores the widgets as instance
    attributes, named like fieldname_widget.
    """

    # This is the order in which we display the distribution flavours
    # in the UI
    ordered_flavours = (
        ShipItFlavour.UBUNTU, ShipItFlavour.KUBUNTU, ShipItFlavour.EDUBUNTU)

    # This is the order in which we display the quantity widgets for each
    # flavour in the UI
    ordered_architectures = (
        ShipItArchitecture.X86, ShipItArchitecture.AMD64,
        ShipItArchitecture.PPC)

    def widgetsMatrixWithFlavours(self):
        """Return a matrix in which each row contains a ShipItFlavour and one
        quantity widget for each ShipItArchitecture that we ship CDs. 

        The architectures of CDs that we ship are dependent on the
        flavour.

        The matrix returned by this method is meant to be used by the
        quantity_widgets macro, defined in templates/shipit-macros.pt.
        """
        matrix = []
        for flavour in self.ordered_flavours:
            row = [flavour.title]
            for arch in self.ordered_architectures:
                widget_name = self.quantity_fields_mapping[flavour][arch]
                if widget_name is not None:
                    widget_name += '_widget'
                    row.append(getattr(self, widget_name))
                else:
                    row.append(None)
            matrix.append(row)
        return matrix

    def getQuantityWidgetsInitialValuesFromExistingOrder(
            self, order, approved=False):
        """Return a dictionary mapping the widget names listed in
        self.quantity_fields_mapping to their initial values.
        """
        initial = {}
        if approved:
            quantity_attrname = 'quantityapproved'
        else:
            quantity_attrname = 'quantity'
        requested = order.getRequestedCDsGroupedByFlavourAndArch()
        for flavour in self.quantity_fields_mapping:
            for arch in self.quantity_fields_mapping[flavour]:
                field_name = self.quantity_fields_mapping[flavour][arch]
                if field_name is None:
                    continue
                requested_cds = requested[flavour][arch]
                if requested_cds is not None:
                    value = getattr(requested_cds, quantity_attrname)
                else:
                    value = 0
                initial[field_name] = value
        return initial


class ShippingRequestApproveOrDenyView(
        GeneralFormView, ShippingRequestAdminMixinView):
    """The page where admins can Approve/Deny existing requests."""

    quantity_fields_mapping = {
        ShipItFlavour.UBUNTU:
            {ShipItArchitecture.X86: 'ubuntu_quantityx86approved',
             ShipItArchitecture.PPC: 'ubuntu_quantityppcapproved',
             ShipItArchitecture.AMD64: 'ubuntu_quantityamd64approved'},
        ShipItFlavour.KUBUNTU:
            {ShipItArchitecture.X86: 'kubuntu_quantityx86approved',
             ShipItArchitecture.PPC: None,
             ShipItArchitecture.AMD64: 'kubuntu_quantityamd64approved'},
        ShipItFlavour.EDUBUNTU:
            {ShipItArchitecture.X86: 'edubuntu_quantityx86approved',
             ShipItArchitecture.PPC: None,
             ShipItArchitecture.AMD64: None}
        }

    def process(self, *args, **kw):
        """Process the submitted form.

        Depending on the button used to submit the form, this method will
        Approve, Deny or Change the approved quantities of this shipit request.
        """
        context = self.context
        form = self.request.form

        if context.isShipped():
            # This order was exported after the form was rendered; we can't
            # allow changing it, so we return to render the page again,
            # without the buttons that allow changing it.
            # XXX: It's probably a good idea to notify the user about what
            # happened here.
            # -- Guilherme Salgado, 2006-07-27
            return

        if 'DENY' not in form:
            quantities = {}
            for flavour in self.quantity_fields_mapping:
                quantities[flavour] = {}
                for arch in self.quantity_fields_mapping[flavour]:
                    field_name = self.quantity_fields_mapping[flavour][arch]
                    if field_name is None:
                        # We don't ship this arch for this flavour
                        continue
                    quantities[flavour][arch] = kw[field_name]

        if 'APPROVE' in form:
            if not context.isAwaitingApproval():
                # This shipit request was changed behind our back; let's just
                # refresh the page so the user can decide what to do with it.
                return
            context.approve(whoapproved=getUtility(ILaunchBag).user)
            context.highpriority = kw['highpriority']
            context.setApprovedQuantities(quantities)
            self._nextURL = self._makeNextURL(previous_action='approved')
        elif 'CHANGE' in form:
            if not context.isApproved():
                # This shipit request was changed behind our back; let's just
                # refresh the page so the user can decide what to do with it.
                return
            self._nextURL = self._makeNextURL(previous_action='changed')
            context.highpriority = kw['highpriority']
            context.setApprovedQuantities(quantities)
        elif 'DENY' in form:
            if context.isDenied():
                # This shipit request was changed behind our back; let's just
                # refresh the page so the user can decide what to do with it.
                return
            self._nextURL = self._makeNextURL(previous_action='denied')
            context.deny()
        else:
            # Nothing to do.
            pass

    def submitted(self):
        # Overwrite GeneralFormView.submitted() because we have several
        # buttons on this page.
        form = self.request.form
        return 'APPROVE' in form or 'CHANGE' in form or 'DENY' in form

    def _makeNextURL(self, previous_action):
        # Need to flush all updates so that getOldestPending() can see the
        # updated values.
        flush_database_updates()
        url = '.'
        next_order = getUtility(IShippingRequestSet).getOldestPending()
        if next_order:
            url = '%s?previous=%d&%s=1' % (canonical_url(next_order),
                                           self.context.id, previous_action)
        return url

    @property
    def quantities_matrix(self):
        """Return a matrix of Flavours x Architectures where the values are
        the requested quantities for CDs of that Flavour and Architecture.
        """
        matrix = []
        quantities = self.context.getRequestedCDsGroupedByFlavourAndArch()
        for flavour in self.ordered_flavours:
            total = 0
            flavour_quantities = []
            for arch in self.ordered_architectures:
                requested_cds = quantities[flavour][arch]
                if requested_cds is not None:
                    quantity = requested_cds.quantity
                else:
                    quantity = 0
                total += quantity
                flavour_quantities.append(quantity)
            if total > 0:
                matrix.append([flavour.title] + flavour_quantities)
        return matrix

    @property
    def initial_values(self):
        order = self.context
        # If this order is not yet approved or shipped, "order.isApproved() or
        # order.isShipped()" will return False and then we'll get the
        # requested quantities as the initial values for the approved
        # quantities widgets.
        initial = self.getQuantityWidgetsInitialValuesFromExistingOrder(
            order, approved=order.isApproved() or order.isShipped())
        initial['highpriority'] = order.highpriority
        return initial

    def recipientHasOtherShippedRequests(self):
        """Return True if the recipient has other requests that were already
        sent to the shipping company."""
        recipient = self.context.recipient
        shipped_requests = recipient.shippedShipItRequestsOfCurrentRelease()
        if not shipped_requests:
            return False
        elif (shipped_requests.count() == 1 
              and shipped_requests[0] == self.context):
            return False
        else:
            return True

    def contextCanBeModified(self):
        """Return true if the context can be modified.
        
        A ShippingRequest can be modified only if it's not shipped nor
        cancelled.
        """
        return not (self.context.isCancelled() or self.context.isShipped())


class ShippingRequestAdminView(GeneralFormView, ShippingRequestAdminMixinView):
    """The page where admins can create new requests or change existing ones."""

    quantity_fields_mapping = {
        ShipItFlavour.UBUNTU:
            {ShipItArchitecture.X86: 'ubuntu_quantityx86',
             ShipItArchitecture.PPC: 'ubuntu_quantityppc',
             ShipItArchitecture.AMD64: 'ubuntu_quantityamd64'},
        ShipItFlavour.KUBUNTU:
            {ShipItArchitecture.X86: 'kubuntu_quantityx86',
             ShipItArchitecture.PPC: None,
             ShipItArchitecture.AMD64: 'kubuntu_quantityamd64'},
        ShipItFlavour.EDUBUNTU:
            {ShipItArchitecture.X86: 'edubuntu_quantityx86',
             ShipItArchitecture.PPC: None,
             ShipItArchitecture.AMD64: None}
        }

    current_order = None
    shipping_details_fields = [
        'recipientdisplayname', 'country', 'city', 'addressline1', 'phone',
        'addressline2', 'province', 'postcode', 'organization']

    def __init__(self, context, request):
        order_id = request.form.get('order')
        if order_id is not None and order_id.isdigit():
            self.current_order = getUtility(IShippingRequestSet).get(
                int(order_id))
        GeneralFormView.__init__(self, context, request)

    @property
    def initial_values(self):
        if self.current_order is None:
            return {}

        order = self.current_order
        initial = self.getQuantityWidgetsInitialValuesFromExistingOrder(
            order, approved=False)
        initial['highpriority'] = order.highpriority

        for field in self.shipping_details_fields:
            initial[field] = getattr(order, field)

        return initial

    def validate(self, data):
        # XXX: Even shipit admins shouldn't be allowed to make requests with 0
        # CDs. We need to check this here.
        # Guilherme Salgado, 2006-04-21
        errors = []
        country = data['country']
        if shipit_postcode_required(country) and not data['postcode']:
            errors.append(LaunchpadValidationError(_(
                "Shipping to your country requires a postcode, but you didn't "
                "provide one. Please enter one below.")))

        if errors:
            raise WidgetsError(errors)

    def process(self, *args, **kw):
        # All requests created through the admin UI have the shipit_admin
        # celeb as the recipient. This is so because shipit administrators have
        # to be able to create requests on behalf of people who don't have a
        # Launchpad account, and only the shipit_admin celeb is allowed to
        # have more than one open request at a time.
        shipit_admin = getUtility(ILaunchpadCelebrities).shipit_admin
        form = self.request.form
        quantities = {}
        for flavour in self.quantity_fields_mapping:
            quantities[flavour] = {}
            for arch in self.quantity_fields_mapping[flavour]:
                field_name = self.quantity_fields_mapping[flavour][arch]
                if field_name is None:
                    # We don't ship this arch for this flavour
                    continue
                quantities[flavour][arch] = intOrZero(kw[field_name])

        current_order = self.current_order
        if not current_order:
            current_order = getUtility(IShippingRequestSet).new(
                shipit_admin, kw['recipientdisplayname'], kw['country'],
                kw['city'], kw['addressline1'], kw['phone'],
                kw['addressline2'], kw['province'], kw['postcode'],
                kw['organization'])
            msg = 'New request created successfully: %d' % current_order.id

            # This is a newly created request, and because it's created by a
            # shipit admin we set both approved and requested quantities and
            # approve it.
            current_order.setQuantities(quantities)
            current_order.approve()
        else:
            for name in self.shipping_details_fields:
                setattr(current_order, name, kw[name])
            msg = 'Request %d changed' % current_order.id

            # This is a request being changed, so we just set the requested
            # quantities and don't approve it.
            current_order.setRequestedQuantities(quantities)

        current_order.highpriority = kw['highpriority']
        self._nextURL = canonical_url(current_order)
        self.request.response.addNotification(msg)


class ShipItReportsView(LaunchpadView):
    """The view for the list of shipit reports."""

    @property
    def reports(self):
        return getUtility(IShipItReportSet).getAll()


class ShipItExportsView:
    """The view for the list of shipit exports."""

    def process_form(self):
        """Process the form, marking the chosen ShippingRun as 'sent for
        shipping'.
        """
        if self.request.method != 'POST':
            return

        for key, value in self.request.form.items():
            if key.isdigit() and value == 'Yes':
                try:
                    shippingrun_id = int(key)
                except ValueError:
                    # The form can only be mangled by the end-user, so
                    # just ignore any poisoning issue if it exists.
                    continue
                shippingrun = getUtility(IShippingRunSet).get(shippingrun_id)
                shippingrun.sentforshipping = True
                break
        flush_database_updates()

    def sent_exports(self):
        """Return all exports that were sent to the shipping companies."""
        return getUtility(IShippingRunSet).getShipped()

    def unsent_exports(self):
        """Return all exports that weren't sent to the shipping companies."""
        return getUtility(IShippingRunSet).getUnshipped()

    def no_exports(self):
        """Return True if there's no generated exports."""
        return not (self.unsent_exports() or self.sent_exports())


class ShipItNavigation(Navigation):

    usedfor = IShipItApplication

    # Support bookmarks to the old shipit application that used cgi scripts.
    redirection('user.cgi', '.', status=301)

    @stepto('requests')
    def requests(self):
        # XXX: permission=launchpad.Admin
        return getUtility(IShippingRequestSet)

    @stepto('standardoptions')
    def standardoptions(self):
        # XXX: permission=launchpad.Admin
        return getUtility(IStandardShipItRequestSet)


class ShippingRequestSetNavigation(Navigation):

    usedfor = IShippingRequestSet

    def traverse(self, name):
        return self.context.get(name)


class StandardShipItRequestSetNavigation(Navigation):

    usedfor = IStandardShipItRequestSet

    def traverse(self, name):
        return self.context.get(name)

