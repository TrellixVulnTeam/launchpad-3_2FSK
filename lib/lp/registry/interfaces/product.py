# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Interfaces including and related to IProduct."""

__metaclass__ = type

__all__ = [
    'InvalidProductName',
    'IProduct',
    'IProductProjectReviewRestricted',
    'IProductDriverRestricted',
    'IProductEditRestricted',
    'IProductPublic',
    'IProductReviewSearch',
    'IProductSet',
    'License',
    'LicenseStatus',
    'NoSuchProduct',
    'valid_sourceforge_project_name',
    ]


import re

from textwrap import dedent

from zope.interface import Interface, Attribute
from zope.schema import (
    Bool, Choice, Date, Datetime, Int, Object, Set, Text, TextLine)
from zope.schema.vocabulary import SimpleVocabulary
from lazr.enum import DBEnumeratedType, DBItem

from canonical.launchpad import _
from canonical.launchpad.fields import (
    Description, IconImageUpload, LogoImageUpload, MugshotImageUpload,
    ParticipatingPersonChoice, ProductBugTracker, ProductNameField,
    PublicPersonChoice, Summary, Title, URIField)
from lp.registry.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget)
from lp.app.interfaces.headings import IRootContext
from lp.code.interfaces.branchvisibilitypolicy import (
    IHasBranchVisibilityPolicy)
from lp.code.interfaces.hasbranches import IHasBranches, IHasMergeProposals
from lp.bugs.interfaces.bugtarget import (
    IBugTarget, IOfficialBugTagTargetPublic, IOfficialBugTagTargetRestricted)
from lp.registry.interfaces.karma import IKarmaContext
from canonical.launchpad.interfaces.launchpad import (
    IHasAppointedDriver, IHasDrivers, IHasExternalBugTracker, IHasIcon,
    IHasLogo, IHasMugshot, IHasSecurityContact, ILaunchpadUsage)
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.milestone import (
    ICanGetMilestonesDirectly, IHasMilestones)
from lp.registry.interfaces.announcement import IMakesAnnouncements
from lp.registry.interfaces.commercialsubscription import (
    ICommercialSubscription)
from lp.registry.interfaces.mentoringoffer import IHasMentoringOffers
from lp.registry.interfaces.pillar import IPillar
from lp.registry.interfaces.productrelease import IProductRelease
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.project import IProject
from lp.blueprints.interfaces.specificationtarget import (
    ISpecificationTarget)
from lp.blueprints.interfaces.sprint import IHasSprints
from lp.translations.interfaces.translationgroup import (
    ITranslationPolicy)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.name import name_validator
from canonical.launchpad.webapp.interfaces import NameLookupFailed
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from lazr.restful.interface import copy_field
from lazr.restful.declarations import (
    REQUEST_USER, call_with, collection_default_content,
    export_as_webservice_collection, export_as_webservice_entry,
    export_factory_operation, export_operation_as, export_read_operation,
    exported, operation_parameters, operation_returns_entry,
    operation_returns_collection_of, rename_parameters_as)


# This is based on the definition of <label> in RFC 1035, section
# 2.3.1, which is what SourceForge project names are based on.
re_valid_rfc1035_label = re.compile(
    '^[a-zA-Z](?:[a-zA-Z0-9-]{,61}[a-zA-Z0-9])?$')


def valid_sourceforge_project_name(project_name):
    """Is this is a valid SourceForge project name?

    Project names must be valid domain name components.

        >>> valid_sourceforge_project_name('mailman')
        True

        >>> valid_sourceforge_project_name('hop-2-hop')
        True

        >>> valid_sourceforge_project_name('quake3')
        True

    They cannot start with a number.

        >>> valid_sourceforge_project_name('1mailman')
        False

    Nor can they start or end with a hyphen.

        >>> valid_sourceforge_project_name('-mailman')
        False

        >>> valid_sourceforge_project_name('mailman-')
        False

    They must be between 1 and 63 characters in length.

        >>> valid_sourceforge_project_name('x' * 0)
        False

        >>> valid_sourceforge_project_name('x' * 1)
        True

        >>> valid_sourceforge_project_name('x' * 63)
        True

        >>> valid_sourceforge_project_name('x' * 64)
        False

    """
    return re_valid_rfc1035_label.match(project_name) is not None


def sourceforge_project_name_validator(project_name):
    """Raise a validation exception if the name is not valid.

        >>> sourceforge_project_name_validator('valid')
        True

        >>> sourceforge_project_name_validator(
        ...     '1nvalid') #doctest: +ELLIPSIS,+NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        LaunchpadValidationError: SourceForge project names...
    """
    if valid_sourceforge_project_name(project_name):
        return True
    else:
        raise LaunchpadValidationError(
            _(dedent("""
                SourceForge project names must begin with a letter (A
                to Z; case does not matter), followed by zero or more
                letters, numbers, or hyphens, then end with a letter
                or number. In total it must not be more than 63
                characters in length.""")))


class LicenseStatus(DBEnumeratedType):
    """The status of a project's license review."""

    OPEN_SOURCE = DBItem(
        10, "Open Source",
        u"This project&rsquo;s license is open source.")
    PROPRIETARY = DBItem(
        20, "Proprietary",
        u"This project&rsquo;s license is proprietary.")
    UNREVIEWED = DBItem(
        30, "Unreviewed",
        u"This project&rsquo;s license has not been reviewed.")
    UNSPECIFIED = DBItem(
        40, "Unspecified",
        u"This project&rsquo;s license has not been specified.")


class License(DBEnumeratedType):
    """Licenses under which a project's code can be released."""

    # Sort licenses alphabetically by their description.
    sort_order = (
        'ACADEMIC', 'APACHE', 'ARTISTIC', 'ARTISTIC_2_0',
        'BSD', 'COMMON_PUBLIC',
        'CC_BY', 'CC_BY_SA', 'CC_0', 'ECLIPSE',
        'EDUCATIONAL_COMMUNITY', 'AFFERO', 'GNU_GPL_V2', 'GNU_GPL_V3',
        'GNU_LGPL_V2_1', 'GNU_LGPL_V3', 'MIT', 'MPL', 'OPEN_SOFTWARE', 'PERL',
        'PHP', 'PUBLIC_DOMAIN', 'PYTHON', 'ZPL',
        'DONT_KNOW', 'OTHER_PROPRIETARY', 'OTHER_OPEN_SOURCE')

    ACADEMIC = DBItem(
        10, "Academic Free License",
        url='http://www.opensource.org/licenses/afl-3.0.php')
    AFFERO = DBItem(
        20, "GNU Affero GPL v3",
        url='http://www.opensource.org/licenses/agpl-v3.html')
    APACHE = DBItem(
        30, "Apache License",
        url='http://www.opensource.org/licenses/apache2.0.php')
    ARTISTIC = DBItem(
        40, "Artistic License 1.0",
        url='http://opensource.org/licenses/artistic-license-1.0.php')
    ARTISTIC_2_0 = DBItem(
        45, 'Artistic License 2.0',
        url='http://www.opensource.org/licenses/artistic-license-2.0.php')
    BSD = DBItem(
        50, "Simplified BSD License",
        url='http://www.opensource.org/licenses/bsd-license.php')
    COMMON_PUBLIC = DBItem(
        80, "Common Public License",
        url='http://www.opensource.org/licenses/cpl1.0.php')
    ECLIPSE = DBItem(
        90, "Eclipse Public License",
        url='http://www.opensource.org/licenses/eclipse-1.0.php')
    EDUCATIONAL_COMMUNITY = DBItem(
        100, "Educational Community License",
        url='http://www.opensource.org/licenses/ecl2.php')
    GNU_GPL_V2 = DBItem(
        130, "GNU GPL v2",
        url='http://www.opensource.org/licenses/gpl-2.0.php')
    GNU_GPL_V3 = DBItem(
        135, "GNU GPL v3",
        url='http://www.opensource.org/licenses/gpl-3.0.html')
    GNU_LGPL_V2_1 = DBItem(
        150, "GNU LGPL v2.1",
        url='http://www.opensource.org/licenses/lgpl-2.1.php')
    GNU_LGPL_V3 = DBItem(
        155, "GNU LGPL v3",
        url='http://www.opensource.org/licenses/lgpl-3.0.html')
    MIT = DBItem(
        160, "MIT / X / Expat License",
        url='http://www.opensource.org/licenses/mit-license.php')
    MPL = DBItem(
        170, "Mozilla Public License",
        url='http://www.opensource.org/licenses/mozilla1.1.php')
    OPEN_SOFTWARE = DBItem(
        190, "Open Software License v 3.0",
        url='http://www.opensource.org/licenses/osl-3.0.php')
    # XXX BarryWarsaw 2009-06-10 There is really no such thing as the "Perl
    # License".  See bug 326308 for details.  We can't remove this option
    # because of the existing data in production, however the plan is to hide
    # this choice from users during project creation as part of bug 333932.
    PERL = DBItem(
        200, "Perl License")
    PHP = DBItem(
        210, "PHP License",
        url='http://www.opensource.org/licenses/php.php')
    PUBLIC_DOMAIN = DBItem(
        220, "Public Domain",
        url='https://answers.launchpad.net/launchpad/+faq/564')
    PYTHON = DBItem(
        230, "Python License",
        url='http://www.opensource.org/licenses/PythonSoftFoundation.php')
    ZPL = DBItem(
        280, "Zope Public License",
        url='http://www.opensource.org/licenses/zpl.php')
    CC_BY = DBItem(
        300, 'Creative Commons - Attribution',
        url='http://creativecommons.org/about/licenses')
    CC_BY_SA = DBItem(
        310, 'Creative Commons - Attribution Share Alike',
        url='http://creativecommons.org/about/licenses')
    CC_0 = DBItem(
        320, 'Creative Commons - No Rights Reserved',
        url='http://creativecommons.org/about/cc0')
    # This is a placeholder "license" for users who know they want something
    # open source but haven't yet chosen a license for their project.  We do
    # not want to block them from registering their project, but this choice
    # will allow us to nag them later.
    DONT_KNOW = DBItem(3000, "I don't know yet")

    OTHER_PROPRIETARY = DBItem(1000, "Other/Proprietary")
    OTHER_OPEN_SOURCE = DBItem(1010, "Other/Open Source")


class IProductDriverRestricted(Interface):
    """`IProduct` properties which require launchpad.Driver permission."""

    def newSeries(owner, name, summary, branch=None, releasefileglob=None):
        """Creates a new `IProductSeries` for this `IProduct`.

        :param owner: The registrant of this series.
        :param name: The unique name of this series.
        :param summary: The summary of the purpose and focus of development
            of this series.
        :param branch: The bazaar branch that contains the code for
            this series.
        :param releasefileglob: The public URL pattern where release files can
            be automatically downloaded from and linked to this series.
        """


class IProductEditRestricted(IOfficialBugTagTargetRestricted,):
    """`IProduct` properties which require launchpad.Edit permission."""


class IProductProjectReviewRestricted(Interface):
    """`IProduct` properties which require launchpad.ProjectReview."""

    qualifies_for_free_hosting = exported(
        Bool(
            title=_("Qualifies for free hosting"),
            readonly=True,
            description=_(
                "Whether the project's licensing qualifies it for free "
                "use of launchpad.")))

    reviewer_whiteboard = exported(
        Text(
            title=_('Notes for the project reviewer'),
            required=False,
            description=_(
                "Notes on the project's license, editable only by reviewers "
                "(Admins and Commercial Admins).")))

    is_permitted = exported(
        Bool(
            title=_("Is Permitted"),
            readonly=True,
            description=_(
                "Whether the project's licensing qualifies for free "
                "hosting or the project has an up-to-date "
                "subscription.")))

    license_reviewed = exported(
        Bool(
            title=_('Project reviewed'),
            description=_("Whether or not this project has been reviewed. "
                          "If you looked at the project and how it uses "
                          "Launchpad, you reviewed it.")))

    license_approved = exported(
        Bool(
            title=_("Project approved"),
            description=_(
                "The project is legitimate and its license appears valid. "
                "Not applicable to 'Other/Proprietary'.")))


class IProductPublic(
    IBugTarget, ICanGetMilestonesDirectly, IHasAppointedDriver, IHasBranches,
    IHasBranchVisibilityPolicy, IHasDrivers, IHasExternalBugTracker, IHasIcon,
    IHasLogo, IHasMentoringOffers, IHasMergeProposals, IHasMilestones,
    IHasMugshot, IHasOwner, IHasSecurityContact, IHasSprints,
    ITranslationPolicy, IKarmaContext, ILaunchpadUsage, IMakesAnnouncements,
    IOfficialBugTagTargetPublic, IPillar, ISpecificationTarget):
    """Public IProduct properties."""

    # XXX Mark Shuttleworth 2004-10-12: Let's get rid of ID's in interfaces
    # unless we really need them. BradB says he can remove the need for them
    # in SQLObject soon.
    id = Int(title=_('The Project ID'))

    project = exported(
        ReferenceChoice(
            title=_('Part of'),
            required=False,
            vocabulary='Project',
            schema=IProject,
            description=_(
                'Super-project. In Launchpad, we can setup a special '
                '"project group" that is an overarching initiative that '
                'includes several related projects. For example, the Mozilla '
                'Project produces Firefox, Thunderbird and Gecko. This '
                'information is used to group those projects in a coherent '
                'way. If you make this project part of a group, the group '
                'preferences and decisions around bug tracking, translation '
                'and security policy will apply to this project.')),
        exported_as='project_group')

    owner = exported(
        ParticipatingPersonChoice(
            title=_('Maintainer'),
            required=True,
            vocabulary='ValidOwner',
            description=_("The person or team who maintains the project "
                          "information in Launchpad.")))

    registrant = exported(
        PublicPersonChoice(
            title=_('Registrant'),
            required=True,
            readonly=True,
            vocabulary='ValidPersonOrTeam',
            description=_("This person registered the project in "
                          "Launchpad.")))

    driver = exported(
        ParticipatingPersonChoice(
            title=_("Driver"),
            description=_(
                "This person or team will be able to set feature goals for "
                "and approve bug targeting or backporting for ANY major "
                "series in this project. You might want to leave this blank "
                "and just appoint a team for each specific series, rather "
                "than having one project team that does it all."),
            required=False, vocabulary='ValidPersonOrTeam'))

    drivers = Attribute(
        "Presents the drivers of this project as a list. A list is "
        "required because there might be a project driver and also a "
        "driver appointed in the overarching project group.")

    name = exported(
        ProductNameField(
            title=_('Name'),
            constraint=name_validator,
            description=_(
                "At least one lowercase letter or number, followed by "
                "letters, numbers, dots, hyphens or pluses. "
                "Keep this name short; it is used in URLs as shown above."
                )))

    displayname = exported(
        TextLine(
            title=_('Display Name'),
            description=_("""The name of the project as it would appear in a
                paragraph.""")),
        exported_as='display_name')

    title = exported(
        Title(
            title=_('Title'),
            description=_("The project title. Should be just a few words.")))

    summary = exported(
        Summary(
            title=_('Summary'),
            description=_("The summary should be a single short paragraph.")))

    description = exported(
        Description(
            title=_('Description'),
            required=False,
            description=_("""Include information on how to get involved with
                development. Don't repeat anything from the Summary.""")))

    datecreated = exported(
        Datetime(
            title=_('Date Created'),
            required=True, readonly=True,
            description=_("The date this project was created in Launchpad.")),
        exported_as='date_created')

    homepageurl = exported(
        URIField(
            title=_('Homepage URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'], allow_userinfo=False,
            description=_("""The project home page. Please include
                the http://""")),
        exported_as="homepage_url")

    wikiurl = exported(
        URIField(
            title=_('Wiki URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'], allow_userinfo=False,
            description=_("""The full URL of this project's wiki, if it has
                one. Please include the http://""")),
        exported_as='wiki_url')

    screenshotsurl = exported(
        URIField(
            title=_('Screenshots URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'], allow_userinfo=False,
            description=_("""The full URL for screenshots of this project,
                if available. Please include the http://""")),
        exported_as='screenshots_url')

    downloadurl = exported(
        URIField(
            title=_('Download URL'),
            required=False,
            allowed_schemes=['http', 'https', 'ftp'], allow_userinfo=False,
            description=_("""The full URL where downloads for this project
                are located, if available. Please include the http://""")),
        exported_as='download_url')

    programminglang = exported(
        TextLine(
            title=_('Programming Languages'),
            required=False,
            description=_("""A comma delimited list of programming
                languages used for this project.""")),
        exported_as='programming_language')

    sourceforgeproject = exported(
        TextLine(
            title=_('Sourceforge Project'),
            required=False,
            constraint=sourceforge_project_name_validator,
            description=_("""The SourceForge project name for
                this project, if it is in sourceforge.""")),
        exported_as='sourceforge_project')

    freshmeatproject = exported(
        TextLine(
            title=_('Freshmeat Project'),
            required=False, description=_("""The Freshmeat project name for
                this project, if it is in freshmeat.""")),
        exported_as='freshmeat_project')

    homepage_content = Text(
        title=_("Homepage Content"), required=False,
        description=_(
            "The content of this project's home page. Edit this and it will "
            "be displayed for all the world to see. It is NOT a wiki "
            "so you cannot undo changes."))

    icon = exported(
        IconImageUpload(
            title=_("Icon"), required=False,
            default_image_resource='/@@/product',
            description=_(
                "A small image of exactly 14x14 pixels and at most 5kb in "
                "size, that can be used to identify this project. The icon "
                "will be displayed next to the project name everywhere in "
                "Launchpad that we refer to the project and link to it.")))

    logo = exported(
        LogoImageUpload(
            title=_("Logo"), required=False,
            default_image_resource='/@@/product-logo',
            description=_(
                "An image of exactly 64x64 pixels that will be displayed in "
                "the heading of all pages related to this project. It should "
                "be no bigger than 50kb in size.")))

    mugshot = exported(
        MugshotImageUpload(
            title=_("Brand"), required=False,
            default_image_resource='/@@/product-mugshot',
            description=_(
                "A large image of exactly 192x192 pixels, that will be "
                "displayed on this project's home page in Launchpad. It "
                "should be no bigger than 100kb in size.")),
        exported_as='brand')

    autoupdate = Bool(
        title=_('Automatic update'),
        description=_("Whether or not this project's attributes are "
                      "updated automatically."))

    private_bugs = Bool(title=_('Private bugs'),
                        description=_(
                            "Whether or not bugs reported into this project "
                            "are private by default."))
    licenses = exported(
        Set(title=_('Licenses'),
            value_type=Choice(vocabulary=License)))

    license_info = exported(
        Description(
            title=_('Description of additional licenses'),
            required=False,
            description=_(
                "Description of licenses that do not appear in the list "
                "above.")))

    bugtracker = exported(
        ProductBugTracker(
            title=_('Bugs are tracked'),
            vocabulary="BugTracker"),
        exported_as='bug_tracker')

    sourcepackages = Attribute(_("List of packages for this product"))

    distrosourcepackages = Attribute(_("List of distribution packages for "
        "this product"))

    series = exported(
        CollectionField(value_type=Object(schema=IProductSeries)))

    development_focus = exported(
        ReferenceChoice(
            title=_('Development focus'), required=True,
            vocabulary='FilteredProductSeries',
            schema=IProductSeries,
            description=_('The "trunk" series where development is focused')))

    name_with_project = Attribute(_("Returns the product name prefixed "
        "by the project name, if a project is associated with this "
        "product; otherwise, simply returns the product name."))

    releases = exported(
        CollectionField(
            title=_("An iterator over the ProductReleases for this product."),
            readonly=True,
            value_type=Reference(schema=IProductRelease)))

    translation_focus = exported(
        ReferenceChoice(
            title=_("Translation Focus"), required=False,
            vocabulary='FilteredProductSeries',
            schema=IProductSeries,
            description=_(
                'The ProductSeries where translations are focused.')))

    translatable_packages = Attribute(
        "A list of the source packages for this product that can be "
        "translated sorted by distroseries.name and sourcepackage.name.")

    translatable_series = Attribute(
        "A list of the series of this product for which we have translation "
        "templates.")

    obsolete_translatable_series = Attribute("""
        A list of the series of this product with obsolete translation
        templates.""")

    primary_translatable = Attribute(
        "The best guess we have for what new translators will want to "
        "translate for a given product: the latest series for which we have "
        "templates, and failing that, an Ubuntu package.")

    translationgroups = Attribute("The list of applicable translation "
        "groups for a product. There can be several: one from the product, "
        "and potentially one from the project, too.")

    aggregatetranslationpermission = Attribute("The translation permission "
        "that applies to translations in this product, based on the "
        "permissions that apply to the product as well as its project.")

    commercial_subscription = exported(
        Reference(
            ICommercialSubscription,
            title=_("Commercial subscriptions"),
            description=_(
                "An object which contains the timeframe and the voucher "
                "code of a subscription.")))

    commercial_subscription_is_due = exported(
            Bool(
                title=_("Commercial subscription is due"),
                readonly=True,
                description=_(
                    "Whether the project's licensing requires a new "
                    "commercial subscription to use launchpad.")))

    license_status = Attribute("""
        Whether the license is OPENSOURCE, UNREVIEWED, or PROPRIETARY.""")

    remote_product = exported(
        TextLine(
            title=_('Remote project'), required=False,
            description=_(
                "The ID of this project on its remote bug tracker.")))

    def redeemSubscriptionVoucher(voucher, registrant, purchaser,
                                  subscription_months, whiteboard=None,
                                  current_datetime=None):
        """Redeem a voucher and extend the subscription expiration date.

        The voucher must have already been verified to be redeemable.
        :param voucher: The voucher id as tracked in the external system.
        :param registrant: Who is redeeming the voucher.
        :param purchaser: Who purchased the voucher.  May not be known.
        :param subscription_months: integer indicating the number of months
            the voucher is for.
        :param whiteboard: Notes for this activity.
        :param current_datetime: Current time.  Will be datetime.now() if not
            specified.
        :return: None
        """

    def getLatestBranches(quantity=5):
        """Latest <quantity> branches registered for this product."""

    def getPackage(distroseries):
        """Return a package in that distroseries for this product."""

    @operation_parameters(
        name=TextLine(title=_("Name"), required=True))
    @operation_returns_entry(IProductSeries)
    @export_read_operation()
    def getSeries(name):
        """Return the series for this product for the given name, or None."""

    @operation_parameters(
        version=TextLine(title=_("Version"), required=True))
    @operation_returns_entry(IProductRelease)
    @export_read_operation()
    def getRelease(version):
        """Return the release for this product that has the version given."""

    def getMilestonesAndReleases():
        """Return all the milestones and releases for this product."""

    def packagedInDistros():
        """Returns the distributions this product has been packaged in."""

    def userCanEdit(user):
        """Can the user edit this product?"""

    def getLinkedBugWatches():
        """Return all the bug watches that are linked to this Product.

        Being linked, means that a bug watch having the same bug tracker
        as this Product is using, is linked to a bug task targeted to
        this Product.
        """

    @operation_parameters(
        include_inactive=Bool(title=_("Include inactive"),
                              required=False, default=False))
    @export_read_operation()
    @export_operation_as('get_timeline')
    def getTimeline(include_inactive):
        """Return basic timeline data useful for creating a diagram."""


class IProduct(IProductEditRestricted, IProductProjectReviewRestricted,
               IProductDriverRestricted, IProductPublic, IRootContext,
               IStructuralSubscriptionTarget):
    """A Product.

    The Launchpad Registry describes the open source world as Projects and
    Products. Each Project may be responsible for several Products.
    For example, the Mozilla Project has Firefox, Thunderbird and The
    Mozilla App Suite as Products, among others.
    """

    export_as_webservice_entry('project')

# Fix cyclic references.
IProject['products'].value_type = Reference(IProduct)
IProductRelease['product'].schema = IProduct

# Patch the official_bug_tags field to make sure that it's
# writable from the API, and not readonly like its definition
# in IHasBugs.
writable_obt_field = copy_field(IProduct['official_bug_tags'])
writable_obt_field.readonly = False
IProduct._v_attrs['official_bug_tags'] = writable_obt_field


class IProductSet(Interface):
    export_as_webservice_collection(IProduct)

    title = Attribute("The set of Products registered in the Launchpad")

    people = Attribute(
        "The PersonSet, placed here so we can easily render "
        "the list of latest teams to register on the /projects/ page.")

    all_active = Attribute(
        "All the active products, sorted newest first.")

    def __iter__():
        """Return an iterator over all the active products."""

    def __getitem__(name):
        """Get a product by its name."""

    def get(productid):
        """Get a product by its id.

        If the product can't be found a NotFoundError will be
        raised.
        """

    def getByName(name, ignore_inactive=False):
        """Return the product with the given name, ignoring inactive products
        if ignore_inactive is True.

        Return None if there is no such product.
        """

    def getProductsWithBranches(num_products=None):
        """Return an iterator over all active products that have branches.

        If num_products is not None, then the first `num_products` are
        returned.
        """

    @call_with(owner=REQUEST_USER)
    @rename_parameters_as(
        displayname='display_name', project='project_group',
        homepageurl='home_page_url', screenshotsurl='screenshots_url',
        freshmeatproject='freshmeat_project', wikiurl='wiki_url',
        downloadurl='download_url',
        sourceforgeproject='sourceforge_project',
        programminglang='programming_lang')
    @export_factory_operation(
        IProduct, ['name', 'displayname', 'title', 'summary', 'description',
                   'project', 'homepageurl', 'screenshotsurl',
                   'downloadurl', 'freshmeatproject', 'wikiurl',
                   'sourceforgeproject', 'programminglang',
                   'license_reviewed', 'licenses', 'license_info',
                   'registrant'])
    @export_operation_as('new_project')
    def createProduct(owner, name, displayname, title, summary,
                      description=None, project=None, homepageurl=None,
                      screenshotsurl=None, wikiurl=None,
                      downloadurl=None, freshmeatproject=None,
                      sourceforgeproject=None, programminglang=None,
                      license_reviewed=False, mugshot=None, logo=None,
                      icon=None, licenses=None, license_info=None,
                      registrant=None):
        """Create and return a brand new Product.

        See `IProduct` for a description of the parameters.
        """

    @operation_parameters(
        search_text=TextLine(title=_("Search text")),
        active=Bool(title=_("Is the project active")),
        license_reviewed=Bool(title=_("Is the project license reviewed")),
        licenses = Set(title=_('Licenses'),
                       value_type=Choice(vocabulary=License)),
        license_info_is_empty=Bool(title=_("License info is empty")),
        has_zero_licenses=Bool(title=_("Has zero licenses")),
        created_after=Date(title=_("Created after date")),
        created_before=Date(title=_("Created before date")),
        subscription_expires_after=Date(
            title=_("Subscription expires after")),
        subscription_expires_before=Date(
            title=_("Subscription expired before")),
        subscription_modified_after=Date(
            title=_("Subscription modified after")),
        subscription_modified_before=Date(
            title=_("Subscription modified before"))
        )
    @operation_returns_collection_of(IProduct)
    @export_read_operation()
    @export_operation_as('licensing_search')
    def forReview(search_text=None,
                  active=None,
                  license_reviewed=None,
                  licenses=None,
                  license_info_is_empty=None,
                  has_zero_licenses=None,
                  created_after=None,
                  created_before=None,
                  subscription_expires_after=None,
                  subscription_expires_before=None,
                  subscription_modified_after=None,
                  subscription_modified_before=None):
        """Return an iterator over products that need to be reviewed."""

    @collection_default_content()
    @operation_parameters(text=TextLine(title=_("Search text")))
    @operation_returns_collection_of(IProduct)
    @export_read_operation()
    def search(text=None, soyuz=None,
               rosetta=None, malone=None,
               bazaar=None):
        """Search through the Registry database for products that match the
        query terms. text is a piece of text in the title / summary /
        description fields of product. soyuz, bazaar, malone etc are
        hints as to whether the search should be limited to products
        that are active in those Launchpad applications."""


    @operation_returns_collection_of(IProduct)
    @call_with(quantity=None)
    @export_read_operation()
    def latest(quantity=5):
        """Return the latest projects registered in Launchpad.

        If the quantity is not specified or is a value that is not 'None'
        then the set of projects returned is limited to that value (the
        default quantity is 5).  If quantity is 'None' then all projects are
        returned.  For the web service it is not possible to specify the
        quantity, so all projects are returned, latest first.
        """

    def getTranslatables():
        """Return an iterator over products that have translatable resources.

        Skips products that are not configured to be translated in
        Launchpad, as well as non-active ones.
        """

    def featuredTranslatables(maximumproducts=8):
        """Return an iterator over a random sample of translatable products.

        Similar to `getTranslatables`, except the number of results is
        limited and they are randomly chosen.

        :param maximum_products: Maximum number of products to be
            returned.
        :return: An iterator over active, translatable products.
        """
        # XXX JeroenVermeulen 2008-07-31 bug=253583: this is not
        # currently used!

    def count_all():
        """Return a count of the total number of products registered in
        Launchpad."""

    def count_translatable():
        """Return a count of the number of products that have
        upstream-oriented translations configured in Rosetta."""

    def count_buggy():
        """Return the number of products that have bugs associated with them
        in Launchpad."""

    def count_featureful():
        """Return the number of products that have specs associated with
        them in Blueprint."""

    def count_reviewed():
        """Return a count of the number of products in the Launchpad that
        are both active and reviewed."""

    def count_answered():
        """Return the number of projects that have questions and answers
        associated with them.
        """

    def count_codified():
        """Return the number of projects that have branches associated with
        them.
        """

    def getProductsWithNoneRemoteProduct(bugtracker_type=None):
        """Get all the IProducts having a `remote_product` of None

        The result can be filtered to only return Products associated
        with a given bugtracker type.
        """

    def getSFLinkedProductsWithNoneRemoteProduct(self):
        """Get IProducts with a sourceforge project and no remote_product."""


emptiness_vocabulary = SimpleVocabulary.fromItems(
        [('Empty', True), ('Not Empty', False)])


class IProductReviewSearch(Interface):
    """A search form for products being reviewed."""

    search_text = TextLine(
      title=_('Search text'),
      description=_("Search text in the product's name, displayname, title, "
                    "summary, and description."),
      required=False)

    active = Choice(
        title=_('Active'), values=[True, False],
        required=False, default=True)

    license_reviewed = Choice(
        title=_('Project Reviewed'), values=[True, False],
        required=False, default=False)

    license_approved = Choice(
        title=_('Project Approved'), values=[True, False],
        required=False, default=False)

    license_info_is_empty = Choice(
        title=_('Description of additional licenses'),
        description=_('Either this field or any one of the selected licenses'
                      ' must match.'),
        vocabulary=emptiness_vocabulary, required=False, default=None)

    licenses = Set(
        title=_('Licenses'),
        value_type=Choice(vocabulary=License),
        required=False,
        default=set())

    has_zero_licenses = Choice(
        title=_('Or has no license specified'),
        values=[True, False], required=False)

    created_after = Date(title=_("Created between"), required=False)

    created_before = Date(title=_("and"), required=False)

    subscription_expires_after = Date(
        title=_("Subscription expires between"), required=False)

    subscription_expires_before = Date(
        title=_("and"), required=False)

    subscription_modified_after = Date(
        title=_("Subscription modified between"), required=False)

    subscription_modified_before = Date(
        title=_("and"), required=False)


class NoSuchProduct(NameLookupFailed):
    """Raised when we try to find a product that doesn't exist."""

    _message_prefix = "No such product"


class InvalidProductName(LaunchpadValidationError):

    def __init__(self, name):
        self.name = name
        LaunchpadValidationError.__init__(
            self, "Invalid name for product: %s." % (name,))


# Fix circular imports.
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage)
IDistributionSourcePackage['upstream_product'].schema = IProduct
