# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Salesforce proxy wrapper."""

__metaclass__ = type
__all__ = ['SalesforceVouchers',
           'Voucher']


import xmlrpclib
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.ftests.salesforce import (
    SalesforceXMLRPCTestTransport,
    )
from canonical.launchpad.interfaces import IProductSet

class Voucher:
    def __init__(self, values):
        self.id = values.get('voucher')
        self.status = values.get('status')
        self.term = values.get('term')
        project_id = values.get('project_id')
        project = None
        if project_id is not None:
            project = getUtility(IProductSet).get(project_id)
        self.project = project

    def __repr__(self):
        if self.project is None:
            project_name = "unassigned"
        else:
            project_name = self.project.displayname
        return "%s %s %s %s" % (self.id,
                                self.status,
                                self.term,
                                project_name)

class SalesforceVoucherProxy:
    """Wrapper class for voucher processing with Salesforce.

    These vouchers are used to allow commercial projects to subscribe to
    Launchpad.
    """

    def __init__(self, baseurl, xmlrpc_transport=None):
        if xmlrpc_transport is None:
            if config.commercialization.voucher_use_mock_transport:
                xmlrpc_transport = SalesforceXMLRPCTestTransport
            else:
                xmlrpc_transport = xmlrpclib.Transport
        self.xmlrpc_transport = xmlrpc_transport
        self._url =  "%s:%d" % (config.commercialization.voucher_proxy_url,
                                config.commercialization.voucher_proxy_port)

    @property
    def server_proxy(self):
        return xmlrpclib.ServerProxy(self._url,
                                     transport=self.xmlrpc_transport)
    def getUnredeemedVouchers(self, user):
        """Get the unredeemed vouchers for the user."""
        server = self.server_proxy
        vouchers = server.getUnredeemedVouchers(user.openid_identifier)
        return [Voucher(voucher) for voucher in vouchers]

    def getAllVouchers(self, user):
        """Get all of the vouchers for the user."""
        server = self.server_proxy
        vouchers = server.getAllVouchers(user.openid_identifier)
        return [Voucher(voucher) for voucher in vouchers]

    def getServerStatus(self):
        """Get the server status."""
        return self.server_proxy.getServerStatus()

    def redeemVoucher(self, voucher_id, user, project):
        """Redeem a voucher.

        :param voucher_id: string with the id of the voucher to be redeemed.
        :param user: user who is redeeming the voucher.
        :param project: project that is being subscribed.
        :return: list with a boolean indicating status of redemption, and an
            integer representing the number of months the subscription
            allows.
        """
        result = self.server_proxy.redeemVoucher(
            voucher_id,
            user.openid_identifier,
            project.id,
            project.displayname)
        return result

    def updateProjectName(self, project):
        """Update the name of a project in Salesforce.

        If a project changes its name it is updated in Salesforce.
        :param project: the project to update
        :return: integer representing the number of vouchers found for this
            project which were updated.
        """
        return self.server_proxy.updateProjectName(
            project.id,
            project.displayname)
