# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for sharing service."""


__metaclass__ = type

__all__ = [
    'ISharingService',
    ]

from lazr.restful.declarations import (
    call_with,
    export_as_webservice_entry,
    export_read_operation,
    export_write_operation,
    operation_for_version,
    operation_parameters,
    REQUEST_USER,
    )
from lazr.restful.fields import Reference
from zope.schema import (
    Choice,
    Dict,
    List,
    )

from lp import _
from lp.app.interfaces.services import IService
from lp.registry.enums import (
    InformationType,
    SharingPermission,
    )
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pillar import IPillar


class ISharingService(IService):

    # XXX 2012-02-24 wallyworld bug 939910
    # Need to export for version 'beta' even though we only want to use it in
    # version 'devel'
    export_as_webservice_entry(publish_web_link=False, as_of='beta')

    def getSharedArtifacts(pillar, person):
        """Return the artifacts shared between the pillar and person."""

    def getInformationTypes(pillar):
        """Return the allowed information types for the given pillar."""

    def getSharingPermissions():
        """Return the information sharing permissions."""

    @export_read_operation()
    @operation_parameters(
        pillar=Reference(IPillar, title=_('Pillar'), required=True))
    @operation_for_version('devel')
    def getPillarSharees(pillar):
        """Return people/teams who can see pillar artifacts."""

    @export_read_operation()
    @operation_parameters(
        pillar=Reference(IPillar, title=_('Pillar'), required=True))
    @operation_for_version('devel')
    def getPillarShareeData(pillar, grantees=None):
        """Return people/teams who can see pillar artifacts.

        The result records are json data which includes:
            - person name
            - permissions they have for each information type.
        """

    @export_write_operation()
    @call_with(user=REQUEST_USER)
    @operation_parameters(
        pillar=Reference(IPillar, title=_('Pillar'), required=True),
        sharee=Reference(IPerson, title=_('Sharee'), required=True),
        permissions=Dict(
            key_type=Choice(vocabulary=InformationType),
            value_type=Choice(vocabulary=SharingPermission)))
    @operation_for_version('devel')
    def sharePillarInformation(pillar, sharee, permissions, user):
        """Ensure sharee has the grants for information types on a pillar.

        :param pillar: the pillar for which to grant access
        :param sharee: the person or team to grant
        :param permissions: a dict of {InformationType: SharingPermission}
            if SharingPermission is ALL, then create an access policy grant
            if SharingPermission is SOME, then remove any access policy grants
            if SharingPermission is NONE, then remove all grants for the access
            policy
        :param user: the user making the request
        """

    @export_write_operation()
    @operation_parameters(
        pillar=Reference(IPillar, title=_('Pillar'), required=True),
        sharee=Reference(IPerson, title=_('Sharee'), required=True),
        information_types=List(
            Choice(vocabulary=InformationType), required=False))
    @operation_for_version('devel')
    def deletePillarSharee(pillar, sharee, information_types):
        """Remove a sharee from a pillar.

        :param pillar: the pillar from which to remove access
        :param sharee: the person or team to remove
        :param information_types: if None, remove all access, otherwise just
                                   remove the specified access_policies
        """
