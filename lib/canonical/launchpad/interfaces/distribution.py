# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Interfaces including and related to IDistribution."""

__metaclass__ = type

__all__ = [
    'IDistribution',
    'IDistributionSet',
    'IDistroPackageFinder',
    ]

from zope.schema import Choice, Int, TextLine
from zope.interface import Interface, Attribute
from zope.i18nmessageid import MessageIDFactory

from canonical.launchpad.fields import Title, Summary, Description
from canonical.launchpad.interfaces import (
    IHasOwner, IBugTarget, ISpecificationTarget, ITicketTarget)

_ = MessageIDFactory('launchpad')

class IDistribution(IHasOwner, IBugTarget, ISpecificationTarget,
    ITicketTarget):

    """An operating system distribution."""

    id = Attribute("The distro's unique number.")
    name = TextLine(
        title=_("Name"),
        description=_("The distro's name."), required=True)
    displayname = TextLine(
        title=_("Display Name"),
        description=_("The displayable name of the distribution."),
        required=True)
    title = Title(
        title=_("Title"),
        description=_("The distro's title."), required=True)
    summary = Summary(
        title=_("Summary"),
        description=_(
            "The distribution summary. A short paragraph"
            "describing the goals and highlights of the distro."),
        required=True)
    description = Description(
        title=_("Description"),
        description=_("The distro's description."),
        required=True)
    domainname = TextLine(
        title=_("Domain name"),
        description=_("The distro's domain name."), required=True)
    translationgroup = Choice(
        title = _("Translation group"),
        description = _("The translation group for this product. This group "
            "is made up of a set of translators for all the languages "
            "approved by the group manager. These translators then have "
            "permission to edit the groups translation files, based on the "
            "permission system selected below."),
        required=False,
        vocabulary='TranslationGroup')
    translationpermission = Choice(
        title=_("Translation Permission System"),
        description=_("The permissions this group requires for "
            "translators. If 'Open', then anybody can edit translations "
            "in any language. If 'Reviewed', then anybody can make "
            "suggestions but only the designated translators can edit "
            "or confirm translations. And if 'Closed' then only the "
            "designated translation group will be able to touch the "
            "translation files at all."),
        required=True,
        vocabulary='TranslationPermission')
    owner = Int(
        title=_("Owner"),
        description=_("The distro's owner."), required=True)
    members = Choice(
        title=_("Members"),
        description=_("The distro's members team."), required=True,
        vocabulary='ValidPersonOrTeam')
    lucilleconfig = TextLine(
        title=_("Lucille Config"),
        description=_("The Lucille Config."), required=False)

    releases = Attribute("DistroReleases inside this Distributions")
    bounties = Attribute(_("The bounties that are related to this distro."))
    bugtasks = Attribute("The bug tasks filed in this distro.")
    bugCounter = Attribute("The distro bug counter")
    milestones = Attribute(_(
        "The release milestones associated with this distribution. "
        "Release milestones are primarily used by the QA team to assign "
        "specific bugs for fixing by specific milestones."))


    # properties
    currentrelease = Attribute(
        "The current development release of this distribution. Note that "
        "all maintainerships refer to the current release. When people ask "
        "about the state of packages in the distribution, we should "
        "interpret that query in the context of the currentrelease."
        )

    open_cve_bugtasks = Attribute(
        "Any bugtasks on this distribution that are for bugs with "
        "CVE references, and are still open.")

    resolved_cve_bugtasks = Attribute(
        "Any bugtasks on this distribution that are for bugs with "
        "CVE references, and are resolved.")

    def traverse(name):
        """Traverse the distribution. Check for special names, and return
        appropriately, otherwise use __getitem__"""

    def __getitem__(name):
        """Returns a DistroRelease that matches name, or raises and
        exception if none exists."""

    def __iter__():
        """Iterate over the distribution releases for this distribution."""

    def getDevelopmentReleases():
        """Return the DistroReleases which are marked as in development."""

    def getRelease(name_or_version):
        """Return the source package release with the name or version
        given.
        """

    def getSourcePackage(self, name):
        """Return the source package with the name given."""

    def getMilestone(name):
        """Return a milestone with the given name for this distribution, or
        None.
        """

    def ensureRelatedBounty(bounty):
        """Ensure that the bounty is linked to this distribution. Return
        None.
        """

    def getDistroReleaseAndPocket(distroreleasename):
        """Return a (distrorelease,pocket) tuple which is the given textual
        distroreleasename in this distribution."""

class IDistributionSet(Interface):
    """Interface for DistrosSet"""

    title = Attribute('Title')

    def __iter__():
        """Iterate over distributions."""

    def __getitem__(name):
        """Retrieve a distribution by name"""

    def count():
        """Return the number of distributions in the system."""

    def get(distributionid):
        """Return the IDistribution with the given distributionid."""

    def getByName(distroname):
        """Return the IDistribution with the given name."""

    def new(name, displayname, title, description, summary, domainname,
            members, owner):
        """Creaste a new distribution."""


class IDistroPackageFinder(Interface):
    """A tool to find packages in a distribution."""

