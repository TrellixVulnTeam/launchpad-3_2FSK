# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Project-related interfaces for Launchpad."""

__metaclass__ = type

__all__ = [
    'IProject',
    'IProjectPublic',
    'IProjectSeries',
    'IProjectSet',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, Int, Object, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import (
    PublicPersonChoice, Summary, Title, URIField)
from lp.app.interfaces.rootcontext import IRootContext
from lp.code.interfaces.branchvisibilitypolicy import (
    IHasBranchVisibilityPolicy)
from lp.code.interfaces.hasbranches import IHasBranches, IHasMergeProposals
from lp.bugs.interfaces.bugtarget import IHasBugs
from lp.registry.interfaces.karma import IKarmaContext
from canonical.launchpad.interfaces.launchpad import (
    IHasAppointedDriver, IHasDrivers, IHasIcon, IHasLogo, IHasMugshot)
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.mentoringoffer import IHasMentoringOffers
from lp.registry.interfaces.milestone import (
    ICanGetMilestonesDirectly, IHasMilestones)
from lp.registry.interfaces.announcement import IMakesAnnouncements
from lp.registry.interfaces.pillar import IPillar
from lp.blueprints.interfaces.specificationtarget import (
    IHasSpecifications)
from lp.blueprints.interfaces.sprint import IHasSprints
from lp.translations.interfaces.translationgroup import (
    IHasTranslationGroup)
from canonical.launchpad.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget)
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.fields import (
    IconImageUpload, LogoImageUpload, MugshotImageUpload, PillarNameField)

from lazr.restful.fields import CollectionField, Reference
from lazr.restful.declarations import (
    collection_default_content, export_as_webservice_collection,
    export_as_webservice_entry, export_read_operation, exported,
    operation_parameters, operation_returns_collection_of)


class ProjectNameField(PillarNameField):

    @property
    def _content_iface(self):
        return IProject


class IProjectPublic(
    ICanGetMilestonesDirectly, IHasAppointedDriver, IHasBranches, IHasBugs,
    IHasDrivers, IHasBranchVisibilityPolicy, IHasIcon, IHasLogo,
    IHasMentoringOffers, IHasMergeProposals, IHasMilestones, IHasMugshot,
    IHasOwner, IHasSpecifications, IHasSprints, IHasTranslationGroup,
    IMakesAnnouncements, IKarmaContext, IPillar, IRootContext):
    """Public IProject properties."""

    id = Int(title=_('ID'), readonly=True)

    owner = exported(
        PublicPersonChoice(
            title=_('Maintainer'),
            required=True,
            vocabulary='ValidOwner',
            description=_("Project group owner. Must be either a "
                          "Launchpad Person or Team.")))

    registrant = exported(
        PublicPersonChoice(
            title=_('Registrant'),
            required=True,
            readonly=True,
            vocabulary='ValidPersonOrTeam',
            description=_("Project group registrant. Must be a valid "
                          "Launchpad Person.")))

    name = exported(
        ProjectNameField(
            title=_('Name'),
            required=True,
            description=_(
                "A unique name, used in URLs, identifying the project "
                "group.  All lowercase, no special characters. "
                "Examples: apache, mozilla, gimp."),
            constraint=name_validator))

    displayname = exported(
        TextLine(
            title=_('Display Name'),
            description=_(
                "Appropriately capitalised, "
                'and typically ending in "Project". '
                "Examples: the Apache Project, the Mozilla Project, "
                "the Gimp Project.")),
        exported_as="display_name")

    title = exported(
        Title(
            title=_('Title'),
            description=_("The full name of the project group, "
                          "which can contain spaces, special characters, "
                          "etc.")))

    summary = exported(
        Summary(
            title=_('Project Group Summary'),
            description=_(
                "A brief (one-paragraph) summary of the project group.")))

    description = exported(
        Text(
            title=_('Description'),
            description=_("A detailed description of the project group, "
                          "including details like when it was founded, "
                          "how many contributors there are, "
                          "and how it is organised and coordinated.")))

    datecreated = exported(
        Datetime(
            title=_('Date Created'),
            description=_(
                "The date this project group was created in Launchpad."),
            readonly=True),
        exported_as="date_created")

    driver = exported(
        PublicPersonChoice(
            title=_("Driver"),
            description=_(
                "This is a project group-wide appointment. Think carefully "
                "here! This person or team will be able to set feature goals "
                "and approve bug targeting and backporting for ANY series in "
                "ANY project in this group. You can also appoint drivers "
                "at the level of a specific project or series. So you may "
                "just want to leave this space blank, and instead let the "
                "individual projects and series have drivers."),
            required=False, vocabulary='ValidPersonOrTeam'))

    homepageurl = exported(
        URIField(
            title=_('Homepage URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'],
            allow_userinfo=False,
            description=_(
                "The project group home page. "
                "Please include the http://")),
        exported_as="homepage_url")

    wikiurl = exported(
        URIField(
            title=_('Wiki URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'],
            allow_userinfo=False,
            description=_("The URL of this project group's wiki, "
                          "if it has one. Please include the http://")),
        exported_as="wiki_url"
        )

    lastdoap = TextLine(
        title=_('Last-parsed RDF fragment'),
        description=_("The last RDF fragment for this "
                      "entity that we received and parsed, or "
                      "generated."),
        required=False)

    sourceforgeproject = exported(
        TextLine(
            title=_("SourceForge Project Name"),
            description=_("The SourceForge project name for this "
                          "project group, if it is in SourceForge."),
            required=False),
        exported_as="sourceforge_project")

    freshmeatproject = exported(
        TextLine(
            title=_("Freshmeat Project Name"),
            description=_("The Freshmeat project name for this "
                          "project group, if it is in Freshmeat."),
            required=False),
        exported_as="freshmeat_project")

    homepage_content = exported(
        Text(
            title=_("Homepage Content"), required=False,
            description=_(
                "The content of this project group's home page. Edit this "
                "and it will be displayed for all the world to see. It is "
                "NOT a wiki so you cannot undo changes.")))

    icon = exported(
        IconImageUpload(
            title=_("Icon"), required=False,
            default_image_resource='/@@/project',
            description=_(
                "A small image of exactly 14x14 pixels and at most 5kb in "
                "size, that can be used to identify this project group. The "
                "icon will be displayed in Launchpad everywhere that we link "
                "to this project group. For example in listings or tables of "
                "active project groups.")))

    logo = exported(
        LogoImageUpload(
            title=_("Logo"), required=False,
            default_image_resource='/@@/project-logo',
            description=_(
                "An image of exactly 64x64 pixels that will be displayed in "
                "the heading of all pages related to this project group. It "
                "should be no bigger than 50kb in size.")))

    mugshot = exported(
        MugshotImageUpload(
            title=_("Brand"), required=False,
            default_image_resource='/@@/project-mugshot',
            description=_(
                "A large image of exactly 192x192 pixels, that will be "
                "displayed on this project group's home page in Launchpad. "
                "It should be no bigger than 100kb in size. ")))

    reviewed = exported(
        Bool(
            title=_('Reviewed'), required=False,
            description=_("Whether or not this project group has been "
                          "reviewed.")))

    bounties = Attribute(
        _("The bounties that are related to this project group."))

    bugtracker = exported(
        Choice(title=_('Bug Tracker'), required=False,
               vocabulary='BugTracker',
               description=_(
                "The bug tracker the projects in this project group use.")),
        exported_as="bug_tracker")

    # products.value_type will be set to IProduct once IProduct is defined.
    products = exported(
        CollectionField(
            title=_('List of active projects for this project group.'),
            value_type=Reference(Interface)),
        exported_as="projects")

    bug_reporting_guidelines = exported(
        Text(
            title=(
                u"If I\N{right single quotation mark}m reporting a bug, "
                u"I should include, if possible"),
            description=(
                u"These guidelines will be shown to "
                "anyone reporting a bug."),
            required=False,
            max_length=50000))

    def getProduct(name):
        """Get a product with name `name`."""

    def ensureRelatedBounty(bounty):
        """Ensure that the bounty is linked to this project group.

        Return None.
        """

    def translatables():
        """Return an iterator over products that have resources translatables.

        It also should have IProduct.official_rosetta flag set.
        """

    def hasProducts():
        """Returns True if a project has products associated with it, False
        otherwise.
        """

    def getSeries(series_name):
        """Return a ProjectSeries object with name `series_name`."""


class IProject(IProjectPublic, IStructuralSubscriptionTarget):
    """A Project."""

    export_as_webservice_entry('project_group')


# Interfaces for set

class IProjectSet(Interface):
    """The collection of projects."""

    export_as_webservice_collection(IProject)

    title = Attribute('Title')

    def __iter__():
        """Return an iterator over all the projects."""

    def __getitem__(name):
        """Get a project by its name."""

    def get(projectid):
        """Get a project by its id.

        If the project can't be found a NotFoundError will be raised.
        """

    def getByName(name, default=None, ignore_inactive=False):
        """Return the project with the given name, ignoring inactive projects
        if ignore_inactive is True.

        Return the default value if there is no such project.
        """

    def new(name, displayname, title, homepageurl, summary, description,
            owner, mugshot=None, logo=None, icon=None, registrant=None):
        """Create and return a project with the given arguments.

        For a description of the parameters see `IProject`.
        """

    def count_all():
        """Return the total number of projects registered in Launchpad."""

    @collection_default_content()
    @operation_parameters(text=TextLine(title=_("Search text")))
    @operation_returns_collection_of(IProject)
    @export_read_operation()
    def search(text=None, soyuz=None,
                     rosetta=None, malone=None,
                     bazaar=None,
                     search_products=True):
        """Search through the Registry database for projects that match the
        query terms. text is a piece of text in the title / summary /
        description fields of project (and possibly product). soyuz,
        bazaar, malone etc are hints as to whether the search should
        be limited to projects that are active in those Launchpad
        applications."""

    def forReview():
        """Return a list of Projects which need review, or which have
        products that needs review."""


class IProjectSeries(IHasSpecifications, IHasAppointedDriver, IHasIcon,
                     IHasOwner):
    """Interface for ProjectSeries.

    This class provides the specifications related to a "virtual project
    series", i.e., to those specifactions that are assigned to a series
    of a product which is part of this project.
    """
    name = TextLine(title=u'The name of the product series.',
                    required=True, readonly=True,
                    constraint=name_validator)

    displayname = TextLine(title=u'Alias for name.',
                           required=True, readonly=True,
                           constraint=name_validator)

    title = TextLine(title=u'The title for this project series.',
                     required=True, readonly=True)

    project = Object(schema=IProject,
                     title=u"The project this series belongs to",
                     required=True, readonly=True)

