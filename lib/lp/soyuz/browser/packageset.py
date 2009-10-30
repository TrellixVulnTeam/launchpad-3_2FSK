# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser views for packagesets."""

__metaclass__ = type

__all__ = [
    'PackagesetSetNavigation',
    ]


from canonical.launchpad.webapp import GetitemNavigation
from lp.soyuz.interfaces.packageset import IPackagesetSet


class PackagesetSetNavigation(GetitemNavigation):
    """Navigation methods for PackagesetSet."""
    usedfor = IPackagesetSet

    def traverse(self, distroseries):
        if self.request.stepstogo:
            # The package set name follows after the distro series.
            ps_name = self.request.stepstogo.consume()
            return self.context.getByName(ps_name, distroseries=distroseries)

        # Otherwise return None (to trigger a NotFound error).
        return None
        
