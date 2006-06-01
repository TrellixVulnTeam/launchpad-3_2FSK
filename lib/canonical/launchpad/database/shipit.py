# Copyright 2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['StandardShipItRequest', 'StandardShipItRequestSet',
           'ShippingRequest', 'ShippingRequestSet', 'RequestedCDs',
           'Shipment', 'ShipmentSet', 'ShippingRun', 'ShippingRunSet',
           'ShipItReport', 'ShipItReportSet']

from StringIO import StringIO
import csv
from datetime import datetime, timedelta
import random

from zope.interface import implements
from zope.component import getUtility

import pytz

from sqlobject import (
    ForeignKey, StringCol, BoolCol, SQLObjectNotFound, IntCol, AND)

from canonical.uuid import generate_uuid
from canonical.database.sqlbase import (
    SQLBase, sqlvalues, quote, quote_like, cursor)
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.helpers import intOrZero
from canonical.launchpad.datetimeutils import make_mondays_between

from canonical.lp.dbschema import (
    ShipItDistroRelease, ShipItArchitecture, ShipItFlavour, EnumCol,
    ShippingService)
from canonical.launchpad.interfaces import (
    IStandardShipItRequest, IStandardShipItRequestSet, IShippingRequest,
    IRequestedCDs, IShippingRequestSet, ShippingRequestStatus,
    ILaunchpadCelebrities, IShipment, IShippingRun, IShippingRunSet,
    IShipmentSet, ShippingRequestPriority, IShipItReport, IShipItReportSet,
    ShipItConstants, SOFT_MAX_SHIPPINGRUN_SIZE, ILibraryFileAliasSet)
from canonical.launchpad.database.country import Country


class ShippingRequest(SQLBase):
    """See IShippingRequest"""

    implements(IShippingRequest)
    sortingColumns = ['daterequested', 'id']
    _defaultOrder = sortingColumns

    recipient = ForeignKey(dbName='recipient', foreignKey='Person',
                           notNull=True)

    daterequested = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    shockandawe = ForeignKey(dbName='shockandawe', foreignKey='ShockAndAwe',
                             default=None)

    # None here means that it's pending approval.
    approved = BoolCol(notNull=False, default=None)
    whoapproved = ForeignKey(dbName='whoapproved', foreignKey='Person',
                             default=None)

    cancelled = BoolCol(notNull=True, default=False)
    whocancelled = ForeignKey(dbName='whocancelled', foreignKey='Person',
                              default=None)

    reason = StringCol(default=None)
    highpriority = BoolCol(notNull=True, default=False)

    city = StringCol(notNull=True)
    phone = StringCol(default=None)
    country = ForeignKey(dbName='country', foreignKey='Country', notNull=True)
    province = StringCol(default=None)
    postcode = StringCol(default=None)
    addressline1 = StringCol(notNull=True)
    addressline2 = StringCol(default=None)
    organization = StringCol(default=None)
    recipientdisplayname = StringCol(notNull=True)

    @property
    def recipient_email(self):
        """See IShippingRequest"""
        return self.recipient.preferredemail.email

    @property
    def shipment(self):
        """See IShippingRequest"""
        return Shipment.selectOneBy(requestID=self.id)

    @property
    def countrycode(self):
        """See IShippingRequest"""
        return self.country.iso3166code2

    @property
    def shippingservice(self):
        """See IShippingRequest"""
        if self.highpriority:
            return ShippingService.TNT
        else:
            return ShippingService.SPRING

    def getTotalApprovedCDs(self):
        """See IShippingRequest"""
        total = 0
        for requested_cds in self.getAllRequestedCDs():
            total += requested_cds.quantityapproved
        return total

    def getTotalCDs(self):
        """See IShippingRequest"""
        total = 0
        for requested_cds in self.getAllRequestedCDs():
            total += requested_cds.quantity
        return total

    def _getRequestedCDsByFlavourAndArch(self, flavour, arch):
        query = AND(RequestedCDs.q.requestID==self.id,
                    RequestedCDs.q.flavour==flavour,
                    RequestedCDs.q.architecture==arch)
        return RequestedCDs.selectOne(query)

    def getAllRequestedCDs(self):
        """See IShippingRequest"""
        return RequestedCDs.selectBy(requestID=self.id)

    def getRequestedCDsGroupedByFlavourAndArch(self):
        """See IShippingRequest"""
        requested_cds = {}
        for flavour in ShipItFlavour.items:
            requested_arches = {}
            for arch in ShipItArchitecture.items:
                cds = self._getRequestedCDsByFlavourAndArch(flavour, arch)
                requested_arches[arch] = cds

            requested_cds[flavour] = requested_arches

        return requested_cds

    def setQuantitiesBasedOnStandardRequest(self, request_type):
        """See IShippingRequestSet"""
        quantities = {
            request_type.flavour:
                {ShipItArchitecture.X86: request_type.quantityx86,
                 ShipItArchitecture.AMD64: request_type.quantityamd64,
                 ShipItArchitecture.PPC: request_type.quantityppc}
            }
        self.setQuantities(quantities)
        
    def setApprovedQuantities(self, quantities):
        """See IShippingRequestSet"""
        assert self.isApproved()
        self._setQuantities(quantities, set_approved=True)

    def setRequestedQuantities(self, quantities):
        """See IShippingRequestSet"""
        self._setQuantities(quantities, set_requested=True)

    def setQuantities(self, quantities):
        """See IShippingRequestSet"""
        self._setQuantities(quantities, set_approved=True, set_requested=True)

    def _setQuantities(self, quantities, set_approved=False,
                       set_requested=False):
        """Set the approved and/or requested quantities of this request.

        :quantities: A dictionary like the described in
                     IShippingRequestSet.setQuantities.
        """
        assert set_approved or set_requested
        for flavour, arches_and_quantities in quantities.items():
            for arch, quantity in arches_and_quantities.items():
                assert quantity >= 0
                requested_cds = self._getRequestedCDsByFlavourAndArch(
                    flavour, arch)
                if requested_cds is None:
                    requested_cds = RequestedCDs(
                        request=self, flavour=flavour, architecture=arch)
                if set_approved:
                    requested_cds.quantityapproved = quantity
                if set_requested:
                    requested_cds.quantity = quantity

    def isCustom(self):
        """See IShippingRequest"""
        requested_cds = self.getAllRequestedCDs()
        for flavour in ShipItFlavour.items:
            if self.containsCustomQuantitiesOfFlavour(flavour):
                return True
        return False

    def containsCustomQuantitiesOfFlavour(self, flavour):
        """See IShippingRequest"""
        quantities = self.getQuantitiesOfFlavour(flavour)
        if not sum(quantities.values()):
            # This is an existing order that contains CDs of other
            # flavours only.
            return False
        else:
            standardrequestset = getUtility(IStandardShipItRequestSet)
            standard_request = standardrequestset.getByNumbersOfCDs(
                flavour, quantities[ShipItArchitecture.X86],
                quantities[ShipItArchitecture.AMD64],
                quantities[ShipItArchitecture.PPC])
            return standard_request is None

    def getQuantitiesOfFlavour(self, flavour):
        """See IShippingRequest"""
        requested_cds = self.getRequestedCDsGroupedByFlavourAndArch()[flavour]
        quantities = {}
        for arch in ShipItArchitecture.items:
            arch_requested_cds = requested_cds[arch]
            # Any of {x86,amd64,ppc}_requested_cds can be None here, so we use
            # a default value for getattr to make things easier.
            quantities[arch] = getattr(arch_requested_cds, 'quantity', 0)
        return quantities

    def isAwaitingApproval(self):
        """See IShippingRequest"""
        return self.approved is None

    def isApproved(self):
        """See IShippingRequest"""
        return self.approved == True

    def isDenied(self):
        """See IShippingRequest"""
        return self.approved == False

    def deny(self):
        """See IShippingRequest"""
        assert not self.isDenied()
        if self.isApproved():
            self.clearApproval()
        self.approved = False

    def clearApproval(self):
        """See IShippingRequest"""
        assert self.isApproved()
        self.approved = None
        self.whoapproved = None
        for requestedcds in self.getAllRequestedCDs():
            requestedcds.quantityapproved = 0

    def approve(self, whoapproved=None):
        """See IShippingRequest"""
        assert not self.cancelled
        assert not self.isApproved()
        self.approved = True
        self.whoapproved = whoapproved

    def cancel(self, whocancelled):
        """See IShippingRequest"""
        assert not self.cancelled
        if self.isApproved():
            self.clearApproval()
        self.cancelled = True
        self.whocancelled = whocancelled


class ShippingRequestSet:
    """See IShippingRequestSet"""

    implements(IShippingRequestSet)

    def get(self, id, default=None):
        """See IShippingRequestSet"""
        try:
            return ShippingRequest.get(id)
        except (SQLObjectNotFound, ValueError):
            return default

    def lockTableInExclusiveMode(self):
        """See IShippingRequestSet"""
        cur = cursor()
        cur.execute('LOCK TABLE ShippingRequest IN EXCLUSIVE MODE')
        cur.execute('LOCK TABLE Shipment IN EXCLUSIVE MODE')

    def new(self, recipient, recipientdisplayname, country, city, addressline1,
            phone, addressline2=None, province=None, postcode=None,
            organization=None, reason=None, shockandawe=None):
        """See IShippingRequestSet"""
        if not recipient.inTeam(getUtility(ILaunchpadCelebrities).shipit_admin):
            # Non shipit-admins can't place more than one order at a time.
            assert recipient.currentShipItRequest() is None

        request = ShippingRequest(
            recipient=recipient, reason=reason, shockandawe=shockandawe,
            city=city, country=country, addressline1=addressline1,
            addressline2=addressline2, province=province, postcode=postcode,
            recipientdisplayname=recipientdisplayname,
            organization=organization, phone=phone)

        return request

    def getUnshippedRequestsIDs(self, priority):
        """See IShippingRequestSet"""
        if priority == ShippingRequestPriority.HIGH:
            priorityfilter = 'AND ShippingRequest.highpriority IS TRUE'
        elif priority == ShippingRequestPriority.NORMAL:
            priorityfilter = 'AND ShippingRequest.highpriority IS FALSE'
        else:
            # Nothing to filter, return all unshipped requests.
            priorityfilter = ''

        query = """
            SELECT ShippingRequest.id
            FROM ShippingRequest
            LEFT OUTER JOIN Shipment ON Shipment.request = ShippingRequest.id
            WHERE Shipment.id IS NULL
                  AND ShippingRequest.cancelled IS FALSE
                  AND ShippingRequest.approved IS TRUE
                  %(priorityfilter)s
            ORDER BY daterequested, id
            """ % {'priorityfilter': priorityfilter}

        cur = cursor()
        cur.execute(query)
        return [id for (id,) in cur.fetchall()]

    def getOldestPending(self):
        """See IShippingRequestSet"""
        q = AND(ShippingRequest.q.cancelled==False,
                ShippingRequest.q.approved==None)
        results = ShippingRequest.select(q, orderBy='daterequested', limit=1)
        try:
            return results[0]
        except IndexError:
            return None

    def search(self, status=ShippingRequestStatus.ALL, flavour=None,
               distrorelease=None, recipient_text=None, include_cancelled=False,
               orderBy=ShippingRequest.sortingColumns):
        """See IShippingRequestSet"""
        queries = []
        clauseTables = set()

        if distrorelease is not None:
            queries.append("""
                (RequestedCDs.request = ShippingRequest.id
                 AND RequestedCDs.distrorelease = %s)
                """ % sqlvalues(distrorelease))
            clauseTables.add('RequestedCDs')

        if flavour is not None:
            queries.append("""
                (RequestedCDs.request = ShippingRequest.id
                 AND RequestedCDs.flavour = %s)
                """ % sqlvalues(flavour))
            clauseTables.add('RequestedCDs')

        if recipient_text:
            recipient_text = recipient_text.lower()
            queries.append("""
                (ShippingRequest.fti @@ ftq(%s) OR recipient IN 
                    (
                    SELECT Person.id FROM Person 
                        WHERE Person.fti @@ ftq(%s)
                    UNION
                    SELECT EmailAddress.person FROM EmailAddress
                        WHERE lower(EmailAddress.email) LIKE %s || '%%'
                    ))
                """ % (quote(recipient_text), quote(recipient_text),
                       quote_like(recipient_text)))

        if not include_cancelled:
            queries.append("ShippingRequest.cancelled IS FALSE")

        if status == ShippingRequestStatus.APPROVED:
            queries.append("ShippingRequest.approved IS TRUE")
        elif status == ShippingRequestStatus.PENDING:
            queries.append("ShippingRequest.approved IS NULL")
        elif status == ShippingRequestStatus.DENIED:
            queries.append("ShippingRequest.approved IS FALSE")
        else:
            # Okay, if you don't want any filtering I won't filter
            pass

        query = " AND ".join(queries)
        # We can't pass an empty string to SQLObject.select(), and it's
        # already reported as https://launchpad.net/bugs/3096. That's why
        # I do this "1 = 1" hack.
        if not query:
            query = "1 = 1"
        return ShippingRequest.select(
            query, clauseTables=clauseTables, distinct=True, orderBy=orderBy)

    def exportRequestsToFiles(self, priority, ztm):
        """See IShippingRequestSet"""
        request_ids = self.getUnshippedRequestsIDs(priority)
        # The SOFT_MAX_SHIPPINGRUN_SIZE is not a hard limit, and it doesn't
        # make sense to split a shippingrun into two just because there's 10 
        # requests more than the limit, so we only split them if there's at
        # least 50% more requests than SOFT_MAX_SHIPPINGRUN_SIZE.
        file_counter = 0
        while len(request_ids):
            file_counter += 1
            ztm.begin()
            if len(request_ids) > SOFT_MAX_SHIPPINGRUN_SIZE * 1.5:
                request_ids_subset = request_ids[:SOFT_MAX_SHIPPINGRUN_SIZE]
                request_ids[:SOFT_MAX_SHIPPINGRUN_SIZE] = []
            else:
                request_ids_subset = request_ids[:]
                request_ids = []
            shippingrun = self._create_shipping_run(request_ids_subset)
            now = datetime.now(pytz.timezone('UTC'))
            filename = 'Ubuntu'
            if priority == ShippingRequestPriority.HIGH:
                filename += '-High-Pri'
            filename += '-%s-%d.%s.csv' % (
                now.strftime('%y-%m-%d'), file_counter, generate_uuid())
            shippingrun.exportToCSVFile(filename)
            ztm.commit()

    def _create_shipping_run(self, request_ids):
        """Create and return a ShippingRun containing all requests whose ids
        are in request_ids.
        
        Each request will be added to the ShippingRun only if it's approved, 
        not cancelled and not part of another shipment.
        """
        shippingrun = ShippingRunSet().new()
        for request_id in request_ids:
            request = self.get(request_id)
            if not request.isApproved():
                # This request's status may have been changed after we started
                # running the script. Now it's not approved anymore and we can't
                # export it.
                continue
            assert not request.cancelled
            assert request.shipment is None
            shipment = ShipmentSet().new(
                request, request.shippingservice, shippingrun)
        return shippingrun

    def _sumRequestedCDCount(self, quantities):
        """Sum the values of a dictionary mapping flavour and architectures 
        to quantities of requested CDs.

        This dictionary must be of the same format of the one returned by
        _getRequestedCDCount().
        """
        total = 0
        for flavour in quantities:
            for arch in quantities[flavour]:
                total += quantities[flavour][arch]
        return total

    def _getRequestedCDCount(
        self, current_release_only, country=None, approved=False):
        """Return the number of Requested CDs for each flavour and architecture.
        
        If country is not None, then consider only CDs requested by people on
        that country.
        
        If approved is True, then we return the number of CDs that were
        approved, which may differ from the number of requested CDs.
        """
        attr_to_sum_on = 'quantity'
        if approved:
            attr_to_sum_on = 'quantityapproved'
        quantities = {}
        release_filter = ""
        if current_release_only:
            release_filter = (
                " AND RequestedCDs.distrorelease = %s"
                % sqlvalues(ShipItConstants.current_distrorelease))
        for flavour in ShipItFlavour.items:
            quantities[flavour] = {}
            for arch in ShipItArchitecture.items:
                query_str = """
                    shippingrequest.id = shipment.request AND
                    shippingrequest.id = requestedcds.request AND
                    requestedcds.flavour = %s AND
                    requestedcds.architecture = %s""" % sqlvalues(flavour, arch)
                query_str += release_filter
                if country is not None:
                    query_str += (" AND shippingrequest.country = %s" 
                                  % sqlvalues(country.id))
                requests = ShippingRequest.select(
                    query_str, clauseTables=['RequestedCDs', 'Shipment'])
                quantities[flavour][arch] = intOrZero(
                    requests.sum(attr_to_sum_on))
        return quantities

    def generateCountryBasedReport(self, current_release_only=True):
        """See IShippingRequestSet"""
        csv_file = StringIO()
        csv_writer = csv.writer(csv_file)
        header = [
            'Country', 'Shipped Ubuntu x86 CDs', 'Shipped Ubuntu AMD64 CDs',
            'Shipped Ubuntu PPC CDs', 'Shipped Kubuntu x86 CDs',
            'Shipped Kubuntu AMD64 CDs', 'Shipped Kubuntu PPC CDs',
            'Shipped Edubuntu x86 CDs', 'Shipped Edubuntu AMD64 CDs',
            'Shipped Edubuntu PPC CDs', 'Normal-prio shipments',
            'High-prio shipments', 'Average request size',
            'Percentage of requested CDs that were approved',
            'Percentage of total shipped CDs', 'Continent']
        csv_writer.writerow(header)
        requested_cd_count = self._getRequestedCDCount(
            current_release_only, approved=True)
        all_shipped_cds = self._sumRequestedCDCount(requested_cd_count)
        ubuntu = ShipItFlavour.UBUNTU
        kubuntu = ShipItFlavour.KUBUNTU
        edubuntu = ShipItFlavour.EDUBUNTU
        x86 = ShipItArchitecture.X86
        amd64 = ShipItArchitecture.AMD64
        ppc = ShipItArchitecture.PPC
        for country in Country.select():
            base_query = (
                "shippingrequest.country = %s AND "
                "shippingrequest.id = shipment.request" % sqlvalues(country.id))
            clauseTables = ['Shipment']
            total_shipped_requests = ShippingRequest.select(
                base_query, clauseTables=clauseTables).count()
            if not total_shipped_requests:
                continue
            
            shipped_cds_per_arch = self._getRequestedCDCount(
                current_release_only, country=country, approved=True)

            high_prio_orders = ShippingRequest.select(
                base_query + " AND highpriority IS TRUE",
                clauseTables=clauseTables)
            high_prio_count = intOrZero(high_prio_orders.count())

            normal_prio_orders = ShippingRequest.select(
                base_query + " AND highpriority IS FALSE",
                clauseTables=clauseTables)
            normal_prio_count = intOrZero(normal_prio_orders.count())

            shipped_cds = self._sumRequestedCDCount(shipped_cds_per_arch)
            requested_cd_count = self._getRequestedCDCount(
                current_release_only, country=country, approved=False)
            requested_cds = self._sumRequestedCDCount(requested_cd_count)
            average_request_size = shipped_cds / total_shipped_requests
            percentage_of_approved = float(shipped_cds) / float(requested_cds)
            percentage_of_total = float(shipped_cds) / float(all_shipped_cds)

            # Need to encode strings that may have non-ASCII chars into
            # unicode because we're using StringIO.
            country_name = country.name.encode('utf-8')
            continent_name = country.continent.name.encode('utf-8')
            row = [country_name,
                   shipped_cds_per_arch[ubuntu][x86],
                   shipped_cds_per_arch[ubuntu][amd64],
                   shipped_cds_per_arch[ubuntu][ppc],
                   shipped_cds_per_arch[kubuntu][x86],
                   shipped_cds_per_arch[kubuntu][amd64],
                   shipped_cds_per_arch[kubuntu][ppc],
                   shipped_cds_per_arch[edubuntu][x86],
                   shipped_cds_per_arch[edubuntu][amd64],
                   shipped_cds_per_arch[edubuntu][ppc],
                   normal_prio_count, high_prio_count,
                   average_request_size,
                   "%.2f%%" % (percentage_of_approved * 100),
                   "%.2f%%" % (percentage_of_total * 100),
                   continent_name]
            csv_writer.writerow(row)
        csv_file.seek(0)
        return csv_file

    def generateWeekBasedReport(self, start_date, end_date):
        """See IShippingRequestSet"""
        flavour = ShipItFlavour
        arch = ShipItArchitecture
        quantities_order = [
            [flavour.UBUNTU, arch.X86, 'Ubuntu Requested PC CDs'],
            [flavour.UBUNTU, arch.AMD64, 'Ubuntu Requested 64-bit PC CDs'],
            [flavour.UBUNTU, arch.PPC, 'Ubuntu Requested Mac CDs'],
            [flavour.KUBUNTU, arch.X86, 'Kubuntu Requested PC CDs'],
            [flavour.KUBUNTU, arch.AMD64, 'Kubuntu Requested 64-bit PC CDs'],
            [flavour.KUBUNTU, arch.PPC, 'Kubuntu Requested Mac CDs'],
            [flavour.EDUBUNTU, arch.X86, 'Edubuntu Requested PC CDs'],
            [flavour.EDUBUNTU, arch.AMD64, 'Edubuntu Requested 64-bit PC CDs'],
            [flavour.EDUBUNTU, arch.PPC, 'Edubuntu Requested Mac CDs']]

        csv_file = StringIO()
        csv_writer = csv.writer(csv_file)
        header = ['Year', 'Week number', 'Requests']
        for dummy, dummy, label in quantities_order:
            header.append(label)
        csv_writer.writerow(header)

        requests_base_query = """
            SELECT COUNT(*) 
            FROM ShippingRequest 
            WHERE ShippingRequest.cancelled IS FALSE
            """

        sum_base_query = """
            SELECT flavour, architecture, SUM(quantity)
            FROM RequestedCDs, ShippingRequest
            WHERE RequestedCDs.request = ShippingRequest.id
                  AND ShippingRequest.cancelled IS FALSE
            """
        sum_group_by = " GROUP BY flavour, architecture"

        cur = cursor()
        for monday_date in make_mondays_between(start_date, end_date):
            year, weeknum, weekday = monday_date.isocalendar()
            row = [year, weeknum]

            date_filter = (
                " AND shippingrequest.daterequested BETWEEN %s AND %s"
                % sqlvalues(monday_date, monday_date + timedelta(days=7)))
            requests_query = requests_base_query + date_filter
            sum_query = sum_base_query + date_filter + sum_group_by

            cur.execute(requests_query)
            row.extend(cur.fetchone())

            cur.execute(sum_query)
            sum_dict = self._convertResultsToDict(cur.fetchall())
            for flavour, arch, dummy in quantities_order:
                try:
                    item = sum_dict[flavour]
                except KeyError:
                    sum = 0
                else:
                    sum = item.get(arch, 0)
                row.append(sum)

            csv_writer.writerow(row)

        csv_file.seek(0)
        return csv_file

    def _convertResultsToDict(self, results):
        """Convert a list of (flavour_id, architecture_id, quantity) tuples
        returned by a raw SQL query into a dictionary mapping ShipItFlavour
        and ShipItArchitecture objects to the quantities.
        """
        sum_dict = {}
        for flavour_id, arch_id, sum in results:
            flavour = ShipItFlavour.items[flavour_id]
            sum_dict.setdefault(flavour, {})
            arch = ShipItArchitecture.items[arch_id]
            sum_dict[flavour].update({arch: sum})
        return sum_dict

    def generateShipmentSizeBasedReport(self, current_release_only=True):
        """See IShippingRequestSet"""
        csv_file = StringIO()
        csv_writer = csv.writer(csv_file)
        header = ['Number of CDs', 'Number of Shipments']
        csv_writer.writerow(header)
        release_filter = ""
        if current_release_only:
            release_filter = (
                " AND RequestedCDs.distrorelease = %s"
                % sqlvalues(ShipItConstants.current_distrorelease))
        query_str = """
            SELECT shipment_size, COUNT(request_id) AS shipments
            FROM
            (
                SELECT shippingrequest.id AS request_id, 
                       SUM(quantityapproved) AS shipment_size
                FROM requestedcds, shippingrequest, shipment
                WHERE requestedcds.request = shippingrequest.id
                      AND shippingrequest.id = shipment.request
                      %(releasefilter)s
                GROUP BY shippingrequest.id
            )
            AS TMP GROUP BY shipment_size ORDER BY shipment_size
            """ % {'releasefilter': release_filter}
        cur = cursor()
        cur.execute(query_str)
        for shipment_size, shipments in cur.fetchall():
            csv_writer.writerow([shipment_size, shipments])

        csv_file.seek(0)
        return csv_file


class RequestedCDs(SQLBase):
    """See IRequestedCDs"""

    implements(IRequestedCDs)

    quantity = IntCol(notNull=True, default=0)
    quantityapproved = IntCol(notNull=True, default=0)

    request = ForeignKey(
        dbName='request', foreignKey='ShippingRequest', notNull=True)

    distrorelease = EnumCol(
        schema=ShipItDistroRelease, notNull=True,
        default=ShipItConstants.current_distrorelease)
    architecture = EnumCol(schema=ShipItArchitecture, notNull=True)
    flavour = EnumCol(schema=ShipItFlavour, notNull=True)

    @property
    def description(self):
        text = "%(quantity)d %(flavour)s "
        if self.quantity > 1:
            text += "CDs "
        else:
            text += "CD "
        text += "for %(arch)s"
        replacements = {
            'quantity': self.quantity, 'flavour': self.flavour.title,
            'arch': self.architecture.title}
        return text % replacements


class StandardShipItRequest(SQLBase):
    """See IStandardShipItRequest"""

    implements(IStandardShipItRequest)
    _table = 'StandardShipItRequest'

    quantityx86 = IntCol(notNull=True)
    quantityppc = IntCol(notNull=True)
    quantityamd64 = IntCol(notNull=True)
    isdefault = BoolCol(notNull=True, default=False)
    flavour = EnumCol(schema=ShipItFlavour, notNull=True)

    @property
    def description_without_flavour(self):
        """See IStandardShipItRequest"""
        if self.totalCDs > 1:
            description = "%d CDs" % self.totalCDs
        else:
            description = "%d CD" % self.totalCDs
        return "%s (%s)" % (description, self._detailed_description())

    @property
    def description(self):
        """See IStandardShipItRequest"""
        if self.totalCDs > 1:
            description = "%d %s CDs" % (self.totalCDs, self.flavour.title)
        else:
            description = "%d %s CD" % (self.totalCDs, self.flavour.title)
        return "%s (%s)" % (description, self._detailed_description())

    def _detailed_description(self):
        detailed = []
        text = '%d %s Edition'
        if self.quantityx86:
            detailed.append(
                text % (self.quantityx86, ShipItArchitecture.X86.title))
        if self.quantityamd64:
            detailed.append(
                text % (self.quantityamd64, ShipItArchitecture.AMD64.title))
        if self.quantityppc:
            detailed.append(
                text % (self.quantityppc, ShipItArchitecture.PPC.title))
        return ", ".join(detailed)

    @property
    def totalCDs(self):
        """See IStandardShipItRequest"""
        return self.quantityx86 + self.quantityppc + self.quantityamd64


class StandardShipItRequestSet:
    """See IStandardShipItRequestSet"""

    implements(IStandardShipItRequestSet)

    def new(self, flavour, quantityx86, quantityamd64, quantityppc, isdefault):
        """See IStandardShipItRequestSet"""
        return StandardShipItRequest(flavour=flavour, quantityx86=quantityx86,
                quantityppc=quantityppc, quantityamd64=quantityamd64,
                isdefault=isdefault)

    def getAll(self):
        """See IStandardShipItRequestSet"""
        return StandardShipItRequest.select()

    def getByFlavour(self, flavour):
        """See IStandardShipItRequestSet"""
        return StandardShipItRequest.selectBy(flavour=flavour)

    def getAllGroupedByFlavour(self):
        """See IStandardShipItRequestSet"""
        standard_requests = {}
        for flavour in ShipItFlavour.items:
            standard_requests[flavour] = self.getByFlavour(flavour)
        return standard_requests

    def get(self, id, default=None):
        """See IStandardShipItRequestSet"""
        try:
            return StandardShipItRequest.get(id)
        except (SQLObjectNotFound, ValueError):
            return default

    def getByNumbersOfCDs(
        self, flavour, quantityx86, quantityamd64, quantityppc):
        """See IStandardShipItRequestSet"""
        return StandardShipItRequest.selectOneBy(
            flavour=flavour, quantityx86=quantityx86,
            quantityamd64=quantityamd64, quantityppc=quantityppc)


class Shipment(SQLBase):
    """See IShipment"""

    implements(IShipment)

    logintoken = StringCol(unique=True, notNull=True)
    dateshipped = UtcDateTimeCol(default=None)
    shippingservice = EnumCol(schema=ShippingService, notNull=True)
    shippingrun = ForeignKey(dbName='shippingrun', foreignKey='ShippingRun',
                             notNull=True)
    request = ForeignKey(dbName='request', foreignKey='ShippingRequest',
                         notNull=True, unique=True)
    trackingcode = StringCol(default=None)


class ShipmentSet:
    """See IShipmentSet"""

    implements(IShipmentSet)

    def new(self, request, shippingservice, shippingrun, trackingcode=None,
            dateshipped=None):
        """See IShipmentSet"""
        token = self._generateToken()
        while self.getByToken(token):
            token = self._generateToken()

        return Shipment(
            shippingservice=shippingservice, shippingrun=shippingrun,
            trackingcode=trackingcode, logintoken=token,
            dateshipped=dateshipped, request=request)

    def _generateToken(self):
        characters = '23456789bcdfghjkmnpqrstwxz'
        length = 10
        return ''.join([random.choice(characters) for count in range(length)])

    def getByToken(self, token):
        """See IShipmentSet"""
        return Shipment.selectOneBy(logintoken=token)


class ShippingRun(SQLBase):
    """See IShippingRun"""

    implements(IShippingRun)
    _defaultOrder = ['-datecreated', 'id']

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    csvfile = ForeignKey(
        dbName='csvfile', foreignKey='LibraryFileAlias', default=None)
    sentforshipping = BoolCol(notNull=True, default=False)

    @property
    def requests(self):
        query = ("ShippingRequest.id = Shipment.request AND "
                 "Shipment.shippingrun = ShippingRun.id AND "
                 "ShippingRun.id = %s" % sqlvalues(self.id))

        clausetables = ['ShippingRun', 'Shipment']
        return ShippingRequest.select(query, clauseTables=clausetables)

    def exportToCSVFile(self, filename):
        """See IShippingRun"""
        csv_file = self._createCSVFile()
        csv_file.seek(0)
        self.csvfile = getUtility(ILibraryFileAliasSet).create(
            name=filename, size=len(csv_file.getvalue()), file=csv_file,
            contentType='text/plain')

    def _createCSVFile(self):
        """Return a csv file containing all requests that are part of this
        shippingrun.
        """
        file_fields = (('recordnr', 'id'),
                       ('Ship to company', 'organization'),
                       ('Ship to name', 'recipientdisplayname'),
                       ('Ship to addr1', 'addressline1'),
                       ('Ship to addr2', 'addressline2'),
                       ('Ship to city', 'city'),
                       ('Ship to county', 'province'),
                       ('Ship to zip', 'postcode'),
                       ('Ship to country', 'countrycode'),
                       ('Ship to phone', 'phone'),
                       ('Ship to email address', 'recipient_email'))

        csv_file = StringIO()
        csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_ALL)
        row = [label for label, attr in file_fields]
        # The values for these fields we can't get using getattr(), so we have
        # to set them manually.
        extra_fields = ['ship Ubuntu quantity PC',
                        'ship Ubuntu quantity 64-bit PC',
                        'ship Ubuntu quantity Mac', 
                        'ship Kubuntu quantity PC',
                        'ship Kubuntu quantity 64-bit PC',
                        'ship Kubuntu quantity Mac',
                        'ship Edubuntu quantity PC',
                        'ship Edubuntu quantity 64-bit PC',
                        'ship Edubuntu quantity Mac',
                        'token', 'Ship via', 'display']
        row.extend(extra_fields)
        csv_writer.writerow(row)

        ubuntu = ShipItFlavour.UBUNTU
        kubuntu = ShipItFlavour.KUBUNTU
        edubuntu = ShipItFlavour.EDUBUNTU
        x86 = ShipItArchitecture.X86
        ppc = ShipItArchitecture.PPC
        amd64 = ShipItArchitecture.AMD64
        for request in self.requests:
            row = []
            for label, attr in file_fields:
                value = getattr(request, attr)
                if isinstance(value, basestring):
                    # Text fields can't have non-ASCII characters or commas.
                    # This is a restriction of the shipping company.
                    value = value.replace(',', ';')
                    # Here we can be sure value can be encoded into ASCII
                    # because we always check this in the UI.
                    value = value.encode('ASCII')
                row.append(value)

            all_requested_cds = request.getRequestedCDsGroupedByFlavourAndArch()
            # The order that the flavours and arches appear in the following
            # two for loops must match the order the headers appear in
            # extra_fields.
            for flavour in [ubuntu, kubuntu, edubuntu]:
                for arch in [x86, amd64, ppc]:
                    requested_cds = all_requested_cds[flavour][arch]
                    if requested_cds is None:
                        quantityapproved = 0
                    else:
                        quantityapproved = requested_cds.quantityapproved
                    row.append(quantityapproved)

            row.append(request.shipment.logintoken)
            row.append(request.shippingservice.title)
            # XXX: 'display' is some magic number that's used by the shipping
            # company. Need to figure out what's it for and use a better name.
            # -- Guilherme Salgado, 2005-10-04
            if request.getTotalApprovedCDs() >= 100:
                display = 1
            else:
                display = 0
            row.append(display)
            csv_writer.writerow(row)

        return csv_file


class ShippingRunSet:
    """See IShippingRunSet"""

    implements(IShippingRunSet)

    def new(self):
        """See IShippingRunSet"""
        return ShippingRun()

    def get(self, id):
        """See IShippingRunSet"""
        try:
            return ShippingRun.get(id)
        except SQLObjectNotFound:
            return None

    def getUnshipped(self):
        """See IShippingRunSet"""
        return ShippingRun.select(ShippingRun.q.sentforshipping==False)

    def getShipped(self):
        """See IShippingRunSet"""
        return ShippingRun.select(ShippingRun.q.sentforshipping==True)


class ShipItReport(SQLBase):
    """See IShipItReport"""

    implements(IShipItReport)
    _defaultOrder = ['-datecreated', 'id']
    _table = 'ShipItReport'

    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    csvfile = ForeignKey(
        dbName='csvfile', foreignKey='LibraryFileAlias', notNull=True)


class ShipItReportSet:
    """See IShipItReportSet"""

    implements(IShipItReportSet)

    def new(self, csvfile):
        """See IShipItReportSet"""
        return ShipItReport(csvfile=csvfile)

    def getAll(self):
        """See IShipItReportSet"""
        return ShipItReport.select()
