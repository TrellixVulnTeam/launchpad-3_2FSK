# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Browser views for archivepermission."""

__metaclass__ = type

__all__ = [
    'ArchivePermissionUrl',
    ]

from zope.interface import implements

from lp.soyuz.interfaces.archivepermission import (
    ArchivePermissionType)
from canonical.launchpad.webapp.interfaces import ICanonicalUrlData

class ArchivePermissionURL:
    """Dynamic URL declaration for `IArchivePermission`."""
    implements(ICanonicalUrlData)
    rootsite = None

    def __init__(self, context):
        self.context = context

    @property
    def inside(self):
        return self.context.archive

    @property
    def path(self):
        if self.context.permission == ArchivePermissionType.UPLOAD:
            perm_type = "+upload"
        elif self.context.permission == ArchivePermissionType.QUEUE_ADMIN:
            perm_type = "+queue-admin"
        else:
            raise AssertionError, (
                "Unknown permission type %s" % self.context.permission)

        username = self.context.person.name

        if self.context.component_name is not None:
            item = "type=component&item=%s" % self.context.component_name
        elif self.context.source_package_name is not None:
            item = (
                "type=packagename&item=%s" % self.context.source_package_name)
        elif self.context.package_set_name is not None:
            item = "type=packageset&item=%s" % self.context.package_set_name
        else:
            raise AssertionError, (
                "One of component, sourcepackagename or package set should "
                "be set")

        return u"%s/%s?%s" % (perm_type, username, item)
