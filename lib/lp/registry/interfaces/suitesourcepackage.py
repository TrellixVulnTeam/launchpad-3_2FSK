# Copyright 2009 Canonical Ltd.  All rights reserved.

"""A pocket of a source package."""

__metaclass__ = type
__all__ = [
    'ISuiteSourcePackage',
    ]

from lazr.restful.declarations import export_as_webservice_entry, exported
from lazr.restful.fields import Reference

from zope.interface import Interface
from zope.schema import Choice, TextLine

from canonical.launchpad import _

from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.soyuz.interfaces.publishing import PackagePublishingPocket


class ISuiteSourcePackage(Interface):
    """A source package that's on a pocket."""

    export_as_webservice_entry()

    distribution = exported(
        Reference(
            IDistribution, title=_("Distribution"), required=True,
            description=_("The distribution for the source package.")))

    # The interface for this is really IDistroSeries, but importing that would
    # cause circular imports. Set in _schema_circular_imports.
    distroseries = exported(
        Reference(
            IDistroSeries, title=_("Distribution Series"), required=True,
            description=_("The DistroSeries for this SourcePackage")))

    path = exported(
        TextLine(
            title=_("Suite"),
            description=_("<distro>/<suite>/<sourcepackagename>")))

    pocket = exported(
        Choice(
            title=_('Pocket'), required=True,
            vocabulary=PackagePublishingPocket,
            description=_("The build targeted pocket.")))

    sourcepackagename = Choice(
        title=_("Package"), required=False, vocabulary='SourcePackageName')

    sourcepackage = exported(
        Reference(
            ISourcePackage, title=_('Source package'), required=True,
            description=_('The source package')))

    suite = exported(
        TextLine(
            title=_("Suite"),
            description=_(
                "A string naming the suite that this package is for. "
                "The distro series followed by the pocket, separated by a "
                "hyphen.")))
