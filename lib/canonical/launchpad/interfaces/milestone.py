# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Milestone interfaces."""

__metaclass__ = type

__all__ = [
    'IMilestone',
    'IMilestoneSet',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Choice, Int, Date, Bool

from canonical.launchpad.interfaces.productseries import IProductSeries
from canonical.launchpad.interfaces.distrorelease import IDistroRelease
from canonical.launchpad import _
from canonical.launchpad.fields import ContentNameField
from canonical.launchpad.validators.name import name_validator


class MilestoneNameField(ContentNameField):

    @property
    def _content_iface(self):
        return IMilestone
    
    def _getByName(self, name):
        if IMilestone.providedBy(self.context):
            milestone = self.context.target.getMilestone(name)
        elif IProductSeries.providedBy(self.context):
            milestone = self.context.product.getMilestone(name)
        elif IDistroRelease.providedBy(self.context):
            milestone = self.context.distribution.getMilestone(name)
        else:
            raise AssertionError, 'Editing a milestone from a weird place.'
        if milestone is not None:
              self.errormessage = _(
                  "The name %%s is already used by a milestone in %s."
                  % milestone.target.displayname)
        return milestone


class IMilestone(Interface):
    """A milestone, or a targeting point for bugs and other release-related
    items that need coordination.
    """
    id = Int(title=_("Id"))
    name = MilestoneNameField(
        title=_("Name"),
        description=_(
            "Only letters, numbers, and simple punctuation are allowed."),
        required=True,
        constraint=name_validator)
    product = Choice(
        title=_("Product"),
        description=_("The product to which this milestone is associated"),
        vocabulary="Product")
    distribution = Choice(title=_("Distribution"),
        description=_("The distribution to which this milestone belongs."),
        vocabulary="Distribution")
    productseries = Choice(
        title=_("Product Series"),
        description=_("The product series for which this is a milestone."),
        vocabulary="FilteredProductSeries",
        required=False) # for now
    distrorelease = Choice(
        title=_("Distribution Release"),
        description=_(
            "The distribution release for which this is a milestone."),
        vocabulary="FilteredDistroRelease",
        required=False) # for now
    dateexpected = Date(title=_("Date Targeted"), required=False,
        description=_("Example: 2005-11-24"))
    visible = Bool(title=_("Active"), description=_("Whether or not this "
        "milestone should be shown in web forms for bug targeting."))
    target = Attribute("The product or distribution of this milestone.")
    series_target = Attribute(
        'The productseries or distrorelease of this milestone.')
    displayname = Attribute("A displayname for this milestone, constructed "
        "from the milestone name.")
    title = Attribute("A milestone context title for pages.")
    specifications = Attribute("A list of the specifications targeted to "
        "this milestone.")


class IMilestoneSet(Interface):
    def __iter__():
        """Return an iterator over all the milestones for a thing."""

    def get(milestoneid):
        """Get a milestone by its id.

        If the milestone with that ID is not found, a
        NotFoundError will be raised.
        """

    def getByNameAndProduct(self, name, product, default=None):
        """Get a milestone by its name and product.

        If no milestone is found, default will be returned. 
        """

    def getByNameAndDistribution(self, name, distribution, default=None):
        """Get a milestone by its name and distribution.

        If no milestone is found, default will be returned.
        """

